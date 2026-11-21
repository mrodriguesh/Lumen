"""Geração do material de estudo com um modelo local via Ollama (http://127.0.0.1:11434)."""
import json
import re
import time
import urllib.error
import urllib.request

from . import AppError
from .package import QUESTION_KINDS, RELATIONS
from .understanding import check as require_understanding

OLLAMA = "http://127.0.0.1:11434"
SINGLE_PASS_CHARS = 40_000   # ~12k tokens: cabe em num_ctx 20k com folga para a resposta
CHUNK_CHARS = 20_000

_TS = {"type": "string"}
_LIST = {"type": "array", "items": {"type": "string"}}
MAP_KINDS = ["conceitual", "tutorial", "argumentacao", "sistema", "livro"]
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "simple_explanation": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "explanation": {"type": "string"}, "why": {"type": "string"},
            "timestamp": _TS}, "required": ["title", "explanation", "why", "timestamp"]}},
        "glossary": {"type": "array", "items": {"type": "object", "properties": {
            "term": {"type": "string"}, "definition": {"type": "string"}}, "required": ["term", "definition"]}},
        "examples": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "origin": {"type": "string", "enum": ["aula", "didatico"]}},
            "required": ["text", "origin"]}},
        "steps": {"type": "array", "items": {"type": "string"}},
        "review_questions": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": list(QUESTION_KINDS)},
            "question": {"type": "string"}, "answer": {"type": "string"}}, "required": ["kind", "question", "answer"]}},
        "key_moments": {"type": "array", "items": {"type": "object", "properties": {
            "timestamp": _TS, "label": {"type": "string"}}, "required": ["timestamp", "label"]}},
        "caveats": {"type": "array", "items": {"type": "string"}},
        "map_kind": {"type": "string", "enum": MAP_KINDS},
        "mind_map": {"type": "object", "properties": {
            "center": {"type": "string"},
            "branches": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "emoji": {"type": "string"},
                "children": {"type": "array", "items": {"type": "string"}}},
                "required": ["label", "emoji", "children"]}}},
            "required": ["center", "branches"]},
        "relations": {"type": "array", "items": {"type": "object", "properties": {
            "from": {"type": "string"}, "type": {"type": "string", "enum": list(RELATIONS)}, "to": {"type": "string"}},
            "required": ["from", "type", "to"]}},
        "mistakes": _LIST, "applications": _LIST, "open_questions": _LIST, "permanent_ideas": _LIST,
    },
    "required": ["title", "summary", "simple_explanation", "topics", "glossary", "examples", "steps",
                 "review_questions", "key_moments", "caveats", "map_kind", "mind_map", "relations", "mistakes",
                 "applications", "open_questions", "permanent_ideas"],
}

SYSTEM = """Você é um professor que prepara material de estudo a partir da transcrição de uma aula.
Regras:
- Use somente informações presentes na transcrição. Não invente fatos, números, nomes, datas nem referências.
- Linhas marcadas com (?) podem ter sido mal transcritas: não as apresente como fato confirmado.
- Linhas "(na tela)", quando houver, trazem o que apareceu no vídeo (slide, quadro, código, tabela), lido da imagem.
  Fazem parte da aula: use-as para acertar termos, nomes, números e fórmulas que a fala pode ter transcrito errado
  e para completar tópicos, glossário, exemplos e passo a passo com os dados, valores e fórmulas mostrados. Não
  copie código nem tabelas inteiros: a página já mostra as telas; explique o que eles dizem.
- title: título claro e específico do assunto da aula.
- summary: 3 a 6 frases com as ideias centrais.
- simple_explanation: explique o assunto para um iniciante, em linguagem simples. Pode usar analogias, sem acrescentar fatos novos.
- topics: principais tópicos na ordem da aula. why = por que esse tópico importa, em 1 frase. timestamp = um marcador
  [mm:ss] existente na transcrição onde o tópico começa, ou "" se não houver marcadores.
- glossary: termos técnicos citados e o significado dado na aula (lista vazia se não houver).
- examples: exemplos citados na aula (origin "aula") e, só se ajudarem, analogias suas (origin "didatico").
- steps: passo a passo apenas se a aula ensinar um procedimento; senão, lista vazia.
- review_questions: 6 a 12 perguntas com respostas baseadas na aula, de tipos variados (kind): recordacao ("O que é
  X?"), compreensao ("Por que X acontece?"), relacao ("Qual a relação entre X e Y?"), aplicacao ("Como você aplicaria
  X neste cenário?"), diagnostico ("O que aconteceria se Y fosse removido?"), sintese ("Como X, Y e Z formam um
  todo?"). No máximo metade de recordacao. Nada de pergunta trivial, de sim ou não, ou respondida no próprio enunciado.
- key_moments: até 10 momentos úteis para revisar, com marcador [mm:ss] existente (lista vazia se não houver marcadores).
- caveats: trechos confusos ou possivelmente mal transcritos e pontos que a aula não deixou claros (lista vazia se não houver).
- map_kind: o tipo de aula, que decide a forma do mind_map: conceitual (ramos = conceitos, com propriedades,
  exemplos e relações), tutorial (objetivo, pré-requisitos, passos, resultado), argumentacao (tese, argumentos,
  evidências, contra-argumentos, conclusão), sistema (componentes, fluxo, dependências, dados, riscos) ou livro
  (capítulos ou partes, ideias, evidências, aplicações).
- mind_map: mapa mental fiel à aula, com a forma do map_kind. center = o tema central em até 5 palavras. branches = as grandes ideias da
  aula, de 2 a 7 conforme o conteúdo (label com até 5 palavras e um emoji que represente o ramo), cada uma com 1 a 4
  children: fatos, termos, exemplos ou passos concretos ditos na aula, em até 8 palavras. Aula curta = mapa pequeno:
  nunca complete com frases genéricas ("impacto global", "importância do tema", "foco da aula"), nem repita itens
  entre ramos.
- relations: até 8 relações que a aula afirma entre itens do mind_map. from e to são exatamente o texto do center, de
  um label ou de um children; type: causa, depende de, exemplo de, contrasta com, leva a, parte de, usado em. Lista
  vazia se a aula não relacionar os itens.
- mistakes: erros e confusões prováveis de quem estuda este assunto, ligados ao que a aula explica (até 5).
- applications: onde este conhecimento se aplica na prática, sem inventar fatos (até 5).
- open_questions: o que a aula deixou sem resposta ou vale pesquisar depois (até 5).
- permanent_ideas: até 5 ideias da aula que valem virar nota permanente do aluno, cada uma uma afirmação curta,
  completa e com sentido sozinha.
- A profundidade acompanha a aula: aula curta, material curto; aula densa, mais tópicos e perguntas. Não encha listas.
- O aluno estudou a aula e escreveu primeiro o que entendeu (no fim do pedido, "Compreensão do aluno"). Este
  material complementa a compreensão dele, não a substitui: dê mais espaço e clareza ao que ele não mencionou,
  entendeu em parte ou pode ter confundido. Não copie, não resuma e não reescreva a nota dele.
{lang}
Responda somente com JSON neste formato: {schema}"""

