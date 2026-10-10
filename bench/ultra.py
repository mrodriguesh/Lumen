"""Benchmark do 4x Ultra, auditoria do 2x e uso de hardware (critérios: adendo 3 de bench/CRITERIOS.md).

    python -m bench.ultra build        # cria aula_longa_4x.wav (atempo 4x de fala real)
    python -m bench.ultra all          # todas as combinações, um processo por combinação
    python -m bench.ultra rate         # taxa de fala: janelas 1x, 2x e 4x (modo Automático)
    python -m bench.ultra responsive   # threads/prioridade x responsividade (CPU)
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import numpy as np

from bench import metrics
from bench.asr_bench import DATA, RES, SR, _load, _peak_ram_mb, _save_wav, _timestamp_error
from bench.report import matched_ref_words

PREPS = {1: [1.0], 2: [1.0, 0.5], 4: [1.0, 0.5, 0.33, 0.25]}
CONFIGS = [  # (modelo, tipo numérico, dispositivo)
    ("large-v3-turbo", "float16", "cuda"),
    ("large-v3-turbo", "float32", "cuda"),
    ("large-v3", "float16", "cuda"),
    ("large-v3", "float32", "cuda"),
    ("small", "float16", "cuda"),
    ("parakeet-tdt-0.6b-v3", "int8", "cpu"),
]
FILES = {1: "aula_longa.wav", 2: "aula_longa_2x.wav", 4: "aula_longa_4x.wav"}


def build():
    from lumen import audio
    long = _load(DATA / "wav" / "aula_longa.wav")
    _save_wav(DATA / "wav" / "aula_longa_4x.wav", audio.tempo(long, 4.0))
    print("aula_longa_4x:", round(len(long) / SR / 4, 1), "s")


class Sampler(threading.Thread):
    """GPU (uso % e VRAM) via nvidia-smi a cada 250 ms; CPU pelo tempo de processo. Métricas reais, não estimadas."""

    def __init__(self):
        super().__init__(daemon=True)
        self.gpu, self.vram, self.stop = [], [], False
        try:
            self.p = subprocess.Popen(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits",
                                       "-lms", "250"], stdout=subprocess.PIPE, text=True,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            self.p = None

    def run(self):
        while self.p and not self.stop:
            line = self.p.stdout.readline()
            try:
                u, m = [int(x) for x in line.split(",")]
                self.gpu.append(u)
                self.vram.append(m)
            except ValueError:
                pass

    def close(self):
        self.stop = True
        if self.p:
            self.p.kill()


def one(model, compute, device, speed, prep):
    from lumen import transcribe
    path = DATA / "wav" / FILES[speed]
    timeline = json.loads((DATA / "aula_longa.json").read_text("utf-8"))
    ref = " ".join(t["ref"] for t in timeline if t["ref"])
    base_gpu = Sampler()
    base_gpu.start()
    time.sleep(1.5)
    base_gpu.close()
    idle_vram = min(base_gpu.vram) if base_gpu.vram else None
    s = Sampler()
    s.start()
    cpu0, t0 = os.times(), time.perf_counter()
    with mock.patch.object(transcribe, "PREP", {(model, speed): prep}), \
            mock.patch.object(transcribe, "COMPUTE", {(model, device): compute}), \
            mock.patch.object(transcribe, "has_gpu", return_value=device == "cuda"):
        tr = transcribe.transcribe(str(path), model, lambda *a: None, lambda: None, speed=speed, second=False)
    wall = time.perf_counter() - t0
    cpu1 = os.times()
    s.close()
    hyp = " ".join(x["text"] for x in tr["segments"])
    sc = metrics.score(ref, hyp)
    a = metrics.aggregate([sc])
    # cobertura por trecho e texto em silêncio/música, na linha do tempo original (tempo do arquivo × velocidade)
    words = [metrics.normalize(t["ref"]) for t in timeline if t["kind"] == "fala"]
    ok = matched_ref_words([w for ws in words for w in ws], metrics.normalize(hyp))
    cover, k = [], 0
    for ws in words:
        cover.append(sum(ok[k:k + len(ws)]) / max(len(ws), 1))
        k += len(ws)
    gaps = [t for t in timeline if t["kind"] != "fala"]
    halluc = sum(len(metrics.normalize(x["text"])) for x in tr["segments"] for g in gaps
                 if min(x["end"] * speed, g["end"]) - max(x["start"] * speed, g["start"]) > 0.5 * (x["end"] - x["start"]) * speed)
    out = {"model": model, "compute": tr["compute"], "device": tr["device"], "speed": speed, "prep": prep,
           "WER": a["WER"], "CER": a["CER"], "S": a["S"], "D": a["D"], "I": a["I"], "N": a["N"],
           "lost": sum(c < 0.5 for c in cover), "halluc": halluc,
           "ts": _timestamp_error(tr["segments"], timeline, 1 / speed), "segments": len(tr["segments"]),
           "secs": wall, "audio_s": tr["duration"],
           "cpu_cores_avg": ((cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)) / wall,
           "ram_peak_gb": _peak_ram_mb() / 1000,
           "gpu_util_avg": float(np.mean(s.gpu)) if s.gpu else None, "gpu_util_max": max(s.gpu) if s.gpu else None,
           "vram_peak_gb": (max(s.vram) - idle_vram) / 1000 if s.vram and idle_vram is not None else None,
           "gpu_used": bool(s.gpu) and max(s.gpu) >= 20, "threads": transcribe.cpu_threads()}
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return out


def run_all():
    out = RES / "ultra.jsonl"
    done = set()
    if out.exists():
        done = {(r["model"], r["compute"], r["speed"], r["prep"]) for r in map(json.loads, out.read_text("utf-8").splitlines())}
    for model, compute, device in CONFIGS:
        for speed, preps in PREPS.items():
            for prep in preps:
                c = "int8 (ONNX)" if device == "cpu" and "parakeet" in model else compute
                if (model, c, speed, prep) in done:
                    continue
                r = subprocess.run([sys.executable, "-W", "ignore", "-m", "bench.ultra", "one", model, compute, device, str(speed), str(prep)],
                                   capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                line = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
                if not line:
                    print("FALHOU", model, compute, speed, prep, r.stderr[-600:], flush=True)
                    continue
                with open(out, "a", encoding="utf-8") as f:
                    f.write(line[-1] + "\n")
                d = json.loads(line[-1])
                print(f"{model:<22} {compute:<8} {speed}x prep {prep:<5} WER {d['WER']:.3f} ts {d['ts']['median_s']} "
                      f"{d['secs']:.0f}s gpu {d['gpu_util_avg']} vram {d['vram_peak_gb']} cpu {d['cpu_cores_avg']:.1f}", flush=True)


def rate():
    """Taxa de fala (função do app) em janelas 1x/2x/4x e estimativa em duas etapas (desacelera e mede de novo)."""
    from lumen import audio, transcribe
    out = {"1x": {}, "2x": {}, "4x": {}, "4x_depois_0.5": {}, "2x_depois_0.5": {}}
    for w in sorted((DATA / "rate").glob("*_normal.wav")):
        x = _load(w)
        name = w.stem.replace("_normal", "")
        for k, y in (("1x", x), ("2x", audio.tempo(x, 2.0)), ("4x", audio.tempo(x, 4.0))):
            p = DATA / "rate" / f"{name}_{k}.wav"
            _save_wav(p, y)
            out[k][name] = transcribe.speech_rate(p, "large-v3-turbo", lambda: None)
            if k in ("2x", "4x"):  # 2ª etapa: desacelera 0,5x e mede de novo
                p2 = DATA / "rate" / f"{name}_{k}_slow.wav"
                _save_wav(p2, audio.tempo(y, 0.5))
                out[f"{k}_depois_0.5"][name] = transcribe.speech_rate(p2, "large-v3-turbo", lambda: None)
        print(name, {k: round(v.get(name) or 0, 2) for k, v in out.items()}, flush=True)
    (RES / "rate4.json").write_text(json.dumps(out, indent=1), "utf-8")


def extra4x():
    """4x: Rubber Band (FFmpeg do sistema, se houver) e condition_on_previous_text=False, nas preparações 0,5/0,33/0,25."""
    import shutil
    from lumen import transcribe
    timeline = json.loads((DATA / "aula_longa.json").read_text("utf-8"))
    ref = " ".join(t["ref"] for t in timeline if t["ref"])
    src = DATA / "wav" / FILES[4]
    ff = shutil.which("ffmpeg")
    out = []
    for model in ("large-v3-turbo", "large-v3"):
        for prep in (0.5, 0.33, 0.25):
            variants = []
            if ff:
                rb = DATA / "wav" / f"aula_longa_4x_rb{prep}.wav"
                subprocess.run([ff, "-y", "-v", "error", "-i", str(src), "-af", f"rubberband=tempo={prep}:pitchq=quality",
                                "-ar", str(SR), "-ac", "1", str(rb)], check=True)
                variants.append(("rubberband", rb, {}))
            variants.append(("atempo, cond_prev=False", None, {"condition_on_previous_text": False}))
            for label, path, opts in variants:
                with mock.patch.object(transcribe, "OPTIONS", {**transcribe.OPTIONS, **opts}), \
                        mock.patch.object(transcribe, "PREP", {} if path else {(model, 4): prep}):
                    t0 = time.perf_counter()
                    tr = transcribe.transcribe(str(path or src), model, lambda *a: None, lambda: None, speed=4, second=False)
                    secs = time.perf_counter() - t0
                if path:  # o arquivo já veio desacelerado: volta para o relógio do arquivo 4x
                    for x in tr["segments"]:
                        x["start"], x["end"] = x["start"] * prep, x["end"] * prep
                hyp = " ".join(x["text"] for x in tr["segments"])
                a_ = metrics.aggregate([metrics.score(ref, hyp)])
                r = {"model": model, "prep": prep, "method": label, "WER": a_["WER"], "D": a_["D"], "I": a_["I"],
                     "ts": _timestamp_error(tr["segments"], timeline, 0.25), "secs": secs}
                out.append(r)
                print(json.dumps(r, ensure_ascii=False), flush=True)
    (RES / "extra4x.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")


def batched():
    """BatchedInferencePipeline do faster-whisper (turbo, GPU) x o modo sequencial do app: precisão, tempo e uso da GPU."""
    import lumen.transcribe  # noqa: F401  (DLLs CUDA)
    from faster_whisper import BatchedInferencePipeline, WhisperModel
    from lumen import audio
    timeline = json.loads((DATA / "aula_longa.json").read_text("utf-8"))
    ref = " ".join(t["ref"] for t in timeline if t["ref"])
    m = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
    out = []
    for speed, prep in ((1, 1.0), (2, 0.5)):
        x = _load(DATA / "wav" / FILES[speed])
        if prep != 1.0:
            x = audio.tempo(x, prep)
        for bs in (0, 8, 16):
            s_ = Sampler()
            s_.start()
            t0 = time.perf_counter()
            if bs:
                segs, _ = BatchedInferencePipeline(model=m).transcribe(x, batch_size=bs, beam_size=5, vad_filter=True)
            else:
                segs, _ = m.transcribe(x, beam_size=5, vad_filter=True, condition_on_previous_text=True)
            segs = [{"start": z.start * prep, "end": z.end * prep, "text": z.text.strip()} for z in segs]
            secs = time.perf_counter() - t0
            s_.close()
            a_ = metrics.aggregate([metrics.score(ref, " ".join(z["text"] for z in segs))])
            r = {"speed": speed, "batch": bs, "WER": a_["WER"], "secs": secs, "gpu_util_avg": float(np.mean(s_.gpu)),
                 "ts": _timestamp_error(segs, timeline, 1 / speed)}
            out.append(r)
            print(json.dumps(r), flush=True)
    (RES / "batched.json").write_text(json.dumps(out, indent=1), "utf-8")


def _probe_once():
    t = time.perf_counter()
    x = 0
    for i in range(3_000_000):
        x += i * i
    return time.perf_counter() - t


def responsive():
    """Transcrição na CPU com várias reservas de núcleos e prioridades; mede uma tarefa de referência em paralelo
    e a latência da API local (critério 15)."""
    import http.client
    from lumen import server, transcribe
    path = DATA / "wav" / "aula_longa.wav"
    idle = float(np.median([_probe_once() for _ in range(5)]))
    httpd = server.serve()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_port
    results = []
    reserves = [int(x) for x in os.environ.get("RESERVES", "0,2,4").split(",")]
    models = os.environ.get("MODELS", "parakeet-tdt-0.6b-v3,large-v3-turbo").split(",")
    for model in models:
        for reserve in reserves:
            for low in (False, True):
                if model == "large-v3-turbo" and (reserve, low) not in ((0, False), (2, True), (6, True), (8, False)):
                    continue  # turbo na CPU é lento: só a configuração atual e a candidata
                stop = threading.Event()
                lat, probes = [], []

                def poll():
                    while not stop.is_set():
                        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                        t = time.perf_counter()
                        c.request("GET", "/api/job", headers={"Host": f"127.0.0.1:{port}", "X-Lumen-Token": server.TOKEN})
                        c.getresponse().read()
                        lat.append(time.perf_counter() - t)
                        time.sleep(0.3)

                def probe():  # outro processo, como um app do usuário
                    while not stop.is_set():
                        r = subprocess.run([sys.executable, "-c", "import bench.ultra as u; print(u._probe_once())"],
                                           capture_output=True, text=True)
                        try:
                            probes.append(float(r.stdout.strip()))
                        except ValueError:
                            pass
                ths = [threading.Thread(target=poll, daemon=True), threading.Thread(target=probe, daemon=True)]
                for t in ths:
                    t.start()
                with mock.patch.object(transcribe, "CPU_RESERVE", reserve), mock.patch.object(transcribe, "has_gpu", return_value=False), \
                        mock.patch.object(transcribe, "LOW_PRIORITY", low):
                    transcribe._loaded.clear()
                    t0 = time.perf_counter()
                    x = _load(path)[: SR * 120]
                    _save_wav(DATA / "resp.wav", x)
                    transcribe.transcribe(str(DATA / "resp.wav"), model, lambda *a: None, lambda: None, second=False)
                    secs = time.perf_counter() - t0
                stop.set()
                for t in ths:
                    t.join(timeout=15)
                r = {"model": model, "reserve": reserve, "low_priority": low, "secs_120s_audio": secs,
                     "api_p95_ms": 1000 * float(np.percentile(lat, 95)) if lat else None,
                     "probe_slowdown": float(np.median(probes)) / idle if probes else None}
                results.append(r)
                print(json.dumps(r), flush=True)
    transcribe._loaded.clear()
    httpd.shutdown()
    old = json.loads((RES / "responsive.json").read_text("utf-8")) if (RES / "responsive.json").exists() else []
    keep = [o for o in old if (o["model"], o["reserve"], o["low_priority"]) not in
            {(r["model"], r["reserve"], r["low_priority"]) for r in results}]
    (RES / "responsive.json").write_text(json.dumps(keep + results, indent=1), "utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build()
    elif cmd == "one":
        one(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), float(sys.argv[6]))
    elif cmd == "all":
        run_all()
    elif cmd == "rate":
        rate()
    elif cmd == "responsive":
        responsive()
    elif cmd == "extra4x":
        extra4x()
    elif cmd == "batched":
        batched()
