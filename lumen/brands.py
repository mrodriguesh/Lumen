"""Logos de marcas para as capas: a logo vem pronta de um acervo e é colocada na capa; a IA nunca a desenha.

Acervo: Simple Icons (CC0, ≈ 3.400 marcas em SVG com a cor oficial de cada uma), baixado só com o clique do usuário
(versão fixa e conferida por SHA-256). Marcas que o acervo não tem (a pedido das próprias empresas: Adobe, OpenAI,
Microsoft…) podem ser acrescentadas pelo usuário na pasta `logos` (SVG ou PNG; o nome do arquivo é o nome da marca).
A marca só é usada se o nome aparecer escrito igual no título ou na aula: sem busca aproximada, para não pôr a logo errada.
"""
import base64
import hashlib
import io
import json
import re
import shutil
import tarfile
import unicodedata
import urllib.request
from pathlib import Path

from . import AppError, store

VERSION = "16.35.0"
URL = f"https://registry.npmjs.org/simple-icons/-/simple-icons-{VERSION}.tgz"
SHA256 = "20ebead4f6bc93464812a5e260d19fc4d84772e5eeff69a6fbea263ca2441c5f"
SIZE = "≈ 6,5 MB"
MIN_BRANDS = 1000   # um acervo com menos que isto veio quebrado
# nomes comuns do dia a dia (“meta de vendas”, “próximo”…): só valem no título, com inicial maiúscula
AMBIGUOUS = {"meta", "next", "linear", "bolt", "signal", "square", "medium", "arc", "ghost", "hive", "brave", "flow",
             "swift", "unity", "ember", "zoom", "scale", "stack", "base", "mind", "pocket", "wise", "vite", "fly"}
ALIASES = {"gemini": "google gemini", "claude ai": "claude", "tik tok": "tiktok"}
_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}


def folder():
    return store.DATA / "marcas"


def user_folder():
    return store.DATA / "logos"


def ready():
    return (folder() / "marcas.json").is_file()


def info():
    """Para a interface: acervo instalado (versão e quantas marcas) e logos do usuário."""
    mine = [p for p in user_folder().glob("*") if p.suffix.lower() in _MIME] if user_folder().is_dir() else []
    return {"ready": ready(), "version": VERSION, "size": SIZE, "count": len(_data()), "mine": len(mine),
            "folder": str(user_folder())}


def download(progress, check):
    """Baixa o acervo (pedido explícito do usuário), confere a versão e guarda só o necessário."""
    raw = bytearray()
    try:
        with urllib.request.urlopen(URL, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0) or 6_600_000
            while chunk := r.read(1 << 18):
                check()
                raw += chunk
                progress(min(len(raw) / total, .9), None)
    except OSError:
        raise AppError("Não foi possível baixar as logos.", "Confira a internet e tente de novo.") from None
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise AppError("O arquivo baixado não é o esperado.", "Nada foi instalado; tente de novo mais tarde.")
    tmp = folder().with_name("marcas.novo")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "icons").mkdir(parents=True)
    brands = []
    with tarfile.open(fileobj=io.BytesIO(bytes(raw)), mode="r:gz") as t:
        for m in t:
            name = m.name.removeprefix("package/")
            if m.isfile() and m.size < 2_000_000 and name == "data/simple-icons.json":
                brands = json.loads(t.extractfile(m).read())
            elif m.isfile() and m.size < 50_000 and re.fullmatch(r"icons/[a-z0-9]+\.svg", name):
                svg = t.extractfile(m).read()
                if svg.lstrip().startswith(b"<svg"):
                    (tmp / "icons" / name[6:]).write_bytes(svg)
    keep = [{"title": b["title"], "slug": b["slug"], "hex": b["hex"], "aka": (b.get("aliases") or {}).get("aka", [])}
            for b in brands if (tmp / "icons" / f"{b['slug']}.svg").is_file()]
    if len(keep) < MIN_BRANDS:
        shutil.rmtree(tmp, ignore_errors=True)
        raise AppError("O acervo de logos veio incompleto.", "Nada foi instalado; tente de novo mais tarde.")
    (tmp / "marcas.json").write_text(json.dumps(keep, ensure_ascii=False), "utf-8")
    shutil.rmtree(folder(), ignore_errors=True)
    tmp.rename(folder())
    progress(1, None)


