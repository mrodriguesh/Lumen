"""HTML → PNG e HTML → PDF pelo Microsoft Edge sem janela, comandado pelo DevTools Protocol (CDP).

O `--screenshot` da linha de comando parou de gravar arquivos no Edge 155 (20/10/2026), e com ele a capa, o mapa
mental e os gráficos; o CDP continua funcionando. Cada chamada abre um Edge próprio, com perfil temporário (nada do
perfil do usuário é lido), conecta no alvo do navegador pelo endereço que ele mesmo grava em DevToolsActivePort e
fecha com Browser.close. Sem Edge ou em falha, devolve None e quem chamou segue sem a imagem."""
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("lumen.cdp")
SETTLE = ("document.fonts.ready.then(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))")


def edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        exe = Path(base or "") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if base and exe.is_file():
            return exe
    return shutil.which("msedge") or shutil.which("microsoft-edge")


class _Conn:
    """Uma conexão CDP: comandos com id; eventos guardados até alguém esperar por eles."""

    def __init__(self, ws):
        self.ws, self.n, self.events = ws, 0, []

    def _recv(self, until):
        self.ws.settimeout(max(0.05, until - time.monotonic()))
        return json.loads(self.ws.recv())

    def call(self, method, session=None, timeout=60, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params, **({"sessionId": session} if session else {})}))
        until = time.monotonic() + timeout
        while True:
            m = self._recv(until)
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error'].get('message')}")
                return m.get("result", {})
            if "method" in m:
                self.events.append(m)

    def wait(self, event, session, timeout=30):
        until = time.monotonic() + timeout
        while True:
            for m in self.events:
                if m["method"] == event and m.get("sessionId") == session:
                    self.events.remove(m)
                    return m.get("params", {})
            m = self._recv(until)
            if "method" in m:
                self.events.append(m)


def _kill(tmp):
    """Encerra o Edge deste perfil temporário (e só ele), quando a conexão CDP nunca aconteceu."""
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -like '*"
                    + tmp.name + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


@contextmanager
def _page(width, height, scale=1, *, visible=False, parent=None):
    """Um Edge sem janela e uma aba width×height (px CSS) com escala `scale`: produz (conexão, sessão, pasta temp).

    --do-not-de-elevate: aberto por um processo de administrador, o Edge sai na hora (código 0) e se reabre fora do
    modo administrador; em 01/11/2026 essa reabertura passou a travar antes de abrir o DevTools. Com o sinal, ele fica
    neste processo (sem efeito quando o Lúmen não é administrador). A espera é pelo DevToolsActivePort e o fim, pelo
    Browser.close."""
    import websocket  # websocket-client
    exe = edge()
    if not exe:
        raise FileNotFoundError("Microsoft Edge não encontrado")
    if parent:
        Path(parent).mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="lumen-cdp-", dir=parent))
    # GPU no Edge sem janela é opt-in (LUMEN_CDP_GPU=1): o modo software é determinístico e não depende do driver.
    gpu = os.environ.get("LUMEN_CDP_GPU") == "1"
    flags = [] if visible else ["--headless=new"]
    flags += (["--ignore-gpu-blocklist", "--enable-gpu-rasterization"] if gpu else ["--disable-gpu"])
    flags += ["--hide-scrollbars", "--no-first-run", "--no-default-browser-check", "--do-not-de-elevate",
              "--remote-debugging-port=0", f"--user-data-dir={tmp / 'perfil'}", "about:blank"]
    launcher = subprocess.Popen([str(exe), *flags],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    conn = None
    try:
        port_file, until = tmp / "perfil" / "DevToolsActivePort", time.monotonic() + 30
        while True:
            try:
                parts = port_file.read_text("utf-8").split()
            except OSError:  # o Edge ainda pode estar criando o arquivo com compartilhamento exclusivo
                parts = []
            if len(parts) >= 2:
                break
            if time.monotonic() > until:
                raise RuntimeError("o Edge não abriu o DevTools em 30 s")
            time.sleep(0.05)
        port, path = parts[:2]
        conn = _Conn(websocket.create_connection(f"ws://127.0.0.1:{port}{path}", timeout=30, suppress_origin=True))
        target = conn.call("Target.createTarget", url="about:blank")["targetId"]
        sid = conn.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        conn.call("Page.enable", sid)
        conn.call("Emulation.setDeviceMetricsOverride", sid, width=width, height=height, deviceScaleFactor=scale, mobile=False)
        yield conn, sid, tmp
    finally:
        if conn:
            try:
                conn.call("Browser.close", timeout=5)
            except Exception:  # noqa: BLE001 - ao fechar, o Edge derruba a conexão antes de responder
                pass
            conn.ws.close()
        else:
            _kill(tmp)
        try:
            launcher.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill(tmp)  # só os processos com o perfil desta chamada
            try:
                launcher.wait(timeout=5)
            except subprocess.TimeoutExpired:
                launcher.kill()
                launcher.wait()
        for _ in range(40):  # o Edge solta os arquivos do perfil alguns instantes depois de fechar
            shutil.rmtree(tmp, ignore_errors=True)
            if not tmp.exists():
                break
            time.sleep(0.25)


def _load(conn, sid, tmp, html, timeout):
    page = tmp / "pagina.html"
    page.write_text(html, "utf-8")
    conn.call("Page.navigate", sid, url=page.as_uri())
    conn.wait("Page.loadEventFired", sid, timeout)
    conn.call("Runtime.evaluate", sid, timeout, expression=SETTLE, awaitPromise=True)


def _guard(what, fn):
    import websocket
    try:
        return fn()
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError, websocket.WebSocketException) as e:
        log.warning("%s pelo Edge falhou: %s", what, e)
        return None


def png(html, width, height, scale=1, transparent=False, timeout=60):
    """PNG (bytes) da página em width×height px CSS (scale 2 = o dobro de pixels), ou None."""
    def run():
        with _page(width, height, scale) as (conn, sid, tmp):
            if transparent:
                conn.call("Emulation.setDefaultBackgroundColorOverride", sid, color={"r": 0, "g": 0, "b": 0, "a": 0})
            _load(conn, sid, tmp, html, timeout)
            shot = conn.call("Page.captureScreenshot", sid, timeout, format="png", captureBeyondViewport=True,
                             clip={"x": 0, "y": 0, "width": width, "height": height, "scale": 1})
            return base64.b64decode(shot["data"])
    return _guard("PNG", run)


def pdf(html, timeout=120, **options):
    """PDF (bytes) da página, com texto selecionável, links, marcação e marcadores (o CSS @page define o papel), ou None."""
    def run():
        with _page(794, 1123) as (conn, sid, tmp):  # A4 a 96 dpi: só o layout de tela antes de imprimir
            _load(conn, sid, tmp, html, timeout)
            out = conn.call("Page.printToPDF", sid, timeout, printBackground=True, preferCSSPageSize=True,
                            generateTaggedPDF=True, generateDocumentOutline=True, **options)
            return base64.b64decode(out["data"])
    return _guard("PDF", run)
