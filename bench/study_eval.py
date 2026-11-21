"""Rodada local: python bench/study_eval.py conjunto.json --out resultado.json [--model nome] [--limit 10]."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", default="qwen3.5:4b")
    p.add_argument("--limit", type=int, default=10)
    a = p.parse_args()
    if a.out.exists():
        p.error("O arquivo de saída já existe; escolha outro nome para preservar a rodada anterior.")
    if a.dataset.stat().st_size > 30_000_000:
        p.error("Conjunto maior que 30 MB.")
    dataset = json.loads(a.dataset.read_text("utf-8-sig"))
    base = Path("D:/Lumen/temp-avaliacao")
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base, prefix="eval-") as tmp:
        os.environ["LUMEN_DATA"] = tmp
        os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from lumen.study import db, evaluation, providers, settings
        assert db.HOME.resolve().is_relative_to(Path(tmp).resolve())
        s = settings.save({"models": {"provider": "ollama", "fallback": "none", "local": a.model, "fast": a.model},
                           "privacy": {"external": False, "organize": "off"}, "search": {"web": False}})
        provider = providers.Ollama(s)
        ok, reason = provider.ready()
        if not ok:
            p.error(reason)
        try:
            result = evaluation.run(dataset, provider, a.limit)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            with a.out.open("x", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(json.dumps({"out": str(a.out), "counts": result["counts"]}, ensure_ascii=False))
        finally:
            db.close()


if __name__ == "__main__":
    main()
