"""HyperbookLM: a transcrição de uma aula vira uma fonte no HyperbookLM deste PC, pela ponte dele (app/api/lumen, no
repositório do HyperbookLM). Vão só o título e o texto da transcrição; nunca áudio, telas, anotações nem caminhos de
arquivo. O envio é sempre manual. É uma integração à parte do Open Notebook: nada aqui muda o que ele faz.

A ponte só atende este PC e exige o código de pareamento, que o Lúmen gera e guarda no cofre do sistema; no HyperbookLM
ele fica no .env.local (LUMEN_BRIDGE_TOKEN). As chaves de IA do HyperbookLM nunca passam por aqui: a ponte só diz se existem.

Rotas da ponte: GET /api/lumen (quem é, pareado ou não; com o código, que análises têm chave e o total guardado),
GET /api/lumen/sources?meta=1 (o que está guardado), POST /api/lumen/sources {title, text} (guarda uma vez: o id vem do
conteúdo)."""
import hashlib
import json
import logging
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import keyring

from . import AppError, llm, store
from .onlocal import _busy
from .opennotebook import _OPENER, Unavailable, has_transcript  # conexão direta, sem proxy e sem redirecionamento

log = logging.getLogger("lumen")
URL = "http://127.0.0.1:3000"
PORTS = range(3000, 3011)  # `next dev` sobe uma porta a cada vez que a anterior está ocupada (o Open Notebook usa a 3000)
MAX_TEXT, MAX_TITLE = 2_000_000, 300  # bytes e caracteres: os mesmos limites da ponte
_SEND = threading.Lock()  # um envio por vez: dois cliques não disputam o mesmo registro


class Refused(AppError):
    """A ponte respondeu, mas não aceitou. code: unauthorized | unpaired | notfound | toobig | limit | error."""
    code = "error"

    def __init__(self, code, message, action=""):
        super().__init__(message, action)
        self.code = code


_REFUSED = {
    401: ("unauthorized", "O HyperbookLM recusou o código de pareamento.",
          "Confira a linha LUMEN_BRIDGE_TOKEN no .env.local dele (ou desconecte e pareie de novo) e reinicie-o."),
    503: ("unpaired", "O HyperbookLM ainda não foi pareado com o Lúmen.",
          "Gere o código em Integrações → HyperbookLM, cole a linha no .env.local dele e reinicie-o."),
    404: ("notfound", "Quem respondeu neste endereço não tem a ponte do Lúmen.",
          "Confira o endereço e se o HyperbookLM está atualizado."),
    403: ("notfound", "O HyperbookLM só aceita pedidos feitos por este PC.", "Use o endereço http://127.0.0.1 com a porta dele."),
    413: ("toobig", "Esta transcrição é grande demais para o HyperbookLM.", "O limite é de 2 MB de texto por aula."),
    409: ("limit", "O HyperbookLM já guarda o máximo de transcrições do Lúmen.", "Remova fontes antigas nele e envie de novo."),
}


def address(raw):
    """Só http neste PC, sem usuário, senha, caminho, consulta nem fragmento: a ponte não atende outros computadores."""
    u = urllib.parse.urlsplit(str(raw or "").strip())
    try:
        port = u.port
    except ValueError:
        port = None
    if (u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1") or not port or u.username or u.password
            or u.path.strip("/") or u.query or u.fragment):
        raise AppError("Endereço do HyperbookLM inválido.", "Use o endereço deste PC com a porta, como http://127.0.0.1:3000.")
    return f"http://{'[::1]' if u.hostname == '::1' else u.hostname}:{port}"


def _token():
    try:
        return keyring.get_password(store.APP, "hyperbooklm")
    except keyring.errors.KeyringError:
        return None


def _forget_token():
    try:
        keyring.delete_password(store.APP, "hyperbooklm")
    except keyring.errors.KeyringError:
        pass


