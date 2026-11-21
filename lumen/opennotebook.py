"""Open Notebook: a transcrição de uma aula vira uma fonte de texto num caderno, pela API REST dele. Vão só o texto e os
metadados (título, curso/módulo, data, idioma, link da fonte); nunca áudio, vídeo nem acesso ao banco dele. É independente
do Notion e do Obsidian: uma falha aqui não desfaz nem bloqueia nada. A senha (opcional) fica no cofre do sistema e só sai
daqui no cabeçalho do pedido.

Rotas (conferidas no /openapi.json da versão 1.15.1): GET /api/config, GET|POST /api/notebooks, GET /api/models/defaults,
POST /api/sources (multipart, async_processing), GET /api/sources, GET /api/sources/{id}/status, POST /api/sources/{id}/retry."""
import hashlib
import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import keyring

from . import AppError, catalog, llm, package, store

log = logging.getLogger("lumen")
NOTEBOOK = "Lúmen — Transcrições"
API, UI = "http://127.0.0.1:5055", "http://127.0.0.1:3000"
_SEND = threading.Lock()  # um envio (ou criação de caderno) por vez: dois cliques não criam duas fontes
# status do Open Notebook → estado mostrado no Lúmen (None: fonte sem comando, já pronta)
_STATES = {"new": "queued", "queued": "queued", "running": "processing", "completed": "completed", None: "completed",
           "failed": "failed"}


class Unavailable(AppError):
    """Sem resposta. sent: o pedido pode ter chegado ao servidor (tempo esgotado, conexão caída) ou não (recusada)."""
    sent = True


class NeedsPassword(AppError):
    pass


