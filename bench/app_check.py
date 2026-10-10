"""Verifica o caminho real do app (lumen.transcribe) na aula longa: 1x, 2x com detecção automática, só CPU.

    python -m bench.app_check
"""
import json
import time
from unittest import mock

from bench import metrics
from bench.asr_bench import DATA, RES, _timestamp_error
from lumen import transcribe


def run(label, path, name, speed, scale_ref):
    timeline = json.loads((DATA / "aula_longa.json").read_text("utf-8"))
    ref = " ".join(t["ref"] for t in timeline if t["ref"])
    t0 = time.perf_counter()
    tr = transcribe.transcribe(str(path), name, lambda *a: None, lambda: None, speed=speed)
    dt = time.perf_counter() - t0
    hyp = " ".join(s["text"] for s in tr["segments"])
    a = metrics.aggregate([metrics.score(ref, hyp)])
    flagged = [s for s in tr["segments"] if s.get("uncertain") or s.get("diverges")]
    out = {"caso": label, "modelo": name, "dispositivo": tr["device"], "velocidade": speed, "WER": round(a["WER"], 4),
           "omissoes": a["D"], "insercoes": a["I"], "segundos": round(dt, 1), "trechos": len(tr["segments"]),
           "marcados": len(flagged), "segundo_modelo": tr.get("second_opinion"),
           "timestamp": _timestamp_error(tr["segments"], timeline, scale_ref)}
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return out


def main():
    long, long2 = DATA / "wav" / "aula_longa.wav", DATA / "wav" / "aula_longa_2x.wav"
    res = [run("A: GPU 1x (equilibrado + segundo modelo)", long, "large-v3-turbo", 1.0, 1.0)]
    for label, path, ref_scale in (("B: automático no arquivo 2x", long2, 0.5), ("C: automático no arquivo 1x", long, 1.0)):
        wps = transcribe.speech_rate(str(path), "large-v3-turbo", lambda: None)
        speed = 2.0 if wps >= transcribe.FAST_WPS else 1.0
        print(f"{label}: {wps:.2f} palavras/s → {'2x' if speed == 2 else 'normal'}", flush=True)
        r = run(label, path, "large-v3-turbo", speed, ref_scale)
        r["detectado_wps"] = round(wps, 2)
        res.append(r)
    # Estratégia 2x com as opções finais do app: direto x desacelerar 0,5x (atempo), por modelo
    for name in ("large-v3-turbo", "large-v3", "small"):
        for slow in (False, True):
            with mock.patch.object(transcribe, "PREP", {(name, 2): 0.5} if slow else {}):
                res.append(run(f"2x {'desacelerado' if slow else 'direto'}", long2, name, 2.0, 0.5))
    with mock.patch.object(transcribe, "has_gpu", return_value=False):
        res.append(run("D: só CPU (equilibrado = Parakeet)", long, transcribe.PARAKEET, 1.0, 1.0))
        name, warn = transcribe.for_speed(transcribe.PARAKEET, 2.0)
        for slow in (False, True):
            with mock.patch.object(transcribe, "PREP", {(name, 2): 0.5} if slow else {}):
                res.append(run(f"E: só CPU, arquivo 2x ({name}, {'desacelerado' if slow else 'direto'})", long2, name, 2.0, 0.5))
    (RES / "app_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()
