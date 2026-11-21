"""Treino falado (fase 6, parte 2; D58): role-play em turnos de voz. A IA faz o papel do personagem (cliente cético,
negociador, recrutadora americana), cada fala dela sai na voz escolhida para o personagem, o estudante responde pelo
"apertar para falar" (ou digitando) e, no fim, uma rubrica com tetos (D18) avalia a conversa e entra no modelo do
estudante (mastery, origem "practice").

As conversas ficam só na memória (no máximo 5, por 2 h): nada é gravado além do resultado da rubrica."""
import re
import threading
import time
import uuid

from .. import AppError
from . import mastery, providers, settings

SCENARIOS = {
    "venda": {"title": "Venda para um cliente cético", "lang": "pt",
              "role": "um cliente cético, dono de uma pequena empresa, que já foi enganado por fornecedores e quer provas",
              "opening": "Comece a conversa como o cliente, recebendo o vendedor com desconfiança.",
              "criteria": ["Descoberta da necessidade", "Clareza da proposta", "Tratamento de objeções", "Prova e confiança",
                           "Próximo passo combinado"]},
    "negociacao": {"title": "Negociação de preço e prazo", "lang": "pt",
                   "role": "um comprador experiente que quer 20% de desconto e prazo maior, educado mas firme",
                   "opening": "Comece a conversa como o comprador, pedindo o desconto logo de cara.",
                   "criteria": ["Preparação e âncora", "Escuta e perguntas", "Concessões com troca", "Calma e firmeza",
                                "Acordo claro"]},
    "entrevista": {"title": "Entrevista de emprego em inglês", "lang": "en",
                   "role": "an American recruiter interviewing the student for a marketing job, friendly but probing",
                   "opening": "Start the interview as the recruiter, with a short greeting and the first question.",
                   "criteria": ["Fluency", "Grammar and vocabulary", "Structure (STAR)", "Relevance", "Confidence"]},
}
MAX_TURNS = 8
SESSIONS, LOCK = {}, threading.Lock()

CHARACTER = """Você está num treino falado com um estudante. Faça o papel de {role}. Cenário: {title}.{topic}
Fale como essa pessoa falaria numa conversa de verdade: no máximo 3 frases curtas, sem narrar ações, sem Markdown, sem
listas, sem sair do papel e sem dar dicas ao estudante. {lang}
Marque "end" como true só quando a conversa chegar a um fim natural (acordo, recusa clara ou fim da entrevista).
Responda só no JSON pedido."""
LANG = {"pt": "Fale em português do Brasil.", "en": "Speak only in English, at a natural pace for a learner (B1-B2)."}
RUBRIC = """Avalie o desempenho do ESTUDANTE (não do personagem) nesta conversa de treino: {title}.
Para cada critério, dê uma nota de 0 a 1 e um comentário curto, citando uma fala dele como exemplo. Depois, a nota
geral de 0 a 1, um retorno curto e encorajador e a próxima coisa a treinar. Seja honesto: respostas vagas valem pouco.
Escreva os comentários em português. Responda só no JSON pedido."""


def _clean():
    now = time.monotonic()
    for k in [k for k, v in SESSIONS.items() if now - v["t"] > 7200]:
        SESSIONS.pop(k, None)
    while len(SESSIONS) > 5:
        SESSIONS.pop(min(SESSIONS, key=lambda k: SESSIONS[k]["t"]))


def _provider():
    chain, reasons = providers.chain()
    if not chain:
        raise AppError("Nenhuma IA disponível. " + " ".join(reasons))
    return chain[0]


def _dialogue(sess):
    who = {"character": "Personagem", "student": "Estudante"}
    return "<conversa>\n" + "\n".join(f"{who[t['role']]}: {t['text']}" for t in sess["turns"]) + "\n</conversa>"


def _line(sess, check=lambda: None):
    sc = SCENARIOS[sess["scenario"]]
    system = CHARACTER.format(role=sc["role"], title=sc["title"], lang=LANG[sc["lang"]],
                              topic=f" Tema do estudo: {sess['topic']}." if sess["topic"] else "")
    user = (_dialogue(sess) + "\nContinue como o personagem.") if sess["turns"] else sc["opening"]
    schema = {"type": "object", "properties": {"line": {"type": "string"}, "end": {"type": "boolean"}}, "required": ["line", "end"]}
    data = _provider().json(system, user, schema, check, max_tokens=300)
    line = re.sub(r"\s+", " ", str(data.get("line") or "")).strip()[:600]
    if not line:
        raise AppError("A IA não respondeu no papel do personagem.", "Tente de novo.")
    sess["turns"].append({"role": "character", "text": line})
    return line, bool(data.get("end"))


