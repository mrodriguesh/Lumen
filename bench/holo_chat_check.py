"""Verificação real do /elegrama 3d: o fluxo inteiro do chat (agent.turn → fila → desenho no TAMANHO REAL → arquivos conferidos →
mensagem na conversa → reabertura), com dados isolados (LUMEN_DATA temporário, no D: por TMP/TEMP) e a IA de duas formas:

  py -3.14 bench/holo_chat_check.py OUT_DIR                       respostas fixas (Ollama falso): conteúdo conhecido, desenho real
  py -3.14 bench/holo_chat_check.py OUT_DIR --ollama URL [--model NOME]   um Ollama de verdade (por exemplo a instância isolada 11435)

Escreve em OUT_DIR, por caso: <caso>.gif, <caso>.png (reserva), <caso>-quadros.png (início, meio e fim da animação), e report.json
com tempos, pesos, quadros, movimento e a mensagem. Não toca na configuração nem nos dados pessoais do Lúmen."""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import numpy as np  # noqa: E402
from PIL import Image, ImageSequence  # noqa: E402

import tests  # noqa: E402,F401 — LUMEN_DATA temporário (no D: se TMP/TEMP apontam para lá) antes de importar o app
from lumen import jobs, llm, visual3d  # noqa: E402
from lumen.study import agent, artifacts, chats, db, settings  # noqa: E402

visual3d.W, visual3d.H, visual3d.ATTEMPTS = tests.REAL_VISUAL["W"], tests.REAL_VISUAL["H"], tests.REAL_VISUAL["ATTEMPTS"]
KEY = "DADOS de uma visualização 3D"


def part(label, detail, parent=-1):
    return {"label": label, "detail": detail, "parent": parent}


CASES = {
    "processo-fotossintese": ("/elegrama 3d das etapas da fotossíntese", {"concept": "Fotossíntese", "sources": [], "diagram": {
        "family": "processo", "title": "Etapas da fotossíntese", "relations": [], "nodes": [
            part("Absorção de luz", "A clorofila nos cloroplastos captura a energia da luz."),
            part("Fotólise da água", "A luz quebra moléculas de água e libera oxigênio."),
            part("Fase clara", "Produz ATP e NADPH para a fase seguinte."),
            part("Ciclo de Calvin", "Usa o ATP e o NADPH para fixar o CO₂ em açúcar."),
            part("Produção de glicose", "O açúcar formado alimenta a planta.")]}}),
    "sistema-computador": ("/holograma 3d de um computador e seus componentes", {"concept": "Computador", "sources": [], "diagram": {
        "family": "sistema", "title": "Computador e seus componentes", "nodes": [
            part("Processador (CPU)", "Executa as instruções dos programas."),
            part("Memória RAM", "Guarda o que está em uso agora, de forma rápida e temporária."),
            part("Placa-mãe", "Liga e alimenta todos os componentes."),
            part("Armazenamento (SSD)", "Guarda arquivos e programas de forma permanente."),
            part("Placa de vídeo (GPU)", "Desenha imagens e acelera cálculos paralelos."),
            part("Fonte de energia", "Converte a tomada na tensão que cada peça usa.")],
        "relations": [{"from": 0, "to": 1, "kind": "depende de"}, {"from": 0, "to": 3, "kind": "depende de"},
                      {"from": 4, "to": 0, "kind": "depende de"}, {"from": 1, "to": 2, "kind": "parte de"}]}}),
    "estrutura-terra": ("/elegrama 3d das camadas da Terra", {"concept": "Terra", "sources": [], "diagram": {
        "family": "estrutura", "title": "Camadas da Terra", "relations": [], "nodes": [
            part("Crosta", "A camada externa e sólida, onde vivemos."),
            part("Manto superior", "Rocha quente e plástica que se move devagar."),
            part("Manto inferior", "Mais denso e mais quente, sob grande pressão."),
            part("Núcleo externo", "Ferro e níquel líquidos que geram o campo magnético."),
            part("Núcleo interno", "Esfera sólida de ferro e níquel.")]}}),
    "comparacao-dna-rna": ("/elegrama 3d diferenças entre DNA e RNA", {"concept": "DNA e RNA", "sources": [], "diagram": {
        "family": "comparacao", "title": "DNA × RNA", "relations": [], "nodes": [
            part("DNA", "Guarda a informação genética."), part("RNA", "Leva a informação para fazer proteínas."),
            part("Dupla hélice", "Duas fitas enroladas.", 0), part("Açúcar desoxirribose", "Sem oxigênio extra.", 0),
            part("Fita simples", "Uma fita só.", 1), part("Uracila no lugar da timina", "Base exclusiva do RNA.", 1)]}}),
    "estresse-rotulos": ("/elegrama 3d fórmulas e rótulos longos", {"concept": "Teste de rótulos", "sources": [], "diagram": {
        "family": "sistema", "title": "Rótulos longos e símbolos especiais para conferir o enquadramento da cena inteira", "relations": [], "nodes": [
            part("Equação de Schrödinger dependente do tempo e independente", "Descreve a evolução do estado quântico."),
            part("H₂O → H⁺ + OH⁻ (equilíbrio de autoionização da água)", "Equilíbrio químico."),
            part("Constante de Planck ℏ ≈ 1,0546 × 10⁻³⁴ J·s", "Quantum de ação."),
            part("Ação & reação — conceito de “par”", "Terceira lei de Newton."),
            part("Entropia ∑ pᵢ ln pᵢ", "Medida de incerteza."), part("Ångström (Å)", "Unidade de comprimento atômico."),
            part("ñ ç ã é ü", "Acentuação variada.")]}}),
}


