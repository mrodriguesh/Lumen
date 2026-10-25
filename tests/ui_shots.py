r"""Screenshots e checagens de todas as telas do Lumen com a API simulada (Playwright + Chrome sem GPU, como o WebView2).

Na raiz do projeto (o Playwright está no Python do sistema, não no .venv):
  py -3.14 tests\ui_shots.py                 todas as telas, 1120×860
  py -3.14 tests\ui_shots.py home run        só os cenários cujo nome contém "home" ou "run"
  py -3.14 tests\ui_shots.py --sizes         também 520×560, 900×700, 1600×1000 e 1920×1040
  py -3.14 tests\ui_shots.py --zoom          também 80, 90, 110 e 120% (1120×860)
  py -3.14 tests\ui_shots.py --perf          mede carga, troca de tela e quadros ao rolar
Imagens em tests\desktop-artifacts\ui\. Falha (código 1) com erro de página, rolagem horizontal, controle fora da janela
ou alvo de clique menor que 24 px. Dados isolados: LUMEN_DATA temporário e nenhuma chamada real ao Notion/Ollama/cofre.
"""
import copy
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "desktop-artifacts" / "ui"
NOW = time.time()


def iso(days=0, hours=0):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - days * 86400 - hours * 3600))


def png(w=320, h=180, rgb=(38, 48, 86)):
    """Uma "tela da aula" de mentira: gradiente com faixas, para as galerias terem o que mostrar."""
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            k = 1 - y / h * .5
            band = 30 if 30 < y < 44 and 24 < x < 220 else 18 if (60 < y < 66 or 80 < y < 86 or 100 < y < 106) and 24 < x < 280 else 0
            row += bytes(min(255, int(c * k) + band * 3) for c in rgb)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


SHOT = png()
NOTE = ("A convolução passa um filtro pequeno pela imagem e soma os produtos, então cada neurônio só olha uma região "
        "local. Isso reduz muito os parâmetros em relação a uma rede densa. O pooling diminui a resolução e deixa a rede "
        "mais tolerante a pequenos deslocamentos. Camadas mais profundas combinam bordas em formas e depois em objetos.")


