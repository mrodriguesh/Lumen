"""Fase 6 (D46 a D52): o Voice Studio como motor de voz. Roda com o .venv do Lúmen e o Voice Studio aberto.

    .venv\\Scripts\\python bench/voicestudio_bench.py roteiro   # o roteiro de 106 palavras (voice_bench.SCRIPT): A e B
    .venv\\Scripts\\python bench/voicestudio_bench.py chat      # tempo até o primeiro som: HTTP frase a frase × /ws/tts
    .venv\\Scripts\\python bench/voicestudio_bench.py cegas     # A (pt), B (sem idioma), C (Chatterbox, D44) às cegas
    .venv\\Scripts\\python bench/voicestudio_bench.py passos    # num_step 8, 12, 16, 24, 32 e o /ws/tts (D56)

Saída em D:\\Lumen\\voz\\amostras-vs (bruto\\*.wav e *.json; no fim, X.wav, Y.wav, Z.wav e chave.json). O erro de
palavras usa a transcrição do próprio Lúmen (large-v3-turbo), como em D44. A VRAM é a do PC inteiro (nvidia-smi)."""
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

import numpy as np  # noqa: E402

from lumen import voice, voicestudio  # noqa: E402

_env = {k: os.environ.get(k) for k in ("HF_HOME", "TORCH_HOME")}
from voice_bench import SCRIPT, Peak, save  # noqa: E402 — ele aponta o HF_HOME para os modelos de voz
for _k, _v in _env.items():  # o Whisper do Lúmen fica no cache padrão: volta ao que era
    os.environ.pop(_k, None) if _v is None else os.environ.__setitem__(_k, _v)

OUT = Path(r"D:\Lumen\voz\amostras-vs")
RAW = OUT / "bruto"
JHONNY = "1faf41ee"
ANSWER = ("Keyframes são pontos na linha do tempo que guardam um valor, como a posição ou a escala de um clipe. "
          "Você cria o primeiro no painel Effect Controls, clicando no cronômetro ao lado da propriedade. "
          "Depois, move a agulha e muda o valor: o Premiere cria o segundo keyframe sozinho. "
          "Entre os dois, ele calcula o caminho, e o elemento se move.")


def wer_of(path, text):
    from lumen import transcribe
    model = transcribe._model("large-v3-turbo", "cuda")
    segs, _ = model.transcribe(str(path), language="pt", beam_size=5, vad_filter=False)
    ref, hyp = voice.words(text), voice.words(" ".join(s.text for s in segs))
    return round(voice._wer(ref, hyp), 3), len(ref), len(hyp)


