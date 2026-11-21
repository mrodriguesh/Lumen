"""One-time repair (20/11/2026): Notion -> Obsidian mirror files the Lumen wrote itself, in runs stopped before
the final receipt, were reported as user edits ("conflicts") forever.

For each page in the conflict list, the encrypted snapshot of the same reading is opened. A file counts as the
Lumen's own write only when it matches that snapshot (Markdown: equal apart from link targets, which the mirror
rewrites; JSON and attachments: same SHA-256). Those get their receipt back so the next mirror run updates them;
anything else is left alone.

    python bench/protection_repair_mirror_receipts_20261120.py           # read-only report
    python bench/protection_repair_mirror_receipts_20261120.py --apply   # Lumen must be closed
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumen import protection as p  # noqa: E402

LINK = re.compile(r"\]\([^)\n]+\)")


def dump(sid, name):
    return p.run_restic(p.HOME / "repository", "dump", sid, "notion/" + name).replace("\r\n", "\n")  # text-mode pipe adds CR


def main(apply):
    s = p.state()
    dest = Path(s["notion_obsidian"]["path"])
    mark = p.read(dest / p.MARKER)
    pages, receipts = mark.get("pages", {}), mark.get("files", {})
    owner_of = {rel: iid for iid, rel in pages.items()}
    owner_of.update({"Dados originais/" + iid + ".json": iid for iid in pages})
    notion_versions = [v for v in s["versions"] if v["source"] == "notion"]
    ours, kept, unclaimed = {}, [], []
    owners = []
    for rel in sorted(set(s["notion_obsidian"].get("conflicts", []))):
        iid = owner_of.get(rel)
        if iid and iid not in owners:
            owners.append(iid)
        elif not iid:
            unclaimed.append(rel)
    for iid in owners:
        page = dest / pages[iid]
        text = page.read_text("utf-8") if page.is_file() else ""
        stamp = re.search(r"Captura: (\S+)", text)
        sid = original = None
        for v in [v for v in notion_versions if stamp and v["captured"] >= stamp[1]][:4]:
            md = dump(v["id"], iid + ".md")
            if stamp[0] in md:
                sid, original = v["id"], md
                break
        if not sid:
            kept.append((pages[iid], "no snapshot of this reading"))
            continue
        item = json.loads(dump(sid, "manifest.json"))["items"][iid]
        outputs = {pages[iid]: None, "Dados originais/" + iid + ".json": item["files"].get(iid + ".json")}
        outputs.update({"Anexos/" + n[len("attachments/"):]: sha for n, sha in item["files"].items() if n.startswith("attachments/")})
        for rel, sha in outputs.items():
            f = dest / rel
            if not f.is_file() or p.digest(f) == receipts.get(rel):
                continue
            same = (LINK.sub("]()", original) == LINK.sub("]()", f.read_text("utf-8"))) if sha is None else p.digest(f) == sha
            if same:
                ours[rel] = p.digest(f)
            else:
                kept.append((rel, "differs from the snapshot: possible user edit"))
    kept += [(rel, "no owner page") for rel in unclaimed]
    print(f"Lumen's own writes: {len(ours)}; left untouched: {len(kept)}")
    for rel, why in kept:
        print("  kept:", rel, "-", why)
    if not apply or not ours:
        return
    try:
        with (p.HOME / "controller.lock").open("r+b") as lock:
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        sys.exit("Close the Lumen first: its backup controller is running.")
    backup = p.HOME / "mirror-marker-before-repair-20261120.json"
    shutil.copy2(dest / p.MARKER, backup)
    mark = p.read(dest / p.MARKER)  # reread right before writing
    mark.setdefault("files", {}).update(ours)
    p.write(dest / p.MARKER, mark)
    print("Receipts restored. Previous marker kept at", backup)


if __name__ == "__main__":
    main("--apply" in sys.argv)
