"""Mapa mental da aula como Obsidian Canvas de verdade (JSON Canvas 1.0, jsoncanvas.org), não uma imagem.

Layout determinístico, sem posições ao acaso: o centro é a própria nota da aula (node `file`), os ramos do mapa
(llm: mind_map) se dividem entre direita e esquerda pela altura, cada ramo com os filhos ao lado; as relações da
aula (llm: relations) viram arestas com rótulo (“causa”, “depende de”…). Embaixo, uma linha de grupos (Processo,
Conexões com o segundo cérebro, Exemplos) e, em cima, o vídeo original. O tamanho de cada card vem do texto.

IDs estáveis (`lumen-` + hash do papel e do rótulo): ao reprocessar, `merge` mantém onde o usuário moveu ou
redimensionou cada card, e os cards e setas que ele criou (ids sem o prefixo) ficam."""
import hashlib
import json
import math
import re

from .package import norm

COLORS = ["5", "4", "6", "2", "3", "1"]  # cores do próprio Obsidian (ciano, verde, roxo, laranja, amarelo, vermelho)
CHAR_W, LINE_H, PAD = 8.6, 26, 34       # texto de um card: largura média de um caractere, altura da linha, margens
CENTER_W, CENTER_H = 440, 300           # a nota no centro (mostra o começo dela)
BRANCH_W, LEAF_W, GROUP_W = 280, 260, 280
GAP_X, LEAF_X, GAP_Y, LEAF_GAP = 150, 140, 56, 24  # LEAF_X: cabe um rótulo de relação na seta
GROUP_PAD, GROUP_GAP, ROW_GAP = 40, 90, 240  # ROW_GAP: espaço para as relações que contornam o mapa por baixo


def md(text, table=False):
    """Texto da IA seguro dentro de Markdown do Obsidian: nenhum link, tag, comentário ou HTML é criado por ele."""
    t = str(text or "").replace("\r", "")
    t = t.replace("<", "&lt;").replace("%%", "% %")
    t = t.replace("[[", "[\\[")
    t = re.sub(r"(?m)(^|\s)#", lambda m: m.group(1) + "\\#", t)
    t = re.sub(r"`(\$?=)", "`​\\1", t)  # código inline que começa por “=” vira consulta em alguns plugins
    if table:
        t = " ".join(t.replace("|", "\\|").split())
    return t


def _height(text, width):
    lines = 0
    for para in str(text).split("\n"):
        lines += max(1, math.ceil(len(para) * CHAR_W / (width - 2 * 20)))
    return max(60, round(lines * LINE_H + PAD))


def _id(lid, role, label, seen):
    base = "lumen-" + hashlib.sha1(f"{lid}|{role}|{norm(label)}".encode()).hexdigest()[:14]
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if not n else f"{base}{n}"


def center_id(lid):
    """O id do card central (a nota da aula): o mesmo em toda versão do canvas desta aula."""
    return _id(lid, "center", "center", {})