NOTES = """Você está lendo a parte {i} de {n} da transcrição de uma aula. Escreva notas detalhadas desta parte:
tópicos, definições, exemplos, procedimentos e nomes próprios citados. Mantenha os marcadores [mm:ss] dos
momentos importantes e o conteúdo das linhas "(na tela)" (slides, fórmulas, código). Use somente o que está no
texto; não invente. {lang}"""

ANALYSIS_SCHEMA = {  # a ordem é a ordem em que o modelo pensa: com as confusões depois dos acertos e das ideias
    "type": "object",  # parciais, uma frase meio certa e meio errada ia sempre para “parciais” (3 de 3 no qwen3:8b)
    "properties": {
        "confusoes": {"type": "array", "items": {"type": "object", "properties": {
            "trecho": {"type": "string"}, "correcao": {"type": "string"}}, "required": ["trecho", "correcao"]}},
        "acertos": _LIST, "parciais": _LIST, "lacunas": _LIST, "complementos": _LIST, "conexoes": _LIST,
        "perguntas": _LIST,
    },
    "required": ["confusoes", "acertos", "parciais", "lacunas", "complementos", "conexoes", "perguntas"],
}

ANALYSIS = """Você é um assistente de aprendizagem.
O estudante primeiro estudou a aula e depois escreveu, com as próprias palavras, o que entendeu. Seu trabalho não é
substituir a compreensão dele, e sim analisá-la em comparação com o conteúdo original da aula, para ele aprender mais.

Regras:
- A nota do estudante é a fonte principal. A aula (transcrição e o que apareceu na tela) é a referência para conferir.
- Preserve a interpretação dele. Não reescreva a nota, não a resuma e não a apresente como sua.
- Não faça um resumo genérico da aula. Cada item precisa dizer respeito ao que ELE escreveu ou deixou de escrever.
- Use só o que a aula diz. Não invente fatos. Linhas marcadas com (?) podem ter sido mal transcritas: não aponte um
  erro do estudante com base nelas. Se a aula não trata de algo que ele escreveu, não diga que está errado.
- Fale com o estudante em "você", com frases curtas, claras e gentis. Sem elogios vazios.
- confusoes (comece por aqui): confira cada frase da nota contra a aula. Toda afirmação que contradiz a aula entra
  aqui (até 4): troca de conceitos, de etapa ou fase (o que acontece onde e quando), de origem (de onde algo vem),
  causa e efeito invertidos, números, nomes ou definições diferentes da aula. Uma frase meio certa e meio errada
  também entra aqui. trecho = as palavras exatas dele, copiadas da nota; correcao = o que a aula diz de fato.
  Lista vazia se não houver.
- Em acertos e parciais, só o que a nota diz: nunca atribua a ele algo que ele não escreveu (isso é lacuna).
- acertos: o que ele entendeu corretamente segundo a aula (até 5), em poucas palavras, sem copiar a frase inteira.
- parciais: ideias certas, mas incompletas: o que está certo e o que falta (até 4). Nada que já esteja em confusoes.
- lacunas: pontos importantes da aula que a nota não menciona, do mais importante ao menos (até 5).
- complementos: informações da aula que completam exatamente o que ele escreveu (até 4).
- conexoes: relações entre conceitos da aula que ele deixou passar (até 3).
- perguntas: 3 a 5 perguntas para ele aprofundar, baseadas no que escreveu e no que faltou (sem as respostas).
- Cada ponto aparece numa lista só. Listas vazias quando não houver nada útil. Prefira menos itens, mais úteis.
{lang}
Responda somente com JSON neste formato: {schema}"""


def fmt_time(seconds):
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def parse_time(value):
    m = re.fullmatch(r"\[?\s*(?:(\d+):)?(\d{1,2}):(\d{2})\s*\]?", str(value or "").strip())
    return int(m[1] or 0) * 3600 + int(m[2]) * 60 + int(m[3]) if m else None


