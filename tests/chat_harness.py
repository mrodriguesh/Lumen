"""Servidor REAL e isolado para as verificações da Conversa rápida: LUMEN_DATA temporário, cofre Obsidian de teste, Ollama falso que
transmite de verdade, sem Notion nem chaves do usuário. Usado por tests/chat_compact.py (geometria) — tests/chat_ui.py tem a sua cópia.

    with serve(ROOT, ART) as H:  H.url, H.call(path, body), H.fakectl(**kw)

ROOT pode ser outra cópia do projeto (a regressão roda também contra o código ANTIGO para provar que o teste falha com ele)."""
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

BOOT = r"""
import sys, threading
sys.path.insert(0, sys.argv[1])
from tests.fake_ollama import FakeOllama
fake = FakeOllama()
fake.models.append("qwen3.5:4b")
from lumen import server, store, obsidian
store.get_token = lambda: ""           # nunca o token real do Notion
from lumen.study import settings
settings.api_key = lambda *a, **kw: ""  # nem as chaves reais dos provedores externos
cfg = store.load_config(); cfg["obsidian_vault"] = sys.argv[2]; store.save_config(cfg)
OPENED = []
obsidian.open_path = lambda p: OPENED.append(str(p))   # o Obsidian de verdade nunca é aberto pelo teste
def _fake(h):
    b = h._json()
    if "answer" in b: fake.answer = b["answer"]
    if "delay" in b: fake.delay = float(b["delay"])
    if "models" in b: fake.models[:] = b["models"]
    if b.get("hold") is not None:
        fake.gate = threading.Event(); fake.hold_after = int(b["hold"])
    if b.get("release") and fake.gate is not None:
        fake.gate.set()
    if b.get("reset"):
        fake.gate = None; fake.delay = 0.0
    chats = [r for r in fake.requests if r[0] == "/api/chat" and not r[1].get("format")]
    return {"ok": True, "chat_requests": len(chats), "opened": OPENED}
server.ROUTES[("POST", "/api/study/__fake")] = _fake
h = server.serve(); print(h.server_port, flush=True); h.serve_forever()
"""

LONG = ("## Como o sono ajuda a memória\n\nDurante o **sono profundo** o hipocampo reativa o que você viveu [S1]. Veja também a "
        "[página do tema](https://example.org/sono/um-endereco-muito-longo-que-nao-pode-alargar-o-painel/de/jeito/nenhum/nem-um-pouco/abcdefghijklmnopqrstuvwxyz).\n\n"
        "- Codificação: o cérebro grava o novo\n- Consolidação: as ondas lentas reativam\n- Evocação: a lembrança fica no córtex\n\n"
        "```python\ndef consolidar(memoria, sono):\n    return memoria if sono >= 7 else None  # uma linha bem comprida para provar a rolagem horizontal do bloco\n```\n\n"
        "| Fase | Papel | Observação comprida que obriga a tabela a rolar por dentro |\n| --- | --- | --- |\n| N3 | consolida | ondas lentas |\n| REM | integra | sonhos vívidos e emoções |\n\n"
        "> Dormir bem depois de estudar vale mais que mais uma hora de revisão.\n\n"
        + " ".join(f"palavra{n}" for n in range(120)))


def note(vault, rel, text):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


@contextmanager
def serve(root, art):
    root = Path(root)
    with tempfile.TemporaryDirectory(prefix="chat-compact-") as temp:
        vault = Path(temp) / "Cofre de teste"
        (vault / ".obsidian").mkdir(parents=True)
        note(vault, "B02 Estudos/Memória e sono.md", "---\ntype: permanent\ntags: [psicologia]\n---\n# Memória e sono\nA consolidação da memória depende do sono profundo. Ver [[Atenção]].")
        note(vault, "Atenção.md", "# Atenção\nFoco seletivo e memória de trabalho.")
        env = {**os.environ, "LUMEN_DATA": str(Path(temp) / "data"), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
        log = (Path(art) / "backend.log").open("w", encoding="utf-8")
        proc = subprocess.Popen([str(root / ".venv/Scripts/python.exe"), "-u", "-c", BOOT, str(root), str(vault)], cwd=root, env=env,
                                stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            url = "http://127.0.0.1:" + proc.stdout.readline().strip()
            token = {"v": None}

            def call(path, body=None):
                if token["v"] is None:
                    html = urllib.request.urlopen(url + "/widget").read().decode()
                    token["v"] = re.search(r'name="lumen-token" content="([^"]+)"', html).group(1)
                req = urllib.request.Request(url + path, headers={"X-Lumen-Token": token["v"], "Content-Type": "application/json"})
                if body is not None:
                    req.data = json.dumps(body).encode()
                return json.loads(urllib.request.urlopen(req).read() or b"{}")

            call("/api/study/sources", {"action": "sync", "source": "obsidian"})
            for _ in range(120):
                st = call("/api/study/state")
                if not st["index"]["running"] and st["counts"].get("documents", st["counts"].get("docs", 1)):
                    break
                time.sleep(0.5)
            time.sleep(1.0)
            yield SimpleNamespace(url=url, call=call, fakectl=lambda **kw: call("/api/study/__fake", kw), vault=vault)
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()
