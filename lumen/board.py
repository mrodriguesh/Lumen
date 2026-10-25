"""Painel visual da aula: o segundo Obsidian Canvas (JSON Canvas 1.0), feito das imagens reais da aula.

O Mapa (canvas.py) responde “como as ideias se relacionam”; o Painel responde “como eu reconheço e lembro desta
aula”: uma prancha editorial com as telas e os gráficos que a aula mostrou, em tamanhos pela importância, cada
imagem com um cartão curto ao lado e poucas linhas. Nada é inventado: só entram telas capturadas da aula (já
deduplicadas e lidas por vision.py) e os gráficos feitos com os dados dela. Sem IA aqui: escolha e layout são
determinísticos e locais.

plan() escolhe as imagens (tipo, ligação com os conceitos, o que o estudante escreveu em “Minha compreensão”,
captura feita por ele, horário, qualidade; quase iguais saem). build() compõe a prancha conforme o tipo da aula
(editorial, sequência ou comparação). merge() refaz o painel sem perder o que o usuário moveu ou criou."""
import io
import math
import re
import struct
from collections import Counter

from . import canvas
from .canvas import _height, _id, md
from .llm import fmt_time
from .package import norm

VERSION = 1
DENSITY = {"compacto": 5, "equilibrado": 10, "visual": 15}  # máximo de imagens; menos se a aula não tiver
KIND = {"diagrama": 3.0, "grafico": 3.0, "tabela": 2.5, "formula": 2.5, "quadro": 2.2, "codigo": 2.0,
        "demonstracao": 2.0, "slide": 1.5, "outro": 0.8}
CHART = 1.8        # gráfico feito com os dados da aula: informativo, mas não é o que a aula mostrou
MIN_SCORE = 2.0    # abaixo disto a imagem não entra (aula verbal não vira galeria)
SAME_CONCEPT, SAME_CAP = 0.6, 2.4  # cada imagem a mais do mesmo conceito vale isto a menos (até o teto)
DUP = 0.05         # miniaturas que diferem menos que isto são a mesma imagem (vision.SMALL)
ROLE_W = {"hero": 880, "primary": 440, "secondary": 330, "detail": 230}
TALL_W = {"hero": 560, "primary": 330, "secondary": 250, "detail": 190}  # imagens em pé: mais estreitas
MAX_H = {"hero": 820, "primary": 520, "secondary": 400, "detail": 300}
CAP_GAP, GAP, BAND_GAP = 20, 56, 110  # imagem → cartão; entre peças; antes da faixa de baixo
HERO_CAP_W, HEAD_W, CONN_W = 300, 520, 260
WORDS = 28         # um cartão é curto: o resto está na nota
STOP = set("""para pelo pela pelos pelas como mais menos sobre entre quando onde porque esta este isso isto essa
esse aqui muito muita todos todas tudo cada mesmo mesma pode podem fazer feito sendo seria sera deve devem outro
outra outros outras ainda apenas depois antes tambem assim entao voce voces nosso nossa seus suas dele dela eles
elas aula aulas tela telas mostra mostrando imagem figura texto exemplo exemplos parte vamos aqui agora sobre
with from that this have what your about there their which they will""".split())


# --- Imagens -------------------------------------------------------------------------------------------------

def dims(data):
    """(largura, altura) do cabeçalho de um JPEG, GIF ou PNG, sem decodificar a imagem. None se não reconhece."""
    if not data or len(data) < 24:
        return None
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0xD8, 0x01, 0xFF) or 0xD0 <= m <= 0xD7:
            i += 1 if m == 0xFF else 2
            continue
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):  # SOF: altura e largura
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return (w, h) if w and h else None
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def thumb(data):
    """Miniatura de cinzas para comparar imagens (a mesma régua da captura, vision._small). None se não decodifica."""
    try:
        import av
        from . import vision
        with av.open(io.BytesIO(data)) as c:
            frame = next(c.decode(video=0))
        return vision._small(frame.to_ndarray(format="gray"))
    except Exception:  # noqa: BLE001 — sem miniatura a imagem só não entra na comparação de quase iguais
        return None


