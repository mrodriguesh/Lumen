"""Arquivos locais em pastas que o usuário autorizou (Estudos → Fontes → Pastas autorizadas).

Só leitura e só dentro das pastas da lista: todo caminho é resolvido e precisa continuar dentro de uma delas; links e
junctions não são seguidos; pastas ocultas ficam de fora. Formatos: Markdown, texto, HTML, CSV e PDF (pypdf)."""
import os
from datetime import datetime, timezone
from pathlib import Path

from ... import AppError, protection, store
from .. import settings
from . import Doc, web

TEXT = {".md", ".markdown", ".txt", ".csv", ".html", ".htm"}
SUPPORTED = TEXT | {".pdf"}
MAX_TEXT, MAX_PDF = 5_000_000, 40_000_000


def folders():
    out = []
    for raw in settings.load()["connectors"]["folders"]:
        p = Path(raw)
        if p.is_dir():
            out.append(p.resolve())
    return out


def validate_folder(raw):
    """Uma pasta pode ser autorizada? Devolve o caminho resolvido ou explica por que não."""
    if not raw:
        raise AppError("Nenhuma pasta escolhida.")
    p = Path(raw).expanduser()
    if not p.is_dir():
        raise AppError("Esta pasta não existe.")
    p = p.resolve()
    if p == Path(p.anchor):
        raise AppError("Autorize uma pasta específica, não o disco inteiro.", "Escolha a pasta dos seus materiais.")
    if p == store.DATA.resolve() or store.DATA.resolve() in p.parents or p in store.DATA.resolve().parents:
        raise AppError("Esta pasta guarda os dados do próprio Lúmen.", "Escolha a pasta dos seus materiais.")
    cofre = store.load_config()["obsidian_vault"]
    if cofre:
        v = Path(cofre).resolve()
        if p == v or v in p.parents or p in v.parents:
            raise AppError("Esta pasta contém (ou está dentro de) o cofre do Obsidian, que já é lido pelo conector dele.",
                           "Escolha uma pasta fora do cofre.")
    return p


def inside_authorized(raw):
    """O arquivo resolvido, se estiver dentro de uma pasta autorizada; senão erro. Nunca segue link para fora."""
    p = Path(raw)
    try:
        real = p.resolve(strict=True)
    except OSError:
        raise AppError("Arquivo não encontrado.") from None
    for folder in folders():
        if real == folder or folder in real.parents:
            rel = real.relative_to(folder)
            if any(part.startswith(".") for part in rel.parts):
                break
            return real
    raise AppError("Este arquivo está fora das pastas autorizadas.", "Autorize a pasta em Estudos → Fontes.")


def extract(p):
    ext = p.suffix.lower()
    if ext == ".pdf":
        if p.stat().st_size > MAX_PDF:
            raise AppError("PDF grande demais para ler.")
        return web.pdf_text(p.read_bytes())
    if p.stat().st_size > MAX_TEXT:
        raise AppError("Arquivo grande demais para ler.")
    raw = p.read_text("utf-8", errors="replace")
    if ext in (".html", ".htm"):
        return web.html_to_text(raw)[1]
    return raw


class Files:
    name, label = "files", "Arquivos locais"

    def status(self):
        fs = folders()
        if not fs:
            return {"connected": False, "message": "Nenhuma pasta autorizada ainda."}
        return {"connected": True, "message": "", "folders": [str(f) for f in fs]}

    def test(self):
        st = self.status()
        if st["connected"]:
            n = sum(1 for _ in self._walk())
            st["message"] = f"{len(st['folders'])} pasta(s) autorizada(s), {n} arquivos legíveis."
        return st

    def _walk(self):
        for folder in folders():
            for directory, dirs, files in os.walk(folder, followlinks=False):
                base = Path(directory)
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not protection.redirected(base / d))
                for name in sorted(files):
                    p = base / name
                    if p.suffix.lower() in SUPPORTED and not name.startswith(".") and not protection.redirected(p):
                        yield p

    def versions(self, check):
        out = {}
        for p in self._walk():
            check()
            try:
                st = p.stat()
            except OSError:
                continue
            out[str(p)] = (f"{st.st_mtime_ns}:{st.st_size}", {"mtime": st.st_mtime})
        return out

    def load(self, source_id, info, check):
        p = inside_authorized(source_id)
        try:
            text = extract(p)
        except AppError:
            return None
        updated = datetime.fromtimestamp(info.get("mtime") or p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        return Doc(source="files", source_id=str(p), title=p.stem, text=text, path=str(p), kind=p.suffix.lower().lstrip("."),
                   updated=updated, meta={"folder": str(p.parent)})

    def read(self, source_id):
        return extract(inside_authorized(source_id))

    def open(self, doc):
        p = inside_authorized(doc["source_id"])
        if p.suffix.lower() not in SUPPORTED:
            raise AppError("Tipo de arquivo não permitido.")
        os.startfile(str(p))  # noqa: S606 — arquivo de leitura numa pasta autorizada, aberto pelo app associado
        return {"notice": "Arquivo aberto."}

    def uri(self, doc):
        return ""
