"""Custo da 1ª fala de uma chamada para o reconhecedor (Parakeet CPU int8), com e sem o aquecimento da preparação.

  .venv\\Scripts\\python bench/asr_first_utterance.py old   # carrega o modelo e só então recebe a 1ª fala (como era)
  .venv\\Scripts\\python bench/asr_first_utterance.py new   # `CallManager._warm_asr_safe` (carrega + inferência de mentira) e depois a 1ª fala

Cada modo roda num processo novo (o 1º uso de um modelo ONNX no processo é o que custa). Dados num diretório único; só CPU; fala sintética."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="asr-first-", dir=r"D:\Lumen\cache")
os.environ["LUMEN_DATA"] = tmp
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from lumen import voice  # noqa: E402
from lumen.study import call  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else "new"
a, sr = voice.read_wav(Path(r"D:\Lumen\voz\amostras-chamada\01_sono.wav"))
a = np.asarray(a, dtype=np.float32)
a = a.mean(axis=1) if a.ndim > 1 else a
a = np.interp(np.linspace(0, a.size - 1, int(round(a.size * 16000 / sr)), dtype=np.float32), np.arange(a.size, dtype=np.float32), a).astype(np.float32)

t0 = time.monotonic()
if mode == "old":
    call._load_call_asr("parakeet")
else:
    cm = call.CallManager()
    cm._s = {"call_asr": "parakeet"}
    cm._warm_asr_safe()
prep_s = time.monotonic() - t0
text, ms, eng = call.transcribe_call_audio(a, "parakeet")
text2, ms2, _ = call.transcribe_call_audio(a, "parakeet")
print(json.dumps({"mode": mode, "preparacao_s": round(prep_s, 2), "1a_fala_asr_ms": ms, "2a_fala_asr_ms": ms2, "motor": eng, "texto": text[:60]}, ensure_ascii=False))
