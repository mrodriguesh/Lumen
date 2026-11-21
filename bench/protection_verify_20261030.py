"""Read-only personal hierarchy audit and fresh independent recovery from existing test IDs.

No uploads, new Notion pages, original-source reads during restore or exported keys in outputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.parse

PROJECT = Path(__file__).resolve().parents[1]
OLD = Path(r"D:\Aplicativos\Lumen-protecao-validacao-20261028")
OUT = Path(r"D:\Aplicativos\Lumen-protecao-validacao-20261030")
sys.path.insert(0, str(PROJECT))


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=1), "utf-8")


def hierarchy():
    from lumen import protection as p, protection_notion as pn
    from PIL import Image
    s = p.state(); source = p.HOME / "capture/notion"
    m = p.read(source / "manifest.json"); dest = Path(s["notion_obsidian"]["path"])
    mark = p.read(dest / p.MARKER); expected, missing = pn.vault_layout(m, source)
    paths = {**expected, **mark["pages"]}
    conflicts = set(s["notion_obsidian"].get("conflicts", []))
    for iid in paths:
        if iid + ".md" in conflicts: paths[iid] = iid + ".md"
    bad, broken, images, examples = [], [], [], []
    links = hashes = 0
    for iid, rel in paths.items():
        f = dest / rel
        if not f.exists(): bad.append(rel); continue
        if rel not in conflicts:
            wanted = pn.mirror_markdown((source / (iid + ".md")).read_bytes(), rel, paths)
            if f.read_bytes() != wanted: bad.append(rel)
            hashes += 1
        for link in re.findall(r"\]\(([^)\n]+)\)", f.read_text("utf-8")):
            u = urllib.parse.urlsplit(link)
            if not u.scheme and not u.netloc and (u.path.endswith(".md") or "Anexos/" in u.path or "attachments/" in u.path):
                links += 1
                if not (f.parent / urllib.parse.unquote(u.path)).is_file(): broken.append({"note": m["items"][iid]["title"], "path": rel, "link": link})
        if len(examples) < 6 and len(Path(rel).parts) >= 4:
            examples.append({"title": m["items"][iid]["title"], "path": rel, "characters_read": len(f.read_text("utf-8"))})
    for rel, sha in mark["files"].items():
        if rel in conflicts: continue
        assert (dest / rel).is_file() and p.digest(dest / rel) == sha, rel
        hashes += 1
        if rel.startswith("Anexos/") and Path(rel).suffix.lower() in (".png", ".jpg", ".jpeg") and len(images) < 4:
            with Image.open(dest / rel) as im: im.load(); images.append({"path": rel, "size": im.size})
    report = {"at": p.now(), "captured": len(m["items"]), "organized": len(mark["pages"]),
              "readable": len(paths), "missing_or_mismatched": bad, "missing_ancestors": missing,
              "links_checked": links, "broken_links": broken, "hashes_checked": hashes,
              "max_depth": max(len(Path(x).parts)-1 for x in expected.values()),
              "roots": [x.name for x in (dest / "Particular").glob("*.md")], "notes_opened": examples,
              "images_decoded": images, "differences": p.attention_details()["items"],
              "workspace_complete_claimed": False}
    write("hierarquia-final.json", report)
    print(json.dumps({k: report[k] for k in ("captured", "organized", "readable", "links_checked", "hashes_checked", "max_depth")}), flush=True)


def checked(folder):
    from PIL import Image
    count, images, notes = 0, 0, 0
    for source in ("notion", "obsidian"):
        base = folder / source
        if not base.is_dir(): continue
        m = json.loads((base / "manifest.json").read_text("utf-8"))
        for rel, item in m["items"].items():
            for name, sha in (item.get("files") or {"files/" + rel: item["sha256"]}).items():
                f = base / name
                assert hashlib.sha256(f.read_bytes()).hexdigest() == sha
                count += 1
                if f.suffix == ".md": f.read_text("utf-8"); notes += 1
                if f.suffix == ".png":
                    with Image.open(f) as im: im.load(); images += 1
    assert count
    return {"files": count, "notes_read": notes, "images_decoded": images}


def recovery():
    os.environ["LUMEN_DATA"] = str(OLD / "native")
    from lumen import protection as p, protection_drive as pd, protection_notion as pn, notion, store
    assert p.configuration()["vault"] == str(OLD / "cofre-teste") and not p.configuration()["enabled"]
    versions = {v["source"]: v for v in p.state()["versions"]}
    target = OUT / "recuperacao-independente"; target.mkdir(exist_ok=True)
    secret = json.loads((OLD / "chaves-separadas/Lumen-chave-recuperacao.json").read_text("utf-8"))["password"]
    result = {}
    for source, version in versions.items():
        clean = target / source; clean.mkdir()
        # Real Drive readback and fresh download of already existing immutable objects.
        pd.verify_catalog(version["drive"])
        downloaded, catalog = pd.download_repository(version["drive"]["id"], clean)
        objects = clean / "objects"; objects.mkdir()
        shutil.copyfile(downloaded / "catalog.json", clean / "catalog.json")
        shutil.copyfile(PROJECT / "docs/recuperar-drive.py", clean / "recuperar-drive.py")
        for obj in catalog["objects"]:
            shutil.copyfile(downloaded / "repository" / obj["path"], objects / ("object-" + obj["sha256"] + ".bin"))
        assembled = clean / "repository"
        run = subprocess.run([sys.executable, "-I", str(clean / "recuperar-drive.py"), str(clean / "catalog.json"), str(objects), str(assembled)], capture_output=True)
        assert run.returncode == 0
        env = {k: v for k,v in os.environ.items() if not k.startswith(("RESTIC_", "LUMEN_", "NOTION_", "GOOGLE_"))}
        env.update(RESTIC_PASSWORD=secret, GOMAXPROCS="2")
        for place, repo, sid in (("drive", assembled, catalog["snapshot"]), ("local", Path(version["local"]["path"]) / "repository", version["local"]["snapshot"])):
            restored = clean / (place + "-restored")
            for args in (("check", "--read-data"), ("snapshots", "--json"), ("restore", sid, "--target", str(restored))):
                run = subprocess.run([str(p.RESTIC), "--no-cache", "-r", str(repo), *args], env=env, cwd=clean, capture_output=True, timeout=180)
                assert run.returncode == 0, "Independent Restic operation failed"
            result[source + "_" + place] = {**checked(restored), "path": str(restored), "snapshot": sid}
        # Incorrect key must fail even for the downloaded repository.
        env["RESTIC_PASSWORD"] = "incorrect-isolated-validation-key"
        run = subprocess.run([str(p.RESTIC), "--no-cache", "-r", str(assembled), "snapshots"], env=env, capture_output=True, timeout=60)
        assert run.returncode != 0
        result[source + "_objects"] = len(catalog["objects"])
        write("recuperacao-real.json", {"at": p.now(), "results": result, "source_or_cache_used_during_restore": False, "wrong_key_rejected": True, "key_separate": True})
        print(source + ": local and fresh Drive recovery verified", flush=True)
    # Persisted Notion mirror and original attachment readback using existing IDs only.
    journal = p.read(p.HOME / "notion-mirror.json")
    token = store.get_token(); readbacks = []
    for key, entry in journal.items():
        if not key.startswith("item-") or not entry.get("source_hash"): continue
        blocks = pn.tree(token, entry["id"])
        assert pn.hash_json(blocks) == entry["hash"]
        attachments = 0
        for b in blocks:
            if b["type"] in ("file", "image", "pdf"):
                url = b[b["type"]].get("file", {}).get("url")
                if url:
                    assert pn.fetch_file(url, target / ("notion-attachment-" + entry["id"])) == entry["source_hash"]
                    attachments += 1
        readbacks.append({"page": entry["id"], "blocks_match": True, "attachments_verified": attachments})
        if len(readbacks) >= 3: break
    write("notion-readback-real.json", {"at": p.now(), "pages": readbacks, "created_pages": 0, "uploads": 0})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("action", choices=("hierarchy", "recovery")); args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    (hierarchy if args.action == "hierarchy" else recovery)()
