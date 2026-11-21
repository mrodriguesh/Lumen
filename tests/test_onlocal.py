"""“Iniciar Open Notebook” (lumen/onlocal.py): ordem, reaproveitamento, porta ocupada e clique repetido, com os serviços
simulados (nenhum processo é iniciado aqui; a partida de verdade é conferida à parte, com um banco descartável)."""
import inspect
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests  # noqa: F401
from lumen import AppError, onlocal as on

PORT = {"db": on.DB, "api": on.API, "ui": on.UI}


class Local(unittest.TestCase):
    def setUp(self):
        on._run.update(active=False, error="", tied=False, steps=[])
        self.cfg = {"opennotebook_url": "http://127.0.0.1:5055", "opennotebook_ui": on.UI}
        self.up, self.foreign, self.spawned, self.dead = set(), set(), [], set()

        def spawn(name, args, cwd, env):
            self.spawned.append((name, args, Path(cwd), env))
            if name not in self.dead:
                self.up.add(name)
            return mock.Mock(poll=lambda: 1 if name in self.dead else None)

        class Inline:  # a partida roda na hora, na própria thread do teste
            def __init__(self, target, daemon):
                self.start = target

        for name, fake in {
            "_busy": lambda url: url in self.foreign or any(PORT[k] == url for k in self.up if k in PORT),
            "_is_db": lambda: "db" in self.up, "_db_status": lambda: "online" if "api" in self.up else None,
            "is_ui": lambda url=on.UI, api=on.API: "ui" in self.up, "_worker_running": lambda: "worker" in self.up,
            "_spawn": spawn, "_owner": lambda url: "node", "_wait": lambda ok, seconds, proc=None: ok(),
            "available": lambda cfg: cfg["opennotebook_url"] == on.API, "_tool": lambda name: name,
            "_dotenv": lambda: {"SURREAL_USER": "usuario", "SURREAL_PASSWORD": "segredo"},
        }.items():
            p = mock.patch.object(on, name, fake)
            p.start()
            self.addCleanup(p.stop)
        for target, fake in ((on.threading, {"Thread": Inline}), (on.time, {"sleep": lambda s: None})):
            p = mock.patch.multiple(target, **fake)
            p.start()
            self.addCleanup(p.stop)

    def states(self):
        return {s["id"]: s["state"] for s in on.status()["steps"]}

    def test_starts_everything_in_order_on_loopback_without_secrets_in_arguments(self):
        run = on.start(self.cfg)
        self.assertEqual((run["active"], run["error"]), (False, ""))
        self.assertEqual([s[0] for s in self.spawned], ["db", "api", "worker", "ui"])
        self.assertEqual(self.states(), dict.fromkeys(("db", "api", "worker", "ui"), "started"))
        by = {s[0]: s for s in self.spawned}
        self.assertEqual(by["db"][1][1:4], ["start", "--bind", "127.0.0.1:8000"])
        self.assertEqual(by["db"][3], {"SURREAL_USER": "usuario", "SURREAL_PASS": "segredo"})  # credenciais só no ambiente
        self.assertEqual(by["api"][1][1:], ["run", "--env-file", ".env", "run_api.py"])
        self.assertEqual((by["api"][2], by["api"][3]["API_RELOAD"], by["api"][3]["API_HOST"]), (on.REPO, "false", "127.0.0.1"))
        self.assertEqual(by["worker"][1][1:], ["run", "--env-file", ".env", "python", "-m", "surreal_commands.cli.worker", "--import-modules", "commands"])
        self.assertEqual(by["worker"][3], {"PYTHONPATH": str(on.REPO), "PYTHONIOENCODING": "utf-8"})
        self.assertEqual((by["ui"][1][1:], by["ui"][2]), (["run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"], on.REPO / "frontend"))
        for _name, args, _cwd, _env in self.spawned:
            self.assertIsInstance(args, list)
            self.assertNotIn("segredo", " ".join(args))

    def test_reuses_what_is_running_and_starts_only_what_is_missing(self):
        self.up = {"db", "api", "worker", "ui"}
        on.start(self.cfg)
        self.assertEqual((self.spawned, self.states()), ([], dict.fromkeys(("db", "api", "worker", "ui"), "reused")))
        self.assertEqual(on.view(self.cfg)["missing"], [])
        self.up = {"db", "api"}
        self.assertEqual(on.view(self.cfg)["missing"], ["Worker", "Interface"])
        on.start(self.cfg)
        self.assertEqual([s[0] for s in self.spawned], ["worker", "ui"])
        on.start(self.cfg)  # de novo, com tudo de pé: nada duplicado
        self.assertEqual(len(self.spawned), 2)

    def test_port_taken_by_another_program_is_an_error_and_nothing_is_touched(self):
        self.foreign = {on.API}
        run = on.start(self.cfg)
        self.assertEqual([s[0] for s in self.spawned], ["db"])  # parou na API: worker e interface nem tentam
        self.assertEqual((self.states()["api"], self.states()["ui"]), ("failed", "pending"))
        for part in ("5055", "node", "API", "Nada foi encerrado"):
            self.assertIn(part, run["error"])
        source = inspect.getsource(on)
        for banned in (".kill(", ".terminate(", "taskkill", "Stop-Process", "shell=True"):
            self.assertNotIn(banned, source)  # este módulo não encerra processo nenhum nem usa shell

    def test_ui_on_port_3000_of_another_app_starts_on_a_free_port_and_leaves_the_other_alone(self):
        self.up, self.foreign = {"db", "api", "worker"}, {on.UI}
        with mock.patch.object(on, "remember_ui") as saved:
            run = on.start(self.cfg)
        self.assertEqual((run["error"], self.states()["ui"]), ("", "started"))
        (name, args, _cwd, _env), = self.spawned
        self.assertEqual((name, args[-2:]), ("ui", ["--port", "3001"]))  # a 3000 não é tocada
        saved.assert_called_once_with("http://127.0.0.1:3001")

    def test_ui_already_running_on_an_alternate_port_is_reused_and_saved(self):
        self.up, alt = {"db", "api", "worker"}, "http://127.0.0.1:3002"
        self.foreign = {on.UI, alt}
        with mock.patch.object(on, "is_ui", lambda url=on.UI, api=on.API: url == alt), mock.patch.object(on, "remember_ui") as saved:
            run = on.start(self.cfg)
        self.assertEqual((run["error"], self.states()["ui"], self.spawned), ("", "reused", []))
        saved.assert_called_once_with(alt)

    def test_no_port_free_for_the_ui_is_a_precise_error(self):
        self.up, self.foreign = {"db", "api", "worker"}, {on._ui_url(p) for p in on.UI_PORTS}
        with mock.patch.object(on, "remember_ui") as saved:
            run = on.start(self.cfg)
        self.assertEqual((self.spawned, self.states()["ui"]), ([], "failed"))
        for part in ("3000 a 3010", "Nada foi encerrado"):
            self.assertIn(part, run["error"])
        saved.assert_not_called()

    def test_failure_names_the_component_and_its_log(self):
        self.dead = {"api"}
        run = on.start(self.cfg)
        self.assertIn("A API do Open Notebook não iniciou", run["error"])
        self.assertIn(str(on.LOGS / "lumen-api.log"), run["error"])
        self.dead = {"worker"}
        self.assertIn(str(on.LOGS / "lumen-worker.log"), on.start(self.cfg)["error"])

    def test_repeated_click_does_not_start_twice_and_remote_address_is_refused(self):
        with mock.patch.object(on.threading, "Thread") as thread:
            first, second = on.start(self.cfg), on.start(self.cfg)
        self.assertEqual((thread.call_count, first["active"], second["active"]), (1, True, True))
        on._run.update(active=False)
        with self.assertRaises(AppError):
            on.start({"opennotebook_url": "http://192.168.0.9:5055"})
        self.assertEqual(self.spawned, [])


