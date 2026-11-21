r"""Fase 9 real: duas fontes lidas, Ollama existente e saída isolada; nenhuma publicação.

  .venv\Scripts\python.exe bench/study_applied_bench.py D:\Lumen\validacao-fase9-20261105\real
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest import mock


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=False)
    personal = Path(os.environ["LOCALAPPDATA"]) / "Lumen"
    config_path = personal / "config.json"
    original_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    config = json.loads(config_path.read_text("utf-8"))
    # A seleção é só leitura: não se abre o perfil pessoal pelo código do aplicativo.
    with sqlite3.connect((personal / "study/study.db").as_uri() + "?mode=ro", uri=True) as c:
        c.row_factory = sqlite3.Row
        note = c.execute("SELECT * FROM documents WHERE source='obsidian' AND path LIKE 'B02 Estudos/%' AND chars>500 ORDER BY chars LIMIT 1").fetchone()
        page = c.execute("SELECT * FROM documents WHERE source='notion' AND title LIKE 'Criando o Primeiro Projeto%' LIMIT 1").fetchone()
        selected = [dict(x) for x in (note, page) if x]
    if len(selected) != 2:
        raise RuntimeError("As duas fontes aprovadas para esta medição não estão no índice.")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import keyring
    token = keyring.get_password("Lumen", "notion")  # somente para os GET limitados abaixo; nunca gravado
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    from keyring.backends.null import Keyring
    keyring.set_keyring(Keyring())
    base = Path("D:/Lumen/temp-fase9")
    base.mkdir(parents=True, exist_ok=True)
    report = {"read_only_sources": [], "timings": {}, "http_methods": [], "passed": False}
    with tempfile.TemporaryDirectory(prefix="phase9-real-", dir=base) as tmp:
        os.environ["LUMEN_DATA"] = tmp
        from lumen import notion, store
        from lumen.study import applied, chats, db, evaluation, index, learn, memory, providers, search, settings, tools
        from lumen.study.sources import Doc, get
        assert db.HOME.resolve().is_relative_to(Path(tmp).resolve())
        s = settings.save({"models": {"provider": "ollama", "fallback": "none", "local": "qwen3.5:4b", "fast": "qwen3.5:4b"},
                           "search": {"images": False, "web": False, "hybrid": False}, "privacy": {"external": False, "organize": "off"},
                           "memory": {"auto": False}})
        provider = providers.Ollama(s)
        report["model"] = provider.model
        request = notion.request
        def read_only(method, path, *args, **kwargs):
            if method != "GET" or len(report["http_methods"]) >= 20:
                raise RuntimeError("Fora do limite de leitura desta medição.")
            report["http_methods"].append(method)
            return request(method, path, *args, **kwargs)
        try:
            with mock.patch.object(store, "get_token", return_value=token), mock.patch.object(store, "load_config", return_value={**store.DEFAULTS, "obsidian_vault": config["obsidian_vault"]}), mock.patch.object(notion, "request", read_only):
                for row in selected:
                    started = time.monotonic()
                    content = get(row["source"]).read(row["source_id"])
                    assert content.strip()
                    index.upsert(Doc(source=row["source"], source_id=row["source_id"], title=row["title"], text=content,
                                     path=row["path"], url=row["url"], author=row["author"]))
                    report["read_only_sources"].append({"source": row["source"], "chars": len(content),
                        "sha256": hashlib.sha256(content.encode()).hexdigest(), "seconds": round(time.monotonic() - started, 3)})
            token = None
            ctx = tools.Ctx()
            for row in search.search("Criando o Primeiro Projeto no Adobe Premiere")["results"]:
                ctx.cite(row)
            assert any(x["source"] == "notion" for x in ctx.sources.values())
            started = time.monotonic()
            practice = learn.generate("exercise", "Criar o primeiro projeto no Adobe Premiere", provider, ctx)
            report["timings"]["practice"] = round(time.monotonic() - started, 3)
            started = time.monotonic()
            practice = applied.submit(practice["id"], "Vou criar um projeto, escolher uma pasta para salvá-lo, importar os arquivos de mídia e criar uma sequência para editar meu vídeo.", [], provider)
            report["timings"]["grade"] = round(time.monotonic() - started, 3)
            started = time.monotonic()
            plan = learn.generate("action", "Criar o primeiro projeto no Adobe Premiere", provider, ctx,
                                  application="Editar um vídeo curto de apresentação do meu curso, organizando os arquivos para continuar a edição depois.")
            report["timings"]["action_plan"] = round(time.monotonic() - started, 3)
            applied.action(plan["id"], "step", 0, True)
            db.close()
            assert learn.item(plan["id"])["data"]["steps"][0]["done"]
            assert len(learn.item(practice["id"])["data"]["attempts"]) == 1
            for name, item in (("practice", practice), ("action-plan", plan)):
                clean = {k: v for k, v in item["data"].items() if k not in ("material", "sources")}
                (out / (name + ".json")).write_text(json.dumps(clean, ensure_ascii=False, indent=2), "utf-8")
            # Caso controlado de regressão, explicitamente sintético; não fabrica avaliações pessoais.
            conv = chats.create()
            chats.add_message(conv["id"], "user", "Para que serve organizar os arquivos antes de editar?")
            msg = chats.add_message(conv["id"], "assistant", "Organizar os arquivos facilita localizar a mídia e continuar a edição [S1].", sources=[
                {"sid": "S1", "title": "Material de controle", "source": "controle", "chunks": [{"id": 1, "text": "Organizar a mídia em pastas facilita localizar os arquivos e retomar a edição."}]}])
            memory.feedback(msg["id"], 1)
            dataset = evaluation.export()
            (out / "evaluation-control.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2), "utf-8")
            started = time.monotonic()
            result = evaluation.run(dataset, provider, 1)
            report["timings"]["evaluation"] = round(time.monotonic() - started, 3)
            (out / "evaluation-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
            report.update(passed=True, criteria=len(practice["data"]["criteria"]), steps=len(plan["data"]["steps"]),
                          reviews=len(plan["data"]["reviews"]), score=practice["data"]["attempts"][0]["score"], evaluation=result["counts"])
        except Exception as e:
            report["error"] = {"type": type(e).__name__, "message": str(e)[:500]}
            raise
        finally:
            report["personal_config_unchanged"] = hashlib.sha256(config_path.read_bytes()).hexdigest() == original_hash
            db.close()
            (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
            print(json.dumps({k: v for k, v in report.items() if k != "read_only_sources"}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
