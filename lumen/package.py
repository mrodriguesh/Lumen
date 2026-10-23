"""StudyPackage: a aula processada UMA vez, na forma canônica que alimenta todos os destinos.

jobs.finish monta o pacote (IA uma vez só: llm.generate, refine, charts, connect) e o entrega a cada destino
(notion.render, obsidian.deliver). Os destinos nunca leem um do outro: o pacote é a fonte da verdade. Fica em
DATA/packages/<lumen_id>.json para tentar de novo um destino sem chamar a IA.

Separação de autoria: `understanding` é o que o estudante escreveu (as chaves de lumen/understanding.py, intactas;
a análise da IA vem à parte em ai_analysis) e `lesson` é o material da IA. Nada aqui reescreve a nota dele.
"""
import hashlib
import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta

from . import AppError, store

PROCESSOR_VERSION = "2.0"
RELATIONS = ("causa", "depende de", "exemplo de", "contrasta com", "leva a", "parte de", "usado em")
QUESTION_KINDS = ("recordacao", "compreensao", "relacao", "aplicacao", "diagnostico", "sintese")
REDACTED = "[segredo removido]"
_SECRET = re.compile(r"\b(?:ntn|secret)_[A-Za-z0-9]{20,}|\bsk-[A-Za-z0-9_-]{20,}|\bBearer\s+[A-Za-z0-9._~+/=-]{20,}")
_MINE = ("original_understanding", "current_understanding", "earlier", "submitted", "ai_analysis", "analyzed_text",
         "model")


def lumen_id(key):
    """Estável por fonte (o mesmo vídeo/arquivo = o mesmo id): é o que evita duplicar a nota ao reprocessar."""
    return "lm-" + hashlib.sha256(str(key).encode()).hexdigest()[:16]