def _same(a, b):
    from . import vision
    return a is not None and b is not None and a.shape == b.shape and vision._diff(a, b) < DUP


# --- Escolha -------------------------------------------------------------------------------------------------

def _terms(text):
    return [w for w in norm(text).split() if len(w) >= 4 and w not in STOP and not w.isdigit()]


def _sentence(text, words=WORDS):
    t = " ".join(str(text or "").split())
    first = re.split(r"(?<=[.!?])\s+", t)[0] if t else ""
    w = first.split()
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


def _attention(pkg):
    """O que o estudante escreveu (peso 2) e o que a análise da nota dele destacou (peso 1), por termo."""
    u = pkg.get("understanding") or {}
    c = Counter()
    for w in _terms(u.get("current_understanding") or u.get("original_understanding") or ""):
        c[w] += 2
    a = u.get("ai_analysis") or {}
    for k in ("acertos", "parciais", "lacunas"):
        for item in a.get(k) or []:
            c.update(_terms(item))
    for item in a.get("confusoes") or []:
        if isinstance(item, dict):
            c.update(_terms(f"{item.get('trecho', '')} {item.get('correcao', '')}"))
    return c


def _concepts(pkg):
    """Os tópicos da aula como conceitos: título, termos, horário de início e um resumo de uma frase."""
    lesson, out = pkg["lesson"], []
    branches = {norm(b["label"]): b["children"] for b in (pkg.get("map") or {}).get("branches") or []}
    for t in lesson.get("topics") or []:
        extra = " ".join(branches.get(norm(t["title"]), []))
        out.append({"title": t["title"], "head": set(_terms(t["title"])), "body": set(_terms(f"{t['explanation']} {extra}")),
                    "t": t.get("timestamp"), "line": _sentence(t["explanation"])})
    return out