def transcript_text(segments, screens=()):
    """Agrupa segmentos em parágrafos de ~30 s com marcador [mm:ss]; (?) marca baixa confiança.

    screens: [(segundos, texto)] do que apareceu na tela (vision.screen_lines), intercalados no tempo certo."""
    paras, cur, start = [], [], None
    for s in segments:
        if start is None:
            start = s.get("start")
        cur.append(("(?) " if s.get("uncertain") else "") + s["text"])
        if s.get("start") is None or (s.get("end") or 0) - (start or 0) >= 30:
            paras.append((start, " ".join(cur)))
            cur, start = [], None
    if cur:
        paras.append((start, " ".join(cur)))
    if screens:  # sem marcadores de tempo na transcrição, as telas vêm antes
        paras = sorted(paras + list(screens), key=lambda p: p[0] if p[0] is not None else float("inf"))
    return "\n".join((f"[{fmt_time(t)}] " if t is not None else "") + text for t, text in paras)


def chunks(text, size=CHUNK_CHARS):
    # linhas gigantes (transcrição sem quebras) são cortadas antes de agrupar
    lines = [ln[i:i + size] for ln in text.split("\n") for i in range(0, max(len(ln), 1), size)]
    out, cur = [], ""
    for line in lines:
        if cur and len(cur) + len(line) + 1 > size:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out


# --- Ollama ----------------------------------------------------------------

DOWN_FOR = 4.0   # segundos em que uma falha ao falar com o Ollama vale para as consultas seguintes (mesmo endereço)
_down = {}       # endereço do Ollama → instante (time.monotonic) da última falha


def models():
    """Modelos instalados, ou None se o Ollama não estiver rodando. Com o Ollama parado, cada tentativa custa ~2 s no
    Windows e a tela de Estudos pergunta várias vezes por abertura (modelo principal, rápido, Máximo, perfil adulto, estado):
    uma falha recente vale por DOWN_FOR segundos, para a tela abrir em ~2 s e não em ~14 s. Uma resposta boa limpa a falha."""
    base = OLLAMA
    if time.monotonic() - _down.get(base, -DOWN_FOR) < DOWN_FOR:
        return None
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=3) as r:
            out = [m["name"] for m in json.load(r).get("models", [])]
    except (OSError, ValueError):
        _down[base] = time.monotonic()
        return None
    _down.pop(base, None)
    return out


def _stream(path, body, check, timeout=900):
    req = urllib.request.Request(OLLAMA + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for line in r:
                check()
                if line.strip():
                    d = json.loads(line)
                    if "error" in d:
                        raise AppError(f"O Ollama informou um erro: {str(d['error'])[:200]}",
                                       "Confira o modelo em Ajustes → IA local e tente de novo.")
                    yield d
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise AppError(f"O modelo “{body.get('model')}” não está instalado no Ollama.",
                           "Abra Ajustes → IA local e baixe o modelo.") from None
        try:  # o motivo vem no corpo (ex.: "does not support tools/thinking"); quem chama decide pelo texto
            detail = str(json.loads(e.read() or b"{}").get("error") or "")[:200]
        except (OSError, ValueError, AttributeError):
            detail = ""
        raise AppError(f"O Ollama recusou o pedido (HTTP {e.code})" + (f": {detail}" if detail else "."), "Tente de novo.") from None
    except (urllib.error.URLError, ConnectionError):
        raise AppError("O Ollama não está rodando.", "Abra o aplicativo Ollama e tente de novo.") from None
    except TimeoutError:
        raise AppError("O modelo demorou demais para responder.",
                       "Tente de novo ou escolha um modelo menor em Ajustes → IA local.") from None


def release_vram():
    """Pede ao Ollama para descarregar da GPU os modelos de texto carregados (keep_alive=0). Ele recarrega sozinho
    no próximo pedido. True se havia algo para liberar."""
    try:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=3) as r:
            names = [m["name"] for m in json.load(r).get("models", [])]
    except (OSError, ValueError, KeyError):
        return False
    for name in names:
        req = urllib.request.Request(OLLAMA + "/api/generate", json.dumps({"model": name, "keep_alive": 0}).encode(),
                                     {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15).close()
        except OSError:
            pass
    return bool(names)


def pull(model, progress, check):
    for d in _stream("/api/pull", {"model": model, "stream": True}, check, timeout=3600):
        if d.get("total"):
            progress(d.get("completed", 0) / d["total"], None)


# Teto de cada resposta (tokens), ~3× o normal: sem ele, a IA às vezes repete texto até encher o contexto e o
# Ollama segue gerando (notas de uma aula longa passaram de 9 min numa só parte). As notas cabem juntas numa leitura.
MAX_OUT = {"notes": 2500, "lesson": 6000, "charts": 2048, "analysis": 2500, "refine": 6000, "connect": 1200}
MAX_SPLITS = 2  # partes que generate relê em dois pedaços quando as notas são cortadas no teto


def _chat(model, system, user, check, tokens, schema=None, num_ctx=20480, temperature=0.2, keep_alive="5m",
          images=None, kind=None, limit=None, on_cut=None):
    """Uma resposta da IA. kind ("lesson", "notes", "charts"): etapa da estimativa de tempo (eta) que ela ocupa e
    o seu teto (MAX_OUT); limit: outro teto. on_cut(): chamado se a resposta parou no teto, no meio (incompleta)."""
    from . import eta
    plan = eta.current
    if plan and kind:
        plan.at(kind)
    out = []
    for d in _stream_chat(model, system, user, check, schema, num_ctx, temperature, keep_alive, images,
                          limit or MAX_OUT.get(kind)):
        if d.get("done"):
            if d.get("done_reason") == "length" and on_cut:
                on_cut()
            eta.learn_llm(model, kind, d, len(system) + len(user))
            continue
        out.append(d.get("message", {}).get("content", ""))
        tokens(len(out))
        if plan and kind:
            plan.writing(model, kind, len(out), len(system) + len(user))
    return "".join(out)


def _stream_chat(model, system, user, check, schema, num_ctx, temperature, keep_alive, images, limit):
    body = {"model": model, "stream": True, "think": False, "keep_alive": keep_alive,
            "options": {"num_ctx": num_ctx, "temperature": temperature, **({"num_predict": limit} if limit else {})},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user, **({"images": images} if images else {})}]}
    if schema:
        body["format"] = schema
    yield from _stream("/api/chat", body, check)


