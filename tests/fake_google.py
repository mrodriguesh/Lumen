"""Google falso (OAuth + Drive v3) para os testes de lumen/gdrive.py, a conta do Drive que a Proteção usa: confere PKCE S256,
o token de acesso de cada pedido, guarda os arquivos criados (com a marca appProperties) e injeta falhas (401, 403, 429, 5xx
e resposta que chega depois do timeout do Lumen)."""
import base64
import hashlib
import json
import re
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lumen import gdrive

TAG = re.compile(r"value='([a-z0-9.-]+)'")


class FakeGoogle:
    def __init__(self):
        self.files, self.calls, self.violations = {}, [], []
        self.codes, self.access, self.refresh = {}, None, "rt-" + uuid.uuid4().hex
        self.revoked, self.markdown = False, True
        self.fail = []        # [(método, trecho do caminho, status, motivo, Retry-After)], consumidos em ordem
        self.slow_create = 0  # segundos de espera DEPOIS de criar um arquivo (a resposta chega tarde demais)
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, data, headers=()):
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except OSError:
                    pass  # o Lumen desistiu de esperar (timeout)

            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                url = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(url.query))
                fake.calls.append((method, url.path, q.get("q") or ""))
                try:
                    if url.path == "/token":
                        return self._reply(*fake.token(dict(urllib.parse.parse_qsl(raw.decode()))))
                    if self.headers.get("Authorization") != f"Bearer {fake.access}" or not fake.access:
                        return self._reply(401, {"error": {"code": 401, "errors": [{"reason": "authError"}]}})
                    for i, (m, part, code, reason, after) in enumerate(fake.fail):
                        if m == method and part in url.path:
                            fake.fail.pop(i)
                            return self._reply(code, {"error": {"code": code, "errors": [{"reason": reason}]}},
                                               [("Retry-After", after)] if after else [])
                    code, data = fake.route(method, url.path, q, raw, self.headers.get("Content-Type") or "")
                    if fake.slow_create and method == "POST" and url.path == "/drive/v3/files":
                        time.sleep(fake.slow_create)
                    self._reply(code, data)
                except AssertionError as e:
                    fake.violations.append(str(e))
                    self._reply(400, {"error": {"code": 400, "errors": [{"reason": "badRequest"}]}})

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

            def do_PATCH(self):
                self._do("PATCH")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.httpd.server_port}"
        self.old = {k: getattr(gdrive, k) for k in ("AUTH", "TOKEN", "API", "UPLOAD")}
        gdrive.AUTH, gdrive.TOKEN = base + "/auth", base + "/token"
        gdrive.API, gdrive.UPLOAD = base + "/drive/v3", base + "/upload/drive/v3"

    def close(self):
        for k, v in self.old.items():
            setattr(gdrive, k, v)
        self.httpd.shutdown()
        self.httpd.server_close()

    # --- OAuth ---------------------------------------------------------------------------------------------------
    def authorize(self, auth_url, deny=False):
        """O que o navegador faria: o usuário aceita (ou recusa) e o Google volta para o redirect_uri."""
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(auth_url).query))
        assert q["code_challenge_method"] == "S256" and q["scope"] == gdrive.SCOPE
        assert q["redirect_uri"].startswith("http://127.0.0.1:") and q["access_type"] == "offline"
        if deny:
            return f"{q['redirect_uri']}/?error=access_denied&state={q['state']}"
        code = "code-" + uuid.uuid4().hex
        self.codes[code] = (q["code_challenge"], q["redirect_uri"], q["client_id"])
        return f"{q['redirect_uri']}/?code={code}&state={urllib.parse.quote(q['state'])}"

    def token(self, f):
        if f.get("grant_type") == "authorization_code":
            challenge, redirect, client = self.codes.pop(f.get("code"), (None, None, None))
            verifier = f.get("code_verifier", "")
            made = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if not challenge or made != challenge or f.get("redirect_uri") != redirect or f.get("client_id") != client:
                self.violations.append("troca de código sem PKCE válido")
                return 400, {"error": "invalid_grant"}
            self.access = "at-" + uuid.uuid4().hex
            return 200, {"access_token": self.access, "expires_in": 3599, "refresh_token": self.refresh}
        if f.get("grant_type") == "refresh_token":
            if self.revoked or f.get("refresh_token") != self.refresh:
                return 400, {"error": "invalid_grant"}
            self.access = "at-" + uuid.uuid4().hex
            return 200, {"access_token": self.access, "expires_in": 3599}
        return 400, {"error": "unsupported_grant_type"}

    def expire(self):
        self.access = "vencido-" + uuid.uuid4().hex  # o Lumen ainda guarda o anterior: o próximo pedido leva 401

    # --- Drive -----------------------------------------------------------------------------------------------------
    def _meta(self, f):
        return {k: f[k] for k in ("id", "name", "webViewLink", "modifiedTime", "version", "trashed")}

    def tagged(self, tag=None):
        return [f for f in self.files.values() if tag is None or f["tag"] == tag]

    def route(self, method, path, q, raw, ctype):
        if method == "GET" and path == "/drive/v3/about":
            return 200, {"user": {"emailAddress": "estudante@example.com"}}
        if method == "GET" and path == "/drive/v3/files":
            tag = TAG.search(q.get("q", ""))[1]
            hit = [self._meta(f) for f in self.files.values() if f["tag"] == tag and not f["trashed"]]
            return 200, {"files": hit}
        if method == "POST" and path == "/drive/v3/files":
            return 200, self._new(json.loads(raw), b"")
        return 404, {"error": {"code": 404, "errors": [{"reason": "notFound"}]}}

    def _new(self, meta, media):
        fid = uuid.uuid4().hex
        self.files[fid] = {"id": fid, "name": meta["name"], "mimeType": meta.get("mimeType"), "content": media,
                           "tag": (meta.get("appProperties") or {}).get("lumen"), "parents": meta.get("parents"),
                           "trashed": False, "version": "1", "webViewLink": f"https://docs.google.com/document/d/{fid}",
                           "modifiedTime": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}
        return self._meta(self.files[fid])

