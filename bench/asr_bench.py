"""Benchmark reproduzível de transcrição local em pt-BR (ver bench/README.md e bench/CRITERIOS.md).

    python -m bench.asr_bench fetch            # baixa as amostras (FLEURS e CORAA, só os trechos usados)
    python -m bench.asr_bench build            # monta ruído, música, aula longa, 2x e sem fala
    python -m bench.asr_bench run <modelo>     # um processo por modelo (mede RAM/VRAM isoladamente)
    python -m bench.asr_bench speed <modelo>   # estratégias para aula acelerada 2x
    python -m bench.asr_bench report           # gera bench/RESULTADOS.md
"""
import csv
import ctypes
import io
import json
import os
import random
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from bench import metrics

ROOT = Path(__file__).parent
DATA = ROOT / ".data"          # fora do Git
RES = ROOT / "results"
SR = 16000
SEED = 7
FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/pt_br/"
CORAA = "https://huggingface.co/datasets/gabrielrstan/CORAA-v1.1/resolve/main/"

MODELS = {
    # nome: (motor, id do modelo, dispositivo, tamanho aproximado, licença)
    "whisper-small": ("fw", "small", "cuda", "0,48 GB", "MIT"),
    "whisper-medium": ("fw", "medium", "cuda", "1,5 GB", "MIT"),
    "whisper-large-v3-turbo": ("fw", "large-v3-turbo", "cuda", "1,6 GB", "MIT"),
    "whisper-large-v3": ("fw", "large-v3", "cuda", "3,1 GB", "MIT"),
    "whisper-small-cpu": ("fw", "small", "cpu", "0,48 GB", "MIT"),
    "whisper-large-v3-turbo-cpu": ("fw", "large-v3-turbo", "cpu", "1,6 GB", "MIT"),
    "parakeet-tdt-0.6b-v3": ("onnx", "nemo-parakeet-tdt-0.6b-v3", "cpu", "0,67 GB (int8)", "CC-BY-4.0"),
    "canary-1b-v2": ("onnx", "nemo-canary-1b-v2", "cpu", "1,0 GB (int8)", "CC-BY-4.0"),
}


# ---------------------------------------------------------------- dados

def _get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


class HttpFile(io.RawIOBase):
    """Arquivo remoto com leitura por Range: lê só os trechos usados de um zip grande."""

    def __init__(self, url):
        self.url, self.pos = url, 0
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def _save_wav(path, x):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def _load(path):
    from lumen import audio
    return audio.load(path)


def fetch():
    """Seleção fixa (semente 7), definida antes de ver resultados."""
    (DATA / "wav").mkdir(parents=True, exist_ok=True)
    rnd = random.Random(SEED)
    items = []

    # FLEURS pt-BR dev: 80 frases espalhadas pela lista (vários falantes)
    cache = DATA / "fleurs.json"
    if cache.exists():
        items = json.loads(cache.read_text("utf-8"))
    else:
        items = _fetch_fleurs()
        cache.write_text(json.dumps(items, ensure_ascii=False, indent=1), "utf-8")
    print("FLEURS:", len(items), "frases")
    _fetch_coraa(items, rnd)


