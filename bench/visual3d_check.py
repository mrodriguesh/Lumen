r"""Amostras públicas e determinísticas, em tamanho real. Sem IA, mocks ou dados de aulas do usuário.

  .venv\Scripts\python bench\visual3d_check.py
  .venv\Scripts\python bench\visual3d_check.py --publish

--publish usa a integração configurada para criar uma página identificada de teste e um cofre isolado.
Não altera configurações, histórico, notas ou páginas anteriores do usuário. Evidências ficam em desktop-artifacts.
"""
import ctypes
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "desktop-artifacts" / "visual3d-current"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["LUMEN_DATA"] = str(OUT / "data")
sys.path.insert(0, str(ROOT))
from lumen import jobs, llm, mindmap, notion, package, store, visual3d as v  # noqa: E402


def sample(title, labels, kind="conceitual", steps=(), relations=()):
    summary = "Material de teste: " + "; ".join(labels) + "."
    les = llm.validate({"title": title, "summary": summary, "simple_explanation": summary,
                       "topics": [{"title": x, "explanation": x, "timestamp": None} for x in labels],
                       "mind_map": {"center": title, "branches": [{"label": x, "children": [], "emoji": ""} for x in labels]},
                       "map_kind": kind, "steps": list(steps), "relations": list(relations), "glossary": [],
                       "examples": [], "review_questions": [{"question": "Quais itens aparecem neste esquema?", "answer": "; ".join(labels)}],
                       "key_moments": [], "caveats": []}, has_times=False)
    src = {"key": "visual3d-check:" + title, "kind": "captures", "label": "Amostra técnica", "title": title}
    mine = {"original_understanding": "Nota sintética para verificar a exportação. Não representa a compreensão de um estudante.",
            "current_understanding": "Nota sintética para verificar a exportação. Não representa a compreensão de um estudante.",
            "model": "fixture técnica, sem execução de IA",
            "ai_analysis": {k: [] for k in ("acertos", "parciais", "lacunas", "confusoes", "complementos", "conexoes", "perguntas")}}
    return package.validate(package.build(src, {"segments": [], "origin": "Amostra técnica determinística, sem IA."}, les, mine))


SAMPLES = {
    "processo": sample("Revisão de um texto", ["Rascunho", "Leitura", "Correção", "Versão final"], "tutorial",
                       ["Escrever o rascunho", "Ler o texto", "Corrigir ambiguidades", "Salvar a versão final"]),
    "sistema": sample("Computador: componentes", ["Processador", "Memória", "Armazenamento", "Entrada", "Saída"], "sistema"),
    "estrutura": sample("Organização de um livro", ["Introdução", "Capítulos", "Conclusão", "Referências"], "livro"),
    "comparacao": sample("Planejamento de estudo", ["Estudo individual", "Estudo em grupo"], relations=[
        {"from": "Estudo individual", "to": "Estudo em grupo", "type": "contrasta com"}]),
    "conceitos": sample("Argumentação", ["Tese", "Premissas", "Evidências", "Objeções", "Conclusão"]),
    "simbolos": sample("Eletricidade: grandezas", ["Resistência (Ω)", "Tensão (V)", "Corrente (A)", "Relação V = R × I"]),
    "pouco": sample("Introdução à leitura", ["Objetivo da leitura"]),
    "longos": sample("Conceitos com rótulos extensos para verificar recortes", [
        "Definição do problema e delimitação do contexto", "Observação cuidadosa dos resultados disponíveis",
        "Comparação das interpretações apresentadas no texto", "Registro das perguntas que ainda não foram respondidas",
        "Organização dos argumentos e das evidências coletadas", "Revisão das conclusões e dos limites da análise",
        "Comunicação dos achados para outros estudantes"]),
}