def build(pkg, note_path, files=None):
    """Canvas da aula. note_path: a nota (caminho no cofre); files: {nome da nota conectada: caminho no cofre}."""
    files = files or {}
    m, lesson, lid, seen = pkg["map"], pkg["lesson"], pkg["lumen_id"], {}
    nodes, edges, by_label, groups, tree, side = [], [], {}, [], {}, {}

    def node(kind, role, label, x, y, w, h, **extra):
        n = {"id": _id(lid, role, label, seen), "type": kind, "x": round(x), "y": round(y), "width": round(w),
             "height": round(h), **extra}
        nodes.append(n)
        return n

    def edge(a, b, fs, ts, **extra):
        e = {"id": _id(lid, "edge", a["id"] + b["id"] + extra.get("label", ""), seen), "fromNode": a["id"],
             "fromSide": fs, "toNode": b["id"], "toSide": ts, **extra}
        edges.append(e)
        return e

    def branch_edge(a, b, right, color):
        tree[frozenset((a["id"], b["id"]))] = edge(a, b, "right" if right else "left", "left" if right else "right",
                                                   color=color)

    # o centro é a própria nota, aberta na Visão geral (o resumo), não no frontmatter
    center = node("file", "center", "center", -CENTER_W / 2, -CENTER_H / 2, CENTER_W, CENTER_H, file=note_path,
                  subpath="#Visão geral")
    by_label[norm(m["center"])] = center
    side[center["id"]] = "center"

    # ramos: altura de cada subárvore e o lado (o mais vazio recebe o próximo; empate vai para a direita)
    trees = []
    for i, b in enumerate(m["branches"]):
        label = f"**{md(b['label'])}**"
        bh = _height(b["label"], BRANCH_W)
        kids = [(k, _height(k, LEAF_W)) for k in b["children"]]
        kh = sum(h for _, h in kids) + LEAF_GAP * max(len(kids) - 1, 0)
        trees.append({"b": b, "text": label, "bh": bh, "kids": kids, "kh": kh, "h": max(bh, kh),
                      "color": COLORS[i % len(COLORS)]})
    # ramos relacionados (llm: relations) ficam do mesmo lado quando isso não desequilibra o mapa: uma relação
    # entre lados opostos teria de passar perto da nota central
    owner = {}
    for i, b in enumerate(m["branches"]):
        owner[norm(b["label"])] = i
        for k in b["children"]:
            owner.setdefault(norm(k), i)
    near = {i: set() for i in range(len(trees))}
    for r in lesson.get("relations") or []:
        a, b = owner.get(norm(r["from"])), owner.get(norm(r["to"]))
        if a is not None and b is not None and a != b:
            near[a].add(b)
            near[b].add(a)
    sides, total, placed = {"right": [], "left": []}, {"right": 0, "left": 0}, {}
    for i, t in enumerate(trees):
        s = "right" if total["right"] <= total["left"] else "left"
        votes = [placed[j] for j in sorted(near[i]) if j in placed]
        if votes:
            want = max(("right", "left"), key=votes.count)
            if total[want] - total["left" if want == "right" else "right"] <= t["h"] + GAP_Y:
                s = want
        placed[i] = s
        sides[s].append(t)
        total[s] += t["h"] + GAP_Y
    for s, items in sides.items():
        y = -(sum(t["h"] for t in items) + GAP_Y * max(len(items) - 1, 0)) / 2
        right = s == "right"
        bx = CENTER_W / 2 + GAP_X if right else -CENTER_W / 2 - GAP_X - BRANCH_W
        kx = bx + BRANCH_W + LEAF_X if right else bx - LEAF_X - LEAF_W
        for t in items:
            br = node("text", "branch", t["b"]["label"], bx, y + (t["h"] - t["bh"]) / 2, BRANCH_W, t["bh"],
                      text=t["text"], color=t["color"])
            by_label.setdefault(norm(t["b"]["label"]), br)
            side[br["id"]] = s
            branch_edge(center, br, right, t["color"])
            ky = y + (t["h"] - t["kh"]) / 2
            for k, h in t["kids"]:
                leaf = node("text", "leaf:" + norm(t["b"]["label"]), k, kx, ky, LEAF_W, h, text=md(k), color=t["color"])
                by_label.setdefault(norm(k), leaf)
                side[leaf["id"]] = s
                branch_edge(br, leaf, right, t["color"])
                ky += h + LEAF_GAP
            y += t["h"] + GAP_Y

    # relações da aula entre cards do mapa, com o rótulo do tipo (validadas em package.validate)
    cross = []
    for r in lesson.get("relations") or []:
        a, b = by_label.get(norm(r["from"])), by_label.get(norm(r["to"]))
        if not (a and b) or a is b:
            continue
        e = tree.get(frozenset((a["id"], b["id"])))
        if e:  # pai e filho: a seta que já existe ganha o rótulo, com a ponta em quem recebe a relação
            if "label" not in e:
                e["label"] = r["type"]
                if e["fromNode"] != a["id"]:
                    e.update(fromEnd="arrow", toEnd="none")
        elif "center" not in (side[a["id"]], side[b["id"]]) and side[a["id"]] != side[b["id"]]:
            cross.append(r)  # lados opostos: a seta cruzaria a nota central; vira um card no grupo Relações
        else:
            edge(a, b, *_sides(a, b), label=r["type"])

    top = min([n["y"] for n in nodes])
    bottom = max([n["y"] + n["height"] for n in nodes])

    # vídeo original em cima do centro
    link = pkg["source"].get("link")
    if link and re.match(r"^https?://", link):
        src = node("link", "source", link, -CENTER_W / 2, top - 260 - ROW_GAP, CENTER_W, 260, url=link)
        edge(src, center, "bottom", "top", label="aula original")

    # linha de grupos embaixo: Processo | Conexões (sob o centro) | Exemplos
    def column(role, title, items, color=None):
        if not items:
            return None
        members, y = [], 0
        for kind, label, h, extra in items:
            members.append(node(kind, role, label, 0, y, GROUP_W, h, **extra))
            y += h + LEAF_GAP
        return {"role": role, "title": title, "members": members, "h": y - LEAF_GAP, "color": color}

    steps = column("step", "Processo", [("text", s, _height(s, GROUP_W), {"text": f"{i}. {md(s)}"})
                                        for i, s in enumerate(lesson.get("steps") or [], 1)][:12])
    links = [c for c in pkg.get("connections") or [] if c["note"] in files]
    anchors = [a for a in pkg.get("anchors") or [] if a in files and a not in {c["note"] for c in links}]
    # cada conexão é um card com o link (clicar abre a nota) e o porquê; um card de arquivo mostraria só o topo
    # da nota (as propriedades), que não diz nada sobre a relação
    conns = column("conn", "Conexões", [
        ("text", c["note"], _height(f"{c['note']}\n{c.get('relation')} — {c['reason']}", GROUP_W),
         {"text": f"**[[{c['note']}]]**\n*{md(c.get('relation') or 'relacionado')}* — {md(c['reason'])}"}) for c in links][:8]
        + [("text", a, 80, {"text": f"**[[{a}]]**\n*Anchor Topic*"}) for a in anchors][:3], "6")
    examples = column("example", "Exemplos", [
        ("text", e["text"], _height(("Da aula: " if e["origin"] == "aula" else "Analogia (IA): ") + e["text"], GROUP_W),
         {"text": ("**Da aula:** " if e["origin"] == "aula" else "**Analogia (IA):** ") + md(e["text"])})
        for e in lesson.get("examples") or []][:6])
    rels = column("relation", "Relações", [
        ("text", f"{r['from']}|{r['type']}|{r['to']}", _height(f"{r['from']} {r['type']} {r['to']}", GROUP_W),
         {"text": f"**{md(r['from'])}** *{md(r['type'])}* **{md(r['to'])}**"}) for r in cross][:8], "4")
    row = [g for g in (steps, conns, examples, rels) if g]
    if row:
        width = GROUP_W + 2 * GROUP_PAD
        mid = row.index(conns) if conns else (len(row) - 1) / 2
        gy = bottom + ROW_GAP
        for i, g in enumerate(row):
            gx = (i - mid) * (width + GROUP_GAP) - width / 2
            for n in g["members"]:
                n["x"], n["y"] = round(gx + GROUP_PAD), round(gy + GROUP_PAD + n["y"])
            groups.append({"id": _id(lid, "group", g["title"], seen), "type": "group", "x": round(gx), "y": round(gy),
                           "width": round(width), "height": round(g["h"] + 2 * GROUP_PAD), "label": g["title"],
                           **({"color": g["color"]} if g["color"] else {})})
        if steps:
            for a, b in zip(steps["members"], steps["members"][1:]):
                edge(a, b, "bottom", "top")
        if conns:  # uma seta só, da nota para o grupo: sem rótulos empilhados
            edge(center, groups[row.index(conns)], "bottom", "top", color="6")
    return {"nodes": groups + nodes, "edges": edges}


