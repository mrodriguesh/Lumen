"""Avaliação do roteamento do perfil adulto (D92) com o classificador REAL (modelo local, segundo Ollama em 127.0.0.1:11435).

Mede `lumen.study.adult.resolve` em modo automático, caso a caso, com dados sintéticos (bench/adult_route_cases.py) e um
LUMEN_DATA temporário: nada do estudante entra, e o Ollama dele (11434) não é usado.

  python -m bench.adult_route_eval run --tag A --split dev [--runs 2]
  python -m bench.adult_route_eval lock                 # congela prompt, filtros e casos do conjunto "final"
  python -m bench.adult_route_eval run --tag A --split final
  python -m bench.adult_route_eval report --tag A --split dev

Falso positivo = caso esperado "main" que foi para o perfil adulto. Falso negativo = esperado "adult" que foi para o principal;
o FN é separado em "perdido pelo filtro" (nenhum sinal e sem perfil adulto antes: o classificador nem foi chamado) e "perdido
pelo classificador". O conjunto final só roda com o lock válido: mudou o prompt, os filtros ou os casos depois do lock, o
resultado não vale como teste final (use `lock --supersede "motivo"`, que fica no ledger)."""
import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="lumen-route-")
os.environ["LUMEN_DATA"] = TMP  # antes de importar o Lúmen: dados isolados
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.adult_route_cases import cases  # noqa: E402
from lumen import llm  # noqa: E402
from lumen.study import adult, settings  # noqa: E402

HOST = "http://127.0.0.1:11435"
llm.OLLAMA = HOST
OUT = Path(os.environ.get("LUMEN_ROUTE_OUT", r"D:\Lumen\perfil-adulto-20261108\route"))
LOCK, LEDGER = OUT / "lock.json", OUT / "ledger.log"


def fingerprint():
    h = hashlib.sha256()
    h.update(adult.CLASSIFY.encode())
    h.update(adult.SIGNAL.pattern.encode())
    h.update(adult.MINOR.pattern.encode())
    h.update(adult.CREATIVE.pattern.encode())
    h.update(adult.STYLE.encode())
    h.update(json.dumps(adult.SCHEMA, sort_keys=True).encode())
    prompt = h.hexdigest()
    final = hashlib.sha256(json.dumps(cases("final"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"prompt_filters": prompt, "final_cases": final}


def ledger(line):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")


def cmd_lock(a):
    OUT.mkdir(parents=True, exist_ok=True)
    fp = fingerprint()
    if LOCK.exists() and not a.supersede:
        sys.exit("já existe lock; use --supersede 'motivo' para registrar um novo")
    if LOCK.exists():
        OUT.joinpath("lock-superseded-%d.json" % int(time.time())).write_text(LOCK.read_text("utf-8"), "utf-8")
    LOCK.write_text(json.dumps({"locked_at": time.strftime("%Y-%m-%d %H:%M:%S"), **fp}, indent=1), "utf-8")
    ledger(f"LOCK {fp['prompt_filters'][:12]} {fp['final_cases'][:12]} {a.supersede}")
    print("lock gravado", fp)


def cmd_run(a):
    OUT.mkdir(parents=True, exist_ok=True)
    if a.split == "final":
        if not LOCK.exists():
            sys.exit("rode `lock` antes do conjunto final")
        if json.loads(LOCK.read_text("utf-8")) | {"locked_at": 0} != {**fingerprint(), "locked_at": 0}:
            sys.exit("o prompt, os filtros ou os casos mudaram depois do lock: não vale como teste final")
        ledger(f"FINAL run tag={a.tag} (prompt {fingerprint()['prompt_filters'][:12]})")
    s = settings.load()
    s["adult"].update(enabled=True, mode="auto", model="hf.co/llmfan46/placeholder")
    if a.fast:
        s["models"]["fast"] = a.fast
    captured = {}
    real = adult.classify

    def spy(*args, **kw):
        t0 = time.perf_counter()
        try:
            v = real(*args, **kw)
            captured.update(verdict=v, ms=round((time.perf_counter() - t0) * 1000))
            return v
        except Exception as e:  # noqa: BLE001
            captured.update(error=str(e)[:120], ms=round((time.perf_counter() - t0) * 1000))
            raise
    adult.classify = spy
    rows = []
    for run in range(a.runs):
        for c in cases(a.split):
            captured.clear()
            hist = [{"role": r, "content": t} for r, t in c["history"]]
            d = adult.resolve(s, c["text"], hist, c["previous"], main_external=False)
            gate = adult.signalled(c["text"]) or c["previous"] == "adult"
            rows.append({"run": run, "id": c["id"], "cat": c["cat"], "expect": c["expect"], "got": d["use"], "by": d["by"],
                         "gate": gate, **{k: v for k, v in captured.items()}})
        print(f"rodada {run + 1}/{a.runs} ok", flush=True)
    path = OUT / f"route-{a.tag}-{a.split}.json"
    path.write_text(json.dumps({"tag": a.tag, "split": a.split, "fast": s["models"]["fast"] or settings.fast_model(s),
                                "fingerprint": fingerprint(), "rows": rows}, ensure_ascii=False, indent=1), "utf-8")
    print("gravado", path)


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))


