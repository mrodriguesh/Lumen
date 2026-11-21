"""Diagrama dos Estudos (fase 5; D20): a IA devolve só dados, nunca código. O desenho é sempre do app: SVG 2D
interativo na conversa (lumen/web/study-diagram.js) e, fora dele, o GIF/PNG do holograma (visual3d) ou o PNG do mapa
mental (mindmap, pelo Edge sem janela).

A spec tem os mesmos campos da spec do holograma (visual3d._KEYS), com três famílias a mais (linha do tempo, ciclo e
mapa mental) e, em cada parte, a explicação dela (`detail`) e a parte de cima (`parent`, para os ramos do mapa e os
lados da comparação). `evidence` traz os S# das fontes. Todo array tem teto (D18), e validate() confere tudo antes de
mostrar ou exportar; a conferência do holograma roda junto, na mesma spec reduzida que vira o GIF (to_visual)."""
import re

from .. import visual3d
from ..package import RELATIONS

FAMILIES = {**visual3d.FAMILIES, "linha": "Linha do tempo", "ciclo": "Ciclo", "mapa": "Mapa mental"}
SEQUENCE = ("processo", "linha", "ciclo")
VISUAL = {"linha": "processo", "ciclo": "processo", "mapa": "conceitos"}  # a cena do holograma de cada família nova
ROLE = {"processo": "step", "linha": "step", "ciclo": "step", "estrutura": "layer"}
MAX_NODES, MAX_LINKS, MAX_DETAIL, MAX_EVIDENCE = 18, 30, 400, 24
MAX_BRANCHES, MAX_CHILDREN = 6, 3
_NODE = {"label", "role", "sub", "detail", "parent"}
_SID = re.compile(r"^(S\d{1,3}|geral)$")
_text = visual3d._text


def _obj(**props):
    return {"type": "object", "properties": props, "required": list(props)}


def _arr(items, n):
    return {"type": "array", "items": items, "maxItems": n}


S, INT = {"type": "string"}, {"type": "integer"}


def schema(lean=False):
    """O que a IA preenche para um diagrama: a família, as partes (rótulo curto e explicação) e as relações entre
    elas pelo índice. parent só vale na comparação (0 ou 1: o lado); nas outras, -1."""
    return _obj(family={"type": "string", "enum": [k for k in FAMILIES if k != "mapa"]}, title=S,
                nodes={**_arr(_obj(label=S, detail=S, parent=INT), 4 if lean else 8), "minItems": 3},  # o 4b mandou 1 parte só
                relations=_arr(_obj(**{"from": INT, "to": INT, "kind": {"type": "string", "enum": list(RELATIONS)}}), 3 if lean else 6))


def mind_schema(ids, lean=False):
    leaf = _obj(label=S, detail=S)
    return _obj(center=S, branches=_arr(_obj(label=S, detail=S, children=_arr(leaf, 2 if lean else MAX_CHILDREN)),
                                        3 if lean else MAX_BRANCHES),
                sources=_arr({"type": "string", "enum": ids}, 4))


def _node(label, detail, role, parent):
    return {"label": label, "role": role, "sub": 0, "detail": _text(detail, MAX_DETAIL), "parent": parent}


def _finish(family, concept, title, nodes, links, evidence, more=0):
    for k, n in enumerate(nodes):
        n["sub"] = min(4, sum(1 for x in nodes if x["parent"] == k))
    seen, out = set(), []
    for x in links:
        pair = frozenset((x["a"], x["b"]))
        if pair not in seen:
            seen.add(pair)
            out.append(x)
    concept = _text(concept, 40) or "Assunto"
    return validate({"v": 1, "family": family, "concept": concept, "title": _text(title, visual3d.MAX_TITLE) or concept,
                     "nodes": nodes, "links": out[:MAX_LINKS],
                     "evidence": [e for e in dict.fromkeys(evidence) if isinstance(e, str) and _SID.match(e)][:MAX_EVIDENCE],
                     "more": min(more, 50)})


