r"""Destinos do material na interface: Ajustes (cofre, pasta, modo), resultado por destino e Biblioteca.

Abra o Edge sem tela pelo PowerShell (lançado pelo Python ele não abre a porta de depuração), com
--remote-debugging-port=9353 --headless=new --disable-gpu e uma pasta de perfil temporária. Depois, na raiz:
  .venv\Scripts\python tests\obsidian_ui.py . 9353 [pasta-das-capturas]     (precisa do Node; dados isolados)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["LUMEN_DATA"] = tempfile.mkdtemp(prefix="lumen-ui-obs-")
TMP = Path(tempfile.mkdtemp(prefix="lumen-ui-vault-"))
os.environ["APPDATA"] = str(TMP / "appdata")  # obsidian.json simulado: o Obsidian real do usuário não é lido
ROOT, HERE, PORT = Path(sys.argv[1]).resolve(), Path(__file__).parent, sys.argv[2]
SHOTS = Path(sys.argv[3]) if len(sys.argv) > 3 else None
sys.path.insert(0, str(ROOT))
from lumen import server, store  # noqa: E402
from tests.test_obsidian import make_vault  # noqa: E402

VAULT = TMP / "Cérebro de teste"
VAULT.mkdir()
make_vault(VAULT)
(TMP / "appdata" / "obsidian").mkdir(parents=True)
(TMP / "appdata" / "obsidian" / "obsidian.json").write_text(json.dumps({"vaults": {
    "a": {"path": str(VAULT), "open": True}, "b": {"path": str(TMP / "Outro cofre")}}}), "utf-8")
store.save_config({**store.DEFAULTS})
httpd = server.serve()
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{httpd.server_port}/"
bridge = subprocess.Popen([shutil.which("node"), str(HERE / "cdp_bridge.mjs"), PORT], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True, encoding="utf-8")
fails = []


def cmd(**c):
    bridge.stdin.write(json.dumps(c) + "\n")
    bridge.stdin.flush()
    r = json.loads(bridge.stdout.readline())
    if not r["ok"]:
        raise RuntimeError(r["error"])
    return r["value"]


def ev(expr):
    return cmd(op="eval", name="m", expr=expr)


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def shot(tag):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        cmd(op="shot", name="m", path=str(SHOTS / f"{tag}.png"))


try:
    cmd(op="open", name="m", url=url, w=1120, h=900)
    for _ in range(60):  # o estado (/api/state) pode demorar com o Ollama ocupado
        if ev("typeof S !== 'undefined' && !!S"):
            break
        time.sleep(0.5)
    ev("document.querySelector('#nav-integrations').click()")  # cofre e destinos: página Integrações
    time.sleep(0.6)
    opts = ev("[...document.querySelectorAll('#vault option')].map(o => [o.value, o.textContent, o.disabled])")
    check(opts[0][0] == "" and len(opts) == 3, f"cofres listados sem escolher sozinho: {opts}")
    check(any(o[2] for o in opts), "cofre que não existe aparece desabilitado")
    check("mais de um cofre" in ev("document.querySelector('#vault-status').textContent"), "pede para escolher entre vários")
    check(ev("document.querySelector('#dest-mode input[value=notion]').checked"), "padrão seguro: só Notion")
    ev("document.querySelector('#dest-settings').scrollIntoView()")
    shot("1-ajustes-sem-cofre")

    # Obsidian sem cofre: recusado com a mensagem certa, e o modo volta para o que estava salvo
    ev("(() => { const r = document.querySelector('#dest-mode input[value=obsidian]'); r.checked = true;"
       " r.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.8)
    toast = ev("document.querySelector('#toast').textContent")
    check("cofre" in toast.lower(), f"sem cofre, o Obsidian não liga: {toast!r}")
    check(store.load_config()["destinations"] == "notion", "config continua só Notion")

    ev(f"(() => {{ const s = document.querySelector('#vault'); s.value = {json.dumps(str(VAULT))};"
       " s.dispatchEvent(new Event('change')); })()")
    time.sleep(0.8)
    check(store.load_config()["obsidian_vault"] == str(VAULT.resolve()), "cofre salvo ao escolher")
    status = ev("document.querySelector('#vault-status').textContent")
    check("“Estudos”" in status and "uma pasta por aula" in status, f"mostra onde os estudos ficam: {status!r}")
    ev("(() => { const r = document.querySelector('#dest-mode input[value=both]'); r.checked = true;"
       " r.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.8)
    check(store.load_config()["destinations"] == "both", "Notion + Obsidian salvo")
    ev("(() => { const i = document.querySelector('#review-intervals'); i.value = '2, 1, 9';"
       " i.dispatchEvent(new Event('change')); })()")
    time.sleep(0.6)
    check(store.load_config()["review_intervals"] == [1, 3, 7, 14, 30, 60], "intervalos fora de ordem recusados")
    ev("(() => { const i = document.querySelector('#vault-folder'); i.value = '../fora';"
       " i.dispatchEvent(new Event('change')); })()")
    time.sleep(0.6)
    check(store.load_config()["obsidian_folder"] == "", "pasta fora do cofre recusada")
    ev("(() => { const r = document.querySelector('#study-level input[value=profundo]'); r.checked = true;"
       " r.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.6)
    check(store.load_config()["study_level"] == "profundo", "profundidade salva")
    ev("document.querySelector('#dest-settings').scrollIntoView()")
    shot("2-ajustes-com-cofre")
    ev("document.querySelector('#nav-new').click()")  # sair das Integrações aplica o que mudou (como fechar os Ajustes)
    time.sleep(0.8)

    # Nova aula só no Obsidian: a organização continua sendo a mesma (um seletor só), e o Notion fica desativado
    ev("(() => { document.querySelector('#nav-integrations').click(); const m = document.querySelector('#dest-mode input[value=obsidian]');"
       " m.checked = true; m.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.8)
    ev("document.querySelector('#nav-new').click()")
    time.sleep(0.8)
    check(ev("document.querySelector('#org-type').textContent") == "A organizar", "organização: “organizar depois” por padrão")
    dest = ev("[document.querySelector('#dest-obs-badge').textContent, document.querySelector('#dest-vault').textContent,"
              " document.querySelector('#dest-notion-badge').textContent, document.querySelector('#dest-notion-fix').textContent]")
    check(dest[0] == "Conectado" and "A organizar" in dest[1] and dest[2] == "Desativado" and dest[3] == "Ativar",
          f"Destinos do estudo com o cofre real: {dest}")
    shot("3-nova-aula-so-obsidian")

    # Resultado: um destino ok e outro com falha, com as ações certas
    r = {"key": "yt:x", "title": "RAG", "course": "IA", "dests": ["obsidian", "notion"],
         "notion": {"status": "error", "error": "O Notion limitou o número de pedidos.", "action": "Aguarde um minuto."},
         "obsidian": {"status": "ok", "state": "created", "canvas": "C04/Mapa - RAG.canvas", "connections": 3, "questions": 9,
                      "note": "C04/2026 - RAG.md"}}
    ev("showView('new'); showStep('run'); lastSpec = {classification: {type: 'inbox'}, mode: 'new'}; renderJob(" + json.dumps(
        {"status": "done", "kind": "process", "stage": "obsidian", "dests": ["obsidian", "notion"], "result": r}) + ")")
    text = ev("document.querySelector('#result').innerText")
    buttons = ev("[...document.querySelectorAll('#run-actions .btn')].map(b => b.textContent)")
    ok = ev("[...document.querySelectorAll('#result .dest-line')].map(l => [l.dataset.ok, l.querySelector('b').textContent])")
    check(["true", "Obsidian"] in ok and ["false", "Notion"] in ok and "3 conexões com o cofre" in text, f"linhas por destino: {ok} {text!r}")
    check("Tentar de novo só o Notion" in buttons and "Abrir no Obsidian" in buttons and "Abrir mapa conceitual" in buttons,
          f"botões: {buttons}")
    check(ev("document.querySelector('#result').className") == "result partial", "parcial não é erro genérico")
    shot("4-resultado-parcial")
    cmd(op="dark", name="m", on=True)
    time.sleep(0.3)
    shot("5-resultado-parcial-escuro")
    cmd(op="dark", name="m", on=False)
    stages = ev("[...document.querySelectorAll('#stages li')].filter(l => !l.hidden).map(l => l.dataset.stage)")
    check(stages[-2:] == ["obsidian", "publish"], f"etapas com os dois destinos: {stages}")

    store.remember("yt:x", {"title": "RAG", "course": "IA", "lumen_id": "lm-0123456789abcdef",
                            "obsidian": {"status": "ok", "note": "C04/x.md", "at": "2026-10-23T10:00:00"}})
    ev("showView('library')")
    time.sleep(0.8)
    lib = ev("document.querySelector('#library-list').innerText")
    check("RAG" in lib and "Obsidian" in lib, f"Biblioteca com aula só no Obsidian: {lib!r}")
    shot("6-biblioteca")
    errors = cmd(op="errors")
    check(not errors.get("m"), f"sem erros de JavaScript: {errors}")
finally:
    try:
        cmd(op="quit")
    except Exception:  # noqa: BLE001
        pass
    httpd.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    shutil.rmtree(os.environ["LUMEN_DATA"], ignore_errors=True)
print("\n" + ("TUDO OK" if not fails else f"{len(fails)} FALHA(S)"))
sys.exit(1 if fails else 0)