def plan(pkg, available, density="equilibrado"):
    """Quais imagens entram e com que papel. available: [{key, source ('tela'|'grafico'), ref, file, data}] — as
    imagens que existem de verdade (bytes da aula ou o arquivo já no cofre). Devolve {assets, kind} ou None quando
    nada vale um painel (aula só de fala, ou só telas pouco informativas)."""
    cap = DENSITY.get(density, DENSITY["equilibrado"])
    concepts, att = _concepts(pkg), _attention(pkg)
    screens = {s["id"]: s for s in pkg.get("screens") or []}
    charts = pkg.get("charts") or []
    moments = [m["timestamp"] for m in pkg["lesson"].get("key_moments") or [] if isinstance(m.get("timestamp"), (int, float))]
    starts = sorted([(c["t"], i) for i, c in enumerate(concepts) if isinstance(c["t"], (int, float))])
    cands = []
    for a in available:
        size = dims(a.get("data"))
        if not size:
            continue
        w, h = size
        if a["source"] == "tela":
            s = screens.get(a["ref"])
            if not s:
                continue
            t = None if s.get("manual") else s.get("t")
            title, text, kind = s.get("titulo") or "", f"{s.get('texto', '')} {s.get('descricao', '')}", s.get("tipo") or "outro"
            base = KIND.get(kind, KIND["outro"]) + (2.0 if s.get("manual") else 0)  # o estudante escolheu esta tela
            line = _sentence(s.get("descricao"))
        else:
            c = charts[a["ref"]] if isinstance(a["ref"], int) and a["ref"] < len(charts) else None
            if not c:
                continue
            t, title, kind = c.get("t"), c.get("titulo") or "Gráfico da aula", "grafico_aula"
            text = f"{c.get('mensagem', '')} {' '.join(map(str, c.get('rotulos') or []))}"
            base, line = CHART, _sentence(c.get("mensagem"))
        terms = set(_terms(f"{title} {title} {text[:600]}"))
        # conceito: termos em comum com cada tópico (o título pesa mais) e, para telas da aula, o tópico do horário
        best, concept = 0.0, None
        during = None  # o tópico que a aula estava explicando quando a tela apareceu
        if isinstance(t, (int, float)) and starts:
            during = ([i for st, i in starts if st <= t + 5] or [starts[0][1]])[-1]
        best_terms = 0.0
        for i, c in enumerate(concepts):  # o horário desempata e liga a tela ao tópico; a nota vem dos termos
            sc = 2 * len(terms & c["head"]) + 0.5 * len(terms & c["body"])
            if sc + (1.0 if i == during else 0) > best:
                best, concept, best_terms = sc + (1.0 if i == during else 0), i, sc
        score = base + min(3.0, best_terms * 0.6) + (0.3 if concept is not None and concept == during else 0)
        if not terms:
            score -= 1.0  # sem nada legível nem descrito: não ensina nada no painel
        score += min(2.5, 0.5 * sum(att[w] for w in terms))           # o que o estudante destacou
        if isinstance(t, (int, float)) and any(abs(t - m) <= 45 for m in moments):
            score += 0.5
        if w < 480:
            score -= 2.0
        if len(a.get("data") or b"") < 12_000 and a["source"] == "tela":
            score -= 1.0  # tela quase vazia (JPEG muito pequeno)
        cands.append({"key": a["key"], "source": a["source"], "ref": a["ref"], "file": a["file"], "w": w, "h": h,
                      "t": t, "title": title, "kind": kind, "concept": concept, "score": round(score, 3),
                      "line": line, "thumb": thumb(a["data"]) if a["source"] == "tela" else None})
    # escolha gulosa: a melhor de cada vez, com retorno decrescente por conceito e sem quase iguais
    cands.sort(key=lambda c: (-c["score"], c["t"] if c["t"] is not None else 1e9, c["key"]))
    chosen, per = [], Counter()
    pool = list(cands)
    while pool and len(chosen) < cap:
        def eff(c):
            return c["score"] - (min(SAME_CAP, SAME_CONCEPT * per[c["concept"]]) if c["concept"] is not None else 0)
        pool.sort(key=lambda c: (-eff(c), c["t"] if c["t"] is not None else 1e9, c["key"]))
        c = pool.pop(0)
        if eff(c) < MIN_SCORE:
            break
        if any(_same(c["thumb"], x["thumb"]) for x in chosen):
            continue
        chosen.append(c)
        per[c["concept"]] += 1
    if not chosen:
        return None
    for c in chosen:
        c.pop("thumb", None)
    # papéis: a melhor (larga o bastante) domina; algumas primárias; o resto menor
    order = sorted(chosen, key=lambda c: (-c["score"], c["key"]))
    hero = next((c for c in order[:3] if c["w"] >= 640 and c["source"] == "tela"), None) or \
        next((c for c in order[:3] if c["w"] >= 640), None)
    n_primary = 2 if len(order) <= 5 else 3 if len(order) <= 8 else 4
    rest = [c for c in order if c is not hero]
    for i, c in enumerate(rest):
        c["role"] = "primary" if i < n_primary else "secondary" if i < n_primary + 4 else "detail"
    if hero:
        hero["role"] = "hero"
    for c in chosen:
        c["concept_title"] = concepts[c["concept"]]["title"] if c["concept"] is not None else ""
        c["concept_line"] = concepts[c["concept"]]["line"] if c["concept"] is not None else ""
    return {"assets": order, "kind": _kind(pkg, order, concepts), "version": VERSION}


def _kind(pkg, assets, concepts):
    """A composição: sequência (aula de passo a passo com imagens no tempo), comparação (a aula contrapõe dois
    conceitos e há imagem dos dois) ou editorial (o resto)."""
    lesson = pkg["lesson"]
    if lesson.get("map_kind") == "tutorial" and len([a for a in assets if a["t"] is not None]) >= 3:
        return {"name": "sequencia"}
    for r in lesson.get("relations") or []:
        if r.get("type") != "contrasta com":
            continue
        sides = []
        for label in (r["from"], r["to"]):
            want = set(_terms(label))
            sides.append([a["key"] for a in assets if want & set(_terms(f"{a['title']} {a['concept_title']}"))])
        a_side, b_side = sides
        b_side = [k for k in b_side if k not in a_side]
        if a_side and b_side:
            return {"name": "comparacao", "a": r["from"], "b": r["to"], "left": a_side[:3], "right": b_side[:3]}
    return {"name": "editorial"}


