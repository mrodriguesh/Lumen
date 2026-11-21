"""Modelo do estudante: o domínio de cada assunto, pelo que ele acertou e errou nos flashcards, nos questionários e nas
checagens das explicações. Serve para a explicação partir do que ele já sabe e para sugerir a próxima revisão.

Os pesos do modelo de IA não mudam: é só uma tabela local (`mastery`), visível e apagável em "Seus dados no Lúmen".
O assunto é guardado pelas palavras dele (vault.tokens, sem acento e sem palavras vazias), e uma pergunta acha o
assunto parecido pela sobreposição dessas palavras."""
from datetime import datetime, timezone

from .. import vault
from . import db

ORIGINS = {"flashcard": "flashcards", "quiz": "questionário", "check": "checagem da explicação", "feynman": "explicação com as suas palavras (Feynman)",
           "practice": "treino falado", "exercise": "prática com correção", "action": "plano de ação"}
LEVELS = {"domina": "domina", "aprendendo": "está aprendendo", "dificuldade": "tem dificuldade"}


def key(text):
    return " ".join(sorted(set(vault.tokens(text))))[:200]


def level(row):
    n = row["correct"] + row["wrong"]
    if not n:
        return ""
    ratio = row["correct"] / n
    return "domina" if n >= 3 and ratio >= .8 else "aprendendo" if ratio >= .5 else "dificuldade"


def record(label, ok, origin, project_id=None, next_review=""):
    """Um acerto (ok=True), um erro (False) ou só a próxima revisão (None). A revisão guardada é a mais próxima que
    ainda não passou."""
    label = " ".join(str(label or "").split())[:120]
    k = key(label)
    if not k:
        return None
    pid, now = project_id or "", db.now()
    same = find(label, project_id, same_project=True)  # o mesmo assunto com outras palavras soma na mesma linha
    if same:
        k, label = same["concept"], same["label"]
    with db.tx() as c:
        row = c.execute("SELECT * FROM mastery WHERE concept = ? AND project_id = ?", (k, pid)).fetchone()
        row = dict(row) if row else {"correct": 0, "wrong": 0, "next_review": "", "origin": "{}"}
        origins = db.loads(row["origin"], {})
        if ok is not None:
            origins[origin] = origins.get(origin, 0) + 1
            row["correct" if ok else "wrong"] += 1
        old = row["next_review"]
        if next_review and (not old or old <= now or next_review < old):
            old = next_review
        c.execute("""INSERT INTO mastery(concept, project_id, label, correct, wrong, last, next_review, origin)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(concept, project_id) DO UPDATE SET label = excluded.label,
                     correct = excluded.correct, wrong = excluded.wrong, last = excluded.last,
                     next_review = excluded.next_review, origin = excluded.origin""",
                  (k, pid, label, row["correct"], row["wrong"], now, old, db.dumps(origins)))
    return find(label, project_id)


def find(topic, project_id=None, same_project=False):
    """O assunto registrado mais parecido: as palavras em comum são ao menos metade das do mais longo dos dois (um
    assunto de uma palavra não casa com qualquer pergunta que a contenha); o do mesmo projeto ganha."""
    words = set(vault.tokens(topic))
    best, score = None, 0.0
    rows = db.rows("SELECT * FROM mastery WHERE project_id = ?", project_id or "") if same_project else db.rows("SELECT * FROM mastery")
    for r in rows:
        have = set(r["concept"].split())
        if not words or not have:
            continue
        s = len(words & have) / max(len(words), len(have)) + (.01 if r["project_id"] == (project_id or "") else 0)
        if s >= .5 and s > score:
            best, score = r, s
    return {**best, "level": level(best)} if best else None


def prompt(topic, project_id=None):
    """O ponto de partida da explicação, para o prompt do sistema."""
    r = find(topic, project_id)
    if not r or not r["level"]:
        return ("Ponto de partida: o estudante ainda não praticou este assunto no Lúmen (sem flashcards, questionário nem "
                "checagem). Comece pela intuição e confira o entendimento no caminho.")
    how = {"domina": "vá direto ao que é mais avançado e às nuances, sem repetir o básico",
           "aprendendo": "reforce o mecanismo e os pontos em que se costuma errar",
           "dificuldade": "comece do básico, com uma analogia do dia a dia, e vá devagar"}[r["level"]]
    return (f"Ponto de partida (modelo do estudante, pelo que ele praticou no Lúmen): em “{r['label']}” ele {LEVELS[r['level']]} "
            f"({r['correct']} acerto(s) e {r['wrong']} erro(s)). Por isso, {how}.")


def to_review(limit=5):
    """Os assuntos para revisar agora: a revisão marcada já chegou, ou ele tem dificuldade."""
    now = db.now()
    rows = [r for r in db.rows("SELECT * FROM mastery ORDER BY next_review = '', next_review, last DESC LIMIT 200")
            if (r["next_review"] and r["next_review"] <= now) or level(r) == "dificuldade"]
    return [{"label": r["label"], "level": level(r), "due": bool(r["next_review"]) and r["next_review"] <= now} for r in rows[:limit]]


def listing():
    rows = db.rows("SELECT * FROM mastery ORDER BY last DESC LIMIT 500")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        r["level"] = level(r)
        r["origin"] = db.loads(r["origin"], {})
        r["due"] = bool(r["next_review"]) and r["next_review"] <= now
    return rows