def _sides(a, b):
    """De que lado sai e chega uma relação, pela posição dos dois cards."""
    ax, bx = a["x"] + a["width"] / 2, b["x"] + b["width"] / 2
    if abs(ax - bx) < (a["width"] + b["width"]) / 2:  # mesma coluna: por cima ou por baixo
        return ("bottom", "top") if a["y"] < b["y"] else ("top", "bottom")
    return ("right", "left") if ax < bx else ("left", "right")


def merge(old, new):
    """Canvas novo sobre o que está no cofre: cards do Lumen que continuam ficam onde o usuário os pôs (posição e
    tamanho); o que o usuário criou fica; o que o Lumen não gera mais sai. Grupos se ajustam aos seus cards."""
    if not isinstance(old, dict):
        return new
    prev = {n.get("id"): n for n in old.get("nodes") or [] if isinstance(n, dict)}
    nodes = []
    for n in new["nodes"]:
        o = prev.get(n["id"])
        if o and n["type"] != "group":
            n = {**n, **{k: o[k] for k in ("x", "y", "width", "height") if isinstance(o.get(k), (int, float))}}
        nodes.append(n)
    mine = [n for n in old.get("nodes") or [] if isinstance(n, dict) and not str(n.get("id", "")).startswith("lumen-")]
    ids = {n["id"] for n in nodes} | {n.get("id") for n in mine}
    edges = new["edges"] + [e for e in old.get("edges") or [] if isinstance(e, dict)
                            and not str(e.get("id", "")).startswith("lumen-")
                            and e.get("fromNode") in ids and e.get("toNode") in ids]
    out = {"nodes": nodes + mine, "edges": edges}
    _fit_groups(out, new)
    return out


