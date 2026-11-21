"""Voz dos Estudos (fase 6, D44 a D46): o texto vira fala. O motor principal é o Voice Studio do estudante
(lumen/voicestudio.py, D46); a reserva local é o Chatterbox pt-br, num processo à parte (lumen/voice_worker.py, com o
Python do ambiente dele, como o imagegen roda o sd.cpp). Quem fala em cada uso é decidido em lumen/study/listen.py.

- speakable(): o que se lê em voz alta. Sem Markdown, sem [S#], sem código; títulos e itens viram frases.
- sentences(): frases curtas. O motor gera uma frase por vez, o que deixa a fala começar cedo e parar no meio.
- Engine: o processo do motor, aberto no primeiro uso e fechado depois de IDLE segundos sem uso (devolve a VRAM).
- synth(): uma frase → WAV. O Chatterbox às vezes balbucia depois da última palavra (medido, D45); com `verify`, o
  Whisper confere a frase e, se sobrar palavra ou faltar muito, gera de novo com outra semente (até 3 vezes) e fica
  com a melhor.
- mix() e encode(): frases e pausas → um áudio só, com o volume igualado, em AAC (.m4a)."""
import json
import os
import queue
import re
import subprocess
import threading
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np

from . import AppError

ROOT = Path(os.environ.get("LUMEN_VOICE_DIR", r"D:\Lumen\voz"))
PYTHON = Path(os.environ.get("LUMEN_VOICE_PY") or ROOT / "chatterbox" / "Scripts" / "python.exe")
WORKER = Path(os.environ.get("LUMEN_VOICE_WORKER") or Path(__file__).with_name("voice_worker.py"))
IDLE, LOAD_S, SENTENCE_S = 300, 600, 180  # segundos: sem uso até fechar; carga (HD) e uma frase, no máximo
SEEDS, CHECKER = (1, 2, 3), "small"       # tentativas por frase; Whisper que confere (rápido e já baixado)
MAX_SENTENCE = 220


def available():
    return PYTHON.exists() and WORKER.exists()


# --- texto para a fala ---------------------------------------------------------------------------------------------

def speakable(md):
    """Markdown da resposta → texto para ler. Tira citações [S#], código, imagens, links (fica o texto), ênfase,
    marcadores e tabelas; título e item de lista sem pontuação ganham ponto (vira pausa)."""
    t = re.sub(r"\s*\[S\d{1,3}\]", "", str(md or ""))
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)|!\[\[[^\]]*\]\]", " ", t)
    t = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m[2] or m[1], t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    lines = []
    for line in t.splitlines():
        if re.fullmatch(r"\s*\|?[\s:|-]*-[\s:|-]*\|?\s*", line):  # separador de tabela
            continue
        line = re.sub(r"^\s{0,3}(?:#{1,6}\s*|>\s?|[-*+]\s+|\d+[.)]\s+)", "", line)
        line = line.strip().strip("|").replace("|", ",")
        line = re.sub(r"(\*\*|__|~~|`)", "", line)
        line = re.sub(r"(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)", "", line)
        line = re.sub(r"\s+", " ", line).strip(" ,")
        if line:
            lines.append(line if line[-1] in ".!?…:;" else line + ".")
    return " ".join(lines)


def sentences(text, limit=MAX_SENTENCE):
    """Frases de até `limit` caracteres; uma frase longa é cortada na vírgula (ou no espaço) mais perto do limite."""
    out = []
    for s in re.split(r"(?<=[.!?…:;])\s+", text.strip()):
        while len(s) > limit:
            cut = max(s.rfind(", ", 0, limit), s.rfind("; ", 0, limit))
            cut = cut + 1 if cut > limit // 3 else (s.rfind(" ", 0, limit) if s.rfind(" ", 0, limit) > 0 else limit)
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            out.append(s)
    return out


def words(text):
    text = unicodedata.normalize("NFKD", str(text).lower())
    return re.findall(r"[a-z0-9]+", "".join(c for c in text if not unicodedata.combining(c)))


def _wer(ref, hyp):
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[-1] / max(len(ref), 1)


# --- processo do motor ---------------------------------------------------------------------------------------------