def cmd_report(a):
    data = json.loads((OUT / f"route-{a.tag}-{a.split}.json").read_text("utf-8"))
    rows = data["rows"]
    pos = [r for r in rows if r["expect"] == "adult"]
    neg = [r for r in rows if r["expect"] == "main"]
    fp = [r for r in neg if r["got"] == "adult"]
    fn = [r for r in pos if r["got"] != "adult"]
    fn_gate = [r for r in fn if not r["gate"]]
    print(f"{a.tag}/{a.split}  classificador={data['fast']}  casos={len(rows) // max(1, max(r['run'] for r in rows) + 1)}  rodadas={max(r['run'] for r in rows) + 1}")
    print(f"  falsos positivos: {len(fp)}/{len(neg)}  IC95% {wilson(len(fp), len(neg))}")
    print(f"  falsos negativos: {len(fn)}/{len(pos)}  IC95% {wilson(len(fn), len(pos))}  (filtro: {len(fn_gate)}, classificador: {len(fn) - len(fn_gate)})")
    cats = {}
    for r in rows:
        c = cats.setdefault(r["cat"], [0, 0, r["expect"]])
        c[0] += 1
        c[1] += r["got"] == r["expect"]
    for cat, (n, ok, exp) in cats.items():
        print(f"    {cat:20s} {ok}/{n}  (esperado {exp})")
    ms = sorted(r["ms"] for r in rows if "ms" in r and "error" not in r)
    if ms:
        print(f"  classificador chamado em {len(ms)} casos; latência ms: mediana {ms[len(ms) // 2]}, p90 {ms[int(len(ms) * .9)]}, máx {ms[-1]}")
    print(f"  sem chamada de modelo (filtro): {sum(1 for r in rows if 'ms' not in r)}/{len(rows)}")
    errs = [r for r in rows if "error" in r]
    if errs:
        print(f"  erros do classificador: {len(errs)} (tratados como incerteza)")
    unstable = {}
    for r in rows:
        unstable.setdefault(r["id"], set()).add(r["got"])
    flips = [i for i, v in unstable.items() if len(v) > 1]
    if flips:
        print("  instável entre rodadas:", flips)
    for r in fp + fn:
        if r["run"] == 0:
            print(f"    ERRO {r['id']} ({r['cat']}): esperado {r['expect']}, obteve {r['got']} por {r['by']}", r.get("verdict", ""))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--tag", required=True)
    p.add_argument("--split", choices=("dev", "final"), required=True)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--fast", default="")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("lock")
    p.add_argument("--supersede", default="")
    p.set_defaults(fn=cmd_lock)
    p = sub.add_parser("report")
    p.add_argument("--tag", required=True)
    p.add_argument("--split", choices=("dev", "final"), required=True)
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