def world():
    """O estado do Lumen que a interface vê. Cada cenário parte de uma cópia e muda só o que precisa."""
    cfg = dict(root_page_id="root-1", root_page_title="Estudos", quality="equilibrado", ollama_model="qwen3:8b",
               page_language="pt", keep_temp=False, watch_screen=True, music_filter=False, music_mode="balanceado",
               widget="left", autostart=True, destinations="both", study_level="balanceado",
               obsidian_vault=r"C:\Users\Estudante\Cérebro", obsidian_folder="C04 Claude Obsidian/16 Lumen",
               obsidian_canvas_folder="", obsidian_canvas=True, obsidian_connections=True, obsidian_review=True,
               obsidian_attachments=True, obsidian_open=False, review_intervals=[1, 3, 7, 14, 30, 60])
    ready = lambda phase, label, tone="wait", detail="": {"phase": phase, "label": label, "detail": detail, "tone": tone, "blocked": tone != "ok"}
    pending = [
        {"key": "k1", "title": "Redes neurais convolucionais", "label": "Gravação", "state": "understanding_written",
         "updated": iso(hours=2), "at": 1, "rev": 3, "ready": ready("ready", "Pronto para analisar", "ok")},
        {"key": "k2", "title": "Complexidade de algoritmos e notação O", "label": "Arquivo local", "state": "completed",
         "updated": iso(days=1), "at": 1, "rev": 5, "ready": ready("completed", "Análise concluída", "ok")},
        {"key": "k3", "title": "Kant: Crítica da razão pura, introdução", "label": "Gravação", "state": "waiting_for_understanding",
         "updated": iso(days=3), "at": 0, "rev": 0, "ready": ready("writing", "Escreva sua compreensão para continuar")},
    ]
    doc = lambda key, title, state, text, analysis=None: {
        "key": key, "title": title, "label": "Gravação", "state": state, "text": text, "at": 1, "original": text if analysis else None,
        "submitted": iso(hours=1) if analysis else None, "analysis": analysis, "analyzed_text": text if analysis else None,
        "model": "qwen3:8b" if analysis else None, "final_knowledge": None, "problem": "", "spec": {"kind": "recording", "path": "C:/aula.wav"},
        "updated": iso(hours=1), "rev": 3, "analyzed_rev": 3 if analysis else None,
        "ready": ready("completed", "Análise concluída", "ok") if analysis else ready("ready", "Pronto para analisar", "ok")}
    analysis = {
        "acertos": ["A convolução aplica um filtro local e compartilha os pesos pela imagem inteira.",
                    "O pooling reduz a resolução e dá tolerância a pequenos deslocamentos."],
        "parciais": ["As camadas profundas combinam padrões, mas a aula mostra que isso depende do campo receptivo, que cresce a cada camada."],
        "lacunas": ["O papel do passo (stride) e do preenchimento (padding) no tamanho da saída.", "Por que a ReLU entra depois de cada convolução."],
        "confusoes": [{"trecho": "cada neurônio só olha uma região local", "correcao": "Vale para a camada; o campo receptivo efetivo cresce com a profundidade."}],
        "complementos": ["Normalização em lote (batch norm) estabiliza o treino de redes profundas."],
        "conexoes": ["Filtros de borda (Sobel) da visão computacional clássica."],
        "perguntas": ["Como o tamanho do filtro muda o número de parâmetros?", "O que acontece com a saída se o stride dobrar?"],
    }
    history = [
        {"key": "h1", "lumen_id": "L1", "title": "Transformers e atenção", "course": "Estudos › Inteligência Artificial",
         "created": iso(days=2), "url": "https://www.notion.so/h1",
         "obsidian": {"status": "ok", "note": "16 Lumen/2026-10-22 - Transformers e atenção.md", "canvas": "16 Lumen/Mapa - Transformers.canvas",
                      "connections": 4, "questions": 12, "state": "created", "at": iso(days=2)}},
        {"key": "h2", "lumen_id": "L2", "title": "Gradiente descendente na prática", "course": "Estudos › Inteligência Artificial",
         "created": iso(days=6), "url": "https://www.notion.so/h2", "obsidian": {"status": "ok", "note": "n.md", "canvas": None, "connections": 2, "questions": 9, "state": "created", "at": iso(days=6)}},
        {"key": "h3", "lumen_id": "L3", "title": "Revolução Francesa: causas econômicas", "course": "Estudos › História",
         "created": iso(days=9), "url": "https://www.notion.so/h3"},
        {"key": "h4", "lumen_id": "L4", "title": "Estruturas de dados: árvores B", "spec": {"course_title": "Banco de dados"},
         "obsidian": {"status": "ok", "note": "b.md", "canvas": "c.canvas", "connections": 6, "questions": 14, "state": "created", "at": iso(days=12)}},
        {"key": "h5", "lumen_id": "L5", "title": "Cálculo II: integrais por partes", "course": "Estudos › Matemática",
         "created": iso(days=20), "url": "https://www.notion.so/h5"},
        {"key": "h6", "lumen_id": "L6", "title": "Introdução à economia comportamental", "course": "Estudos › Economia",
         "created": iso(days=31), "url": "https://www.notion.so/h6"},
    ]
    pages = [
        {"id": "root-1", "title": "Estudos", "path": "Estudos", "top": True, "parent": None, "icon": "📚"},
        {"id": "p-ia", "title": "Inteligência Artificial", "path": "Estudos › Inteligência Artificial", "top": False, "parent": "root-1", "icon": "🤖"},
        {"id": "p-hist", "title": "História", "path": "Estudos › História", "top": False, "parent": "root-1", "icon": "🏛️"},
        {"id": "p-mat", "title": "Matemática", "path": "Estudos › Matemática", "top": False, "parent": "root-1", "icon": None},
        {"id": "p-dl", "title": "Deep Learning", "path": "Estudos › Inteligência Artificial › Deep Learning", "top": False, "parent": "p-ia", "icon": None},
    ]
    review = {"review": True, "key": "k2", "title": "Complexidade de algoritmos e notação O", "engine": "large-v3-turbo na GPU (CUDA, float16)",
              "speed": {"requested": "auto", "used": 1, "words_per_s": 2.6}, "duration": 1840, "language": "pt", "can_retranscribe": True,
              "music": None, "segments": [
                  {"start": 0, "text": "Hoje a gente vai falar de complexidade de algoritmos, começando pela notação O grande.", "flags": []},
                  {"start": 14.2, "text": "Quando o algoritmo percorre a lista uma vez, dizemos que ele é linear, O de n.", "flags": []},
                  {"start": 31.8, "text": "O merge sort divide a lista ao meio e junta, então ele fica em n log n.", "flags": ["modelos discordam"], "alt": "O merge sort divide a lista ao meio e junta, então fica n log n."},
                  {"start": 52.5, "text": "No teste, o bubble sort levou 5.200 milissegundos com dez mil itens.", "flags": ["número"]},
                  {"start": 71.0, "text": "Isso explica por que o Knuth recomenda medir antes de otimizar.", "flags": ["nome próprio", "trecho incerto"]},
              ], "screens": {"seen": 9, "items": [{"id": f"s{i}", "t": 60 * i + 12, "titulo": t, "manual": False}
                                                 for i, t in enumerate(["Notação O grande", "Comparação de algoritmos de ordenação", "Gráfico n log n", "Código do merge sort"])]}}
    return {
        "config": cfg, "has_token": True, "gpu": True,
        "whisper": {"active": "equilibrado", "models": {
            "rapido": {"label": "Rápido", "name": "small", "size": "0,48 GB", "downloaded": True},
            "equilibrado": {"label": "Equilibrado", "name": "large-v3-turbo", "size": "1,6 GB", "downloaded": True},
            "maximo": {"label": "Maior precisão", "name": "large-v3", "size": "3,1 GB", "downloaded": False}}},
        "ollama": {"running": True, "installed": True, "models": ["qwen3:8b", "qwen3.5:4b"]},
        "sources": {k: {"id": "compativel", "label": "Compatível"} for k in ("recording", "file", "youtube", "telegram", "captures")},
        "formats": {".mp4": "MP4", ".mkv": "MKV", ".webm": "WebM", ".mov": "MOV", ".mp3": "MP3", ".m4a": "M4A", ".wav": "WAV"},
        "images": [".png", ".jpg", ".jpeg", ".webp", ".bmp"],
        "covers": {"ready": False, "label": "Z-Image-Turbo", "size": "6,7 GB"},
        "vision": {"model": "qwen3.5:4b", "size": "3,3 GB", "installed": True},
        "music": {"ready": False, "size": "72 MB"},
        "obsidian": {"vaults": [{"path": cfg["obsidian_vault"], "name": "Cérebro", "open": True, "ok": True, "folder": cfg["obsidian_folder"]}],
                     "folder": cfg["obsidian_folder"], "error": None},
        "recording": {"active": False, "seconds": 0, "level": 0, "heard": False, "paused": False},
        "job": {"status": "idle"},
        "pending": pending, "history": history, "pages": pages, "review": review,
        "reviews": [{"key": "h1", "title": "Transformers e atenção", "next_review": iso(days=0)[:10], "stage": 2, "overdue": False},
                    {"key": "h4", "title": "Estruturas de dados: árvores B", "next_review": iso(days=2)[:10], "stage": 1, "overdue": True}],
        "docs": {"k1": doc("k1", "Redes neurais convolucionais", "understanding_written", NOTE),
                 "k2": doc("k2", "Complexidade de algoritmos e notação O", "completed", NOTE, analysis),
                 "k3": doc("k3", "Kant: Crítica da razão pura, introdução", "waiting_for_understanding", "")},
        "found": {"title": "Redes neurais convolucionais", "label": "Gravação", "duration": 2712, "needs_transcription": True,
                  "whisper_ready": True, "estimate": 140, "info": {"format": "WAV · 48 kHz"}},
        "pomodoro": {"phase": "focus", "running": True, "left": 1122, "total": 1500, "done": 1, "event": None,
                     "settings": {"focus": 25, "short": 5, "long": 15, "cycles": 4, "auto": False, "sound": True}},
    }