def start(scenario, topic="", voice=""):
    if scenario not in SCENARIOS:
        raise AppError("Cenário desconhecido.")
    s = settings.load()["voice"]
    voice = voice if isinstance(voice, str) and settings.VOICE_ID.fullmatch(voice) and voice else s["practice_voice"]
    sess = {"id": uuid.uuid4().hex, "scenario": scenario, "topic": " ".join(str(topic or "").split())[:120],
            "voice": voice, "turns": [], "t": time.monotonic()}
    line, end = _line(sess)
    with LOCK:
        _clean()
        SESSIONS[sess["id"]] = sess
    sc = SCENARIOS[scenario]
    return {"id": sess["id"], "title": sc["title"], "language": sc["lang"], "voice": voice, "line": line, "end": end,
            "left": MAX_TURNS}


def _get(sid):
    sess = SESSIONS.get(sid) if isinstance(sid, str) else None
    if not sess:
        raise AppError("Este treino terminou.", "Comece outro.")
    sess["t"] = time.monotonic()
    return sess


def turn(sid, text):
    sess = _get(sid)
    text = re.sub(r"\s+", " ", str(text or "")).strip()[:1500]
    if not text:
        raise AppError("Fale ou escreva a sua resposta.")
    sess["turns"].append({"role": "student", "text": text})
    left = MAX_TURNS - sum(1 for t in sess["turns"] if t["role"] == "student")
    if left <= 0:
        return {"line": "", "end": True, "left": 0}
    try:
        line, end = _line(sess)
    except AppError:
        sess["turns"].pop()  # a IA falhou: a fala volta para a caixa e a tentativa não gasta uma resposta
        raise
    return {"line": line, "end": end, "left": left}


def finish(sid, project_id=None, record=True):
    sess = _get(sid)
    if not any(t["role"] == "student" for t in sess["turns"]):
        raise AppError("Responda ao menos uma vez antes de terminar.")
    sc = SCENARIOS[sess["scenario"]]
    crit = {"type": "object", "properties": {"name": {"type": "string", "enum": sc["criteria"]}, "score": {"type": "number"},
                                             "comment": {"type": "string"}}, "required": ["name", "score", "comment"]}
    schema = {"type": "object", "properties": {"criteria": {"type": "array", "items": crit, "maxItems": 5},
                                               "overall": {"type": "number"}, "feedback": {"type": "string"},
                                               "next": {"type": "string"}},
              "required": ["criteria", "overall", "feedback", "next"]}
    data = _provider().json(RUBRIC.format(title=sc["title"]), _dialogue(sess), schema, lambda: None, max_tokens=1200)
    seen, rows = set(), []
    for c in data.get("criteria") or []:
        name = c.get("name")
        if name in sc["criteria"] and name not in seen:
            seen.add(name)
            rows.append({"name": name, "score": round(max(0.0, min(float(c.get("score") or 0), 1.0)), 2),
                         "comment": str(c.get("comment") or "")[:300]})
    # a nota geral é a média dos critérios avaliados (o número "geral" do modelo só vale se nenhum critério vier)
    overall = round(sum(r["score"] for r in rows) / len(rows) if rows else max(0.0, min(float(data.get("overall") or 0), 1.0)), 2)
    label = f"Treino falado: {sc['title']}" + (f" ({sess['topic']})" if sess["topic"] else "")
    if record:
        mastery.record(label, overall >= 0.7, "practice", project_id)
    with LOCK:
        SESSIONS.pop(sid, None)
    return {"title": sc["title"], "criteria": rows, "overall": overall, "correct": overall >= 0.7,
            "feedback": str(data.get("feedback") or "")[:600], "next": str(data.get("next") or "")[:300],
            "turns": len(sess["turns"])}


def _route(h):
    if h.command == "GET":
        return {"scenarios": [{"id": k, "title": v["title"], "language": v["lang"]} for k, v in SCENARIOS.items()],
                "max_turns": MAX_TURNS}
    from .api import limit
    b = h._json()
    if not isinstance(b, dict):
        raise AppError("Pedido inválido.")
    action = b.get("action")
    if action == "start":
        limit("practice", 6)
        return start(b.get("scenario"), b.get("topic") or "", b.get("voice") or "")
    if action == "turn":
        limit("practice", 12)
        return turn(b.get("id"), b.get("text"))
    if action == "end":
        return finish(b.get("id"), b.get("project_id") if isinstance(b.get("project_id"), str) else None,
                      record=b.get("temporary") is not True)
    raise AppError("Ação desconhecida.")


ROUTES = {("GET", "/api/study/practice"): _route, ("POST", "/api/study/practice"): _route}
