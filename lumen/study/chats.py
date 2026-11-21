"""Conversas e projetos do Lúmen Study AI.

Conversa temporária: só na memória deste processo (nunca no banco, no índice de busca nem no histórico), sem criar
memórias; some ao fechar o Lúmen ou depois de 24 h sem uso. Apagar conversas apaga mensagens e o índice de busca
delas; documentos do Notion e do Obsidian nunca são tocados. Memórias têm vida própria (apagadas na central de memória)."""
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from .. import AppError, vault
from . import db

TEMP, _temp_lock = {}, threading.Lock()
TEMP_HOURS = 24


def _expire():
    limit = time.monotonic() - TEMP_HOURS * 3600
    with _temp_lock:
        old = [k for k, v in TEMP.items() if v["touched"] < limit]
        for cid in old:
            TEMP.pop(cid, None)
    if old:
        from . import attachments
        attachments.drop(old)


def is_temp(cid):
    return cid in TEMP


def create(project_id=None, title="", temporary=False, provider="", model=""):
    if project_id and not db.one("SELECT id FROM projects WHERE id = ?", project_id):
        raise AppError("Projeto não encontrado.")
    conv = {"id": ("tmp-" if temporary else "") + db.new_id(), "title": title[:200], "project_id": project_id or None,
            "created": db.now(), "updated": db.now(), "pinned": 0, "archived": 0, "provider": provider, "model": model,
            "memory": 0 if temporary else 1, "titled": 0, "temporary": temporary, "summary": None, "summary_upto": 0}
    if temporary:
        _expire()
        with _temp_lock:
            TEMP[conv["id"]] = {"conv": conv, "messages": [], "touched": time.monotonic()}
        return conv
    with db.tx() as c:
        c.execute("""INSERT INTO conversations(id, title, project_id, created, updated, provider, model, memory)
                     VALUES (?, ?, ?, ?, ?, ?, ?, 1)""", (conv["id"], conv["title"], conv["project_id"], conv["created"],
                                                      conv["updated"], provider, model))
    return conv


def get(cid, with_messages=True):
    if cid in TEMP:
        with _temp_lock:
            item = TEMP[cid]
            item["touched"] = time.monotonic()
            return {**item["conv"], "messages": [dict(m) for m in item["messages"]] if with_messages else []}
    conv = db.one("SELECT * FROM conversations WHERE id = ?", cid)
    if not conv:
        raise AppError("Conversa não encontrada.", "Ela pode ter sido apagada.")
    conv["temporary"], conv["summary"] = False, db.loads(conv.get("summary") or "", None)
    if with_messages:
        conv["messages"] = []
        for m in db.rows("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", cid):
            m["sources"], m["meta"] = db.loads(m["sources"], []), db.loads(m["meta"], {})
            conv["messages"].append(m)
    return conv


def add_message(cid, role, content, sources=None, meta=None):
    sources, meta = sources or [], meta or {}
    if cid in TEMP:
        with _temp_lock:
            item = TEMP[cid]
            msg = {"id": f"t{len(item['messages']) + 1}", "conversation_id": cid, "role": role, "content": content,
                   "created": db.now(), "sources": sources, "meta": meta, "feedback": 0, "correction": "", "pinned": 0}
            item["messages"].append(msg)
            item["conv"]["updated"] = msg["created"]
            item["touched"] = time.monotonic()
            return msg
    with db.tx() as c:
        mid = c.execute("""INSERT INTO messages(conversation_id, role, content, created, sources, meta)
                           VALUES (?, ?, ?, ?, ?, ?)""", (cid, role, content, db.now(), db.dumps(sources), db.dumps(meta))).lastrowid
        c.execute("INSERT INTO messages_fts(rowid, content) VALUES (?, ?)", (mid, content))
        c.execute("UPDATE conversations SET updated = ? WHERE id = ?", (db.now(), cid))
    return {"id": mid, "conversation_id": cid, "role": role, "content": content, "sources": sources, "meta": meta}


