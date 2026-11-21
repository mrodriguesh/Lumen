"""Barra flutuante com o servidor REAL (arquivos estáticos e token, LUMEN_DATA temporário) e a API de gravação SIMULADA dentro da página:
um `fetch` de teste com uma máquina de estados parecida com a de lumen/record.py (iniciar, pausar, retomar, parar), com atrasos, falhas e
queda de conexão injetáveis. Assim a cápsula de gravação é provada sem tocar no áudio, em nenhuma gravação pessoal nem nos dados do usuário.

    with page(ART) as H:     H.w (Playwright Page)   H.sim("delay.start = 800")   H.calls() (comandos recebidos)   H.edge("left")

O `chrome.webview` também é simulado: H.messages() lista o que a página pediu ao Lumen.exe. A simulação mora na página (setTimeout), então
ela não bloqueia o navegador de teste."""
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

SIM = r"""
(() => {
  const real = window.fetch.bind(window);
  const JOB = {status: "idle", kind: null, stage: null, detail: null, progress: null, eta: null, eta_total: null, error: null, title: "", url: "", review: false};
  const sim = window.__sim = {
    s: {active: false, paused: false, seconds: 0, level: 0, heard: false, error: null, screens: null, recovered: null},
    session: 0, pauses: 0, calls: [], reads: 0, offline: false, widgetDelay: 0, delays: [], notes: [],
    delay: {start: 0, stop: 0, pause: 0, resume: 0}, fail: {}, failAlways: {},
    save() { sessionStorage.setItem('__sim', JSON.stringify({s: this.s, session: this.session, pauses: this.pauses, notes: this.notes})); },  // sobrevive à recarga da página
    view() { const s = {...this.s}; if (s.active) { s.elapsed = s.seconds; s.paused_for = s.paused ? 3 : 0; s.pause_count = this.pauses; } return s; },
  };
  try { const saved = JSON.parse(sessionStorage.getItem('__sim') || 'null'); if (saved) { Object.assign(sim.s, saved.s); sim.session = saved.session; sim.pauses = saved.pauses; sim.notes = saved.notes || []; } } catch (e) { /* sem estado salvo */ }
  const json = (code, body) => new Response(JSON.stringify(body), {status: code, headers: {"Content-Type": "application/json"}});
  const err = (message) => json(400, {error: {message, action: "Tente de novo."}});
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  window.fetch = async (input, opt = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href), path = url.pathname;
    if (!/^\/api\/(widget|record\/(start|stop|pause|resume))$/.test(path) || url.searchParams.get("view") === "settings") return real(input, opt);
    if (sim.offline) throw new TypeError("Failed to fetch");
    if (path === "/api/widget") {
      sim.reads++;
      const view = sim.view();   // o instante em que o servidor LEU o estado; a resposta pode chegar depois (resposta atrasada)
      const late = sim.delays.length ? sim.delays.shift() : sim.widgetDelay;   // `delays`: um atraso só para a PRÓXIMA leitura; `widgetDelay`: para todas
      if (late) await wait(late);
      return json(200, {job: JOB, recording: view, watch: false, music: false, notes: sim.notes, pomodoro: {phase: "idle", running: false, remaining: 0, total: 0, cycle: 0}});
    }
    const cmd = path.split("/").pop(), s = sim.s;
    sim.calls.push({cmd, at: performance.now()});
    await wait(sim.delay[cmd] || 0);
    const msg = sim.failAlways[cmd] || sim.fail[cmd];
    if (msg && !sim.failAlways[cmd]) delete sim.fail[cmd];
    if (msg) return err(msg);
    if (cmd === "start") {
      if (s.active) return err("Já existe uma gravação em andamento.");
      sim.session++; sim.pauses = 0;
      Object.assign(s, {active: true, paused: false, seconds: 1, level: .3, heard: true, error: null});
      sim.save();
      return json(200, sim.view());
    }
    if (!s.active) return err("Nenhuma gravação em andamento.");
    if (cmd === "pause") { if (!s.paused) sim.pauses++; Object.assign(s, {paused: true, level: 0}); sim.save(); return json(200, sim.view()); }
    if (cmd === "resume") { s.paused = false; sim.save(); return json(200, sim.view()); }
    Object.assign(s, {active: false, paused: false, seconds: 0, level: 0}); sim.save();
    return json(200, {path: "D:/teste/Aula.wav", name: "Aula.wav", warning: null});
  };
})();
"""


@contextmanager
def page(art, viewport=(304, 252), scale=2, headless=True, channel="chrome", sim=True, video=None):
    art = Path(art)
    art.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="capsule-") as temp:
        env = {**os.environ, "LUMEN_DATA": str(Path(temp) / "data"), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
        log = (art / "backend.log").open("w", encoding="utf-8")
        proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c",
                                 "from lumen import server; h=server.serve(); print(h.server_port,flush=True); h.serve_forever()"],
                                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            url = "http://127.0.0.1:" + proc.stdout.readline().strip()
            errors = []
            with sync_playwright() as p:
                browser = p.chromium.launch(channel=channel, headless=headless, args=["--disable-gpu"])
                extra = {"record_video_dir": str(video), "record_video_size": {"width": viewport[0] * 2, "height": viewport[1] * 2}} if video else {}
                ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, device_scale_factor=scale, **extra)
                ctx.add_init_script("window.messages=[]; window.hostListeners=[]; window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(t,fn)=>hostListeners.push(fn)};")
                if sim:
                    ctx.add_init_script(SIM)
                w = ctx.new_page()
                w.on("pageerror", lambda e: errors.append(str(e)))
                w.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Content Security Policy" in m.text else None)
                w.goto(url + "/widget")
                w.wait_for_function("() => state !== null")
                H = SimpleNamespace(w=w, ctx=ctx, errors=errors, url=url, art=art, browser=browser)
                H.sim = lambda js: w.evaluate("(() => { const sim = window.__sim, s = sim.s; " + js + "; sim.save(); })()")
                H.calls = lambda: w.evaluate("window.__sim.calls.map(c => c.cmd)")
                H.messages = lambda: w.evaluate("messages.slice()")
                H.edge = lambda name: w.evaluate("e => { hostListeners.forEach(fn => fn({data: 'edge:' + e})); hostListeners.forEach(fn => fn({data: 'side:' + (e === 'right' ? 'right' : 'left')})) }", name)
                yield H
                browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()
