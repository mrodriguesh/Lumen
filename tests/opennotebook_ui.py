"""Open Notebook: a aba de Integrações e o envio de uma transcrição, no NAVEGADOR (Chrome headless, Playwright), com o
servidor real do Lúmen em dados isolados no D: e a API REAL do Open Notebook instalado (ON_API, padrão http://127.0.0.1:5055).

  py -3.14 tests/opennotebook_ui.py        capturas em LUMEN_ON_SHOTS (padrão D:/Lumen/open-notebook-20261115/ui/<execução>)

Cria um caderno temporário pela API e, pelo botão da interface, o “Lúmen — Transcrições”; no fim apaga só o que criou
nesta execução (pelo id), com a fonte de teste. Nenhum caderno que já existia é tocado. NÃO é a janela nativa (WebView2)
nem os dados reais de %LOCALAPPDATA%\\Lumen; com o Open Notebook parado, o teste para no início e avisa."""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from ui_harness import serve  # noqa: E402

API = os.environ.get("ON_API", "http://127.0.0.1:5055")
RUN = time.strftime("%Y%m%d-%H%M%S")
OUT = Path(os.environ.get("LUMEN_ON_SHOTS") or f"D:/Lumen/open-notebook-20261115/ui/{RUN}")
DATA = Path(f"D:/Lumen/open-notebook-20261115/dados-{RUN}")
NAME, TEMP_NAME, KEY, TITLE = "Lúmen — Transcrições", f"Lúmen — verificação {RUN} (temporário)", f"teste:on:{RUN}", f"Aula de verificação {RUN}"
fails = []


def check(ok, what):
    print(("ok   " if ok else "FALHA ") + what)
    if not ok:
        fails.append(what)


def on(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"null")


try:
    before = on("GET", "/api/notebooks")
except (urllib.error.URLError, OSError) as e:
    sys.exit(f"Open Notebook fora do ar em {API} ({type(e).__name__}): nada foi verificado.")
existed = {n["id"] for n in before}
print(f"Open Notebook {on('GET', '/api/config')['version']} em {API}; {len(before)} caderno(s) antes do teste")

OUT.mkdir(parents=True, exist_ok=True)
store = DATA / "Lumen"
work = store / "work" / hashlib.sha256(KEY.encode()).hexdigest()[:16]
work.mkdir(parents=True)
(work / "transcript.json").write_text(json.dumps({"language": "pt", "duration": 9, "segments": [
    {"start": 0, "end": 4, "text": "Esta é uma transcrição de verificação do Lúmen."},
    {"start": 4, "end": 9, "text": "Pode ser apagada sem problema."}]}, ensure_ascii=False), "utf-8")
(store / "history.json").write_text(json.dumps({KEY: {
    "title": TITLE, "url": "https://www.notion.so/verificacao", "created": "2026-11-15T12:00:00",
    "lumen_id": "lm-" + hashlib.sha256(KEY.encode()).hexdigest()[:16],
    "classification": {"type": "course", "course": "Curso de verificação", "module": "Módulo 1"}}}, ensure_ascii=False), "utf-8")
temp = on("POST", "/api/notebooks", {"name": TEMP_NAME, "description": "Criado por tests/opennotebook_ui.py; pode apagar."})