def update_message(cid, mid, content, meta_patch=None):
    """Atualiza o texto (e campos de `meta`) de uma mensagem já salva — usado quando o estudante interrompe a fala."""
    if cid in TEMP:
        with _temp_lock:
            msg = next((m for m in TEMP[cid]["messages"] if str(m["id"]) == str(mid)), None)
            if not msg:
                return None
            msg["content"] = content
            if meta_patch:
                msg["meta"] = {**(msg.get("meta") or {}), **meta_patch}
            TEMP[cid]["conv"]["updated"] = db.now()
            TEMP[cid]["touched"] = time.monotonic()
            return dict(msg)
    row = db.one("SELECT id, meta FROM messages WHERE id = ? AND conversation_id = ?", mid, cid)
    if not row:
        return None
    meta = {**db.loads(row.get("meta") or "", {}), **(meta_patch or {})}
    with db.tx() as c:
        c.execute("UPDATE messages SET content = ?, meta = ? WHERE id = ? AND conversation_id = ?",
                  (content, db.dumps(meta), mid, cid))
        c.execute("DELETE FROM messages_fts WHERE rowid = ?", (mid,))
        c.execute("INSERT INTO messages_fts(rowid, content) VALUES (?, ?)", (mid, content))
        c.execute("UPDATE conversations SET updated = ? WHERE id = ?", (db.now(), cid))
    return {"id": mid, "conversation_id": cid, "content": content, "meta": meta}


def drop_last_answer(cid):
    """Para regenerar: tira a última resposta da IA (a pergunta fica)."""
    if cid in TEMP:
        with _temp_lock:
            msgs = TEMP[cid]["messages"]
            if msgs and msgs[-1]["role"] == "assistant":
                msgs.pop()
        return
    last = db.one("SELECT id, role FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", cid)
    if last and last["role"] == "assistant":
        with db.tx() as c:
            c.execute("DELETE FROM messages_fts WHERE rowid = ?", (last["id"],))
            c.execute("DELETE FROM messages WHERE id = ?", (last["id"],))


def drop_trailing_user(cid, mid):
    """Tira a pergunta `mid` se ela é a ÚLTIMA mensagem da conversa (ainda sem resposta): usada quando o estudante continua a frase
    depois de uma pausa e a fala inteira passa a ser um turno só. Devolve True se tirou; nunca apaga uma mensagem que já tem resposta."""
    if cid in TEMP:
        with _temp_lock:
            msgs = TEMP[cid]["messages"]
            if msgs and msgs[-1]["role"] == "user" and str(msgs[-1]["id"]) == str(mid):
                msgs.pop()
                return True
        return False
    last = db.one("SELECT id, role FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", cid)
    if last and last["role"] == "user" and str(last["id"]) == str(mid):
        with db.tx() as c:
            c.execute("DELETE FROM messages_fts WHERE rowid = ?", (last["id"],))
            c.execute("DELETE FROM messages WHERE id = ?", (last["id"],))
        return True
    return False


def seq(m):
    """Ordem da mensagem na conversa (o id no banco; "t3" na conversa temporária)."""
    return int(str(m["id"]).lstrip("t"))


def set_summary(cid, summary, upto):
    """Guarda o resumo das mensagens até `upto` (compactação). Nenhuma mensagem é apagada."""
    if cid in TEMP:
        with _temp_lock:
            TEMP[cid]["conv"].update(summary=summary, summary_upto=upto)
        return
    with db.tx() as c:
        if not c.execute("UPDATE conversations SET summary = ?, summary_upto = ? WHERE id = ?",
                         (db.dumps(summary), upto, cid)).rowcount:
            raise AppError("Conversa não encontrada.")


def pin_message(cid, mid, pinned):
    """Mensagem fixada nunca entra no resumo: vai sempre inteira para o modelo."""
    if cid in TEMP:
        with _temp_lock:
            msg = next((m for m in TEMP[cid]["messages"] if str(m["id"]) == str(mid)), None)
            if not msg:
                raise AppError("Mensagem não encontrada.")
            msg["pinned"] = int(pinned)
        return {"id": mid, "pinned": bool(pinned)}
    with db.tx() as c:
        if not c.execute("UPDATE messages SET pinned = ? WHERE id = ? AND conversation_id = ?", (int(pinned), mid, cid)).rowcount:
            raise AppError("Mensagem não encontrada.")
    return {"id": mid, "pinned": bool(pinned)}


def update(cid, **fields):
    allowed = {"title": str, "pinned": bool, "archived": bool, "project_id": (str, type(None)), "memory": bool}
    values = {}
    for k, v in fields.items():
        if k in allowed and isinstance(v, allowed[k]):
            values[k] = v.strip()[:200] if isinstance(v, str) and k == "title" else v
    if "project_id" in values and values["project_id"] and not db.one("SELECT id FROM projects WHERE id = ?", values["project_id"]):
        raise AppError("Projeto não encontrado.")
    if cid in TEMP:
        with _temp_lock:
            TEMP[cid]["conv"].update(values)
        return get(cid, False)
    if not values:
        return get(cid, False)
    if "title" in values:
        values["titled"] = 1
    sets = ", ".join(f"{k} = ?" for k in values)
    with db.tx() as c:
        if not c.execute(f"UPDATE conversations SET {sets} WHERE id = ?", (*[int(v) if isinstance(v, bool) else v for v in values.values()], cid)).rowcount:
            raise AppError("Conversa não encontrada.")
    return get(cid, False)


