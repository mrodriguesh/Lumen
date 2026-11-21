"""Conta do Google Drive (lumen/gdrive.py): login OAuth de app para computador com PKCE, renovação do token, erros e repetições.
É o acesso que a Proteção do cérebro usa para a cópia de segurança (lumen/protection_drive.py); estes testes ficam depois da
retirada do envio ao Gemini Notebook, que dividia o módulo. Google falso em tests/fake_google.py; credenciais em memória."""
import json
import re
import time
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA e o cofre antes do lumen)
from lumen import AppError, gdrive, protection, protection_drive, server, store
from tests.fake_google import FakeGoogle

CLIENT = json.dumps({"installed": {"client_id": "1234567890-abcdefghijklmnop.apps.googleusercontent.com",
                                   "client_secret": "GOCSPX-teste",
                                   "auth_uri": "https://evil.example/auth", "token_uri": "https://evil.example/t"}})
TAG = "protection-teste"


class Drive(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGoogle()
        self.creds, self.sleeps, self.auth_url = {}, [], None
        for p in (mock.patch.object(gdrive, "_creds", side_effect=lambda: dict(self.creds)),
                  mock.patch.object(gdrive, "_keep", side_effect=lambda c: (self.creds.clear(), self.creds.update(c))),
                  mock.patch.object(gdrive.webbrowser, "open", side_effect=self._browse),
                  mock.patch.object(gdrive, "time", types.SimpleNamespace(sleep=self.sleeps.append, monotonic=time.monotonic)),
                  mock.patch.object(gdrive, "TIMEOUT", 0.6)):
            p.start()
            self.addCleanup(p.stop)
        gdrive._access.update(token=None, until=0.0)
        gdrive._login.update(state="idle", error="")

    def tearDown(self):
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def _browse(self, url):
        self.auth_url = url
        return True

    def wait_login(self):
        for _ in range(100):
            if gdrive._login["state"] != "waiting":
                break
            time.sleep(0.05)

    def connect(self):
        gdrive.set_client(CLIENT.encode())
        gdrive.login()
        with urllib.request.urlopen(self.fake.authorize(self.auth_url)) as r:
            self.assertEqual(r.status, 200)
        self.wait_login()
        self.assertEqual(gdrive.status()["login"], "ok", gdrive.status()["error"])

    def create(self, tag=TAG, idempotent=False):
        meta = {"name": "Lumen - Protecao do cerebro", "mimeType": "application/vnd.google-apps.folder",
                "appProperties": {"lumen": tag}}
        return gdrive._call("POST", gdrive.API + "/files?fields=id", json.dumps(meta).encode(), "application/json", idempotent=idempotent)

    def test_client_file_must_be_a_desktop_client_and_its_own_addresses_are_ignored(self):
        with self.assertRaises(AppError):
            gdrive.set_client(json.dumps({"web": {"client_id": "1.apps.googleusercontent.com"}}).encode())
        with self.assertRaises(AppError):
            gdrive.set_client(b"isto nao e json")
        st = gdrive.set_client(CLIENT.encode())
        self.assertEqual((st["client"], st["connected"]), (True, False))
        self.assertNotIn("folder", st)  # a pasta do Gemini Notebook não existe mais

    def test_login_pkce_state_and_secrets_only_in_the_keyring(self):
        gdrive.set_client(CLIENT.encode())
        gdrive.login()
        self.assertTrue(self.auth_url.startswith(gdrive.AUTH))  # o endereço do arquivo (evil.example) é ignorado
        self.assertEqual(gdrive.login()["login"], "waiting")  # clique duplo: um login só
        redirect = dict(urllib.parse.parse_qsl(self.auth_url.split("?", 1)[1]))["redirect_uri"]
        with self.assertRaises(urllib.error.HTTPError) as e:  # outro pedido em 127.0.0.1 com state errado
            urllib.request.urlopen(redirect + "/?code=roubado&state=errado")
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(gdrive.status()["login"], "waiting")
        with urllib.request.urlopen(self.fake.authorize(self.auth_url)):
            pass
        self.wait_login()
        st = gdrive.status()
        self.assertEqual((st["login"], st["connected"], st["email"]), ("ok", True, "estudante@example.com"))
        self.assertEqual(self.creds["refresh_token"], self.fake.refresh)
        self.create()
        logf = store.DATA / "lumen.log"
        disk = logf.read_text("utf-8") if logf.exists() else ""
        for secret in (self.fake.refresh, self.fake.access, "GOCSPX"):
            self.assertNotIn(secret, disk)
            self.assertNotIn(secret, json.dumps(gdrive.status()))

    def test_access_denied_is_reported(self):
        gdrive.set_client(CLIENT.encode())
        gdrive.login()
        with urllib.request.urlopen(self.fake.authorize(self.auth_url, deny=True)) as r:
            self.assertIn("não recebeu".encode(), r.read())
        self.wait_login()
        self.assertEqual(gdrive.status()["login"], "error")
        self.assertIn("não autorizou", gdrive.status()["error"])

    def test_logging_in_without_a_client_or_without_login_points_to_the_drive_card(self):
        with self.assertRaises(AppError) as e:
            gdrive.login()
        self.assertIn("Integrações → Google Drive", e.exception.action)
        with self.assertRaises(AppError) as e:
            gdrive._token()
        self.assertIn("Integrações → Google Drive", e.exception.action)
        for text in (str(e.exception), e.exception.action):
            self.assertNotIn("Gemini", text)

    def test_logout_forgets_the_authorization_of_this_pc(self):
        self.connect()
        with mock.patch.object(gdrive.keyring, "delete_password", side_effect=lambda *a: self.creds.clear()) as delete:
            st = gdrive.logout()
        delete.assert_called_once_with(store.APP, "google-drive")  # só a entrada do Drive
        self.assertEqual((st["login"], st["connected"]), ("idle", False))

    def test_expired_token_is_renewed_once_and_revoked_asks_to_reconnect(self):
        self.connect()
        self.fake.expire()
        self.assertIsNone(gdrive.find(TAG))  # 401 → renova uma vez → repete o pedido
        self.assertEqual(sum(1 for c in self.fake.calls if c[1] == "/token"), 2)  # login + uma renovação
        self.fake.expire()
        self.fake.revoked = True
        with self.assertRaises(AppError) as e:
            gdrive.find(TAG)
        self.assertIn("expirou", str(e.exception))
        self.assertIn("7 dias", e.exception.action)
        self.assertNotIn("refresh_token", self.creds)
        st = gdrive.status()  # a interface distingue “acesso expirado ou revogado” de “falta entrar”
        self.assertEqual((st["client"], st["connected"], st["expired"]), (True, False, True))
        self.fake.revoked = False
        gdrive.login()  # entrar de novo (o mesmo cliente) apaga o aviso
        with urllib.request.urlopen(self.fake.authorize(self.auth_url)):
            pass
        self.wait_login()
        st = gdrive.status()
        self.assertEqual((st["login"], st["connected"], st["expired"]), ("ok", True, False))

    def test_403_reasons_and_429_with_retry_after(self):
        self.connect()
        self.fake.fail.append(("GET", "/drive/v3/files", 429, "rateLimitExceeded", "7"))
        self.assertIsNone(gdrive.find(TAG))  # 429 recusado de verdade: espera o Retry-After e repete
        self.assertIn(7.0, self.sleeps)
        self.fake.fail.append(("POST", "/drive/v3/files", 403, "storageQuotaExceeded", None))
        with self.assertRaises(AppError) as e:
            self.create()
        self.assertIn("sem espaço", str(e.exception))
        self.fake.fail.append(("POST", "/drive/v3/files", 403, "accessNotConfigured", None))
        with self.assertRaises(AppError) as e:
            self.create()
        self.assertIn("Google Drive API não está ativada", str(e.exception))
        self.fake.fail.append(("POST", "/drive/v3/files", 403, "userRateLimitExceeded", None))
        self.create()  # limite: foi recusado, nada foi criado; espera e tenta de novo
        self.assertEqual(len(self.fake.tagged(TAG)), 1)

    def test_server_errors_repeat_only_what_is_idempotent(self):
        self.connect()
        self.fake.fail += [("GET", "/drive/v3/files", 503, "backendError", None), ("GET", "/drive/v3/files", 500, "backendError", None)]
        self.assertIsNone(gdrive.find(TAG))  # GET é idempotente: repete e passa
        self.fake.fail.append(("POST", "/drive/v3/files", 500, "backendError", None))
        before = sum(1 for c in self.fake.calls if c[0] == "POST" and c[1] == "/drive/v3/files")
        with self.assertRaises(gdrive.Unconfirmed):
            self.create()
        after = sum(1 for c in self.fake.calls if c[0] == "POST" and c[1] == "/drive/v3/files")
        self.assertEqual(after, before + 1)  # a criação não foi repetida

    def test_timeout_after_create_is_reconciled_by_the_lumen_mark_without_duplicate(self):
        self.connect()
        self.fake.slow_create = 1.5
        with self.assertRaises(gdrive.Unconfirmed):
            self.create()
        self.fake.slow_create = 0
        time.sleep(1.2)  # o Google terminou de criar depois que o Lumen desistiu de esperar
        found = gdrive.find(TAG)  # quem chama procura pela marca antes de criar de novo
        self.assertIsNotNone(found)
        self.assertEqual(len(self.fake.tagged(TAG)), 1)

    def test_the_protection_keeps_using_the_shared_drive_functions(self):
        for name in ("status", "set_client", "login", "logout", "find", "_call", "_token", "_error", "_reason", "_after",
                     "Unconfirmed", "NotFound", "API", "UPLOAD", "SCOPE", "AUTH", "TOKEN"):
            self.assertTrue(hasattr(gdrive, name), name)
        for name in ("create", "update", "folder", "get", "_multipart", "_mime", "FOLDER", "DOC"):  # o envio ao Gemini Notebook
            self.assertFalse(hasattr(gdrive, name), name)
        self.assertIs(protection_drive.gdrive, gdrive)
        self.assertIs(protection.gdrive, gdrive)
        self.assertIn(("GET", "/api/drive"), server.ROUTES)
        for path in ("client", "login", "logout"):
            self.assertIn(("POST", "/api/drive/" + path), server.ROUTES)

    def test_every_api_path_the_protection_screen_calls_exists_on_the_server(self):
        js = (Path(__file__).resolve().parent.parent / "lumen" / "web" / "protection.js").read_text("utf-8")
        paths = set(re.findall(r"['\"](/api/[a-z0-9/_-]+)['\"]", js))
        self.assertIn("/api/drive/login", paths)  # o botão “Conectar” do Drive
        self.assertNotIn("/api/notebook/drive/login", paths)
        known = {p for _, p in server.ROUTES}
        self.assertEqual(sorted(p for p in paths if p not in known), [])


if __name__ == "__main__":
    unittest.main()
