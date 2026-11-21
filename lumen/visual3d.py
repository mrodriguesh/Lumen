"""Visualização 3D da aula: uma cena tridimensional com aparência de holograma, feita com o material da própria aula
e entregue ao Notion e ao Obsidian como GIF animado (com PNG de reserva) ou só PNG.

Fluxo: pacote validado → spec (um objeto de dados pequeno, montado aqui sem IA a partir do mapa, dos passos e das
relações) → validate (tipos, quantidades, rótulos, relações aceitas) → cena (primitivas 3D) → quadros → GIF/PNG
conferidos (inspect) → cache em DATA/visuals/<lumen_id> → destinos. Nada da aula ou da IA vira código: a spec só
traz rótulos e índices, e o desenho é sempre este.

Desenho: NumPy + Pillow, na CPU e no próprio processo (sem navegador, sem GPU, sem processo externo para encerrar).
Projeção em perspectiva com a câmera orbitando; objetos ordenados por profundidade (o da frente cobre o de trás);
faces translúcidas com a borda mais clara quando vistas de lado; arestas de trás apagadas; brilho por desfoque. Os
textos usam a Inter do próprio projeto (lumen/web/fonts), desenhados por último para ficarem legíveis.
"""
import hashlib
import io
import json
import logging
import math
import os
import re
import struct
import threading
import time
import unicodedata
from pathlib import Path

import numpy as np

from . import Cancelled, store
from .package import RELATIONS, norm

log = logging.getLogger("lumen")

RENDERER = "holo-3"                 # versão do desenho e do contrato de validação/cache
MODES = ("animated", "static", "off")
W, H, FPS, FRAMES = 960, 540, 12, 48  # 16:9, 4 s em laço contínuo
ATTEMPTS = ((960, 540, 48), (960, 540, 36), (800, 450, 36))  # se o GIF passar do peso: menos quadros, depois menor
MAX_GIF, MAX_PNG = 4_500_000, 1_500_000  # o Notion gratuito aceita até 5 MB por arquivo
BUDGET_S, LIMIT_S = 45.0, 120.0     # orçamento da animação (senão, PNG) e limite de tudo
POSTER_P = 0.19                     # o instante do PNG: a câmera já virou um pouco (dá para ver que é 3D)
SS = 2                              # a geometria é desenhada em 2× e reduzida (bordas suaves)
FAMILIES = {"processo": "Processo", "sistema": "Sistema", "estrutura": "Estrutura", "comparacao": "Comparação",
            "conceitos": "Conceitos"}
ROLES = ("item", "step", "layer", "a", "b")
LINK_KINDS = (*RELATIONS, "hub", "sequencia")
MAX_NODES, MAX_LINKS, MAX_LABEL, MAX_TITLE, MAX_EVIDENCE = 7, 12, 52, 90, 24
_KEYS = {"v", "family", "concept", "title", "nodes", "links", "evidence", "more"}
_REF = re.compile(r"^(title|mind_map\.center|mind_map\.branches\[\d{1,2}\](\.children\[\d{1,2}\])?|steps\[\d{1,2}\]|"
                  r"relations\[\d{1,2}\]|topics\[\d{1,2}\])$")
_LID = re.compile(r"^lm-[0-9a-f]{16}$")
_LOCK = threading.Lock()            # uma renderização por vez (o resto do Lumen também usa a CPU e a memória)

BG_IN, BG_OUT = (12, 21, 44), (3, 5, 13)
CYAN, ICE, VIOLET, AMBER, GRID = (86, 204, 255), (214, 240, 255), (172, 142, 255), (255, 196, 92), (52, 120, 190)
INK, MUTED, DIM = (226, 238, 255), (150, 174, 212), (104, 124, 160)


# --- especificação --------------------------------------------------------------------------------------------------

