"""Gráficos da aula: os números, datas e fórmulas que a aula disse ou mostrou viram gráficos animados (GIF).

Precisão: a IA local só propõe. Cada valor é conferido aqui na transcrição e nas telas junto do seu rótulo (no
mesmo trecho da fala ou na mesma linha da tela, ou na vizinha); um valor que não aparece assim derruba o gráfico
inteiro. Fórmulas são calculadas aqui (lista fechada de operações), não pela IA, e precisam estar escritas na aula.

Desenho: HTML/SVG no Edge headless, como o mapa mental. Todos os quadros da animação saem num só print (uma
grade) e viram GIF pelo FFmpeg do PyAV (palettegen + paletteuse): o Notion anima GIF sem clique.
"""
import ast
import io
import json
import logging
import math
import re
import subprocess
import tempfile
import unicodedata
from fractions import Fraction
from pathlib import Path

import numpy as np

from .cover import edge

log = logging.getLogger("lumen")

W, H = 1200, 675
FRAMES, FPS, COLS = 30, 25, 5   # 1,2 s de animação; grade de 5 × 6 quadros num print de 6000 × 4050
HOLD_CS = 800                   # o último quadro fica 8 s antes de recomeçar
MAX_CHARTS = 3
MAX_GIF = 4_500_000             # o plano gratuito do Notion aceita arquivos de até 5 MB
CONTEXT_CHARS = 20_000           # ponytail: aula muito longa e cheia de números perde os do fim; por partes se fizer falta
KINDS = ("barras", "linha", "rosca", "funcao", "linha_do_tempo")

_S = {"type": "string"}
# Os dados vêm em linhas (rótulo junto dos seus valores, como numa tabela): com rótulos e séries separados, o
# modelo de 8B trocava valores de lugar e fazia uma "série" por categoria.
SCHEMA = {"type": "object", "properties": {"graficos": {"type": "array", "items": {"type": "object", "properties": {
    "trecho": _S, "tipo": {"type": "string", "enum": list(KINDS)}, "titulo": _S, "mensagem": _S, "unidade": _S,
    "eixo_x": _S, "eixo_y": _S, "series": {"type": "array", "items": _S},
    "dados": {"type": "array", "items": {"type": "object", "properties": {
        "rotulo": _S, "valores": {"type": "array", "items": {"type": "number"}}}, "required": ["rotulo", "valores"]}},
    "funcoes": {"type": "array", "items": {"type": "object", "properties": {"nome": _S, "expressao": _S},
                                           "required": ["nome", "expressao"]}},
    "x_min": {"type": "number"}, "x_max": {"type": "number"},
    "eventos": {"type": "array", "items": {"type": "object", "properties": {"data": _S, "texto": _S},
                                           "required": ["data", "texto"]}}},
    "required": ["trecho", "tipo", "titulo", "mensagem", "unidade", "eixo_x", "eixo_y", "series", "dados",
                 "funcoes", "x_min", "x_max", "eventos"]}}}, "required": ["graficos"]}

SYSTEM = """Você cria gráficos para o material de estudo de uma aula. Use SOMENTE dados que a aula disse ou mostrou
na tela (linhas "(na tela)"). Responda só com JSON.
- De 0 a 3 gráficos, só os que ajudam a entender o assunto. Se a aula não tiver números, datas ou fórmulas que
  rendam um gráfico, devolva a lista vazia. Nunca invente, estime, arredonde, converta ou complete valores:
  copie os números exatamente como aparecem. Nada de notas, pontuações ou "1" para representar algo que não é
  número na aula.
- trecho: copie a frase ou a linha da tela de onde vêm os dados.
- tipo:
  - "barras": comparar um valor entre categorias (ex.: o tempo de cada algoritmo, a população de cada país).
  - "linha": um valor que muda ao longo de algo ordenado (anos, tamanho da entrada, tempo).
  - "rosca": partes de um todo (ex.: porcentagens que somam 100%).
  - "funcao": curvas de fórmulas escritas ou ditas na aula (ex.: y = x² - 4x + 3, s = 5 + 2t). Complexidades
    citadas, como O(n), O(n log n) e O(n²), viram um gráfico funcao com uma curva para cada uma. Escreva cada
    expressão como na aula (use x, n ou t; ^ para potência; log, sqrt). O app calcula as curvas.
  - "linha_do_tempo": pelo menos 3 acontecimentos com o ano citado na aula.
- titulo: o que o gráfico mostra, curto. mensagem: copie a frase da aula que comenta esses dados ("" se não houver).
- dados (barras, linha, rosca): uma linha por categoria ou ponto do eixo x, com o rótulo como na aula e os seus
  valores (um por série). Cada valor precisa ter sido dito ou mostrado junto do seu rótulo.
- series: o nome de cada coluna de valores (ex.: ["Tempo"]; ["2024", "2025"] para comparar dois anos). Rosca: uma.
- unidade: a unidade dos valores (ex.: "ms", "%", "milhões de habitantes") ou "".
- eixo_x, eixo_y: o nome de cada eixo (linha e funcao) ou "".
- funcoes, x_min, x_max: só em funcao; o intervalo de x que mostra bem as curvas (se a aula disser, use o dela).
- eventos: só em linha_do_tempo; data = o ano como na aula; texto = o acontecimento em até 8 palavras.
- Deixe vazios os campos que não são do tipo escolhido.
Exemplo de formato (de outra aula): {"graficos": [{"trecho": "(na tela) Sudeste | 84,8", "tipo": "barras",
"titulo": "População por região", "mensagem": "", "unidade": "milhões", "eixo_x": "Região", "eixo_y": "",
"series": ["População"], "dados": [{"rotulo": "Norte", "valores": [18.9]}, {"rotulo": "Sudeste", "valores": [84.8]}],
"funcoes": [], "x_min": 0, "x_max": 0, "eventos": []}, {"trecho": "a reta y = 2x + 1", "tipo": "funcao",
"titulo": "Reta y = 2x + 1", "mensagem": "", "unidade": "", "eixo_x": "x", "eixo_y": "y", "series": [], "dados": [],
"funcoes": [{"nome": "y = 2x + 1", "expressao": "2x + 1"}], "x_min": -5, "x_max": 5, "eventos": []}]}"""


# --- conferência dos dados -----------------------------------------------------------------------------------------