# --- Composição ----------------------------------------------------------------------------------------------

def head_id(lid):
    """O id do cabeçalho do painel: o mesmo em toda versão do painel desta aula (acha o arquivo sem o manifesto)."""
    return _id(lid, "board-head", "head", {})


def _size(a):
    tall = a["h"] > a["w"] * 1.1
    w = (TALL_W if tall else ROLE_W)[a["role"]]
    h = w * a["h"] / a["w"]
    if h > MAX_H[a["role"]]:
        h = MAX_H[a["role"]]
        w = h * a["w"] / a["h"]
    return max(120, round(w)), max(80, round(h))


def _caption(a):
    """“`03:09` · **Título**”, o conceito (se for outro) e uma frase. Texto da IA sempre por md()."""
    when = f"`{fmt_time(a['t'])}` · " if a["t"] is not None else ""
    lines = [f"{when}**{md(a['title'] or 'Tela da aula')}**" + (" · *sua captura*" if a["source"] == "tela" and a["t"] is None else "")]
    head, title = set(_terms(a["concept_title"])), set(_terms(a["title"]))
    if head and len(head & title) < max(1, len(head) / 2):  # o conceito só aparece quando diz algo a mais
        lines.append(f"*{md(a['concept_title'])}*")
    line = a["line"]
    if a["role"] in ("hero", "primary") and a["concept_line"] and a["source"] == "tela":
        line = a["concept_line"]  # a imagem principal leva a ideia do conceito; as outras, o que mostram
    if line:
        lines.append(md(line))
    return "\n".join(lines)


def _plain(text):
    """O texto como aparece no card (para medir a altura): sem marcação e com o rótulo no lugar do link."""
    text = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", text)
    return re.sub(r"[`*#]|\[\[|\]\]", "", text).strip()