class Spawn(unittest.TestCase):
    def test_no_window_no_shell_own_log_and_outside_the_lumen_job_when_allowed(self):
        calls = []

        def popen(args, **kw):
            calls.append((args, kw))
            if kw["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB and len(calls) == 1:
                raise PermissionError(5, "Acesso negado")  # Lumen.exe antigo: sem permissão para sair do grupo
            return mock.Mock()

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(on, "LOGS", Path(tmp) / "logs"), \
                mock.patch.object(on.subprocess, "Popen", popen), mock.patch.dict(on.os.environ, {"LUMEN_DATA": "x", "PYTHONPATH": "y"}):
            on._spawn("api", ["uv", "run"], tmp, {"API_RELOAD": "false"})
            self.assertTrue((Path(tmp) / "logs" / "lumen-api.log").is_file())
        (_, first), (_, second) = calls
        for kw in (first, second):
            self.assertFalse(kw["shell"])
            self.assertTrue(kw["creationflags"] & subprocess.CREATE_NO_WINDOW)
            self.assertEqual((kw["env"]["API_RELOAD"], "LUMEN_DATA" in kw["env"], "PYTHONPATH" in kw["env"]), ("false", False, False))
        self.assertFalse(second["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB)
        self.assertTrue(on.status()["tied"])  # a interface avisa que este serviço fecha junto com o Lúmen


if __name__ == "__main__":
    unittest.main()
