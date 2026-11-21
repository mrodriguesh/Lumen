"""Rotas /api/study/* (registradas em server.ROUTES). Todas passam pela proteção do servidor (Host 127.0.0.1 +
X-Lumen-Token por sessão). Entradas são validadas aqui; segredos nunca voltam para a tela.

A conversa usa streaming: a rota devolve um Stream e o servidor manda um JSON por linha (NDJSON) conforme a resposta
é gerada. Fechar a conexão (botão Parar, janela fechada) cancela a geração."""
import re
import threading
import time
import uuid

from .. import AppError, llm
from . import (activity, agent, attachments, chats, context, data, db, diagram, explain, images, index, learn, listen,
               memory, providers, search, settings, tools, writes)
from . import registry as commands  # o registro único (o nome "registry" aqui é o das fontes, logo abaixo)
from .sources import files, registry


class Stream:
    """Resposta em streaming: um gerador de eventos e o que fazer se a conexão cair."""

    def __init__(self, events, on_close=lambda: None):
        self.events, self.on_close = events, on_close


class File:
    """Um arquivo do Lúmen servido com Range (o player de áudio pula para um capítulo sem baixar tudo)."""

    def __init__(self, path, ctype):
        self.path, self.ctype = path, ctype


_hits, _hits_lock = {}, threading.Lock()


def limit(key, per_10s):
    """Limite simples de pedidos por janela de 10 s (protege o Ollama e a API do Notion de rajadas)."""
    now = time.monotonic()
    with _hits_lock:
        recent = [t for t in _hits.get(key, []) if now - t < 10]
        if len(recent) >= per_10s:
            raise AppError("Muitos pedidos seguidos.", "Aguarde alguns segundos.")
        recent.append(now)
        _hits[key] = recent


PULL = {"model": "", "progress": 0.0, "running": False, "error": "", "done": False}


def _pull(model):
    def work():
        PULL.update(model=model, progress=0.0, running=True, error="", done=False)
        try:
            llm.pull(model, lambda p, _: PULL.update(progress=round(p, 3)), lambda: None)
            PULL.update(done=True)
            index.request()
        except AppError as e:
            PULL["error"] = str(e)
        finally:
            PULL["running"] = False
    if PULL["running"]:
        raise AppError("Já há um download de modelo em andamento.")
    threading.Thread(target=work, name="Lumen study pull", daemon=True).start()


def _str(body, key, size=500):
    v = body.get(key)
    if not isinstance(v, str):
        raise AppError("Pedido inválido.", "Recarregue a janela.")
    return v.strip()[:size]


# --- Estado e ajustes --------------------------------------------------------------------------------------------

_migrated = False