def _fit_groups(canvas, fresh):
    """Cada grupo do Lumen volta a envolver os seus cards (que podem ter sido movidos ou ser novos)."""
    pos = {n["id"]: n for n in canvas["nodes"]}
    for g in [n for n in fresh["nodes"] if n["type"] == "group"]:
        inner = [pos[n["id"]] for n in fresh["nodes"] if n["type"] != "group" and _within(n, g)]
        if inner:
            x0, y0 = min(n["x"] for n in inner) - GROUP_PAD, min(n["y"] for n in inner) - GROUP_PAD
            x1 = max(n["x"] + n["width"] for n in inner) + GROUP_PAD
            y1 = max(n["y"] + n["height"] for n in inner) + GROUP_PAD
            pos[g["id"]].update(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def _within(n, g):
    return (g["x"] <= n["x"] and n["x"] + n["width"] <= g["x"] + g["width"]
            and g["y"] <= n["y"] and n["y"] + n["height"] <= g["y"] + g["height"])


def _overlap(a, b):
    return (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
            and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"])


SPEC = {"text": {"text"}, "file": {"file"}, "link": {"url"}, "group": set()}
EDGE_SIDES = {"top", "right", "bottom", "left"}


def check(canvas, layout=True):
    """Problemas do canvas ([] = ok): formato do JSON Canvas, ids, arestas, e (layout=True, o que o Lumen calculou)
    cards sobrepostos, card fora do seu grupo e card solto (sem seta e fora de grupo)."""
    probs, ids = [], set()
    nodes, edges = canvas.get("nodes") or [], canvas.get("edges") or []
    for n in nodes:
        need = {"id", "type", "x", "y", "width", "height"} | SPEC.get(n.get("type"), {"?"})
        if need - set(n) or n.get("type") not in SPEC:
            probs.append(f"card inválido: {n.get('id')}")
        if n.get("id") in ids:
            probs.append(f"id repetido: {n.get('id')}")
        ids.add(n.get("id"))
        if n.get("width", 0) < 40 or n.get("height", 0) < 40:
            probs.append(f"card pequeno demais: {n.get('id')}")
        if "color" in n and not re.fullmatch(r"[1-6]|#[0-9a-fA-F]{6}", str(n["color"])):
            probs.append(f"cor inválida: {n.get('id')}")
    for e in edges:
        if e.get("fromNode") not in ids or e.get("toNode") not in ids:
            probs.append(f"seta para card inexistente: {e.get('id')}")
        if {e.get("fromSide", "top"), e.get("toSide", "top")} - EDGE_SIDES:
            probs.append(f"lado inválido: {e.get('id')}")
    if layout:
        cards = [n for n in nodes if n.get("type") != "group"]
        grouped = {n["id"] for n in cards for g in nodes if g.get("type") == "group" and _within(n, g)}
        linked = {e["fromNode"] for e in edges} | {e["toNode"] for e in edges}
        for i, a in enumerate(cards):
            probs += [f"sobreposição: {a['id']} × {b['id']}" for b in cards[i + 1:] if _overlap(a, b)]
            if a["id"] not in grouped and a["id"] not in linked:
                probs.append(f"card solto: {a['id']}")
        for g in [n for n in nodes if n.get("type") == "group"]:
            if not any(_within(n, g) for n in cards):
                probs.append(f"grupo vazio: {g['id']}")
    return probs


def dumps(canvas):
    return json.dumps(canvas, ensure_ascii=False, indent="\t")
