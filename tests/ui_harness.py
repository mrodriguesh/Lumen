"""Servidor REAL e isolado + capturas das janelas do Lumen para verificar temas (Playwright + Chrome sem GPU, como o WebView2).

    with serve(ROOT, DATA_DIR) as H:   H.url, H.call(path, body)   (LUMEN_DATA em DATA_DIR; Ollama falso; nada do usuário)
    shots(browser, H, outdir, prefix)  salva as capturas de todas as janelas

É teste de NAVEGADOR (Chrome headless): não é o Lumen.exe nativo. A parte nativa (cores do Windows, DWM) é conferida em
tests/DesktopChecks.cs. Os dados são sempre isolados: DATA_DIR fica no D:, nunca em %LOCALAPPDATA%\\Lumen.
"""
import json
import os
import re
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

BOOT = r"""
import sys
sys.path.insert(0, sys.argv[1])
import importlib.util
spec = importlib.util.spec_from_file_location("fake_ollama", sys.argv[1] + "/tests/fake_ollama.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)   # sem o pacote tests (ele trocaria o LUMEN_DATA)
fake = mod.FakeOllama()
from lumen import server, store
store.get_token = lambda: ""           # nunca o token real do Notion
from lumen.study import settings
settings.api_key = lambda *a, **kw: ""  # nem as chaves reais dos provedores externos
def _fake(h):                          # controle do Ollama falso (resposta e ritmo do streaming), só nos testes
    b = h._json()
    if "answer" in b: fake.answer = b["answer"]
    if "delay" in b: fake.delay = float(b["delay"])
    return {"ok": True}
server.ROUTES[("POST", "/api/study/__fake")] = _fake
h = server.serve(); print(h.server_port, flush=True); h.serve_forever()
"""


@contextmanager
def serve(root, data, log=None):
    root, data = Path(root), Path(data)
    data.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "LUMEN_DATA": str(data), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
    logf = open(log, "w", encoding="utf-8") if log else subprocess.DEVNULL
    py = root / ".venv/Scripts/python.exe"
    if not py.exists():  # cópia do projeto sem .venv (a restauração): usa o do projeto original
        py = Path("D:/Aplicativos/lumen 2026/.venv/Scripts/python.exe")
    proc = subprocess.Popen([str(py), "-u", "-c", BOOT, str(root)], cwd=root, env=env, stdout=subprocess.PIPE, stderr=logf, text=True)
    try:
        url = "http://127.0.0.1:" + proc.stdout.readline().strip()
        box = {"token": None}

        def call(path, body=None, raw=False):
            if box["token"] is None:
                html = urllib.request.urlopen(url + "/widget").read().decode()
                box["token"] = re.search(r'name="lumen-token" content="([^"]+)"', html).group(1)
            req = urllib.request.Request(url + path, headers={"X-Lumen-Token": box["token"], "Content-Type": "application/json"})
            if body is not None:
                req.data = json.dumps(body).encode()
            try:
                data_ = urllib.request.urlopen(req).read()
            except urllib.error.HTTPError as e:
                data_ = e.read()
                if raw:
                    return e.code, data_
                return {"_http": e.code, **(json.loads(data_ or b"{}"))}
            return (200, data_) if raw else json.loads(data_ or b"{}")

        yield SimpleNamespace(url=url, call=call, data=data / "Lumen", proc=proc)  # store.DATA = LUMEN_DATA/Lumen
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if log:
            logf.close()


def widget_stub(page, **recording):
    """Responde /api/widget com o servidor real, trocando só `recording` (gravando, pausado, erro) — a API de gravação não é tocada."""
    def handler(route):
        try:
            resp = route.fetch()
            d = json.loads(resp.body())
            d["recording"] = {**d["recording"], **recording}
            route.fulfill(response=resp, body=json.dumps(d), headers={**resp.headers, "content-type": "application/json"})
        except Exception:  # a página fechou no meio do pedido
            pass
    page.route("**/api/widget", handler)


HOST_STUB = ("window.messages=[]; window.hostListeners=[]; window.chrome = window.chrome || {}; "
             "window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(t,fn)=>hostListeners.push(fn)};")


def open_widget(ctx, url, rec=None):
    """A barra no navegador: sem o Lumen.exe, `chrome.webview` é um registro de mensagens e o mouse a expande (como na janela real)."""
    w = ctx.new_page()
    if rec is not None:
        widget_stub(w, **rec)
    w.goto(url + "/widget")
    w.wait_for_function("() => typeof state !== 'undefined' && state !== null")
    w.mouse.move(100, 100)
    w.wait_for_function("() => document.body.dataset.expanded === 'true'")
    return w