# --- Validação ---------------------------------------------------------------

def _s(v, limit=4000):
    return str(v).strip()[:limit] if isinstance(v, (str, int, float)) else ""


def validate(data, duration=None, has_times=True):
    """Confere e limpa a resposta do modelo. Resposta inútil → AppError (nada é publicado)."""
    bad = AppError("A IA devolveu um resultado incompleto.",
                   "Tente de novo; se persistir, escolha outro modelo em Ajustes → IA local.")
    if not isinstance(data, dict):
        raise bad

    def items(key, fields, cap, optional=("timestamp",)):
        out = []
        for it in data.get(key) or []:
            if isinstance(it, dict):
                it = {f: _s(it.get(f)) for f in fields}
                if all(it[f] for f in fields if f not in optional):
                    out.append(it)
        return out[:cap]

    def ts(v):
        t = parse_time(v) if has_times else None
        return t if t is not None and (not duration or t <= duration + 5) else None

    lesson = {
        "title": _s(data.get("title"), 180),
        "summary": _s(data.get("summary")),
        "simple_explanation": _s(data.get("simple_explanation")),
        "topics": [{**t, "timestamp": ts(t["timestamp"])}
                   for t in items("topics", ("title", "explanation", "timestamp", "why"), 15, ("timestamp", "why"))],
        "glossary": items("glossary", ("term", "definition"), 25),
        "examples": [e for e in items("examples", ("text", "origin"), 12) if e["origin"] in ("aula", "didatico")],
        "steps": [_s(x) for x in data.get("steps") or [] if _s(x)][:20],
        "review_questions": [{**q, "kind": q["kind"] if q["kind"] in QUESTION_KINDS else ""} for q in items(
            "review_questions", ("question", "answer", "kind"), 14, ("kind",))],
        "key_moments": [m for m in ({**m, "timestamp": ts(m["timestamp"])}
                                    for m in items("key_moments", ("timestamp", "label"), 15))
                        if m["timestamp"] is not None],
        "caveats": [_s(x, 500) for x in data.get("caveats") or [] if _s(x)][:10],
        "mind_map": data.get("mind_map") if isinstance(data.get("mind_map"), dict) else None,  # limpo em mindmap.data
        "map_kind": data.get("map_kind") if data.get("map_kind") in MAP_KINDS else "conceitual",
        "relations": [r for r in items("relations", ("from", "type", "to"), 8) if r["type"] in RELATIONS],
        **{k: [_s(x, 500) for x in data.get(k) or [] if _s(x)][:5]
           for k in ("mistakes", "applications", "open_questions", "permanent_ideas")},
    }
    if not (lesson["title"] and lesson["summary"] and lesson["simple_explanation"]
            and lesson["topics"] and lesson["review_questions"]):
        raise bad
    return lesson


def validate_analysis(data):
    """Confere e limpa a análise da compreensão. Sem o que dizer ao estudante → AppError (nada é guardado)."""
    if not isinstance(data, dict):
        raise AppError("A IA devolveu uma análise incompleta.", "Tente de novo.")

    def texts(key, cap):
        return [_s(x, 600) for x in data.get(key) or [] if _s(x, 600)][:cap]
    out = {"acertos": texts("acertos", 5), "parciais": texts("parciais", 4), "lacunas": texts("lacunas", 5),
           "confusoes": [c for c in ({"trecho": _s(c.get("trecho"), 400), "correcao": _s(c.get("correcao"), 600)}
                                     for c in data.get("confusoes") or [] if isinstance(c, dict))
                         if c["trecho"] and c["correcao"]][:4],
           "complementos": texts("complementos", 4), "conexoes": texts("conexoes", 3), "perguntas": texts("perguntas", 5)}
    if not out["perguntas"] or not (out["acertos"] or out["parciais"] or out["lacunas"] or out["confusoes"]):
        raise AppError("A IA devolveu uma análise incompleta.", "Tente de novo.")
    return out