def state_of(w):
    keys = ("config", "has_token", "gpu", "whisper", "ollama", "sources", "formats", "images", "covers", "vision", "music",
            "obsidian", "recording", "job", "pending")
    return {k: w[k] for k in keys}


def router(W, log):
    def route(r):
        u = urlsplit(r.request.url)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        body = r.request.post_data_json if r.request.method == "POST" and r.request.post_data else {}
        log.append((r.request.method, path, body))
        code, data = 200, {}
        if path in ("/api/screen", "/api/capture"):
            return r.fulfill(status=200, content_type="image/png", body=SHOT)
        if path == "/api/state": data = state_of(W)
        elif path == "/api/job": data = W["job"]
        elif path == "/api/record": data = W["recording"]
        elif path == "/api/widget":
            if q.get("view") == "settings": data = {"config": W["config"], "has_token": W["has_token"]}
            else:
                j = W["job"]
                data = {"job": {**{k: j.get(k) for k in ("status", "kind", "stage", "detail", "progress", "eta", "eta_total", "error")},
                                "title": j.get("title", ""), "url": "", "review": False},
                        "recording": W["recording"], "watch": W["config"]["watch_screen"], "music": W["config"]["music_filter"],
                        "notes": W["pending"], "pomodoro": {**W["pomodoro"], "now": time.time(), "ends_at": time.time() + W["pomodoro"]["left"]}}
        elif path == "/api/pomodoro":
            if body.get("action") in ("play", "pause"):
                W["pomodoro"]["running"] = body["action"] == "play"
            data = {**W["pomodoro"], "now": time.time(), "ends_at": time.time() + W["pomodoro"]["left"]}
        elif path == "/api/history": data = {"items": W["history"]}
        elif path == "/api/reviews": data = {"items": W["reviews"]}
        elif path == "/api/courses": data = {"courses": W["pages"], "root_ok": True, "root": W["config"]["root_page_id"]}
        elif path == "/api/notion/pages": data = {"pages": W["pages"]}
        elif path == "/api/inspect": data = W["found"]
        elif path == "/api/understanding": data = W["docs"].get(q.get("key"), W["docs"]["k1"])
        elif path == "/api/understanding/draft":
            d = W["docs"].get(body.get("key"))
            if d: d.update(text=body.get("text", ""), at=body.get("at", 0))
            data = d or {}
        elif path == "/api/review": data = {**W["review"], "key": q.get("key", W["review"]["key"])}
        # o fluxo de uma aula, com estado (para o percurso de ponta a ponta)
        elif path == "/api/record/start":
            W["recording"] = {"active": True, "seconds": 0, "level": .3, "heard": True, "paused": False, "screens": {"seen": 0}}
            data = W["recording"]
        elif path in ("/api/record/pause", "/api/record/resume"):
            W["recording"].update(paused=path.endswith("pause"), paused_for=0)
            data = W["recording"]
        elif path == "/api/record/stop":
            W["recording"] = {"active": False, "seconds": 0, "level": 0, "heard": False, "paused": False}
            data = {"path": "C:/Lumen/aula.wav", "name": "Aula de 24-10.wav", "warning": None}
        elif path == "/api/start":  # a preparação termina na hora: a aula k1 espera a compreensão
            W["job"] = {"status": "done", "kind": "process", "key": "k1", "result": {"review": True, "key": "k1", "title": W["docs"]["k1"]["title"]}}
            data = W["job"]
        elif path == "/api/understanding/submit":  # a IA analisa na hora
            k = body["key"]
            W["docs"][k].update(state="completed", analysis=W["docs"]["k2"]["analysis"], analyzed_text=body["text"], original=body["text"],
                                submitted=iso(), model="qwen3:8b", ready={"phase": "completed", "label": "Análise concluída", "tone": "ok", "detail": ""})
            W["job"] = {"status": "done", "kind": "analyze", "spec": {"key": k}, "result": {"analysis": True, "key": k}}
            data = {}
        elif path == "/api/finish":
            W["job"] = {**copy.deepcopy(globals()["DONE"]), "result": {**DONE["result"], "key": body.get("key") or "k1"}}
            data = W["job"]
        elif path == "/api/settings":
            W["config"].update({k: v for k, v in body.items() if k in W["config"]})
            data = {"config": W["config"], "has_token": W["has_token"]} if q.get("view") == "settings" else state_of(W)
        r.fulfill(status=code, content_type="application/json", body=json.dumps(data))
    return route


