r"""Fase 8 real: Ollama existente, Edge visível e cofre temporário; nenhum envio ao Notion.
  .venv\Scripts\python.exe bench/study_agent_bench.py D:\Lumen\validacao-fase8-20261104
"""
import base64
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
import tests  # isola LUMEN_DATA e impede uso do Voice Studio real
from lumen import cdp, store
from lumen.study import agent, browser, chats, db, settings, writes

vault = Path(os.environ["LUMEN_DATA"]) / "cofre"
(vault / ".obsidian").mkdir(parents=True)
config = {**store.DEFAULTS, "obsidian_vault": str(vault)}
settings.save({"models": {"local": "qwen3.5:4b", "fast": "qwen3.5:4b", "fallback": "none"},
               "privacy": {"open_windows": True, "organize": "ai"},
               "search": {"web": True, "obsidian": True, "notion": False, "files": False},
               "memory": {"auto": False}})
report = {"started": db.now(), "model": "qwen3.5:4b", "data": os.environ["LUMEN_DATA"], "edge": str(cdp.edge()),
          "notion": "não chamado", "new_installations": []}
page = cdp._page

@contextmanager
def measured(*args, **kwargs):
    with page(*args, **kwargs) as (conn, sid, folder):
        report["visible_requested"] = kwargs.get("visible") is True
        report["profile"] = str(folder)
        report["browser_version"] = conn.call("Browser.getVersion")["product"]
        target = conn.call("Target.getTargetInfo", sid)["targetInfo"]["targetId"]
        report["window"] = conn.call("Browser.getWindowForTarget", targetId=target)
        yield conn, sid, folder
    report["profile_removed"] = not folder.exists()

start = time.monotonic()
try:
    with mock.patch.object(store, "load_config", return_value=config), mock.patch.object(store, "get_token", return_value=""), \
         mock.patch.object(cdp, "_page", measured), mock.patch.object(agent, "_after"):
        events = list(agent.turn({"text": "Python programming language", "mode": "chat", "web": True, "effort": "rapido"}, "bench-phase8"))
        report["seconds"] = round(time.monotonic() - start, 2)
        report["event_types"] = [e["type"] for e in events]
        if events[-1]["type"] != "done":
            raise RuntimeError(str(events[-1]))
        msg = events[-1]["message"]
        report["answer"] = msg["content"]
        report["sources"] = [{k: s.get(k) for k in ("title", "url", "cited")} for s in msg["sources"]]
        cid = next(e["conversation"]["id"] for e in events if e["type"] == "conversation")
        current = browser.state(cid)
        if current.get("image"):
            (out / "edge-real.jpg").write_bytes(base64.b64decode(current["image"].split(",")[1]))
        a = writes.prepare("obsidian-note", "Python — pesquisa medida", writes.note_markdown("Python", "Python programming language", msg["content"], msg["sources"]), cid)
        r = writes.finish(a, requested=True)
        note = vault / r["path"]
        (out / "nota-real.md").write_bytes(note.read_bytes())
        report["note_readback"] = note.is_file() and "https://" in note.read_text("utf-8")
        writes.undo(r["id"])
        report["undo"] = not note.exists() and bool(list((vault / ".trash").glob("lumen-*.md")))
        report["passed"] = report["note_readback"] and report["undo"] and any(s["cited"] for s in report["sources"])
except Exception as e:
    report.update(passed=False, error=f"{type(e).__name__}: {e}")
finally:
    report["total_seconds"] = round(time.monotonic() - start, 2)
    (out / "real.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=True), flush=True)
