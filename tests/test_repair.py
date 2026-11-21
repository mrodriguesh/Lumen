"""Instalar / reparar (lumen/repair.py, D187) com um HyperbookLM falso: repositório numa pasta temporária no D:, “yarn” e
“npm run dev” trocados por scripts Python locais. Nada é baixado; nada dos dados reais do Lúmen nem do HyperbookLM real
é lido ou tocado (tests/__init__.py isola LUMEN_DATA e o cofre)."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from lumen import AppError, diagnostics, repair, store
from tests import VAULT
from tests.test_diagnostics import Fake

TOKEN = "segredo-de-pareamento-do-teste-0123456789abcdef"
FAKE_DEV = textwrap.dedent("""
    import json, sys, time
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port, delay, life = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
    time.sleep(delay)
    if delay >= 999: time.sleep(life)
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"app": "hyperbooklm", "paired": False}).encode()
            self.send_response(200 if self.path.startswith("/api/lumen") else 404)
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a): pass
    s = HTTPServer(("127.0.0.1", port), H); s.timeout = 0.5
    end = time.time() + life
    while time.time() < end: s.handle_request()
""")
FAKE_YARN = textwrap.dedent("""
    import json, sys, time
    from pathlib import Path
    repo, delay = Path(sys.argv[1]), float(sys.argv[2])
    time.sleep(delay)
    d = repo / "node_modules" / "left-pad"; d.mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text(json.dumps({"name": "left-pad", "version": "1.3.0"}))