def generate():
    from PIL import Image
    assert (v.W, v.H, v.FPS, v.FRAMES, v.ATTEMPTS[0]) == (960, 540, 12, 48, (960, 540, 48))
    measures = []
    for name, pkg in SAMPLES.items():
        start, cpu = time.perf_counter(), time.process_time()
        asset, rec = v.prepare(pkg, "animated", refresh=True)
        assert asset, rec
        (OUT / (name + ".png")).write_bytes(asset["png_data"])
        (OUT / (name + "." + asset["kind"])).write_bytes(asset["data"])
        (OUT / (name + "-spec.json")).write_text(json.dumps(v.spec(pkg), ensure_ascii=False, indent=2), "utf-8")
        import io
        with Image.open(io.BytesIO(asset["data"])) as im:
            for tag, index in (("inicio", 0), ("meio", im.n_frames // 2), ("fim", im.n_frames - 1)):
                im.seek(index)
                im.convert("RGB").save(OUT / f"{name}-{tag}.png")
        measures.append({"sample": name, **v.record(asset, rec), "wall_s": round(time.perf_counter() - start, 3),
                         "cpu_s": round(time.process_time() - cpu, 3), "png_bytes": len(asset["png_data"])})
        print(json.dumps({k: measures[-1][k] for k in ("sample", "kind", "bytes", "png_bytes", "width", "height", "frames", "duration_ms", "wall_s", "cpu_s", "cached")}), flush=True)
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [(n, ctypes.c_size_t) for n in
                ("peak_working_set", "working_set", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
        c = Counters(); c.cb = ctypes.sizeof(c)
        process = ctypes.windll.kernel32.GetCurrentProcess
        process.restype = ctypes.c_void_p
        memory = ctypes.windll.psapi.GetProcessMemoryInfo
        memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        assert memory(process(), ctypes.byref(c), c.cb)
        print(json.dumps({"peak_process_mb": round(c.peak_working_set / 1024**2, 1)}), flush=True)
    (OUT / "measures.json").write_text(json.dumps(measures, ensure_ascii=False, indent=2), "utf-8")


def publish():
    real = json.loads((Path(os.environ["LOCALAPPDATA"]) / "Lumen" / "config.json").read_text("utf-8"))
    token = store.get_token()
    assert token and real.get("root_page_id"), "Falta conexão Notion ou raiz configurada."
    evidence = OUT / "real.json"
    prior = json.loads(evidence.read_text("utf-8")) if evidence.exists() else {}
    if prior.get("page"):
        page = prior["page"]
        title = notion._title(notion.request("GET", f"/pages/{page}", token))
        assert title.startswith("Lumen · teste 3D · continuação") or title == "Lumen · teste da Visualização 3D (pode apagar)"
    else:
        existing = [p for p in notion.list_courses(token, real["root_page_id"])
                    if p["title"] == "Lumen · teste da Visualização 3D (pode apagar)"]
        assert len(existing) <= 1, "Mais de uma página de teste; escolha explicitamente."
        page = existing[0]["id"] if existing else notion.create_course(
            token, real["root_page_id"], "Lumen · teste 3D · continuação 27-10-2026 (pode apagar)")["id"]
        evidence.write_text(json.dumps({"page": page}), "utf-8")
    vault = OUT / "Cofre de teste 3D"
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    cfg = {**store.DEFAULTS, "root_page_id": page, "destinations": "both", "obsidian_vault": str(vault),
           "obsidian_folder": "Estudos", "obsidian_connections": False}
    store.save_config(cfg)
    results = []
    for name, mode in (("sistema", "animated"), ("processo", "static")):
        pkg = SAMPLES[name]
        package.save(pkg)
        store.remember(pkg["key"], {"lumen_id": pkg["lumen_id"], "spec": {"course_id": page, "course_title": "Teste 3D"}})
        store.save_config({**cfg, "visual_3d": mode})
        for attempt in range(2):
            start = time.perf_counter()
            spec = {"key": pkg["key"], "only": ["notion", "obsidian"], "mode": "replace"}
            jobs.start("process", jobs.deliver, spec, spec=spec)
            while jobs.snapshot()["status"] == "running":
                time.sleep(0.2)
            j = jobs.snapshot()
            assert j["status"] == "done", j.get("error")
            result = j["result"]
            assert result["notion"]["status"] == result["obsidian"]["status"] == "ok", result
            assert result["notion"]["visual"] == "confirmed", result["notion"]
            e = store.history()[pkg["key"]]
            blocks = notion.all_children(token, page)
            marker = notion.visual_marker(pkg["lumen_id"])
            images = [b for b in blocks if b["type"] == "image" and marker in json.dumps(b, ensure_ascii=False)]
            assert len(images) == 1, "Visual duplicado"
            assert images[0]["id"] == e["notion_visual"]["block"]
            ob = result["obsidian"]
            assert (vault / ob["visual"]["file"]).is_file()
            assert Path(ob["visual"]["file"]).name in (vault / ob["note"]).read_text("utf-8")
            results.append({"sample": name, "attempt": attempt + 1, "seconds": round(time.perf_counter() - start, 2),
                            "notion": e["notion_visual"], "obsidian": ob})
            evidence.write_text(json.dumps({"page": page, "vault": str(vault), "results": results}, ensure_ascii=False, indent=2), "utf-8")
            print(json.dumps({"sample": name, "attempt": attempt + 1, "notion": "confirmed", "obsidian": ob["state"]}), flush=True)


if __name__ == "__main__":
    publish() if "--publish" in sys.argv else generate()
