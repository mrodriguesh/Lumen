"""Cofres do Obsidian: quais existem neste PC, como o cofre está organizado e quais notas podem se conectar a uma
aula. Só leitura (quem escreve é lumen/obsidian.py).

A estrutura vem das próprias notas (o `type:` do frontmatter), não de caminhos fixos: Anchor Topics são as notas
`type: anchor`, estudos anteriores do Lumen são `type: ai-study`, e assim por diante. Nada do cofre sai do PC: as
candidatas vão só para a IA local (llm.connect)."""
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

from . import AppError
from .package import norm

# Notas que não são conhecimento (sistema, memória da IA, diário, captura bruta): nunca viram conexão.
SKIP_TYPES = {"system", "ai-memory", "ai-log", "ai-decision", "ai-briefing", "ai-spec", "ai-suggestion", "daily",
              "capture", "review"}
# Num cofre que usa `type:`, conhecimento é o que tem um destes tipos; notas sem tipo são documentação do sistema
# (teste real: “Agents”, “Skills” e índices viravam conexões de uma aula sobre RAG).
KNOWLEDGE = {"permanent", "resource", "project", "book", "ai-study", "anchor"}
KINDS = {"anchor": "Anchor Topic", "permanent": "Nota permanente", "resource": "Recurso", "project": "Projeto",
         "book": "Livro", "ai-study": "Estudo Lumen", "ai-output": "Output da IA"}
STOP = set("""a o as os um uma uns umas de da do das dos e em no na nos nas para por pela pelo pelas pelos com sem que
se ao aos como mais menos muito sobre entre este esta isso esse essa seu sua ou mas nao sim ser sao foi tem the of and
to in is for on with this that are was aula voce ele ela eles elas quando onde qual quais tambem""".split())


def config_path():
    return Path(os.environ.get("APPDATA") or Path.home()) / "obsidian" / "obsidian.json"


def vaults():
    """Cofres registrados no Obsidian deste PC, o aberto primeiro. Quem escolhe é o usuário (nunca em silêncio)."""
    try:
        data = json.loads(config_path().read_text("utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for v in (data.get("vaults") or {}).values():
        raw = str(v.get("path") or "") if isinstance(v, dict) else ""
        if raw:
            p = Path(raw)
            out.append({"path": str(p), "name": p.name, "open": bool(v.get("open")), "ok": (p / ".obsidian").is_dir()})
    return sorted(out, key=lambda x: (not x["open"], x["name"].casefold()))


def check(path):
    """O cofre (caminho resolvido) ou AppError dizendo o que está errado."""
    raw = str(path or "").strip()
    if not raw:
        raise AppError("O cofre do Obsidian ainda não foi escolhido.", "Abra Ajustes → Destinos do material e escolha o cofre.")
    p = Path(raw).expanduser()
    if not p.is_dir():
        raise AppError("A pasta do cofre do Obsidian não existe mais.", "Confira o cofre em Ajustes → Destinos do material.")
    if not (p / ".obsidian").is_dir():
        raise AppError("Esta pasta não é um cofre do Obsidian (falta a pasta .obsidian).",
                       "Escolha a pasta do cofre, a que o Obsidian abre.")
    return p.resolve()


def inside(vault, rel):
    """vault/rel resolvido, recusando o que sairia do cofre ou entraria em pastas ocultas (.obsidian, .trash…)."""
    raw = str(rel or "").replace("\\", "/").strip()
    rel = raw.strip("/")
    parts = [x for x in rel.split("/") if x not in ("", ".")]
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", rel) or any(x == ".." or x.startswith(".") for x in parts):
        raise AppError("A pasta escolhida no cofre não é válida.", "Use um caminho dentro do cofre, como “C04 Claude Obsidian/16 Lumen”.")
    p = vault.joinpath(*parts).resolve()
    if p != vault and vault not in p.parents:  # junction/symlink que aponta para fora
        raise AppError("A pasta escolhida aponta para fora do cofre.", "Escolha uma pasta comum dentro do cofre.")
    return p


def default_folder(vault):
    """Pasta padrão das notas do Lumen: dentro da área da IA do cofre (a pasta de topo com “Claude” no nome), com o
    próximo número livre da numeração dela; sem essa área, “Lumen” na raiz."""
    for d in sorted(vault.iterdir(), key=lambda x: x.name):
        if d.is_dir() and not d.name.startswith(".") and "claude" in d.name.casefold():
            kids = [c.name for c in d.iterdir() if c.is_dir()]
            mine = [c for c in kids if re.fullmatch(r"\d{2} Lumen", c)]
            if mine:
                return f"{d.name}/{mine[0]}"
            nums = [int(c[:2]) for c in kids if re.match(r"\d{2} ", c) and int(c[:2]) < 90]
            return f"{d.name}/{(max(nums) + 1 if nums else 1):02d} Lumen"
    return "Lumen"


# --- Frontmatter -------------------------------------------------------------------------------------------------

def split(text):
    """(linhas do frontmatter, corpo). Sem frontmatter: ([], texto)."""
    if text.startswith("---\n") or text.startswith("---\r\n"):
        lines = text.split("\n")
        for i in range(1, len(lines)):
            if lines[i].rstrip("\r") == "---":
                return [x.rstrip("\r") for x in lines[1:i]], "\n".join(lines[i + 1:])
    return [], text


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        try:
            return json.loads(v) if v[0] == '"' else v[1:-1]
        except ValueError:
            return v[1:-1]
    return v


def fields(lines):
    """Chaves de topo do frontmatter: texto ou lista (`- item` embaixo ou `[a, b]`). O resto é ignorado aqui."""
    out, key = {}, None
    for ln in lines:
        m = re.match(r"^([\w-]+):\s*(.*)$", ln)
        if m:
            key, v = m[1], m[2].strip()
            if v.startswith("[") and v.endswith("]"):
                out[key] = [_scalar(x) for x in re.findall(r'"(?:[^"\\]|\\.)*"|[^,\[\]]+', v[1:-1]) if x.strip()]
            else:
                out[key] = _scalar(v) if v else []
        elif key and re.match(r"^\s+-\s*", ln) and isinstance(out.get(key), list):
            out[key].append(_scalar(re.sub(r"^\s+-\s*", "", ln)))
    return out


# --- Índice e busca ----------------------------------------------------------------------------------------------

def _listed(v):
    return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])