def _fold(s):
    """Sem acentos e sem caixa: para comparar palavras ("População" = "populacao")."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(s).casefold()) if not unicodedata.combining(c))


_MULT = {"mil": 1e3, "milhao": 1e6, "milhoes": 1e6, "bilhao": 1e9, "bilhoes": 1e9, "trilhao": 1e12, "trilhoes": 1e12,
         "thousand": 1e3, "million": 1e6, "millions": 1e6, "billion": 1e9, "billions": 1e9}
_WORDS = {"zero": 0, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
          "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15,
          "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30, "quarenta": 40,
          "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90, "cem": 100}
_TOKEN = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[a-z0-9]+")  # sobre o texto sem acentos: "5.200", "t1", "milhoes"


DOT_DECIMAL = {"en", "zh", "ja", "ko", "th", "he", "hi"}  # idiomas em que "5.200" é 5,2 (no resto é 5200)


def _readings(tok, comma=True):
    """O valor de um número escrito. comma (português e a maioria dos idiomas): "5.200" = 5200, "1,5" = 1,5,
    "1.234,5"; senão (inglês): "5,200" = 5200, "1.5". "3.14" (sem grupo de 3 dígitos) é decimal nos dois."""
    thou, dec = (".", ",") if comma else (",", ".")
    if re.fullmatch(r"\d+", tok):
        return {float(tok)}
    if re.fullmatch(rf"\d{{1,3}}(?:\{thou}\d{{3}})+(?:\{dec}\d+)?", tok):
        return {float(tok.replace(thou, "").replace(dec, "."))}
    if re.fullmatch(r"\d+[.,]\d+", tok):
        return {float(tok.replace(",", "."))}
    return set()


def _scan(text, comma=True):
    """[(palavra sem acento, valores se for número)] na ordem do texto ("1 milhão" = 1 e 1.000.000; "cinco" = 5;
    "-5")."""
    folded = _fold(text)
    toks = [(m.group(), m.start()) for m in _TOKEN.finditer(folded)]
    out = []
    for i, (tok, at) in enumerate(toks):
        nxt = toks[i + 1][0] if i + 1 < len(toks) else ""
        num = tok[0].isdigit()
        vals = _readings(tok, comma) if num else ({_WORDS[tok]} if tok in _WORDS else
                                                  {1.0} if tok in ("um", "uma") and nxt in _MULT else set())
        if tok in _MULT and not (i and toks[i - 1][0][0].isdigit()):
            vals = {_MULT[tok]}
        if nxt in _MULT:
            vals |= {v * _MULT[nxt] for v in vals}
        if num and at and folded[at - 1] in "-−" and (at < 2 or not folded[at - 2].isalnum()):
            vals |= {-v for v in vals}
        out.append((tok, vals))
    return out


def numbers(text, comma=True):
    """Todos os números de um texto."""
    return set().union(*(v for _, v in _scan(text, comma)))


def _has(nums, v):
    return any(abs(v - n) <= 1e-9 * max(1.0, abs(n)) for n in nums)


_STOP = set("de da do das dos e o a os as em no na nos nas um uma com sem por para pelo pela que se ao aos foi "
            "era sao ser como mais the of and in on to for".split())


def _words(s):
    return [w for w in re.findall(r"[a-z0-9]+", _fold(s)) if w not in _STOP and (len(w) >= 3 or w.isdigit())]


def _match(words, tok):
    """A palavra do texto é uma das palavras (plural e gênero valem: "algoritmo" acha "algoritmos")."""
    return any(tok == w if w.isdigit() else tok.startswith(w[:max(4, len(w) - 2)]) for w in words)


def _named(words, tokens):
    return any(_match(words, t) for t in tokens)


def units(segments, screens=()):
    """[(segundos, texto, é_fala)]: cada trecho da fala e cada linha das telas escolhidas, na ordem da aula."""
    out = [(s.get("start"), str(s["text"]), True) for s in segments if str(s.get("text") or "").strip()]
    for sc in screens:
        note = sc["note"]
        if note.get("tipo") == "codigo":
            continue  # os números de um código (índices, 0 e 1) não são dados da aula
        lines = [x for x in note["texto"].splitlines() if _fold(x.strip()) != _fold(note["titulo"].strip())]
        pairs = [f"{p['rotulo']}: {p['valor']}" for p in note.get("valores") or []]  # o par lido na imagem
        out += [(sc["t"], x.strip(), False) for x in [note["titulo"], *lines, *pairs] if x.strip()]
    return sorted(out, key=lambda u: u[0] if u[0] is not None else float("inf"))


def _windows(us, comma=True):
    """Onde um valor e o seu rótulo precisam aparecer juntos: o trecho da fala com o seguinte (a frase pode
    continuar) ou uma linha da tela (linha de tabela, "Bubble sort: 5.200 ms"). Linhas vizinhas da tela não
    valem: "5.200 ms / Bubble sort / 180 ms" não diz de quem é o 180. [(segundos, [(palavra, valores)])]"""
    out = []
    for i, (t, text, speech) in enumerate(us):
        if speech and i + 1 < len(us) and us[i + 1][2]:
            text += " " + us[i + 1][1]
        out.append((t, _scan(text, comma)))
    return out


_NONE = object()


def _where(v, k, labels, values, wins):
    """Tempo do primeiro trecho em que o valor v é do rótulo k, ou _NONE. labels: palavras de cada rótulo do
    gráfico (_distinct); values: todos os valores do gráfico.

    De quem é cada valor segue o jeito da frase: se ela começa por um valor ("78% de nitrogênio, 21% de
    oxigênio"), cada valor é do rótulo seguinte; se começa por um rótulo ("o bubble sort levou 5.200 ms e o merge
    sort, 180"; "Quicksort | 150"), do rótulo anterior. Estar no mesmo trecho não basta."""
    for t, toks in wins:
        spots = _spots(toks, labels)
        if k in spots.values() and any(_has(toks[p][1], v) and _owner(toks, spots, values, p) == k
                                       for p in range(len(toks)) if p not in spots):
            return t
    return _NONE


def _spots(toks, labels):
    """{posição: índice do rótulo} das palavras dos rótulos no trecho."""
    return {i: j for j, words in enumerate(labels) for i, (w, _) in enumerate(toks) if _match(words, w)}


def _owner(toks, spots, values, pv):
    """De qual rótulo é o número na posição pv (ver _where), ou None."""
    nums = [i for i, (_, vals) in enumerate(toks) if i not in spots and any(_has(vals, x) for x in values)]
    if not nums or not spots:
        return None
    if nums[0] < min(spots):  # a frase começa por valor: é do rótulo seguinte
        near = [i for i in spots if i > pv]
        return spots[min(near)] if near else None
    near = [i for i in spots if i < pv]
    return spots[max(near)] if near else None


def _columns(values, labels, names, us, wins):
    """Várias séries: cada valor precisa ser da sua linha e também da sua coluna ("Alpha: 2024 10, 2025 20" não vale
    para 2024 = 20). Ou os nomes das séries estão no trecho, cada valor com o seu, ou é uma linha de tabela na tela
    com os valores na ordem de um cabeçalho que lista as séries nessa ordem. Na fala sem os nomes, não dá para
    saber: recusa."""
    cols = _distinct(names)
    flat = [v for row in values for v in row]

    def row_ok(k, row, i):
        t, toks = wins[i]
        rows = _spots(toks, labels)
        if k not in rows.values():
            return False
        spots = _spots(toks, cols)
        # o mesmo número é da linha k (não o da outra categoria no mesmo trecho) e da coluna j
        mine = [p for p in range(len(toks)) if p not in spots and p not in rows and _owner(toks, rows, flat, p) == k]
        if len(set(spots.values())) == len(cols):
            return all(any(_has(toks[p][1], v) and _owner(toks, spots, row, p) == j for p in mine)
                       for j, v in enumerate(row))
        if us[i][2]:
            return False
        at, pos = 0, []
        for v in row:  # na linha da tabela, os valores na ordem das colunas
            p = next((p for p in mine if p >= at and _has(toks[p][1], v)), None)
            if p is None:
                return False
            pos.append(p)
            at = p + 1
        for u in us:  # e um cabeçalho da mesma tela com as séries nessa ordem
            if not u[2] and u[0] == t:
                words = re.findall(r"[a-z0-9]+", _fold(u[1]))
                first = [next((p for p, w in enumerate(words) if _match(c, w)), None) for c in cols]
                if None not in first and first == sorted(first) and len(set(first)) == len(first):
                    return True
        return False
    return all(any(row_ok(k, row, i) for i in range(len(wins))) for k, row in enumerate(values))


def _distinct(labels):
    """Palavras de cada rótulo que nenhum outro tem ("merge" em "Merge sort", não "sort": com "sort", a linha
    "Merge sort: 180 ms" também serviria para o Bubble sort)."""
    sets = [_words(lab) or re.findall(r"[a-z0-9]+", _fold(lab)) for lab in labels]
    same = lambda a, b: _match([a], b) or _match([b], a)  # noqa: E731
    out = []
    for i, ws in enumerate(sets):
        others = [u for j, s in enumerate(sets) if j != i for u in s]
        out.append([w for w in ws if not any(same(w, u) for u in others)] or ws)
    return out


def _clip(v, n):
    v = " ".join(str(v or "").split())
    return v if len(v) <= n else v[:n - 1].rstrip(" ,.;:") + "…"


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _table(c, us, wins, all_tokens):
    """barras, linha, rosca: linhas (rótulo, valores) → rótulos e séries, com cada valor achado junto do rótulo."""
    rows = [r for r in c.get("dados") or [] if isinstance(r, dict) and _clip(r.get("rotulo"), 40)]
    kind = c["tipo"]
    lo, hi = {"barras": (2, 12), "linha": (3, 40), "rosca": (2, 8)}[kind]
    labels = [_clip(r["rotulo"], 40) for r in rows]
    values = [[_num(v) for v in (r.get("valores") if isinstance(r.get("valores"), list) else [])] for r in rows]
    width = len(values[0]) if values else 0
    if not (lo <= len(rows) <= hi) or len(set(map(_fold, labels))) < len(labels) \
            or not 1 <= width <= (1 if kind == "rosca" else 4 if kind == "linha" else 3) \
            or any(len(v) != width or None in v for v in values):
        return None
    names = ([_clip(n, 40) for n in c.get("series") or [] if isinstance(n, str)] + [""] * width)[:width]
    if width > 1 and not all(n and _named(_words(n), all_tokens) for n in names):
        return None  # série com nome inventado
    flat = [v for row in values for v in row]
    if kind in ("barras", "rosca") and min(flat) < 0 or kind == "rosca" and min(flat) <= 0:
        return None
    times, words = [], _distinct(labels)
    for k, row in enumerate(values):
        for v in row:
            t = _where(v, k, words, flat, wins)
            if t is _NONE:
                return None
            times.append(t)
    if width > 1 and not _columns(values, words, names, us, wins):
        return None
    series = [{"nome": names[j], "valores": [row[j] for row in values]} for j in range(width)]
    if kind == "rosca" and "%" in str(c.get("unidade")) and abs(sum(series[0]["valores"]) - 100) > 2:
        return None  # porcentagens que não fecham o todo
    return {"rotulos": labels, "series": series, "t": min((t for t in times if t is not None), default=None)}


def fmt(v, unit=""):
    """5200 → "5.200"; 84.4 → "84,4"; com a unidade: "5.200 ms", "78%"."""
    s = f"{v:,.4f}".rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".")
    return s + ("%" if unit == "%" else f" {unit}" if unit else "")


