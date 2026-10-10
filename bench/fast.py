"""Acelerar o modo “Maior precisão” (large-v3 na GPU) sem perder precisão.

    python -m bench.fast phases            # quanto custa cada etapa do pipeline atual (carga, taxa, transcrição, 2º modelo)
    python -m bench.fast variant NOME      # uma variante na aula longa (1 processo por variante: VRAM limpa)
    python -m bench.fast all               # todas as variantes, 2 rodadas cada (o Whisper varia entre execuções)

Referência: bench/.data/aula_longa.json (≈ 6 min de palestras reais com transcrição humana; ver README).
Resultados em bench/results/fast_*.json e no fim de bench/RESULTADOS.md.
"""
import json
import subprocess
import sys
import time

from bench import metrics
from bench.asr_bench import DATA, RES, _load, _timestamp_error

AUDIO = "aula_longa.wav"


def _ref():
    timeline = json.loads((DATA / "aula_longa.json").read_text("utf-8"))
    return timeline, " ".join(t["ref"] for t in timeline if t["ref"])


def _score(segs, timeline, ref):
    a = metrics.aggregate([metrics.score(ref, " ".join(s["text"] for s in segs))])
    lens = sorted(s["end"] - s["start"] for s in segs) or [0]
    return {"WER": a["WER"], "S": a["S"], "D": a["D"], "I": a["I"], "ts": _timestamp_error(segs, timeline, 1.0),
            "segs": len(segs), "seg_p90_s": round(lens[int(len(lens) * .9)], 1)}


# variante → (tipo numérico, lote, beam, opções extras)
VARIANTS = {
    "seq_fp32": ("float32", 0, 5, {}),                  # o app hoje
    "seq_fp16": ("float16", 0, 5, {}),
    "seq_int8f16": ("int8_float16", 0, 5, {}),
    "batch16_fp16": ("float16", 16, 5, {}),
    "batch8_fp32": ("float32", 8, 5, {}),
    "batch16_int8f16": ("int8_float16", 16, 5, {}),
}


def variant(name):
    import lumen.transcribe as tr  # DLLs CUDA
    from faster_whisper import BatchedInferencePipeline, WhisperModel
    compute, batch, beam, extra = VARIANTS[name]
    timeline, ref = _ref()
    x = _load(DATA / "wav" / AUDIO)
    t0 = time.perf_counter()
    model = WhisperModel("large-v3", device="cuda", compute_type=compute, local_files_only=True)
    load = time.perf_counter() - t0
    t0 = time.perf_counter()
    if batch:
        it, _ = BatchedInferencePipeline(model=model).transcribe(x, batch_size=batch, beam_size=beam, vad_filter=True,
                                                                 word_timestamps=True, **extra)
        segs = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in tr.split_words(list(it))]
    else:
        it, _ = model.transcribe(x, **{**tr.OPTIONS, "beam_size": beam, **extra})
        segs = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in it]
    secs = time.perf_counter() - t0
    r = {"variant": name, "load_s": round(load, 1), "secs": round(secs, 1), "x_realtime": round(len(x) / 16000 / secs, 1),
         **_score(segs, timeline, ref)}
    print(json.dumps(r), flush=True)
    return r


def phases():
    """O pipeline do app hoje, etapa por etapa (mesmas funções que o app chama)."""
    import lumen.transcribe as tr
    path = str(DATA / "wav" / AUDIO)
    out = {}
    tr._loaded.clear()
    t = time.perf_counter()
    tr._model("large-v3", "cuda")
    out["carregar_modelo"] = time.perf_counter() - t
    t = time.perf_counter()
    out["wps"] = tr.speech_rate(path, "large-v3", lambda: None)
    out["medir_velocidade_120s"] = time.perf_counter() - t
    t = time.perf_counter()
    with mock_second() as calls:
        res = tr.transcribe(path, "large-v3", lambda *a: None, lambda: None, speed=1.0)
    out["transcricao_total"] = time.perf_counter() - t
    out["segundo_modelo"] = calls["secs"]
    out["compute"] = res["compute"]
    print(json.dumps({k: round(v, 1) if isinstance(v, float) else v for k, v in out.items()}), flush=True)


class mock_second:
    """Mede quanto do tempo total é a conferência com o segundo modelo."""
    def __enter__(self):
        import lumen.transcribe as tr
        self.tr, self.orig, self.calls = tr, tr.second_opinion, {"secs": 0.0}

        def timed(*a, **k):
            t = time.perf_counter()
            try:
                return self.orig(*a, **k)
            finally:
                self.calls["secs"] = round(time.perf_counter() - t, 1)
        tr.second_opinion = timed
        return self.calls

    def __exit__(self, *a):
        self.tr.second_opinion = self.orig


def wide(compute):
    """As 200 falas do manifest (leitura, palestra, conversa) com as opções do app, para um tipo numérico."""
    import lumen.transcribe as tr
    from faster_whisper import WhisperModel
    items = json.loads((DATA / "manifest.json").read_text("utf-8"))
    model = WhisperModel("large-v3", device="cuda", compute_type=compute, local_files_only=True)
    by, secs = {}, 0.0
    for it in items:
        x = _load(it["path"])
        t = time.perf_counter()
        hyp = " ".join(s.text.strip() for s in model.transcribe(x, **tr.OPTIONS)[0])
        secs += time.perf_counter() - t
        by.setdefault(it["set"], []).append(metrics.score(it["ref"], hyp))
    r = {"compute": compute, "secs": round(secs, 1), **{k: round(metrics.aggregate(v)["WER"] * 100, 2) for k, v in by.items()},
         "todas": round(metrics.aggregate([x for v in by.values() for x in v])["WER"] * 100, 2)}
    print(json.dumps(r), flush=True)


def run_all(rounds=2):
    out = []
    for name in VARIANTS:
        for _ in range(rounds):
            p = subprocess.run([sys.executable, "-m", "bench.fast", "variant", name], capture_output=True, text=True)
            line = [ln for ln in p.stdout.splitlines() if ln.startswith("{")]
            if not line:
                print(name, "falhou:", p.stderr[-500:], flush=True)
                continue
            out.append(json.loads(line[-1]))
            print(line[-1], flush=True)
    (RES / "fast_variants.json").write_text(json.dumps(out, indent=1), "utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "variant":
        variant(sys.argv[2])
    elif cmd == "phases":
        phases()
    elif cmd == "wide":
        wide(sys.argv[2])
    elif cmd == "all":
        run_all()
