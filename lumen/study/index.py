"""Índice local: documentos normalizados, trechos, FTS5 e vetores, e a sincronização incremental em segundo plano.

Um documento só é relido quando a versão da fonte mudou (mtime+tamanho no disco, last_edited_time no Notion); se o
texto não mudou (mesmo hash), só a versão é atualizada e os vetores ficam. Um documento só sai do índice depois de
uma enumeração completa da fonte. A primeira sincronização de cada fonte é sempre um pedido do usuário; depois disso o
trabalhador mantém o índice em dia sozinho, cedendo a vez quando uma aula está sendo processada."""
import hashlib
import re
import threading
import time

import numpy as np

from .. import AppError, Cancelled, protection, vault
from . import db, settings
from .sources import registry

HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SIZE, OVERLAP = 1200, 200

STATE = {"running": False, "source": "", "phase": "", "done": 0, "total": 0, "message": "",
         "embedding": {"model": "", "ready": None, "done": 0, "total": 0, "message": ""}}
_lock = threading.RLock()
_wake = threading.Event()
_stop = threading.Event()
_requested = []
_thread = None
_gen = 0
_cache = {"key": None, "ids": None, "m": None}


def stems(text):
    return " ".join(vault.tokens(text))


def chunks(text, size=SIZE, overlap=OVERLAP):
    """[(caminho de títulos, trecho)] respeitando títulos, parágrafos e blocos de código."""
    sections, stack, cur, code = [], [], [], False
    for line in (text or "").splitlines():
        if line.lstrip().startswith("```"):
            code = not code
        m = None if code else HEAD.match(line)
        if m:
            if "".join(cur).strip():
                sections.append((" › ".join(t for _, t in stack), "\n".join(cur)))
            level = len(m[1])
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m[2].strip()))
            cur = []
        else:
            cur.append(line)
    if "".join(cur).strip():
        sections.append((" › ".join(t for _, t in stack), "\n".join(cur)))
    out = []
    for heading, body in sections:
        buf = ""
        for para in re.split(r"\n\s*\n", body):
            para = para.strip("\n")
            if not para.strip():
                continue
            while len(para) > size:  # parágrafo enorme: corta no fim de frase ou espaço da segunda metade
                cut = para.rfind(". ", size // 2, size)
                if cut > 0:
                    cut += 1
                else:
                    cut = para.rfind(" ", size // 2, size)
                    cut = cut if cut > 0 else size
                if buf:
                    out.append((heading, buf))
                    buf = ""
                out.append((heading, para[:cut].strip()))
                para = para[cut:].strip()
            if buf and len(buf) + len(para) + 2 > size:
                out.append((heading, buf))
                tail = buf[-overlap:]
                buf = tail[tail.find(" ") + 1:] if " " in tail else ""
            buf = f"{buf}\n\n{para}" if buf else para
        if buf.strip():
            out.append((heading, buf))
    return out or [("", (text or "").strip()[:size])] if (text or "").strip() else out


def doc_id(source, source_id):
    return f"{source}:{source_id}"


def bump():
    global _gen
    _gen += 1


def _drop_chunks(c, did):
    ids = [r[0] for r in c.execute("SELECT id FROM chunks WHERE doc_id = ?", (did,)).fetchall()]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        marks = ",".join("?" * len(part))
        c.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({marks})", part)
        c.execute(f"DELETE FROM vectors WHERE kind = 'chunk' AND ref IN ({marks})", part)
    c.execute("DELETE FROM chunks WHERE doc_id = ?", (did,))
    return len(ids)


def upsert(doc):
    did = doc_id(doc.source, doc.source_id)
    text = (doc.text or "").strip()
    digest = hashlib.sha256((doc.title + "\n" + text).encode("utf-8", "replace")).hexdigest()
    old = db.one("SELECT hash FROM documents WHERE id = ?", did)
    meta = (did, doc.source, doc.source_id, doc.title[:500], doc.path, doc.url, doc.kind, doc.author,
            db.dumps(doc.tags), db.dumps(doc.links), db.dumps(doc.meta), doc.updated, doc.version, digest, len(text), db.now())
    with db.tx() as c:
        c.execute("""INSERT INTO documents(id, source, source_id, title, path, url, kind, author, tags, links, meta, updated,
                     version, hash, chars, indexed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(id) DO UPDATE SET title=excluded.title, path=excluded.path, url=excluded.url,
                     kind=excluded.kind, author=excluded.author, tags=excluded.tags, links=excluded.links, meta=excluded.meta,
                     updated=excluded.updated, version=excluded.version, hash=excluded.hash, chars=excluded.chars,
                     indexed=excluded.indexed""", meta)
        if old and old["hash"] == digest:
            return did
        _drop_chunks(c, did)
        for order, (heading, body) in enumerate(chunks(text) or [("", doc.title)]):
            cid = c.execute("INSERT INTO chunks(doc_id, ord, heading, text) VALUES (?, ?, ?, ?)",
                            (did, order, heading[:300], body)).lastrowid
            c.execute("INSERT INTO chunks_fts(rowid, title, heading, text, stems) VALUES (?, ?, ?, ?, ?)",
                      (cid, doc.title, heading, body, stems(f"{doc.title} {heading} {body}")))
    bump()
    return did


def remove(did):
    with db.tx() as c:
        _drop_chunks(c, did)
        c.execute("DELETE FROM documents WHERE id = ?", (did,))
    bump()


def purge(source):
    """Tira uma fonte inteira do índice (trechos, palavras e vetores). Os originais não são tocados."""
    ids = [r["id"] for r in db.rows("SELECT id FROM documents WHERE source = ?", source)]
    for did in ids:
        remove(did)
    with db.tx() as c:
        c.execute("DELETE FROM sources WHERE name = ?", (source,))
    db.checkpoint()
    return len(ids)


def _source_row(name):
    row = db.one("SELECT * FROM sources WHERE name = ?", name) or {"name": name, "state": "", "synced": "", "message": "", "stats": "{}"}
    row["stats"] = db.loads(row["stats"], {})
    return row


def _set_source(name, **values):
    row = {**_source_row(name), **values}
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO sources(name, state, synced, message, stats) VALUES (?, ?, ?, ?, ?)",
                  (name, row["state"], row["synced"], row["message"], db.dumps(row["stats"])))


def sync(name, check=lambda: None):
    """Sincroniza uma fonte. Devolve as contagens. Erros de um documento não param os outros (ficam na contagem)."""
    src = registry()[name]
    with _lock:
        STATE.update(running=True, source=name, phase="listing", done=0, total=0, message="")
    _set_source(name, state="syncing", message="")
    try:
        current = src.versions(check)
    except Cancelled:
        _set_source(name, state="paused", message="Sincronização interrompida; continua depois.")
        raise
    except (AppError, OSError) as e:
        message = (str(e) + " " + getattr(e, "action", "")).strip() if isinstance(e, AppError) else "Não foi possível ler esta fonte."
        _set_source(name, state="error", message=message)
        raise AppError(message) from None
    row = _source_row(name)
    skipped = {k: v for k, v in row["stats"].get("skipped", {}).items() if k in current}
    known = {r["source_id"]: r for r in db.rows("SELECT id, source_id, version FROM documents WHERE source = ?", name)}
    todo = [sid for sid, (version, _) in current.items()
            if (sid not in known or known[sid]["version"] != version) and skipped.get(sid) != version]
    # "anexo:": anexo do chat guardado no índice (attachments.add_to_index); não está em pasta nenhuma
    removed = [r["id"] for sid, r in known.items() if sid not in current and not sid.startswith("anexo:")]
    errors = []
    with _lock:
        STATE.update(phase="reading", total=len(todo))
    for i, sid in enumerate(todo, 1):
        check()
        version, info = current[sid]
        try:
            doc = src.load(sid, info, check)
        except Cancelled:
            raise
        except (AppError, OSError, ValueError, KeyError) as e:
            errors.append(f"{sid[:80]}: {type(e).__name__}")
            continue
        if doc is None:
            skipped[sid] = version
            if sid in known:
                remove(known[sid]["id"])
        else:
            doc.version = version
            upsert(doc)
        with _lock:
            STATE["done"] = i
    for did in removed:
        remove(did)
    total = db.value("SELECT COUNT(*) FROM documents WHERE source = ?", name)
    stats = {"documents": total, "updated": len(todo) - len(errors), "removed": len(removed), "errors": len(errors),
             "skipped": skipped, "error_samples": errors[:5]}
    message = f"{len(errors)} documento(s) não puderam ser lidos; os outros estão no índice." if errors else ""
    _set_source(name, state="partial" if errors else "ok", synced=db.now(), message=message, stats=stats)
    return {k: v for k, v in stats.items() if k != "skipped"}


def counts():
    out = {}
    for r in db.rows("SELECT source, COUNT(*) AS n FROM documents GROUP BY source"):
        out[r["source"]] = {"documents": r["n"]}
    model = settings.load()["models"]["embed"]
    for r in db.rows("""SELECT d.source, COUNT(c.id) AS chunks, COUNT(v.ref) AS vectors FROM chunks c
                        JOIN documents d ON d.id = c.doc_id
                        LEFT JOIN vectors v ON v.kind = 'chunk' AND v.ref = c.id AND v.model = ?
                        GROUP BY d.source""", model):
        out.setdefault(r["source"], {}).update(chunks=r["chunks"], vectors=r["vectors"])
    return out


def source_view(name):
    row = _source_row(name)
    stats = {k: v for k, v in row["stats"].items() if k != "skipped"}
    return {"state": row["state"], "synced": row["synced"], "message": row["message"], "stats": stats}


# --- Vetores --------------------------------------------------------------------------------------------------

def store_vectors(kind, refs, vecs, model, expected):
    with db.tx() as c:
        table, column = ("chunks", "text") if kind == "chunk" else ("memories", "content")
        for ref, vec, original in zip(refs, vecs, expected):
            # O texto pode ter sido editado ou apagado enquanto a IA calculava o vetor.
            current = c.execute(f"SELECT {column} FROM {table} WHERE id = ?", (ref,)).fetchone()
            if not current or current[0] != original:
                continue
            v = np.asarray(vec, dtype=np.float32)
            n = float(np.linalg.norm(v)) or 1.0
            c.execute("INSERT OR REPLACE INTO vectors(kind, ref, model, dim, vec) VALUES (?, ?, ?, ?, ?)",
                      (kind, int(ref), model, int(v.shape[0]), (v / n).tobytes()))
    bump()


def matrix(kind, model):
    """(ids, matriz normalizada) dos vetores de um tipo e modelo; em cache até o próximo índice mudar."""
    key = (kind, model, _gen, str(db.path()))
    if _cache["key"] != key:
        rows = db.connect().execute("SELECT ref, dim, vec FROM vectors WHERE kind = ? AND model = ?", (kind, model)).fetchall()
        dims = {r[1] for r in rows}
        if not rows or len(dims) != 1:
            _cache.update(key=key, ids=np.zeros(0, dtype=np.int64), m=np.zeros((0, 1), dtype=np.float32))
        else:
            _cache.update(key=key, ids=np.array([r[0] for r in rows], dtype=np.int64),
                          m=np.vstack([np.frombuffer(r[2], dtype=np.float32) for r in rows]))
    return _cache["ids"], _cache["m"]


def embed_missing(check=lambda: None, limit=None):
    """Calcula os vetores que faltam (trechos e memórias) com o modelo de embeddings escolhido, se ele estiver
    instalado no Ollama. Sem o modelo, a busca continua só por palavras e a tela diz isso."""
    from . import providers
    s = settings.load()
    model = s["models"]["embed"]
    ready = providers.embed_ready(model)
    with _lock:
        STATE["embedding"].update(model=model, ready=ready, message="" if ready else "Modelo de embeddings não instalado.")
    if not ready:
        return 0
    batch = s["performance"]["embed_batch"]
    done = 0
    for kind, sql in (("chunk", """SELECT c.id, d.title, c.heading, c.text FROM chunks c JOIN documents d ON d.id = c.doc_id
                                   LEFT JOIN vectors v ON v.kind = 'chunk' AND v.ref = c.id AND v.model = ?
                                   WHERE v.ref IS NULL"""),
                      ("memory", """SELECT m.id, '', '', m.content FROM memories m
                                    LEFT JOIN vectors v ON v.kind = 'memory' AND v.ref = m.id AND v.model = ?
                                    WHERE v.ref IS NULL""")):
        pending = db.connect().execute(sql, (model,)).fetchall()
        with _lock:
            STATE["embedding"].update(done=0, total=len(pending))
        for i in range(0, len(pending), batch):
            check()
            part = pending[i:i + batch]
            texts = [(f"{r[1]}\n{r[2]}\n{r[3]}" if r[1] else r[3])[:2000] for r in part]
            vecs = providers.embed(texts, model)
            store_vectors(kind, [r[0] for r in part], vecs, model, [r[3] for r in part])
            done += len(part)
            with _lock:
                STATE["embedding"]["done"] = min(i + batch, len(pending))
            if limit and done >= limit:
                return done
    return done


# --- Trabalhador em segundo plano -------------------------------------------------------------------------------

def _background_check():
    if _stop.is_set():
        raise Cancelled()
    while settings.load()["performance"]["yield_to_lessons"] and protection.foreground_busy() and not _stop.is_set():
        with _lock:
            STATE["message"] = "Aula em processamento: a sincronização espera ela terminar."
        time.sleep(2)
    with _lock:
        if STATE["message"].startswith("Aula em processamento"):
            STATE["message"] = ""


def request(names=None):
    """Pede uma sincronização agora (das fontes dadas, ou de todas as já sincronizadas antes)."""
    with _lock:
        for n in names or []:
            if n not in _requested:
                _requested.append(n)
    start()
    _wake.set()


def start():
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="Lumen study index", daemon=True)
        _thread.start()


