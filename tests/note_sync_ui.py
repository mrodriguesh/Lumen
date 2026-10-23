r"""Minha compreensão nas três interfaces (principal, barra lateral, janela flutuante): sincronização, mesma aula e status.

Abra o Edge sem tela pelo PowerShell (lançado pelo Python ele não abre a porta de depuração), com
--remote-debugging-port=9352 --headless=new --disable-gpu --disable-background-timer-throttling
--disable-renderer-backgrounding e uma pasta de perfil temporária. Depois, na raiz do projeto:
  .venv\Scripts\python tests\note_sync_ui.py . 9352        (precisa do Node; usa dados isolados)
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

os.environ["LUMEN_DATA"] = tempfile.mkdtemp(prefix="lumen-ui-sync-")
ROOT, HERE, PORT = Path(sys.argv[1]).resolve(), Path(__file__).parent, sys.argv[2]
sys.path.insert(0, str(ROOT))
NODE = r"%USERPROFILE%\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.19.0-win-x64\node.exe"
from lumen import jobs, server, understanding  # noqa: E402
from tests.test_llm import NOTE  # noqa: E402

CTX = {"recording": False, "job": {"running": False}}
understanding.context = lambda: CTX
httpd = server.serve()
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{httpd.server_port}"
for k, t in (("aula-A", "Aula A"), ("aula-B", "Aula B")):
    understanding.start(k, t, "Curso", {"kind": "recording"})
    understanding.prepared(k)
understanding.start("aula-C", "Aula C", "Curso", {"kind": "recording"})  # não preparada
bridge = subprocess.Popen([NODE, str(HERE / "cdp_bridge.mjs"), PORT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          text=True, encoding="utf-8")
fails = []


def cmd(**c):
    bridge.stdin.write(json.dumps(c) + "\n")
    bridge.stdin.flush()
    r = json.loads(bridge.stdout.readline())
    if not r["ok"]:
        raise RuntimeError(r["error"])
    return r["value"]


ev = lambda n, e: cmd(op="eval", name=n, expr=e)  # noqa: E731
q = lambda n, sel, prop: ev(n, f"document.querySelector({json.dumps(sel)}).{prop}")  # noqa: E731
wait = time.sleep
TXT = {"m": "#u-text", "n": "#nw-text", "w": "#note-text"}
READY = {"m": "#u-hint", "n": "#nw-ready", "w": "#note-ready"}
GO = {"m": "#u-go", "n": "#nw-go", "w": "#note-go"}



def shots(tag):
    for n in "mnw":
        os.environ.get("SHOTS") and cmd(op="shot", name=n, path=str(Path(os.environ["SHOTS"]) / f"{tag}-{n}.png"))


def check(label, ok, extra=""):
    print(("OK   " if ok else "FAIL ") + label, "" if ok else extra)
    if not ok:
        fails.append(label)


def type_into(n, text):
    ev(n, f"""(async () => {{ const t = document.querySelector({json.dumps(TXT[n])}); t.focus();
      for (const ch of {json.dumps(text)}) {{ t.value += ch; t.dispatchEvent(new Event('input', {{bubbles: true}}));
        await new Promise(r => {{ const c = new MessageChannel(); c.port1.onmessage = r; c.port2.postMessage(0); }}); }} }})()""")


def texts():
    return {n: q(n, s, "value") for n, s in TXT.items()}


def labels():
    return {n: q(n, s, "textContent") for n, s in READY.items()}


def gos():
    return {n: {"hidden": q(n, s, "hidden"), "disabled": q(n, s, "disabled")} for n, s in GO.items()}


try:
    cmd(op="open", name="m", url=url + "/", w=1120, h=820)
    wait(2)
    ev("m", "openUnderstanding('aula-A')")
    cmd(op="open", name="n", url=url + "/note?key=aula-A", w=420, h=520)
    cmd(op="open", name="w", url=url + "/widget", w=360, h=440)
    wait(1.5)
    ev("w", "document.body.dataset.expanded='true'; showNote(true)")
    wait(1.5)
    type_into("m", "Obsidian utiliza Markdown")
    wait(.7)
    t = texts()
    check("1 principal -> flutuante e lateral", len(set(t.values())) == 1 and t["n"] == "Obsidian utiliza Markdown", t)
    type_into("n", " e links.")
    wait(.7)
    t = texts()
    check("2 flutuante -> principal e lateral", len(set(t.values())) == 1 and t["m"].endswith("e links."), t)

    print("--- troca de aula")
    ev("m", "openUnderstanding('aula-B')")
    wait(2)
    keys = {"m": ev("m", "U.key"), "n": ev("n", "editor.key"), "w": ev("w", "noteKey")}
    check("3 as três na mesma aula depois da troca", set(keys.values()) == {"aula-B"}, keys)
    t = texts()
    check("4 nenhuma mistura de textos", set(t.values()) == {""}, t)
    check("4b URL da flutuante e título acompanham", "aula-B" in ev("n", "location.search") and "Aula B" in ev("n", "document.title"))
    ev("m", "openUnderstanding('aula-A')")
    wait(2)
    t = texts()
    check("5 voltando à aula A o texto de A volta", set(t.values()) == {"Obsidian utiliza Markdown e links."}, t)
    ev("m", "openUnderstanding('aula-B')")
    wait(2)

    print("--- status (aula B, preparada)")
    lab = labels()
    check("6 vazio: 'Escreva sua compreensão'", all("Escreva sua compreensão" in v for v in lab.values()), lab)
    check("6b botões bloqueados", all(g["disabled"] or g["hidden"] for g in gos().values()), gos())
    type_into("w", "Escrevendo")
    wait(.2)
    check("7 pouco texto: motivo com faltam N palavras", "faltam" in labels()["w"], labels())
    type_into("w", " " + NOTE)
    wait(.1)
    lab = labels()
    check("8 digitando: 'Salvando' (compacto traz o estado de salvamento)", "Salvando" in lab["w"] or "Salvo" in lab["w"], lab)
    wait(1.6)
    lab = labels()
    check("9 tudo pronto: 'Pronto para analisar' nas três", all("Pronto para analisar" in v for v in lab.values()), lab)
    g = gos()
    check("9b botão habilitado nas três", all(not x["disabled"] and not x["hidden"] for x in g.values()), g)

    shots("ready")
    print("--- gravação ativa")
    CTX["recording"] = True
    wait(3.6)
    shots("recording")
    lab = labels()
    check("10 gravação: motivo nas três", all("gravação" in v for v in lab.values()), lab)
    g = gos()
    check("10b botão não executa nas três", all(x["disabled"] or x["hidden"] for x in g.values()), g)
    CTX["recording"] = False
    wait(3.6)
    check("10c liberou quando a gravação acabou", all("Pronto" in v for v in labels().values()), labels())

    print("--- processar pela flutuante")
    with mock.patch.object(jobs, "start"):  # sem IA: só a trava e o estado
        ev("n", "document.querySelector('#nw-go').click()")
        wait(2.5)
    shots("analyzing")
    check("11 servidor travou a nota", understanding.analyzing == "aula-B")
    lab = {**labels(), "m": q("m", "#u-status", "textContent")}  # na principal, a caixa de status mostra a análise
    check("11b 'Analisando…' nas três", all("Analisando" in v for v in lab.values()), lab)
    g = gos()
    check("11c botão some/bloqueia nas três (sem processar duas vezes)", all(x["hidden"] or x["disabled"] for x in g.values()), g)
    ro = {n: q(n, s, "readOnly") for n, s in TXT.items()}
    check("12 editores só leitura durante a análise", all(ro.values()), ro)
    before = understanding.get("aula-B")["text"]
    status = ev("w", """fetch('/api/understanding/draft', {method:'POST', headers:{'X-Lumen-Token': document.querySelector('meta[name=lumen-token]').content, 'Content-Type':'application/json'}, body: JSON.stringify({key:'aula-B', text:'tentativa no meio da análise', at: Date.now()})}).then(r => r.status)""")
    check("12b servidor recusa edição durante a análise", status == 400 and understanding.get("aula-B")["text"] == before, status)

    print("--- análise termina")
    understanding.end_analysis()
    understanding.save_analysis("aula-B", {"acertos": ["x"]}, understanding.get("aula-B")["text"], "m")
    wait(3.8)
    lab = labels()
    check("13 'Análise concluída' na lateral e na flutuante", "Análise concluída" in lab["w"] and "Análise concluída" in lab["n"], lab)

    shots("done")
    print("--- autosave atrasado de outra janela")
    cur = understanding.get("aula-B")
    stale = ev("w", f"""fetch('/api/understanding/draft', {{method:'POST', headers:{{'X-Lumen-Token': document.querySelector('meta[name=lumen-token]').content, 'Content-Type':'application/json'}}, body: JSON.stringify({{key:'aula-B', text:'VERSÃO ANTIGA', at: {cur["at"] - 5000}}})}}).then(r => r.json())""")
    check("14 atrasado é ignorado e devolve a versão nova", stale["stale"] and stale["text"] == cur["text"] and understanding.get("aula-B")["text"] == cur["text"], stale.get("text", "")[:30])

    print("--- aula C (preparando)")
    CTX["job"] = {"running": True, "kind": "process", "key": "aula-C", "detail": "Transcrevendo"}
    snap = mock.patch.object(jobs, "snapshot", return_value={"status": "running", "kind": "process", "key": "aula-C", "detail": "Transcrevendo"})
    snap.start()
    ev("m", "openUnderstanding('aula-C')")
    wait(2.5)
    lab = labels()
    check("15 'Preparando a aula…' nas três", all("Preparando" in v for v in lab.values()), lab)
    check("15b nas três o botão não processa", all(x["disabled"] or x["hidden"] for x in gos().values()), gos())
    type_into("n", "Escrevo enquanto a aula prepara")
    wait(.8)
    shots("preparing")
    t = texts()
    check("15c dá para escrever e sincroniza durante a preparação", len(set(t.values())) == 1 and t["m"], t)
    CTX["job"] = {"running": False}
    snap.stop()
    understanding.prepared("aula-C")
    wait(3.8)
    lab = labels()
    check("16 preparação pronta: status muda sem recarregar", all("Preparando" not in v for v in lab.values()), lab)

    print("errors:", cmd(op="errors"))
finally:
    try:
        cmd(op="quit")
    except Exception:
        bridge.kill()
    httpd.shutdown()
print("FALHAS:", fails or "nenhuma")