class Missing(AppError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # um redirecionamento levaria a senha e a transcrição a outro endereço
        return None


# Conexão direta: a transcrição não passa pelo proxy do sistema.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def address(raw):
    """Endereço http(s) sem usuário, senha, consulta nem fragmento (o que a interface manda é conferido aqui)."""
    u = urllib.parse.urlsplit(str(raw or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise AppError("Endereço do Open Notebook inválido.", "Use algo como http://127.0.0.1:5055.")
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"[:300]


def _password():
    try:
        return keyring.get_password(store.APP, "opennotebook")
    except keyring.errors.KeyringError:
        return None


def _forget_password():
    try:
        keyring.delete_password(store.APP, "opennotebook")
    except keyring.errors.KeyringError:
        pass


def _call(cfg, method, path, body=None, form=None, timeout=8, password=None):
    """Um pedido à API. Os erros viram AppError com o que fazer; nem a senha nem o corpo vão para o log."""
    headers = {"Accept": "application/json"}
    password = password or _password()
    if password:
        headers["Authorization"] = "Bearer " + password
    data = None
    if form is not None:
        mark = uuid.uuid4().hex
        data = b"".join(f'--{mark}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode() + str(v).encode() + b"\r\n"
                        for k, v in form.items()) + f"--{mark}--\r\n".encode()
        headers["Content-Type"] = "multipart/form-data; boundary=" + mark
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(cfg["opennotebook_url"] + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            e.close()
        if e.code == 401:
            raise NeedsPassword("O Open Notebook pede uma senha.", "Informe a senha em Integrações → Open Notebook.") from None
        if e.code == 404:
            raise Missing("O Open Notebook não encontrou este item.", "") from None
        try:
            detail = str(json.loads(e.read()).get("detail") or "")[:200]
        except (ValueError, AttributeError, OSError):
            detail = ""
        finally:
            e.close()
        raise AppError(f"O Open Notebook recusou o pedido (HTTP {e.code}).", detail or "Confira o endereço da API.") from None
    except (OSError, ValueError) as e:  # URLError, tempo esgotado, conexão caída, resposta que não é JSON
        err = Unavailable("O Open Notebook não respondeu.", "Confira se ele está aberto e o endereço da API.")
        err.sent = not isinstance(getattr(e, "reason", e), ConnectionRefusedError)
        raise err from None


def notebook_url(cfg, notebook):
    return f"{cfg['opennotebook_ui']}/notebooks/{urllib.parse.quote(notebook, safe='')}" if notebook else cfg["opennotebook_ui"]


def view(cfg=None):
    """A conexão como a interface a vê (nunca a senha): off | connected | unavailable | password | error."""
    cfg = cfg or store.load_config()
    out = {"state": "off", "message": "", "version": "", "notebooks": [], "has_password": bool(_password()),
           "open_url": notebook_url(cfg, cfg["opennotebook_notebook"]), "name": NOTEBOOK,
           **{k: cfg[k] for k in store.DEFAULTS if k.startswith("opennotebook_")}}
    if not cfg["opennotebook_on"]:
        return out
    try:
        conf = _call(cfg, "GET", "/api/config", timeout=5) or {}
        if conf.get("dbStatus") != "online":  # a API de pé sem o banco não é “conectado”
            raise Unavailable("A API do Open Notebook respondeu, mas o banco de dados dele está fora do ar.", "Inicie o banco e teste de novo.")
        out["notebooks"] = [{"id": n["id"], "name": n["name"], "archived": bool(n.get("archived")),
                             "sources": n.get("source_count") or 0} for n in _call(cfg, "GET", "/api/notebooks", timeout=5)]
        out["version"] = str(conf.get("version") or "")[:20]
        out["state"] = "connected"
    except AppError as e:
        out["state"] = "password" if isinstance(e, NeedsPassword) else "unavailable" if isinstance(e, Unavailable) else "error"
        out["message"] = f"{e} {e.action}".strip()
    from . import onlocal  # onlocal importa este módulo
    out["local"] = onlocal.view(cfg)  # o que está parado neste PC e se dá para iniciar por aqui
    out["ui_state"] = onlocal.ui_state(cfg["opennotebook_ui"], cfg["opennotebook_url"])  # conferida à parte; a página decide o que fazer
    if out["ui_state"] != "ok":  # o endereço salvo é de outro programa (ou está parado): a interface pode estar em outra porta
        found = onlocal.find_ui(cfg["opennotebook_ui"], cfg["opennotebook_url"])
        if found:
            onlocal.remember_ui(found)
            out.update(ui_state="ok", opennotebook_ui=found, open_url=notebook_url({**cfg, "opennotebook_ui": found}, cfg["opennotebook_notebook"]))
    out["ui_ok"] = out["ui_state"] == "ok"
    return out


def connect(body):
    """Guarda os endereços (e a senha, se veio), liga a integração e testa. Senha recusada não é guardada; endereço novo
    não herda a senha nem o caderno do antigo."""
    api, ui, pw = address(body.get("url") or API), address(body.get("ui") or UI), str(body.get("password") or "")
    with store.LOCK:
        cfg = store.load_config()
        if api != cfg["opennotebook_url"]:
            cfg["opennotebook_notebook"] = cfg["opennotebook_notebook_name"] = ""
            _forget_password()
        cfg.update(opennotebook_url=api, opennotebook_ui=ui, opennotebook_on=True)
        store.save_config(cfg)
    if pw:
        try:
            _call(cfg, "GET", "/api/notebooks", timeout=5, password=pw)
        except NeedsPassword:
            raise AppError("O Open Notebook recusou esta senha.", "Confira a senha (OPEN_NOTEBOOK_PASSWORD) e tente de novo.") from None
        except AppError:
            pass  # serviço parado: a senha fica guardada e é conferida quando ele voltar
        keyring.set_password(store.APP, "opennotebook", pw)
    return view(cfg)


def disconnect():
    """Desliga e tira a senha deste PC. Os cadernos e as fontes no Open Notebook ficam."""
    with store.LOCK:
        cfg = store.load_config()
        cfg["opennotebook_on"] = False
        store.save_config(cfg)
    _forget_password()
    return view(cfg)


def choose(body):
    """Caderno de destino: um que já existe ou, a pedido, o “Lúmen — Transcrições” (reaproveitado se já existir; nenhum
    caderno existente é alterado)."""
    cfg = store.load_config()
    with _SEND:
        books = _call(cfg, "GET", "/api/notebooks", timeout=8)
        if body.get("create") is True:
            book = next((n for n in books if n["name"] == NOTEBOOK), None) or _call(
                cfg, "POST", "/api/notebooks", body={"name": NOTEBOOK, "description": "Transcrições enviadas pelo Lúmen."}, timeout=15)
        else:
            book = next((n for n in books if n["id"] == body.get("id")), None)
            if not book:
                raise AppError("Este caderno não existe mais no Open Notebook.", "Recarregue a lista e escolha outro.")
    with store.LOCK:
        cfg = store.load_config()
        cfg["opennotebook_notebook"], cfg["opennotebook_notebook_name"] = book["id"], str(book["name"])[:200]
        store.save_config(cfg)
    return view(cfg)


def has_transcript(key):
    from . import jobs  # jobs importa este módulo (envio automático)
    return (jobs.work_dir(key) / "transcript.json").is_file()


def _material(key):
    """Título, texto e hash do que vai para o Open Notebook: os metadados e a transcrição, só texto."""
    from . import jobs
    entry = store.history().get(key) or {}
    tr = jobs._load(jobs.work_dir(key) / "transcript.json")
    if not entry.get("title") or not tr or not tr.get("segments"):
        raise AppError("A transcrição desta aula não está mais guardada neste PC.",
                       "O Lúmen guarda a transcrição da última aula publicada (ou de todas, com “Manter arquivos temporários” ligado).")
    lid = entry.get("lumen_id") or package.lumen_id(key)
    try:
        pkg = package.load(lid)
    except AppError:
        pkg = {}
    meta = [("Organização", " › ".join(catalog.breadcrumb(entry.get("classification")))), ("Data", pkg.get("date")),
            ("Idioma", tr.get("language")), ("Fonte", (pkg.get("source") or {}).get("link")), ("Enviado pelo Lúmen", lid)]
    text = "\n".join([f"# {entry['title']}", "", *[f"- {k}: {v}" for k, v in meta if v], "", "## Transcrição", "",
                      llm.transcript_text(tr["segments"])])
    return entry["title"], text, hashlib.sha256(text.encode()).hexdigest(), lid


def _note(key, **kw):
    kw["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with store.LOCK:
        store.remember(key, {"opennotebook": {**((store.history().get(key) or {}).get("opennotebook") or {}), **kw}})


def lesson(key):
    """O envio desta aula como a interface o vê: none | sending | unconfirmed | queued | processing | completed | failed |
    missing | unknown, e de onde abrir."""
    cfg, on = store.load_config(), (store.history().get(key) or {}).get("opennotebook") or {}
    return {"key": key, "state": on.get("state") or "none", "error": on.get("error"), "at": on.get("at"),
            "notebook_name": on.get("notebook_name") or cfg["opennotebook_notebook_name"], "transcript": has_transcript(key),
            "open_url": notebook_url(cfg, on.get("notebook") or cfg["opennotebook_notebook"]),
            "target": {"on": cfg["opennotebook_on"], "notebook_name": cfg["opennotebook_notebook_name"], "url": cfg["opennotebook_url"]}}


def refresh(key):
    """Pergunta ao Open Notebook o estado real da fonte e guarda no manifesto."""
    on = (store.history().get(key) or {}).get("opennotebook") or {}
    if on.get("source"):
        try:
            st = _call(store.load_config(), "GET", f"/api/sources/{urllib.parse.quote(on['source'], safe='')}/status")
            state = _STATES.get(st.get("status"), "unknown")
            err = ((st.get("processing_info") or {}).get("error") or st.get("message")) if state == "failed" else None
            _note(key, state=state, error=str(err)[:300] if err else None)
        except Missing:
            _note(key, state="missing", error=None)
    return lesson(key)


def status(key, check=False):
    """Para a interface acompanhar o envio: com o Open Notebook fora do ar, devolve o último estado guardado e o aviso."""
    try:
        return refresh(key) if check else lesson(key)
    except (Unavailable, NeedsPassword) as e:
        return {**lesson(key), "offline": f"{e} {e.action}".strip()}


def _find(cfg, on, title, lid):
    """Um envio sem resposta pode ter criado a fonte. Procura no caderno pelo título: fonte já processada tem de trazer o
    lumen_id no texto; a que ainda está na fila (sem texto) tem de ser de depois da tentativa (5 min de folga de relógio)."""
    since = datetime.fromisoformat(on["at"]) - timedelta(minutes=5)
    query = urllib.parse.urlencode({"notebook_id": on["notebook"], "limit": 100, "sort_by": "created"})
    for s in _call(cfg, "GET", "/api/sources?" + query, timeout=10):
        if s.get("title") != title:
            continue
        full = _call(cfg, "GET", "/api/sources/" + urllib.parse.quote(s["id"], safe=""), timeout=10).get("full_text")
        try:
            made = datetime.fromisoformat(str(s.get("created")).replace("Z", "+00:00"))
            recent = (made if made.tzinfo else made.replace(tzinfo=timezone.utc)) >= since
        except ValueError:
            recent = False
        if lid in full if full else recent:
            return s["id"]
    return None


def send(key):
    """Envia a transcrição uma vez. Repetir o clique, reabrir o app ou um tempo esgotado não duplicam a fonte: o manifesto
    guarda o hash e o id remoto, e um envio sem confirmação é procurado no caderno antes de qualquer nova tentativa."""
    cfg = store.load_config()
    if not cfg["opennotebook_on"]:
        raise AppError("O Open Notebook não está conectado.", "Abra Integrações → Open Notebook e conecte.")
    book = cfg["opennotebook_notebook"]
    if not book:
        raise AppError("Escolha o caderno de destino.", "Abra Integrações → Open Notebook e escolha um caderno.")
    title, text, digest, lid = _material(key)
    with _SEND:
        on = (store.history().get(key) or {}).get("opennotebook") or {}
        if on.get("hash") == digest and on.get("notebook") == book:
            if on.get("state") in ("sending", "unconfirmed"):
                found = _find(cfg, on, title, lid)
                if found:
                    _note(key, source=found, state="queued", error=None)
                    return refresh(key)
            elif on.get("source"):
                cur = refresh(key)
                if cur["state"] == "failed":  # falhou lá: o próprio Open Notebook reprocessa a mesma fonte
                    _call(cfg, "POST", f"/api/sources/{urllib.parse.quote(on['source'], safe='')}/retry", timeout=30)
                    _note(key, state="queued", error=None)
                    return lesson(key)
                if cur["state"] != "missing":
                    return cur  # já está lá: nada é reenviado
        # sem modelo de embeddings configurado lá, pedir a indexação faria o processamento falhar
        embed = bool((_call(cfg, "GET", "/api/models/defaults") or {}).get("default_embedding_model"))
        _note(key, state="sending", hash=digest, notebook=book, notebook_name=cfg["opennotebook_notebook_name"], source=None,
              error=None)
        try:
            src = _call(cfg, "POST", "/api/sources", timeout=30, form={
                "type": "text", "title": title, "content": text, "notebooks": json.dumps([book]),
                "embed": str(embed).lower(), "async_processing": "true"})
        except Unavailable as e:
            _note(key, state="unconfirmed" if e.sent else "failed", error=f"{e} {e.action}".strip())
            raise
        except AppError as e:
            _note(key, state="failed", error=f"{e} {e.action}".strip())
            raise
        _note(key, source=src["id"], state=_STATES.get(src.get("status"), "queued"))
    log.info("open notebook: transcrição enviada (%d caracteres)", len(text))
    return lesson(key)


def auto(key):
    """Envio automático ao terminar a aula (desligado por padrão), fora da tarefa: nunca atrasa nem derruba a entrega."""
    cfg = store.load_config()
    if not (cfg["opennotebook_on"] and cfg["opennotebook_auto"] and cfg["opennotebook_notebook"]):
        return

    def run():
        try:
            send(key)
        except AppError as e:
            log.warning("open notebook: envio automático não concluído (%s)", type(e).__name__)
        except Exception as e:  # noqa: BLE001 — o material já está salvo nos outros destinos
            log.error("open notebook: erro inesperado no envio automático (%s)", type(e).__name__)
    threading.Thread(target=run, daemon=True).start()