def build(raw, concept, evidence=()):
    """A spec a partir do JSON da IA (schema()). Partes sem rótulo, índices fora e relações repetidas saem aqui;
    o que sobrar inválido → ValueError (sem diagrama)."""
    raw = raw if isinstance(raw, dict) else {}
    num = re.compile(r"^\s*(?:\d{1,2}|[a-z])[.)º-]\s+")  # "1. Desenho": o número já está no desenho
    fam = raw.get("family") if raw.get("family") in FAMILIES and raw.get("family") != "mapa" else "conceitos"
    given = [(i, x) for i, x in enumerate(raw.get("nodes") if isinstance(raw.get("nodes"), list) else [])
             if isinstance(x, dict) and _text(x.get("label"))]
    new, nodes = {}, []
    for i, x in given:
        if len(nodes) >= MAX_NODES:
            break
        parent = -1
        if fam == "comparacao" and len(nodes) >= 2:
            parent = new.get(x.get("parent")) if type(x.get("parent")) is int else None
            if parent not in (0, 1):
                continue  # um detalhe sem lado não entra
        role = ROLE.get(fam) or ({0: "a", 1: "b"}.get(len(nodes)) if fam == "comparacao" else "item")
        new[i] = len(nodes)
        nodes.append(_node(_text(num.sub("", x["label"])) or _text(x["label"]), x.get("detail"),
                           nodes[parent]["role"] if parent >= 0 else role, parent))
    n = len(nodes)
    if fam in SEQUENCE:
        links = [{"a": k, "b": k + 1, "kind": "sequencia"} for k in range(n - 1)]
        if fam == "ciclo" and n >= 3:
            links.append({"a": n - 1, "b": 0, "kind": "sequencia"})
    elif fam == "comparacao":
        links = [{"a": 0, "b": 1, "kind": "contrasta com"}] + [{"a": x["parent"], "b": k, "kind": "hub"}
                                                             for k, x in enumerate(nodes) if x["parent"] >= 0]
    elif fam == "estrutura":
        links = []
    else:
        links = [{"a": -1, "b": k, "kind": "hub"} for k in range(n)]
    for r in raw.get("relations") if isinstance(raw.get("relations"), list) else []:
        if isinstance(r, dict) and r.get("kind") in RELATIONS:
            a, b = new.get(r.get("from")), new.get(r.get("to"))
            if a is not None and b is not None and a != b:
                links.append({"a": a, "b": b, "kind": r["kind"]})
    return _finish(fam, concept, raw.get("title") or concept, nodes, links, evidence, len(given) - n)


def from_mind(raw, topic, sources=()):
    """O mapa mental (mind_schema()) na mesma spec: o centro é o assunto, os ramos ficam ligados a ele e os filhos,
    ao ramo."""
    raw = raw if isinstance(raw, dict) else {}
    nodes, links, more = [], [], 0
    lst = lambda v: v if isinstance(v, list) else []  # noqa: E731 — fora do esquema (o Claude pode mandar outra coisa)
    for b in [b for b in lst(raw.get("branches")) if isinstance(b, dict) and _text(b.get("label"))][:MAX_BRANCHES]:
        if len(nodes) >= MAX_NODES:
            more += 1
            continue
        k = len(nodes)
        nodes.append(_node(_text(b["label"]), b.get("detail"), "item", -1))
        links.append({"a": -1, "b": k, "kind": "hub"})
        for c in [c for c in lst(b.get("children")) if isinstance(c, dict) and _text(c.get("label"))][:MAX_CHILDREN]:
            if len(nodes) >= MAX_NODES:
                more += 1
                continue
            links.append({"a": k, "b": len(nodes), "kind": "hub"})
            nodes.append(_node(_text(c["label"]), c.get("detail"), "item", k))
    center = raw.get("center") or topic
    return _finish("mapa", center, f"Mapa mental · {center}", nodes, links,
                   [x for x in lst(raw.get("sources")) if isinstance(x, str) and x in sources], more)