def _link_name(v):
    return re.sub(r"^\[\[|\]\]$", "", v.strip()).split("|")[0].split("#")[0].strip()


def index(vault):
    """Todas as notas do cofre (fora das pastas ocultas), com o que importa para conexões e para validar links.
    ponytail: varre o cofre a cada aula (ms com centenas de notas); um cache por mtime se passar de ~20 mil."""
    notes = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = Path(root) / f
            try:
                text = p.read_text("utf-8", errors="replace")[:200_000]
            except OSError:
                continue
            fm, body = split(text)
            d = fields(fm)
            rel = p.relative_to(vault).as_posix()
            name = p.stem
            typ = str(d.get("type") or "")
            template = name.startswith("Template - ") or "/Templates/" in "/" + rel or "Templates/" in rel
            system = name in ("Home", "CLAUDE") or name.startswith("00 - ") or name.endswith(" Dashboard")
            notes.append({"name": name, "path": rel, "type": typ, "author": str(d.get("author") or ""),
                          "aliases": _listed(d.get("aliases")), "topics": [_link_name(t) for t in _listed(d.get("topics"))],
                          "lumen_id": str(d.get("lumen-id") or ""),
                          "candidate": not (template or system or typ in SKIP_TYPES),
                          "headings": re.findall(r"^#{1,4}\s+(.+)$", body, re.M)[:30],
                          "text": re.sub(r"%%.*?%%", " ", body, flags=re.S)[:6000]})
    return notes


def tokens(text):
    """Palavras comparáveis: sem acento, sem palavras vazias, cortadas em 6 letras (“embeddings” = “embedding”)."""
    return [w[:6] for w in norm(text).split() if len(w) > 2 and w not in STOP and not w.isdigit()]


def search(notes, query, limit=12, exclude=""):
    """Candidatas a conexão por relevância (BM25 com pesos por campo). query: [(texto, peso)]. Só ranqueia; quem
    decide se a relação é real é a IA (llm.connect), entre estas e só estas."""
    typed = sum(1 for n in notes if n["type"]) >= 0.3 * len(notes)
    docs = [n for n in notes if n["candidate"] and (not exclude or n["lumen_id"] != exclude)
            and (n["type"] in KNOWLEDGE or not typed)]
    if not docs:
        return []
    tfs = []
    for n in docs:
        tf = Counter()
        for w in tokens(" ".join([n["name"], *n["aliases"]])):
            tf[w] += 3
        for w in tokens(" ".join([*n["headings"], *n["topics"]])):
            tf[w] += 1.5
        for w in tokens(n["text"]):
            tf[w] += 1
        tfs.append(tf)
    avg = sum(sum(t.values()) for t in tfs) / len(tfs) or 1
    df = Counter(w for t in tfs for w in t)
    q = Counter()
    for text, weight in query:
        for w in tokens(text):
            q[w] = max(q[w], weight)
    scored = []
    for n, tf in zip(docs, tfs):
        size, s, hits = sum(tf.values()), 0.0, 0
        for w, qw in q.items():
            if tf[w]:
                hits += 1
                idf = math.log(1 + (len(docs) - df[w] + 0.5) / (df[w] + 0.5))
                s += qw * idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * size / avg))
        if s > 0 and hits >= min(2, len(q)):  # uma palavra em comum não basta para ser candidata
            scored.append((s, n))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    top = scored[0][0] if scored else 0
    return [n for s, n in scored[:limit] if s >= top * 0.2]


def anchors(notes):
    return [n for n in notes if n["type"] == "anchor" and n["candidate"]]


def find(notes, lid):
    """A nota do Lumen desta aula, onde quer que o usuário a tenha movido ou renomeado."""
    return next((n for n in notes if lid and n["lumen_id"] == lid), None)


def excerpt(n, size=300):
    body = re.sub(r"^>.*$|^#.*$|^---$", " ", n["text"], flags=re.M)
    return " ".join(body.split())[:size]