def build(plan_, pkg, note_name, map_name=None, files=None):
    """A prancha. Devolve (canvas, peças): cada peça é a lista de ids que se movem juntos (imagem + cartão)."""
    files = files or {}
    lid, seen = pkg["lumen_id"], {}
    nodes, edges, units = [], [], []
    rects = []  # o que já ocupa lugar (cards e imagens), para a colocação não sobrepor

    def node(kind, role, name, x, y, w, h, **extra):
        n = {"id": _id(lid, role, name, seen), "type": kind, "x": round(x), "y": round(y), "width": round(w),
             "height": round(h), **extra}
        nodes.append(n)
        if kind != "group":
            rects.append(n)
        return n

    def edge(a, b, fs, ts, **extra):
        edges.append({"id": _id(lid, "board-edge", a["id"] + b["id"], seen), "fromNode": a["id"], "fromSide": fs,
                      "toNode": b["id"], "toSide": ts, **extra})

    def tile(a, x, y, caption=True, cap_w=None):
        """Imagem com o cartão logo abaixo (ou nenhum, para os detalhes). Devolve (imagem, cartão)."""
        w, h = _size(a)
        img = node("file", "board-img", a["key"], x, y, w, h, file=a["file"])
        cap = None
        if caption and a["role"] != "detail":
            text = _caption(a)
            cw = cap_w or max(240, min(w, 340))
            cap = node("text", "board-cap", a["key"], x, y + h + CAP_GAP, cw, _height(_plain(text), cw), text=text)
        units.append([img["id"]] + ([cap["id"]] if cap else []))
        return img, cap

    def extent(n):
        return n["x"], n["y"], n["x"] + n["width"], n["y"] + n["height"]

    def tile_size(a, caption=True, cap_w=None):
        w, h = _size(a)
        if caption and a["role"] != "detail":
            cw = cap_w or max(240, min(w, 340))
            return max(w, cw), h + CAP_GAP + _height(_plain(_caption(a)), cw)
        return w, h

    def free(x, y, w, h):
        return not any(x < r["x"] + r["width"] + GAP and r["x"] < x + w + GAP and y < r["y"] + r["height"] + GAP
                       and r["y"] < y + h + GAP for r in rects)

    def drop(a, x, y):
        """Coloca a peça em (x, y) ou, se não couber, desce em passos até caber (nunca sobrepõe)."""
        w, h = tile_size(a)
        while not free(x, y, w, h):
            y += 20
        return tile(a, x, y)

    def skyline(items, top):
        """A faixa de baixo: cada peça cai no ponto livre mais alto da faixa (empate: mais perto do centro), como
        peças empilhadas. Larguras diferentes dão uma prancha assimétrica, mas cada posição sai de uma regra."""
        if not items:
            return
        x0 = min(r["x"] for r in rects)
        x1 = max(r["x"] + r["width"] for r in rects)
        mid = (x0 + x1) / 2
        for i, a in enumerate(items):
            if a["role"] == "secondary" and i % 2:
                a["role"] = "detail" if i % 4 == 3 else a["role"]
            w, h = tile_size(a)
            best = None
            for x in range(int(x0), int(max(x0, x1 - w)) + 1, 20):
                # abaixo de tudo o que ocupa esta faixa horizontal: sob a imagem principal sobe; sob uma coluna, desce
                y = max([top] + [r["y"] + r["height"] + GAP for r in rects
                                 if x < r["x"] + r["width"] + GAP and r["x"] < x + w + GAP])
                cand = (y, abs(x + w / 2 - mid), x)
                if best is None or cand < best:
                    best = cand
            y, _, x = best
            y += (i % 3) * 28  # desencontro deliberado: a faixa respira e não vira grade
            tile(a, x, y)

    lesson, src, assets = pkg["lesson"], pkg["source"], plan_["assets"]
    kind = plan_["kind"]
    by_key = {a["key"]: a for a in assets}

    # cabeçalho discreto: título, curso · data · duração, e os caminhos para a nota e o mapa
    course = " ".join(str(pkg.get("course") or "").split())
    course = course if len(course) <= 40 else course[:38].rstrip() + "…"
    meta = " · ".join(x for x in (md(course), pkg.get("date") or "",
                                  f"{round(src['duration'] / 60)} min" if src.get("duration") else "",
                                  md(src.get("label") or "")) if x)
    links = [f"[[{note_name}|Abrir a nota de estudo]]"] + ([f"[[{map_name}|Mapa conceitual]]"] if map_name else [])
    head_text = f"## {md(lesson['title'])}\n{meta}\n\n" + " · ".join(links)
    head_h = _height(_plain(head_text), HEAD_W) + 12

    if kind["name"] == "sequencia":
        seq = sorted(assets, key=lambda a: (a["t"] if a["t"] is not None else 1e9, a["key"]))
        for a in seq:  # num passo a passo, nenhum passo esconde os outros, e todo passo leva o seu horário
            a["role"] = "primary" if a["role"] == "hero" else "secondary" if a["role"] == "detail" else a["role"]
        head = node("text", "board-head", "head", 0, -head_h - 80, HEAD_W, head_h, text=head_text)
        units.append([head["id"]])
        per_row, row_top, prev_img, right = 4, 0, None, 0
        for r, row in enumerate([seq[i:i + per_row] for i in range(0, len(seq), per_row)]):
            back = r % 2 == 1  # zigue-zague: a linha seguinte volta, e a seta desce em vez de cruzar a prancha
            cursor, row_h = (right if back else 0), 0
            for j, a in enumerate(row):
                w, _ = tile_size(a)
                x = cursor - w if back else cursor
                img, cap = tile(a, x, row_top + (110 if j % 2 else 0))
                row_h = max(row_h, (cap or img)["y"] + (cap or img)["height"] - row_top)
                if prev_img:
                    if j == 0:
                        edge(prev_img, img, "bottom", "top")
                    else:
                        edge(prev_img, img, "left" if back else "right", "right" if back else "left")
                prev_img = img
                cursor = x - GAP * 1.6 if back else x + w + GAP * 1.6
                right = max(right, x + w)
            row_top += row_h + BAND_GAP
    elif kind["name"] == "comparacao":
        head = node("text", "board-head", "head", 0, -head_h - 200, HEAD_W, head_h, text=head_text)
        units.append([head["id"]])
        col_w = 460
        left = node("text", "board-side", kind["a"], 0, -110, 320, 70, text=f"**{md(kind['a'])}**", color="5")
        right = node("text", "board-side", kind["b"], col_w + 180, -110, 320, 70, text=f"**{md(kind['b'])}**", color="4")
        units.append([left["id"]])
        units.append([right["id"]])
        edge(left, right, "right", "left", label="contrasta com")
        used = set()
        for keys, x in ((kind["left"], 0), (kind["right"], col_w + 180)):
            y = 0
            for k in keys:
                a = by_key[k]
                if a["role"] in ("hero", "detail"):
                    a["role"] = "primary"
                img, cap = tile(a, x, y)
                y = (cap or img)["y"] + (cap or img)["height"] + GAP
                used.add(k)
        skyline([a for a in assets if a["key"] not in used], max(r["y"] + r["height"] for r in rects) + BAND_GAP)
    else:
        hero = next((a for a in assets if a["role"] == "hero"), None)
        primaries = [a for a in assets if a["role"] == "primary"]
        if not hero:  # sem imagem larga: a melhor primária ocupa o centro, menor
            hero = primaries.pop(0)
        hw, hh = _size(hero)
        img = node("file", "board-img", hero["key"], 0, 0, hw, hh, file=hero["file"])
        text = _caption(hero)
        cap = node("text", "board-cap", hero["key"], hw + CAP_GAP + 8, 0, HERO_CAP_W,
                   _height(_plain(text), HERO_CAP_W), text=text)
        units.append([img["id"], cap["id"]])
        head = node("text", "board-head", "head", 0, -head_h - 80, HEAD_W, head_h, text=head_text)
        units.append([head["id"]])
        right_x = hw + CAP_GAP + 8 + HERO_CAP_W + GAP * 1.4
        ys = {"right": 70, "left": 150}  # alturas desencontradas: os lados não espelham um ao outro
        for i, a in enumerate(primaries):
            side = "right" if i % 2 == 0 else "left"
            w, h = tile_size(a)
            x = right_x if side == "right" else -GAP * 1.4 - w
            img2, cap2 = drop(a, x, ys[side])
            ys[side] = (cap2 or img2)["y"] + (cap2 or img2)["height"] + GAP + 30
        rest = [a for a in assets if a["role"] in ("secondary", "detail")]
        skyline(rest, max(img["y"] + img["height"], cap["y"] + cap["height"]) + BAND_GAP)

    # Conexões com o segundo cérebro: poucas, num grupo na borda (o painel não é o mapa do cofre)
    conns = [c for c in pkg.get("connections") or [] if c["note"] in files][:4]
    if conns:
        gx = max(r["x"] + r["width"] for r in rects) + GAP * 2.2
        gy, members = min(r["y"] for r in rects if r["type"] == "file"), []
        y = gy + 40
        for c in conns:
            t = f"**[[{c['note']}]]**\n*{md(c.get('relation') or 'relacionado')}*"
            h = _height(_plain(t), CONN_W)
            members.append(node("text", "board-conn", c["note"], gx + 40, y, CONN_W, h, text=t))
            y += h + 24
        g = node("group", "board-group", "Conexões", gx, gy, CONN_W + 80, y - gy + 16, label="Conexões", color="6")
        units.append([g["id"]] + [m["id"] for m in members])
    groups = [n for n in nodes if n["type"] == "group"]
    return {"nodes": groups + [n for n in nodes if n["type"] != "group"], "edges": edges}, units