def _said(msg, wins):
    """A frase está na aula (quase todas as palavras num mesmo trecho), não é uma conclusão da IA."""
    ws = [w for w in _words(msg) if not w.isdigit()]
    return len(ws) >= 3 and any(sum(_named([w], [x for x, _ in toks]) for w in ws) >= 0.75 * len(ws)
                                for _, toks in wins)


def _subtitle(c):
    """Subtítulo tirado dos próprios dados (sempre certo) quando a aula não comenta o gráfico."""
    u = c["unidade"]
    if c["tipo"] in ("barras", "linha", "rosca") and len(c["series"]) == 1:
        v, labs = c["series"][0]["valores"], c["rotulos"]
        if c["tipo"] == "linha":
            return f"De {fmt(v[0], u)} em {labs[0]} a {fmt(v[-1], u)} em {labs[-1]}"
        hi, lo = v.index(max(v)), v.index(min(v))
        if c["tipo"] == "rosca":
            return f"Maior parte: {labs[hi]} ({fmt(round(v[hi] / sum(v) * 100, 1), '%')})"
        return f"Maior: {labs[hi]} ({fmt(v[hi], u)}) · menor: {labs[lo]} ({fmt(v[lo], u)})"
    if c["tipo"] == "linha_do_tempo":
        return f"De {c['eventos'][0]['data']} a {c['eventos'][-1]['data']}"
    return ""


# --- fórmulas ------------------------------------------------------------------------------------------------------

_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉", "01234567890123456789")


def _sup(s, paren=True):
    s = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+", lambda m: ("^(%s)" if paren else "^%s") % m.group().translate(_SUP), str(s))
    return s.translate(_SUP)


def _fact(a):
    a = np.asarray(a, float)
    ok = (a > -1) & (a < 171)
    return np.where(ok, np.vectorize(lambda v: math.gamma(v + 1) if -1 < v < 171 else math.nan)(a), np.inf)


_FN = {"ln": np.log, "log2": np.log2, "lg": np.log2, "log10": np.log10, "sqrt": np.sqrt, "raiz": np.sqrt,
       "exp": np.exp, "sin": np.sin, "sen": np.sin, "cos": np.cos, "tan": np.tan, "tg": np.tan, "abs": np.abs,
       "fat": _fact, "log": None}  # log: base 2 em complexidade (n), base 10 no resto
_CONST = {"pi": math.pi, "e": math.e}
_VARS = ("x", "n", "t")
_NAMES = sorted([*_FN, *_CONST, *_VARS], key=len, reverse=True)
_OPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide, ast.Pow: np.power}


def _split(name):
    """"nlogn" → [n, log, n]; None se não for só de nomes conhecidos."""
    if not name:
        return []
    for k in _NAMES:
        if name.startswith(k):
            rest = _split(name[len(k):])
            if rest is not None:
                return [k] + rest
    return None


