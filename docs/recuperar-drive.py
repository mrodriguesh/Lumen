"""Monta um repositório Restic com arquivos baixados do Drive, sem Lúmen ou credenciais.

Uso: python recuperar-drive.py snapshot-....json PASTA_DOS_OBJETOS NOVA_PASTA
Depois: restic -r NOVA_PASTA check --read-data
        restic -r NOVA_PASTA snapshots
        restic -r NOVA_PASTA restore ID --target PASTA_VAZIA
"""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path, PurePosixPath


def assemble(catalog, objects, destination):
    m = json.loads(Path(catalog).read_text("utf-8"))
    dest = Path(destination)
    if dest.exists() or m.get("format") != "lumen-restic-1" or not m.get("objects"):
        raise ValueError("Use um catálogo válido e uma pasta nova.")
    pending, seen = [], set()
    for obj in m["objects"]:
        name = obj["path"]
        rel = PurePosixPath(name)
        if rel.is_absolute() or "\\" in name or any(x in ("", ".", "..") or x.endswith((".", " ")) or
                re.search(r'[<>:"|?*\x00-\x1f]', x) or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", x)
                for x in name.split("/")) or name.casefold() in seen:
            raise ValueError("Caminho inseguro ou duplicado no catálogo.")
        seen.add(name.casefold())
        if not re.fullmatch(r"[a-f0-9]{64}", obj["sha256"]):
            raise ValueError("Hash inválido.")
        source = Path(objects) / ("object-" + obj["sha256"] + ".bin")
        if source.is_symlink() or not source.is_file() or source.stat().st_size != obj["size"]:
            raise ValueError("Objeto ausente ou tamanho incorreto: " + source.name)
        with source.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != obj["sha256"]:
                raise ValueError("Objeto corrompido: " + source.name)
        pending.append((source, dest.joinpath(*rel.parts)))
    dest.mkdir(parents=True)
    for source, out in pending:
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out)
    return m["snapshot"]


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    print("Repositório montado. Confira com restic check --read-data. Snapshot:", assemble(*sys.argv[1:]))