""")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


class Repair(unittest.TestCase):
    def setUp(self):
        VAULT.items.clear()
        base = "D:/" if Path("D:/").is_dir() else None
        self.repo = Path(tempfile.mkdtemp(prefix="lumen-hb-falso-", dir=base))
        self.scripts = Path(tempfile.mkdtemp(prefix="lumen-hb-scripts-", dir=base))
        (self.scripts / "dev.py").write_text(FAKE_DEV)
        (self.scripts / "yarn.py").write_text(FAKE_YARN)
        r = self.repo
        (r / "app" / "api" / "lumen").mkdir(parents=True)
        (r / "app" / "api" / "lumen" / "route.ts").write_text("// ponte")
        (r / "package.json").write_text(json.dumps({"name": "hyperbook-lm", "scripts": {"dev": "next dev -H 127.0.0.1"},
                                                     "dependencies": {"next": "15.0.0", "left-pad": "^1.3.0"}}))
        (r / "yarn.lock").write_text('# yarn lockfile v1\n\n\nleft-pad@^1.3.0:\n  version "1.3.0"\n\nnext@15.0.0:\n  version "15.0.0"\n')
        (r / ".env.local").write_text(f"LUMEN_BRIDGE_TOKEN={TOKEN}\nOPENAI_API_KEY=sk-teste\n")
        (r / ".lumen").mkdir()
        (r / ".lumen" / "sources.json").write_text('[{"id": "a", "title": "Aula"}]')
        for name, ver in (("next", "15.0.0"), ("left-pad", "1.3.0")):
            (r / "node_modules" / name).mkdir(parents=True)
            (r / "node_modules" / name / "package.json").write_text(json.dumps({"name": name, "version": ver}))
        self.keep = {p: digest(r / p) for p in (".env.local", "yarn.lock", ".lumen/sources.json", "package.json")}
        self.port = free_port()
        cfg = store.load_config()
        self.addCleanup(store.save_config, dict(cfg))
        cfg.update(hyperbooklm_on=True, hyperbooklm_url=f"http://127.0.0.1:{self.port}")
        store.save_config(cfg)
        self.pids = []
        for p in (patch.object(repair, "HB_REPO", r), patch.object(repair, "HB_PORTS", [self.port]),
                  patch.object(repair, "HEALTH_S", 25), patch("lumen.hyperbooklm.detect", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        self.dev(delay=1)
        self.yarn(delay=0)
        self.addCleanup(self.cleanup)

    def dev(self, delay, life=20):
        """`npm run dev -- -p N` trocado pelo servidor falso (responde /api/lumen como a ponte, sem pareamento)."""
        def cmd(port):
            return [sys.executable, str(self.scripts / "dev.py"), str(port), str(delay), str(life)]
        p = patch.object(repair, "_npm_dev", cmd)
        p.start()
        self.addCleanup(p.stop)

    def yarn(self, delay):
        p = patch.object(repair, "_installer", lambda: [sys.executable, str(self.scripts / "yarn.py"), str(self.repo), str(delay)])
        p.start()
        self.addCleanup(p.stop)

    def cleanup(self):
        repair.cancel()
        self.wait(10)
        for p in list(repair._procs):
            repair._kill(p)
        for log in (store.DATA / "logs").glob("repair-*.log"):
            text = log.read_text("utf-8", "replace")
            self.assertNotIn(TOKEN, text)
        import shutil
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.scripts, ignore_errors=True)
        repair._job.update(id=None, status="idle", steps=[], message="")

    def wait(self, seconds=40):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            job = repair.view()["job"]
            if job["status"] != "running":
                return job
            time.sleep(0.2)
        return repair.view()["job"]

    def assert_preserved(self):
        for p, h in self.keep.items():
            self.assertEqual(digest(self.repo / p), h, p)
        self.assertNotIn(TOKEN, json.dumps(repair.view()))

    # --- casos ---------------------------------------------------------------------------------------------------

    def test_stopped_service_with_dependencies_installed_starts_and_verifies(self):
        plan = repair.plan()
        hb = next(p for p in plan if p["id"] == "hyperbooklm")
        self.assertTrue(hb["title"].startswith("Iniciar"))
        self.assertIn("2 conferidas com o yarn.lock", hb["detail"])
        repair.start("hyperbooklm")
        job = self.wait()
        self.assertEqual(job["status"], "done", job)
        self.assertNotIn("deps", [s["id"] for s in job["steps"]])  # nada instalado: as dependências já estavam lá
        self.assertIn("falta parear", job["message"])               # passo do usuário, sem inventar código
        self.assertEqual(repair._bridge(f"http://127.0.0.1:{self.port}"), "hyperbooklm")
        self.assertEqual(store.load_config()["hyperbooklm_url"], f"http://127.0.0.1:{self.port}")
        self.assert_preserved()

    def test_missing_locked_dependency_is_installed_first(self):
        import shutil
        shutil.rmtree(self.repo / "node_modules" / "left-pad")
        self.assertEqual(repair.hb_deps(self.repo)["missing"], ["left-pad"])
        self.assertTrue(repair.plan()[0]["title"].startswith("Instalar dependências"))
        repair.start("hyperbooklm")
        job = self.wait()
        self.assertEqual(job["status"], "done", job)
        self.assertEqual([s["id"] for s in job["steps"]][:2], ["repo", "deps"])
        self.assertEqual(repair.hb_deps(self.repo)["missing"], [])
        self.assert_preserved()

    def test_no_package_manager_is_an_actionable_error(self):
        import shutil
        shutil.rmtree(self.repo / "node_modules" / "left-pad")
        with patch.object(repair, "_installer", return_value=None):
            repair.start("hyperbooklm")
            job = self.wait()
        self.assertEqual(job["status"], "failed")
        self.assertIn("corepack", job["message"])
        self.assertIn("Node.js", job["action"])
        self.assert_preserved()

    def test_already_running_is_respected(self):
        f = Fake({("GET", "/api/lumen"): (200, {"app": "hyperbooklm", "paired": True})})
        self.addCleanup(f.close)
        store.save_config({**store.load_config(), "hyperbooklm_url": f.url})
        self.assertEqual([p for p in repair.plan() if p["id"] == "hyperbooklm"], [])
        with self.assertRaises(AppError):
            repair.start("hyperbooklm")

    def test_running_on_another_port_only_fixes_the_saved_address(self):
        f = Fake({("GET", "/api/lumen"): (200, {"app": "hyperbooklm", "paired": False})})
        self.addCleanup(f.close)
        with patch("lumen.hyperbooklm.detect", return_value=f.url), patch.object(repair, "_npm_dev", side_effect=AssertionError("não deveria iniciar")):
            repair.start("hyperbooklm")
            job = self.wait()
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(store.load_config()["hyperbooklm_url"], f.url)
        self.assert_preserved()

    def test_wrong_port_used_by_another_program_is_never_stopped(self):
        other = Fake({("GET", "/"): (200, {"sou": "outro programa"})})
        self.addCleanup(other.close)
        other_port = other.srv.server_port
        store.save_config({**store.load_config(), "hyperbooklm_url": other.url})
        with patch.object(repair, "HB_PORTS", [other_port, self.port]):
            repair.start("hyperbooklm")
            job = self.wait()
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(store.load_config()["hyperbooklm_url"], f"http://127.0.0.1:{self.port}")
        self.assertEqual(repair._bridge(other.url), "other")  # o outro programa continua respondendo
        self.assert_preserved()

    def test_health_timeout_stops_only_what_it_started(self):
        self.dev(delay=999, life=30)  # nunca escuta
        with patch.object(repair, "HEALTH_S", 4):
            repair.start("hyperbooklm")
            for _ in range(100):  # a porta fechada leva ~2 s para recusar no Windows: o processo nasce depois disso
                if repair._procs:
                    break
                time.sleep(0.1)
            pid = repair._procs[0].pid
            job = self.wait()
        self.assertEqual(job["status"], "failed")
        self.assertIn("não respondeu", job["message"])
        time.sleep(1)
        self.assertFalse(alive(pid))
        self.assert_preserved()

    def test_cancel_during_install(self):
        import shutil
        shutil.rmtree(self.repo / "node_modules" / "left-pad")
        self.yarn(delay=30)
        repair.start("hyperbooklm")
        for _ in range(50):
            if any(s["id"] == "deps" for s in repair.view()["job"]["steps"]):
                break
            time.sleep(0.1)
        pid = repair._procs[0].pid
        repair.action({"action": "cancel"})
        job = self.wait(10)
        self.assertEqual(job["status"], "cancelled")
        time.sleep(1)
        self.assertFalse(alive(pid))
        self.assertFalse((self.repo / "node_modules" / "left-pad").exists())
        self.assert_preserved()

    def test_unknown_or_unneeded_ids_are_refused(self):
        with self.assertRaises(AppError):
            repair.action({"action": "start", "id": "rm -rf /"})
        with self.assertRaises(AppError):
            repair.action({"action": "start", "id": "python"})  # nada faltando no requirements.txt
        with self.assertRaises(AppError):
            repair.action({"action": "qualquer"})

    def test_python_install_is_verified_not_assumed(self):
        with patch.object(diagnostics, "_pins", return_value=[("pacote-falso-lumen", "1.0")]):
            item = next(p for p in repair.plan() if p["id"] == "python")
            self.assertIn("pacote-falso-lumen==1.0", item["commands"][0])
            with patch.object(repair, "_pip_cmd", lambda specs: [sys.executable, "-c", "pass"]):  # “instala” sem instalar
                repair.start("python")
                job = self.wait()
        self.assertEqual(job["status"], "failed")  # o pip saiu com 0, mas o pacote não apareceu: não é sucesso
        self.assertIn("Ainda faltam", job["message"])

    def test_diagnostic_points_to_repair_and_stays_optional(self):
        r = diagnostics.check_hyperbooklm(diagnostics.Ctx())
        self.assertEqual((r["state"], r["required"], r["repair"]), ("unreachable", False, "hyperbooklm"))
        self.assertIn("servidor parado", r["detail"])
        self.assertIn("2 dependências completas", r["detail"])
        import shutil
        shutil.rmtree(self.repo / "node_modules" / "left-pad")
        r = diagnostics.check_hyperbooklm(diagnostics.Ctx())
        self.assertEqual((r["state"], r["required"]), ("missing", False))
        res = diagnostics.run_diagnostics(checks=[("integrations", "HyperbookLM", diagnostics.check_hyperbooklm),
                                                  ("python", "núcleo", lambda c: diagnostics.R("ok", "ok", required=True))])
        self.assertTrue(res["summary"]["operational"])  # o opcional fora do ar não derruba a prontidão do núcleo
        self.assert_preserved()


class YarnLock(unittest.TestCase):
    def test_parse_scoped_and_multi_specs(self):
        text = ('# yarn lockfile v1\n\n"@alloc/quick-lru@^5.2.0":\n  version "5.2.0"\n\n'
                'react@^19.0.0, react@^19.1.0:\n  version "19.1.0"\n  resolved "x"\n')
        lock = repair.yarn_lock(text)
        self.assertEqual(lock["@alloc/quick-lru"]["^5.2.0"], "5.2.0")
        self.assertEqual(lock["react"], {"^19.0.0": "19.1.0", "^19.1.0": "19.1.0"})


if __name__ == "__main__":
    unittest.main()
