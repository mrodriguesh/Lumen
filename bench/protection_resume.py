"""Continuação da prova real, somente o perfil e os IDs de teste já existentes.

Não inicia controladores, não recria áreas, não consulta o cofre pessoal e não imprime chaves.
"""
import argparse
import ctypes
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(r"D:\Aplicativos\Lumen-protecao-validacao-20261028")
os.environ["LUMEN_DATA"] = str(ROOT / "native")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lumen import protection as p, protection_notion as pn, protection_drive as pd, notion, store, server

REPORT = ROOT / "evidencias-retomada.json"


def save(key, value):
    report = p.read(REPORT)
    report[key] = value
    p.write(REPORT, report)
    print(json.dumps({key: value}, ensure_ascii=True), flush=True)


def api(body=None, path="/api/protection"):
    url = "http://127.0.0.1:" + (store.DATA / "port.txt").read_text().strip()
    html = urllib.request.urlopen(url, timeout=5).read().decode()
    token = re.search(r'name="lumen-token" content="([^"]+)"', html)[1]
    req = urllib.request.Request(url + path, json.dumps(body).encode() if body else None,
        headers={"X-Lumen-Token": token, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=45))


def handler(action, **body):
    h = mock.Mock()
    h._json.return_value = {"action": action, **body}
    return server._protection_action(h)


def visible(pid):
    user = ctypes.windll.user32
    result = []
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each(hwnd, _):
        process = ctypes.c_ulong()
        user.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(process))
        if process.value == pid:
            result.append({"visible": bool(user.IsWindowVisible(ctypes.c_void_p(hwnd))),
                           "minimized": bool(user.IsIconic(ctypes.c_void_p(hwnd)))})
        return True
    user.EnumWindows(callback(each), 0)
    return result


def prepare():
    widget = api(path="/api/widget")
    assert not widget["recording"]["active"] and widget["job"]["status"] != "running"
    assert not p.configuration()["enabled"]
    old = p.configuration()["local"]
    destination = ROOT / "destino-native-final"
    destination.mkdir(exist_ok=True)
    key = ROOT / "chaves-separadas" / "Lumen-chave-recuperacao.json"
    key.parent.mkdir(exist_ok=True)
    with mock.patch.object(server, "_protection_folder", return_value=str(destination)):
        handler("choose")
    with mock.patch.object(server, "_protection_dialog", return_value=str(key)):
        handler("export-key")
        handler("import-key")
    save("preparation", {"at": p.now(), "previous_destination_preserved": Path(old).is_dir(),
        "destination": p.configuration()["local"], "exported_key": str(key),
        "export_import_handlers": True, "native_dialog_selection_tested": False})


def change(label):
    report = p.read(REPORT)
    if report.get(label):
        raise RuntimeError("Esta alteração já está registrada; retome a observação.")
    vault = Path(p.configuration()["vault"])
    file = vault / "Continuidade automatica - TESTE.md"
    body = "# Teste isolado\nCiclo " + label + " em " + p.now() + "\n"
    file.write_text(body, "utf-8")
    save(label, {"at": p.now(), "path": str(file), "sha256": p.digest(file), "text": body})


def change_notion(label):
    report = p.read(REPORT)
    if report.get(label):
        raise RuntimeError("Alteração Notion já registrada.")
    previous = p.read(ROOT / "evidencias.json")
    token = store.get_token()
    blocks = notion.all_children(token, previous["source_page"])
    block = next(b for b in blocks if b["type"] == "paragraph")
    text = "Notion: teste isolado de latência " + label + " " + p.now()
    notion.request("PATCH", "/blocks/" + block["id"], token, {"paragraph": {"rich_text": notion._rt(text)}})
    save(label, {"at": p.now(), "page": previous["source_page"], "text": text})


def observe(label, source):
    change = p.read(REPORT)[label]
    deadline = time.monotonic() + 600
    observations = []
    last_capture = None
    while time.monotonic() < deadline:
        state = p.state()
        latest = next((v for v in reversed(state.get("versions", [])) if v["source"] == source), {})
        capture = p.read(p.HOME / "capture" / source / "manifest.json")
        stamp = state.get(source, {}).get("captured")
        if stamp != last_capture:
            observations.append({"seen": p.now(), "capture": stamp, "poll_seconds": state.get("notion", {}).get("poll_seconds")})
            last_capture = stamp
        if source == "obsidian":
            item = capture.get("items", {}).get(Path(change["path"]).name, {})
            journal = p.read(p.HOME / "notion-mirror.json")
            mirror = journal.get("file-" + item.get("id", ""), {})
            matched = item.get("sha256") == change["sha256"]
            mirror_ok = any(v.get("source_hash") == change["sha256"] for v in journal.values() if isinstance(v, dict))
        else:
            item = capture.get("items", {}).get(change["page"], {})
            raw = p.HOME / "capture/notion" / (change["page"] + ".json")
            matched = raw.exists() and change["text"] in raw.read_text("utf-8")
            copy = Path(p.configuration()["vault"]) / "Lumen - Backup do Notion" / (change["page"] + ".md")
            mirror_ok = copy.exists() and change["text"] in copy.read_text("utf-8")
        if matched and latest.get("local") and latest.get("drive") and mirror_ok and latest.get("captured", "") > change["at"]:
            save(label + "_completed", {"at": p.now(), "source": source, "version": latest,
                "capture": state.get(source), "mirror": state.get("obsidian_notion" if source == "obsidian" else "notion_obsidian"),
                "observations": observations})
            return
        time.sleep(2)
    raise RuntimeError("Ciclo ainda pendente; consulte state.json, sem repetir a alteração.")


def idle():
    stamps = []
    deadline = time.monotonic() + 260
    while time.monotonic() < deadline and len(stamps) < 4:
        current = p.state().get("notion", {})
        if current.get("captured") and (not stamps or stamps[-1]["captured"] != current["captured"]):
            stamps.append({k: current.get(k) for k in ("captured", "poll_seconds", "signature")})
        time.sleep(2)
    assert len(stamps) == 4, stamps
    save("notion_idle_measurement", stamps)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "change", "change-notion", "observe", "status", "start", "pause", "hidden", "idle"])
    parser.add_argument("--label", default="hidden_file")
    parser.add_argument("--source", choices=["obsidian", "notion"], default="obsidian")
    parser.add_argument("--pid", type=int)
    args = parser.parse_args()
    assert p.HOME == ROOT / "native/Lumen/protection"
    assert Path(p.configuration()["vault"]) == ROOT / "cofre-teste"
    if args.action == "prepare": prepare()
    elif args.action == "idle": idle()
    elif args.action == "change": change(args.label)
    elif args.action == "change-notion": change_notion(args.label)
    elif args.action == "observe": observe(args.label, args.source)
    elif args.action == "hidden": save("native_windows_" + args.label, {"at": p.now(), "pid": args.pid, "windows": visible(args.pid)})
    elif args.action in ("start", "pause"):
        result = api({"action": args.action}); print(json.dumps({"enabled": result["config"]["enabled"]}))
    else:
        v = api(); print(json.dumps({"enabled": v["config"]["enabled"], "states": {k:v['state'].get(k) for k in ('obsidian','notion','local','drive','obsidian_notion','notion_obsidian')}}, ensure_ascii=True))