def parse(expr):
    """Fórmula → (f(xs) em numpy, variável, é complexidade) ou None. Só números, x/n/t, + − × ÷ ^, parênteses,
    fatorial e as funções de _FN; qualquer outro nome, atributo ou chamada é recusado."""
    s = _sup(expr).strip()
    for a, b in (("−", "-"), ("–", "-"), ("·", "*"), ("×", "*"), ("⋅", "*"), ("÷", "/"), ("√", "sqrt"), ("π", "pi")):
        s = s.replace(a, b)
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    big_o = re.fullmatch(r"\s*[OoΘθΩω]\s*\((.*)\)\s*", s)
    if big_o:
        s = big_o.group(1)
    s = s.split("=")[-1]
    raw = re.findall(r"\d+(?:\.\d+)?|[A-Za-z]+\d*|\*\*|[-+*/^()!]|\S", s)
    toks = []
    for tok in raw:
        if tok[0].isalpha():
            parts = [tok.lower()] if tok.lower() in _FN or tok.lower() in _CONST else _split(tok.lower())
            if parts is None:
                return None
            toks += parts
        elif tok[0].isdigit() or tok in ("**", "+", "-", "*", "/", "^", "(", ")", "!"):
            toks.append("**" if tok == "^" else tok)
        else:
            return None
    value = lambda k: k[0].isdigit() or k in _VARS or k in _CONST  # noqa: E731
    out, i = [], 0
    while i < len(toks):
        k = toks[i]
        if out and (value(out[-1]) or out[-1] == ")") and (value(k) or k in _FN or k == "("):
            out.append("*")  # multiplicação implícita: 2x, n log n, x(x+1)
        if k in _FN and (i + 1 >= len(toks) or toks[i + 1] != "("):
            if i + 1 >= len(toks) or not value(toks[i + 1]):
                return None
            out += [k, "(", toks[i + 1], ")"]  # log n = log(n)
            i += 2
            continue
        if k == "!":
            if not out or not value(out[-1]):
                return None
            out[-1:] = ["fat", "(", out[-1], ")"]
        else:
            out.append(k)
        i += 1
    try:
        tree = ast.parse(" ".join(out), mode="eval")
    except (SyntaxError, ValueError):
        return None
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in _FN and len(node.args) == 1 and not node.keywords):
                return None
        elif isinstance(node, ast.Name):
            if node.id in _VARS:
                used.add(node.id)
            elif node.id not in _CONST and node.id not in _FN:
                return None
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                return None
        elif not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Load, ast.USub, ast.UAdd,
                                   *_OPS)):
            return None
    if len(used) > 1:
        return None
    var = next(iter(used), "x")
    cx = bool(big_o) or var == "n"

    def ev(node, xs):
        if isinstance(node, ast.Expression):
            return ev(node.body, xs)
        if isinstance(node, ast.Constant):
            return np.full_like(xs, float(node.value))
        if isinstance(node, ast.Name):
            return xs if node.id in _VARS else np.full_like(xs, _CONST[node.id])
        if isinstance(node, ast.UnaryOp):
            return -ev(node.operand, xs) if isinstance(node.op, ast.USub) else ev(node.operand, xs)
        if isinstance(node, ast.BinOp):
            return _OPS[type(node.op)](ev(node.left, xs), ev(node.right, xs))
        fn = _FN[node.func.id] or (np.log2 if cx else np.log10)
        return fn(ev(node.args[0], xs))

    def f(xs):
        with np.errstate(all="ignore"):
            ys = np.asarray(ev(tree, np.asarray(xs, float)), float)
        return np.where(np.isfinite(ys), ys, np.nan)
    return f, var, cx


def _ekey(s):
    """Forma comparável de uma complexidade, para não repetir: "n log n" e "n·log₂ n" → "nlogn"."""
    s = _sup(s, paren=False).casefold()
    for a, b in (("log10", "log"), ("log2", "log"), ("lg", "log"), ("ln", "log"), ("**", "^"), ("·", ""),
                 ("×", ""), ("⋅", ""), ("*", "")):
        s = s.replace(a, b)
    return re.sub(r"[\s()\[\]{}]", "", s)


_SPOKEN = ((" igual a ", " = "), ("ao quadrado", "^2"), ("ao cubo", "^3"), ("elevado a", "^"), ("raiz quadrada de", "sqrt"),
           ("raiz de", "sqrt"), ("log de", "log"), ("dividido por", "/"), (" mais ", " + "), (" menos ", " - "),
           (" vezes ", " * "))


def written(us):
    """[(segundos, parse(), texto)] das fórmulas escritas ou ditas na aula: O(...), o lado direito de cada "=" e a
    linha da tela inteira, cada uma lida pelo parser (o trecho mais longo que for fórmula)."""
    out = []
    for t, text, _ in us:
        s = str(text)
        for a, b in _SPOKEN:
            s = re.sub(a, b, s, flags=re.I)
        cands = ["O(" + m.group(1) + ")" for m in _BIG_O.finditer(s)]
        cands += [re.split(r"[;=]|,\s", s[m.end():])[0] for m in re.finditer("=", s)] + [s]
        for cand in cands:
            words = re.sub(r"[.!?:;]+$", "", cand.strip()).split()[:16]  # sem o ponto final da frase
            for n in range(len(words), 0, -1):
                p = parse(" ".join(words[:n]))
                if p:
                    out.append((t, p, " ".join(words[:n])))
                    break
    return out


_PROBE = np.array([-2.9, -1.7, -.6, .37, .83, 1.3, 1.9, 2.6, 3.4, 4.7, 6.1, 7.9])


def _same(f, g, x0, x1):
    """Mesma função (não o mesmo texto): os mesmos valores nos pontos de prova e em todo o trecho desenhado.
    "(x+1)^2" ≠ "x+1^2"; "abs(x-8)" ≠ "8-x" em [-10, 10]; "sqrt(x-10)" vale em [10, 20]."""
    xs = np.concatenate([_PROBE, np.linspace(x0, x1, 97)])
    a, b = f(xs), g(xs)
    ok = np.isfinite(a) & np.isfinite(b)
    return ok.sum() >= 5 and np.allclose(a[ok], b[ok], rtol=1e-7, atol=1e-9) and \
        (np.isfinite(a) == np.isfinite(b)).all()


def _formula(c, us):
    """Curvas das fórmulas da aula, calculadas aqui. A IA só aponta qual: a fórmula precisa ser a mesma função
    de uma escrita (ou dita) na aula, e o que se desenha e se mostra é a da aula, não a da IA."""
    source = written(us)
    found, times, cx = [], [], False
    x0, x1 = _num(c.get("x_min")), _num(c.get("x_max"))
    if x0 is None or x1 is None or not x1 > x0 or x1 - x0 > 1e6:
        x0, x1 = -10.0, 10.0
    for fn in (c.get("funcoes") or [])[:5]:
        if not isinstance(fn, dict):
            continue
        parsed = parse(_clip(fn.get("expressao"), 80))
        if not parsed:
            continue
        span = (1.0, 32.0) if parsed[2] else (x0, x1)
        hit = next(((t, text) for t, p, text in source if p[2] == parsed[2] and _same(p[0], parsed[0], *span)), None)
        if not hit:
            continue
        name = str(fn.get("nome") or "")
        if not name.strip() or re.search(r"[\d=]", name):  # um nome com fórmula poderia ser outra fórmula
            name = hit[1]
        found.append({"nome": _clip(name, 40), "expressao": _clip(hit[1], 80)})
        times.append(hit[0])
        cx = cx or parsed[2]
    if not found:
        return None
    if cx:
        x0, x1 = 1.0, 32.0  # complexidade: o que importa é a forma do crescimento
    out = {"funcoes": found, "x_min": x0, "x_max": x1, "complexidade": cx,
           "t": min((t for t in times if t is not None), default=None)}
    return out if curves(out)[0] else None


def curves(chart, points=241):
    """[(nome, xs, ys)] e os limites (x0, x1, y0, y1) do gráfico de funções. Uma curva que dispara (2^n perto
    de n²) sai pelo alto em vez de achatar as outras."""
    xs = np.linspace(chart["x_min"], chart["x_max"], points)
    out = []
    for fn in chart["funcoes"]:
        parsed = parse(fn["expressao"])
        if parsed:
            ys = parsed[0](xs)
            if np.isfinite(ys).sum() >= 20:
                out.append((fn["nome"], xs, ys))
    if not out:
        return [], None
    tops = sorted(float(np.nanmax(ys)) for _, _, ys in out)
    lo = min(0.0, min(float(np.nanmin(ys)) for _, _, ys in out))
    hi = tops[-1] if len(tops) < 2 or tops[-1] <= 8 * max(tops[-2], 1e-9) else tops[-2] * 1.6
    if hi <= lo:
        hi = lo + 1
    return out, (float(xs[0]), float(xs[-1]), lo, hi)