def norm(text):
    """Para comparar rótulos: sem acentos, minúsculo, espaços simples."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^\w\s]", " ", t.casefold()).split())


def _canon(pkg):
    """O que define o conteúdo (sem horários): o mesmo material dá o mesmo hash."""
    keep = ("source", "course", "understanding", "lesson", "map", "charts", "screens", "connections", "anchors",
            "anchor_suggestion")
    return json.dumps({k: pkg.get(k) for k in keep}, ensure_ascii=False, sort_keys=True)


def content_hash(pkg):
    return hashlib.sha256(_canon(pkg).encode()).hexdigest()[:24]


def build(src, tr, lesson, mine, screens=(), charts=(), links=None, course="", model="", vision_model="",
          intervals=(), today=None):
    """Junta o que o Lumen já produziu numa representação só. screens: telas escolhidas (vision.select) com o texto
    lido; charts: os gráficos conferidos (sem os uploads do Notion); links: llm.connect (ou None)."""
    from .mindmap import data as mind_map
    today = today or date.today()
    edited = sum(1 for s in tr.get("segments") or [] if s.get("edited"))
    links = links or {}
    pkg = {
        "lumen_id": lumen_id(src["key"]), "key": src["key"], "processor_version": PROCESSOR_VERSION,
        "processed_at": datetime.now().isoformat(timespec="seconds"), "date": today.isoformat(),
        "source": {"kind": src["kind"], "label": src.get("label"), "title": src.get("title"),
                   "link": src.get("link"), "yt_id": src.get("yt_id"), "duration": tr.get("duration"),
                   "language": tr.get("language"),
                   "origin": (tr.get("origin") or "") + (f" {edited} trecho(s) corrigido(s) pelo usuário." if edited else ""),
                   "uncertain": sum(1 for s in tr.get("segments") or [] if s.get("uncertain") and not s.get("edited")),
                   "model": model, "vision_model": vision_model if screens else ""},
        "course": course or "",
        "understanding": {k: mine.get(k) for k in _MINE},
        "lesson": lesson,
        "map": mind_map(lesson),
        "screens": [{"id": s["id"], "t": s.get("t"), "manual": bool(s.get("manual")), **{
            k: s["note"].get(k, "") for k in ("titulo", "tipo", "texto", "descricao")}} for s in screens],
        "charts": [{k: v for k, v in c.items() if k != "upload"} for c in charts or []],
        "connections": links.get("links") or [], "anchors": links.get("anchors") or [],
        "anchor_suggestion": links.get("anchor_suggestion") or "",
        "review_dates": [(today + timedelta(days=int(d))).isoformat() for d in intervals],
    }
    pkg["flashcards"] = flashcards(lesson)
    pkg["timeline"] = timeline(lesson, pkg["screens"])
    return pkg


def flashcards(lesson):
    """Cartões sem IA nova: os termos do glossário e as perguntas de recordação (frente → verso)."""
    cards = [{"front": g["term"], "back": g["definition"]} for g in lesson.get("glossary") or []]
    cards += [{"front": q["question"], "back": q["answer"]} for q in lesson.get("review_questions") or []
              if q.get("kind") == "recordacao"]
    return cards[:24]


def timeline(lesson, screens):
    """Momentos da aula e telas que apareceram, em ordem (só o que tem tempo de verdade: nunca inventado)."""
    items = [{"t": m["timestamp"], "label": m["label"]} for m in lesson.get("key_moments") or []]
    items += [{"t": s["t"], "label": "Na tela: " + (s["titulo"] or "tela")} for s in screens
              if not s["manual"] and s.get("t") is not None]
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["t"]):
        if (it["t"], it["label"]) not in seen:
            seen.add((it["t"], it["label"]))
            out.append(it)
    return out[:40]


def _redact(v, token):
    if isinstance(v, str):
        v = _SECRET.sub(REDACTED, v)
        return v.replace(token, REDACTED) if token and len(token) >= 12 else v
    if isinstance(v, list):
        return [_redact(x, token) for x in v]
    if isinstance(v, dict):
        return {k: _redact(x, token) for k, x in v.items()}
    return v


def validate(pkg, known=None):
    """StudyPackageValidator. Falta o essencial → AppError (nada é salvo em lugar nenhum). O resto é limpo: relações
    entre rótulos que o mapa não tem, conexões com notas que não existem (known: nomes do cofre), segredos."""
    lesson, mine = pkg["lesson"], pkg["understanding"]
    if not (lesson.get("title") and lesson.get("summary") and lesson.get("topics")):
        raise AppError("O material ficou incompleto (sem título, resumo ou tópicos).", "Tente gerar de novo.")
    if not (mine.get("original_understanding") or "").strip():
        raise AppError("A sua compreensão não foi encontrada no material.", "Escreva e processe a sua compreensão.")
    if any(not (q.get("question") and q.get("answer")) for q in lesson.get("review_questions") or []):
        raise AppError("Há perguntas sem resposta no material.", "Tente gerar de novo.")
    m = pkg["map"]
    labels = {norm(m["center"])} | {norm(b["label"]) for b in m["branches"]} | {
        norm(k) for b in m["branches"] for k in b["children"]}
    lesson["relations"] = [r for r in lesson.get("relations") or []
                           if norm(r["from"]) in labels and norm(r["to"]) in labels and norm(r["from"]) != norm(r["to"])]
    if known is not None:
        names = {norm(n) for n in known}
        pkg["connections"] = [c for c in pkg["connections"] if norm(c["note"]) in names]
        pkg["anchors"] = [a for a in pkg["anchors"] if norm(a) in names]
    pkg.update(_redact({k: v for k, v in pkg.items()}, store.get_token() or ""))
    pkg["content_hash"] = content_hash(pkg)
    return pkg


def _path(lid):
    if not re.fullmatch(r"lm-[0-9a-f]{16}", str(lid)):
        raise AppError("Material não encontrado.", "Gere a página de novo.")
    return store.DATA / "packages" / f"{lid}.json"


def save(pkg):
    p = _path(pkg["lumen_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(pkg, ensure_ascii=False), "utf-8")
    os.replace(tmp, p)


def load(lid):
    try:
        return json.loads(_path(lid).read_text("utf-8"))
    except (OSError, ValueError):
        raise AppError("O material desta aula não está mais guardado no PC.",
                       "Gere a página de novo a partir da aula.") from None
