"""Obsidian por leitura direta do cofre configurado nos Ajustes (store: obsidian_vault).

Só leitura. Pula pastas ocultas (.obsidian, .trash, .claude…), links e junctions, a cópia do Notion que a Proteção cria
dentro do cofre (pasta com o marcador `.lumen-protection.json` de tipo notion-mirror: indexá-la duplicaria cada página
do Notion), notas com `lumen-protection-origin` no começo e templates. Abre notas por obsidian://open."""
import os
import posixpath
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from ... import AppError, obsidian, protection, store, vault
from .. import images, settings
from . import Doc

TAG = re.compile(r"(?<![\w&#/])#([^\s#.,;:!?()\[\]{}\"'`]+)")
LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
MAX_BYTES = 2_000_000
# Imagens embutidas: ![[x.png]] ou ![[x.png|300]] (pelo nome, em qualquer pasta, como o Obsidian) e ![texto](x.png)
# (relativo à nota ou à raiz). Endereços da internet ficam de fora.
EMBED = re.compile(r"!\[\[([^\]|#]+)[^\]]*\]\]|!\[[^\]]*\]\((?:<([^>]+)>|([^)\s]+))[^)]*\)")


def _vault():
    return vault.check(store.load_config()["obsidian_vault"])


def _template(rel, name):
    return name.startswith("Template - ") or "/Templates/" in "/" + rel or re.search(r"(^|/)\d* ?Templates/", rel)


def _author(fields):
    author = str(fields.get("author") or "").casefold()
    kind = str(fields.get("type") or "").casefold()
    if author in ("user", "usuario", "usuário") or kind in ("permanent", "anchor"):
        return "user"
    if author == "lumen-ai" or kind == "ai-study":
        return "lumen"
    if author.startswith("claude") or author.startswith("ai") or kind.startswith("ai-"):
        return "ai"
    return ""