def norm(s):
    """Minúsculas, sem acento, só letras e números separados por um espaço (“Next.js” → “next js”)."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _fold(s):
    """Como norm, mas mantém as maiúsculas (a marca citada no meio de uma frase tem inicial maiúscula)."""
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()


def _data():
    try:
        return json.loads((folder() / "marcas.json").read_text("utf-8"))
    except (OSError, ValueError):
        return []


_cache = {"key": None, "names": {}, "rx": None}


def _names():
    """nome normalizado → marca. Logos do usuário vencem as do acervo."""
    mine = sorted(p for p in user_folder().glob("*") if p.suffix.lower() in _MIME) if user_folder().is_dir() else []
    key = (ready() and (folder() / "marcas.json").stat().st_mtime, tuple((p.name, p.stat().st_mtime) for p in mine))
    if _cache["key"] == key:
        return _cache["names"]
    names = {}
    for b in _data():
        for n in [b["title"], *b["aka"]]:
            names.setdefault(norm(n), {"name": b["title"], "slug": b["slug"], "hex": b["hex"], "file": None})
    for alias, target in ALIASES.items():
        if target in names:
            names.setdefault(alias, names[target])
    for p in mine:
        names[norm(p.stem)] = {"name": p.stem.replace("-", " ").replace("_", " ").title(), "slug": None, "hex": None,
                               "file": p}
    names = {n: v for n, v in names.items() if len(n) >= 3}
    parts = sorted(names, key=len, reverse=True)
    rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(n.replace(" ", "[^A-Za-z0-9]+") for n in parts)
                    + r")(?![A-Za-z0-9])", re.I) if parts else None
    _cache.update(key=key, names=names, rx=rx)
    return names


def find(title, texts=(), limit=2):
    """Marcas que a aula (ou a página) cita, as mais citadas primeiro. title conta mais que o texto corrido.

    Só valem nomes escritos iguais ao da marca e com inicial maiúscula; nomes comuns (AMBIGUOUS) e com menos de 4
    letras só valem no título. No texto corrido, a marca precisa aparecer 3 vezes ou mais."""
    names = _names()
    rx = _cache["rx"]
    if not rx:
        return []
    score = {}  # nome → [marca, vezes no título, vezes no texto]

    def scan(text, in_title):
        text = _fold(text)
        for m in rx.finditer(text):
            raw = m.group(0)
            n = norm(raw)
            brand = names.get(n)
            capital, common = raw[:1].isupper(), n in AMBIGUOUS or len(n) < 4
            # no título, um nome comum só vale no meio da frase (“Marketing com Meta Ads”, não “Meta de vendas”)
            midsentence = text[:m.start()].rstrip()[-1:].isalnum() and text[m.start() - 1:m.start()] == " "
            if not brand or (in_title and common and not (capital and midsentence)) or (not in_title and (common or not capital)):
                continue
            score.setdefault(brand["name"], [brand, 0, 0])[1 if in_title else 2] += 1
    scan(title, True)
    for t in texts:
        scan(t, False)
    ranked = sorted(((b, 5 * t + c) for b, t, c in score.values() if t or c >= 3), key=lambda x: -x[1])
    return [b for b, s in ranked[:limit] if ranked and s * 10 >= ranked[0][1] * 6]


def logo(brand):
    """Dados para desenhar a logo: `mask` (SVG de um traço só, que ganha a cor da capa) ou `img` (arquivo do
    usuário, com as próprias cores), mais a cor oficial. Nunca mexe no SVG: vai como imagem, sem scripts."""
    try:
        if brand["file"]:
            p = brand["file"]
            uri = f"data:{_MIME[p.suffix.lower()]};base64," + base64.b64encode(p.read_bytes()).decode()
            return {"name": brand["name"], "img": uri, "mask": None, "hex": None}
        svg = (folder() / "icons" / f"{brand['slug']}.svg").read_bytes()
    except OSError:
        return None
    return {"name": brand["name"], "img": None, "hex": "#" + brand["hex"],
            "mask": "data:image/svg+xml;base64," + base64.b64encode(svg).decode()}