def roteiro(name, language):
    """O roteiro inteiro, frase a frase, com as mesmas pausas do voice_bench (volume igualado no fim)."""
    RAW.mkdir(parents=True, exist_ok=True)
    peak, parts, gen, spoken, per = Peak(), [], 0.0, 0.0, []
    with tempfile.TemporaryDirectory(prefix="lumen-vsb-") as d:
        voicestudio.speak("Aquecendo.", Path(d) / "w.wav", JHONNY, language=language, seed=1)
        for i, item in enumerate(SCRIPT):
            if isinstance(item, float):
                parts.append(np.zeros(int(24000 * item), np.float32))
                continue
            out = Path(d) / f"{i}.wav"
            t = time.perf_counter()
            secs = voicestudio.speak(item, out, JHONNY, language=language, seed=1)
            took = time.perf_counter() - t
            gen, spoken = gen + took, spoken + secs
            per.append({"fala_s": round(secs, 2), "geracao_s": round(took, 2)})
            a, sr = voice.read_wav(out)
            parts += [a, np.zeros(int(sr * 0.35), np.float32)]
    audio = np.concatenate(parts)
    save(RAW / f"{name}.wav", audio, 24000)
    text = " ".join(x for x in SCRIPT if isinstance(x, str))
    wer, n_ref, n_hyp = wer_of(RAW / f"{name}.wav", text)
    out = {"motor": "voicestudio", "voz": "Jhonny (1faf41ee)", "language": language, "geracao_s": round(gen, 1),
           "fala_s": round(spoken, 1), "geracao_por_s_de_fala": round(gen / spoken, 2),
           "geracao_por_min_de_audio_s": round(60 * gen / spoken, 1), "vram_gb": peak.done(), "wer": wer,
           "palavras": [n_ref, n_hyp], "frases": per}
    (RAW / f"{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "frases"}, ensure_ascii=False))


def chat():
    """Tempo até o primeiro som de uma resposta de 4 frases, 3 vezes em cada caminho (modelo já carregado)."""
    sents = voice.sentences(voice.speakable(ANSWER))
    res = {"http": [], "ws": [], "ws_por_frase": []}
    with tempfile.TemporaryDirectory(prefix="lumen-vsb-") as d:
        voicestudio.speak("Aquecendo.", Path(d) / "w.wav", JHONNY, language="pt", seed=1)
        for _ in range(3):
            t = time.perf_counter()
            voicestudio.speak(sents[0], Path(d) / "a.wav", JHONNY, language="pt", seed=1)
            res["http"].append(round(time.perf_counter() - t, 2))
            t, first = time.perf_counter(), None  # o texto inteiro num pedido: o Voice Studio divide as frases
            for _chunk in voicestudio.stream(ANSWER, JHONNY, language="pt"):
                first = first or round(time.perf_counter() - t, 2)
            res["ws"].append(first)
            t, first = time.perf_counter(), None  # uma frase por pedido, como o chat faz
            for _chunk in voicestudio.stream(sents[0], JHONNY, language="pt"):
                first = first or round(time.perf_counter() - t, 2)
            res["ws_por_frase"].append(first)
    res["mediana"] = {k: float(np.median(v)) for k, v in res.items()}
    (RAW / "chat.json").parent.mkdir(parents=True, exist_ok=True)
    (RAW / "chat.json").write_text(json.dumps(res, indent=1), "utf-8")
    print(json.dumps(res))


def passos(steps=(8, 12, 16, 24, 32)):
    """Fase 6, parte 2 (D56): os passos (num_step) do /v1/audio/speech. Para cada valor: o roteiro inteiro (tempo,
    erro de palavras, VRAM) e o 1º som de uma frase de chat em PCM (3 vezes); no fim, o /ws/tts (16 passos fixos) com
    uma conexão por frase e com o texto inteiro, para comparar. Modelo quente (um pedido de aquecimento antes)."""
    RAW.mkdir(parents=True, exist_ok=True)
    sents = voice.sentences(voice.speakable(ANSWER))
    text = " ".join(x for x in SCRIPT if isinstance(x, str))
    res = {"roteiro": {}, "primeiro_som_pcm": {}}
    with tempfile.TemporaryDirectory(prefix="lumen-vsb-") as d:
        voicestudio.speak("Aquecendo.", Path(d) / "w.wav", JHONNY, language="pt", seed=1)
        for n in steps:
            peak, parts, gen, spoken = Peak(), [], 0.0, 0.0
            for i, item in enumerate(SCRIPT):
                if isinstance(item, float):
                    parts.append(np.zeros(int(24000 * item), np.float32))
                    continue
                out = Path(d) / f"{n}-{i}.wav"
                t = time.perf_counter()
                secs = voicestudio.speak(item, out, JHONNY, language="pt", seed=1, steps=n)
                gen, spoken = gen + time.perf_counter() - t, spoken + secs
                a, sr = voice.read_wav(out)
                parts += [a, np.zeros(int(sr * 0.35), np.float32)]
            save(RAW / f"passos-{n}.wav", np.concatenate(parts), 24000)
            wer, n_ref, n_hyp = wer_of(RAW / f"passos-{n}.wav", text)
            firsts = []
            for _ in range(3):
                t = time.perf_counter()
                voicestudio.synth(sents[0], JHONNY, language="pt", seed=1, steps=n, fmt="pcm")
                firsts.append(round(time.perf_counter() - t, 2))
            res["roteiro"][n] = {"geracao_s": round(gen, 1), "fala_s": round(spoken, 1), "por_s_de_fala": round(gen / spoken, 3),
                                 "wer": wer, "palavras": [n_ref, n_hyp], "vram_gb": peak.done()}
            res["primeiro_som_pcm"][n] = {"vezes": firsts, "mediana": float(np.median(firsts))}
            print(n, res["roteiro"][n], res["primeiro_som_pcm"][n], flush=True)
        ws1, wsall = [], []
        for _ in range(3):
            t, first = time.perf_counter(), None
            for _c in voicestudio.stream(sents[0], JHONNY, language="pt"):
                first = first or round(time.perf_counter() - t, 2)
            ws1.append(first)
            t, first = time.perf_counter(), None
            for _c in voicestudio.stream(ANSWER, JHONNY, language="pt"):
                first = first or round(time.perf_counter() - t, 2)
            wsall.append(first)
        res["ws_16_por_frase"] = {"vezes": ws1, "mediana": float(np.median(ws1))}
        res["ws_16_texto_inteiro"] = {"vezes": wsall, "mediana": float(np.median(wsall))}
    (RAW / "passos.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(res, ensure_ascii=False))


def blind_steps():
    """Escuta cega dos passos (D56): 8, 12 e 16 (os três mais rápidos sem erro relevante), com letras sorteadas."""
    out = Path(r"D:\Lumen\voz\amostras-passos")
    out.mkdir(parents=True, exist_ok=True)
    order = ["8", "12", "16"]
    for i in range(len(order) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        order[i], order[j] = order[j], order[i]
    key = {}
    for letter, n in zip("XYZ", order):
        shutil.copy(RAW / f"passos-{n}.wav", out / f"{letter}.wav")
        key[letter] = f"{n} passos"
    (out / "chave.json").write_text(json.dumps(key), "utf-8")
    print("Amostras:", ", ".join(str(out / f"{k}.wav") for k in key))


def blind():
    """A = pt, B = sem idioma, C = Chatterbox (a amostra da escuta de 01/11), com letras sorteadas (X, Y, Z)."""
    files = {"A-pt": RAW / "pt.wav", "B-auto": RAW / "auto.wav", "C-chatterbox": Path(r"D:\Lumen\voz\amostras\bruto\chatterbox.wav")}
    order = list(files)
    for i in range(len(order) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        order[i], order[j] = order[j], order[i]
    key = {}
    for letter, name in zip("XYZ", order):
        shutil.copy(files[name], OUT / f"{letter}.wav")
        key[letter] = name
    (OUT / "chave.json").write_text(json.dumps(key), "utf-8")
    print("Amostras:", ", ".join(str(OUT / f"{k}.wav") for k in key))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "roteiro":
        roteiro("pt", "pt")
        roteiro("auto", None)
    elif cmd == "chat":
        chat()
    elif cmd == "passos":
        passos()
    elif cmd == "cegas-passos":
        blind_steps()
    else:
        blind()
