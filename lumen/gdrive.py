"""Google Drive pela API oficial e gratuita: a conta, o acesso e os pedidos que a proteção do cérebro usa para guardar a
cópia de segurança fora do PC (lumen/protection_drive.py). Este módulo é compartilhado: cuida do login e das chamadas à
API; o que vai para o Drive é decidido por quem chama.

(O envio de fontes de aulas ao Gemini Notebook, que também passava por aqui, foi retirado em 09/11/2026.)

- Escopo só drive.file: o Lumen vê apenas os arquivos que ele mesmo criou.
- OAuth de app para computador (developers.google.com/identity/protocols/oauth2/native-app): navegador do sistema,
  retorno para 127.0.0.1 numa porta livre, PKCE S256 e state. O cliente OAuth é do usuário (projeto dele no Google
  Cloud); o client_secret de app para computador não é segredo de verdade, mas fica com o refresh token no cofre do
  sistema (keyring), nunca em arquivo.
- Erros: 401 renova o token uma vez; 429 e 403 de limite esperam (Retry-After) e repetem; 5xx e falta de resposta só
  repetem o que é idempotente. Uma criação sem resposta nunca é repetida aqui (Unconfirmed: quem chama procura pela
  marca do Lumen, appProperties).
- Nada de token, cabeçalho ou conteúdo no log: só o código HTTP e o motivo.
"""
import base64
import hashlib
import json
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import keyring

from . import AppError, store

log = logging.getLogger("lumen")
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.file"
FIELDS = "id,name,webViewLink,modifiedTime,version,trashed"
TIMEOUT, WAIT, TRIES, MAX_WAIT = 30, 300, 3, 30
_TAG = re.compile(r"[a-z0-9.-]{1,100}")
_RATE = ("userRateLimitExceeded", "rateLimitExceeded")
_login = {"state": "idle", "error": ""}  # idle | waiting | ok | error
_access = {"token": None, "until": 0.0}
_lock = threading.Lock()


class Unconfirmed(AppError):
    """A criação saiu e a resposta não voltou: o arquivo pode existir ou não no Drive."""


class NotFound(Exception):
    pass


# --- credenciais (cofre do sistema) -------------------------------------------------------------------------------

def _creds():
    try:
        return json.loads(keyring.get_password(store.APP, "google-drive") or "{}")
    except (keyring.errors.KeyringError, ValueError):
        return {}


def _keep(c):
    try:
        keyring.set_password(store.APP, "google-drive", json.dumps(c))
    except keyring.errors.KeyringError:
        raise AppError("Não consegui guardar a autorização no cofre do Windows.", "Tente de novo.") from None


def status():
    c = _creds()
    return {"client": bool(c.get("client_id")), "connected": bool(c.get("refresh_token")), "email": c.get("email", ""),
            "expired": bool(c.get("expired")) and not c.get("refresh_token"),  # o Google recusou a renovação (7 dias ou revogada)
            "login": _login["state"], "error": _login["error"]}


def set_client(raw):
    """O JSON do cliente OAuth “App para computador” baixado do Google Cloud. Os endereços dele são ignorados: o
    Lumen só fala com os endereços oficiais acima."""
    try:
        j = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, AttributeError):
        j = None
    how = "No Google Cloud, em APIs e serviços → Credenciais, baixe o JSON do cliente do tipo “App para computador”."
    if not isinstance(j, dict) or not isinstance(j.get("installed"), dict):
        raise AppError("Este cliente OAuth não é do tipo “App para computador”." if isinstance(j, dict) and "web" in j
                       else "Este arquivo não é o JSON de um cliente OAuth.", how)
    cid, sec = str(j["installed"].get("client_id") or ""), str(j["installed"].get("client_secret") or "")
    if not re.fullmatch(r"[A-Za-z0-9.-]{8,200}\.apps\.googleusercontent\.com", cid) or len(sec) > 200:
        raise AppError("O JSON não tem um client_id válido do Google.", how)
    _keep({"client_id": cid, "client_secret": sec})  # cliente novo: a autorização anterior não vale para ele
    _access.update(token=None, until=0.0)
    _login.update(state="idle", error="")
    return status()


def logout():
    """Apaga a autorização deste PC (para revogar no Google: myaccount.google.com/permissions)."""
    try:
        keyring.delete_password(store.APP, "google-drive")
    except keyring.errors.KeyringError:
        pass
    _access.update(token=None, until=0.0)
    _login.update(state="idle", error="")
    return status()


# --- login (OAuth de app para computador) ------------------------------------------------------------------------

class _Loop(HTTPServer):
    """Recebe o retorno do Google em 127.0.0.1: só um pedido com o state certo conta; o resto recebe 400."""
    def __init__(self, state):
        super().__init__(("127.0.0.1", 0), _Answer)
        self.state, self.result, self.timeout = state, None, 1


