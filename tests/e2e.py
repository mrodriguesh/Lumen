"""Verificação ponta a ponta real (Whisper + Ollama locais; Notion simulado por padrão).

    python -m tests.e2e <pasta-com-amostras>

A pasta deve ter aula.{mp4,mkv,webm,mov,mp3,m4a,wav}, sem_audio.mp4 e falso.mp4 (ver README).
Para publicar de verdade numa página SUA de teste: defina LUMEN_E2E_TOKEN e LUMEN_E2E_PARENT.
"""
import json
import os
import sys
import time
from pathlib import Path

import tests  # noqa: F401  (isola LUMEN_DATA)
from lumen import AppError, jobs, llm, notion, sources, store, transcribe
from tests.fake_notion import Fake


def main(folder):
    folder = Path(folder)
    for ext in sources.MEDIA:
        info = sources.probe(folder / f"aula{ext}")
        print(f"ok  probe {ext:5} {info['codec']:8} {info['duration']:.1f}s")
    for bad in ("sem_audio.mp4", "falso.mp4"):
        try:
            sources.probe(folder / bad)
            raise SystemExit(f"FALHOU: {bad} deveria ser rejeitado")
        except AppError as e:
            print(f"ok  rejeita {bad}: {e}")

    _, m = transcribe.pick("rapido")
    if not transcribe.downloaded(m["name"]):
        raise SystemExit(f"Baixe o modelo {m['name']} antes (Configurações ou faster_whisper.download_model).")
    if not llm.models():
        raise SystemExit("Ollama não está rodando.")

    real = os.environ.get("LUMEN_E2E_TOKEN") and os.environ.get("LUMEN_E2E_PARENT")
    fake = None if real else Fake()
    token = os.environ["LUMEN_E2E_TOKEN"] if real else "secret_test"
    root = notion.page_id(os.environ["LUMEN_E2E_PARENT"]) if real else fake.add_page("Estudos")
    store.get_token = lambda: token
    store.save_config({**store.DEFAULTS, "root_page_id": root, "quality": "rapido"})

    def wait():
        last = None
        while (j := jobs.snapshot())["status"] == "running":
            if (j["stage"], j["detail"]) != last:
                print(f"..  {j['stage']}: {j['detail']}")
                last = (j["stage"], j["detail"])
            time.sleep(0.5)
        if j["status"] != "done":
            print(j["status"], j.get("error"))
            raise SystemExit(1)
        return j

    t0 = time.time()
    chosen = notion.create_course(token, root, "Aula de teste Lumen")
    spec = {"kind": "file", "path": str(folder / "aula.mp4"), "course_id": chosen["id"], "course_title": chosen["title"],
            "language": "pt", "mode": "new",
            "speed": "auto"}
    jobs.start("process", jobs.process, spec)
    review = wait()["result"]
    flagged = [s for s in review["segments"] if s["flags"]]
    print(f"ok  revisão: {len(review['segments'])} trechos, {len(flagged)} marcados, velocidade {review['speed']}")
    first = review["segments"][0]["text"]
    edit = {"0": first + " (corrigido na revisão)"}
    jobs.start("process", jobs.finish, {**spec, "edits": edit, "include_transcript": True})
    j = wait()
    print(f"done em {time.time() - t0:.0f}s", j["result"])
    if fake:
        assert not fake.violations, fake.violations
        page = fake.pages[chosen["id"]]
        assert len(fake.pages) == 2, "a publicação não deveria criar uma subpágina"
        assert store.history()[review["key"]]["page_id"] == chosen["id"], "o material deveria ficar na página escolhida"
        toggles = [b for b in page["blocks"] if b["type"] == "toggle"]
        print(f"ok  página “{page['title']}”: {len(page['blocks'])} blocos, {len(toggles)} perguntas com resposta recolhida")
        head = page["blocks"][-1]
        assert head["type"] == "heading_3" and head["heading_3"]["is_toggleable"], "transcrição deveria estar recolhida"
        text = json.dumps(head, ensure_ascii=False)
        assert "corrigido na revisão" in text, "a página deveria usar a transcrição revisada"
        print(f"ok  transcrição completa recolhida com {len(head['heading_3']['children'])} parágrafos, com a correção")
        Path(os.environ["LUMEN_DATA"], "e2e_page.json").write_text(json.dumps(page, ensure_ascii=False, indent=1), "utf-8")
        print("    blocos salvos em", Path(os.environ["LUMEN_DATA"], "e2e_page.json"))
        fake.close()


if __name__ == "__main__":
    main(sys.argv[1])