def settle(page, ms=450):
    """Espera o que carrega sozinho (fontes, esqueletos de lista) e um respiro: assim duas capturas do mesmo estado saem iguais."""
    page.evaluate("document.fonts && document.fonts.ready")
    try:
        page.wait_for_function("() => !document.querySelector('.skeleton, [aria-busy=true]')", timeout=4000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


MAIN_VIEWS = ["home", "new", "library", "study", "integrations"]
SETTINGS_CATS = ["general", "appearance", "capture", "pomodoro", "transcription", "ai", "covers", "privacy", "diagnostics", "protection"]


def shots(browser, H, out, prefix="", only=None, extra_settings=()):
    """Capturas (PNG) de: janela principal (telas e ajustes), diálogo/aviso/dica, barra flutuante (parada, gravando, pausada, erro,
    ajustes, conversa), nota flutuante e o mostruário /design. Movimento reduzido (sem animações), para o antes/depois ser comparável."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    want = (lambda n: True) if not only else (lambda n: any(o in n for o in only))
    done = []

    def save(page, name, full=False):
        if want(name):
            page.screenshot(path=str(out / f"{prefix}{name}.png"), full_page=full)
            done.append(name)

    errors = []
    ctx = browser.new_context(viewport={"width": 1120, "height": 860}, device_scale_factor=1, reduced_motion="reduce", color_scheme="dark")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"main: {e}"))
    page.goto(H.url + "/")
    page.wait_for_function("typeof showView === 'function'")
    settle(page, 900)
    for v in MAIN_VIEWS:
        page.evaluate(f"showView('{v}')")
        if v == "study":  # a aba carrega o estado da IA e a lista de conversas depois de abrir
            try:
                page.wait_for_function("() => /Todos os projetos/.test(document.body.innerText) && /IA local|Ollama/.test(document.body.innerText)", timeout=8000)
            except Exception:
                pass
        settle(page)
        save(page, f"main-{v}")
    for cat in [*SETTINGS_CATS, *extra_settings]:
        if cat == "appearance" and not page.evaluate("!!document.querySelector('[data-cat=appearance]')"):
            continue  # o código original (antes dos temas) não tem esta categoria
        page.evaluate(f"goSettings('{cat}')")
        settle(page)
        save(page, f"main-ajustes-{cat}")
    # componentes que flutuam: aviso, diálogo de confirmação e dica
    page.evaluate("goSettings('general')")
    page.evaluate("ui.toast('Ajustes salvos. Este é um aviso de exemplo.', 'success')")
    settle(page, 300)
    save(page, "main-aviso")
    page.evaluate("() => { ui.confirm('Descartar esta gravação? Essa ação não pode ser desfeita.', { danger: true, confirmText: 'Descartar' }); }")  # a promessa só resolve com o clique
    settle(page, 350)
    save(page, "main-dialogo")
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    tip = page.locator("#nav-new")
    tip.hover()
    settle(page, 500)
    save(page, "main-dica")
    # janela estreita (mínima do app)
    page.set_viewport_size({"width": 520, "height": 560})
    page.evaluate("showView('home')")
    settle(page)
    save(page, "main-520")
    ctx.close()

    # barra flutuante 304 x 252 (a janela real); estados de gravação por resposta simulada de /api/widget
    for name, rec in [("parada", None), ("gravando", dict(active=True, paused=False, seconds=75, elapsed=76, level=.2, heard=True)),
                      ("pausada", dict(active=True, paused=True, seconds=75, elapsed=96, paused_for=20, pause_count=1, heard=True)),
                      ("erro", dict(active=False, error="Não foi possível abrir o microfone."))]:
        ctx = browser.new_context(viewport={"width": 304, "height": 252}, device_scale_factor=2, reduced_motion="reduce")
        ctx.add_init_script(HOST_STUB)
        ctx.on("page", lambda pg: pg.on("pageerror", lambda e: errors.append(f"widget: {e}")))
        w = open_widget(ctx, H.url, rec)
        settle(w, 900)
        save(w, f"barra-{name}")
        if name == "parada":
            w.click("#settings")
            settle(w, 600)
            save(w, "barra-ajustes")
            w.keyboard.press("Escape")
            w.reload()
            w.wait_for_function("() => typeof state !== 'undefined' && state !== null")
            w.mouse.move(100, 100)
            w.wait_for_function("() => document.body.dataset.expanded === 'true'")
            settle(w, 700)
            w.click("#chat-btn")
            settle(w, 700)
            save(w, "barra-conversa")
        w.unroute_all(behavior="ignoreErrors")  # sem pedido pendente ao fechar (evita ruído do Playwright)
        ctx.close()

    # nota flutuante
    ctx = browser.new_context(viewport={"width": 520, "height": 480}, device_scale_factor=1, reduced_motion="reduce")
    n = ctx.new_page()
    n.on("pageerror", lambda e: errors.append(f"note: {e}"))
    n.goto(H.url + "/note")
    settle(n, 700)
    save(n, "nota")
    ctx.close()

    # mostruário interno /design (todos os componentes de ui.css)
    ctx = browser.new_context(viewport={"width": 1120, "height": 900}, device_scale_factor=1, reduced_motion="reduce")
    d = ctx.new_page()
    d.on("pageerror", lambda e: errors.append(f"design: {e}"))
    d.goto(H.url + "/design")
    settle(d, 700)
    save(d, "design", full=True)
    ctx.close()
    return SimpleNamespace(done=done, errors=errors)
