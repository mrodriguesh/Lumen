"""Minha compreensão: a IA só trabalha depois que o estudante escreve o que entendeu.

Regra central do Lumen, para toda fonte (gravação, arquivo, capturas, YouTube, Telegram e as que vierem): nenhum
resumo, anotação ou página é gerado, e nada do conteúdo da aula (transcrição, telas) chega à interface, antes de
existir uma nota de compreensão escrita pelo estudante. Quem gera material chama `require`/`check` daqui; a
interface recebe a tarefa por `guard` e o conteúdo da aula só depois de `reveal`. Uma fonte nova passa pelo mesmo
caminho (jobs.process → nota → jobs.analyze → jobs.finish) e herda a regra sem código próprio.

Por aula (chave da fonte), em DATA/understanding/<hash>.json:
  original_understanding  o que o estudante escreveu antes de qualquer análise (congela na 1ª análise da IA)
  current_understanding   a versão atual: rascunho salvo sozinho e, depois da análise, a nota editada
  ai_analysis             a análise da IA sobre a nota (acertos, lacunas, confusões…), nunca misturada a ela
  final_knowledge         onde o material final foi salvo no Notion
"""
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime

from . import AppError, store

STATES = ("not_started", "studying", "waiting_for_understanding", "understanding_written", "processing_with_ai",
          "completed", "synced_to_notion")
WRITING = ("studying", "waiting_for_understanding", "understanding_written")  # o estudante ainda escreve
MIN_WORDS, MIN_DISTINCT, MAX_CHARS = 20, 12, 12_000  # app.js usa os mesmos números para liberar o botão
_WORD = re.compile(r"[^\W\d_]{2,}")                  # palavras de 2+ letras (sem números nem símbolos)
_VOWEL = re.compile(r"[aeiouyáéíóúâêôãõàü]", re.I)
_lock = threading.Lock()
analyzing = None  # chave da aula que a IA está analisando agora (marcada em begin_analysis, antes do job existir)
context = lambda: {}  # o servidor troca por {"recording": bool, "job": {...}}: o que bloqueia fora da nota (server.py)


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _path(key):
    return store.DATA / "understanding" / (hashlib.sha256(str(key).encode()).hexdigest()[:16] + ".json")


def _read(path):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def load(key):
    return _read(_path(key)) if key else None