def _fetch_fleurs():
    items = []
    rows = list(csv.reader(io.StringIO(_get(FLEURS + "dev.tsv").decode("utf-8")), delimiter="\t"))
    ids = sorted({r[0] for r in rows}, key=int)
    chosen_ids = set(ids[:: max(1, len(ids) // 80)][:80])
    wanted = {r[1]: r for r in rows if r[0] in chosen_ids}
    seen = set()
    with urllib.request.urlopen(FLEURS + "audio/dev.tar.gz", timeout=300) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                name = os.path.basename(m.name)
                r = wanted.get(name)
                if not r or r[0] in seen:  # uma gravação por frase
                    continue
                seen.add(r[0])
                data = tar.extractfile(m).read()
                p = DATA / "wav" / f"leitura_{r[0]}.wav"
                p.write_bytes(data)
                items.append({"id": f"leitura_{r[0]}", "set": "leitura", "path": str(p), "ref": r[2], "gender": r[6] if len(r) > 6 else ""})
    return items


def _fetch_coraa(items, rnd):

    # CORAA v1.1 dev
    meta = list(csv.DictReader(io.StringIO(_get(CORAA + "metadata_dev_final.csv").decode("utf-8"))))
    ted = [m for m in meta if m["dataset"] == "TEDx Talks" and m["variety"] == "pt_br" and len(m["text"].split()) >= 6]
    conv = {d: [m for m in meta if m["dataset"] == d and m["variety"] == "pt_br" and m["task"].startswith("annotation")
                and int(m["up_votes"]) >= 2 and int(m["down_votes"]) == 0 and int(m["votes_for_second_voice"]) == 0
                and len(m["text"].split()) >= 6] for d in ("NURC-Recife", "SP2010", "C-ORAL-BRASIL I")}
    pick = [("palestra", m) for m in rnd.sample(ted, 60)]
    for d, rows_d in conv.items():
        pick += [("conversa", m) for m in rnd.sample(rows_d, 20)]
    z = zipfile.ZipFile(io.BufferedReader(HttpFile(CORAA + "dev.zip"), buffer_size=1 << 20))
    names = {n.replace("\\", "/").split("dev/", 1)[-1]: n for n in z.namelist()}
    for s, m in pick:
        key = m["file_path"].split("dev/", 1)[-1]
        x = _load(io.BytesIO(z.read(names[key])))
        p = DATA / "wav" / f"{s}_{Path(key).stem}.wav"
        _save_wav(p, x)
        items.append({"id": p.stem, "set": s, "path": str(p), "ref": m["text"], "accent": m["accent"], "dataset": m["dataset"],
                      "noise_votes": int(m["votes_for_noise_or_low_voice"] or 0)})
    print("CORAA:", sum(i["set"] != "leitura" for i in items), "trechos")
    (DATA / "manifest.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), "utf-8")


def _pink(n, rnd):
    w = rnd.standard_normal(n)
    f = np.fft.rfft(w) / np.sqrt(np.arange(1, n // 2 + 2))
    x = np.fft.irfft(f, n)
    return (x / np.abs(x).max()).astype(np.float32)


def _music(n, rnd):
    """Música sintética (acordes com envelope); não é fala."""
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    chords = [(220, 277.2, 329.6), (196, 246.9, 293.7), (174.6, 220, 261.6), (196, 246.9, 311.1)]
    beat = int(SR * 0.5)
    for k in range(0, n, beat):
        c = chords[(k // (beat * 4)) % 4]
        seg = slice(k, min(n, k + beat))
        env = np.exp(-3 * (t[seg] - t[k]))
        for f in c:
            out[seg] += (np.sin(2 * np.pi * f * t[seg]) * env).astype(np.float32)
    return out / np.abs(out).max()


def _mix(speech, noise, snr_db):
    ps, pn = np.mean(speech ** 2) + 1e-12, np.mean(noise ** 2) + 1e-12
    return (speech + noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))).astype(np.float32)


def build():
    from lumen import audio
    items = [i for i in json.loads((DATA / "manifest.json").read_text("utf-8")) if i["set"] in ("leitura", "palestra", "conversa")]
    rnd = np.random.default_rng(SEED)
    out = list(items)
    for i in [i for i in items if i["set"] == "leitura"][:40]:
        x = _load(i["path"])
        for kind, noise in (("ruido", _pink(len(x), rnd)), ("musica", _music(len(x), rnd))):
            p = DATA / "wav" / f"{kind}_{i['id']}.wav"
            _save_wav(p, _mix(x, noise, 10))
            out.append({**i, "id": f"{kind}_{i['id']}", "set": kind, "path": str(p)})

    # aula longa: 40 trechos de palestra, pausas, silêncio e música no meio, ruído de fundo
    parts, timeline, t = [], [], 0.0
    talks = [i for i in items if i["set"] == "palestra"][:40]
    for k, i in enumerate(talks):
        if k == 14:
            parts.append(np.zeros(8 * SR, dtype=np.float32)); timeline.append({"start": t, "end": t + 8, "ref": "", "kind": "silencio"}); t += 8
        if k == 27:
            mus = _music(6 * SR, rnd) * 0.3
            parts.append(mus); timeline.append({"start": t, "end": t + 6, "ref": "", "kind": "musica"}); t += 6
        x = _load(i["path"])
        parts.append(x)
        timeline.append({"start": t, "end": t + len(x) / SR, "ref": i["ref"], "kind": "fala", "id": i["id"]})
        t += len(x) / SR
        pause = float(rnd.uniform(0.4, 3.0))
        parts.append(np.zeros(int(pause * SR), dtype=np.float32)); t += pause
    long = np.concatenate(parts)
    long = _mix(long, _pink(len(long), rnd), 20)
    _save_wav(DATA / "wav" / "aula_longa.wav", long)
    _save_wav(DATA / "wav" / "aula_longa_2x.wav", audio.tempo(long, 2.0))
    (DATA / "aula_longa.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), "utf-8")
    ref = " ".join(s["ref"] for s in timeline if s["ref"])
    out.append({"id": "aula_longa", "set": "aula_longa", "path": str(DATA / "wav" / "aula_longa.wav"), "ref": ref, "long": True})

    quiet = np.concatenate([rnd.standard_normal(10 * SR).astype(np.float32) * 0.002, _music(10 * SR, rnd) * 0.3,
                            _pink(10 * SR, rnd) * 0.05])
    _save_wav(DATA / "wav" / "sem_fala.wav", quiet)
    out.append({"id": "sem_fala", "set": "sem_fala", "path": str(DATA / "wav" / "sem_fala.wav"), "ref": "", "long": True})
    # Amostras próprias (opcional): bench/.data/proprias/<nome>.wav|mp3|m4a + <nome>.txt com a transcrição revisada
    for wav in sorted((DATA / "proprias").glob("*.*")):
        ref = wav.with_suffix(".txt")
        if wav.suffix.lower() != ".txt" and ref.exists():
            out.append({"id": "propria_" + wav.stem, "set": "proprias", "path": str(wav),
                        "ref": ref.read_text("utf-8"), "long": True})
    (DATA / "manifest_full.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print("conjuntos:", {s: sum(1 for i in out if i["set"] == s) for s in dict.fromkeys(i["set"] for i in out)},
          f"| aula longa {len(long) / SR / 60:.1f} min")


# ---------------------------------------------------------------- modelos

class Engine:
    def __init__(self, name):
        self.kind, self.mid, self.device, self.size, self.license = MODELS[name]
        if self.kind == "fw":
            import lumen.transcribe  # noqa: F401  (registra as DLLs CUDA)
            from faster_whisper import WhisperModel, download_model
            download_model(self.mid)
            self.m = WhisperModel(self.mid, device=self.device, compute_type="float16" if self.device == "cuda" else "int8",
                                  cpu_threads=os.cpu_count())
        else:
            import onnx_asr
            self.m = onnx_asr.load_model(self.mid, quantization="int8")
            self.vad = onnx_asr.load_vad("silero")

    def transcribe(self, x, long=False):
        """Devolve segmentos [{start, end, text, logprob}]. Mesmas opções que o app (VAD ligado, beam 5)."""
        if self.kind == "fw":
            segs, _ = self.m.transcribe(x, language="pt", beam_size=5, vad_filter=True,
                                        condition_on_previous_text=False)
            return [{"start": s.start, "end": s.end, "text": s.text.strip(), "logprob": s.avg_logprob,
                     "no_speech": s.no_speech_prob, "compression": s.compression_ratio} for s in segs]
        kw = {"language": "pt"} if "canary" in self.mid else {}
        if long:
            out = []
            for r in self.m.with_vad(self.vad, batch_size=1).recognize(x, sample_rate=SR, **kw):
                out.append({"start": r.start, "end": r.end, "text": r.text.strip(), "logprob": None})
            return out
        text = self.m.recognize(x, sample_rate=SR, **kw)
        return [{"start": 0, "end": len(x) / SR, "text": text.strip(), "logprob": None}]


def _peak_ram_mb():
    if os.name != "nt":
        return None

    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_uint32]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.PeakWorkingSetSize / 1e6


def _gpu_used():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


class VramPeak(threading.Thread):
    """Pico de VRAM da GPU durante o teste menos a linha de base (o Windows não informa por processo), em MB."""

    def __init__(self):
        super().__init__(daemon=True)
        self.base, self.peak, self.stop = _gpu_used(), 0, False

    def run(self):
        while not self.stop and self.base is not None:
            used = _gpu_used()
            if used is not None:
                self.peak = max(self.peak, used - self.base)
            time.sleep(0.5)


def run(name):
    items = json.loads((DATA / "manifest_full.json").read_text("utf-8"))
    RES.mkdir(exist_ok=True)
    vram = VramPeak()
    vram.start()
    t0 = time.perf_counter()
    eng = Engine(name)
    load_s = time.perf_counter() - t0
    rows, audio_s, proc_s = [], 0.0, 0.0
    for it in items:
        x = _load(it["path"])
        t = time.perf_counter()
        segs = eng.transcribe(x, long=it.get("long", False))
        dt = time.perf_counter() - t
        audio_s += len(x) / SR
        proc_s += dt
        hyp = " ".join(s["text"] for s in segs)
        rows.append({"id": it["id"], "set": it["set"], "ref": it["ref"], "hyp": hyp, "segments": segs,
                     "dur": len(x) / SR, "secs": dt, **metrics.score(it["ref"], hyp)})
        print(f"{it['id']:<40} {dt:6.2f}s", flush=True)
    vram.stop = True
    import faster_whisper
    info = {"model": name, "engine": eng.kind, "model_id": eng.mid, "device": eng.device, "size": eng.size,
            "license": eng.license, "load_s": load_s, "audio_s": audio_s, "proc_s": proc_s, "rtf": audio_s / proc_s,
            "peak_ram_mb": _peak_ram_mb(), "peak_vram_mb": vram.peak or None,
            "versions": {"faster_whisper": faster_whisper.__version__, "python": sys.version.split()[0],
                         "onnx_asr": _version("onnx_asr"), "ctranslate2": _version("ctranslate2")},
            "options": "language=pt, beam_size=5, vad_filter=True, condition_on_previous_text=False" if eng.kind == "fw"
            else "language=pt, int8, Silero VAD no áudio longo"}
    (RES / f"{name}.json").write_text(json.dumps({"info": info, "rows": rows}, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(info, ensure_ascii=False))


def _version(mod):
    try:
        return __import__(mod).__version__
    except Exception:
        return None


def speed(name):
    """Aula efetivamente acelerada 2x: direto x desacelerar com atempo x desacelerar por reamostragem (controle)."""
    from lumen import audio
    timeline = json.loads((DATA / "aula_longa.json").read_text("utf-8"))
    ref = " ".join(s["ref"] for s in timeline if s["ref"])
    x2 = _load(DATA / "wav" / "aula_longa_2x.wav")
    eng = Engine(name)
    out = {}
    variants = {
        "direto": (x2, 1.0),
        "atempo_0.5": (audio.tempo(x2, 0.5), 2.0),                      # t_arquivo = t_processado / 2
        "reamostragem_0.5": (np.interp(np.arange(0, len(x2), 0.5), np.arange(len(x2)), x2).astype(np.float32), 2.0),
    }
    for v, (x, k) in variants.items():
        t = time.perf_counter()
        segs = eng.transcribe(x, long=True)
        dt = time.perf_counter() - t
        for s in segs:
            s["start"], s["end"] = s["start"] / k, s["end"] / k
        hyp = " ".join(s["text"] for s in segs)
        out[v] = {"secs": dt, "segments": segs, **metrics.score(ref, hyp), "ts": _timestamp_error(segs, timeline, 0.5)}
        print(v, f"{dt:.1f}s", f"WER {metrics.aggregate([out[v]])['WER']:.3f}", out[v]["ts"])
    (RES / f"speed_{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")


def variants(model_id="large-v3-turbo"):
    """Auditoria das opções do app (mesmo modelo, GPU): aula longa + palestra + sem fala."""
    import lumen.transcribe  # noqa: F401
    from faster_whisper import WhisperModel
    m = WhisperModel(model_id, device="cuda", compute_type="float16")
    items = [i for i in json.loads((DATA / "manifest_full.json").read_text("utf-8")) if i["set"] in ("palestra", "aula_longa", "sem_fala")]
    timeline = json.loads((DATA / "aula_longa.json").read_text("utf-8"))
    configs = {
        "app_atual (auto idioma, cond_prev=True, VAD)": dict(language=None, condition_on_previous_text=True, vad_filter=True),
        "pt, cond_prev=True, VAD": dict(language="pt", condition_on_previous_text=True, vad_filter=True),
        "pt, cond_prev=False, VAD": dict(language="pt", condition_on_previous_text=False, vad_filter=True),
        "pt, cond_prev=False, sem VAD": dict(language="pt", condition_on_previous_text=False, vad_filter=False),
        "pt, cond_prev=False, VAD, hotwords": None,  # vocabulário do curso (palavras raras da referência)
    }
    rare = sorted({w for t in timeline if t["ref"] for w in t["ref"].split() if len(w) >= 9})[:40]
    out = {}
    for name, kw in configs.items():
        if kw is None:
            kw = dict(language="pt", condition_on_previous_text=False, vad_filter=True, hotwords=" ".join(rare))
        rows = []
        t0 = time.perf_counter()
        for it in items:
            segs, _ = m.transcribe(_load(it["path"]), beam_size=5, **kw)
            segs = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]
            hyp = " ".join(s["text"] for s in segs)
            rows.append({"id": it["id"], "set": it["set"], "ref": it["ref"], "hyp": hyp, "segments": segs, **metrics.score(it["ref"], hyp)})
        long = next(r for r in rows if r["set"] == "aula_longa")
        out[name] = {"secs": time.perf_counter() - t0,
                     "palestra": metrics.aggregate([r for r in rows if r["set"] == "palestra"]),
                     "aula_longa": metrics.aggregate([long]), "ts": _timestamp_error(long["segments"], timeline, 1.0),
                     "sem_fala_words": len(metrics.normalize(next(r for r in rows if r["set"] == "sem_fala")["hyp"])),
                     "rows": rows}
        print(f"{name:<45} palestra {out[name]['palestra']['WER']:.3f} aula_longa {out[name]['aula_longa']['WER']:.3f} "
              f"ts {out[name]['ts']} sem_fala {out[name]['sem_fala_words']}", flush=True)
    (RES / "variants.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")


def rate(model_id="large-v3-turbo"):
    """Calibra o modo Automático: taxa de fala (função do app) em janelas normais e 2x."""
    from lumen import audio, transcribe
    items = json.loads((DATA / "manifest_full.json").read_text("utf-8"))
    rnd = np.random.default_rng(SEED)
    (DATA / "rate").mkdir(exist_ok=True)
    windows = []
    for st in ("leitura", "palestra", "conversa"):
        buf, k = [], 0
        for it in [i for i in items if i["set"] == st]:
            buf += [_load(it["path"]), np.zeros(int(rnd.uniform(0.3, 1.0) * SR), dtype=np.float32)]
            if sum(len(b) for b in buf) >= 120 * SR:
                windows.append((f"{st}_{k}", np.concatenate(buf)[:120 * SR])); buf, k = [], k + 1
    long = _load(DATA / "wav" / "aula_longa.wav")
    windows += [(f"aula_longa_{k}", long[k * 120 * SR:(k + 1) * 120 * SR]) for k in range(len(long) // (120 * SR))]
    out = {"normal": {}, "2x": {}}
    for name, x in windows:
        for kind, y in (("normal", x), ("2x", audio.tempo(x, 2.0))):
            path = DATA / "rate" / f"{name}_{kind}.wav"
            _save_wav(path, y)
            out[kind][name] = transcribe.speech_rate(path, model_id, lambda: None)
            print(kind, name, round(out[kind][name] or 0, 2), flush=True)
    hi, lo = max(out["normal"].values()), min(out["2x"].values())
    out["limite"] = (hi + lo) / 2 if lo > hi else None
    print("maior normal", round(hi, 2), "| menor 2x", round(lo, 2), "| limite", out["limite"])
    (RES / "rate.json").write_text(json.dumps(out, indent=1), "utf-8")


def _timestamp_error(segs, timeline, scale):
    """Para cada trecho de fala da referência (tempo no arquivo 2x = tempo original * scale), procura o segmento
    reconhecido que começa mais perto e mede a diferença. Usa só trechos cujo texto o segmento contém."""
    errs = []
    for ref in (r for r in timeline if r["kind"] == "fala"):
        start = ref["start"] * scale
        first = " ".join(metrics.normalize(ref["ref"])[:3])
        cands = [s for s in segs if first and first in " ".join(metrics.normalize(s["text"]))]
        if cands:
            errs.append(min(abs(s["start"] - start) for s in cands))
    return {"n": len(errs), "median_s": float(np.median(errs)) if errs else None,
            "p90_s": float(np.percentile(errs, 90)) if errs else None}


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"fetch": fetch, "build": build}.get(cmd, lambda: None)()
    if cmd == "run":
        run(sys.argv[2])
    elif cmd == "speed":
        speed(sys.argv[2])
    elif cmd == "variants":
        variants()
    elif cmd == "rate":
        rate()
    elif cmd == "report":
        from bench import report
        report.main()
