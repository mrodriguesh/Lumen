"""Gravação controlada com áudio sintético; nenhum microfone, som pessoal ou tela é capturado."""
import json
import os
import sys
import threading
import time
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(r"D:\Aplicativos\Lumen-protecao-validacao-20261028") / "gravacao-controlada"
ROOT.mkdir(exist_ok=True)
os.environ["LUMEN_DATA"] = str(ROOT / "profile")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from lumen import protection as p, record, store


class Synthetic:
    def __init__(self):
        self.deadline = None
        self.count = 0
        self.maximum_lag = 0
    def record(self, numframes):
        if self.deadline is None:
            self.deadline = time.monotonic()
        self.deadline += numframes / record.RATE
        time.sleep(max(0, self.deadline - time.monotonic()))
        self.maximum_lag = max(self.maximum_lag, time.monotonic() - self.deadline)
        samples = np.arange(numframes) + self.count
        self.count += numframes
        return np.repeat((.08 * np.sin(samples * 2 * np.pi * 440 / record.RATE))[:, None], 2, axis=1)
    def __exit__(self, *args): pass


vault = ROOT / "vault"; vault.mkdir(exist_ok=True)
dest = ROOT / "destination"; dest.mkdir(exist_ok=True)
store.save_config({**store.DEFAULTS, "watch_screen": False})
p.configure(vault=str(vault), roots=[], enabled=True)
(vault / "aula-teste.md").write_text("Conteúdo original de teste durante gravação. " + p.now(), "utf-8")
old_versions = {v["id"] for v in p.state().get("versions", [])}
controller = p.Controller()
recorder = Synthetic()
with mock.patch.object(p, "password", return_value="isolated-recording-validation-not-a-real-secret"), mock.patch.object(record, "_open_recorder", return_value=recorder):
    p.choose_local(dest)
    start = time.monotonic()
    record.start("TESTE audio sintetico 440Hz")
    wav = record._state["path"]
    for name, fn, seconds in (("obsidian", controller.vault_cycle, 60), ("local", p.deliver_local, 5)):
        thread = threading.Thread(target=controller.loop, args=(name, fn, seconds), daemon=True, name="Lumen protection " + name)
        controller.threads.append(thread); thread.start()
    try:
        deadline = start + 75
        while time.monotonic() < deadline:
            versions = p.state().get("versions", [])
            if versions and versions[-1]["id"] not in old_versions and versions[-1].get("local"):
                break
            time.sleep(.25)
        assert versions and versions[-1].get("local"), p.state()
        assert record.active() and not record.status().get("error")
        elapsed = time.monotonic() - start
        with wave.open(str(wav), "rb") as f:
            duration = f.getnframes() / f.getframerate()
        assert abs(duration - elapsed) < 1.5, (duration, elapsed)
        assert recorder.maximum_lag < .5, recorder.maximum_lag
        report = {"at": p.now(), "synthetic_audio": True, "real_device_tested": False,
            "elapsed_seconds": elapsed, "wav_seconds": duration, "max_capture_lag_seconds": recorder.maximum_lag,
            "backup_completed_while_recording": True, "state": p.state(), "wav": str(wav)}
        p.write(ROOT / "evidencias.json", report)
        print(json.dumps({k:v for k,v in report.items() if k != "state"}), flush=True)
    finally:
        controller.stop()
        record.stop()