class Engine:
    """O processo do motor. Um pedido por vez (lock); a resposta é casada pelo id, então um pedido cancelado não
    confunde o seguinte. Fecha sozinho depois de IDLE segundos sem uso."""

    def __init__(self):
        self.proc, self.sr, self.n, self.used = None, None, 0, 0.0
        self.lock, self.lines = threading.Lock(), queue.Queue()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _start(self, check):
        if not available():
            raise AppError("A voz não está instalada neste PC.", "Veja Estudos → Configurações → Voz.")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HOME": str(ROOT / "hf"), "TORCH_HOME": str(ROOT / "torch"),
               "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
        self.lines = queue.Queue()
        self.proc = subprocess.Popen([str(PYTHON), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._pump, args=(self.proc, self.lines), daemon=True, name="Lumen voice out").start()
        first = self._wait(lambda m: "ready" in m or "fatal" in m, LOAD_S, check)
        if "fatal" in first:
            self.close()
            raise AppError("A voz não carregou.", first["fatal"])
        self.sr = first["sr"]
        threading.Thread(target=self._idle, args=(self.proc,), daemon=True, name="Lumen voice idle").start()

    @staticmethod
    def _pump(proc, lines):
        for line in proc.stdout:
            try:
                lines.put(json.loads(line))
            except ValueError:
                continue
        lines.put({"fatal": "o processo de voz fechou"})

    def _wait(self, match, seconds, check):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            check()
            try:
                msg = self.lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if match(msg) or "fatal" in msg:
                return msg
        self.close()
        raise AppError("A voz demorou demais para responder.", "Tente de novo.")

    def say(self, text, out, seed=1, check=lambda: None):
        """Gera uma frase em `out` (WAV). Devolve a duração em segundos."""
        with self.lock:
            if not self.alive():
                self._start(check)
            self.n += 1
            rid = self.n
            self.proc.stdin.write(json.dumps({"id": rid, "text": text, "out": str(out), "seed": seed}) + "\n")
            self.proc.stdin.flush()
            msg = self._wait(lambda m: m.get("id") == rid, SENTENCE_S, check)
            self.used = time.monotonic()
            if "fatal" in msg:
                self.close()
                raise AppError("A voz parou no meio.", "Tente de novo.")
            if "error" in msg:
                raise AppError("A voz falhou numa frase.", msg["error"])
            return float(msg["seconds"])

    def _idle(self, proc):
        while proc.poll() is None:
            time.sleep(15)
            if self.proc is proc and self.used and time.monotonic() - self.used > IDLE and self.lock.acquire(blocking=False):
                try:
                    self.close()
                finally:
                    self.lock.release()

    def close(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
                proc.wait(10)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()


ENGINE = Engine()


# --- frase conferida -----------------------------------------------------------------------------------------------

def heard(path):
    """O que o Whisper ouve no arquivo (palavras normalizadas)."""
    from . import transcribe
    model = transcribe._model(CHECKER, "cuda" if transcribe.has_gpu() else "cpu")
    segments, _ = model.transcribe(str(path), language="pt", beam_size=1, vad_filter=False)
    return words(" ".join(s.text for s in segments))


def synth(text, out, check=lambda: None, verify=True, engine=None, seeds=SEEDS):
    """Uma frase → `out` (WAV). `engine` é qualquer objeto com say(text, out, seed, check) → segundos: o Chatterbox
    (ENGINE) ou o Voice Studio (lumen/study/listen.py). Com `verify`, até 3 sementes; gera de novo só se sobrar palavra
    (o balbucio) ou, numa frase de 6 palavras ou mais, faltar mais de 40%. O erro de palavras sozinho não decide: numa
    frase curta com termo em inglês ("Keyframes no Premiere.") o Whisper erra mesmo com a fala certa (medido em 01/11).
    Sem passar, fica a de menor erro, com as palavras a mais pesando o dobro."""
    engine = engine or ENGINE
    if not verify:
        seconds = engine.say(text, out, seeds[0], check)
        return {"seed": seeds[0], "extra": None, "wer": None, "seconds": seconds}
    ref, best = words(text), None
    for seed in seeds:
        tmp = out.with_name(f"{out.stem}.s{seed}.wav")
        seconds = engine.say(text, tmp, seed, check)
        hyp = heard(tmp)
        extra, wer = max(len(hyp) - len(ref) - 1, 0), _wer(ref, hyp)  # 1 palavra de folga (número lido por extenso)
        score = wer + 2 * extra / max(len(ref), 1)
        if best is None or score < best[0]:
            if best:
                best[1].unlink(missing_ok=True)
            best = (score, tmp, {"seed": seed, "extra": extra, "wer": round(wer, 3), "seconds": seconds})
        else:
            tmp.unlink(missing_ok=True)
        if not extra and not (len(ref) >= 6 and len(hyp) < 0.6 * len(ref)):
            break
    best[1].replace(out)
    return best[2]


# --- áudio final ---------------------------------------------------------------------------------------------------

def read_wav(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768, w.getframerate()


def mix(parts, sr):
    """parts: [arquivo WAV | segundos de pausa] → (áudio float32, início de cada parte em segundos). O volume é
    igualado (RMS em -20 dBFS da fala, pico até 0,98)."""
    chunks, starts, t = [], [], 0.0
    for p in parts:
        starts.append(t)
        if isinstance(p, (int, float)):
            a = np.zeros(int(sr * p), np.float32)
        else:
            a, rate = read_wav(p)
            if rate != sr:
                raise AppError("As frases saíram com taxas diferentes.")
        chunks.append(a)
        t += len(a) / sr
    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    voiced = audio[np.abs(audio) > 1e-3]
    if voiced.size:
        audio = audio * (0.1 / float(np.sqrt(np.mean(voiced ** 2))))
        audio = audio * min(1.0, 0.98 / float(np.abs(audio).max()))
    return audio, starts


def encode(audio, sr, out, bitrate=96000):
    """float32 mono → AAC em .m4a (PyAV). Grava num temporário e troca no fim (um áudio pela metade nunca fica)."""
    import av
    tmp = Path(out).with_suffix(".tmp.m4a")
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)[None, :]
    with av.open(str(tmp), "w", format="mp4") as c:
        s = c.add_stream("aac", rate=sr, layout="mono")
        s.bit_rate = bitrate
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = sr
        resampler, fifo = av.AudioResampler(format="fltp", layout="mono", rate=sr), av.AudioFifo()
        for f in resampler.resample(frame):
            fifo.write(f)
        while (f := fifo.read(s.codec_context.frame_size or 1024)) is not None:
            for packet in s.encode(f):
                c.mux(packet)
        if fifo.samples:
            for packet in s.encode(fifo.read()):
                c.mux(packet)
        for packet in s.encode(None):
            c.mux(packet)
    tmp.replace(out)
    return Path(out)

