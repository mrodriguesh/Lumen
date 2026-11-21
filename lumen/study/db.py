"""Banco local do Lúmen Study AI: um SQLite em DATA/study/study.db (WAL, FTS5, secure_delete).

Uma conexão por thread (o servidor atende cada pedido numa thread). Migrações por PRAGMA user_version: cada item de
MIGRATIONS roda uma vez, em ordem, numa transação. Apagar é apagar de verdade: secure_delete=ON zera as páginas
liberadas e checkpoint() trunca o WAL depois de uma limpeza, para o conteúdo não continuar legível no arquivo."""
import contextlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import store

HOME = store.DATA / "study"
# Mídia dos Estudos (anexos e imagens das notas): no D: (D22), fora do C: quase cheio. Com LUMEN_DATA (testes e medições
# isoladas) fica dentro dele, para nunca misturar com a pasta real.
MEDIA = HOME / "media" if os.environ.get("LUMEN_DATA") or not Path("D:/").is_dir() else Path(r"D:\Lumen\estudos")
_local = threading.local()
_MIGRATE = threading.Lock()
_CONNECT = threading.Lock()  # a preparação de uma conexão nova (PRAGMAs e migração) é uma por vez no processo
_optimized = False

# Texto das tabelas FTS: sem acento e sem diferença de maiúsculas. A coluna `stems` guarda as palavras cortadas em 6
# letras (vault.tokens), o que aproxima singular/plural e flexões do português sem um stemmer.
_FTS = 'tokenize="unicode61 remove_diacritics 2"'

MIGRATIONS = [
    f"""
    CREATE TABLE documents(
        id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
        path TEXT DEFAULT '', url TEXT DEFAULT '', kind TEXT DEFAULT 'note', author TEXT DEFAULT '',
        tags TEXT DEFAULT '[]', links TEXT DEFAULT '[]', meta TEXT DEFAULT '{{}}',
        updated TEXT DEFAULT '', version TEXT DEFAULT '', hash TEXT DEFAULT '', chars INTEGER DEFAULT 0, indexed TEXT);
    CREATE UNIQUE INDEX documents_origin ON documents(source, source_id);
    CREATE INDEX documents_hash ON documents(hash);
    CREATE TABLE chunks(
        id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        ord INTEGER NOT NULL, heading TEXT DEFAULT '', text TEXT NOT NULL);
    CREATE INDEX chunks_doc ON chunks(doc_id);
    CREATE VIRTUAL TABLE chunks_fts USING fts5(title, heading, text, stems, {_FTS});
    CREATE TABLE vectors(
        kind TEXT NOT NULL, ref INTEGER NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL,
        PRIMARY KEY(kind, ref, model));
    CREATE TABLE sources(name TEXT PRIMARY KEY, state TEXT DEFAULT '', synced TEXT DEFAULT '', message TEXT DEFAULT '',
        stats TEXT DEFAULT '{{}}');
    CREATE TABLE projects(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '', instructions TEXT DEFAULT '',
        goals TEXT DEFAULT '', sources TEXT DEFAULT '{{}}', created TEXT, updated TEXT, archived INTEGER DEFAULT 0);
    CREATE TABLE project_documents(
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, doc_id TEXT NOT NULL, added TEXT,
        PRIMARY KEY(project_id, doc_id));
    CREATE TABLE conversations(
        id TEXT PRIMARY KEY, title TEXT DEFAULT '', project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
        created TEXT, updated TEXT, pinned INTEGER DEFAULT 0, archived INTEGER DEFAULT 0, provider TEXT DEFAULT '',
        model TEXT DEFAULT '', memory INTEGER DEFAULT 1, titled INTEGER DEFAULT 0);
    CREATE INDEX conversations_updated ON conversations(updated);
    CREATE TABLE messages(
        id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL, content TEXT NOT NULL, created TEXT, sources TEXT DEFAULT '[]', meta TEXT DEFAULT '{{}}',
        feedback INTEGER DEFAULT 0, correction TEXT DEFAULT '');
    CREATE INDEX messages_conversation ON messages(conversation_id);
    CREATE VIRTUAL TABLE messages_fts USING fts5(content, {_FTS});
    CREATE TABLE memories(
        id INTEGER PRIMARY KEY, category TEXT NOT NULL, project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
        content TEXT NOT NULL, origin TEXT DEFAULT '{{}}', confidence REAL DEFAULT 1, status TEXT DEFAULT 'active',
        created TEXT, updated TEXT, used TEXT DEFAULT '', uses INTEGER DEFAULT 0, expires TEXT DEFAULT '');
    CREATE VIRTUAL TABLE memories_fts USING fts5(content, stems, {_FTS});
    CREATE TABLE flashcards(
        id INTEGER PRIMARY KEY, deck TEXT DEFAULT '', question TEXT NOT NULL, answer TEXT NOT NULL,
        explanation TEXT DEFAULT '', sources TEXT DEFAULT '[]', project_id TEXT, created TEXT, due TEXT,
        interval REAL DEFAULT 0, ease REAL DEFAULT 2.5, reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0, last TEXT DEFAULT '');
    CREATE INDEX flashcards_due ON flashcards(due);
    CREATE TABLE items(
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, data TEXT NOT NULL, project_id TEXT,
        conversation_id TEXT, created TEXT, updated TEXT);
    CREATE TABLE pending_actions(
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, level INTEGER NOT NULL, title TEXT DEFAULT '', preview TEXT NOT NULL,
        payload TEXT NOT NULL, status TEXT DEFAULT 'pending', created TEXT, decided TEXT DEFAULT '',
        result TEXT DEFAULT '', conversation_id TEXT DEFAULT '');
    CREATE TABLE activity(
        id INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL, tool TEXT DEFAULT '', target TEXT DEFAULT '',
        result TEXT DEFAULT '', permission TEXT DEFAULT '', provider TEXT DEFAULT '', conversation_id TEXT DEFAULT '',
        detail TEXT DEFAULT '');
    CREATE INDEX activity_at ON activity(at);
    CREATE TABLE web_cache(url TEXT PRIMARY KEY, fetched TEXT, title TEXT, text TEXT, status INTEGER);
    """,
    # 2 (Study AI 2.0, fase 3): compactação não destrutiva. summary = resumo (JSON) das mensagens até summary_upto, que
    # vai para o modelo no lugar delas; as mensagens continuam aqui. pinned = mensagem que nunca entra no resumo.
    """
    ALTER TABLE conversations ADD COLUMN summary TEXT DEFAULT '';
    ALTER TABLE conversations ADD COLUMN summary_upto INTEGER DEFAULT 0;
    ALTER TABLE messages ADD COLUMN pinned INTEGER DEFAULT 0;
    """,
    # 3 (fase 4): anexos das conversas salvas (as temporárias ficam só na memória, D13) e imagens das notas, pelo hash
    # do conteúdo (a mesma imagem em duas notas é lida uma vez). note = o que a visão leu (JSON de vision.clean).
    """
    CREATE TABLE attachments(
        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER DEFAULT 0,
        created TEXT, status TEXT DEFAULT 'reading', message TEXT DEFAULT '', text TEXT DEFAULT '', meta TEXT DEFAULT '{}',
        doc_id TEXT DEFAULT '');
    CREATE INDEX attachments_conversation ON attachments(conversation_id);
    CREATE TABLE images(
        hash TEXT PRIMARY KEY, source TEXT DEFAULT '', name TEXT DEFAULT '', state TEXT DEFAULT 'pending',
        note TEXT DEFAULT '', created TEXT, read TEXT DEFAULT '');
    CREATE INDEX images_state ON images(state);
    """,
    # 4 (fase 5): modelo do estudante. concept = as palavras do assunto, normalizadas (mastery.key); origin = quantas
    # vezes veio de cada origem (flashcard, quiz, check); next_review = a próxima revisão sugerida.
    """
    CREATE TABLE mastery(
        concept TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '', label TEXT NOT NULL, correct INTEGER DEFAULT 0,
        wrong INTEGER DEFAULT 0, last TEXT DEFAULT '', next_review TEXT DEFAULT '', origin TEXT DEFAULT '{}',
        PRIMARY KEY(concept, project_id));
    """,
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id():
    return uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value, default=None):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def path():
    return HOME / "study.db"