def _text(s, n=MAX_LABEL):
    """Rótulo seguro para desenhar: letras, números, pontuação e alguns sinais (sem emoji nem controle), espaços
    simples, cortado numa palavra com reticências."""
    keep = []
    for ch in unicodedata.normalize("NFC", str(s or "")):
        cat = unicodedata.category(ch)
        if cat[0] in "LNP" or cat == "Sm" or ch in "°&":  # Sm: sinais de matemática (→, ≤, ∑, +, =)
            keep.append(ch)
        elif cat[0] in "ZC" or cat == "So":
            keep.append(" ")
    t = " ".join("".join(keep).split()).strip(" -–—·:;,")
    if len(t) > n:
        cut = t[:n - 1]
        t = (cut.rsplit(" ", 1)[0] if " " in cut[n // 2:] else cut).rstrip(" ,.;:-–") + "…"
    return t


def spec(pkg):
    """A especificação do visual, só com o que o material diz (sem IA): a família pela forma do conteúdo, os rótulos
    e as relações. None se não houver o que mostrar."""
    lesson = pkg.get("lesson") or {}
    m = pkg.get("map") or {}
    if not m.get("branches"):  # pacote antigo sem o mapa guardado
        from .mindmap import data
        m = data(lesson)
    title = _text(lesson.get("title"), MAX_TITLE)
    center = _text(m.get("center") or lesson.get("title"), 40)
    branches = [(i, _text(b.get("label")), b) for i, b in enumerate(m.get("branches") or [])
                if isinstance(b, dict) and _text(b.get("label"))]
    steps = [(i, _text(s)) for i, s in enumerate(lesson.get("steps") or []) if isinstance(s, str) and _text(s)]
    rels = [(i, r) for i, r in enumerate(lesson.get("relations") or [])
            if isinstance(r, dict) and r.get("type") in RELATIONS]
    kind = lesson.get("map_kind")
    top = {norm(m.get("center") or lesson.get("title")): -1,
           **{norm(b["label"]): k for k, (_, _, b) in enumerate(branches)}}
    pos = lambda x: top.get(norm(x))  # noqa: E731 — compara a origem inteira, antes de abreviar o rótulo
    contrast = next(((i, r) for i, r in rels if r["type"] == "contrasta com" and pos(r["from"]) is not None
                     and pos(r["to"]) is not None and pos(r["from"]) != pos(r["to"])), None)
    whole = "mind_map.center" if m.get("center") else "title"
    if contrast:
        family = "comparacao"
    elif kind == "tutorial" and len(steps) >= 3:
        family = "processo"
    elif kind == "sistema" and len(branches) >= 2:
        family = "sistema"
    elif len(branches) >= 2 and (kind == "livro" or sum(r["type"] == "parte de" for _, r in rels) >= 2):
        family = "estrutura"
    elif len(steps) >= 3:
        family = "processo"
    else:
        family = "conceitos"
    nodes, links, ev, more = [], [], [whole], 0
    if family == "processo":
        shown = steps[:6]
        nodes = [{"label": lab, "role": "step", "sub": 0} for _, lab in shown]
        links = [{"a": k, "b": k + 1, "kind": "sequencia"} for k in range(len(shown) - 1)]
        ev += [f"steps[{i}]" for i, _ in shown]
        more = len(steps) - len(shown)
    elif family == "comparacao":
        i, r = contrast
        sides = []
        for end, role in ((r["from"], "a"), (r["to"], "b")):
            k = pos(end)
            if k == -1:
                sides.append((center, role, [], whole))
            else:
                j, lab, b = branches[k]
                kids = [(c, _text(x, 36)) for c, x in enumerate(b.get("children") or []) if isinstance(x, str) and _text(x, 36)]
                sides.append((lab, role, kids[:2], f"mind_map.branches[{j}]"))
                ev += [f"mind_map.branches[{j}].children[{c}]" for c, _ in kids[:2]]
        for lab, role, _, ref in sides:
            nodes.append({"label": lab, "role": role, "sub": 0})
            ev.append(ref)
        links.append({"a": 0, "b": 1, "kind": "contrasta com"})
        for (_, role, kids, _) in sides:
            parent = 0 if role == "a" else 1
            for _, lab in kids:
                nodes.append({"label": lab, "role": role, "sub": 0})
                links.append({"a": parent, "b": len(nodes) - 1, "kind": "hub"})
        ev.append(f"relations[{i}]")
    else:
        cap = 5 if family == "estrutura" else MAX_NODES
        shown = branches[:cap]
        role = "layer" if family == "estrutura" else "item"
        nodes = [{"label": lab, "role": role, "sub": min(len([x for x in b.get("children") or [] if isinstance(x, str)]), 4)}
                 for _, lab, b in shown]
        ev += [f"mind_map.branches[{j}]" for j, _, _ in shown]
        more = len(branches) - len(shown)
        if family != "estrutura":
            links = [{"a": -1, "b": k, "kind": "hub"} for k in range(len(nodes))]
            seen = set()
            for i, r in rels:
                a, b = pos(r["from"]), pos(r["to"])
                if a is None or b is None or a == b or max(a, b) >= len(nodes) or (a, b) in seen:
                    continue
                seen |= {(a, b), (b, a)}
                links = [x for x in links if {x["a"], x["b"]} != {a, b}]  # a relação da aula no lugar da ligação ao centro
                links.append({"a": a, "b": b, "kind": r["type"]})
                ev.append(f"relations[{i}]")
        else:
            ev += [f"relations[{i}]" for i, r in rels if r["type"] == "parte de"][:6]
        if not nodes and lesson.get("topics"):  # sem mapa: os tópicos (o pacote sempre tem ao menos um)
            topics = [(i, _text(t.get("title"))) for i, t in enumerate(lesson["topics"]) if isinstance(t, dict)]
            topics = [(i, lab) for i, lab in topics if lab][:MAX_NODES]
            nodes = [{"label": lab, "role": "item", "sub": 0} for _, lab in topics]
            links = [{"a": -1, "b": k, "kind": "hub"} for k in range(len(nodes))]
            ev += [f"topics[{i}]" for i, _ in topics]
            family = "conceitos"
    if not nodes:
        return None
    return {"v": 1, "family": family, "concept": center, "title": title or center, "nodes": nodes,
            "links": links[:MAX_LINKS], "evidence": list(dict.fromkeys(ev))[:MAX_EVIDENCE], "more": max(more, 0)}


def validate(s):
    """A spec antes de virar cena: só os campos, tipos, quantidades e valores aceitos. Qualquer outra coisa (campo a
    mais, texto longo, relação desconhecida, índice fora, número estranho) → ValueError, e não há visual."""
    def need(ok, what):
        if not ok:
            raise ValueError(what)

    def label(v, n):
        need(isinstance(v, str) and 0 < len(v) <= n and v == _text(v, n), "rótulo inválido")
    need(isinstance(s, dict) and set(s) == _KEYS, "campos da especificação")
    need(s["v"] == 1 and type(s["v"]) is int, "versão")
    need(s["family"] in FAMILIES, "família")
    label(s["concept"], 40)
    label(s["title"], MAX_TITLE)
    nodes, links = s["nodes"], s["links"]
    need(isinstance(nodes, list) and 1 <= len(nodes) <= MAX_NODES, "quantidade de elementos")
    for n in nodes:
        need(isinstance(n, dict) and set(n) == {"label", "role", "sub"}, "elemento")
        label(n["label"], MAX_LABEL)
        need(n["role"] in ROLES, "papel do elemento")
        need(type(n["sub"]) is int and 0 <= n["sub"] <= 4, "detalhes do elemento")
    need(isinstance(links, list) and len(links) <= MAX_LINKS, "quantidade de ligações")
    for x in links:
        need(isinstance(x, dict) and set(x) == {"a", "b", "kind"}, "ligação")
        need(all(type(x[k]) is int and -1 <= x[k] < len(nodes) for k in "ab") and x["a"] != x["b"], "ponta da ligação")
        need(x["kind"] in LINK_KINDS, "tipo de ligação")
    need(isinstance(s["evidence"], list) and 1 <= len(s["evidence"]) <= MAX_EVIDENCE
         and all(isinstance(e, str) and _REF.match(e) for e in s["evidence"]), "origem no material")
    need(type(s["more"]) is int and 0 <= s["more"] <= 50, "elementos de fora")
    roles = {n["role"] for n in nodes}
    fam = s["family"]
    need({"processo": roles == {"step"} and len(nodes) >= 2, "estrutura": roles == {"layer"} and len(nodes) <= 5,
          "comparacao": roles == {"a", "b"} and nodes[0]["role"] == "a" and nodes[1]["role"] == "b",
          }.get(fam, roles == {"item"}), "elementos da família")
    return s


def spec_hash(s, mode):
    raw = json.dumps([s, RENDERER, mode, W, H, FPS, FRAMES, MAX_GIF], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


WHAT = {"processo": ("etapa", "etapas"), "sistema": ("componente", "componentes"), "estrutura": ("parte", "partes"),
        "comparacao": ("elemento", "elementos"), "conceitos": ("conceito", "conceitos")}


def describe(s, origin="da aula"):
    """“Processo · 5 etapas da aula”: o que a cena mostra, para o subtítulo e as legendas. origin: de onde veio
    ("das suas notas", no diagrama dos Estudos)."""
    fam, n = s["family"], len(s["nodes"])
    if fam == "comparacao":
        return f"Comparação · {s['nodes'][0]['label']} × {s['nodes'][1]['label']}"
    one, many = WHAT[fam]
    out = f"{FAMILIES[fam]} · {n} {one if n == 1 else many} {origin}"
    rel = sum(1 for x in s["links"] if x["kind"] not in ("hub", "sequencia"))
    if rel:
        out += f" e {rel} {'relação' if rel == 1 else 'relações'}"
    return out + (f" (+{s['more']} fora da imagem)" if s["more"] else "")


# --- cena -----------------------------------------------------------------------------------------------------------

def _shape(kind):
    """Vértices e faces (índices) de cada forma, com raio ~1. A simetria em torno do eixo vertical diz quanto a
    peça gira por volta do laço sem dar salto no recomeço."""
    if kind == "ico":
        a = [2 * math.pi * k / 5 for k in range(5)]
        V = [(0, 1, 0)] + [(0.894 * math.cos(t), 0.447, 0.894 * math.sin(t)) for t in a] + \
            [(0.894 * math.cos(t + math.pi / 5), -0.447, 0.894 * math.sin(t + math.pi / 5)) for t in a] + [(0, -1, 0)]
        F = [(0, 1 + k, 1 + (k + 1) % 5) for k in range(5)] + [(11, 6 + (k + 1) % 5, 6 + k) for k in range(5)]
        F += [(1 + k, 6 + k, 1 + (k + 1) % 5) for k in range(5)] + [(1 + (k + 1) % 5, 6 + k, 6 + (k + 1) % 5) for k in range(5)]
        return np.array(V, float), F, 5
    if kind == "oct":
        V = [(1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, 0, -1), (0, 1, 0), (0, -1, 0)]
        F = [(4, k, (k + 1) % 4) for k in range(4)] + [(5, (k + 1) % 4, k) for k in range(4)]
        return np.array(V, float), F, 4
    if kind == "cube":
        V = [(x, y, z) for y in (-0.72, 0.72) for x, z in ((-0.72, -0.72), (0.72, -0.72), (0.72, 0.72), (-0.72, 0.72))]
        F = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        return np.array(V, float), F, 4
    sides, h = (6, 0.2) if kind == "hex" else (8, 0.05)  # hex: plataforma de uma etapa; plate: camada
    a = [2 * math.pi * k / sides + math.pi / sides for k in range(sides)]
    V = [(math.cos(t), y, math.sin(t)) for y in (-h, h) for t in a]
    F = [tuple(range(sides - 1, -1, -1)), tuple(range(sides, 2 * sides))]
    F += [(k, (k + 1) % sides, sides + (k + 1) % sides, sides + k) for k in range(sides)]
    return np.array(V, float), F, sides


SHAPES = {k: _shape(k) for k in ("ico", "oct", "cube", "hex", "plate")}


def _rot(yaw, tilt=0.0):
    cy, sy, ct, st = math.cos(yaw), math.sin(yaw), math.cos(tilt), math.sin(tilt)
    return np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]])