def migrate_legacy():
    """Uma vez por execução: a retirada do Gemini. Ajustes antigos que apontavam para ele voltam à IA local (com uma cópia
    .bak do original) e a chave que ele deixou no cofre é apagada. Idempotente; chamada ao abrir o servidor e no estado."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    try:
        settings.migrate()
    except OSError:  # sem permissão para gravar agora: a política já vale na leitura (settings.load), a migração tenta na próxima vez
        _migrated = False


def state(h=None):
    migrate_legacy()
    s = settings.load()
    index.start()
    attachments.sweep()  # uma vez por execução: anexos que ficaram sem conversa salva
    sources = {}
    for name, src in registry().items():
        st = src.status()
        sources[name] = {**st, "enabled": s["search"].get(name, False), "index": index.source_view(name)}
    counts = index.counts()
    with index._lock:
        progress = {**index.STATE, "embedding": dict(index.STATE["embedding"])}
    return {"settings": settings.public(s), "providers": providers.status(s), "sources": sources, "counts": counts,
            "index": progress, "pull": dict(PULL), "pending": len(writes.pending()),
            "due": learn.due(1)["total"], "projects": chats.projects(),
            "web_enabled": s["search"]["web"], "temporary_hours": chats.TEMP_HOURS}


def _settings(h):
    patch = h._json()
    conn = patch.get("connectors") if isinstance(patch, dict) and isinstance(patch.get("connectors"), dict) else {}
    if isinstance(conn.get("obsidian_output"), str):
        from .. import store, vault
        root = vault.check(store.load_config()["obsidian_vault"])
        conn["obsidian_output"] = vault.inside(root, conn["obsidian_output"]).relative_to(root).as_posix()
    if isinstance(conn.get("notion_parent"), str) and conn["notion_parent"].strip():
        from .. import notion
        conn["notion_parent"] = notion.page_id(conn["notion_parent"])
    return {"settings": settings.public(settings.save(patch))}


def _models(h):
    """Os modelos de chat instalados no Ollama (os de embeddings ficam de fora). Não há lista de modelos em nuvem."""
    return {"local": sorted(m for m in llm.models() or [] if "embed" not in m.lower())}


def _quick(h):
    """Ajustes da Conversa rápida (a barra flutuante): `quick.model` (vazio = o modelo rápido do Lúmen) e `quick.new_chat`. GET devolve o que
    está salvo, o que cada escolha resolve agora e os modelos locais que podem ser escolhidos. POST grava só estas duas chaves (mesma validação
    de /api/study/settings) ou, com {"reset": true}, volta só elas ao padrão: conversas, notas, modelos e o resto dos ajustes não são tocados."""
    if h.command == "POST":
        body = h._json()
        patch = dict(settings.DEFAULTS["quick"]) if body.get("reset") is True else {k: body[k] for k in settings.DEFAULTS["quick"] if k in body}
        if patch:
            settings.save({"quick": patch})
    return settings.quick_view()


MODEL = re.compile(r"^[\w.\-/]+(?::[\w.\-]+)?$")


def _pull_route(h):
    model = _str(h._json(), "model", 120)
    if not MODEL.match(model):
        raise AppError("Nome de modelo inválido.")
    s = settings.load()
    if model not in (s["models"]["embed"], settings.local_model(s), settings.fast_model(s), settings.max_model(s),
                     settings.adult_model(s), *filter(None, settings.RECOMMENDED.values())):
        raise AppError("Escolha o modelo nas configurações antes de baixar.")
    _pull(model)
    return {"pull": dict(PULL)}


# --- Fontes ------------------------------------------------------------------------------------------------------

def _sources(h):
    body = h._json()
    action, name = body.get("action"), body.get("source")
    if name not in ("notion", "obsidian", "files"):
        raise AppError("Fonte desconhecida.")
    src = registry()[name]
    if action == "test":
        result = src.test()
        activity.log("testar-fonte", target=src.label, result="ok" if result.get("connected") else result.get("message", ""))
        return {"result": result}
    if action in ("connect", "sync"):
        if not src.status().get("connected"):
            raise AppError(src.status().get("message") or "Fonte não conectada.")
        settings.save({"search": {name: True}})
        index.request([name])
        activity.log("sincronizar", target=src.label, result="pedido")
        return state()
    if action == "disconnect":
        settings.save({"search": {name: False}})
        removed = index.purge(name) if body.get("purge") else 0
        activity.log("desconectar-fonte", target=src.label, result=f"{removed} documento(s) tirados do índice",
                     permission="confirmado pelo usuário")
        return state()
    raise AppError("Ação desconhecida.")


def _folders(h):
    body = h._json()
    current = settings.load()["connectors"]["folders"]
    if body.get("action") == "add":
        from ..server import _protection_folder
        chosen = _protection_folder("Autorizar pasta para o Lúmen Study AI ler")
        if not chosen:
            return {"cancelled": True, **state()}
        p = str(files.validate_folder(chosen))
        if p not in current:
            settings.set_folders(current + [p])
            activity.log("autorizar-pasta", target=p, permission="leitura")
        return state()
    if body.get("action") == "remove":
        path = _str(body, "path", 1000)
        settings.set_folders([x for x in current if x != path])
        for d in db.rows("SELECT id, source_id FROM documents WHERE source = 'files'"):
            if d["source_id"] == path or d["source_id"].startswith(path.rstrip("\\/") + ("\\" if "\\" in path else "/")):
                index.remove(d["id"])
        activity.log("remover-pasta", target=path, permission="confirmado pelo usuário")
        return state()
    raise AppError("Ação desconhecida.")


# --- Busca e documentos --------------------------------------------------------------------------------------------

def _search(h):
    limit("search", 30)
    q = h._query()
    text = q.get("q", "").strip()[:500]
    if not text:
        raise AppError("Escreva o que procurar.")
    source = q.get("source", "")
    sources = [source] if source in ("notion", "obsidian", "files") else None
    project = chats.project(q["project"]) if q.get("project") else None
    r = search.search(text, sources, limit=min(int(q.get("limit") or 12), 30), project=project)
    activity.log("busca", target=f"{len(r['results'])} resultado(s)", detail="semântica" if r["semantic"] else "palavras")
    return r


def _document(h):
    return search.document(h._query().get("id", ""), full=h._query().get("full") == "1")


def _open(h):
    did = _str(h._json(), "id", 2000)
    row = db.one("SELECT * FROM documents WHERE id = ?", did)
    if not row:
        raise AppError("Documento não encontrado no índice.")
    out = registry()[row["source"]].open(row)
    activity.log("abrir", tool=row["source"], target=row["title"], permission="nível 1 · navegação pelo usuário")
    return out


# --- Conversa -------------------------------------------------------------------------------------------------------

def _turn(h):
    body = h._json()
    turn_id = body.get("turn_id") if isinstance(body.get("turn_id"), str) and re.fullmatch(r"[\w-]{8,64}", body["turn_id"]) else uuid.uuid4().hex
    return Stream(agent.turn(body, turn_id), on_close=lambda: agent.cancel(turn_id))


def _cancel(h):
    return agent.cancel(_str(h._json(), "turn_id", 64))


def _conversations(h):
    q = h._query()
    return {"conversations": chats.listing(q.get("q", "")[:200], q.get("project") or None, q.get("archived") == "1",
                                           q.get("from", "")[:10], q.get("to", "")[:10]),
            "projects": chats.projects()}


def _conversation(h):
    q = h._query()
    if q.get("brief") == "1":
        # Só o necessário para saber se algo mudou (a barra flutuante confere isto ao reabrir e enquanto espera uma
        # resposta): sem mensagens, sem consultas a ações pendentes.
        conv = chats.get(q.get("id", ""), with_messages=False)
        return {"id": conv["id"], "updated": conv["updated"], "temporary": bool(conv.get("temporary")), "generating": agent.generating(conv["id"])}
    conv = chats.get(q.get("id", ""))
    conv["pending"] = writes.pending(conv["id"])
    conv["created"] = writes.completed(conv["id"])
    conv["generating"] = agent.generating(conv["id"])
    return conv


def _context(h):
    return context.estimate(h._query().get("id", ""))


def _registry(h):
    """O menu "/" só precisa da lista (disco); o catálogo inteiro consulta o Ollama e as fontes (?full=1)."""
    q = h._query()
    if q.get("skill"):
        return commands.skill(q["skill"], editing=True)
    return commands.catalog() if q.get("full") == "1" else {"menu": commands.menu()}


def _registry_action(h):
    body = h._json()
    if body.get("action") == "enable":
        return commands.enable(_str(body, "id", 80), body.get("enabled"))
    if body.get("action") == "save":
        return commands.save_skill(body.get("name"), body.get("description", ""), body.get("args", ""), body.get("body"), body.get("revision", ""))
    raise AppError("Ação desconhecida.")


def _evaluation(h):
    from . import evaluation
    return evaluation.export()


def _conversations_action(h):
    body = h._json()
    action, cid = body.get("action"), body.get("id")
    if action == "create":
        return chats.create(body.get("project_id") or None, "", temporary=bool(body.get("temporary")))
    if action == "rename":
        return chats.update(cid, title=_str(body, "title", 200))
    if action in ("pin", "unpin"):
        return chats.update(cid, pinned=action == "pin")
    if action in ("archive", "unarchive"):
        return chats.update(cid, archived=action == "archive")
    if action == "move":
        return chats.update(cid, project_id=body.get("project_id") or None)
    if action == "memory":
        return chats.update(cid, memory=bool(body.get("on")))
    if action == "compact":  # /compact [foco] e o botão do medidor: resume as antigas para a IA, sem apagar nada
        limit(f"compact:{cid}", 2)
        return context.compact_now(_str(body, "id", 64), str(body.get("focus") or "")[:300])
    if action == "pin_message":
        mid = body.get("message_id")
        if not isinstance(mid, (int, str)) or isinstance(mid, bool):
            raise AppError("Pedido inválido.")
        return chats.pin_message(_str(body, "id", 64), mid, bool(body.get("pinned")))
    if action == "delete":
        n = chats.delete([cid])
    elif action == "delete_many":
        ids = body.get("ids") if isinstance(body.get("ids"), list) else []
        n = chats.delete(ids)
    elif action == "delete_all":
        if body.get("confirm") != "APAGAR":
            raise AppError("Confirme digitando APAGAR.")
        n = chats.delete_all()
    else:
        raise AppError("Ação desconhecida.")
    activity.log("apagar-conversas", target=f"{n} conversa(s)", permission="confirmado pelo usuário")
    return {"deleted": n}


def _export(h):
    q = h._query()
    fmt = "json" if q.get("format") == "json" else "md"
    conv = chats.get(q.get("id", ""), with_messages=False)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", conv["title"] or "Conversa").strip()[:60] or "Conversa"
    return {"filename": f"{name}.{fmt}", "content": chats.export(conv["id"], fmt)}


def _projects(h):
    return {"projects": chats.projects(include_archived=h._query().get("archived") == "1")}


def _projects_action(h):
    body = h._json()
    action = body.get("action")
    if action == "save":
        return chats.save_project(body.get("project") if isinstance(body.get("project"), dict) else {})
    if action == "delete":
        chats.delete_project(_str(body, "id", 64))
        activity.log("apagar-projeto", target=body.get("id"), permission="confirmado pelo usuário")
        return {"ok": True}
    if action in ("pin", "unpin"):
        return chats.pin_document(_str(body, "id", 64), _str(body, "doc_id", 2000), action == "pin")
    raise AppError("Ação desconhecida.")


# --- Anexos e imagens ------------------------------------------------------------------------------------------------

def _attach(h):
    """Corpo binário (o arquivo), com o nome em ?name=. O tipo é conferido pelos bytes, não pelo nome."""
    limit("attach", 20)
    n, got = max(0, int(h.headers.get("Content-Length") or 0)), [0]

    def read(k):
        b = h.rfile.read(k)
        got[0] += len(b)
        return b
    try:
        return attachments.receive(read, n, h._query().get("name", ""))
    except AppError as e:
        if got[0] < n:  # lê o resto antes de responder: com o corpo por ler, o Windows derruba a conexão
            from ..server import _refuse
            _refuse(h, n - got[0], e)
        raise


def _attachments(h):
    q = h._query()
    if q.get("conversation"):
        recs = attachments.listing(q["conversation"][:64])
    else:
        recs = []
        for aid in q.get("ids", "").split(",")[:attachments.MAX_PER_CONV]:
            try:
                recs.append(attachments.get(aid.strip()[:64]))
            except AppError:
                continue
    return {"attachments": [attachments.public(r) for r in recs]}


def _attachment_action(h):
    body = h._json()
    aid = _str(body, "id", 64)
    if body.get("action") == "remove":
        return attachments.remove(aid)
    if body.get("action") == "index":
        out = attachments.add_to_index(aid)
        activity.log("indexar-anexo", target=out["name"], permission="confirmado pelo usuário")
        return out
    raise AppError("Ação desconhecida.")


def _image(h):
    """Miniatura (JPEG): ?h= imagem de uma nota, pelo hash; ?a= anexo de imagem."""
    q = h._query()
    try:
        if images.HASH.fullmatch(q.get("h", "")):
            return images.path(q["h"]).read_bytes()
        rec = attachments.get(q.get("a", "")[:64])
        return (attachments.folder(rec["id"]) / "miniatura.jpg").read_bytes()
    except OSError:
        raise AppError("Imagem não encontrada.") from None


# --- Memória --------------------------------------------------------------------------------------------------------

def _memories(h):
    q = h._query()
    return {"memories": memory.listing(q.get("q", "")[:200], q.get("category") or None, q.get("project") or None,
                                       q.get("status") or None), "categories": memory.CATEGORIES}


def _memories_action(h):
    body = h._json()
    action = body.get("action")
    if action == "create":
        m = memory.create(_str(body, "content", 600), body.get("category"), body.get("project_id") or None, {"type": "manual"})
        activity.log("memoria", target="criada", permission="usuário")
        return m
    if action == "update":
        return memory.update(int(body["id"]), body.get("content"), body.get("category"),
                             body.get("project_id", "keep") if "project_id" in body else "keep", body.get("status"))
    if action == "approve":
        return memory.update(int(body["id"]), status="active")
    if action in ("delete", "reject"):
        memory.delete(int(body["id"]))
        activity.log("memoria", target="apagada", permission="usuário")
        return {"ok": True}
    if action == "clear":
        n = memory.clear(body.get("category") or None, body.get("project_id") or None)
        activity.log("memoria", target=f"{n} apagada(s)", permission="confirmado pelo usuário")
        return {"deleted": n}
    if action == "clear_all":
        if body.get("confirm") != "APAGAR":
            raise AppError("Confirme digitando APAGAR.")
        n = memory.clear()
        activity.log("memoria", target=f"todas ({n}) apagadas", permission="confirmado pelo usuário")
        return {"deleted": n}
    if action == "import_preview":
        return {"items": memory.import_preview()}
    if action == "import":
        items = body.get("items") if isinstance(body.get("items"), list) else []
        n = memory.import_items(items)
        activity.log("memoria", target=f"{n} importada(s)", permission="usuário")
        return {"imported": n}
    if action == "export":
        return {"filename": "Lumen - memorias.json", "content": __import__("json").dumps(memory.export(), ensure_ascii=False, indent=1)}
    if action == "analyze":
        chain, reasons = providers.chain()
        if not chain:
            raise AppError("Nenhuma IA disponível. " + " ".join(reasons))
        return {"suggested": memory.analyze(chain[0])}
    raise AppError("Ação desconhecida.")


def _feedback(h):
    body = h._json()
    return memory.feedback(int(body.get("message_id")), int(body.get("value") or 0), str(body.get("correction") or ""))


# --- Estudar ---------------------------------------------------------------------------------------------------------

def _learn(h):
    limit("learn", 4)
    body = h._json()
    kind = body.get("kind")
    if kind not in learn.KINDS:
        raise AppError("Modo de estudo desconhecido.")
    topic = _str(body, "topic", 300)
    if not topic:
        raise AppError("Escreva o assunto.")
    project = chats.project(body["project_id"]) if body.get("project_id") else None
    chain, reasons = providers.chain(None)
    if not chain:
        raise AppError("Nenhuma IA disponível. " + " ".join(reasons))
    ctx = tools.Ctx("", project, chain[0].name)
    found = search.search(topic, project=project)
    for item in found["results"]:
        ctx.cite(item)
    level = body.get("level") if body.get("level") in ("basico", "intermediario", "avancado") else ""
    return learn.generate(kind, topic, chain[0], ctx, project, "", level, application=_str(body, "application", 2000))


def _applied(h):
    from . import applied
    body = h._json()
    iid = _str(body, "id", 64)
    if body.get("action") == "event" and not iid:
        iid = next((r["id"] for r in db.rows("SELECT id, data FROM items WHERE kind = 'action'")
                    if db.loads(r["data"], {}).get("focus")), "")
        if not iid:
            return {"ok": True}
    if body.get("action") == "submit":
        limit("submit", 4)
        it = learn.item(iid)
        project = chats.project(it["project_id"]) if it.get("project_id") else None
        chain, reasons = providers.chain(None)
        if not chain:
            raise AppError("Nenhuma IA disponível. " + " ".join(reasons))
        return applied.submit(iid, body.get("text", ""), body.get("attachments", []), chain[0])
    return applied.action(iid, body.get("action"), body.get("index"), body.get("done"))


def _feynman(h):
    """Explique com as suas palavras (texto ou o que o "apertar para falar" transcreveu): corrigido contra as notas."""
    limit("feynman", 4)
    body = h._json()
    topic = _str(body, "topic", 200)
    project = chats.project(body["project_id"]) if body.get("project_id") else None
    chain, reasons = providers.chain(None)
    if not chain:
        raise AppError("Nenhuma IA disponível. " + " ".join(reasons))
    ctx = tools.Ctx("", project, chain[0].name)
    for item in search.search(topic, project=project)["results"]:
        ctx.cite(item)
    return explain.feynman(topic, body.get("text"), chain[0], ctx, project["id"] if project else None)


def _items(h):
    q = h._query()
    return {"items": learn.items(q.get("kind") or None, q.get("project") or None)}


def _item(h):
    it = learn.item(h._query().get("id", ""))
    if h._query().get("format") == "md":
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", it["title"]).strip()[:80] or "Estudo"
        return {"filename": f"{name}.md", "content": _item_markdown(it)}
    return it


def _items_action(h):
    body = h._json()
    if body.get("action") == "delete":
        learn.delete_item(_str(body, "id", 64))
        return {"ok": True}
    if body.get("action") == "save_answer":
        msg = db.one("SELECT * FROM messages WHERE id = ?", int(body.get("message_id")))
        if not msg or msg["role"] != "assistant":
            raise AppError("Resposta não encontrada.")
        title = _str(body, "title", 120) or "Resposta salva"
        return learn.save("answer", title, {"content": msg["content"], "sources": db.loads(msg["sources"], [])},
                          None, msg["conversation_id"])
    raise AppError("Ação desconhecida.")


def _due(h):
    q = h._query()
    return learn.due(int(q.get("limit") or 50), q.get("deck") or None, q.get("project") or None)


def _review(h):
    body = h._json()
    return learn.review(int(body.get("card_id")), int(body.get("grade")))


def _quiz(h):
    body = h._json()
    chain, _ = providers.chain()
    return learn.answer(_str(body, "item_id", 64), body.get("index"), body.get("response"), chain[0] if chain else None)


def _check(h):
    """Resposta do estudante à checagem de uma explicação: corrigida e registrada no modelo do estudante."""
    limit("check", 10)
    body = h._json()
    conv = chats.get(_str(body, "conversation_id", 64))
    msg = next((m for m in conv["messages"] if str(m["id"]) == str(body.get("message_id")) and m["role"] == "assistant"), None)
    if not msg:
        raise AppError("Resposta não encontrada.")
    project = chats.project(conv["project_id"]) if conv.get("project_id") else None
    chain, _ = providers.chain(None)
    return explain.grade(msg["meta"], body.get("response"), chain[0] if chain else None, conv.get("project_id"),
                         record=not conv.get("temporary"))  # temporária: corrige, mas não guarda (D13)


def _diagram(h):
    """O diagrama (a spec que a tela recebeu, conferida de novo aqui) como imagem para baixar: PNG ou GIF."""
    limit("diagram", 6)
    body = h._json()
    try:
        return diagram.image(body.get("spec"), "gif" if body.get("format") == "gif" else "png")
    except (ValueError, TypeError, KeyError):
        raise AppError("Diagrama inválido.") from None


# --- Gravações com prévia ------------------------------------------------------------------------------------------

def _item_markdown(it):
    d, k = it["data"], it["kind"]
    lines = [f"# {it['title']}", ""]
    if k == "answer":
        lines.append(d.get("content", ""))
    elif k in ("exercise", "action"):
        from . import applied
        lines.append(applied.markdown(d, k))
    elif k == "flashcards":
        for c in d.get("cards", []):
            lines += [f"**{c['question']}**", "", c["answer"], "", f"_{c.get('explanation', '')}_" if c.get("explanation") else "", ""]
    elif k == "quiz":
        for i, q in enumerate(d.get("questions", []), 1):
            lines += [f"{i}. {q['question']}"] + [f"   - {o}" for o in q.get("options", [])] + [f"   Resposta: {q['answer']}", ""]
    elif k == "plan":
        lines += [d.get("goal", ""), "", "## Pré-requisitos"] + [f"- {p['topic']}: {p['why']}" for p in d.get("prerequisites", [])]
        lines += ["", "## Etapas"] + [f"1. **{s['title']}** ({s['minutes']} min): {s['objective']}" for s in d.get("steps", [])]
        lines += ["", "## Revisões"] + [f"- Dia {r['after_days']}: {r['focus']}" for r in d.get("reviews", [])]
    elif k == "gaps":
        lines += ["## Já estudado"] + [f"- {x['topic']}" for x in d.get("known", [])]
        lines += ["", "## Falta estudar"] + [f"- **{x['topic']}**: {x['why']}" for x in d.get("missing", [])]
        lines += ["", "## Próximos passos"] + [f"- {x}" for x in d.get("next", [])]
    elif k == "map":
        lines += [f"- {e['from']} → {e['to']} ({e['label']})" for e in d.get("edges", [])]
    elif k == "mindmap":
        nodes = d["diagram"]["nodes"]
        for i, n in enumerate(nodes):
            if n["parent"] < 0:
                lines.append(f"- **{n['label']}**" + (f": {n['detail']}" if n["detail"] else ""))
                lines += [f"    - {c['label']}" + (f": {c['detail']}" if c["detail"] else "") for c in nodes if c["parent"] == i]
    elif k == "audio":  # o roteiro da revisão em áudio: pergunta e resposta escondida (callout recolhido do Obsidian)
        lines += [d.get("intro", ""), ""]
        for ch in d.get("chapters", []):
            lines += [f"## {ch['title']}", ""]
            for q in ch["items"]:
                lines += [f"> [!question]- {q['question']}", f"> {q['answer']}", ""]
        lines.append(d.get("outro", ""))
    return "\n".join(lines)


def _save(h):
    """Prepara a gravação de uma resposta ou item salvo (vira prévia pendente; grava só depois de confirmar)."""
    body = h._json()
    dest = body.get("destination")
    if dest not in ("obsidian", "notion"):
        raise AppError("Escolha Obsidian ou Notion.")
    title = _str(body, "title", 120) or "Estudo"
    if body.get("artifact_id"):
        from . import artifacts
        return artifacts.prepare(_str(body, "artifact_id", 64), dest, title)
    visual = None
    if body.get("message_id"):
        msg = db.one("SELECT * FROM messages WHERE id = ?", int(body["message_id"]))
        if not msg or msg["role"] != "assistant":
            raise AppError("Resposta não encontrada.")
        question = db.one("SELECT content FROM messages WHERE conversation_id = ? AND id < ? AND role = 'user' ORDER BY id DESC LIMIT 1",
                          msg["conversation_id"], msg["id"])
        sources = [x for x in db.loads(msg["sources"], []) if x.get("cited")] or db.loads(msg["sources"], [])
        answer, cid = msg["content"], msg["conversation_id"]
        request = question["content"] if question else ""
        visual = db.loads(msg["meta"], {}).get("explain", {}).get("diagram")
    elif body.get("item_id"):
        it = learn.item(_str(body, "item_id", 64))
        answer, sources, cid, request = _item_markdown(it), it["data"].get("sources", []), it.get("conversation_id") or "", it["title"]
        visual = it["data"].get("diagram")
    else:
        raise AppError("Nada para salvar.")
    if dest == "obsidian":
        out = writes.prepare("obsidian-note", title, writes.note_markdown(title, request, answer, sources), cid)
        aid = f"rev-{it['id']}" if body.get("item_id") and it["kind"] == "audio" else None
        if aid and body.get("with_audio") and (listen.AUDIO / f"{aid}.m4a").exists():  # o áudio entra pela mesma prévia (D11)
            preview = writes.with_audio(writes.pending_preview(out["id"]), aid, listen.AUDIO / f"{aid}.m4a", title)
            writes.update_preview(out["id"], preview)
            out = {"id": out["id"], **preview}
    else:
        refs = "\n".join(f"- {s.get('title', '')} ({s.get('source', '')})" + (f" — {s['url']}" if s.get('url') else "") for s in sources)
        out = writes.prepare("notion-page", title, answer + ("\n\n## Fontes\n" + refs if refs else ""), cid)
    return writes.with_diagram(out, visual) if visual else out


def _pending(h):
    return {"pending": writes.pending(h._query().get("conversation") or None)}


def _pending_action(h):
    body = h._json()
    aid = _str(body, "id", 64)
    if body.get("decision") == "confirm":
        return writes.confirm(aid, body.get("title"), body.get("content"))
    if body.get("decision") == "cancel":
        return writes.cancel(aid)
    if body.get("decision") == "undo":
        return writes.undo(aid)
    raise AppError("Decisão inválida.")


def _open_app(h):
    from . import apps
    body = h._json()
    if set(body) != {"app"}:
        raise AppError("Escolha somente o aplicativo da lista.")
    return apps.open_app(_str(body, "app", 30), confirmed=True)


def _browser(h):
    from . import browser
    return browser.state(h._query().get("conversation", ""))


def _browser_action(h):
    from . import browser
    body = h._json()
    return browser.control(_str(body, "id", 64), _str(body, "action", 20))


# --- Atividade e dados ---------------------------------------------------------------------------------------------

def _activity(h):
    return {"activity": activity.recent(min(int(h._query().get("limit") or 200), 1000))}


def _data(h):
    data.retention()
    return data.inventory()


def _data_action(h):
    body = h._json()
    action = body.get("action")
    if action == "export":
        return {"filename": "Lumen Study AI - dados.json", "content": data.export_json()}
    if action == "delete":
        category = body.get("category")
        if category not in data.CATEGORIES:
            raise AppError("Categoria desconhecida.")
        return {"deleted": data.delete(category), **data.inventory()}
    if action == "delete_all":
        if body.get("confirm") != "APAGAR TUDO":
            raise AppError("Confirme digitando APAGAR TUDO.")
        return {"deleted": data.delete_all(), **data.inventory()}
    raise AppError("Ação desconhecida.")


ROUTES = {
    ("GET", "/api/study/state"): state,
    ("POST", "/api/study/settings"): _settings,
    ("GET", "/api/study/models"): _models,
    ("GET", "/api/study/quick"): _quick,
    ("POST", "/api/study/quick"): _quick,
    ("POST", "/api/study/pull"): _pull_route,
    ("POST", "/api/study/sources"): _sources,
    ("POST", "/api/study/folders"): _folders,
    ("GET", "/api/study/search"): _search,
    ("GET", "/api/study/document"): _document,
    ("POST", "/api/study/open"): _open,
    ("POST", "/api/study/turn"): _turn,
    ("POST", "/api/study/cancel"): _cancel,
    ("GET", "/api/study/conversations"): _conversations,
    ("GET", "/api/study/conversation"): _conversation,
    ("POST", "/api/study/conversations"): _conversations_action,
    ("GET", "/api/study/context"): _context,
    ("GET", "/api/study/registry"): _registry,
    ("GET", "/api/study/export"): _export,
    ("GET", "/api/study/projects"): _projects,
    ("POST", "/api/study/projects"): _projects_action,
    ("GET", "/api/study/memories"): _memories,
    ("POST", "/api/study/memories"): _memories_action,
    ("POST", "/api/study/feedback"): _feedback,
    ("POST", "/api/study/registry"): _registry_action,
    ("GET", "/api/study/evaluation"): _evaluation,
    ("POST", "/api/study/applied"): _applied,
    ("POST", "/api/study/learn"): _learn,
    ("POST", "/api/study/feynman"): _feynman,
    ("GET", "/api/study/items"): _items,
    ("GET", "/api/study/item"): _item,
    ("POST", "/api/study/items"): _items_action,
    ("GET", "/api/study/due"): _due,
    ("POST", "/api/study/review"): _review,
    ("POST", "/api/study/quiz"): _quiz,
    ("POST", "/api/study/check"): _check,
    ("POST", "/api/study/diagram"): _diagram,
    ("POST", "/api/study/save"): _save,
    ("GET", "/api/study/pending"): _pending,
    ("POST", "/api/study/pending"): _pending_action,
    ("POST", "/api/study/open-app"): _open_app,
    ("GET", "/api/study/browser"): _browser,
    ("POST", "/api/study/browser"): _browser_action,
    ("GET", "/api/study/activity"): _activity,
    ("POST", "/api/study/attachments"): _attach,
    ("GET", "/api/study/attachments"): _attachments,
    ("POST", "/api/study/attachment"): _attachment_action,
    ("GET", "/api/study/image"): _image,
    ("GET", "/api/study/data"): _data,
    ("POST", "/api/study/data"): _data_action,
}