# --- linha do tempo ------------------------------------------------------------------------------------------------

def _year(s):
    m = re.search(r"\d{1,4}", str(s))
    if not m:
        return None
    y = int(m.group())
    return -y if re.search(r"a\.?\s*c\b|bc\b|antes de cristo", _fold(s)) else y


def _timeline(c, wins):
    raw = [e for e in (c.get("eventos") or [])[:12] if isinstance(e, dict)]
    words = _distinct([_clip(e.get("texto"), 70) for e in raw])
    years = [float(abs(y)) for y in map(_year, (e.get("data") for e in raw)) if y is not None]
    events, times = [], []
    for k, e in enumerate(raw):
        y, text = _year(e.get("data")), _clip(e.get("texto"), 70)
        if y is None or not text:
            return None
        t = _where(float(abs(y)), k, words, years, wins)
        if t is _NONE:
            return None
        events.append({"data": _clip(e.get("data"), 20), "ano": y, "texto": text})
        times.append(t)
    events.sort(key=lambda e: e["ano"])
    if len({e["ano"] for e in events}) < 3:
        return None
    return {"eventos": events, "t": min((t for t in times if t is not None), default=None)}


# --- da resposta da IA aos gráficos conferidos ---------------------------------------------------------------------

def validate(data, us, comma=True):
    """Gráficos conferidos na aula. O que não se confirma fica de fora, inteiro."""
    wins = _windows(us, comma)
    all_nums = set().union(*(v for _, toks in wins for _, v in toks))
    all_tokens = {w for _, toks in wins for w, _ in toks}
    out, seen = [], set()
    items = data.get("graficos") if isinstance(data, dict) else None
    for c in items if isinstance(items, list) else []:
        if not isinstance(c, dict) or c.get("tipo") not in KINDS or not _clip(c.get("titulo"), 90):
            continue
        kind = c["tipo"]
        body = (_formula(c, us) if kind == "funcao" else _timeline(c, wins) if kind == "linha_do_tempo"
                else _table(c, us, wins, all_tokens))
        if not body:
            continue
        chart = {"tipo": kind, "titulo": _clip(c.get("titulo"), 90), "unidade": _clip(c.get("unidade"), 30),
                 "eixo_x": _clip(c.get("eixo_x"), 40), "eixo_y": _clip(c.get("eixo_y"), 40), **body}
        # a frase só entra se for da aula (a IA tira conclusões erradas: "o merge sort é o mais rápido"); senão,
        # o subtítulo sai dos próprios dados
        msg = _clip(c.get("mensagem"), 160)
        ok = _said(msg, wins) and all(_has(all_nums, v) for v in numbers(msg, comma))
        chart["mensagem"] = msg if ok else _subtitle(chart)
        sig = json.dumps([kind, body.get("series"), body.get("funcoes"), body.get("eventos")], sort_keys=True)
        if sig not in seen:
            seen.add(sig)
            out.append(chart)
    return out


_TRIGGER = re.compile(r"\d|%|[²³√=]|\b(?:dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|vinte|trinta|"
                      r"quarenta|cinquenta|cem|mil)\b|\b(?:milh|bilh)", re.I)


def context(us):
    """Só os trechos com números, datas ou fórmulas (e o seguinte, que pode completar a frase); uma tela com algum
    número vai inteira (o cabeçalho da tabela diz o que é cada coluna)."""
    from .llm import fmt_time
    pick = set()
    by_screen = {}
    for i, (t, text, speech) in enumerate(us):
        if not speech:
            by_screen.setdefault(t, []).append(i)
    for i, (t, text, speech) in enumerate(us):
        if _TRIGGER.search(text):
            pick |= {i, i + 1} if speech else set(by_screen[t])
    lines = []
    for i in sorted(j for j in pick if j < len(us)):
        t, text, speech = us[i]
        lines.append((f"[{fmt_time(t)}] " if t is not None else "") + ("" if speech else "(na tela) ") + text)
    out = "\n".join(lines)
    return out[:CONTEXT_CHARS]


_BIG_O = re.compile(r"[OΘΩ]\s*\(((?:[^()]|\([^()]*\))+)\)")


def complexities(us):
    """As complexidades citadas na aula (O(n), O(n log n), O(n²)…) num gráfico de curvas, sem IA: só as que a aula
    escreveu ou disse, calculadas aqui, da que cresce menos à que cresce mais. None se forem menos de duas."""
    found, times, seen = [], [], set()
    for t, text, _ in us:
        for m in _BIG_O.finditer(text):
            expr = f"O({' '.join(m.group(1).split())})"
            key = _ekey(m.group(1))
            if key not in seen and parse(expr):
                seen.add(key)
                found.append({"nome": _clip(expr, 40), "expressao": expr})
                times.append(t)
    if len(found) < 2:
        return None
    at = {f["nome"]: float(parse(f["expressao"])[0](np.array([32.0]))[0]) for f in found}
    found.sort(key=lambda f: at[f["nome"]] if math.isfinite(at[f["nome"]]) else math.inf)
    chart = {"tipo": "funcao", "titulo": "Como cresce cada complexidade citada na aula", "unidade": "", "eixo_x": "",
             "eixo_y": "", "funcoes": found[:5], "x_min": 1.0, "x_max": 32.0, "complexidade": True,
             "t": min((t for t in times if t is not None), default=None)}
    chart["mensagem"] = "Da que cresce menos à que cresce mais: " + ", ".join(f["nome"] for f in chart["funcoes"])
    return chart if curves(chart)[0] else None


def extract(segments, screens, lesson, model, check, status=lambda d: None, language=None):
    """Gráficos da aula conferidos, ou [] (aula sem números, datas ou fórmulas). Erro da IA → AppError/ValueError."""
    from .llm import _chat
    us = units(segments, screens)
    cx = complexities(us)
    text = context(us)
    if not text:
        return [cx] if cx else []
    topics = "; ".join(t["title"] for t in lesson.get("topics", []))[:600]
    user = f"Aula: {lesson.get('title', '')}\nTópicos: {topics}\n\nTrechos com números, datas ou fórmulas:\n{text}"
    raw = json.loads(_chat(model, SYSTEM, user, check,
                           lambda n: status(f"Procurando dados para gráficos… ({n} trechos)"),
                           schema=SCHEMA, num_ctx=16384, temperature=0))
    found = validate(raw, us, comma=language not in DOT_DECIMAL)
    log.info("gráficos: %d proposto(s), %d conferido(s)%s",
             len(raw.get("graficos") or []) if isinstance(raw, dict) else 0, len(found), " + complexidades" if cx else "")
    if cx:  # o das complexidades, calculado aqui, no lugar dos parecidos da IA
        found = [c for c in found if not (c["tipo"] == "funcao" and c.get("complexidade"))] + [cx]
    when = lambda c: c["t"] if c["t"] is not None else math.inf  # noqa: E731
    # até MAX_CHARTS: primeiro os que comparam algo (uma curva sozinha diz pouco), na ordem da aula
    found.sort(key=lambda c: (c["tipo"] == "funcao" and len(c["funcoes"]) < 2, when(c)))
    return sorted(found[:MAX_CHARTS], key=when)


# --- desenho -------------------------------------------------------------------------------------------------------