def _bezier(a, b, lift):
    a, b = np.asarray(a, float), np.asarray(b, float)
    mid = (a + b) / 2 + np.array([0, lift, 0])
    t = np.linspace(0, 1, 40)[:, None]
    return (1 - t) ** 2 * a + 2 * (1 - t) * t * mid + t ** 2 * b


def _spline(pts, per=14):
    """Catmull-Rom pelos pontos (o caminho das etapas)."""
    P = np.asarray(pts, float)
    P = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, per, endpoint=False):
            out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return np.array(out + [P[-2]])


def _spread(options, radius, fixed, cam):
    """Entre arranjos possíveis, o que deixa os elementos mais separados na tela durante todo o laço: a menor folga
    entre dois deles (a distância menos o tamanho de cada um na tela), em todos os instantes, é a maior.
    fixed: [(posição, raio)] que não mudam (o núcleo)."""
    cams = [_Cam(cam, p, W, H) for p in (0.0, 0.25, 0.5, 0.75)]

    def score(P):
        pts = list(P) + [q for q, _ in fixed]
        rad = np.array([radius] * len(P) + [r for _, r in fixed])
        worst = math.inf
        for c in cams:
            xy, z = c.project(pts)
            rr = rad * c.F / z
            d = np.linalg.norm(xy[:, None] - xy[None], axis=2) - rr[:, None] - rr[None] + np.eye(len(pts)) * 1e9
            worst = min(worst, float(d.min()))
        return worst
    return max(options, key=score)