def _write(rec):
    rec["updated"] = _now()
    path = _path(rec["key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), "utf-8")
    os.replace(tmp, path)  # atômico: fechar o app no meio nunca deixa a nota pela metade


def _clean(text):
    return str(text or "").replace("\r\n", "\n")[:MAX_CHARS]  # o resto fica exatamente como foi escrito


# --- a nota vale? ----------------------------------------------------------------------------------------------

def problem(text):
    """Por que a nota ainda não vale, ou None. Vale um texto de verdade, mesmo imperfeito: pelo menos MIN_WORDS
    palavras, MIN_DISTINCT diferentes (não “teste teste teste”) e com cara de texto (não teclas ao acaso)."""
    words = _WORD.findall(unicodedata.normalize("NFC", text or ""))
    if len(words) < MIN_WORDS:
        n = MIN_WORDS - len(words)
        return f"Escreva mais um pouco: faltam {n} palavra{'s' if n > 1 else ''}."
    if len({w.casefold() for w in words}) < MIN_DISTINCT:
        return "Explique com suas palavras: a nota repete quase só as mesmas palavras."
    if sum(1 for w in words if _VOWEL.search(w)) < len(words) * 0.8:
        return "A nota não parece um texto. Escreva com suas palavras o que entendeu."
    return None


def valid(text):
    return problem(text) is None


def check(text):
    """Trava de toda função de IA que escreve material sobre a aula: sem nota válida, nada roda."""
    why = problem(text)
    if why:
        raise AppError("A IA só trabalha depois da sua compreensão. " + why,
                       "Escreva em “Minha compreensão” o que você entendeu da aula.")


def require(key, analyzed=False):
    """A nota enviada (“Processar minha compreensão”) desta aula, ou AppError. analyzed: exige também a análise
    (salvar no Notion vem depois dela)."""
    rec = load(key)
    if not rec or not rec.get("original_understanding"):
        raise AppError("A IA só trabalha depois que você escreve sua compreensão da aula.",
                       "Escreva em “Minha compreensão” o que entendeu e clique em “Processar minha compreensão”.")
    check(rec["current_understanding"])
    if analyzed and not rec.get("ai_analysis"):
        raise AppError("Sua compreensão ainda não foi analisada.",
                       "Clique em “Processar minha compreensão” e depois salve no Notion.")
    return rec


def reveal(key):
    """Transcrição, telas e revisão da aula só aparecem depois da nota enviada: antes, seriam cola."""
    rec = load(key)
    if not (rec and rec.get("original_understanding")):
        raise AppError("A transcrição e as telas aparecem depois que você escreve sua compreensão.",
                       "Escreva primeiro o que você entendeu da aula.")


def guard(job):
    """O que a interface recebe de uma tarefa: o resultado da preparação sai sem a transcrição e as telas enquanto
    a nota não foi enviada (elas continuam no disco, para a IA usar depois)."""
    res = job.get("result")
    if isinstance(res, dict) and res.get("review"):
        rec = load(res.get("key"))
        if not (rec and rec.get("original_understanding")):
            job["result"] = {k: v for k, v in res.items() if k not in ("segments", "screens")}
    return job


# --- ciclo de vida -----------------------------------------------------------------------------------------------

def start(key, title, label, spec):
    """Aula escolhida para estudar (a preparação técnica começou). Uma aula já salva no Notion começa uma nova
    sessão de estudo; a compreensão anterior não se perde: fica em `earlier` e vai junto para a subpágina."""
    # sem a transcrição colada (YouTube): ela fica na pasta da aula, e cada autosave regravaria até 5 MB
    spec = {k: v for k, v in (spec or {}).items() if k not in ("retranscribe", "edits", "screens_off", "captions")}
    with _lock:
        rec = load(key)
        if rec and rec.get("final_knowledge"):
            earlier = rec.get("earlier", []) + [{"text": rec["original_understanding"], "at": rec.get("submitted")}]
            rec = {"earlier": earlier[-20:]}
        if not rec or "key" not in rec:
            rec = {"key": key, "created": _now(), "current_understanding": "", "current_at": 0,
                   "original_understanding": None, "ai_analysis": None, "final_knowledge": None, "prepared": False,
                   **(rec or {})}
        rec.update(title=title, label=label, spec=spec)
        _write(rec)


def prepared(key):
    """A preparação técnica terminou (transcrição e telas no disco): a IA já poderá comparar com a nota."""
    with _lock:
        rec = load(key)
        if rec and not rec.get("prepared"):
            rec["prepared"] = True
            _write(rec)


def _rec(key):
    rec = load(key)
    if not rec:
        raise AppError("Esta aula não foi encontrada.", "Escolha a aula de novo.")
    if analyzing == key:
        raise AppError("A IA está analisando sua compreensão agora.", "Aguarde terminar para editar.")
    return rec


def save_draft(key, text, at=None):
    """Autosave. `at` (ms, relógio da interface) ordena os pedidos: um atrasado não apaga o texto mais novo."""
    at = int(at or time.time() * 1000)
    with _lock:
        rec = _rec(key)
        stale = at < rec.get("current_at", 0)  # pedido atrasado: a versão mais nova (outra janela) fica; quem pediu a adota
        if not stale:
            rec["current_understanding"], rec["current_at"] = _clean(text), at
            rec["rev"] = rec.get("rev", 0) + 1
            _write(rec)
    return {**view(rec), "stale": stale}


def submit(key, text, at=None):
    """“Processar minha compreensão”. A original é o que o estudante entendeu antes de a IA interferir: muda só
    enquanto nenhuma análise existe; depois da 1ª, fica congelada e as edições vão só para a atual.
    `at`: horário da versão que a interface tem; se outra janela já gravou uma mais nova, nada é processado."""
    text = _clean(text)
    check(text)
    with _lock:
        rec = _rec(key)
        if not rec.get("prepared"):
            raise AppError("A aula ainda está sendo preparada.", "Continue escrevendo; o botão libera quando terminar.")
        if at is not None and int(at) < rec.get("current_at", 0):
            raise AppError("Sua compreensão foi alterada em outra janela.", "Confira o texto e processe de novo.")
        rec["current_understanding"] = text
        rec["current_at"] = max(int(at or 0), rec.get("current_at", 0), int(time.time() * 1000))
        rec["rev"] = rec.get("rev", 0) + 1
        rec["submitted_rev"], rec["processing_since"] = rec["rev"], _now()  # a análise usa exatamente esta versão
        if not rec.get("ai_analysis"):
            rec["original_understanding"], rec["submitted"] = text, _now()
        _write(rec)


def begin_analysis(key):
    """Trava as edições desta aula no instante do pedido (antes de o job começar): sem janela em que a nota ainda
    aceita texto que a análise não vai ler. jobs.analyze (ou o servidor, se o job não iniciar) solta a trava."""
    global analyzing
    analyzing = key


def end_analysis():
    global analyzing
    analyzing = None


def save_analysis(key, analysis, text, model):
    with _lock:
        rec = load(key)
        rec.update(ai_analysis=analysis, analyzed_text=text, analyzed=_now(), model=model,
                   analyzed_rev=rec.get("submitted_rev"), processing_since=None)
        _write(rec)


def synced(key, info):
    with _lock:
        rec = load(key)
        if not rec:  # aula antiga ou dados locais apagados (Organizar, Tentar de novo): não há nota a marcar
            return
        rec["final_knowledge"] = {**info, "at": _now()}
        _write(rec)


# --- o que a interface vê ------------------------------------------------------------------------------------

def state(rec):
    if not rec:
        return "not_started"
    if analyzing == rec["key"]:
        return "processing_with_ai"
    if rec.get("final_knowledge"):
        return "synced_to_notion"
    if rec.get("ai_analysis"):
        return "completed"
    if rec.get("original_understanding") or valid(rec.get("current_understanding")):
        return "understanding_written"
    return "waiting_for_understanding" if rec.get("prepared") else "studying"


def readiness(rec, ctx=None):
    """UMA regra para “posso processar?” e “o que está acontecendo?”, usada pelo servidor (submit) e pelas três
    interfaces. blocked = nada a fazer ainda (o texto em si é conferido à parte: problem). Devolve phase, label (curto),
    detail, tone (ok | wait | busy | error) e blocked."""
    ctx = context() if ctx is None else ctx
    job = ctx.get("job") or {}
    mine = bool(job.get("running")) and job.get("key") == rec["key"]

    def out(phase, label, detail="", tone="wait", blocked=True):
        return {"phase": phase, "label": label, "detail": detail, "tone": tone, "blocked": blocked}
    if analyzing == rec["key"]:
        return out("processing", "Analisando sua compreensão…",
                   job.get("detail") if mine and job.get("kind") == "analyze" else "", "busy")
    if rec.get("final_knowledge"):
        return out("synced", "Material salvo", "", "ok")
    if rec.get("processing_since"):  # o pedido foi feito e a análise não terminou (erro, cancelada ou o app fechou)
        return out("interrupted", "Não foi possível analisar", "Sua compreensão está guardada. Tente de novo.", "error", False)
    if rec.get("ai_analysis"):
        return out("completed", "Análise concluída", "", "ok", False)
    if not rec.get("prepared"):
        if mine and job.get("kind") == "process":
            return out("preparing", "Preparando a aula…", "A análise será liberada quando o conteúdo estiver pronto.", "busy")
        return out("prep_failed", "A preparação da aula não terminou", "Abra o Lumen e use “Preparar de novo”.", "error")
    if ctx.get("recording"):
        return out("recording", "Termine a gravação para analisar", "Pare a gravação em andamento; sua nota continua salva.")
    if job.get("running"):
        return out("busy", "Aguardando outra tarefa terminar", job.get("detail") or "")
    why = problem(rec["current_understanding"])
    if why:
        empty = not (rec["current_understanding"] or "").strip()
        return out("writing", "Escreva sua compreensão para continuar" if empty else why, "", "wait", True)
    return out("ready", "Pronto para analisar", "", "ok", False)


def view(rec):
    """A nota, a análise e o estado; nunca a transcrição."""
    return {"key": rec["key"], "created": rec.get("created"), "title": rec.get("title"), "label": rec.get("label"),
            "state": state(rec),
            "text": rec["current_understanding"], "at": rec.get("current_at", 0),
            "original": rec.get("original_understanding"), "submitted": rec.get("submitted"),
            "analysis": rec.get("ai_analysis"), "analyzed_text": rec.get("analyzed_text"), "model": rec.get("model"),
            "final_knowledge": rec.get("final_knowledge"), "problem": problem(rec["current_understanding"]),
            "spec": rec.get("spec") or {}, "updated": rec.get("updated"), "rev": rec.get("rev", 0),
            "analyzed_rev": rec.get("analyzed_rev"), "ready": readiness(rec)}


def get(key):
    rec = load(key)
    if not rec:
        raise AppError("Esta aula não foi encontrada.", "Escolha a aula de novo.")
    return view(rec)


def pending(extra=None):
    """“Continuar aprendendo”: aulas preparadas (ou com rascunho) que ainda não foram salvas no Notion. extra: a aula
    que a tarefa atual está preparando (a barra lateral e a flutuante já precisam dela, mesmo sem texto)."""
    out, ctx = [], context()
    for f in (store.DATA / "understanding").glob("*.json"):
        rec = _read(f)
        if rec and "key" in rec and not rec.get("final_knowledge") and (
                rec.get("prepared") or rec.get("current_understanding", "").strip() or rec["key"] == extra):
            out.append({"key": rec["key"], "title": rec.get("title"), "label": rec.get("label"), "state": state(rec),
                        "updated": rec.get("updated"), "at": rec.get("current_at", 0), "rev": rec.get("rev", 0),
                        "ready": readiness(rec, ctx)})
    return sorted(out, key=lambda r: r["updated"] or "", reverse=True)[:30]