def _call(url, method, path, body=None, timeout=15, auth=True):
    """Um pedido à ponte. Os erros viram AppError com o que fazer; nem o código nem o corpo vão para o log. (O prazo é
    folgado porque o `next dev` compila cada rota no primeiro pedido.)"""
    headers, token = {"Accept": "application/json"}, _token() if auth else None
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body, ensure_ascii=False).encode(), "application/json"
    req = urllib.request.Request(url + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            out = json.loads(r.read() or b"null")
            if not isinstance(out, dict):
                raise ValueError
            return out
    except urllib.error.HTTPError as e:
        e.close()
        code, message, action = _REFUSED.get(e.code) or ("error", f"O HyperbookLM recusou o pedido (HTTP {e.code}).",
                                                           "Tente de novo; se continuar, reinicie o HyperbookLM.")
        raise Refused(code, message, action) from None
    except ValueError:  # respondeu, mas não em JSON: outro programa na porta
        raise Refused(*_REFUSED[404]) from None
    except OSError as e:  # URLError, tempo esgotado, conexão caída
        err = Unavailable("O HyperbookLM não respondeu.", "Abra-o com npm run dev na pasta dele e confira o endereço.")
        err.sent = not isinstance(getattr(e, "reason", e), ConnectionRefusedError)
        raise err from None


def detect():
    """Procura o HyperbookLM nas portas de sempre deste PC; devolve o endereço ou None. Só lê a identificação da ponte."""
    def probe(port):
        url = f"http://127.0.0.1:{port}"
        try:
            return url if _busy(url) and _call(url, "GET", "/api/lumen", auth=False).get("app") == "hyperbooklm" else None
        except AppError:
            return None
    ports = list(PORTS)
    if not ports:
        return None
    with ThreadPoolExecutor(len(ports)) as pool:
        return next((u for u in pool.map(probe, ports) if u), None)


def view(cfg=None):
    """A conexão como a interface a vê (nunca o código): off | connected | pairing | unauthorized | notfound |
    unavailable | error. “connected” é o servidor; as chaves de IA dele vêm à parte, em features (text: chat, resumo e
    mapa mental; slides), só como existe/não existe."""
    cfg = cfg or store.load_config()
    out = {"state": "off", "message": "", "features": None, "sources": None, "has_token": bool(_token()),
           "hyperbooklm_on": cfg["hyperbooklm_on"], "hyperbooklm_url": cfg["hyperbooklm_url"]}
    if not cfg["hyperbooklm_on"]:
        return out
    try:
        info = _call(cfg["hyperbooklm_url"], "GET", "/api/lumen")
        if info.get("app") != "hyperbooklm":
            raise Refused(*_REFUSED[404])
        if not out["has_token"] or not info.get("paired") or "features" not in info:
            raise Refused(*_REFUSED[503])
        out.update(state="connected", features={k: v is True for k, v in info["features"].items()}, sources=info.get("sources"))
    except AppError as e:
        out["state"] = ("unavailable" if isinstance(e, Unavailable) else
                        {"unauthorized": "unauthorized", "unpaired": "pairing", "notfound": "notfound"}.get(getattr(e, "code", ""), "error"))
        out["message"] = f"{e} {e.action}".strip()
    return out


def connect(body):
    """Guarda o endereço, liga a integração e testa. Se o HyperbookLM não está nesse endereço, procura nas portas de
    sempre e, achando, corrige o endereço (detected)."""
    url = address(body.get("url") or URL)
    with store.LOCK:
        cfg = store.load_config()
        cfg.update(hyperbooklm_url=url, hyperbooklm_on=True)
        store.save_config(cfg)
    out = view(cfg)
    if out["state"] in ("unavailable", "notfound"):
        found = detect()
        if found and found != url:
            with store.LOCK:
                cfg = store.load_config()
                cfg["hyperbooklm_url"] = found
                store.save_config(cfg)
            out = {**view(cfg), "detected": True}
    return out


def pair():
    """Gera o código de pareamento, guarda no cofre do sistema e devolve, uma única vez, a linha para o .env.local do
    HyperbookLM. O código não fica na configuração nem aparece de novo."""
    token = secrets.token_urlsafe(32)
    keyring.set_password(store.APP, "hyperbooklm", token)
    return {**view(), "line": "LUMEN_BRIDGE_TOKEN=" + token}


def disconnect():
    """Desliga e tira o código deste PC. O que já foi enviado continua no HyperbookLM."""
    with store.LOCK:
        cfg = store.load_config()
        cfg["hyperbooklm_on"] = False
        store.save_config(cfg)
    _forget_token()
    return view(cfg)


def _material(key):
    """O que vai: o título e o texto da transcrição, mais o id que a ponte também calcula a partir deles."""
    from . import jobs  # jobs importa as integrações
    entry = store.history().get(key) or {}
    tr = jobs._load(jobs.work_dir(key) / "transcript.json")
    title = " ".join(str(entry.get("title") or "").split())[:MAX_TITLE]
    if not title or not tr or not tr.get("segments"):
        raise AppError("A transcrição desta aula não está mais guardada neste PC.",
                       "O Lúmen guarda a transcrição da última aula publicada (ou de todas, com “Manter arquivos temporários” ligado).")
    text = llm.transcript_text(tr["segments"])
    if len(text.encode()) > MAX_TEXT:
        raise Refused(*_REFUSED[413])
    return title, text, "lumen-" + hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()[:32]


def _note(key, **kw):
    with store.LOCK:
        store.remember(key, {"hyperbooklm": {**((store.history().get(key) or {}).get("hyperbooklm") or {}), **kw}})


def lesson(key):
    """O envio desta aula como a interface o vê: none | sending | unconfirmed | sent | failed | missing."""
    cfg, rec = store.load_config(), (store.history().get(key) or {}).get("hyperbooklm") or {}
    return {"key": key, "state": rec.get("state") or "none", "error": rec.get("error"), "transcript": has_transcript(key),
            "open_url": cfg["hyperbooklm_url"], "target": {"on": cfg["hyperbooklm_on"], "url": cfg["hyperbooklm_url"]}}


def _stored(cfg, sid):
    return any(s.get("id") == sid for s in _call(cfg["hyperbooklm_url"], "GET", "/api/lumen/sources?meta=1").get("sources") or [])


def refresh(key):
    """Pergunta à ponte se a fonte enviada continua guardada (ela pode ter sido removida no HyperbookLM)."""
    rec = (store.history().get(key) or {}).get("hyperbooklm") or {}
    if rec.get("id") and rec.get("state") in ("sent", "missing"):
        _note(key, state="sent" if _stored(store.load_config(), rec["id"]) else "missing", error=None)
    return lesson(key)


def status(key, check=False):
    """Para o diálogo de envio: com o HyperbookLM fora do ar, devolve o último estado guardado e o aviso."""
    try:
        return refresh(key) if check else lesson(key)
    except AppError as e:
        return {**lesson(key), "offline": f"{e} {e.action}".strip()}


def send(key):
    """Envia a transcrição uma vez. Repetir o clique ou um tempo esgotado não duplicam a fonte: o id vem do conteúdo, a
    ponte devolve o mesmo id para o mesmo texto, e “enviado” só vale depois de a ponte listar a fonte guardada."""
    cfg = store.load_config()
    if not cfg["hyperbooklm_on"]:
        raise AppError("O HyperbookLM não está conectado.", "Abra Integrações → HyperbookLM e conecte.")
    title, text, sid = _material(key)
    with _SEND:
        rec = (store.history().get(key) or {}).get("hyperbooklm") or {}
        if rec.get("id") == sid and rec.get("state") == "sent" and _stored(cfg, sid):
            return {**lesson(key), "duplicate": True}  # já está lá: nada é reenviado
        _note(key, state="sending", id=sid, error=None)
        try:
            res = _call(cfg["hyperbooklm_url"], "POST", "/api/lumen/sources", body={"title": title, "text": text}, timeout=30)
            if res.get("id") != sid or not _stored(cfg, sid):
                raise AppError("O HyperbookLM não confirmou que guardou a transcrição.", "Tente de novo.")
        except Unavailable as e:
            _note(key, state="unconfirmed" if e.sent else "failed", error=f"{e} {e.action}".strip())
            raise
        except AppError as e:
            _note(key, state="failed", error=f"{e} {e.action}".strip())
            raise
        _note(key, state="sent", error=None)
    log.info("hyperbooklm: transcrição enviada (%d caracteres)", len(text))
    return {**lesson(key), "duplicate": res.get("duplicate") is True}