def validate(d):
    """A spec antes de ir para a tela ou virar imagem: campos, tipos, quantidades, rótulos e ligações aceitos, e a
    mesma conferência do holograma (visual3d.validate) na versão reduzida. Qualquer outra coisa → ValueError."""
    def need(ok, what):
        if not ok:
            raise ValueError(what)
    need(isinstance(d, dict) and set(d) == visual3d._KEYS, "campos do diagrama")
    need(d["v"] == 1 and type(d["v"]) is int, "versão")
    fam, nodes, links = d["family"], d["nodes"], d["links"]
    need(fam in FAMILIES, "família")
    need(isinstance(nodes, list) and 1 <= len(nodes) <= MAX_NODES, "quantidade de partes")
    for k, n in enumerate(nodes):
        need(isinstance(n, dict) and set(n) == _NODE, "parte")
        need(isinstance(n["label"], str) and 0 < len(n["label"]) <= visual3d.MAX_LABEL and n["label"] == _text(n["label"]), "rótulo")
        need(isinstance(n["detail"], str) and n["detail"] == _text(n["detail"], MAX_DETAIL), "explicação da parte")
        need(type(n["sub"]) is int and 0 <= n["sub"] <= 4, "detalhes da parte")
        p = n["parent"]
        need(type(p) is int and -1 <= p < k, "parte de cima")
        if fam == "mapa":
            need(p < 0 or nodes[p]["parent"] < 0, "nível do mapa")
        elif fam == "comparacao":
            need((p < 0) if k < 2 else (p in (0, 1) and n["role"] == nodes[p]["role"]), "lado da comparação")
        else:
            need(p < 0, "parte de cima")
    roles = {n["role"] for n in nodes}
    need({**dict.fromkeys(SEQUENCE, roles == {"step"} and len(nodes) >= 2), "estrutura": roles == {"layer"},
          "comparacao": len(nodes) >= 2 and nodes[0]["role"] == "a" and nodes[1]["role"] == "b" and roles == {"a", "b"},
          }.get(fam, roles == {"item"}), "partes da família")
    need(isinstance(links, list) and len(links) <= MAX_LINKS, "quantidade de ligações")
    for x in links:
        need(isinstance(x, dict) and set(x) == {"a", "b", "kind"}, "ligação")
        need(all(type(x[e]) is int and -1 <= x[e] < len(nodes) for e in "ab") and x["a"] != x["b"], "ponta da ligação")
        need(x["kind"] in visual3d.LINK_KINDS, "tipo de ligação")
    need(isinstance(d["evidence"], list) and len(d["evidence"]) <= MAX_EVIDENCE
         and all(isinstance(e, str) and _SID.match(e) for e in d["evidence"]), "fontes")
    need(type(d["more"]) is int and 0 <= d["more"] <= 50, "partes de fora")
    visual3d.validate(to_visual(d))
    return d


def to_visual(d):
    """A spec do holograma (visual3d), com o que cabe na cena: até 6 etapas, 5 camadas, 7 elementos, os dois lados
    com dois detalhes cada. É o que vira o GIF/PNG do Notion, do Obsidian e do PDF."""
    fam, nodes = VISUAL.get(d["family"], d["family"]), d["nodes"]
    if fam == "processo":
        keep = list(range(len(nodes)))[:6]
    elif fam == "estrutura":
        keep = list(range(len(nodes)))[:5]
    elif fam == "comparacao":
        keep = [0, 1] + [k for k in range(2, len(nodes)) if nodes[k]["parent"] == 0][:2] + \
               [k for k in range(2, len(nodes)) if nodes[k]["parent"] == 1][:2]
    else:
        keep = [k for k, n in enumerate(nodes) if n["parent"] < 0][:visual3d.MAX_NODES]
    new = {-1: -1, **{old: i for i, old in enumerate(keep)}}
    vnodes = [{"label": nodes[k]["label"], "role": nodes[k]["role"],
               "sub": nodes[k]["sub"] if fam in ("conceitos", "sistema", "estrutura") else 0} for k in keep]
    links = [{"a": new[x["a"]], "b": new[x["b"]], "kind": x["kind"]} for x in d["links"]
             if x["a"] in new and x["b"] in new]
    return {"v": 1, "family": fam, "concept": d["concept"], "title": d["title"], "nodes": vnodes,
            "links": links[:visual3d.MAX_LINKS], "evidence": ["title"], "more": min(50, d["more"] + len(nodes) - len(keep))}


def to_mind(d):
    """O mapa mental no formato de mindmap.render."""
    return {"center": d["concept"], "branches": [
        {"label": n["label"], "emoji": "", "children": [c["label"] for c in d["nodes"] if c["parent"] == k]}
        for k, n in enumerate(d["nodes"]) if n["parent"] < 0]}


def image(d, kind="png"):
    """(bytes, tipo) para baixar ou mandar a outro app. O mapa mental sai pelo Edge sem janela (mindmap); sem Edge, e
    nas outras famílias, sai a cena do holograma (visual3d), em PNG ou GIF animado."""
    validate(d)
    if d["family"] == "mapa" and kind == "png":
        from .. import mindmap
        png = mindmap.render(to_mind(d))
        if png:
            return png, "image/png"
    out = visual3d.render(to_visual(d), "animated" if kind == "gif" else "static", origin="das suas notas")
    return (out["gif"], "image/gif") if kind == "gif" and out["gif"] else (out["png"], "image/png")