def auto_title(cid, title):
    """Título sugerido pela IA ou pela primeira pergunta; nunca troca um título que o usuário escreveu."""
    title = " ".join(str(title).split())[:80]
    if not title:
        return
    if cid in TEMP:
        with _temp_lock:
            if not TEMP[cid]["conv"]["titled"]:
                TEMP[cid]["conv"]["title"] = title
        return
    with db.tx() as c:
        c.execute("UPDATE conversations SET title = ? WHERE id = ? AND titled = 0", (title, cid))


def listing(q="", project_id=None, archived=False, date_from="", date_to="", limit=300):
    where, args = ["c.archived = ?"], [1 if archived else 0]
    if project_id == "none":
        where.append("c.project_id IS NULL")
    elif project_id:
        where.append("c.project_id = ?")
        args.append(project_id)
    if date_from:
        where.append("c.updated >= ?")
        args.append(date_from)
    if date_to:
        where.append("c.updated <= ?")
        args.append(date_to + "T23:59:59")
    q = (q or "").strip()
    if q:
        stems = [s for s in dict.fromkeys(vault.tokens(q)) if re.fullmatch(r"\w+", s)][:8]
        if stems:
            expr = " AND ".join(f'"{s}"*' for s in stems)
            where.append("(c.id IN (SELECT m.conversation_id FROM messages m JOIN messages_fts f ON f.rowid = m.id "
                         "WHERE messages_fts MATCH ?) OR c.title LIKE ?)")
            args += [expr, f"%{q[:80]}%"]
        else:
            where.append("c.title LIKE ?")
            args.append(f"%{q[:80]}%")
    rows = db.rows(f"""SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS count,
                       (SELECT substr(content, 1, 140) FROM messages m WHERE m.conversation_id = c.id AND m.role = 'user'
                        ORDER BY m.id LIMIT 1) AS first FROM conversations c WHERE {' AND '.join(where)}
                       ORDER BY c.pinned DESC, c.updated DESC LIMIT ?""", *args, int(limit))
    _expire()
    with _temp_lock:
        temps = [{**v["conv"], "count": len(v["messages"]), "first": (v["messages"][0]["content"][:140] if v["messages"] else "")}
                 for v in TEMP.values()] if not archived and not q and not project_id else []
    return temps + rows


def delete(ids):
    ids = [i for i in ids if isinstance(i, str)][:1000]
    with _temp_lock:
        for i in ids:
            TEMP.pop(i, None)
    with db.tx() as c:
        for i in ids:
            mids = [r[0] for r in c.execute("SELECT id FROM messages WHERE conversation_id = ?", (i,)).fetchall()]
            for k in range(0, len(mids), 500):
                part = mids[k:k + 500]
                c.execute(f"DELETE FROM messages_fts WHERE rowid IN ({','.join('?' * len(part))})", part)
            c.execute("DELETE FROM messages WHERE conversation_id = ?", (i,))
            c.execute("DELETE FROM pending_actions WHERE conversation_id = ? AND status = 'pending'", (i,))
            c.execute("DELETE FROM conversations WHERE id = ?", (i,))
    from . import attachments
    attachments.drop(ids)  # os arquivos anexados somem com a conversa
    db.checkpoint()
    return len(ids)


def delete_all():
    ids = [r["id"] for r in db.rows("SELECT id FROM conversations")] + list(TEMP)
    with _temp_lock:
        TEMP.clear()
    with db.tx() as c:
        n = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        c.execute("DELETE FROM messages_fts")
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM pending_actions WHERE status = 'pending'")
        c.execute("DELETE FROM conversations")
    from . import attachments
    attachments.drop(ids)
    db.checkpoint()
    return n


def prune(days):
    """Retenção: apaga conversas sem atividade há mais de `days` dias (as fixadas ficam)."""
    if not days:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    ids = [r["id"] for r in db.rows("SELECT id FROM conversations WHERE updated < ? AND pinned = 0", cutoff)]
    return delete(ids) if ids else 0