def calls(segments, model, screens=(), final="lesson", extra=0):
    """As respostas que generate (final="lesson") ou analyze (final="analysis") vão pedir à IA, [(tipo, caracteres
    do pedido)], para estimar o tempo: aula longa é lida por partes (notas) antes. As partes são as de verdade (o
    corte é por linha); nas rodadas seguintes, o texto das notas do tamanho que a IA costuma escrever
    (eta.out_tokens), cortado do mesmo jeito. extra: caracteres da nota do estudante, que vão no mesmo pedido."""
    from . import eta
    text, out, rnd, budget = transcript_text(segments, screens), [], 0, SINGLE_PASS_CHARS - extra
    per = eta.value("chars_per_token", model)
    while len(text) > budget:
        rnd += 1
        parts = chunks(text)
        out += [("notes", len(p) + len(NOTES)) for p in parts]
        text = "\n\n".join("n" * int(eta.out_tokens(model, "notes", (len(p) + len(NOTES)) / per) * per)
                           for p in parts)
        if rnd >= 3:
            text = text[:budget]
    system, schema = (SYSTEM, SCHEMA) if final == "lesson" else (ANALYSIS, ANALYSIS_SCHEMA)
    return out + [(final, len(text) + extra + len(system) + len(json.dumps(schema, ensure_ascii=False)))]


def _lang(language):
    return ("Escreva tudo em português do Brasil." if language == "pt"
            else "Escreva no mesmo idioma em que a aula foi falada.")


