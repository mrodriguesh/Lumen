"""Downloads reais, chave exportada e recuperação independente sem origens/cache/credenciais do Lúmen."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Aplicativos\Lumen-protecao-validacao-20261028")
os.environ["LUMEN_DATA"] = str(ROOT / "native")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lumen import protection as p, protection_drive as pd
from PIL import Image


def checked_files(folder):
    verified, pictures, notes = [], [], []
    for source in ("obsidian", "notion"):
        base = folder / source
        if not base.exists(): continue
        manifest = json.loads((base / "manifest.json").read_text("utf-8"))
        for rel, item in manifest["items"].items():
            for name, sha in (item.get("files") or {"files/" + rel: item["sha256"]}).items():
                file = base / name
                with file.open("rb") as stream:
                    assert hashlib.file_digest(stream, "sha256").hexdigest() == sha, name
                verified.append(name)
                if file.suffix.lower() == ".png":
                    with Image.open(file) as im: im.load(); pictures.append({"name": name, "size": im.size})
                if file.suffix.lower() == ".md": notes.append({"name": name, "characters": len(file.read_text("utf-8"))})
    assert verified
    return {"files": len(verified), "images_decoded": pictures, "notes_read": notes}


target = ROOT / "recuperacao-final"
target.mkdir(exist_ok=True)
key_file = ROOT / "chaves-separadas/Lumen-chave-recuperacao.json"
secret = json.loads(key_file.read_text("utf-8"))["password"]
versions = {v["source"]: v for v in p.state()["versions"]}
report = p.read(ROOT / "evidencias-retomada.json")
results = report.setdefault("final_recovery", {})
for source, version in versions.items():
    if source in results: continue
    assert version["local"] and version["drive"]
    local = p.restore(Path(version["local"]["path"]) / "repository", version["local"]["snapshot"], target, secret)
    local_check = checked_files(Path(local["path"]))
    downloaded, catalog = pd.download_repository(version["drive"]["id"], target)
    # Export only the downloaded artifacts and tool, then run a fresh process using the documented interface.
    clean = target / ("independente-" + source)
    clean.mkdir()
    objects = clean / "objects"; objects.mkdir()
    shutil.copyfile(downloaded / "catalog.json", clean / "catalog.json")
    shutil.copyfile(Path(__file__).parents[1] / "docs/recuperar-drive.py", clean / "recuperar-drive.py")
    for obj in catalog["objects"]:
        shutil.copyfile(downloaded / "repository" / obj["path"], objects / ("object-" + obj["sha256"] + ".bin"))
    assembled = clean / "repository"
    run = subprocess.run([sys.executable, "-I", str(clean / "recuperar-drive.py"), str(clean / "catalog.json"), str(objects), str(assembled)], capture_output=True)
    assert run.returncode == 0, "Falha no utilitário independente"
    env = {k:v for k,v in os.environ.items() if not k.startswith(("RESTIC_", "LUMEN_", "GOOGLE_", "NOTION_"))}
    env.update(RESTIC_PASSWORD=secret, RESTIC_CACHE_DIR=str(clean / "empty-cache"), GOMAXPROCS="2")
    restored = clean / "restored"
    for args in (("check", "--read-data"), ("restore", catalog["snapshot"], "--target", str(restored))):
        result = subprocess.run([str(p.RESTIC), "--no-cache", "-r", str(assembled), *args], env=env, cwd=clean, capture_output=True, timeout=180)
        assert result.returncode == 0, "Restic independente recusou o backup"
    verified = checked_files(restored)
    assert not (clean / "empty-cache").exists()
    results[source] = {"at": p.now(), "snapshot": version["id"], "local": {**local, **local_check},
        "drive": {"downloaded": str(downloaded), "restored": str(restored), "objects": len(catalog["objects"]), **verified},
        "standalone_script": True, "restic_no_cache": True, "key_from_exported_file": True,
        "original_sources_consulted_during_restore": False}
    current_report = p.read(ROOT / "evidencias-retomada.json")
    current_report["final_recovery"] = results
    p.write(ROOT / "evidencias-retomada.json", current_report)
    print(json.dumps({source: results[source]}, ensure_ascii=True), flush=True)