class _Answer(BaseHTTPRequestHandler):
    def log_message(self, *a):  # a URL tem o código de autorização
        pass

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        mine = url.path == "/" and secrets.compare_digest(q.get("state", ""), self.server.state)
        if mine and self.server.result is None:
            self.server.result = q
        text = ("Pronto: o Lumen recebeu a autorização do Google Drive. Pode fechar esta aba e voltar ao Lumen."
                if mine and q.get("code") else "O Lumen não recebeu a autorização. Volte ao Lumen e tente de novo.")
        body = f"<!doctype html><meta charset=utf-8><title>Lumen</title><p>{text}</p>".encode()
        self.send_response(200 if mine else 400)
        for k, v in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))),
                     ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


def _browser(url):
    if not webbrowser.open(url):
        raise AppError("Não consegui abrir o navegador.", "Confira o navegador padrão do Windows.")


def login():
    """Abre o login do Google no navegador do sistema e espera o retorno (até 5 min, numa thread)."""
    c = _creds()
    if not c.get("client_id"):
        raise AppError("Escolha primeiro o arquivo do cliente OAuth.", "Em Integrações → Google Drive.")
    with _lock:
        if _login["state"] == "waiting":  # clique duplo: um login só
            return status()
        _login.update(state="waiting", error="")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    srv = _Loop(secrets.token_urlsafe(24))
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": srv.state,
        "access_type": "offline", "prompt": "consent"})
    try:
        _browser(url)
    except AppError as e:
        srv.server_close()
        _login.update(state="error", error=f"{e} {e.action}")
        raise
    threading.Thread(target=_wait_login, args=(srv, c, verifier, redirect), daemon=True).start()
    return status()