def connect():
    target = path()
    c = getattr(_local, "conn", None)
    if c is not None and getattr(_local, "path", None) == target:
        return c
    # No primeiro acesso a um banco que ainda não existe, duas threads trocando o journal_mode para WAL ao mesmo tempo recebiam
    # "database is locked" na hora (essa troca não espera pelo busy_timeout): a primeira chamada de /api/study/state dava 500 (medido:
    # 115 erros em 150 bancos novos × 8 threads). Uma conexão nova por vez no processo; as já preparadas não passam por aqui.
    with _CONNECT:
        HOME.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(target, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        # cache_size negativo = KB (64 MB): as buscas do Study AI e os índices FTS ficam na memória, não no disco.
        # temp_store=MEMORY: ordenações e tabelas temporárias não escrevem no C:. mmap_size: leituras sem cópia.
        for pragma in ("journal_mode=WAL", "foreign_keys=ON", "secure_delete=ON", "synchronous=NORMAL",
                       "busy_timeout=30000", "cache_size=-65536", "temp_store=MEMORY", "mmap_size=268435456"):
            c.execute("PRAGMA " + pragma)
        _migrate(c)
        _optimize(c)
        _local.conn, _local.path = c, target
        return c


def _optimize(c):
    """PRAGMA optimize uma vez por processo: atualiza as estatísticas que o planejador usa, sem ANALYZE pesado."""
    global _optimized
    if _optimized:
        return
    _optimized = True
    try:
        c.execute("PRAGMA optimize")
    except sqlite3.Error:
        pass


def _migrate(c):
    with _MIGRATE:
        version = c.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            try:
                c.executescript(f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version={number};\nCOMMIT;")
            except sqlite3.Error:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                raise


@contextlib.contextmanager
def tx():
    """Uma transação de escrita (BEGIN IMMEDIATE). Aninhada, reaproveita a de fora."""
    c = connect()
    if c.in_transaction:
        yield c
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
    except BaseException:
        c.execute("ROLLBACK")
        raise
    c.execute("COMMIT")


def rows(sql, *args):
    return [dict(r) for r in connect().execute(sql, args).fetchall()]


def one(sql, *args):
    r = connect().execute(sql, args).fetchone()
    return dict(r) if r else None


def value(sql, *args):
    r = connect().execute(sql, args).fetchone()
    return r[0] if r else None


def checkpoint():
    """Depois de apagar: grava o WAL no banco e zera o arquivo -wal (com secure_delete, nada apagado fica legível)."""
    connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")


def close():
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
        _local.conn = None


def files():
    """Arquivos do banco no disco (para "Seus dados no Lúmen")."""
    base = path()
    return [p for p in (base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")) if p.exists()]