def stop():
    _stop.set()
    _wake.set()


def _loop():
    next_auto = time.monotonic() + 5
    while not _stop.is_set():
        _wake.wait(timeout=20)
        _wake.clear()
        if _stop.is_set():
            return
        s = settings.load()
        with _lock:
            names = list(_requested)
            _requested.clear()
        if not names and time.monotonic() >= next_auto:
            # automático: só fontes ligadas na busca e que o usuário já sincronizou uma vez
            names = [n for n in ("obsidian", "notion", "files") if s["search"].get(n) and _source_row(n)["synced"]]
            next_auto = time.monotonic() + s["performance"]["sync_minutes"] * 60
        try:
            for name in names:
                if registry()[name].status().get("connected"):
                    try:
                        sync(name, _background_check)
                    except AppError as e:
                        with _lock:
                            STATE["message"] = str(e)
            if names or STATE["embedding"]["ready"] is not False:
                with _lock:
                    STATE.update(phase="embedding", source="")
                embed_missing(_background_check)
            if names and s["search"]["images"]:  # só depois de uma sincronização: um lote por rodada, não sem parar
                from . import images
                with _lock:
                    STATE.update(phase="images", source="")
                images.read_pending(_background_check, s["performance"]["images_per_sync"])
        except Cancelled:
            pass
        except Exception as e:  # noqa: BLE001 — o trabalhador não pode morrer; o erro aparece na tela
            with _lock:
                STATE["message"] = f"A sincronização parou ({type(e).__name__}). Tente de novo."
        finally:
            with _lock:
                STATE.update(running=False, phase="", source="")
