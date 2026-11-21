"""Explicit repair of proven metadata-only differences, preserving every original byte.

Call only with the controller exclusively held and after a verified mirror restore point.
This is not an automatic conflict-resolution policy.
"""
import os
from pathlib import Path

from lumen import AppError, protection as p, protection_notion as pn


def reconcile():
    details = [x for x in p.attention_details()["items"] if x["kind"] == "difference"]
    if not details or any(x.get("reason") != "capture_time_only" for x in details):
        raise AppError("A correção exige diferenças somente de data/quebras de linha, já comparadas.")
    s = p.state(); dest = Path(s["notion_obsidian"]["path"])
    mark = p.read(dest / p.MARKER)
    if mark.get("owner") != p.configuration()["set_id"] or mark.get("kind") != "notion-mirror":
        raise AppError("A área de cópia não corresponde ao conjunto.")
    source = p.HOME / "capture/notion"; manifest = p.read(source / "manifest.json")
    paths, missing = pn.vault_layout(manifest, source)
    if missing: raise AppError("Confira a ancestralidade antes de reorganizar.")
    records = mark.setdefault("preserved_copies", [])
    for item in details:
        rel = item["path"]; iid = Path(rel).stem
        # This repair is deliberately limited to the previous flat layout.
        if iid not in paths or rel != iid + ".md": raise AppError("Caminho fora da migração plana.")
        old = p.target(dest, rel); sha = p.digest(old)
        preserved = "Versões preservadas/" + iid + ".md"
        out = p.target(dest, preserved)
        if out.exists() and p.digest(out) != sha: raise AppError("Já há uma versão diferente na área preservada.")
        if not out.exists(): p.stable_copy(old, out)
        assert p.digest(out) == sha
        if not any(x["path"] == preserved for x in records):
            records.append({"path": preserved, "title": item["title"], "sha256": sha,
                            "reason": "capture_time_only", "original_path": rel, "at": p.now()})
        mark["pages"][iid] = paths[iid]
        mark["files"].pop(rel, None)
    p.write(dest / p.MARKER, mark)
    for record in records:
        old = p.target(dest, record["original_path"])
        out = p.target(dest, record["path"])
        if old.exists():
            if p.digest(old) != record["sha256"] or p.digest(out) != record["sha256"]:
                raise AppError("Uma nota mudou durante a conferência. Ambas as versões foram preservadas.")
            os.replace(old, out)
    pn.mirror_to_vault(p.configuration()["vault"], manifest, source)
    for record in records:
        assert p.digest(p.target(dest, record["path"])) == record["sha256"]
    return records