def contact(frames, path):
    """Início, meio e fim da animação lado a lado (miniaturas), para conferir que a cena muda."""
    pick = [frames[0], frames[len(frames) // 3], frames[2 * len(frames) // 3], frames[-1]]
    w, h = pick[0].size
    sheet = Image.new("RGB", (w * 2, h * 2))
    for i, im in enumerate(pick):
        sheet.paste(im, ((i % 2) * w, (i // 2) * h))
    sheet.save(path)


SEED = {  # conversas com uma explicação anterior, para o pedido que a cita ("desse processo que você explicou")
    "referencia-processo": [("user", "Como o corpo transforma comida em energia?"),
                            ("assistant", "A respiração celular tem três etapas principais. Primeiro, na glicólise, a glicose é quebrada em duas moléculas "
                                          "de piruvato no citoplasma. Depois, no ciclo de Krebs, dentro das mitocôndrias, o piruvato é oxidado e libera CO₂ e "
                                          "carregadores de elétrons. Por fim, na cadeia transportadora de elétrons, esses carregadores produzem a maior parte do "
                                          "ATP, e o oxigênio recebe os elétrons no final, formando água.")]}


EFFORT = ""


def run(case, text, out_dir, temporary=False):
    t0 = time.monotonic()
    payload = {"text": text, "temporary": temporary, **({"effort": EFFORT} if EFFORT else {})}
    if case in SEED:
        conv = chats.create(None, "Energia", temporary=temporary)
        for role, content in SEED[case]:
            chats.add_message(conv["id"], role, content)
        payload["conversation_id"] = conv["id"]
    events = list(agent.turn(payload, "check-" + case))
    db.close()
    seconds = round(time.monotonic() - t0, 2)
    last = events[-1]
    row = {"caso": case, "pedido": text, "segundos_no_total": seconds, "eventos": [e["type"] for e in events],
           "status": [e["detail"] for e in events if e["type"] == "status" and e.get("detail")]}
    if last["type"] != "done":
        row["erro"] = last
        return row
    msg = last["message"]
    a = msg["meta"]["artifact"]
    path, mime = artifacts.file(a["id"])
    blob = path.read_bytes()
    (out_dir / f"{case}.{a['format']}").write_bytes(blob)
    row.update(artefato={k: a[k] for k in ("kind", "format", "animated", "poster", "width", "height", "frames", "duration_ms",
                                           "state", "reason", "family", "size", "name")}, mime=mime, sha256=hashlib.sha256(blob).hexdigest(),
               render_s=msg["meta"]["holo"]["seconds"], mensagem=msg["content"], alt=a["alt"], fontes=[s["sid"] for s in msg["sources"]])
    if a["poster"]:
        poster, pmime = artifacts.file(a["id"], "poster")
        (out_dir / f"{case}.png").write_bytes(poster.read_bytes())
        row["poster_bytes"] = poster.stat().st_size
    with Image.open(path) as im:
        frames = [f.convert("RGB").copy() for f in ImageSequence.Iterator(im)]
    arr = [np.asarray(f, np.int16) for f in frames]
    diffs = [float(np.abs(arr[i] - arr[i - 1]).mean()) for i in range(1, len(arr))]
    row["quadros"] = {"lidos": len(frames), "com_movimento": sum(d > 0.15 for d in diffs), "distintos": len({hashlib.sha256(x.tobytes()).hexdigest() for x in arr}),
                      "diferenca_media_entre_quadros": round(float(np.mean(diffs)), 3) if diffs else 0}
    if len(frames) > 1:
        contact(frames, out_dir / f"{case}-quadros.png")
    # reabertura: a conversa guardada mostra o mesmo artefato
    cid = next(e["conversation"]["id"] for e in events if e["type"] == "conversation")
    if not temporary:
        again = chats.get(cid)["messages"][-1]["meta"]["artifact"]["id"]
        row["reabertura"] = again == a["id"]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--ollama", default="")
    ap.add_argument("--cases", default="")
    ap.add_argument("--prompts", default="", help="arquivo JSON {caso: pedido} para usar com --ollama")
    ap.add_argument("--effort", default="", help="rapido|equilibrado|profundo|maximo (o modelo que organiza os dados segue o esforço)")
    args = ap.parse_args()
    global EFFORT
    EFFORT = args.effort
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fake = None
    if args.ollama:
        llm.OLLAMA = args.ollama.rstrip("/")
    else:
        from tests.fake_ollama import FakeOllama
        fake = FakeOllama(models=("qwen3.5:4b", "qwen3.5:9b", "qwen3-embedding:0.6b"))
    wanted = [c for c in args.cases.split(",") if c] or list(CASES)
    prompts = json.loads(Path(args.prompts).read_text("utf-8")) if args.prompts else {}
    report = {"modo": "ollama " + args.ollama if args.ollama else "respostas fixas", "tamanho": [visual3d.W, visual3d.H],
              "dados": os.environ["LUMEN_DATA"], "esforco": EFFORT or "equilibrado", "modelos": {"principal": settings.local_model(settings.load()), "rapido": settings.fast_model(settings.load()), "maximo": settings.max_model(settings.load())},
              "casos": []}
    jobs._cancel.clear()
    for case in wanted:
        text, reply = CASES[case] if case in CASES else (prompts[case], None)
        text = prompts.get(case, text)
        if not args.ollama and case in SEED:
            continue
        if fake and reply is not None:
            fake.json_replies[KEY] = reply
        report["casos"].append(run(case, text, out, temporary=False))
        print(json.dumps({k: report["casos"][-1].get(k) for k in ("caso", "segundos_no_total", "render_s", "erro")}, ensure_ascii=False), flush=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    if fake:
        fake.close()
    ok = all("erro" not in c for c in report["casos"])
    print("OK" if ok else "COM ERRO", out / "report.json")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