HOST = ("window.messages=[];window.hostListeners=[];window.chrome=window.chrome||{};"
        "window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(t,f)=>hostListeners.push(f)};")

# Problemas que a tela não pode ter, conferidos em cada captura.
CHECKS = r"""(z) => {
  const out = [], vw = innerWidth, vh = innerHeight;
  const seen = (e) => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0.05 && s.clipPath === "none" && !e.closest("[hidden],[inert],.sr"); };
  const name = (e) => (e.id ? "#" + e.id : e.tagName.toLowerCase() + (e.className && typeof e.className === "string" ? "." + e.className.split(" ").filter(Boolean).join(".") : ""))
    + (e.textContent.trim() ? ` “${e.textContent.trim().slice(0, 24)}”` : "");
  for (const el of [document.scrollingElement, ...document.querySelectorAll(".content, .view, main")])
    if (el && el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== "hidden") out.push(`rolagem horizontal em ${name(el)} (${el.scrollWidth} > ${el.clientWidth})`);
  const scroller = (e) => { for (let p = e.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowY; if (o === "auto" || o === "scroll") return p; } return null; };
  for (const e of document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, [role=tab], [role=switch]")) {
    if (!seen(e) || e.matches("#peek")) continue;  // a alça recolhida (12×84) é a própria janela: o hover nela abre a barra
    const r = e.getBoundingClientRect(), box = scroller(e)?.getBoundingClientRect();
    const inline = e.matches(".link-btn, .crumb") || getComputedStyle(e).display === "inline";
    if (!inline && (r.width / z < 23.5 || r.height / z < 19.5) && !e.matches("input[type=checkbox], input[type=radio]")) out.push(`alvo pequeno ${Math.round(r.width / z)}×${Math.round(r.height / z)}: ${name(e)}`);
    const clipL = box ? Math.max(0, box.left) : 0, clipR = box ? Math.min(vw, box.right) : vw;
    if (r.right > clipR + 1 && r.left < clipR - 1) out.push(`cortado à direita: ${name(e)}`);
    if (r.left < clipL - 1 && r.right > clipL) out.push(`cortado à esquerda: ${name(e)}`);
  }
  for (const e of document.querySelectorAll("h1, h2, h3, .btn, .badge, .rail-item span, .stepper li")) {
    if (!seen(e)) continue;
    const s = getComputedStyle(e);
    if (e.scrollWidth > e.clientWidth + 1 && s.textOverflow !== "ellipsis" && s.overflow !== "visible") out.push(`texto cortado: ${name(e)}`);
  }
  return out;
}"""


