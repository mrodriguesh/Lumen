"""Diagnóstico do sistema (lumen/diagnostics.py, D186): esquema, estados, prazos, segredos e prevenção de sucesso falso.

Tudo com dados isolados (tests/__init__.py: LUMEN_DATA temporária e cofre em memória) e serviços falsos em 127.0.0.1;
nenhum teste fala com o Notion, o Google, o Ollama ou o Voice Studio de verdade, exceto o teste de esquema, que roda as
verificações reais deste PC só com leituras."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from lumen import diagnostics as d
from lumen import gdrive, llm, notion, store
from tests import VAULT

TOKEN = "ntn_TESTE_segredo_que_nunca_aparece_1234567890"


class Fake:
    """Servidor HTTP falso: routes = {(método, caminho): (status, corpo dict|bytes)}; guarda os pedidos recebidos."""

    def __init__(self, routes):
        fake = self
        self.routes, self.seen = routes, []

        class H(BaseHTTPRequestHandler):
            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                fake.seen.append((method, self.path, dict(self.headers), body))
                path = self.path.split("?")[0]
                code, out = fake.routes.get((method, path), (404, {"error": "não encontrado"}))
                data = out if isinstance(out, bytes) else json.dumps(out).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def closed_port():
    s = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = s.server_port
    s.server_close()
    return f"http://127.0.0.1:{port}"


def run(*checks, request=None, deadline=10):
    return d.run_diagnostics(request, checks=[(c, n, f) for c, n, f in checks], deadline=deadline)


def item(res, name):
    return next(i for c in res["categories"] for i in c["items"] if i["name"] == name)


class Base(unittest.TestCase):
    def setUp(self):
        VAULT.items.clear()
        self.cfg = store.load_config()
        self.addCleanup(store.save_config, dict(self.cfg))

    def config(self, **values):
        cfg = store.load_config()
        cfg.update(values)
        store.save_config(cfg)

    def fake(self, routes):
        f = Fake(routes)
        self.addCleanup(f.close)
        return f


class Schema(Base):
    def test_real_run_is_compatible_and_consistent(self):
        """As verificações reais deste PC (só leituras): o esquema antigo continua, mais os campos novos coerentes."""
        res = d.run_diagnostics({"ua": "teste", "bind": "127.0.0.1", "port": 1})
        s = res["summary"]
        for key in ("total", "ok", "warn", "error", "info", "state", "message", "operational", "coverage", "readiness", "states"):
            self.assertIn(key, s)
        self.assertEqual(s["total"], s["ok"] + s["warn"] + s["error"] + s["info"])
        self.assertEqual(s["total"], sum(s["states"].values()))
        self.assertTrue(0 <= res["score"] <= 100)
        ids = [c["id"] for c in res["categories"]]
        for cid in ("python", "desktop", "audio", "whisper", "ollama", "study", "voicestudio", "integrations", "protection", "media", "hardware"):
            self.assertIn(cid, ids)
        rows = [i for c in res["categories"] for i in c["items"]]
        self.assertEqual(len(rows), len(d.CHECKS))
        for i in rows:
            self.assertIn(i["state"], d.STATE_LABEL)
            self.assertIn(i["status"], ("ok", "warn", "error", "info"))
            self.assertEqual(set(i["stages"]), set(d.STAGES))
            self.assertIsInstance(i["required"], bool)
            self.assertIsInstance(i["ms"], int)
            if i["state"] == "ok":
                self.assertNotIn(False, i["stages"].values(), i["name"])  # ok nunca com uma etapa reprovada
        req = [i for i in rows if i["required"]]
        self.assertEqual(s["operational"], all(i["state"] == "ok" for i in req))
        if not s["operational"]:
            self.assertNotIn("100%", s["message"])
        self.assertTrue(datetime_ok(res["timestamp"]))

    def test_request_outside_http_is_unverified_not_ok(self):
        res = run(("desktop", "Servidor local do Lúmen", d.check_server))
        self.assertEqual(item(res, "Servidor local do Lúmen")["state"], "unverified")
        self.assertFalse(res["summary"]["operational"])


def datetime_ok(text):
    from datetime import datetime
    return datetime.fromisoformat(text).tzinfo is not None


class FalseSuccess(Base):
    def test_crash_timeout_and_denied_never_count_as_success(self):
        def crash(ctx):
            raise RuntimeError("quebrou com " + TOKEN)

        def slow(ctx):
            time.sleep(3)
            return d.R("ok", "tarde demais", required=True)

        def denied(ctx):
            raise PermissionError("negado")

        def good(ctx):
            return d.R("ok", "tudo certo", required=True, stages={"installed": True, "usable": True})

        t = time.monotonic()
        res = run(("python", "quebra", crash), ("python", "lenta", slow), ("python", "negada", denied), ("python", "boa", good), deadline=1)
        self.assertLess(time.monotonic() - t, 2.5)  # o prazo total vale mesmo com uma verificação presa
        self.assertEqual(item(res, "quebra")["state"], "unverified")
        self.assertNotIn("quebrou", item(res, "quebra")["detail"])  # só o tipo do erro, nunca a mensagem (pode ter segredo)
        self.assertEqual(item(res, "lenta")["state"], "unverified")
        self.assertIn("Tempo esgotado", item(res, "lenta")["detail"])
        self.assertEqual(item(res, "negada")["state"], "blocked")
        s = res["summary"]
        self.assertFalse(s["operational"])
        # sem resultado, a verificação conta como obrigatória: só “boa” passou de 4
        self.assertEqual((s["readiness"]["required"], s["readiness"]["required_ok"]), (4, 1))
        self.assertEqual(res["score"], 25)
        self.assertEqual(s["coverage"]["ran"], 1)
        self.assertEqual(s["coverage"]["unverified"], 2)
        self.assertEqual(s["coverage"]["blocked"], 1)

    def test_required_failure_blocks_operational_and_optional_disabled_is_not_verified(self):
        res = run(("python", "obrigatória ok", lambda c: d.R("ok", "ok", required=True)),
                  ("python", "obrigatória faltando", lambda c: d.R("missing", "falta", required=True, next="Faça X.")),
                  ("python", "opcional desligada", lambda c: d.R("disabled", "desligada", enabled=False)))
        s = res["summary"]
        self.assertFalse(s["operational"])
        self.assertEqual(s["state"], "error")
        self.assertEqual(res["score"], 50)
        self.assertIn("obrigatória faltando (faltando)", s["message"])
        off = item(res, "opcional desligada")
        self.assertEqual((off["status"], off["enabled"], off["required"]), ("info", False, False))
        self.assertEqual(s["readiness"]["optional_disabled"], 1)
        self.assertEqual(s["readiness"]["optional_enabled"], 0)

    def test_all_required_ok_is_operational(self):
        res = run(("python", "a", lambda c: d.R("ok", "ok", required=True)),
                  ("python", "b", lambda c: d.R("disabled", "desligada", enabled=False)))
        self.assertTrue(res["summary"]["operational"])
        self.assertEqual(res["score"], 100)
        self.assertIn("configuração opcional", res["summary"]["message"])


class Packages(Base):
    def test_missing_and_wrong_versions(self):
        with patch.object(d, "_pins", return_value=[("pacote-que-nao-existe-lumen", "1.0")]):
            r = d.check_packages(None)
        self.assertEqual(r["state"], "missing")
        self.assertIn("Iniciar Lumen.bat", r["next"])
        with patch.object(d, "_pins", return_value=[("keyring", "0.0.1")]):
            r = d.check_packages(None)
        self.assertEqual(r["state"], "misconfigured")
        self.assertIn("fixado 0.0.1", r["detail"])
        with patch.object(d, "_pins", return_value=None):
            self.assertEqual(d.check_packages(None)["state"], "missing")


class Ollama(Base):
    def test_service_down(self):
        with patch.object(llm, "OLLAMA", closed_port()):
            res = run(("ollama", "Serviço Ollama", d.check_ollama), ("ollama", "Modelo do material das aulas", d.check_lesson_model))
        self.assertEqual(item(res, "Serviço Ollama")["state"], "unreachable")
        self.assertEqual(item(res, "Serviço Ollama")["status"], "error")
        self.assertEqual(item(res, "Modelo do material das aulas")["state"], "unreachable")
        self.assertIn("não o inicia", item(res, "Serviço Ollama")["next"])

    def test_models_installed_missing_and_wrong_capability(self):
        f = self.fake({("GET", "/api/version"): (200, {"version": "9.9"}),
                       ("GET", "/api/tags"): (200, {"models": [{"name": "qwen3:8b"}, {"name": "texto:1b"}]}),
                       ("POST", "/api/show"): (200, {"capabilities": ["completion"], "details": {"parameter_size": "8B"}})})
        self.config(ollama_model="qwen3:8b")
        with patch.object(llm, "OLLAMA", f.url):
            ctx = d.Ctx()
            self.assertEqual(d.check_lesson_model(ctx)["state"], "ok")
            r = d._model_check(ctx, "nao-instalado:1b", purpose="Teste", required=True)
            self.assertEqual(r["state"], "missing")
            r = d._model_check(ctx, "texto:1b", purpose="Visão", required=False, capability="vision")
            self.assertEqual(r["state"], "misconfigured")  # instalado não basta: precisa declarar a capacidade
        self.assertTrue(all(m != "POST" or p == "/api/show" for m, p, *_ in f.seen))  # nada além de leituras


class Notion(Base):
    def setUp(self):
        super().setUp()
        store.set_token(TOKEN)
        self.config(destinations="notion", root_page_id="raiz123", root_page_title="Estudos")

    def notion(self, routes):
        f = self.fake(routes)
        p = patch.object(notion, "API", f.url + "/v1")
        p.start()
        self.addCleanup(p.stop)
        return f

    def test_token_never_leaks_even_when_echoed(self):
        f = self.notion({("GET", "/v1/users/me"): (200, {"bot": {"workspace_name": "Eco " + TOKEN}}),
                         ("GET", "/v1/pages/raiz123"): (404, {"code": "object_not_found"})})
        res = run(("integrations", "Notion", d.check_notion))
        n = item(res, "Notion")
        self.assertEqual(n["state"], "misconfigured")
        self.assertTrue(n["required"])
        self.assertEqual(n["stages"]["authenticated"], True)
        self.assertEqual(n["stages"]["usable"], False)
        self.assertIn("Conexões", n["next"])
        self.assertNotIn(TOKEN, json.dumps(res, ensure_ascii=False))
        self.assertTrue(all(m == "GET" for m, *_ in f.seen))

    def test_ok_unauthorized_and_offline(self):
        self.notion({("GET", "/v1/users/me"): (200, {"bot": {"workspace_name": "Meu"}}), ("GET", "/v1/pages/raiz123"): (200, {"in_trash": False})})
        self.assertEqual(d.check_notion(d.Ctx())["state"], "ok")
        self.notion({("GET", "/v1/users/me"): (401, {"code": "unauthorized"})})
        r = d.check_notion(d.Ctx())
        self.assertEqual((r["state"], r["stages"]["authenticated"]), ("misconfigured", False))
        with patch.object(notion, "API", closed_port() + "/v1"):
            self.assertEqual(d.check_notion(d.Ctx())["state"], "unreachable")

    def test_optional_when_not_a_destination(self):
        store.delete_token()
        self.config(destinations="obsidian")
        r = d.check_notion(d.Ctx())
        self.assertEqual((r["state"], r["required"], r["enabled"]), ("disabled", False, False))


class Obsidian(Base):
    def test_vault_states(self):
        tmp = Path(tempfile.mkdtemp(prefix="lumen-diag-cofre-", dir="D:/" if Path("D:/").is_dir() else None))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / ".obsidian").mkdir()
        self.config(destinations="both", obsidian_vault=str(tmp))
        r = d.check_obsidian(d.Ctx())
        self.assertEqual((r["state"], r["required"]), ("ok", True))
        self.assertEqual(list(tmp.iterdir()), [tmp / ".obsidian"])  # nada foi criado no cofre
        self.config(obsidian_vault=str(tmp / "sumiu"))
        self.assertEqual(d.check_obsidian(d.Ctx())["state"], "unreachable")
        self.config(obsidian_vault="")
        self.assertEqual(d.check_obsidian(d.Ctx())["state"], "misconfigured")


class Drive(Base):
    PROT = {"config": {"enabled": True, "local": "X:/backup", "set_id": "abc", "drive_enabled": True}, "local_available": True,
            "state": {}, "places": {}}

    def creds(self):
        c = {"client_id": "cliente", "client_secret": "segredo-do-cliente-123", "refresh_token": "1//refresh-token-secreto-abcdef", "email": "a@b.c"}
        VAULT.set_password(store.APP, "google-drive", json.dumps(c))
        return VAULT.get_password(store.APP, "google-drive")

    def test_expired_authorization_is_reported_without_writing_the_vault(self):
        before = self.creds()
        f = self.fake({("POST", "/token"): (400, {"error": "invalid_grant"})})
        with patch.object(gdrive, "TOKEN", f.url + "/token"), patch.object(d.Ctx, "protection", lambda self: Drive.PROT):
            res = run(("protection", "Google Drive", d.check_drive))
        r = item(res, "Google Drive")
        self.assertEqual((r["state"], r["stages"]["authenticated"]), ("misconfigured", False))
        self.assertEqual(VAULT.get_password(store.APP, "google-drive"), before)  # o diagnóstico não grava a expiração
        text = json.dumps(res)
        self.assertNotIn("refresh-token-secreto", text)
        self.assertNotIn("segredo-do-cliente", text)

    def test_read_only_api_probe(self):
        self.creds()
        f = self.fake({("POST", "/token"): (200, {"access_token": "ya29.acesso-temporario-secreto", "expires_in": 3600}),
                       ("GET", "/drive/v3/files"): (200, {"files": []})})
        with patch.object(gdrive, "TOKEN", f.url + "/token"), patch.object(gdrive, "API", f.url + "/drive/v3"), \
                patch.object(d.Ctx, "protection", lambda self: Drive.PROT):
            res = run(("protection", "Google Drive", d.check_drive))
        r = item(res, "Google Drive")
        self.assertEqual(r["state"], "ok")
        self.assertEqual([m for m, *_ in f.seen], ["POST", "GET"])  # renovação + uma leitura; nada enviado nem apagado
        self.assertNotIn("ya29.acesso", json.dumps(res))

    def test_disabled_drive_is_optional_setup(self):
        prot = {**self.PROT, "config": {**self.PROT["config"], "drive_enabled": False}}
        with patch.object(d.Ctx, "protection", lambda self: prot):
            r = d.check_drive(d.Ctx())
        self.assertEqual((r["state"], r["enabled"]), ("disabled", False))


class Protection(Base):
    def test_missing_restic_when_enabled(self):
        from lumen import protection
        with patch.object(protection, "RESTIC", Path(tempfile.gettempdir()) / "sem-restic.exe"), \
                patch.object(d.Ctx, "protection", lambda self: Drive.PROT):
            r = d.check_restic(d.Ctx())
        self.assertEqual(r["state"], "missing")

    def test_missing_key(self):
        with patch.object(d.Ctx, "protection", lambda self: Drive.PROT):
            r = d.check_protection_repo(d.Ctx())
        self.assertEqual((r["state"], r["stages"]["authenticated"]), ("misconfigured", False))


class LocalApps(Base):
    def test_disabled_and_down(self):
        self.config(opennotebook_on=False, hyperbooklm_on=False)
        self.assertEqual(d.check_opennotebook(d.Ctx())["state"], "disabled")
        self.assertEqual(d.check_hyperbooklm(d.Ctx())["state"], "disabled")
        self.config(opennotebook_on=True, opennotebook_url=closed_port(), hyperbooklm_on=True, hyperbooklm_url=closed_port())
        self.assertEqual(d.check_opennotebook(d.Ctx())["state"], "unreachable")
        from lumen import repair
        with patch.object(repair, "HB_REPO", Path(tempfile.gettempdir()) / "sem-hyperbooklm"), patch("lumen.hyperbooklm.detect", return_value=None):
            r = d.check_hyperbooklm(d.Ctx())  # nem o repositório real nem as portas reais do HyperbookLM
        self.assertEqual(r["state"], "unreachable")
        self.assertIsNone(r.get("repair"))  # sem repositório, não há o que reparar com um clique

    def test_opennotebook_db_offline_and_never_writes_config(self):
        f = self.fake({("GET", "/api/config"): (200, {"dbStatus": "offline", "version": "1"})})
        self.config(opennotebook_on=True, opennotebook_url=f.url, opennotebook_ui="http://127.0.0.1:9")
        before = (store.DATA / "config.json").read_bytes()
        r = d.check_opennotebook(d.Ctx())
        self.assertEqual(r["state"], "unreachable")
        self.assertEqual((store.DATA / "config.json").read_bytes(), before)

    def test_perplexity_unused_makes_no_network_request(self):
        shutil.rmtree(store.DATA / "webview-perplexity", ignore_errors=True)
        with patch.object(d, "http", side_effect=AssertionError("não deveria consultar a internet")):
            r = d.check_perplexity(d.Ctx({"ua": "LumenShell/3"}))
        self.assertEqual(r["state"], "disabled")


class Shell(Base):
    def test_server_and_window_from_the_request(self):
        res = run(("desktop", "Servidor local do Lúmen", d.check_server),
                  request={"ua": "Mozilla/5.0 LumenShell/3", "bind": "0.0.0.0", "port": 5})
        self.assertEqual(item(res, "Servidor local do Lúmen")["state"], "misconfigured")
        with patch.object(d, "webview2_version", return_value="150.0.0.0"):
            r = d.check_shell(d.Ctx({"ua": "Mozilla/5.0 Chrome"}))
        self.assertIn(r["state"], ("unverified", "missing"))  # navegador comum: a janela nativa não é dada como verificada

    def test_route_passes_the_request(self):
        from lumen import server
        httpd = server.serve(0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        port = httpd.server_port
        with patch.object(d, "CHECKS", [("desktop", "Servidor local do Lúmen", d.check_server)]):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/diagnostics",
                                         headers={"X-Lumen-Token": server.TOKEN, "Host": f"127.0.0.1:{port}", "User-Agent": "teste LumenShell/3"})
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.load(r)
        it = item(res, "Servidor local do Lúmen")
        self.assertEqual(it["state"], "ok")
        self.assertIn(f"127.0.0.1:{port}", it["detail"])
        with self.assertRaises(urllib.error.HTTPError) as e:  # sem o token da sessão, nada
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/diagnostics", headers={"Host": f"127.0.0.1:{port}"}), timeout=5)
        self.assertEqual(e.exception.code, 403)


class Redact(unittest.TestCase):
    def test_patterns_and_known_values(self):
        out = d.redact({"a": ["Bearer abc.def", "x ntn_ABCDEFGH123 y", "chave-muito-secreta-000"]}, {"chave-muito-secreta-000"})
        self.assertNotIn("abc.def", json.dumps(out))
        self.assertNotIn("ntn_ABCDEFGH123", json.dumps(out))
        self.assertNotIn("chave-muito-secreta", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