def _condense(text, model, lang, check, status, budget):
    """Aula longa: lida por partes (notas de cada parte) até caber num pedido junto da nota do estudante.
    Devolve (texto, partes que a IA não terminou de resumir)."""
    rnd, lost, splits = 0, [], [MAX_SPLITS]

    def read_part(part, i, n, again=True):
        """Notas de uma parte. Resposta cortada no teto (a parte tem muito conteúdo): a parte é lida de novo em dois
        pedaços, no máximo MAX_SPLITS vezes na aula toda (se a IA se repete, todas as partes cortam e reler cada uma
        multiplicaria o tempo: já levou 27 min em vez de 3). O que ainda cortar segue como veio e a página avisa."""
        cut = []
        notes = _chat(model, NOTES.format(i=i, n=n, lang=lang), part, check, lambda k: None, num_ctx=12288,
                      kind="notes" if again else None, limit=MAX_OUT["notes"], on_cut=lambda: cut.append(1))
        if not cut:
            return notes
        if again and splits[0] > 0 and len(part) > 2000:
            splits[0] -= 1
            return "\n\n".join(read_part(p, i, n, False) for p in chunks(part, len(part) // 2 + 1))
        lost.append(i)
        return notes

    while len(text) > budget:  # aula longa: resume por partes e junta as notas
        rnd += 1
        parts = chunks(text)
        notes = []
        for i, part in enumerate(parts, 1):
            status(f"Lendo a aula por partes ({i} de {len(parts)})…", (i - 1) / len(parts))
            notes.append(read_part(part, i, len(parts)))
        text = "\n\n".join(notes)
        if rnd >= 3:
            text = text[:budget]
    return text, lost


def generate(segments, duration, model, language, check, status, redo=False, note="", screens=(), understanding="",
             deep=False):
    """Transcrição + compreensão do aluno → material de estudo validado. status(detail, progress).

    understanding: a nota que o aluno escreveu antes; sem ela (válida), nada é gerado (lumen/understanding.py).
    redo: o aluno pediu para refazer a página; note: o que ele quer diferente (opcional).
    screens: o que apareceu na tela (vision.screen_lines), intercalado na transcrição.
    deep: modo Profundo, uma 2ª passada critica e melhora o material (_refine), com a mesma aula já condensada."""
    require_understanding(understanding)
    lang = _lang(language)
    has_times = any(s.get("start") is not None for s in segments)
    # ponytail: aula longa é lida por partes aqui e de novo em analyze; guardar as notas se o tempo incomodar
    text, lost = _condense(transcript_text(segments, screens), model, lang, check, status,
                           SINGLE_PASS_CHARS - len(understanding))
    system = SYSTEM.format(lang=lang, schema=json.dumps(SCHEMA, ensure_ascii=False))
    ask = ""
    if redo:
        ask = ("O aluno não gostou da versão anterior desta página e pediu uma nova, com outra organização e outras "
               "palavras, sempre fiel à aula.")
        note = " ".join(str(note or "").split())[:300]
        if note:
            ask += f" Pedido do aluno: {note}"
        ask += "\n\n"
    for attempt in (1, 2):
        status("Escrevendo o material de estudo…" + (" (2ª tentativa)" if attempt == 2 else ""), None)
        head = "Transcrição da aula, com o que apareceu na tela:" if screens else "Transcrição da aula:"
        mine = "\n\n---\nCompreensão do aluno (escrita por ele antes deste material; complemente, não reescreva):\n\n"
        raw = _chat(model, system, ask + head + "\n\n" + text + mine + understanding, check,
                    lambda n: status(f"Escrevendo o material de estudo… ({n} trechos gerados)", None),
                    schema=SCHEMA, temperature=0.6 if redo else 0.2, kind="lesson")
        try:
            lesson = validate(json.loads(raw), duration, has_times)
            if lost:  # visível na página, em “Pontos de atenção”: nada se perde em silêncio
                lesson["caveats"] = ["Parte da aula foi lida de forma incompleta (a IA não terminou o resumo da "
                                     "parte " + ", ".join(map(str, sorted(set(lost)))) + "); confira a aula original "
                                     "nesses trechos."] + lesson["caveats"][:9]
        except (ValueError, AppError):
            if attempt == 2:
                raise AppError("A IA devolveu um resultado malformado duas vezes.",
                               "Tente de novo; se persistir, escolha outro modelo em Ajustes → IA local.") from None
            continue
        return _refine(lesson, text, model, lang, check, status, understanding, duration, has_times) if deep else lesson


REFINE = """Você revisa um material de estudo gerado por IA a partir de uma aula, conferindo com a própria aula, e devolve
uma versão melhor no mesmo formato. Corrija:
- conceitos importantes da aula que ficaram de fora (tópicos, glossário, mapa);
- resumo genérico ou que não bate com a aula;
- perguntas fracas (triviais, ambíguas, respondidas no enunciado), respostas erradas e falta de variedade de tipos;
- relações que a aula não sustenta, itens repetidos entre seções e listas cheias de frases vagas;
- qualquer afirmação que não esteja na aula: tire.
Use só o que está na aula. Não invente fatos, números, nomes nem referências. Mantenha os marcadores [mm:ss]
existentes. A compreensão do aluno continua sendo dele: complemente o que ele não mencionou, não a reescreva.
{lang}
Responda somente com JSON neste formato: {schema}"""


def _refine(lesson, text, model, lang, check, status, understanding, duration, has_times):
    """Modo Profundo: crítica do material contra a aula, devolvendo o mesmo esquema. Resposta inútil → fica a 1ª
    versão (a crítica nunca impede a página)."""
    status("Revisando o material (modo profundo)…", None)
    draft = {**lesson, "topics": [{**t, "timestamp": f"[{fmt_time(t['timestamp'])}]" if t["timestamp"] is not None else ""}
                                  for t in lesson["topics"]],
             "key_moments": [{**m, "timestamp": f"[{fmt_time(m['timestamp'])}]"} for m in lesson["key_moments"]]}
    system = REFINE.format(lang=lang, schema=json.dumps(SCHEMA, ensure_ascii=False))
    user = ("Aula:\n\n" + text + "\n\n---\nMaterial gerado (revise e melhore):\n\n" + json.dumps(draft, ensure_ascii=False)
            + "\n\n---\nCompreensão do aluno:\n\n" + understanding)
    need = int((len(system) + len(user)) / 2.6) + MAX_OUT["refine"]
    try:
        raw = _chat(model, system, user, check, lambda n: status(f"Revisando o material (modo profundo)… ({n} trechos)",
                                                                  None),
                    schema=SCHEMA, num_ctx=min(max(20480, need), 32768), kind="refine")
        better = validate(json.loads(raw), duration, has_times)
    except (ValueError, AppError):
        return lesson
    lost = [c for c in lesson["caveats"] if c.startswith("Parte da aula foi lida")]
    better["caveats"] = list(dict.fromkeys(lost + better["caveats"]))[:10]
    return {**better, "refined": True}


LINK_RELATIONS = ["fundamenta", "aprofunda", "aplica", "exemplo de", "contrasta com", "depende de", "usado no projeto",
                  "relacionado"]
CONNECT = """Você ajuda um estudante a ligar uma aula nova às notas que ele já tem no Obsidian (o segundo cérebro dele).
Regras:
- links: entre as notas candidatas, só as que têm relação conceitual real com a aula. Palavra igual não é conexão.
  Poucas e boas (até 6); lista vazia se nenhuma servir. Nunca cite nota fora da lista.
- strength: forte (a nota trata do mesmo conceito ou o aplica), media (relação clara e útil para estudar) ou fraca
  (só palavras ou temas parecidos). Seja rigoroso: na dúvida, fraca.
- relation: fundamenta, aprofunda, aplica, exemplo de, contrasta com, depende de, usado no projeto (só para projetos) ou
  relacionado.
- reason: uma frase com a relação concreta entre a aula e aquela nota.
- anchors: os Anchor Topics (mapas de assunto do cofre) a que a aula claramente pertence, de 0 a 2.
- anchor_suggestion: se nenhum Anchor Topic servir, o nome curto de um tema que serviria; senão "".
{lang}
Responda somente com JSON neste formato: {schema}"""


def connect(lesson, candidates, anchors, model, language, check, status):
    """Conexões com o cofre. candidates/anchors: [{name, kind, excerpt}] (vault.search, só no PC). Os nomes vão num
    enum do JSON Schema: o Ollama não consegue responder com uma nota que não existe."""
    names, tops = [c["name"] for c in candidates], [a["name"] for a in anchors]
    if not (names or tops):
        return {"links": [], "anchors": [], "anchor_suggestion": ""}
    schema = {"type": "object", "properties": {
        "links": {"type": "array", "items": {"type": "object", "properties": {
            "note": {"type": "string", "enum": names or [""]}, "relation": {"type": "string", "enum": LINK_RELATIONS},
            "reason": {"type": "string"}, "strength": {"type": "string", "enum": ["forte", "media", "fraca"]}},
            "required": ["note", "relation", "reason", "strength"]}},
        "anchors": {"type": "array", "items": {"type": "string", "enum": tops or [""]}},
        "anchor_suggestion": {"type": "string"}}, "required": ["links", "anchors", "anchor_suggestion"]}
    system = CONNECT.format(lang=_lang(language), schema=json.dumps(schema, ensure_ascii=False))
    terms = [t["title"] for t in lesson["topics"]] + [g["term"] for g in lesson.get("glossary") or []]
    user = (f"Aula: {lesson['title']}\nResumo: {lesson['summary'][:1200]}\nConceitos: {'; '.join(terms)[:1200]}\n\n"
            "Notas candidatas do cofre:\n" + "\n".join(f"- {c['name']} ({c['kind']}): {c['excerpt']}" for c in candidates)
            + "\n\nAnchor Topics do cofre:\n" + "\n".join(f"- {a['name']}: {a['excerpt']}" for a in anchors))
    for attempt in (1, 2):
        status("Encontrando conexões no seu cofre…", None)
        raw = _chat(model, system, user, check, lambda n: None, schema=schema, num_ctx=8192, temperature=0.1,
                    kind="connect")
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                break
        except ValueError:
            pass
        if attempt == 2:
            raise AppError("A IA não conseguiu sugerir conexões com o cofre.", "Tente de novo.")
    links, seen = [], set()
    for x in data.get("links") or []:
        if isinstance(x, dict) and x.get("note") in names and x["note"] not in seen and _s(x.get("reason")) \
                and x.get("strength") in ("forte", "media"):  # fraca = palavra parecida, não conexão
            seen.add(x["note"])
            links.append({"note": x["note"], "reason": _s(x["reason"], 300),
                          "relation": x.get("relation") if x.get("relation") in LINK_RELATIONS else "relacionado"})
    picked = list(dict.fromkeys(a for a in data.get("anchors") or [] if a in tops))[:2]
    return {"links": links[:6], "anchors": picked,
            "anchor_suggestion": "" if picked else " ".join(_s(data.get("anchor_suggestion"), 60).split())}


def analyze(segments, model, language, understanding, check, status, screens=()):
    """Aula + nota do estudante → análise da compreensão dele (acertos, lacunas, confusões…), não um resumo da aula.
    A nota nunca é alterada: ela só entra no pedido. Sem nota válida, a IA não é chamada."""
    require_understanding(understanding)
    lang = _lang(language)
    text, _ = _condense(transcript_text(segments, screens), model, lang, check, status,
                        SINGLE_PASS_CHARS - len(understanding))
    system = ANALYSIS.format(lang=lang, schema=json.dumps(ANALYSIS_SCHEMA, ensure_ascii=False))
    user = ("Conteúdo original da aula" + (" (transcrição e o que apareceu na tela)" if screens else " (transcrição)")
            + ":\n\n" + text + "\n\n---\nCompreensão escrita pelo estudante (o texto original dele; analise, não "
            "reescreva):\n\n" + understanding)
    for attempt in (1, 2):
        status("Comparando sua compreensão com a aula…" + (" (2ª tentativa)" if attempt == 2 else ""), None)
        raw = _chat(model, system, user, check, lambda n: None, schema=ANALYSIS_SCHEMA, kind="analysis")
        try:
            return validate_analysis(json.loads(raw))
        except (ValueError, AppError):
            if attempt == 2:
                raise AppError("A IA devolveu uma análise malformada duas vezes.",
                               "Tente de novo; se persistir, escolha outro modelo em Ajustes → IA local.") from None


# --- Enfeitar páginas novas (ícone, capa, destaque) ----------------------------

COVERS = {  # capas do próprio Notion (conferidas: respondem 200)
    "gradients_2": "gradiente laranja/coral quente", "gradients_3": "gradiente azul acinzentado sóbrio",
    "gradients_4": "rosa vibrante", "gradients_5": "gradiente roxo/lilás", "gradients_8": "gradiente verde-água suave",
    "solid_blue": "azul liso", "solid_red": "vermelho liso", "solid_yellow": "amarelo liso", "solid_beige": "bege liso",
}
CALLOUT_COLORS = ["blue_background", "purple_background", "pink_background", "red_background", "orange_background",
                  "yellow_background", "green_background", "brown_background", "gray_background"]
PALETTES = {  # paletas desenhadas (cores vivas que combinam); a IA escolhe pelo clima do assunto
    "tecnologia": (["#4f46e5", "#06b6d4", "#8b5cf6"], "índigo, ciano e violeta"),
    "ia_neon": (["#7c3aed", "#ec4899", "#22d3ee"], "roxo, rosa e ciano neon (IA, futuro)"),
    "oceano": (["#0ea5e9", "#2563eb", "#14b8a6"], "azuis e turquesa"),
    "ceu": (["#38bdf8", "#818cf8", "#f0abfc"], "azul-céu, lavanda e rosa claro"),
    "noite": (["#1e3a8a", "#3b82f6", "#a855f7"], "azul-noite e roxo"),
    "floresta": (["#15803d", "#84cc16", "#065f46"], "verdes de mata"),
    "natureza_sol": (["#16a34a", "#facc15", "#f97316"], "verde, amarelo-sol e laranja"),
    "saude": (["#14b8a6", "#22c55e", "#a3e635"], "verde-água e verde-limão"),
    "dinheiro": (["#047857", "#10b981", "#eab308"], "verde-dinheiro e dourado (vendas, negócios)"),
    "luxo": (["#312e81", "#a16207", "#facc15"], "azul profundo e ouro"),
    "por_do_sol": (["#f97316", "#ec4899", "#8b5cf6"], "laranja, rosa e roxo"),
    "fogo": (["#dc2626", "#f97316", "#facc15"], "vermelho, laranja e amarelo"),
    "doce": (["#f472b6", "#fb7185", "#c084fc"], "rosas e lilás"),
    "criativo": (["#f43f5e", "#a855f7", "#3b82f6"], "vermelho-rosado, roxo e azul (arte, design, vídeo)"),
    "terra": (["#92400e", "#d97706", "#65a30d"], "marrom, âmbar e verde-oliva"),
    "idiomas": (["#2563eb", "#e11d48", "#f59e0b"], "azul, vermelho e amarelo (bandeiras, viagem)"),
}
DECOR_SCHEMA = {
    "type": "object",
    "properties": {
        "emoji": {"type": "string"},
        "motifs": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "palette": {"type": "string", "enum": list(PALETTES)},
        "cover": {"type": "string", "enum": list(COVERS)},
        "color": {"type": "string", "enum": CALLOUT_COLORS},
        "subtitle": {"type": "string"},
        "image_prompt": {"type": "string"},
    },
    "required": ["emoji", "motifs", "palette", "cover", "color", "subtitle", "image_prompt"],
}
DECOR_SYSTEM = """Você decora páginas do Notion de um estudante. A partir do título da página, escolha:
- emoji: UM emoji de objeto, planta, animal ou símbolo que represente bem o assunto (nunca círculos ou
  quadrados coloridos como 🟢🔵🟥).
- motifs: 3 a 5 outros emojis ligados ao tema, para ilustrar a capa (sem repetir o principal, sem formas geométricas).
- palette: o nome da paleta de cores que mais combina com o assunto: {palettes}.
- cover: uma capa reserva, caso a desenhada não possa ser usada: {covers}.
- color: a cor do destaque no topo, harmonizando com a capa.
- subtitle: uma frase curta e convidativa (até 110 caracteres) dizendo o que a página vai reunir, por exemplo
  "Resumos, anotações e revisões das aulas de …". Não invente fatos, datas, nomes ou conteúdo do curso.
- image_prompt: EM INGLÊS, a descrição de uma ilustração bonita para a capa (1 a 2 frases): um objeto, personagem
  ou cena concreta que simbolize o assunto, o estilo e as cores da paleta escolhida. NUNCA telas, interfaces,
  programas, documentos, placas ou livros abertos (viram texto ilegível); nada de letras ou logotipos de marcas. Ex.: "A friendly white robot assembling glowing puzzle pieces with small tools on a workbench, purple and
  cyan neon light".
Escreva subtitle em português do Brasil. Responda só com JSON."""


_SHAPES = set("🟢🟡🟠🔴🟣🔵🟤⚫⚪🟥🟧🟨🟩🟦🟪🟫⬛⬜◼◻▪▫🔶🔷🔸🔹🔺🔻")


def _emoji(v, default="📘"):
    """Só aceita emoji de verdade: curto, sem nenhum caractere ASCII (evita texto e HTML na capa) e sem as
    formas geométricas coloridas, que deixam a capa sem tema."""
    v = str(v or "").strip()
    ok = 0 < len(v) <= 8 and all(ord(c) > 127 for c in v) and not (set(v) & _SHAPES)
    return v if ok else default


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_PALETTE = ["#4f46e5", "#0ea5e9", "#a855f7"]


def decorate(title, parent_path, model, check=lambda: None, variant=0):
    """Visual para uma página nova. Tudo validado; valor fora do permitido vira um padrão seguro.

    variant > 0 pede outra combinação (botão “Gerar outra”)."""
    system = DECOR_SYSTEM.format(covers="; ".join(f"{k} = {v}" for k, v in COVERS.items()),
                                 palettes="; ".join(f"{k} ({d})" for k, (_, d) in PALETTES.items()))
    extra = f"\nVariação {variant}: escolha uma paleta e emojis diferentes das óbvias." if variant else ""
    raw = _chat(model, system, f"Título: {title}\nDentro de: {parent_path or 'raiz'}{extra}", check, lambda n: None,
                schema=DECOR_SCHEMA, num_ctx=2048, limit=1024, temperature=0.2 if not variant else 0.9,
                keep_alive="0")  # libera a VRAM para o gerador de imagens logo em seguida
    try:
        d = json.loads(raw)
    except ValueError:
        raise AppError("A IA não respondeu no formato esperado.", "A página foi criada sem enfeites.") from None
    sub = " ".join(_s(d.get("subtitle"), 200).split())
    emoji = _emoji(d.get("emoji"))
    motifs = [m for m in (_emoji(x, "") for x in (d.get("motifs") or [])[:6]) if m and m != emoji][:5]
    pal = d.get("palette")
    palette = list(PALETTES[pal][0]) if isinstance(pal, str) and pal in PALETTES else list(DEFAULT_PALETTE)
    return {"emoji": emoji, "motifs": motifs, "palette": palette,
            "cover": d.get("cover") if d.get("cover") in COVERS else "gradients_3",
            "color": d.get("color") if d.get("color") in CALLOUT_COLORS else "blue_background",
            "subtitle": sub[:160],
            "image_prompt": " ".join(str(d.get("image_prompt") or "").split())[:600]}


def valid_decor(d):
    """Confere um enfeite vindo da interface (prévia aceita pelo usuário) antes de usar."""
    if not isinstance(d, dict):
        return None
    emoji = _emoji(d.get("emoji"))
    palette = [str(c) for c in (d.get("palette") or []) if _HEX.match(str(c))][:3]
    return {"emoji": emoji, "motifs": [m for m in (_emoji(x, "") for x in (d.get("motifs") or [])[:5]) if m],
            "palette": palette + DEFAULT_PALETTE[len(palette):],
            "cover": d.get("cover") if d.get("cover") in COVERS else "gradients_3",
            "color": d.get("color") if d.get("color") in CALLOUT_COLORS else "blue_background",
            "subtitle": " ".join(_s(d.get("subtitle"), 200).split())[:160]}