class Harness:
    def __init__(self, browser, url, out, zoom=1.0):
        self.browser, self.url, self.out, self.zoom = browser, url, out, zoom
        self.problems, self.shots, self.errors = {}, [], []

    def open(self, kind, w, h, patch=None, query=""):
        W = world()
        if patch: patch(W)
        log = []
        ctx = self.browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, reduced_motion="no-preference")
        ctx.add_init_script(HOST)
        ctx.route("**/api/**", router(W, log))
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("requestfailed", lambda r: errs.append(f"falhou {r.url}"))
        path = {"main": "/?frame=1", "widget": "/widget", "note": "/note?key=k1", "design": "/design"}[kind] + query
        page.goto(self.url + path)
        page.wait_for_load_state("load")  # networkidle nunca chega com a gravação ativa (o Lumen consulta a cada 220 ms)
        ready = {"main": "() => typeof S !== 'undefined' && S !== null && typeof historyItems !== 'undefined'",
                 "widget": "() => typeof state !== 'undefined' && state !== null"}.get(kind)
        if ready:
            page.wait_for_function(ready, timeout=10000)
        if self.zoom != 1 and kind == "main":  # zoom da página (Ctrl + roda); a barra e a nota têm tamanho físico fixo (DPI no C#)
            page.evaluate(f"document.documentElement.style.zoom = {self.zoom}")
        page.wait_for_timeout(300)
        page.evaluate("document.fonts.ready")
        return ctx, page, W, log, errs

    def shot(self, name, kind, w, h, setup="", patch=None, query=""):
        ctx, page, W, log, errs = self.open(kind, w, h, patch, query)
        try:
            if setup:
                page.evaluate(f"async () => {{ {setup} }}")
            page.wait_for_timeout(450)
            tag = f"{name}-{w}x{h}" + (f"@{int(self.zoom * 100)}" if self.zoom != 1 else "")
            file = self.out / f"{tag}.png"
            page.screenshot(path=str(file), animations="disabled")
            found = page.evaluate(CHECKS, self.zoom if kind == "main" else 1) + [f"erro de página: {e}" for e in errs if "favicon" not in e]
            if found: self.problems[tag] = found
            self.shots.append(file)
            return page
        finally:
            ctx.close()


def serve():
    data = tempfile.mkdtemp(prefix="lumen-ui-shots-")
    env = {**os.environ, "LUMEN_DATA": data,
           "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
    proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c",
                             "from lumen import server; h=server.serve(); print(h.server_port, flush=True); h.serve_forever()"],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)
    proc.data = data  # apagada ao terminar (o C: costuma estar cheio)
    return proc, "http://127.0.0.1:" + proc.stdout.readline().strip()


def run(scenarios, filters=(), sizes=((1120, 860),), zooms=(1.0,), out=OUT):
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    proc, url = serve()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            total = {}
            for zoom in zooms:
                h = Harness(browser, url, out, zoom)
                for name, kind, setup, patch, own in scenarios:
                    if filters and not any(f in name for f in filters) or zoom != 1 and kind != "main":
                        continue
                    for w, hh in ([own] if own else sizes):
                        try:
                            h.shot(name, kind, w, hh, setup, patch)
                        except Exception as e:  # um cenário quebrado não esconde os outros
                            h.problems[f"{name}-{w}x{hh}"] = [f"falhou: {str(e).splitlines()[0]}"]
                total.update(h.problems)
                print(f"zoom {int(zoom * 100)}%: {len(h.shots)} capturas")
            browser.close()
    finally:
        proc.kill()
        proc.wait(timeout=10)
        shutil.rmtree(proc.data, ignore_errors=True)
    for tag, found in total.items():
        print(f"\n{tag}:")
        for f in dict.fromkeys(found):
            print("  -", f)
    print(f"\n{len(total)} capturas com problema" if total else "\nnenhum problema encontrado")
    return 1 if total else 0


# ---------------------------------------------------------------------------------------------------------------
# Cenários: (nome, página, JS de preparo, mudança no estado simulado, tamanho fixo ou None = todos os tamanhos)
REC = {"active": True, "seconds": 754, "level": .28, "heard": True, "paused": False, "screens": {"seen": 6, "read": 4, "kept": 3}}
JOB = {"status": "running", "kind": "process", "stage": "generate", "detail": "Escrevendo o material a partir da sua compreensão",
       "progress": .42, "eta_total": 95, "dests": ["obsidian", "notion"], "skipped": ["transcribe"], "title": "Redes neurais convolucionais", "key": "k1"}