class Obsidian:
    name, label = "obsidian", "Obsidian"

    def __init__(self):
        self._names = None  # nome do arquivo → caminhos das imagens do cofre (uma passada por sincronização)

    def _image(self, root, note_rel, target):
        """O caminho de uma imagem embutida, sempre dentro do cofre; None se não achar."""
        target = urllib.parse.unquote(target).strip()
        if "://" in target or not target.lower().endswith(images.EXT):
            return None
        for base in (posixpath.dirname(note_rel), ""):
            rel = posixpath.normpath(posixpath.join(base, target))
            if not rel.startswith(".."):
                try:
                    p = vault.inside(root, rel)
                except AppError:
                    continue
                if p.is_file():
                    return p
        if self._names is None:
            self._names = {}
            for directory, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if not d.startswith(".") and not protection.redirected(Path(directory) / d)]
                for n in files:
                    if n.lower().endswith(images.EXT):
                        self._names.setdefault(n.casefold(), []).append(Path(directory) / n)
        found = self._names.get(posixpath.basename(target).casefold(), [])
        near = [p for p in found if p.parent == root.joinpath(*posixpath.dirname(note_rel).split("/"))]
        for p in near + sorted(found, key=lambda p: len(p.parts)):
            try:  # um link ou junction que aponta para fora do cofre fica de fora, como no caminho direto
                return vault.inside(root, p.relative_to(root).as_posix())
            except AppError:
                continue
        return None

    def _pictures(self, root, note_rel, body):
        """Troca cada imagem embutida pelo que a visão leu dela (ou pelo nome, enquanto não leu)."""
        pics = []

        def swap(m):
            if len(pics) >= images.PER_DOC:
                return m[0]
            p = self._image(root, note_rel, m[1] or m[2] or m[3] or "")
            try:
                h = images.register(p.read_bytes(), p.name, "obsidian") if p and p.stat().st_size <= images.MAX_BYTES else None
            except OSError:
                h = None
            if not h:
                return m[0]
            pics.append({"hash": h, "name": p.name})
            return images.inline(h, p.name)
        return EMBED.sub(swap, body), pics

    def status(self):
        raw = store.load_config()["obsidian_vault"]
        if not raw:
            return {"connected": False, "message": "Escolha o cofre do Obsidian em Integrações."}
        try:
            root = _vault()
        except AppError as e:
            return {"connected": False, "message": str(e)}
        return {"connected": True, "message": "", "where": root.name}

    def test(self):
        st = self.status()
        if not st["connected"]:
            return st
        root = _vault()
        count = sum(1 for _ in self._walk(root))
        return {**st, "message": f"Cofre “{root.name}” lido: {count} notas Markdown disponíveis."}

    def _walk(self, root):
        for directory, dirs, files in os.walk(root, followlinks=False):
            base = Path(directory)
            if base != root and (base / protection.MARKER).exists():
                try:
                    mark = protection.read(base / protection.MARKER)
                except Exception:  # noqa: BLE001 — marcador ilegível: na dúvida, é área gerada
                    mark = {"kind": "notion-mirror"}
                if mark.get("kind") in ("notion-mirror", "repository"):
                    dirs[:] = []
                    continue
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not protection.redirected(base / d))
            for name in sorted(files):
                if not name.lower().endswith(".md"):
                    continue
                p = base / name
                rel = p.relative_to(root).as_posix()
                if _template(rel, p.stem) or protection.redirected(p):
                    continue
                yield p, rel

    def versions(self, check):
        root = _vault()
        out = {}
        for p, rel in self._walk(root):
            check()
            try:
                st = p.stat()
                if st.st_size > MAX_BYTES:
                    continue
                with p.open("rb") as f:
                    if b"lumen-protection-origin:" in f.read(512):
                        continue
            except OSError:
                continue
            out[rel] = (f"{st.st_mtime_ns}:{st.st_size}", {"mtime": st.st_mtime})
        return out

    def load(self, source_id, info, check):
        root = _vault()
        p = vault.inside(root, source_id)
        text = p.read_text("utf-8", errors="replace")
        front, body = vault.split(text)
        fields = vault.fields(front)
        body = re.sub(r"%%.*?%%", " ", body, flags=re.S)
        body, pics = self._pictures(root, source_id, body) if settings.load()["search"]["images"] else (body, [])
        tags = [str(t).lstrip("#") for t in (fields.get("tags") if isinstance(fields.get("tags"), list) else
                                             [fields.get("tags")] if fields.get("tags") else [])]
        tags += [t for t in TAG.findall(re.sub(r"```.*?```", " ", body, flags=re.S)) if not t.isdigit()]
        aliases = fields.get("aliases") if isinstance(fields.get("aliases"), list) else []
        title = str(fields.get("title") or p.stem).strip() or p.stem
        updated = datetime.fromtimestamp(info.get("mtime") or p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        meta = {"type": str(fields.get("type") or ""), "aliases": [str(a) for a in aliases][:20],
                "topics": [str(t) for t in (fields.get("topics") or [])][:20] if isinstance(fields.get("topics"), list) else [],
                "folder": str(Path(source_id).parent.as_posix()), **({"images": pics} if pics else {})}
        return Doc(source="obsidian", source_id=source_id, title=title, text=body.strip(), path=source_id,
                   kind="note", author=_author(fields), tags=list(dict.fromkeys(t for t in tags if t))[:40],
                   links=list(dict.fromkeys(x.strip() for x in LINK.findall(body)))[:200], updated=updated,
                   version="", meta=meta)

    def read(self, source_id):
        root = _vault()
        return vault.split(vault.inside(root, source_id).read_text("utf-8", errors="replace"))[1]

    def open(self, doc):
        root = _vault()
        p = vault.inside(root, doc["source_id"])
        if not p.is_file():
            raise AppError("A nota não está mais no cofre.", "Sincronize o Obsidian em Estudos → Fontes.")
        obsidian.open_path(p)
        return {"notice": "Nota aberta no Obsidian."}

    def uri(self, doc):
        try:
            return obsidian.uri(vault.inside(_vault(), doc["source_id"]))
        except AppError:
            return ""
