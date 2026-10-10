"""Geração do material de estudo com um modelo local via Ollama (http://127.0.0.1:11434)."""
import json
import re
import urllib.error
import urllib.request

from . import AppError

OLLAMA = "http://127.0.0.1:11434"
SINGLE_PASS_CHARS = 40_000   # ~12k tokens: cabe em num_ctx 20k com folga para a resposta
CHUNK_CHARS = 20_000

_TS = {"type": "string"}
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "simple_explanation": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "explanation": {"type": "string"}, "timestamp": _TS},
            "required": ["title", "explanation", "timestamp"]}},
        "glossary": {"type": "array", "items": {"type": "object", "properties": {
            "term": {"type": "string"}, "definition": {"type": "string"}}, "required": ["term", "definition"]}},
        "examples": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "origin": {"type": "string", "enum": ["aula", "didatico"]}},
            "required": ["text", "origin"]}},
        "steps": {"type": "array", "items": {"type": "string"}},
        "review_questions": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"}, "answer": {"type": "string"}}, "required": ["question", "answer"]}},
        "key_moments": {"type": "array", "items": {"type": "object", "properties": {
            "timestamp": _TS, "label": {"type": "string"}}, "required": ["timestamp", "label"]}},
        "caveats": {"type": "array", "items": {"type": "string"}},
        "mind_map": {"type": "object", "properties": {
            "center": {"type": "string"},
            "branches": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "emoji": {"type": "string"},
                "children": {"type": "array", "items": {"type": "string"}}},
                "required": ["label", "emoji", "children"]}}},
            "required": ["center", "branches"]},
    },
    "required": ["title", "summary", "simple_explanation", "topics", "glossary", "examples", "steps",
                 "review_questions", "key_moments", "caveats", "mind_map"],
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
- topics: principais tópicos na ordem da aula. timestamp = um marcador [mm:ss] existente na transcrição onde o tópico começa, ou "" se não houver marcadores.
- glossary: termos técnicos citados e o significado dado na aula (lista vazia se não houver).
- examples: exemplos citados na aula (origin "aula") e, só se ajudarem, analogias suas (origin "didatico").
- steps: passo a passo apenas se a aula ensinar um procedimento; senão, lista vazia.
- review_questions: 4 a 8 perguntas que testem a compreensão, com respostas baseadas na aula.
- key_moments: até 10 momentos úteis para revisar, com marcador [mm:ss] existente (lista vazia se não houver marcadores).
- caveats: trechos confusos ou possivelmente mal transcritos e pontos que a aula não deixou claros (lista vazia se não houver).
- mind_map: mapa mental fiel à aula. center = o tema central em até 5 palavras. branches = as grandes ideias da
  aula, de 2 a 7 conforme o conteúdo (label com até 5 palavras e um emoji que represente o ramo), cada uma com 1 a 4
  children: fatos, termos, exemplos ou passos concretos ditos na aula, em até 8 palavras. Aula curta = mapa pequeno:
  nunca complete com frases genéricas ("impacto global", "importância do tema", "foco da aula"), nem repita itens
  entre ramos.
{lang}
Responda somente com JSON neste formato: {schema}"""

NOTES = """Você está lendo a parte {i} de {n} da transcrição de uma aula. Escreva notas detalhadas desta parte:
tópicos, definições, exemplos, procedimentos e nomes próprios citados. Mantenha os marcadores [mm:ss] dos
momentos importantes e o conteúdo das linhas "(na tela)" (slides, fórmulas, código). Use somente o que está no
texto; não invente. {lang}"""


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

def models():
    """Modelos instalados, ou None se o Ollama não estiver rodando."""
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except (OSError, ValueError):
        return None


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
                                       "Confira o modelo em Configurações e tente de novo.")
                    yield d
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise AppError(f"O modelo “{body.get('model')}” não está instalado no Ollama.",
                           "Abra Configurações e baixe o modelo.") from None
        raise AppError(f"O Ollama recusou o pedido (HTTP {e.code}).", "Tente de novo.") from None
    except (urllib.error.URLError, ConnectionError):
        raise AppError("O Ollama não está rodando.", "Abra o aplicativo Ollama e tente de novo.") from None
    except TimeoutError:
        raise AppError("O modelo demorou demais para responder.",
                       "Tente de novo ou escolha um modelo menor em Configurações.") from None


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


def _chat(model, system, user, check, tokens, schema=None, num_ctx=20480, temperature=0.2, keep_alive="5m",
          images=None):
    body = {"model": model, "stream": True, "think": False, "keep_alive": keep_alive,
            "options": {"num_ctx": num_ctx, "temperature": temperature},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user, **({"images": images} if images else {})}]}
    if schema:
        body["format"] = schema
    out = []
    for d in _stream("/api/chat", body, check):
        out.append(d.get("message", {}).get("content", ""))
        tokens(len(out))
    return "".join(out)


# --- Validação ---------------------------------------------------------------

def _s(v, limit=4000):
    return str(v).strip()[:limit] if isinstance(v, (str, int, float)) else ""


def validate(data, duration=None, has_times=True):
    """Confere e limpa a resposta do modelo. Resposta inútil → AppError (nada é publicado)."""
    bad = AppError("A IA devolveu um resultado incompleto.",
                   "Tente de novo; se persistir, escolha outro modelo em Configurações.")
    if not isinstance(data, dict):
        raise bad

    def items(key, fields, cap):
        out = []
        for it in data.get(key) or []:
            if isinstance(it, dict):
                it = {f: _s(it.get(f)) for f in fields}
                if all(it[f] for f in fields if f not in ("timestamp",)):
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
                   for t in items("topics", ("title", "explanation", "timestamp"), 15)],
        "glossary": items("glossary", ("term", "definition"), 25),
        "examples": [e for e in items("examples", ("text", "origin"), 12) if e["origin"] in ("aula", "didatico")],
        "steps": [_s(x) for x in data.get("steps") or [] if _s(x)][:20],
        "review_questions": items("review_questions", ("question", "answer"), 10),
        "key_moments": [m for m in ({**m, "timestamp": ts(m["timestamp"])}
                                    for m in items("key_moments", ("timestamp", "label"), 15))
                        if m["timestamp"] is not None],
        "caveats": [_s(x, 500) for x in data.get("caveats") or [] if _s(x)][:10],
        "mind_map": data.get("mind_map") if isinstance(data.get("mind_map"), dict) else None,  # limpo em mindmap.data
    }
    if not (lesson["title"] and lesson["summary"] and lesson["simple_explanation"]
            and lesson["topics"] and lesson["review_questions"]):
        raise bad
    return lesson


def generate(segments, duration, model, language, check, status, redo=False, note="", screens=()):
    """Transcrição → material de estudo validado. status(detail, progress).

    redo: o aluno pediu para refazer a página; note: o que ele quer diferente (opcional).
    screens: o que apareceu na tela (vision.screen_lines), intercalado na transcrição."""
    lang = ("Escreva tudo em português do Brasil." if language == "pt"
            else "Escreva no mesmo idioma em que a aula foi falada.")
    text = transcript_text(segments, screens)
    has_times = any(s.get("start") is not None for s in segments)
    rnd = 0
    while len(text) > SINGLE_PASS_CHARS:  # aula longa: resume por partes e junta as notas
        rnd += 1
        parts = chunks(text)
        notes = []
        for i, part in enumerate(parts, 1):
            status(f"Lendo a aula por partes ({i} de {len(parts)})…", (i - 1) / len(parts))
            notes.append(_chat(model, NOTES.format(i=i, n=len(parts), lang=lang), part, check,
                               lambda n: None, num_ctx=12288))
        text = "\n\n".join(notes)
        if rnd >= 3:
            text = text[:SINGLE_PASS_CHARS]
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
        raw = _chat(model, system, ask + head + "\n\n" + text, check,
                    lambda n: status(f"Escrevendo o material de estudo… ({n} trechos gerados)", None),
                    schema=SCHEMA, temperature=0.6 if redo else 0.2)
        try:
            return validate(json.loads(raw), duration, has_times)
        except (ValueError, AppError):
            if attempt == 2:
                raise AppError("A IA devolveu um resultado malformado duas vezes.",
                               "Tente de novo; se persistir, escolha outro modelo em Configurações.") from None


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
        "motifs": {"type": "array", "items": {"type": "string"}},
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
                schema=DECOR_SCHEMA, num_ctx=2048, temperature=0.2 if not variant else 0.9,
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