DONE = {"status": "done", "kind": "process", "dests": ["obsidian", "notion"], "result": {
    "key": "k2", "title": "Complexidade de algoritmos e notação O", "course": "Estudos › Inteligência Artificial",
    "notion": {"status": "ok", "url": "https://notion.so/x", "understanding_url": "https://notion.so/y"},
    "obsidian": {"status": "ok", "note": "n.md", "canvas": "c.canvas", "connections": 4, "questions": 12, "state": "created"}}}


def run_js(job, url="/api/finish"):
    return f'showView("new"); lastUrl="{url}"; lastSpec={{kind:"recording"}}; showStep("run"); renderJob({json.dumps(job)}); renderStatus();'


def patch(**kv):
    return lambda W: W.update(copy.deepcopy(kv))


def no_data(W):
    W.update(pending=[], history=[], reviews=[])


def first_use(W):
    no_data(W)
    W.update(has_token=False)
    W["config"].update(root_page_id="", root_page_title="", obsidian_vault="")
    W["ollama"]["installed"] = False
    W["obsidian"].update(folder="")


def notion_fail(W):
    W["job"] = copy.deepcopy(DONE)
    W["job"]["result"]["notion"] = {"status": "error", "error": "O Notion recusou o pedido (limite de envio).", "action": "Tente de novo em 1 minuto."}


UNDER = 'showView("new"); await openUnderstanding("k1");'
WOPEN = 'document.body.dataset.expanded="true";'
SCENARIOS = [
    ("home", "main", "", None, None),
    ("home-first", "main", "", first_use, None),
    ("home-rec", "main", "", patch(recording=REC), None),
    ("home-job", "main", 'lastUrl="/api/finish"; showView("home"); poll();', patch(job=JOB), None),
    ("new-compose", "main", 'showView("new");', None, None),
    ("new-ready", "main", 'showView("new"); picked.recording={path:"C:/aula.wav",name:"Aula.wav"}; setRecState("done","Gravar de novo"); await inspect();', None, None),
    ("new-recording", "main", 'showView("new");', patch(recording=REC), None),
    ("new-paused", "main", 'showView("new");', patch(recording={**REC, "paused": True, "paused_for": 42}), None),
    ("new-recover", "main", 'showView("new");', patch(recording={"active": False, "seconds": 0, "recovered": {"seconds": 1234}}), None),
    ("new-file", "main", 'showView("new"); $("#tab-file").click();', None, None),
    ("new-captures", "main", 'showView("new"); $("#tab-captures").click(); await addCaps([{path:"C:/a.png",name:"slide 1.png"},{path:"C:/b.png",name:"código.png"},{path:"C:/c.png",name:"tabela.png"}]);', None, None),
    ("new-picker", "main", 'showView("new"); setPicker(true);', None, None),
    ("new-search", "main", 'showView("new"); const s=$("#course-filter"); s.focus(); s.value="ia"; s.dispatchEvent(new Event("input"));', None, None),
    ("understand", "main", UNDER, None, None),
    ("understand-rec", "main", UNDER, patch(recording=REC), None),
    ("understand-prep", "main", UNDER + ' U.state="studying"; renderUStatus({status:"running",kind:"process",key:"k1",stage:"transcribe",detail:"Transcrevendo (3 de 9 min)",progress:.33});', None, None),
    ("understand-ai", "main", UNDER + ' U.state="processing_with_ai"; renderUnderstanding(); renderUStatus({status:"running",kind:"analyze",key:"k1",spec:{key:"k1"},detail:"Lendo a aula por partes (1 de 3)",eta_total:42});', None, None),
    ("analysis", "main", 'showView("new"); await openUnderstanding("k2");', None, None),
    ("analysis-review", "main", 'showView("new"); await openUnderstanding("k2"); $("#review-more").open=true;', None, None),
    ("run-prep", "main", run_js({**JOB, "stage": "transcribe", "detail": "Transcrevendo no PC (12 de 45 min)", "progress": .27, "skipped": []}, "/api/start"), None, None),
    ("run", "main", run_js(JOB), None, None),
    ("run-indeterminate", "main", run_js({**JOB, "stage": "publish", "detail": "Enviando ao Notion", "progress": None}), None, None),
    ("run-done", "main", run_js(DONE), None, None),
    ("run-partial", "main", 'showView("new"); lastUrl="/api/finish"; lastSpec={kind:"recording"}; showStep("run"); renderJob(await api("/api/job"));', notion_fail, None),
    ("run-error", "main", run_js({"status": "error", "kind": "process", "stage": "generate", "error": {"message": "A IA local não respondeu.", "action": "Abra o Ollama e tente de novo."}}), None, None),
    ("run-cancel", "main", run_js({"status": "cancelled", "kind": "process", "stage": "generate"}), None, None),
    ("library", "main", 'showView("library");', None, None),
    ("library-empty", "main", 'showView("library");', no_data, None),
    ("library-loading", "main", 'loadHistory = () => new Promise(() => {}); historyItems = null; showView("library");', None, None),  # lista ainda chegando
    ("library-none", "main", 'showView("library"); const s=$("#lib-search"); s.value="quântica"; s.dispatchEvent(new Event("input"));', None, None),
    ("integrations", "main", 'showView("integrations");', None, None),
    ("integrations-off", "main", 'showView("integrations");', first_use, None),
    *[(f"settings-{c}", "main", f'goSettings("{c}");', None, None) for c in ("general", "capture", "transcription", "ai", "covers", "privacy")],
    ("palette", "main", 'openPalette();', None, None),
    ("palette-typed", "main", 'openPalette(); palIn.value="kant"; palIn.dispatchEvent(new Event("input"));', None, None),
    ("confirm", "main", 'showView("settings"); ui.confirm("Apaga o histórico de aulas e as notas de compreensão deste PC.",{title:"Limpar os dados locais?",ok:"Apagar dados locais",danger:true});', None, None),
    ("toast-error", "main", 'toast("O Lumen parou de responder. Abra o aplicativo de novo.", true);', None, None),
    ("toast-ok", "main", 'toast("Notion conectado.");', None, None),
    ("design", "design", "", None, (1120, 860)),
    # barra flutuante (no tamanho real da janela) e janela flutuante da nota
    ("widget-idle", "widget", WOPEN, None, (304, 252)),
    ("widget-live", "widget", WOPEN, patch(recording=REC), (304, 252)),
    ("widget-paused", "widget", WOPEN, patch(recording={**REC, "paused": True, "paused_for": 42}), (304, 252)),
    ("widget-error", "widget", WOPEN, patch(recording={"active": False, "seconds": 0, "error": "A saída de áudio foi desconectada. Confira o fone ou alto-falante e tente de novo."}), (304, 252)),
    ("widget-job", "widget", WOPEN, patch(job=JOB), (304, 252)),
    ("widget-note", "widget", WOPEN + ' Notes.setActive("k1"); await new Promise(r=>setTimeout(r,1300)); showNote(true);', None, (360, 440)),
    ("widget-prefs", "widget", WOPEN + ' await openPreferences();', None, (304, 252)),
    ("widget-prefs-desktop", "widget", WOPEN + ' await openPreferences(); await openCategory("desktop");', None, (304, 252)),
    ("widget-prefs-transcription", "widget", WOPEN + ' await openPreferences(); await openCategory("transcription");', None, (304, 252)),
    ("widget-top", "widget", WOPEN + ' hostListeners.forEach(f=>f({data:"edge:top"}));', patch(recording=REC), (304, 252)),
    ("widget-peek", "widget", 'document.body.dataset.expanded="false";', patch(recording=REC), (12, 84)),
    ("note", "note", "", None, (420, 520)),
    ("note-rec", "note", "", patch(recording=REC), (420, 520)),
    ("note-compact", "note", 'compact(true);', patch(recording={**REC, "paused": True, "paused_for": 30}), (420, 46)),
    ("note-min", "note", "", patch(recording=REC), (300, 240)),  # o menor tamanho da janela (NoteForm.Least)
]