def _wait_login(srv, c, verifier, redirect):
    try:
        end = time.monotonic() + WAIT
        while srv.result is None and time.monotonic() < end and _login["state"] == "waiting":
            srv.handle_request()
        q = srv.result
        if q is None:
            raise AppError("O login no Google não terminou a tempo.", "Clique em “Entrar com Google” de novo.")
        if q.get("error"):
            raise AppError("Você não autorizou o acesso ao Google Drive." if q["error"] == "access_denied"
                           else "O Google recusou o login.", "Clique em “Entrar com Google” para tentar de novo.")
        if not q.get("code"):
            raise AppError("O Google não devolveu a autorização.", "Clique em “Entrar com Google” de novo.")
        tok = _form({"code": q["code"], "client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                     "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
        if not tok.get("refresh_token"):
            raise AppError("O Google não devolveu uma autorização duradoura.",
                           "Remova o acesso do app em myaccount.google.com/permissions e entre de novo.")
        _access.update(token=tok.get("access_token"), until=time.monotonic() + int(tok.get("expires_in") or 3600) - 60)
        c = {k: v for k, v in _creds().items() if k != "expired"} | {"refresh_token": tok["refresh_token"]}
        _keep(c)
        try:
            who = _call("GET", API + "/about?fields=user(emailAddress)")
            _keep({**c, "email": str((who.get("user") or {}).get("emailAddress") or "")})
        except AppError:
            pass  # a conta só aparece na interface; as cópias não dependem dela
        _login.update(state="ok", error="")
        log.info("google drive: conectado")
    except AppError as e:
        _login.update(state="error", error=f"{e} {e.action}".strip())
    except Exception as e:  # noqa: BLE001 — a thread não pode morrer calada
        log.error("google drive: login falhou (%s)", type(e).__name__)
        _login.update(state="error", error="Erro inesperado no login. Tente de novo.")
    finally:
        srv.server_close()


def _form(fields):
    """Pedido ao endpoint de token (código → tokens, ou renovação)."""
    data = urllib.parse.urlencode({k: v for k, v in fields.items() if v}).encode()
    req = urllib.request.Request(TOKEN, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            err = str(json.loads(e.read() or b"{}").get("error") or "")
        except ValueError:
            err = ""
        log.info("google oauth: HTTP %s %s", e.code, err)
        if err == "invalid_grant" and fields["grant_type"] == "refresh_token":
            _keep({k: v for k, v in _creds().items() if k != "refresh_token"} | {"expired": True})
            raise AppError("A autorização do Google Drive expirou ou foi removida.",
                           "Entre com Google de novo. Com o app em modo “Testing” no Google Cloud, ela vale 7 dias.") from None
        if err in ("invalid_client", "unauthorized_client"):
            raise AppError("O Google recusou o cliente OAuth.", "Baixe o JSON do cliente “App para computador” de novo e "
                                                                 "escolha-o no Lumen.") from None
        raise AppError("O Google recusou a autorização.", "Clique em “Entrar com Google” de novo.") from None
    except (urllib.error.URLError, OSError):
        raise AppError("Sem resposta do Google.", "Confira a internet e tente de novo.") from None


def _token():
    if _access["token"] and time.monotonic() < _access["until"]:
        return _access["token"]
    c = _creds()
    if not c.get("refresh_token"):
        raise AppError("O Google Drive não está conectado.", "Em Integrações → Google Drive, clique em “Entrar com Google”.")
    tok = _form({"client_id": c.get("client_id", ""), "client_secret": c.get("client_secret", ""),
                 "refresh_token": c["refresh_token"], "grant_type": "refresh_token"})
    _access.update(token=tok["access_token"], until=time.monotonic() + int(tok.get("expires_in") or 3600) - 60)
    return _access["token"]


# --- pedidos à API ------------------------------------------------------------------------------------------------

def _reason(e):
    try:
        err = json.loads(e.read() or b"{}").get("error") or {}
    except (ValueError, AttributeError, OSError):
        return ""
    found = [x.get("reason") for x in err.get("errors") or [] if isinstance(x, dict)]
    found += [x.get("reason") for x in err.get("details") or [] if isinstance(x, dict)]
    return next((str(r) for r in found if r), "")


def _after(e, attempt):
    raw = str(e.headers.get("Retry-After") or "").strip() if e.headers else ""
    try:
        wait = float(raw) if raw else 2 ** attempt
    except ValueError:
        try:
            wait = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            wait = 2 ** attempt
    return max(wait, 0)


_MSG = {"storageQuotaExceeded": ("O seu Google Drive está sem espaço.", "Libere espaço no Drive e tente de novo."),
        "insufficientPermissions": ("O Lumen não tem permissão no seu Google Drive.",
                                    "Entre com Google de novo e permita o acesso ao Drive."),
        "insufficientFilePermissions": ("O Lumen não tem permissão neste arquivo do Drive.",
                                        "Entre com Google de novo e permita o acesso ao Drive."),
        "appNotAuthorizedToFile": ("Este arquivo do Drive não foi criado pelo Lumen.", "Envie de novo para criar outro."),
        "accessNotConfigured": ("A Google Drive API não está ativada no seu projeto do Google Cloud.",
                                "No console do Google Cloud, ative a Google Drive API e tente de novo."),
        "SERVICE_DISABLED": ("A Google Drive API não está ativada no seu projeto do Google Cloud.",
                             "No console do Google Cloud, ative a Google Drive API e tente de novo.")}


def _error(code, reason):
    if reason in _MSG:
        return AppError(*_MSG[reason])
    if code == 429 or reason in _RATE:
        return AppError("O Google Drive pediu para esperar.", "Tente de novo em alguns minutos.")
    if code == 401:
        return AppError("O Google Drive recusou a autorização.", "Entre com Google de novo.")
    if code >= 500:
        return AppError("O Google Drive está com problemas agora.", "Tente de novo mais tarde.")
    if code == 403:
        return AppError("O Google Drive recusou o pedido.", "Confira o projeto no Google Cloud e entre com Google de novo.")
    return AppError("O Google Drive recusou o pedido.", "Tente de novo.")


def _call(method, url, data=None, ctype=None, idempotent=True):
    for attempt in range(TRIES):
        headers = {"Authorization": "Bearer " + _token(), **({"Content-Type": ctype} if ctype else {})}
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            reason = _reason(e)
            log.info("google drive: HTTP %s %s", e.code, reason)
            if e.code == 401 and attempt == 0:
                _access.update(token=None, until=0.0)  # token vencido: renova uma vez
                continue
            if e.code == 404:
                raise NotFound() from None
            refused = e.code == 429 or (e.code == 403 and reason in _RATE)  # recusado de verdade: nada foi feito
            if (refused or (e.code >= 500 and idempotent)) and attempt < TRIES - 1:
                time.sleep(_after(e, attempt))
                continue
            if e.code >= 500 and not idempotent:
                raise Unconfirmed("O Google Drive falhou no meio do envio.",
                                  "O Lumen confere o que chegou ao Drive antes de enviar de novo.") from None
            raise _error(e.code, reason) from None
        except (urllib.error.URLError, OSError) as e:  # timeout, conexão caída: o pedido pode ter chegado
            log.info("google drive: sem resposta (%s)", type(e).__name__)
            if not idempotent:
                raise Unconfirmed("O Google Drive não respondeu ao envio.",
                                  "O Lumen confere o que chegou ao Drive antes de enviar de novo.") from None
            if attempt < TRIES - 1:
                time.sleep(2 ** attempt)
                continue
            raise AppError("Sem resposta do Google Drive.", "Confira a internet e tente de novo.") from None
    raise AppError("O Google Drive recusou a autorização.", "Entre com Google de novo.")


def find(tag):
    """O arquivo do Lumen com esta marca (appProperties lumen=tag), fora da lixeira, ou None."""
    if not _TAG.fullmatch(tag):
        raise ValueError(tag)
    q = f"appProperties has {{ key='lumen' and value='{tag}' }} and trashed = false"
    files = _call("GET", API + "/files?" + urllib.parse.urlencode(
        {"q": q, "fields": f"files({FIELDS})", "spaces": "drive", "pageSize": 10})).get("files") or []
    return files[0] if files else None


