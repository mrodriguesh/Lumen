"""One-time, authorized repair of the eight audited metadata differences; no source writes."""
import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from lumen import protection as p, store
from bench.protection_reconcile_metadata import reconcile

OUT = Path(r"D:\Aplicativos\Lumen-protecao-validacao-20261030")
before = p.read(OUT / "antes.json")
restore = Path(before["restore"])
config = p.configuration()
assert config["vault"] == r"D:\downloads\cerebro\Cerebro Oficial"
assert config["local"] == r"D:\Cerebro backup\Lumen - Protecao do cerebro"
assert not config["enabled"]
base = "http://127.0.0.1:" + (store.DATA / "port.txt").read_text().strip()
html = urllib.request.urlopen(base).read().decode()
token = re.search(r'name="lumen-token" content="([^"]+)"', html)[1]
def api(path, body=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body else None,
                                 headers={"X-Lumen-Token": token, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))

widget = api("/api/widget"); live = api("/api/protection")
assert not widget["recording"]["active"] and widget["job"]["status"] != "running"
assert not live["activity"] and live["state"]["operation"]["status"] != "running" and not live["config"]["enabled"]
dest = Path(live["state"]["notion_obsidian"]["path"])
audited = p.read(OUT / "divergencias-inspecao.json")
assert len(audited) == 8
for row in audited: assert p.digest(dest / row["path"]) == row["actual"]

manifest = {}
package = restore / "copia-notion-antes-reconciliacao.zip"
assert not package.exists(), "The existing restore point must not be replaced"
with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as z:
    for f in dest.rglob("*"):
        if not f.is_file(): continue
        raw = f.read_bytes(); rel = f.relative_to(dest).as_posix()
        if f.suffix == ".json":
            assert json.loads(raw).get("format") != "lumen-recovery-key-1", "Exported key must remain separate"
        manifest[rel] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        z.writestr(rel, raw)
with zipfile.ZipFile(package) as z:
    assert set(z.namelist()) == set(manifest)
    for rel, row in manifest.items():
        raw = z.read(rel); assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"]
p.write(restore / "copia-notion-sha256.json", manifest)
cfg_hashes = {name: p.digest(store.DATA / name) for name in before["personal_config_hashes"]}
assert cfg_hashes == before["personal_config_hashes"]
# Stop only the idle backup controller via its normal API, then hold the same exclusive lock.
api("/api/protection", {"action": "stop"})
controller = p.Controller()
try:
    controller.start()
    records = reconcile()
    counts = []
    from lumen import protection_notion as pn
    source = p.HOME / "capture/notion"; captured = p.read(source / "manifest.json")
    for _ in range(3):
        pn.mirror_to_vault(config["vault"], captured, source)
        counts.append(len(list(dest.rglob("*.md"))))
    assert len(set(counts)) == 1
    for row in records: assert p.digest(dest / row["path"]) == row["sha256"]
    assert {name: p.digest(store.DATA / name) for name in cfg_hashes} == cfg_hashes
    p.write(OUT / "reconciliacao-pessoal.json", {"at": p.now(), "archive": str(package), "verified_archive_files": len(manifest),
            "preserved": records, "note_counts_three_cycles": counts, "state": p.state()["notion_obsidian"], "config_unchanged": True,
            "controller_stopped_for_final_relaunch": True, "notion_source_writes": 0})
    print("Eight original files preserved byte-for-byte; hierarchy regenerated and repeated three times.")
finally:
    controller.stop()