def walk(out=OUT / "percurso"):
    """O uso de ponta a ponta, clicando nos botões de verdade: Início → Nova aula → gravar → pausar → retomar → Pomodoro
    → parar → Minha compreensão (com a barra e a janela da nota juntas) → processar → análise → salvar → resultado →
    Biblioteca → Integrações → Ajustes (um ajuste seguro) → Início. Uma imagem por etapa; falha no primeiro passo errado."""
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    proc, url = serve()
    W, log, fails = world(), [], []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            ctx = b.new_context(viewport={"width": 1120, "height": 860})
            ctx.add_init_script(HOST)
            ctx.route("**/api/**", router(W, log))
            m = ctx.new_page()
            errs = []
            m.on("pageerror", lambda e: errs.append(str(e)))
            n = [0]

            def shot(page, name):
                n[0] += 1
                page.wait_for_timeout(350)
                page.screenshot(path=str(out / f"{n[0]:02d}-{name}.png"), animations="disabled")

            def step(name, ok, page=m):
                print(("ok   " if ok else "FALHA ") + name)
                if not ok:
                    fails.append(name)
                shot(page, name)

            def until(js, page=m, ms=6000):
                try:
                    page.wait_for_function(js, timeout=ms)
                    return True
                except Exception:  # noqa: BLE001
                    return False

            m.goto(url + "/?frame=1")
            step("inicio", until("() => typeof S !== 'undefined' && S && !document.querySelector('#view-home').hidden"))
            m.click("#nav-new")
            step("nova-aula", until("() => !document.querySelector('#view-new').hidden && step === 'compose'"))
            m.click("#rec-start")
            step("gravando", until("() => recorder.dataset.state === 'live' && document.querySelector('#global-status').dataset.tone === 'rec'"))
            w = ctx.new_page()
            w.set_viewport_size({"width": 304, "height": 252})
            w.goto(url + "/widget")
            until("() => typeof state !== 'undefined' && state && state.recording.active", w)
            w.evaluate('document.body.dataset.expanded = "true"')
            step("barra-gravando", until("() => document.body.dataset.state === 'live' && !document.querySelector('#pause').hidden", w), w)
            m.click("#rec-pause")
            step("pausado", until("() => recorder.dataset.paused === 'true' && document.querySelector('#global-status').dataset.tone === 'paused'"
                                  " && document.querySelector('#rec-pause-label').textContent === 'Retomar'"))
            step("barra-pausada", until("() => document.body.dataset.paused === 'true' && document.querySelector('#pause-label').textContent.startsWith('Retomar')", w), w)
            m.click("#rec-pause")
            step("retomado", until("() => recorder.dataset.paused === 'false' && document.querySelector('#rec-pause-label').textContent === 'Pausar'"))
            m.click("#u-pomo .pomo-time")
            m.wait_for_timeout(200)
            m.click("#u-pomo [data-act=toggle]")
            step("pomodoro", until("() => !document.querySelector('#u-pomo .pomo-sheet').hidden && document.querySelector('#u-pomo .pomo').dataset.running === 'false'"))
            m.keyboard.press("Escape")
            m.click("#rec-start")
            step("gravacao-pronta", until("() => recorder.dataset.state === 'done' && found && !document.querySelector('#go').disabled"
                                          " && document.querySelector('#global-status').dataset.tone !== 'rec'"))
            m.click("#go")
            step("minha-compreensao", until("() => step === 'understand' && U && U.key === 'k1' && document.querySelector('#u-text').value.length > 50"))
            nw = ctx.new_page()
            nw.set_viewport_size({"width": 420, "height": 520})
            nw.goto(url + "/note?key=k1")
            m.click("#u-text")
            m.keyboard.press("End")
            m.keyboard.type(" O padding mantém o tamanho da saída.")
            step("nota-flutuante-sincronizada", until("() => document.querySelector('#nw-text').value.endsWith('tamanho da saída.')", nw), nw)
            step("compreensao-salva", until("() => document.querySelector('#u-save').textContent === 'Salvo' && !document.querySelector('#u-go').disabled"))
            m.click("#u-go")
            step("analise", until("() => step === 'analysis' && !document.querySelector('#review').hidden && document.querySelectorAll('#ai .ai-sec').length > 3"))
            m.click("#review-go")
            step("resultado", until("() => document.querySelector('#result').classList.contains('ok')"
                                    " && [...document.querySelectorAll('#run-actions .btn')].some(b => b.textContent.includes('Abrir no Notion'))"
                                    " && [...document.querySelectorAll('#run-actions .btn')].some(b => b.textContent.includes('Abrir no Obsidian'))"))
            m.click("#nav-library")
            step("biblioteca", until("() => !document.querySelector('#view-library').hidden && document.querySelectorAll('#library-list .lib-title').length > 3"))
            m.click("#nav-integrations")
            step("integracoes", until("() => document.querySelector('#notion-badge').dataset.tone === 'ok' && document.querySelector('#obsidian-badge').dataset.tone === 'ok'"))
            m.click("#open-settings")
            m.click("#settings-nav [data-cat=privacy]")
            m.click("label:has(#keep)")
            step("ajuste-salvo", until("() => S.config.keep_temp === true") and W["config"]["keep_temp"] is True)
            m.click("#nav-home")
            step("inicio-de-novo", until("() => !document.querySelector('#view-home').hidden && document.querySelector('#nav-home').getAttribute('aria-current') === 'page'"))
            if errs:
                fails.append(f"erros de página: {errs}")
            b.close()
    finally:
        proc.kill()
        proc.wait(timeout=10)
        shutil.rmtree(proc.data, ignore_errors=True)
    print(f"\n{n[0]} etapas em {out}" + (f"\nFALHAS: {fails}" if fails else "\npercurso completo sem falhas"))
    return 1 if fails else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--walk" in args:
        sys.exit(walk())
    sizes = ((1120, 860),) + (((520, 560), (900, 700), (1600, 1000), (1920, 1040)) if "--sizes" in args else ())
    zooms = (1.0,) + ((.8, .9, 1.1, 1.2) if "--zoom" in args else ())
    sys.exit(run(SCENARIOS, [a for a in args if not a.startswith("--")], sizes, zooms))
