"""Registro de atividades do Lúmen Study AI: o que foi feito, com qual ferramenta, em qual documento e com qual
permissão. Guarda títulos, caminhos e contagens, nunca o conteúdo das notas nem das mensagens."""
from datetime import datetime, timedelta, timezone

from . import db


def log(action, tool="", target="", result="ok", permission="", provider="", conversation_id="", detail=""):
    with db.tx() as c:
        c.execute("""INSERT INTO activity(at, action, tool, target, result, permission, provider, conversation_id, detail)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (db.now(), action[:80], tool[:60], str(target)[:300], str(result)[:200], permission[:40], provider[:40],
                   conversation_id or "", str(detail)[:300]))


def recent(limit=200, action=None):
    if action:
        return db.rows("SELECT * FROM activity WHERE action = ? ORDER BY id DESC LIMIT ?", action, int(limit))
    return db.rows("SELECT * FROM activity ORDER BY id DESC LIMIT ?", int(limit))


def providers_used():
    """Quais provedores externos receberam dados, quando e quantas vezes (para "Seus dados no Lúmen")."""
    return db.rows("""SELECT provider, COUNT(*) AS calls, MIN(at) AS first, MAX(at) AS last FROM activity
                      WHERE action = 'envio-externo' GROUP BY provider""")


def prune(days):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with db.tx() as c:
        n = c.execute("DELETE FROM activity WHERE at < ?", (cutoff,)).rowcount
    return n