def check(board):
    """Problemas ([] = ok): o formato (canvas.check) e, como o layout é do Lumen, nada sobreposto e cada cartão
    colado na sua imagem. Cartão “solto” é permitido: a proximidade é a ligação, sem setas de enfeite."""
    probs = canvas.check(board, layout=False)
    cards = [n for n in board["nodes"] if n["type"] != "group"]
    for i, a in enumerate(cards):
        probs += [f"sobreposição: {a['id']} × {b['id']}" for b in cards[i + 1:] if canvas._overlap(a, b)]
    return probs


# --- Atualizar sem perder o que o usuário fez -------------------------------------------------------------------

def layout(board):
    """As posições que o Lumen calculou (guardadas no manifesto, fora do arquivo: o JSON Canvas fica limpo)."""
    return {n["id"]: [n["x"], n["y"], n["width"], n["height"]] for n in board["nodes"]}


def merge(old, fresh, units, last=None, sticky=()):
    """Painel novo sobre o que está no cofre. Devolve (painel, ids que o usuário moveu).
    last: layout() do que o Lumen gravou da vez anterior (None = sem manifesto: tudo o que está no arquivo conta
    como mexido pelo usuário); sticky: os que ele já tinha movido antes (continuam dele). Cards do Lumen que o
    usuário moveu ficam onde ele os pôs, mesmo que a imagem tenha saído da escolha; o que ele criou fica; o resto
    segue o layout novo. Uma peça nova que caia em cima de algo mantido desce para baixo de tudo."""
    if not isinstance(old, dict) or not isinstance(old.get("nodes"), list):
        return fresh, set()
    last = last if isinstance(last, dict) else None
    sticky = {i for i in sticky or () if isinstance(i, str)}
    olds = [n for n in old["nodes"] if isinstance(n, dict) and isinstance(n.get("id"), str)]
    prev = {n["id"]: n for n in olds}
    box = ("x", "y", "width", "height")

    def moved(o):
        if not all(isinstance(o.get(k), (int, float)) for k in box):
            return False
        if o["id"] in sticky:
            return True
        g = (last or {}).get(o["id"])
        return last is None or g is None or [o[k] for k in box] != list(g)

    nodes, kept = [], set()
    fresh_ids = {n["id"] for n in fresh["nodes"]}
    for n in fresh["nodes"]:
        o = prev.get(n["id"])
        if o and n["type"] != "group" and moved(o):
            n = {**n, **{k: o[k] for k in box}}
            kept.add(n["id"])
        nodes.append(n)
    for o in olds:  # do Lumen, fora da escolha nova, mas mexido pelo usuário: fica
        if o["id"] not in fresh_ids and o["id"].startswith("lumen-") and o.get("type") != "group" and moved(o):
            nodes.append(o)
            kept.add(o["id"])
    mine = [o for o in olds if not o["id"].startswith("lumen-")]
    kept |= {o["id"] for o in mine}
    pos = {n["id"]: n for n in nodes + mine}
    # peças novas (ou que seguem o layout novo) não podem cair em cima do que ficou onde estava
    fixed = [pos[i] for i in kept if pos[i].get("type") != "group" and all(isinstance(pos[i].get(k), (int, float)) for k in box)]
    for unit in units:
        free_part = [pos[i] for i in unit if i in pos and i not in kept]
        if not free_part:
            continue
        if all(i in prev and all(prev[i].get(k) == pos[i][k] for k in box) for i in unit if i in pos):
            fixed += [n for n in free_part if n["type"] != "group"]  # já estava exatamente aí: não sai do lugar
            continue
        if any(canvas._overlap(a, b) for a in free_part if a["type"] != "group" for b in fixed):
            top = min(n["y"] for n in free_part)
            floor = max(n["y"] + n["height"] for n in fixed + free_part) + GAP
            for n in free_part:
                n["y"] = round(n["y"] + floor - top)
        fixed += [n for n in free_part if n["type"] != "group"]
    ids = set(pos)
    edges = fresh["edges"] + [e for e in old.get("edges") or [] if isinstance(e, dict)
                              and not str(e.get("id", "")).startswith("lumen-")
                              and e.get("fromNode") in ids and e.get("toNode") in ids]
    out = {"nodes": [n for n in nodes if n["type"] == "group"] + [n for n in nodes if n["type"] != "group"] + mine,
           "edges": edges}
    canvas._fit_groups(out, fresh)
    return out, {i for i in kept if i.startswith("lumen-")}


def files_of(board):
    """Os arquivos que o painel mostra (para a limpeza de anexos não apagar nada que ele usa)."""
    return {n["file"] for n in board.get("nodes") or [] if isinstance(n, dict) and n.get("type") == "file" and n.get("file")}
