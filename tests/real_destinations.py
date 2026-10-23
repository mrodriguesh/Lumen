r"""Teste real controlado dos dois destinos: Ollama real, Notion real (página “Sem curso” da raiz) e o cofre real.

Uma aula de teste (legenda colada sobre RAG) passa por todo o caminho do app: preparar → compreensão → análise da
IA → material (uma geração) → Obsidian + Notion. Confere o resultado e, com --limpar, apaga o que criou (blocos no
Notion, a nota, o canvas e os anexos no cofre; o painel do Lumen fica). Dados do Lumen isolados numa pasta temporária.
  .venv\Scripts\python tests\real_destinations.py <cofre> [--limpar]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

REAL = json.loads((Path(os.environ["LOCALAPPDATA"]) / "Lumen" / "config.json").read_text("utf-8"))
os.environ["LUMEN_DATA"] = tempfile.mkdtemp(prefix="lumen-real-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumen import jobs, notion, sources, store, understanding  # noqa: E402

VAULT, CLEAN = Path(sys.argv[1]), "--limpar" in sys.argv
CAPTIONS = """0:00
Hoje vamos entender o que é RAG, a geração aumentada por recuperação, usada em assistentes de inteligência artificial.
0:20
Um modelo de linguagem só sabe o que viu no treinamento. Quando falta informação, ele pode inventar uma resposta.
0:45
No RAG, antes de responder, o sistema busca trechos relevantes nos seus documentos e entrega esses trechos ao modelo.
1:10
Primeiro os documentos são divididos em pedaços menores, chamados chunks, com um pouco de sobreposição entre eles.
1:35
Cada pedaço vira um embedding, um vetor de números que representa o sentido do texto.
2:00
Os vetores ficam guardados num banco vetorial, que encontra os vetores mais parecidos com o da pergunta.
2:25
Na hora da pergunta, ela também vira um vetor, e o banco devolve os trechos mais próximos.
2:50
Esses trechos entram no prompt, e o modelo responde com base neles, citando as fontes.
3:15
Se os pedaços forem grandes demais, a busca fica imprecisa e o contexto enche de texto irrelevante.
3:40
Um exemplo: um chat que responde dúvidas sobre o manual interno de uma empresa sem treinar o modelo de novo.
4:05
Resumindo: o RAG troca memória por consulta. O modelo continua o mesmo; o que muda é o contexto que ele recebe."""
NOTE = ("Entendi que o RAG serve para a IA não inventar coisas. Antes de responder, ela procura nos documentos os "
        "trechos parecidos com a pergunta. Os documentos são cortados em pedaços e cada pedaço vira um vetor que fica "
        "num banco vetorial. Acho que o modelo é treinado de novo com esses documentos para aprender o conteúdo.")
SPEC = {"kind": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ", "captions": CAPTIONS, "language": "pt",
        "mode": "new", "course_id": "__none__", "course_title": ""}


def wait(label):
    t0 = time.monotonic()
    while True:
        j = jobs.snapshot()
        if j["status"] != "running":
            print(f"{label}: {j['status']} em {time.monotonic() - t0:.0f} s")
            if j["status"] != "done":
                raise SystemExit(json.dumps(j.get("error"), ensure_ascii=False))
            return j
        time.sleep(1)


store.save_config({**store.DEFAULTS, "root_page_id": REAL["root_page_id"], "root_page_title": REAL["root_page_title"],
                   "ollama_model": REAL.get("ollama_model") or "qwen3:8b", "destinations": "both",
                   "obsidian_vault": str(VAULT), "study_level": "balanceado"})
token, root = store.get_token(), REAL["root_page_id"]
had_no_course = any(c["title"] == notion.NO_COURSE for c in notion.list_courses(token, root))
with mock.patch.object(sources, "youtube_meta", return_value={"title": "Teste do Lumen: RAG", "author": "Lumen"}):
    jobs.start("process", jobs.process, SPEC, spec=SPEC)
    key = wait("preparação")["result"]["key"]
    understanding.submit(key, NOTE)
    understanding.begin_analysis(key)
    jobs.start("analyze", jobs.analyze, key, spec={"key": key})
    wait("análise da compreensão")
    print("confusões apontadas pela IA:", json.dumps(understanding.load(key)["ai_analysis"]["confusoes"], ensure_ascii=False))
    jobs.start("process", jobs.finish, SPEC, spec=SPEC)
    res = wait("material + destinos")["result"]

print(json.dumps({k: res[k] for k in ("notion", "obsidian")}, ensure_ascii=False, indent=1))
entry = store.history()[key]
ob = res["obsidian"]
note = VAULT / ob["note"]
text = note.read_text("utf-8")
checks = {
    "Notion ok": res["notion"]["status"] == "ok",
    "Obsidian ok": ob["status"] == "ok",
    "canvas criado": bool(ob.get("canvas")) and (VAULT / ob["canvas"]).exists(),
    "nota aponta para o Notion": f'notion: "{res["notion"]["url"]}"' in text,
    "minha compreensão intacta": NOTE[:80] in text.replace("\n> ", " "),
    "blocos no Notion": len(entry["block_ids"]) > 5,
    "pacote guardado": (store.DATA / "packages" / f"{entry['lumen_id']}.json").exists(),
}
blocks = notion.request("GET", f"/blocks/{entry['page_id']}/children?page_size=100", token)["results"]
checks["Notion tem o resumo do mesmo pacote"] = any(b["type"] == "heading_2" for b in blocks)
pkg = json.loads((store.DATA / "packages" / f"{entry['lumen_id']}.json").read_text("utf-8"))
checks["resumo igual nos dois"] = pkg["lesson"]["summary"].split("\n")[0][:60] in text
for k, v in checks.items():
    print(("ok   " if v else "FAIL ") + k)
print("perguntas por tipo:", sorted(q.get("kind") for q in pkg["lesson"]["review_questions"]))
print("conexões:", pkg["connections"], "âncoras:", pkg["anchors"], "sugestão:", pkg["anchor_suggestion"])
print("relações:", pkg["lesson"].get("relations"), "map_kind:", pkg["lesson"].get("map_kind"))
chk = subprocess.run(["node", str(VAULT / ".claude/scripts/vault-check.mjs"), str(VAULT)], capture_output=True,
                     text=True, encoding="utf-8")
print(chk.stdout.strip().splitlines()[-1])
copy = Path(os.environ.get("LUMEN_COPY_TO", ""))
if copy.name:  # para abrir no Obsidian isolado do teste visual
    for rel in (ob["note"], ob["canvas"]):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(VAULT / rel, copy / rel)
    print("copiado para", copy)

if CLEAN:
    for bid in entry["block_ids"]:
        try:
            notion.request("DELETE", f"/blocks/{bid}", token)
        except Exception as e:  # noqa: BLE001
            print("não apagou", bid, type(e).__name__)
    if not had_no_course:
        for c in notion.list_courses(token, root):
            if c["title"] == notion.NO_COURSE:
                notion.trash(token, c["id"])
    note.unlink()
    (VAULT / ob["canvas"]).unlink()
    for f in (VAULT / Path(ob["note"]).parent / "Anexos").glob(f"{pkg['date']} *"):
        f.unlink()
    print("limpo: blocos do Notion, nota, canvas e anexos de teste")
shutil.rmtree(os.environ["LUMEN_DATA"], ignore_errors=True)
sys.exit(0 if all(checks.values()) else 1)