def _scene(s):
    """A cena da família: objetos (forma, posição, raio, cor), caminhos (pontos 3D, estilo), rótulos (âncora 3D) e
    a câmera. Tudo parado no mundo; o movimento vem da câmera, dos giros e dos pulsos (laço de 1 volta)."""
    fam, nodes, links = s["family"], s["nodes"], s["links"]
    n = len(nodes)
    objs, paths, labels = [], [], []
    cam = {"target": (0.0, 1.35, 0.0), "dist": 10.6, "az": 0.52, "el": 0.30, "amp": 0.24}
    pos = {}
    if fam in ("conceitos", "sistema"):
        core = (0.0, 1.55, 0.0)
        pos[-1] = core
        objs.append({"shape": "ico", "pos": core, "r": 0.62 if fam == "conceitos" else 0.5, "color": CYAN, "core": True})
        labels.append({"at": (0.0, 1.55 + (0.62 if fam == "conceitos" else 0.5) + 0.12, 0.0), "lines": [s["concept"]],
                       "kind": "center", "of": len(objs) - 1})
        R = 3.3 if n > 3 else 2.7
        ring = lambda t0, h, d: [(R * math.cos(t), 1.45 + h * math.sin(2 * t + 0.8), R * d * math.sin(t))  # noqa: E731
                                 for t in (t0 + 2 * math.pi * k / n for k in range(n))]
        r_core = 0.62 if fam == "conceitos" else 0.5
        spots = _spread([ring(-math.pi / 2 + j * 2 * math.pi / n / 16, h, d) for j in range(16)
                         for h in (0.45, 0.75) for d in (0.5, 0.65)], 0.36, [(core, r_core * 1.1)], cam)
        for k, nd in enumerate(nodes):
            p = spots[k]
            pos[k] = p
            objs.append({"shape": "oct" if fam == "conceitos" else "cube", "pos": p, "r": 0.34 if fam == "conceitos" else 0.3,
                         "color": CYAN if fam == "conceitos" else ICE, "sub": nd["sub"], "spin": 1 if k % 2 else -1})
            labels.append({"at": p, "lines": [nd["label"]], "kind": "item", "of": len(objs) - 1})
    elif fam == "processo":
        cam.update(target=(0.0, 1.05, 0.0), az=-0.42, el=0.36, amp=0.2, dist=10.9)
        for k, nd in enumerate(nodes):
            u = k / max(n - 1, 1)
            p = (-3.1 + 6.2 * u, 0.42 + 1.25 * u, 1.25 - 2.5 * u + 0.45 * math.sin(math.pi * u))
            pos[k] = p
            objs.append({"shape": "hex", "pos": p, "r": 0.44, "color": CYAN, "step": k, "spin": 1})
            labels.append({"at": (p[0], p[1] + 0.12, p[2]), "lines": [nd["label"]], "num": str(k + 1), "kind": "item",
                           "of": len(objs) - 1})
        top = [(x, y + 0.24, z) for x, y, z in (pos[k] for k in range(n))]
        paths.append({"pts": _spline(top), "style": "seq", "pulses": 3})
        for k in range(n):  # o pilar de cada plataforma até o chão: a altura de cada etapa fica visível
            x, y, z = pos[k]
            paths.append({"pts": np.array([(x, 0.0, z), (x, y - 0.2, z)]), "style": "pillar"})
    elif fam == "estrutura":
        cam.update(target=(0.0, 1.5, 0.0), az=0.62, el=0.42, amp=0.26, dist=10.2)
        for k, nd in enumerate(nodes):
            p = (0.0, 2.95 - k * (2.5 / max(n - 1, 1)) if n > 1 else 1.6, 0.0)
            pos[k] = p
            r = 0.95 + 0.6 * (k / max(n - 1, 1)) if n > 1 else 1.3
            objs.append({"shape": "plate", "pos": p, "r": r, "color": CYAN if k % 2 == 0 else ICE, "layer": k,
                         "sub": nd["sub"], "spin": 1 if k % 2 else -1})
            labels.append({"at": (r * 0.92, p[1], r * 0.38), "lines": [nd["label"]], "kind": "item", "of": len(objs) - 1})
        paths.append({"pts": np.array([(0, 0.0, 0), (0, 3.45, 0)]), "style": "axis"})
        labels.append({"at": (0.0, 3.5, 0.0), "lines": [s["concept"]], "kind": "center", "of": None})
    else:  # comparacao: dois lados de um plano
        cam.update(target=(0.0, 1.35, 0.0), az=0.36, el=0.27, amp=0.25, dist=10.4)
        side = {"a": [], "b": []}
        for k, nd in enumerate(nodes):
            side[nd["role"]].append(k)
        for role, x0, col in (("a", -2.35, CYAN), ("b", 2.35, VIOLET)):
            for j, k in enumerate(side[role]):
                main = j == 0
                p = (x0, 1.95, 0.0) if main else (x0 + (0.35 if role == "a" else -0.35), 0.82, 0.95 * (1 if j == 1 else -1))
                pos[k] = p
                objs.append({"shape": "ico" if main else "oct", "pos": p, "r": 0.52 if main else 0.24, "color": col,
                             "spin": 1 if role == "a" else -1})
                labels.append({"at": p, "lines": [nodes[k]["label"]], "kind": "center" if main else "item",
                               "of": len(objs) - 1, "role": role})
        paths.append({"pts": None, "style": "divider"})
    for x in links:
        a, b = pos.get(x["a"]), pos.get(x["b"])
        if a is None or b is None or x["kind"] == "sequencia":
            continue
        if x["kind"] == "hub":
            paths.append({"pts": np.linspace(a, b, 12), "style": "hub", "ends": (x["a"], x["b"])})
            continue
        lift = 1.25 if fam == "comparacao" else 0.55 + 0.12 * float(np.linalg.norm(np.subtract(a, b)))
        pts = _bezier(a, b, lift)
        paths.append({"pts": pts, "style": "rel", "pulses": 2 if fam == "comparacao" else 1,
                      "both": x["kind"] == "contrasta com"})
        labels.append({"at": tuple(pts[len(pts) // 2]), "lines": [x["kind"]], "kind": "rel", "of": None})
    return {"family": fam, "objs": objs, "paths": paths, "labels": labels, "cam": cam, "pos": pos, "n": n}


# --- câmera e desenho -----------------------------------------------------------------------------------------------

class _Cam:
    def __init__(self, c, p, w, h):
        az = c["az"] + c["amp"] * math.sin(2 * math.pi * p)
        el = c["el"] + 0.035 * math.sin(2 * math.pi * p + math.pi / 3)
        t = np.array(c["target"], float)
        self.dist = c["dist"]
        self.eye = t + self.dist * np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)])
        f = t - self.eye
        f /= np.linalg.norm(f)
        r = np.cross(f, (0, 1, 0))
        r /= np.linalg.norm(r)
        self.R = np.stack([r, np.cross(r, f), f])
        self.F = (h / 2) / math.tan(math.radians(17))
        self.cx, self.cy = w * 0.54, h * 0.57

    def project(self, P):
        d = (np.asarray(P, float).reshape(-1, 3) - self.eye) @ self.R.T
        z = np.maximum(d[:, 2], 1e-3)
        return np.stack([self.cx + self.F * d[:, 0] / z, self.cy - self.F * d[:, 1] / z], 1), z

    def depth(self, p):
        return float((np.asarray(p, float) - self.eye) @ self.R[2])


def _mix(a, b, t):
    t = min(max(t, 0.0), 1.0)
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _fade(cam, z):
    """Mais perto, mais forte; mais longe, mais apagado (profundidade)."""
    return min(max(1.16 - (z - (cam.dist - 3.6)) / 7.2 * 0.66, 0.42), 1.12)


_BG = {}


def _background(w, h):
    if (w, h) not in _BG:
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt(((x - w * 0.55) / (w * 0.62)) ** 2 + ((y - h * 0.6) / (h * 0.72)) ** 2)
        t = np.clip(d, 0, 1)[..., None] ** 1.35
        _BG[(w, h)] = (np.array(BG_IN, np.float32) * (1 - t) + np.array(BG_OUT, np.float32) * t)
    return _BG[(w, h)]


def _floor(dr, cam, S, u, p, extent):
    """O projetor: chão em grade que some com a distância, anéis concêntricos, um anel tracejado que gira e o brilho
    do emissor no centro."""
    R = extent
    lines = []
    for v in np.arange(-R * 1.5, R * 1.5 + 1e-6, 0.8):
        lines += [np.array([(v, 0, w) for w in np.linspace(-R * 1.5, R * 1.5, 16)]),
                  np.array([(w, 0, v) for w in np.linspace(-R * 1.5, R * 1.5, 16)])]
    for L in lines:
        xy, z = cam.project(L)
        for i in range(len(L) - 1):
            d = float(np.linalg.norm((L[i] + L[i + 1]) / 2))
            a = max(0.0, 1 - d / (R * 1.45)) ** 2 * _fade(cam, (z[i] + z[i + 1]) / 2)
            if a > 0.02:
                dr.line([tuple(xy[i] * S), tuple(xy[i + 1] * S)], fill=_mix(BG_IN, GRID, 0.55 * a), width=max(1, round(1.2 * S * u)))
    for r, k in ((0.7, 0.75), (R * 0.55, 0.5), (R, 0.62)):
        ring = np.array([(r * math.cos(t), 0, r * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 97)])
        xy, z = cam.project(ring)
        for i in range(96):
            dr.line([tuple(xy[i] * S), tuple(xy[i + 1] * S)], fill=_mix(BG_IN, CYAN, k * _fade(cam, z[i])),
                    width=max(1, round(1.6 * S * u)))
    rr = R * 0.8  # anel tracejado: 16 traços; uma volta de 1/16 por laço não dá salto
    for j in range(16):
        t0 = 2 * math.pi * (j + p) / 16
        arc = np.array([(rr * math.cos(t), 0, rr * math.sin(t)) for t in np.linspace(t0, t0 + 0.24, 6)])
        xy, z = cam.project(arc)
        dr.line([tuple(q * S) for q in xy], fill=_mix(BG_IN, ICE, 0.7 * _fade(cam, float(z.mean()))),
                width=max(1, round(2.4 * S * u)))
    for r, a in ((1.25, 26), (0.75, 40), (0.38, 60)):
        disc = np.array([(r * math.cos(t), 0, r * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 40)])
        xy, _ = cam.project(disc)
        dr.polygon([tuple(q * S) for q in xy], fill=(*CYAN, a))


def _poly_items(cam, o, p, S, u, active):
    """Um objeto como uma unidade (convexo): faces de trás, arestas de trás, faces da frente, arestas da frente."""
    V, faces, sym = SHAPES[o["shape"]]
    yaw = 2 * math.pi * p / sym * o.get("spin", 1) * (2 if o.get("core") else 1)
    tilt = 0.32 if o["shape"] in ("ico", "oct", "cube") else 0.0
    P = (V * o["r"]) @ _rot(yaw, tilt).T + np.array(o["pos"])
    xy, z = cam.project(P)
    xy = xy * S
    k = _fade(cam, cam.depth(o["pos"]))
    col = AMBER if active else o["color"]
    persp = cam.dist / max(cam.depth(o["pos"]), 1e-3)
    back, front, edges = [], [], {}
    for f in faces:
        Q = P[list(f)]
        c = Q.mean(0)
        nrm = np.cross(Q[1] - Q[0], Q[2] - Q[0])
        nrm /= np.linalg.norm(nrm) + 1e-9
        if np.dot(nrm, c - np.array(o["pos"])) < 0:
            nrm = -nrm
        v = cam.eye - c
        facing = float(np.dot(nrm, v) / np.linalg.norm(v))
        (front if facing > 0 else back).append((f, facing))
        for i in range(len(f)):
            e = tuple(sorted((f[i], f[(i + 1) % len(f)])))
            edges[e] = edges.get(e, False) or facing > 0
    pts = lambda f: [tuple(xy[i]) for i in f]  # noqa: E731

    def draw(dr):
        for f, _ in back:
            dr.polygon(pts(f), fill=(*_mix(BG_IN, col, 0.16 * k), int(60 * k)))
        for (i, j), fr in edges.items():
            if not fr:
                dr.line([tuple(xy[i]), tuple(xy[j])], fill=_mix(BG_IN, col, 0.36 * k), width=max(1, round(1.3 * S * u * persp)))
        for f, facing in front:
            rim = (1 - facing) ** 1.6
            dr.polygon(pts(f), fill=(*_mix(BG_IN, col, (0.2 + 0.32 * rim) * k), int(70 + 105 * rim)))
        for (i, j), fr in edges.items():
            if fr:
                dr.line([tuple(xy[i]), tuple(xy[j])], fill=_mix(BG_IN, _mix(col, (255, 255, 255), 0.22), 0.95 * k),
                        width=max(1, round(2.3 * S * u * persp)))
        if o.get("core"):  # o núcleo: um brilho no meio, visto através das faces
            c = cam.project(o["pos"])[0][0] * S
            for r, a in ((26, 40), (14, 90), (6, 220)):
                rr = r * S * u * persp
                dr.ellipse([c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr], fill=(*ICE, a))
    return [(cam.depth(o["pos"]), draw)]


def _dot(dr, c, r, col, alpha=1.0):
    for k, a in ((3.2, 30), (2.0, 70), (1.15, 150), (0.6, 255)):
        rr = r * k
        dr.ellipse([c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr], fill=(*(col if k > 0.7 else (250, 252, 255)), int(a * alpha)))


def _along(pts, t):
    """O ponto a uma fração t do comprimento do caminho."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    acc = np.concatenate([[0], np.cumsum(seg)])
    d = t * acc[-1]
    i = min(int(np.searchsorted(acc, d, side="right")) - 1, len(seg) - 1)
    f = (d - acc[i]) / (seg[i] or 1)
    return pts[i] + (pts[i + 1] - pts[i]) * f


def _path_items(cam, sc, path, p, S, u):
    style, items = path["style"], []
    if style == "divider":  # comparação: o plano entre os dois lados, com uma linha de varredura que sobe
        quad = np.array([(0, 0.05, -1.9), (0, 0.05, 1.9), (0, 3.0, 1.9), (0, 3.0, -1.9)])
        xy, z = cam.project(quad)
        xy = xy * S
        k = _fade(cam, float(z.mean()))
        ys = [0.05 + 2.95 * j / 9 for j in range(10)]
        scan = 0.05 + 2.95 * ((p * 2) % 1)

        def draw(dr):
            dr.polygon([tuple(q) for q in xy], fill=(*_mix(BG_IN, ICE, 0.25 * k), 46))
            for y in ys + [scan]:
                q, _ = cam.project(np.array([(0, y, -1.9), (0, y, 1.9)]))
                bright = y == scan
                dr.line([tuple(q[0] * S), tuple(q[1] * S)], fill=_mix(BG_IN, ICE if bright else CYAN, (0.85 if bright else 0.3) * k),
                        width=max(1, round((2.2 if bright else 1.1) * S * u)))
            for i in range(4):
                dr.line([tuple(xy[i]), tuple(xy[(i + 1) % 4])], fill=_mix(BG_IN, ICE, 0.7 * k), width=max(1, round(1.8 * S * u)))
        return [(float(z.mean()), draw)]
    P = path["pts"]
    xy, z = cam.project(P)
    xy = xy * S
    col, width, k_all = {"seq": (CYAN, 3.4, 1.0), "rel": (VIOLET, 2.6, 1.0), "hub": (CYAN, 1.4, 0.42),
                         "pillar": (CYAN, 1.3, 0.38), "axis": (ICE, 1.4, 0.4)}[style]
    step = 2 if style == "hub" else 1  # a ligação ao centro tracejada: é do mapa, não uma relação da aula
    chunk = 4
    for i in range(0, len(P) - 1, chunk):
        j = min(i + chunk, len(P) - 1)
        if style == "hub" and (i // chunk) % step:
            continue
        zz = float(z[i:j + 1].mean())
        k = _fade(cam, zz) * k_all
        seg = [tuple(q) for q in xy[i:j + 1]]
        wpx = max(1, round(width * S * u * cam.dist / zz))

        def draw(dr, seg=seg, k=k, wpx=wpx):
            dr.line(seg, fill=_mix(BG_IN, col, k), width=wpx, joint="curve")
            for q in (seg[0], seg[-1]):
                r = wpx / 2
                dr.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=_mix(BG_IN, col, k))
        items.append((zz, draw))
    for j in range(path.get("pulses", 0)):
        for back in ((False, True) if path.get("both") else (False,)):
            t = (p + j / path["pulses"]) % 1
            q = _along(P, 1 - t if back else t)
            c, zq = cam.project(q)
            zq = float(zq[0])
            items.append((zq - 0.01, lambda dr, c=c[0] * S, zq=zq: _dot(dr, c, 3.1 * S * u * cam.dist / zq,
                                                                         AMBER if style == "seq" else ICE)))
    return items


def _sub_items(cam, o, p, S, u):
    """Os detalhes de um elemento (quantos filhos ele tem no mapa): pontos que giram em volta dele."""
    n = o.get("sub") or 0
    if not n:
        return []
    out, r = [], o["r"] * (2.1 if o["shape"] != "plate" else 1.0)
    for j in range(n):
        t = 2 * math.pi * (j + p) / n
        q = np.array(o["pos"]) + (np.array([r * math.cos(t), 0.18 * math.sin(t), r * math.sin(t)])
                                  if o["shape"] != "plate" else np.array([r * math.cos(t), 0.0, r * math.sin(t)]))
        c, zq = cam.project(q)
        zq = float(zq[0])
        out.append((zq, lambda dr, c=c[0] * S, zq=zq: _dot(dr, c, 2.0 * S * u * cam.dist / zq, CYAN, 0.9)))
    return out


# --- textos ---------------------------------------------------------------------------------------------------------

FONT_DIR = Path(__file__).resolve().parent / "web" / "fonts"
FONT_FILES = [FONT_DIR / "inter-latin.woff2", FONT_DIR / "inter-latin-ext.woff2",
              Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "SegUIVar.ttf",
              Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"]
_FONTS, _MISSING = {}, {}


def _load(path, size, weight):
    key = (str(path), size, weight)
    if key not in _FONTS:
        from PIL import ImageFont
        f = ImageFont.truetype(str(path), size)
        try:
            axes = f.get_variation_axes()
            f.set_variation_by_axes([weight if a.get("name") in (b"Weight", "Weight") else a["default"] for a in axes])
        except (OSError, AttributeError):
            pass  # fonte sem eixos (peso fixo)
        _FONTS[key] = f
    return _FONTS[key]


def _font(text, size, weight=400):
    """A primeira fonte da lista que tem todos os caracteres do texto (a Inter do projeto; no Windows, a Segoe UI
    para letras gregas, setas e outros símbolos)."""
    size = max(8, int(round(size)))
    best, lost = None, None
    for path in FONT_FILES:
        if not path.is_file():
            continue
        f = _load(path, size, weight)
        miss = _MISSING.setdefault(str(path), bytes(_load(path, 24, 400).getmask("\U0010fffd")))
        probe = _load(path, 24, 400)
        n = sum(1 for ch in set(text) if not ch.isspace() and bytes(probe.getmask(ch)) == miss)
        if not n:
            return f
        if lost is None or n < lost:  # nenhuma fonte tem tudo: a que perde menos (os que faltam saem em _drawable)
            best, lost = f, n
    if best is None:
        from PIL import ImageFont
        return ImageFont.load_default(size)
    return best


def _drawable(text, f):
    """O texto só com o que a fonte escolhida desenha. O caractere sem glifo (ℏ, expoentes e subscritos raros) vira o seu
    equivalente de compatibilidade (⁴ → 4, ℏ → ħ) ou sai, em vez de aparecer como um quadrado no rótulo."""
    miss = bytes(f.getmask("\U0010fffd"))
    ok = lambda c: c.isspace() or bytes(f.getmask(c)) != miss  # noqa: E731
    out = []
    for ch in text:
        if ok(ch):
            out.append(ch)
        else:
            alt = unicodedata.normalize("NFKD", ch)
            out.append(alt if alt != ch and all(ok(c) for c in alt) else "")
    return " ".join("".join(out).split())


def _wrap(text, size, weight, width, lines=2):
    f = _font(text, size, weight)
    words, out, cur = _drawable(text, f).split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if not cur or f.getlength(t) <= width:
            cur = t
        else:
            out.append(cur)
            cur = w
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        last = out[-1]
        while last and f.getlength(last + "…") > width:
            last = last[:-1]
        out[-1] = last.rstrip(" ,.;:") + "…"
    for i, ln in enumerate(out):
        while len(ln) > 1 and f.getlength(ln) > width:
            ln = ln[:-2] + "…"
        out[i] = ln
    return out, f


# --- quadro ---------------------------------------------------------------------------------------------------------

def _layout(sc, w, h, u):
    """Onde cada rótulo fica em relação ao seu ponto: escolhido uma vez, olhando a cena em vários instantes, para
    os rótulos não se cobrirem nem cobrirem o título, e não pularem de um quadro para outro."""
    samples = [_Cam(sc["cam"], p, w, h) for p in (0.0, 0.25, 0.5, 0.75)]
    placed, out = [(0, 0, 560 * u, 128 * u)], {}  # o título no canto de cima
    order = sorted(range(len(sc["labels"])), key=lambda i: {"center": 0, "item": 1, "rel": 2}[sc["labels"][i]["kind"]])
    for i in order:
        lab = sc["labels"][i]
        size = (20 if lab["kind"] == "center" else 14 if lab["kind"] == "rel" else 18) * u
        weight = 650 if lab["kind"] == "center" else 520
        lines, f = _wrap(lab["lines"][0], size, weight, (250 if lab["kind"] != "rel" else 150) * u)
        num = 26 * u if lab.get("num") else 0
        tw = max(f.getlength(ln) for ln in lines) + num
        pw, ph = tw + 22 * u, len(lines) * size * 1.28 + 14 * u
        anchors = [c.project(lab["at"])[0][0] for c in samples]
        r = 30 * u
        cands = ([(-pw / 2, -ph / 2)] if lab["kind"] == "rel" else
                 [(r, -ph / 2), (-r - pw, -ph / 2), (r * 0.6, -ph - r * 0.6), (-r * 0.6 - pw, -ph - r * 0.6),
                  (r * 0.6, r * 0.6), (-r * 0.6 - pw, r * 0.6), (-pw / 2, -ph - r), (-pw / 2, r)])
        if lab["kind"] == "center":  # o nome do todo logo acima (ou abaixo) do núcleo
            cands = cands[6:] + cands[:6]
        best, cost = None, None
        for n, (dx, dy) in enumerate(cands):
            c = n * 40 * u * u
            for a, cm in zip(anchors, samples):
                box = (a[0] + dx, a[1] + dy, a[0] + dx + pw, a[1] + dy + ph)
                c += sum(_overlap(box, b) for b in placed) * 4
                c += sum(_overlap(_lead(a, box, u), b) for b in placed[1:]) * 4  # a linha-guia não cruza outro rótulo
                c += max(0, 12 * u - box[0]) * 400 + max(0, box[2] - (w - 12 * u)) * 400
                c += max(0, 12 * u - box[1]) * 400 + max(0, box[3] - (h - 44 * u)) * 400
                for o in sc["objs"]:
                    q = cm.project(o["pos"])[0][0]
                    rr = o["r"] * cm.F / cm.dist * 1.2
                    c += _overlap(box, (q[0] - rr, q[1] - rr, q[0] + rr, q[1] + rr)) * 1.5
            if cost is None or c < cost:
                best, cost = (dx, dy), c
        if lab["kind"] == "rel" and cost > 900 * u * u:
            continue  # o nome da relação não cabe sem cobrir outro rótulo: a seta fica sem ele
        for a in anchors:
            box = (a[0] + best[0], a[1] + best[1], a[0] + best[0] + pw, a[1] + best[1] + ph)
            placed.append(box)
            if lab["kind"] != "rel":
                placed.append(_lead(a, box, u))
        out[i] = {"off": best, "size": size, "weight": weight, "lines": lines, "font": f, "pw": pw, "ph": ph, "num": num}
    # Se os rótulos não couberem junto das peças, duas colunas estáveis preservam a leitura durante todo o laço.
    crowded = False
    for p in [POSTER_P, *(k / 16 for k in range(16))]:
        cm, boxes = _Cam(sc["cam"], p, w, h), []
        for i, L in out.items():
            a = cm.project(sc["labels"][i]["at"])[0][0]
            x = min(max(a[0] + L["off"][0], 10 * u), w - 10 * u - L["pw"])
            y = min(max(a[1] + L["off"][1], 10 * u), h - 42 * u - L["ph"])
            box = (x, y, x + L["pw"], y + L["ph"])
            crowded |= any(_overlap(box, b) > 0 for b in boxes)
            boxes.append(box)
    if crowded:
        out, rows = {}, [0, 0]
        labels = [i for i, lab in enumerate(sc["labels"]) if lab["kind"] != "rel"]
        for k, i in enumerate(labels):
            lab = sc["labels"][i]
            size, weight = 16 * u, 520
            lines, f = _wrap(lab["lines"][0], size, weight, 210 * u, lines=3)
            pw, ph = 232 * u, len(lines) * size * 1.28 + 14 * u
            # as colunas se alternam; na comparação, cada rótulo fica na coluna do seu lado (A à esquerda, B à direita)
            col = (0 if lab["role"] == "a" else 1) if "role" in lab else k % 2
            row = rows[col] if "role" in lab else k // 2
            rows[col] += 1
            out[i] = {"fixed": ((18 if col == 0 else 710) * u, (150 + row * 84) * u),
                      "size": size, "weight": weight, "lines": lines, "font": f, "pw": pw, "ph": ph, "num": 0}
    return out


def _lead(a, box, u):
    """A caixa da linha-guia (do ponto até a placa), fina, para outros rótulos não a cobrirem."""
    cx, cy = min(max(a[0], box[0]), box[2]), min(max(a[1], box[1]), box[3])
    t = 3 * u
    return (min(a[0], cx) - t, min(a[1], cy) - t, max(a[0], cx) + t, max(a[1], cy) + t)


def _overlap(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _frame(sc, p, w, h, layout, static=False):
    from PIL import Image, ImageDraw, ImageFilter
    u, S = w / 960, SS
    cam = _Cam(sc["cam"], p, w, h)
    bg = _background(w * S, h * S)
    img = Image.fromarray(bg.astype(np.uint8))
    dr = ImageDraw.Draw(img, "RGBA")
    _floor(dr, cam, S, u, p, 3.0)
    n = sc["n"]
    active = int(p * n) % n if sc["family"] == "processo" else None
    items = []
    for o in sc["objs"]:
        items += _poly_items(cam, o, p, S, u, o.get("step") == active and active is not None)
        items += _sub_items(cam, o, p, S, u)
    for path in sc["paths"]:
        items += _path_items(cam, sc, path, p, S, u)
    for _, draw in sorted(items, key=lambda t: -t[0]):  # do fundo para a frente: o da frente cobre o de trás
        draw(dr)
    small = np.asarray(img.reduce(S), np.float32)
    base = _background(w, h)
    glow = np.clip(small - base, 0, 255).astype(np.uint8)
    g = Image.fromarray(glow)
    bloom = (np.asarray(g.filter(ImageFilter.GaussianBlur(4 * u)), np.float32) * 0.7
             + np.asarray(g.filter(ImageFilter.GaussianBlur(15 * u)), np.float32) * 0.55)
    ys = np.arange(h, dtype=np.float32)
    band = 0.4 * np.exp(-(((ys - (p * 1.25 - 0.1) * h) / (26 * u)) ** 2))  # a varredura do holograma, de cima a baixo
    out = small + bloom + glow * band[:, None, None]
    out[1::3] *= 0.9  # linhas de varredura
    fy = int(64 * u)  # o rodapé sobre uma faixa escura: o chão não passa por cima da autoria
    t = np.linspace(0, 1, fy, dtype=np.float32)[:, None, None] ** 1.4 * 0.88
    out[h - fy:] = out[h - fy:] * (1 - t) + base[h - fy:] * 0.6 * t
    frame = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    _texts(frame, sc, cam, layout, u, static)
    return np.asarray(frame)


def _texts(img, sc, cam, layout, u, static):
    from PIL import ImageDraw
    dr = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    spec_ = sc["spec"]
    labs = [(i, cam.depth(sc["labels"][i]["at"])) for i in layout]
    for i, z in sorted(labs, key=lambda t: -t[1]):  # o rótulo mais perto por cima
        lab, L = sc["labels"][i], layout[i]
        a = cam.project(lab["at"])[0][0]
        x, y = L["fixed"] if "fixed" in L else (a[0] + L["off"][0], a[1] + L["off"][1])
        x, y = min(max(x, 10 * u), w - 10 * u - L["pw"]), min(max(y, 10 * u), h - 42 * u - L["ph"])
        k = _fade(cam, z)
        edge = VIOLET if lab["kind"] == "rel" else CYAN
        if lab["kind"] != "rel":
            cx, cy = min(max(a[0], x), x + L["pw"]), min(max(a[1], y), y + L["ph"])
            dr.line([(a[0], a[1]), (cx, cy)], fill=(*edge, int(150 * k)), width=max(1, round(1.5 * u)))
            dr.ellipse([a[0] - 3 * u, a[1] - 3 * u, a[0] + 3 * u, a[1] + 3 * u], fill=(*ICE, int(230 * k)))
        dr.rounded_rectangle([x, y, x + L["pw"], y + L["ph"]], radius=8 * u, fill=(5, 11, 27, 205),
                             outline=(*edge, int(90 + 90 * min(k, 1))), width=max(1, round(1.2 * u)))
        tx = x + 11 * u
        if L["num"]:
            r = 10 * u
            cy = y + 7 * u + L["size"] * 0.64
            dr.ellipse([tx, cy - r, tx + 2 * r, cy + r], fill=(*CYAN, 60), outline=(*CYAN, 220), width=max(1, round(1.3 * u)))
            nf = _font(lab["num"], 13 * u, 700)
            dr.text((tx + r, cy), lab["num"], font=nf, fill=ICE, anchor="mm")
            tx += L["num"]
        for j, ln in enumerate(L["lines"]):
            dr.text((tx, y + 7 * u + j * L["size"] * 1.28), ln, font=L["font"], anchor="la",
                    fill=MUTED if lab["kind"] == "rel" else INK)
    # título, subtítulo e a autoria (parados: legíveis e baratos no GIF)
    eyebrow = "VISUALIZAÇÃO 3D · IMAGEM ESTÁTICA" if static else "VISUALIZAÇÃO 3D"
    ef = _font(eyebrow, 12.5 * u, 650)
    x0 = 30 * u
    dr.text((x0, 24 * u), eyebrow, font=ef, fill=CYAN, anchor="la")
    lines, tf = _wrap(spec_["title"], 26 * u, 640, 520 * u)
    for j, ln in enumerate(lines):
        dr.text((x0, 44 * u + j * 32 * u), ln, font=tf, fill=INK, anchor="la")
    sub, sf = _wrap(describe(spec_, sc.get("origin", "da aula")), 15 * u, 450, 900 * u, lines=1)
    dr.text((x0, 50 * u + len(lines) * 32 * u), sub[0], font=sf, fill=MUTED, anchor="la")
    foot = sc.get("foot") or f"Esquema gerado pelo Lumen a partir do material {sc.get('origin', 'da aula')}"
    ff = _font(foot, 12.5 * u, 450)
    dr.text((x0, h - 20 * u), foot, font=ff, fill=DIM, anchor="ls")
    lf = _font("Lumen", 13 * u, 650)
    dr.text((w - 30 * u, h - 20 * u), "Lumen", font=lf, fill=MUTED, anchor="rs")


# --- arquivos -------------------------------------------------------------------------------------------------------

def _gif_blocks(data):
    """(largura, altura, quadros, atrasos em centésimos, repetições) lidos da estrutura do GIF; ValueError se o
    arquivo não for um GIF inteiro."""
    try:
        if data[:6] not in (b"GIF87a", b"GIF89a"):
            raise ValueError("assinatura de GIF")
        w, h = struct.unpack("<HH", data[6:10])
        flags, i = data[10], 13
        if flags & 0x80:
            i += 3 * (2 << (flags & 7))
        frames, delays, delay, loop = 0, [], 0, None
        while True:
            b = data[i]
            if b == 0x3B:
                break
            if b == 0x21:
                label = data[i + 1]
                i += 2
                if label == 0xF9:
                    delay = data[i + 2] | data[i + 3] << 8
                elif label == 0xFF and data[i + 1:i + 12] == b"NETSCAPE2.0":
                    loop = data[i + 14] | data[i + 15] << 8
                while data[i]:
                    i += data[i] + 1
                i += 1
            elif b == 0x2C:
                fl = data[i + 9]
                i += 10
                if fl & 0x80:
                    i += 3 * (2 << (fl & 7))
                i += 1
                while data[i]:
                    i += data[i] + 1
                i += 1
                frames += 1
                delays.append(delay)
            else:
                raise ValueError("bloco desconhecido no GIF")
    except IndexError:
        raise ValueError("GIF incompleto") from None
    return w, h, frames, delays, loop


def inspect(data, kind, w=None, h=None, frames=None):
    """Confere o arquivo antes de entregar: assinatura e tipo, decodificação, tamanho, quadros, duração, peso,
    movimento de verdade e imagem não vazia. Devolve as medidas; ValueError com o motivo."""
    import av
    if kind not in ("gif", "png") or len(data) > (MAX_GIF if kind == "gif" else MAX_PNG):
        raise ValueError("tipo ou peso do arquivo")
    if kind == "gif":
        gw, gh, n, delays, loop = _gif_blocks(data)
        if not 2 <= n <= FRAMES or len(delays) != n or any(not 7 <= d <= 9 for d in delays):
            raise ValueError("quadros ou duração do GIF")
    else:
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ValueError("assinatura de PNG")
        gw, gh = struct.unpack(">II", data[16:24])
    if not (0 < gw <= 960 and 0 < gh <= 540 and gw * 9 == gh * 16):
        raise ValueError("dimensões fora do limite")
    if kind == "gif":
        gw, gh, n, delays, loop = _gif_blocks(data)
        with av.open(io.BytesIO(data), format="gif") as f:
            pics = [fr.to_ndarray(format="rgb24") for fr in f.decode(video=0)]
        if len(pics) != n or not n:
            raise ValueError("quadros do GIF")
        if loop != 0:
            raise ValueError("o GIF não repete")
        duration = sum(delays) * 10
        diffs = [float(np.abs(pics[i].astype(np.int16) - pics[i - 1]).mean()) for i in range(1, n)]
        if n < 2 or sum(d > 0.15 for d in diffs) < 0.6 * (n - 1) or \
                float(np.abs(pics[n // 2].astype(np.int16) - pics[0]).mean()) < 1.0:
            raise ValueError("o GIF não tem movimento")
        sample = pics[0]
        if len(data) > MAX_GIF:
            raise ValueError("GIF acima do peso")
        mime = "image/gif"
    elif kind == "png":
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("assinatura de PNG")
        gw, gh = struct.unpack(">II", data[16:24])
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            sample = np.asarray(im.convert("RGB"))
        n, duration, mime = 1, 0, "image/png"
        if len(data) > MAX_PNG:
            raise ValueError("PNG acima do peso")
    else:
        raise ValueError("tipo de arquivo")
    if sample.shape[:2] != (gh, gw) or (w and (gw, gh) != (w, h)) or (frames and n != frames):
        raise ValueError("dimensões")
    lum = sample.mean(axis=2)
    if lum.std() < 8 or float((lum > 70).mean()) < 0.01:
        raise ValueError("imagem vazia")
    return {"kind": kind, "mime": mime, "width": gw, "height": gh, "frames": n, "duration_ms": duration,
            "bytes": len(data)}


def _png(frame):
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    if len(data) > MAX_PNG:  # ainda grande: 256 cores (a cena é quase toda em tons de azul)
        buf = io.BytesIO()
        Image.fromarray(frame).quantize(256, dither=0).save(buf, "PNG", optimize=True)
        data = buf.getvalue()
    return data


class Timeout(Exception):
    pass


def render(s, mode, check=lambda: None, budget=BUDGET_S, limit=LIMIT_S, origin="da aula", foot=None):
    """{"png": bytes, "gif": bytes|None, "state", "reason", "render_s", medidas}. O PNG sai sempre (é a reserva e
    o modo estático). A animação desiste para o PNG se não couber no orçamento de tempo ou no peso. foot: a linha de
    autoria do rodapé quando "a partir do material <origin>" não descreve a origem (o holograma pedido no chat)."""
    from .charts import _gif
    t0 = time.monotonic()
    check()
    validate(s)
    sc = _scene(s)
    sc["spec"], sc["origin"], sc["foot"] = s, origin, foot
    lay = {}

    def frames_at(w, h, n):
        lay[(w, h)] = lay.get((w, h)) or _layout(sc, w, h, w / 960)
        out = []
        for k in range(n):
            check()
            spent = time.monotonic() - t0
            if spent > limit:
                raise Timeout
            if k == 3 and spent / 4 * n > budget:
                raise Timeout  # no ritmo destes primeiros quadros, a animação passaria do orçamento
            out.append(_frame(sc, k / n, w, h, lay[(w, h)]))
        return out
    png = _png(_frame(sc, POSTER_P, W, H, lay.setdefault((W, H), _layout(sc, W, H, 1.0)), static=True))
    info = inspect(png, "png", W, H)
    check()
    out = {"png": png, "png_info": info, "gif": None, "state": "ok", "reason": None}
    if mode == "animated":
        reason = "peso"
        try:
            for w, h, n in ATTEMPTS:
                frames = frames_at(w, h, n)
                for colors in (128, 96):  # 128 cores: igual a 256 a olho nu (conferido) e ~22% menor
                    gif = _gif(frames, FPS, -1, colors)
                    check()
                    if time.monotonic() - t0 > limit:
                        raise Timeout
                    if gif and len(gif) <= MAX_GIF:
                        out.update(gif=gif, gif_info=inspect(gif, "gif", w, h, n), colors=colors)
                        break
                if out["gif"]:
                    break
        except Timeout:
            reason = "tempo"
        except ValueError as e:  # conferência do GIF
            reason = str(e)
        if not out["gif"]:
            out.update(state="static-fallback", reason=reason)
    out["render_s"] = round(time.monotonic() - t0, 2)
    check()
    return out


class Busy(Exception):
    """Outra renderização do Lumen não terminou dentro do limite de espera."""


def make(s, mode, check=lambda: None, origin="da aula", foot=None):
    """render() com a mesma trava de prepare(): uma renderização por vez no Lumen. É o caminho de um visual que não pertence a
    uma aula (o holograma pedido no chat, study/holo.py): sem cache de aula, sem manifesto, sem tocar na configuração."""
    deadline = time.monotonic() + LIMIT_S
    while not _LOCK.acquire(timeout=min(0.1, max(0, deadline - time.monotonic()))):
        check()
        if time.monotonic() >= deadline:
            raise Busy
    try:
        return render(s, mode, check, origin=origin, foot=foot)
    finally:
        _LOCK.release()


# --- produção com cache ---------------------------------------------------------------------------------------------

def _folder(lid):
    if not _LID.match(str(lid)):
        raise ValueError("identificador da aula")
    return store.DATA / "visuals" / lid


def _atomic(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def record(asset, rec):
    """O que vai para o manifesto: sem os bytes."""
    return {k: v for k, v in {**rec, **(asset or {})}.items() if k not in ("data", "png_data")}


def prepare(pkg, mode, check=lambda: None, refresh=False):
    """(asset, registro): o visual pronto para os dois destinos (feito uma vez; tentar de novo um envio reaproveita o
    arquivo guardado) e o registro para o manifesto. Nunca levanta erro de desenho: sem visual, asset é None e o
    registro diz por quê (o texto da aula sai do mesmo jeito)."""
    if mode not in ("animated", "static"):
        return None, {"state": "off", "mode": "off"}
    check()
    try:
        s = validate(spec(pkg))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        log.info("visual 3D: sem especificação (%s)", type(e).__name__)
        return None, {"state": "skipped", "mode": mode, "reason": "material sem elementos para a cena"}
    h = spec_hash(s, mode)
    rec = {"spec_hash": h, "renderer": RENDERER, "mode": mode, "family": s["family"], "concept": s["concept"],
           "evidence": s["evidence"], "describe": describe(s)}
    folder = _folder(pkg["lumen_id"])
    meta = folder / f"{h}.json"
    deadline = time.monotonic() + LIMIT_S
    while not _LOCK.acquire(timeout=min(0.1, max(0, deadline - time.monotonic()))):
        check()
        if time.monotonic() >= deadline:
            return None, {**rec, "state": "failed", "reason": "outra visualização estava sendo desenhada"}
    try:
        check()
        try:
            with meta.open("rb") as f:
                raw = f.read(65537)
            if len(raw) > 65536:
                raise ValueError("manifesto grande demais")
            m = json.loads(raw)
            if refresh:
                raise ValueError("nova tentativa solicitada")
            fallback = mode == "animated" and m.get("state") == "static-fallback"
            kind = "gif" if mode == "animated" and not fallback else "png"
            if (m["spec_hash"], m["renderer"], m["mode"], m["kind"], m["state"], m["file"], m["png"]) != \
                    (h, RENDERER, mode, kind, "static-fallback" if fallback else "ok", f"{h}.{kind}", f"{h}.png"):
                raise ValueError("manifesto incompatível")
            with (folder / f"{h}.{kind}").open("rb") as f:
                data = f.read((MAX_GIF if kind == "gif" else MAX_PNG) + 1)
            with (folder / f"{h}.png").open("rb") as f:
                png = f.read(MAX_PNG + 1)
            if hashlib.sha256(data).hexdigest() != m["sha256"] or hashlib.sha256(png).hexdigest() != m["png_sha256"]:
                raise ValueError("arquivo alterado")
            info = inspect(data, kind, m["width"], m["height"], m["frames"])
            inspect(png, "png", W, H)
            check()
            return {**m, **rec, **info, "data": data, "png_data": png, "cached": True}, {**rec, "state": m["state"]}
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            pass  # cache ausente, antigo ou corrompido: refaz a partir do material
        out = render(s, mode, check)
        kind = "gif" if out["gif"] else "png"
        data, info = (out["gif"], out["gif_info"]) if out["gif"] else (out["png"], out["png_info"])
        folder.mkdir(parents=True, exist_ok=True)
        _atomic(folder / f"{h}.png", out["png"])
        if kind == "gif":
            _atomic(folder / f"{h}.gif", data)
        m = {**info, **rec, "file": f"{h}.{kind}", "png": f"{h}.png", "state": out["state"], "reason": out["reason"],
             "render_s": out["render_s"], "colors": out.get("colors"), "sha256": hashlib.sha256(data).hexdigest(),
             "png_sha256": hashlib.sha256(out["png"]).hexdigest()}
        _atomic(meta, json.dumps(m, ensure_ascii=False).encode())
        for f in folder.iterdir():
            if re.fullmatch(r"[0-9a-f]{16}\.(gif|png|json)(\.tmp)?", f.name) and not f.name.startswith(h):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    log.info("visual 3D: cache anterior mantido")
        check()
    except Cancelled:
        raise
    except MemoryError:
        log.warning("visual 3D: memória insuficiente")
        return None, {**rec, "state": "failed", "reason": "memória insuficiente"}
    except ImportError:  # instalação de antes da visualização 3D, sem o Pillow
        log.warning("visual 3D: Pillow não instalado")
        return None, {**rec, "state": "failed", "reason": "falta o Pillow: abra o “Iniciar Lumen.bat” uma vez"}
    except OSError:
        return None, {**rec, "state": "failed", "reason": "não foi possível gravar o visual; confira espaço e permissão na pasta do Lumen"}
    except Exception as e:  # noqa: BLE001 — o visual é opcional: a aula sai sem ele
        log.warning("visual 3D: desenho falhou (%s)", type(e).__name__)
        return None, {**rec, "state": "failed", "reason": f"o desenho falhou ({type(e).__name__})"}
    finally:
        _LOCK.release()
    log.info("visual 3D: %s %s, %d×%d, %d quadro(s), %d KB em %.1f s (%s)", s["family"], kind, info["width"],
             info["height"], info["frames"], info["bytes"] // 1024, out["render_s"], out["state"])
    return {**m, "data": data, "png_data": out["png"], "cached": False}, {**rec, "state": out["state"],
                                                                          "reason": out["reason"]}


def caption(asset):
    """A legenda nos dois destinos: de quem é, o que mostra e se é animação ou imagem estática. Nunca promete
    girar com o mouse (é um GIF)."""
    what = asset.get("describe") or ""
    what = what[0].lower() + what[1:] if what else ""
    if asset["kind"] == "gif":
        return f"Visualização 3D gerada pelo Lumen (animação, esquemática): {what}."
    return f"Visualização 3D gerada pelo Lumen (imagem estática, esquemática): {what}."