def export(cid, fmt="md"):
    conv = get(cid)
    if fmt == "json":
        return json.dumps({k: v for k, v in conv.items() if k != "temporary"}, ensure_ascii=False, indent=1)
    lines = [f"# {conv['title'] or 'Conversa de estudo'}", "", f"Exportada do Lúmen Study AI · criada em {conv['created'][:10]}", ""]
    for m in conv["messages"]:
        lines += [f"## {'Você' if m['role'] == 'user' else 'Lúmen'}", "", m["content"], ""]
        if m.get("sources"):
            lines.append("Fontes:")
            lines += [f"- {s.get('title', '')} ({s.get('source', '')}{' · ' + s['path'] if s.get('path') else ''})" for s in m["sources"]]
            lines.append("")
    return "\n".join(lines)


# --- Projetos ---------------------------------------------------------------------------------------------------

SOURCE_KEYS = ("notion", "obsidian", "files", "web")


def projects(include_archived=False):
    rows = db.rows("""SELECT p.*, (SELECT COUNT(*) FROM conversations c WHERE c.project_id = p.id) AS conversations,
                      (SELECT COUNT(*) FROM memories m WHERE m.project_id = p.id) AS memories,
                      (SELECT COUNT(*) FROM project_documents d WHERE d.project_id = p.id) AS documents
                      FROM projects p WHERE p.archived = 0 OR ? ORDER BY p.updated DESC""", 1 if include_archived else 0)
    for r in rows:
        r["sources"] = {**dict.fromkeys(SOURCE_KEYS, True), **db.loads(r["sources"], {})}
    return rows


def project(pid):
    r = db.one("SELECT * FROM projects WHERE id = ?", pid)
    if not r:
        raise AppError("Projeto não encontrado.")
    r["sources"] = {**dict.fromkeys(SOURCE_KEYS, True), **db.loads(r["sources"], {})}
    r["documents"] = db.rows("""SELECT d.id, d.title, d.source FROM project_documents p JOIN documents d ON d.id = p.doc_id
                                WHERE p.project_id = ? ORDER BY p.added""", pid)
    return r


def save_project(data):
    name = str(data.get("name") or "").strip()[:80]
    if not name:
        raise AppError("Dê um nome ao projeto.")
    sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
    sources = {k: bool(sources.get(k, True)) for k in SOURCE_KEYS}
    fields = (name, str(data.get("description") or "")[:1000], str(data.get("instructions") or "")[:4000],
              str(data.get("goals") or "")[:2000], db.dumps(sources))
    pid = data.get("id")
    with db.tx() as c:
        if pid:
            if not c.execute("""UPDATE projects SET name = ?, description = ?, instructions = ?, goals = ?, sources = ?, updated = ?,
                                archived = ? WHERE id = ?""", (*fields, db.now(), 1 if data.get("archived") else 0, pid)).rowcount:
                raise AppError("Projeto não encontrado.")
        else:
            pid = db.new_id()
            c.execute("""INSERT INTO projects(id, name, description, instructions, goals, sources, created, updated)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (pid, *fields, db.now(), db.now()))
    return project(pid)


def delete_project(pid):
    """Apaga o projeto, as memórias dele e o modelo do estudante nele. As conversas ficam (sem projeto)."""
    with db.tx() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM memories WHERE project_id = ?", (pid,)).fetchall()]
        for k in range(0, len(ids), 500):
            part = ids[k:k + 500]
            marks = ",".join("?" * len(part))
            c.execute(f"DELETE FROM memories_fts WHERE rowid IN ({marks})", part)
            c.execute(f"DELETE FROM vectors WHERE kind = 'memory' AND ref IN ({marks})", part)
        c.execute("DELETE FROM memories WHERE project_id = ?", (pid,))
        c.execute("DELETE FROM mastery WHERE project_id = ?", (pid,))
        if not c.execute("DELETE FROM projects WHERE id = ?", (pid,)).rowcount:
            raise AppError("Projeto não encontrado.")
    db.checkpoint()


def pin_document(pid, did, pinned=True):
    project(pid)
    with db.tx() as c:
        if pinned:
            if not c.execute("SELECT 1 FROM documents WHERE id = ?", (did,)).fetchone():
                raise AppError("Documento não encontrado no índice.")
            c.execute("INSERT OR IGNORE INTO project_documents(project_id, doc_id, added) VALUES (?, ?, ?)", (pid, did, db.now()))
        else:
            c.execute("DELETE FROM project_documents WHERE project_id = ? AND doc_id = ?", (pid, did))
    return project(pid)