def _view(c):
    """O que o desenho precisa (tudo já conferido; os textos entram no SVG como texto, nunca como HTML)."""
    from .llm import fmt_time
    when = f" · {fmt_time(c['t'])}" if c.get("t") is not None else ""
    v = {k: c[k] for k in ("tipo", "titulo", "mensagem", "unidade", "eixo_x", "eixo_y")}
    if c["tipo"] == "funcao":
        found, box = curves(c)
        v["curvas"] = [{"nome": n, "pts": [[round(float(x), 6), None if not np.isfinite(y) else round(float(y), 6)]
                                           for x, y in zip(xs, ys)]} for n, xs, ys in found]
        v["dom"] = box
        v["fonte"] = "Curvas calculadas pelo Lumen a partir das fórmulas da aula" + when
        if c.get("complexidade"):
            v["eixo_y"] = v["eixo_y"] or "operações (proporcional)"
            v["eixo_x"] = v["eixo_x"] or "n (tamanho da entrada)"
    elif c["tipo"] == "linha_do_tempo":
        v["eventos"] = c["eventos"]
        v["fonte"] = "Datas citadas na aula" + when
    else:
        v["rotulos"], v["series"] = c["rotulos"], c["series"]
        xs = [sorted(_readings(x.strip())) for x in c["rotulos"]]
        v["xnum"] = [r[0] for r in xs] if all(len(r) == 1 for r in xs) and \
            all(a[0] < b[0] for a, b in zip(xs, xs[1:])) else None
        v["fonte"] = "Dados citados na aula" + when
    return v


def html(c):
    spec = json.dumps(_view(c), ensure_ascii=False).replace("</", "<\\/")
    return (_PAGE.replace("__SPEC__", spec).replace("__FRAMES__", str(FRAMES)).replace("__COLS__", str(COLS))
            .replace("__W__", str(W)).replace("__H__", str(H)))


def _gif(frames):
    """Quadros RGB → GIF com uma paleta de 256 cores feita para este gráfico (palettegen) e só a parte que muda
    em cada quadro (diff_mode=rectangle)."""
    import av
    import av.filter
    buf = io.BytesIO()
    with av.open(buf, "w", format="gif", options={"loop": "0", "final_delay": str(HOLD_CS)}) as out:
        st = out.add_stream("gif", rate=FPS)
        st.width, st.height, st.pix_fmt = W, H, "pal8"
        g = av.filter.Graph()
        src = g.add_buffer(width=W, height=H, format="rgb24", time_base=Fraction(1, FPS))
        split, sink = g.add("split"), g.add("buffersink")
        gen = g.add("palettegen", "stats_mode=full:max_colors=256")
        use = g.add("paletteuse", "dither=none:diff_mode=rectangle")
        src.link_to(split)
        split.link_to(gen, 0, 0)
        split.link_to(use, 1, 0)
        gen.link_to(use, 0, 1)
        use.link_to(sink)
        g.configure()
        for k, f in enumerate(frames):
            vf = av.VideoFrame.from_ndarray(np.ascontiguousarray(f), format="rgb24")
            vf.pts, vf.time_base = k, Fraction(1, FPS)
            g.push(vf)
        g.push(None)
        n = 0
        while True:
            try:
                q = g.pull()
            except (av.error.BlockingIOError, av.error.EOFError):
                break
            q.pts, n = n, n + 1
            for p in st.encode(q):
                out.mux(p)
        for p in st.encode():
            out.mux(p)
    return buf.getvalue() if n == len(frames) else None