try:
    with serve(ROOT, DATA, log=OUT / "lumen-stderr.txt") as H, sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1280, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(H.url)
        page.wait_for_function("() => typeof S !== 'undefined' && S && window.lumenON")
        text = lambda sel: page.inner_text(sel).strip()  # noqa: E731
        shot = lambda name: page.screenshot(path=str(OUT / f"{name}.png"))  # noqa: E731

        page.evaluate("() => { showView('integrations'); integSelect('opennotebook'); }")
        page.wait_for_function("() => document.querySelector('#on-status').textContent.includes('Desconectado')")
        check(page.input_value("#on-url") == "http://127.0.0.1:5055" and not page.is_checked("#on-auto"),
              "padrões: API em http://127.0.0.1:5055 e envio automático desligado")
        check(page.is_hidden("#on-book-sec"), "desconectado: sem seletor de caderno")
        shot("1-desconectado")

        page.fill("#on-url", "http://127.0.0.1:9")  # ninguém escuta aqui: o mesmo que o serviço parado
        page.click("#on-connect")
        page.wait_for_function("() => document.querySelector('#on-status').textContent.includes('indisponível')")
        check(page.evaluate("() => (showView('library'), !!document.querySelector('#library-list'))"), "serviço indisponível: o Lúmen segue navegável")
        page.evaluate("() => showView('integrations')")
        shot("2-indisponivel")

        page.fill("#on-url", API)
        page.click("#on-connect")
        page.wait_for_function("() => document.querySelector('#on-status').textContent.includes('Conectado')")
        check("versão" in text("#on-status") and "Conectado" in text("#on-badge"), f"conectado à API real: {text('#on-status')!r}")
        check(TEMP_NAME in text("#on-book"), "o caderno temporário aparece no seletor")

        if any(n["name"] == NAME for n in before):
            check(page.is_hidden("#on-create"), "“Lúmen — Transcrições” já existia: o botão de criar não aparece")
        else:
            page.click("#on-create")
            page.wait_for_function("() => document.querySelector('#on-create').hidden")
            H.call("/api/opennotebook/notebook", {"create": True})  # pedir de novo não duplica
            same = [n for n in on("GET", "/api/notebooks") if n["name"] == NAME]
            check(len(same) == 1, f"“Lúmen — Transcrições” criado uma vez só ({len(same)})")
        page.select_option("#on-book", temp["id"])
        page.wait_for_function("id => S && document.querySelector('#on-book').value === id", arg=temp["id"])
        time.sleep(0.5)
        check(H.call("/api/opennotebook")["opennotebook_notebook"] == temp["id"], "caderno temporário escolhido como destino")
        page.focus("#on-book")
        shot("3-conectado")
        cfg = (store / "config.json").read_text("utf-8")
        check('"opennotebook_on": true' in cfg and "password" not in cfg.lower(), "config.json: integração ligada, nenhuma senha")

        page.evaluate("() => refresh().then(() => showView('library'))")
        page.wait_for_selector(f".lib-row[data-key='{KEY}'] [aria-label^='Open Notebook']")
        page.click(f".lib-row[data-key='{KEY}'] [aria-label^='Open Notebook']")
        page.wait_for_function("() => document.querySelector('#on-dlg-state').textContent.includes('ainda não foi enviada')")
        what = text("#on-dlg-what")
        check("Nenhum áudio ou vídeo" in what and TEMP_NAME in what and API in what, f"o diálogo diz o que vai e para onde: {what!r}")
        check(page.is_visible("#on-dlg-send") and page.is_visible("#on-dlg-send-open"), "ações: Enviar e Enviar e abrir")
        shot("4-dialogo-antes")

        page.click("#on-dlg-send")
        page.wait_for_function("() => !/Enviando|ainda não/.test(document.querySelector('#on-dlg-state').textContent)", timeout=40000)
        first = text("#on-dlg-state")
        shot("5-enviado")
        sources = on("GET", "/api/sources?" + urllib.parse.urlencode({"notebook_id": temp["id"]}))
        check(len(sources) == 1 and sources[0]["title"] == TITLE, f"uma fonte no caderno real, com o título da aula ({len(sources)})")
        again = H.call("/api/opennotebook/send", {"key": KEY})
        check(len(on("GET", "/api/sources?" + urllib.parse.urlencode({"notebook_id": temp["id"]}))) == 1,
              f"enviar de novo não cria outra fonte (estado: {again.get('state')})")

        state, t0 = None, time.time()
        while time.time() - t0 < 90:  # o estado real, pela API: depende do worker do Open Notebook
            state = H.call(f"/api/opennotebook/lesson?key={urllib.parse.quote(KEY)}&check=1")["state"]
            if state in ("completed", "failed"):
                break
            time.sleep(3)
        full = on("GET", "/api/sources/" + urllib.parse.quote(sources[0]["id"], safe=""))
        print(f"     estado depois de {time.time() - t0:.0f} s: {state}; primeiro texto do diálogo: {first!r}")
        check(state in ("completed", "queued", "processing"), f"estado honesto do processamento: {state}")
        if state == "completed":
            body = full.get("full_text") or ""
            check("transcrição de verificação" in body and "Curso de verificação" in body and "Idioma: pt" in body,
                  "a fonte processada traz a transcrição e os metadados")
            page.wait_for_function("() => document.querySelector('#on-dlg-state').textContent.includes('pronta')", timeout=15000)
            check(page.is_hidden("#on-dlg-send") and page.is_visible("#on-dlg-open"), "pronta: só “Abrir no Open Notebook”")
        shot("6-estado-final")
        opened = page.evaluate("""() => { let u = null; const w = window.open; window.open = (x) => { u = x; return null; };
            document.querySelector('#on-dlg-open').click(); window.open = w; return u; }""")
        check(opened == f"http://127.0.0.1:3000/notebooks/{urllib.parse.quote(temp['id'], safe='')}", f"abrir leva ao caderno: {opened}")
        page.keyboard.press("Escape")
        check(not page.evaluate("() => document.querySelector('#on-dlg').open"), "Esc fecha o diálogo")

        page.evaluate("() => showView('integrations')")
        page.click("#on-disconnect")
        page.wait_for_function("() => document.querySelector('#on-status').textContent.includes('Desconectado')")
        check(not errors, f"sem erros de JavaScript: {errors}")
        browser.close()
finally:
    for n in on("GET", "/api/notebooks"):  # só o que esta execução criou
        if n["id"] not in existed and n["name"] in (NAME, TEMP_NAME):
            on("DELETE", f"/api/notebooks/{urllib.parse.quote(n['id'], safe='')}?delete_exclusive_sources=true")
    after = on("GET", "/api/notebooks")
    check({n["id"] for n in after} == existed, f"Open Notebook como estava: {len(after)} caderno(s)")
print(f"\ncapturas: {OUT}\n" + ("TUDO OK" if not fails else f"{len(fails)} FALHA(S)"))
sys.exit(1 if fails else 0)