def render(c):
    """GIF animado do gráfico, ou None (sem Edge, falha ou arquivo grande demais)."""
    import av
    exe = edge()
    if not exe:
        return None
    rows = -(-FRAMES // COLS)
    with tempfile.TemporaryDirectory(prefix="lumen-grafico-") as tmp:
        page, shot = Path(tmp) / "grafico.html", Path(tmp) / "quadros.png"
        page.write_text(html(c), "utf-8")
        try:
            subprocess.run([str(exe), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            f"--user-data-dir={Path(tmp) / 'perfil'}", f"--window-size={W * COLS},{H * rows}",
                            f"--screenshot={shot}", page.as_uri()],
                           capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with av.open(str(shot)) as f:
                sheet = next(f.decode(video=0)).to_ndarray(format="rgb24")
        except (OSError, subprocess.SubprocessError, av.error.FFmpegError, StopIteration):
            return None
    if sheet.shape[:2] != (H * rows, W * COLS):
        return None
    frames = [sheet[(k // COLS) * H:(k // COLS + 1) * H, (k % COLS) * W:(k % COLS + 1) * W] for k in range(FRAMES)]
    if frames[-1][::8, ::8].std() < 8:  # o desenho não aconteceu (página em branco)
        return None
    try:
        gif = _gif(frames)
    except (av.error.FFmpegError, ValueError) as e:
        log.warning("gráfico: GIF falhou (%s)", e)
        return None
    return gif if gif and len(gif) <= MAX_GIF else None


_PAGE = r"""<!doctype html><meta charset="utf-8"><style>
html,body{margin:0;background:#0d1024}svg{position:absolute;display:block}
text{font-family:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif}
</style><body><script>
const S=__SPEC__,N=__FRAMES__,COLS=__COLS__,W=__W__,H=__H__,NS="http://www.w3.org/2000/svg";
const C=["#60a5fa","#f472b6","#34d399","#fbbf24","#a78bfa","#22d3ee","#fb923c","#f87171"];
const BG="#0d1024",INK="#eef1fb",MUTED="#9aa3c7",DIM="#5d6590",AXIS="#39406b",GRID="#1d2346";
const nf=new Intl.NumberFormat("pt-BR",{maximumFractionDigits:2});
const ctx=document.createElement("canvas").getContext("2d");
const FONT='"Segoe UI Variable Text","Segoe UI",sans-serif';
function measure(s,size,weight){ctx.font=`${weight||400} ${size}px ${FONT}`;return ctx.measureText(String(s)).width}
function wrap(s,width,size,weight,max){const out=[];let cur="";
  for(const w of String(s).split(/\s+/).filter(Boolean)){const t=cur?cur+" "+w:w;
    if(!cur||measure(t,size,weight)<=width)cur=t;else{out.push(cur);cur=w}}
  if(cur)out.push(cur);
  for(let i=0;i<out.length;i++)while(out[i].length>1&&measure(out[i],size,weight)>width)out[i]=out[i].slice(0,-2)+"…";
  if(out.length>max){out.length=max;let l=out[max-1];while(l.length>1&&measure(l+"…",size,weight)>width)l=l.slice(0,-1);
    out[max-1]=l.trimEnd()+"…"}
  return out}
const fit=(s,width,size,weight)=>wrap(s,width,size,weight,1)[0]||"";
function E(p,tag,a,txt){const e=document.createElementNS(NS,tag);for(const k in a)e.setAttribute(k,a[k]);
  if(txt!==undefined)e.textContent=txt;p.appendChild(e);return e}
const clamp=t=>Math.min(Math.max(t,0),1),ease=t=>1-Math.pow(1-clamp(t),3);
function stag(p,i,n,span){span=span||.62;const d=n>1?(1-span)/(n-1):0;return ease((p-i*d)/span)}
function ticks(lo,hi,n){if(!(hi>lo))hi=lo+1;const raw=(hi-lo)/(n||5),mag=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/mag,
  step=(f<=1?1:f<=2?2:f<=2.5?2.5:f<=5?5:10)*mag,a=Math.floor(lo/step+1e-9)*step,b=Math.ceil(hi/step-1e-9)*step,out=[];
  for(let v=a;v<=b+step*1e-6;v+=step)out.push(+v.toFixed(10));return out}
const U=S.unidade||"",SHORT=U.length>0&&U.length<=6;
const isInt=v=>Math.abs(v-Math.round(v))<1e-9;
function val(v,ref){const r=ref===undefined?v:ref;const s=nf.format(isInt(r)?Math.round(v):v);
  return !U?s:U==="%"?s+"%":SHORT?s+" "+U:s}
let uid=0;
function clipRect(svg,x,y,w,h){const id="c"+(uid++),d=E(svg,"defs",{}),cp=E(d,"clipPath",{id});
  E(cp,"rect",{x,y,width:Math.max(w,0.01),height:h});return `url(#${id})`}
function legend(g,items,y,line){let x=60;for(const[name,col]of items){
  if(line)E(g,"line",{x1:x,y1:y,x2:x+22,y2:y,stroke:col,"stroke-width":5,"stroke-linecap":"round"});
  else E(g,"rect",{x,y:y-8,width:16,height:16,rx:4,fill:col});
  const t=fit(name,260,17,500);E(g,"text",{x:x+(line?32:26),y:y+6,fill:MUTED,"font-size":17,"font-weight":500},t);
  x+=(line?32:26)+measure(t,17,500)+34}}
function header(g){
  E(g,"rect",{x:0,y:0,width:W,height:H,fill:BG});
  E(g,"rect",{x:40,y:40,width:6,height:38,rx:3,fill:C[0]});
  let y=72;
  for(const l of wrap(S.titulo,W-130,34,650,2)){E(g,"text",{x:62,y,fill:INK,"font-size":34,"font-weight":650},l);y+=42}
  if(S.mensagem){y-=4;for(const l of wrap(S.mensagem,W-130,20,400,2)){E(g,"text",{x:62,y,fill:MUTED,"font-size":20},l);y+=27}}
  E(g,"text",{x:60,y:H-26,fill:DIM,"font-size":15},S.fonte);
  E(g,"text",{x:W-60,y:H-26,fill:DIM,"font-size":15,"font-weight":650,"text-anchor":"end"},"Lumen");
  return y+20}
function barras(g,top,p){
  const L=S.rotulos,SR=S.series,n=L.length,m=SR.length;let y0=top;
  if(m>1){legend(g,SR.map((s,j)=>[s.nome,C[j]]),top+6);y0+=36}
  const y1=H-74-(U&&!SHORT?22:0),lw=Math.min(330,Math.max(...L.map(l=>measure(l,19,500)))+30);
  const xl=60+lw,vmax=Math.max(...SR.flatMap(s=>s.valores))||1;
  const labw=Math.max(...SR.flatMap(s=>s.valores.map(v=>measure(val(v),19,650))))+24,xr=W-60-labw;
  const row=(y1-y0)/n,bh=Math.min(58,row*.74/m);
  E(g,"line",{x1:xl,y1:y0-4,x2:xl,y2:y1+4,stroke:AXIS,"stroke-width":2});
  let k=0;
  L.forEach((lab,i)=>{const cy=y0+row*i+row/2;
    E(g,"text",{x:60,y:cy+7,fill:INK,"font-size":19,"font-weight":500},fit(lab,lw-26,19,500));
    SR.forEach((s,j)=>{const v=s.valores[i],e=stag(p,k++,n*m),w=Math.max(3,(xr-xl)*v/vmax*e),
      y=cy-m*bh/2+j*bh+bh*.1,h=bh*.8,col=m>1?C[j%C.length]:C[i%C.length];
      E(g,"rect",{x:xl,y,width:w,height:h,rx:Math.min(9,h/2),fill:col});
      if(e>0)E(g,"text",{x:xl+w+12,y:y+h/2+7,fill:INK,"font-size":19,"font-weight":650,opacity:clamp(e*2.5)},val(v*e,v))})});
  if(U&&!SHORT)E(g,"text",{x:xl,y:H-70,fill:MUTED,"font-size":15},"Valores em "+U)}
function axes(g,x0,x1,y0,y1,TY,Y,X,TX){
  for(const t of TY){E(g,"line",{x1:x0,y1:Y(t),x2:x1,y2:Y(t),stroke:Math.abs(t)<1e-12?AXIS:GRID,"stroke-width":Math.abs(t)<1e-12?2:1.5});
    E(g,"text",{x:x0-14,y:Y(t)+6,fill:MUTED,"font-size":16,"text-anchor":"end"},val(t))}
  if(TX)for(const t of TX){E(g,"line",{x1:X(t),y1:y0,x2:X(t),y2:y1,stroke:Math.abs(t)<1e-12?AXIS:GRID,"stroke-width":Math.abs(t)<1e-12?2:1.5});
    E(g,"text",{x:X(t),y:y1+28,fill:MUTED,"font-size":16,"text-anchor":"middle"},nf.format(t))}
  if(S.eixo_y)E(g,"text",{x:x0,y:y0-16,fill:MUTED,"font-size":15,"font-weight":600},fit(S.eixo_y,500,15,600));
  if(S.eixo_x)E(g,"text",{x:x1,y:y1+56,fill:MUTED,"font-size":15,"font-weight":600,"text-anchor":"end"},fit(S.eixo_x,600,15,600))}
function linha(svg,g,top,p){
  const L=S.rotulos,SR=S.series,n=L.length,m=SR.length;let y0=top+28;
  if(m>1){legend(g,SR.map((s,j)=>[s.nome,C[j]]),top+6,true);y0+=34}
  const all=SR.flatMap(s=>s.valores),mn=Math.min(...all),mx=Math.max(...all);
  const TY=ticks(mn>=0&&mn<=mx*.6?0:mn,mx,5),lo=TY[0],hi=TY[TY.length-1];
  const x0=60+Math.max(...TY.map(t=>measure(val(t),16)))+18,x1=W-80,y1=H-112;
  const X=i=>S.xnum?x0+(S.xnum[i]-S.xnum[0])/((S.xnum[n-1]-S.xnum[0])||1)*(x1-x0):x0+(n===1?.5:i/(n-1))*(x1-x0);
  const Y=v=>y1-(v-lo)/((hi-lo)||1)*(y1-y0);
  axes(g,x0,x1,y0,y1,TY,Y);
  const step=Math.ceil(n/12);
  L.forEach((l,i)=>{if(i%step===0||i===n-1)E(g,"text",{x:X(i),y:y1+28,fill:MUTED,"font-size":16,"text-anchor":"middle"},
    fit(l,Math.max(60,(x1-x0)/Math.min(n,12)-8),16))});
  const e=ease(p*1.08),reveal=x0-12+(x1-x0+24)*e,cg=E(g,"g",{"clip-path":clipRect(svg,x0-12,y0-40,reveal-x0+12,y1-y0+60)});
  SR.forEach((s,j)=>{const col=C[j%C.length],pts=s.valores.map((v,i)=>[X(i),Y(v)]);
    const d="M"+pts.map(q=>q.join(" ")).join("L");
    if(m===1)E(cg,"path",{d:d+`L${pts[n-1][0]} ${y1}L${pts[0][0]} ${y1}Z`,fill:col,opacity:.14});
    E(cg,"path",{d,fill:"none",stroke:col,"stroke-width":4.5,"stroke-linejoin":"round","stroke-linecap":"round"});
    if(n<=24)pts.forEach(q=>E(cg,"circle",{cx:q[0],cy:q[1],r:6,fill:col,stroke:BG,"stroke-width":3}));
    s.valores.forEach((v,i)=>{if((m===1&&n<=10)||i===n-1){const q=pts[i];if(q[0]<=reveal)
      E(g,"text",{x:q[0],y:q[1]-16,fill:INK,"font-size":16,"font-weight":650,
        "text-anchor":i===n-1?"end":i===0?"start":"middle",opacity:clamp((reveal-q[0])/12)},val(v))}})})}
function arc(g,cx,cy,R,r,a0,a1,col){const big=a1-a0>Math.PI?1:0,P=(d,a)=>[cx+d*Math.cos(a),cy+d*Math.sin(a)];
  const[x0,y0]=P(R,a0),[x1,y1]=P(R,a1),[x2,y2]=P(r,a1),[x3,y3]=P(r,a0);
  E(g,"path",{d:`M${x0} ${y0}A${R} ${R} 0 ${big} 1 ${x1} ${y1}L${x2} ${y2}A${r} ${r} 0 ${big} 0 ${x3} ${y3}Z`,
    fill:col,stroke:BG,"stroke-width":3,"stroke-linejoin":"round"})}
function rosca(g,top,p){
  const L=S.rotulos,v=S.series[0].valores,n=L.length,tot=v.reduce((a,b)=>a+b,0);
  const bot=H-62,R=Math.min(190,(bot-top)/2-6),r=R*.6,cx=60+R+10,cy=(top+bot)/2;
  const e=ease(p*1.12),end=-Math.PI/2+2*Math.PI*e;let a0=-Math.PI/2;
  v.forEach((x,i)=>{const a1=a0+2*Math.PI*x/tot,b=Math.min(a1,end);if(b>a0+1e-4)arc(g,cx,cy,R,r,a0,b,C[i%C.length]);a0=a1});
  const pct=x=>nf.format(Math.round(x/tot*1000)/10)+"%",top1=v.indexOf(Math.max(...v)),o=clamp((p-.55)*2.5);
  E(g,"text",{x:cx,y:cy+10,fill:INK,"font-size":46,"font-weight":700,"text-anchor":"middle",opacity:o},U==="%"?val(v[top1]):pct(v[top1]));
  E(g,"text",{x:cx,y:cy+40,fill:MUTED,"font-size":17,"text-anchor":"middle",opacity:o},fit(L[top1],r*1.7,17));
  const lx=cx+R+70,rowH=Math.min(66,(bot-top)/n),ly=cy-rowH*n/2;
  L.forEach((l,i)=>{const k=stag(p,i,n,.5),y=ly+rowH*i+rowH/2;
    const gi=E(g,"g",{opacity:k,transform:`translate(${(1-k)*24} 0)`});
    E(gi,"rect",{x:lx,y:y-17,width:18,height:18,rx:5,fill:C[i%C.length]});
    E(gi,"text",{x:lx+32,y:y-2,fill:INK,"font-size":20,"font-weight":500},fit(l,W-lx-100,20,500));
    E(gi,"text",{x:lx+32,y:y+22,fill:MUTED,"font-size":17},U==="%"?val(v[i]):val(v[i])+" · "+pct(v[i]))})}
function funcao(svg,g,top,p){
  const F=S.curvas,[xa,xb]=S.dom;let y0=top+28;
  legend(g,F.map((f,j)=>[f.nome,C[j%C.length]]),top+6,true);y0+=34;
  const TY=ticks(S.dom[2],S.dom[3],5),ya=TY[0],yb=TY[TY.length-1],TX=ticks(xa,xb,8).filter(t=>t>=xa-1e-9&&t<=xb+1e-9);
  const x0=60+Math.max(...TY.map(t=>measure(val(t),16)))+18,x1=W-80,y1=H-112;
  const X=x=>x0+(x-xa)/((xb-xa)||1)*(x1-x0),Y=y=>Math.min(Math.max(y1-(y-ya)/((yb-ya)||1)*(y1-y0),-4000),4000);
  axes(g,x0,x1,y0,y1,TY,Y,X,TX);
  const e=ease(p*1.05),cg=E(g,"g",{"clip-path":clipRect(svg,x0,y0-6,(x1-x0)*e,y1-y0+12)});
  F.forEach((f,j)=>{let d="",pen=false;for(const[x,y]of f.pts){if(y===null){pen=false;continue}
      d+=(pen?"L":"M")+X(x).toFixed(1)+" "+Y(y).toFixed(1);pen=true}
    E(cg,"path",{d,fill:"none",stroke:C[j%C.length],"stroke-width":4.5,"stroke-linejoin":"round","stroke-linecap":"round"})})}
function tempo(g,top,p){
  const ev=S.eventos,n=ev.length,xa=120,xb=W-120,cy=(top+H-60)/2+4;
  let X=ev.map(v=>xa+(v.ano-ev[0].ano)/((ev[n-1].ano-ev[0].ano)||1)*(xb-xa));
  if(X.some((x,i)=>i&&x-X[i-1]<150))X=ev.map((_,i)=>xa+(n===1?.5:i/(n-1))*(xb-xa));
  const e=ease(p*1.1),xe=xa-50+(xb-xa+100)*e,room=Math.min(250,(xb-xa)/Math.max(n-1,1)*1.8);
  E(g,"line",{x1:xa-50,y1:cy,x2:xe,y2:cy,stroke:AXIS,"stroke-width":4,"stroke-linecap":"round"});
  ev.forEach((v,i)=>{const x=X[i],k=ease((xe-x)/70);if(k<=0)return;
    const col=C[i%C.length],up=i%2===0,dir=up?-1:1,lines=wrap(v.texto,room,17,400,3);
    E(g,"circle",{cx:x,cy,r:10*k,fill:col,stroke:BG,"stroke-width":3});
    const gi=E(g,"g",{opacity:k,transform:`translate(0 ${(1-k)*10*dir})`});
    E(gi,"line",{x1:x,y1:cy+dir*16,x2:x,y2:cy+dir*42,stroke:col,"stroke-width":2.5});
    const yy=up?cy-58-lines.length*22:cy+72;
    E(gi,"text",{x,y:yy,fill:col,"font-size":24,"font-weight":700,"text-anchor":"middle"},v.data);
    lines.forEach((l,j)=>E(gi,"text",{x,y:yy+26+j*22,fill:INK,"font-size":17,"text-anchor":"middle"},l))})}
for(let k=0;k<N;k++){
  const p=k/(N-1),svg=E(document.body,"svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`});
  svg.style.left=(k%COLS)*W+"px";svg.style.top=Math.floor(k/COLS)*H+"px";
  const g=E(svg,"g",{}),top=header(g);
  if(S.tipo==="barras")barras(g,top,p);else if(S.tipo==="linha")linha(svg,g,top,p);
  else if(S.tipo==="rosca")rosca(g,top,p);else if(S.tipo==="funcao")funcao(svg,g,top,p);else tempo(g,top,p)}
</script></body>"""


if __name__ == "__main__":  # python -m lumen.charts grafico.json saida.gif — prévia de um gráfico já conferido
    import sys
    Path(sys.argv[2]).write_bytes(render(json.loads(Path(sys.argv[1]).read_text("utf-8"))) or b"")
