"""Servidor local (somente 127.0.0.1) que serve a interface e a API usada por ela."""
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import AppError, cover, eta, imagegen, jobs, llm, notion, record, sources, store, transcribe, vision

log = logging.getLogger("lumen")
WEB = Path(__file__).parent / "web"
STATIC = {"/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
          "/app.js": ("app.js", "text/javascript"), "/widget": ("widget.html", "text/html"),
          "/widget.css": ("widget.css", "text/css"), "/widget.js": ("widget.js", "text/javascript"),
          "/fonts/inter-latin.woff2": ("fonts/inter-latin.woff2", "font/woff2"),
          "/fonts/inter-latin-ext.woff2": ("fonts/inter-latin-ext.woff2", "font/woff2")}
TOKEN = secrets.token_urlsafe(24)
last_seen = time.monotonic()
bye_at = None

_PICK = """import sys, tkinter as t
from tkinter import filedialog as f
r = t.Tk(); r.withdraw(); r.attributes('-topmost', 1)
print(f.askopenfilename(title=sys.argv[1], filetypes=[(sys.argv[2], sys.argv[3]), ('Todos', '*.*')],
                        initialdir=sys.argv[4] or None) or '')"""


_PICK_MANY = """import sys, tkinter as t
from tkinter import filedialog as f
r = t.Tk(); r.withdraw(); r.attributes('-topmost', 1)
print("\\n".join(f.askopenfilenames(title=sys.argv[1], filetypes=[(sys.argv[2], sys.argv[3]), ('Todos', '*.*')])))"""


def pick_images():
    """Escolher várias capturas de tela no diálogo do Windows (os arquivos ficam onde estão; o Lumen só lê)."""
    r = subprocess.run([sys.executable, "-c", _PICK_MANY, "Escolher capturas de tela", "Imagens",
                        " ".join("*" + e for e in sources.IMAGES)],
                       capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    chosen = [Path(p) for p in r.stdout.splitlines() if p.strip() and Path(p).suffix.lower() in sources.IMAGES]
    up = store.WORK / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    paths = []
    for p in chosen[:sources.MAX_CAPTURES]:  # cópias na pasta do Lumen: as originais não são tocadas nem apagadas
        if p.is_file() and p.stat().st_size <= sources.MAX_IMAGE_BYTES:
            dest = up / f"{secrets.token_hex(4)}_{p.name}"
            shutil.copyfile(p, dest)
            paths.append(str(dest))
    return {"paths": paths, "names": [Path(p).name.split("_", 1)[1] for p in paths]}


def pick_file(kind):
    if kind == "images":
        return pick_images()
    if kind == "captions":
        title, label, exts, start = "Importar transcrição", "Legendas e texto", sources.CAPTIONS, ""
    else:
        title, label, exts = "Escolher vídeo ou áudio", "Vídeo e áudio", tuple(sources.MEDIA)
        tg = Path.home() / "Downloads" / "Telegram Desktop"
        start = str(tg) if kind == "telegram" and tg.is_dir() else ""
    r = subprocess.run([sys.executable, "-c", _PICK, title, label, " ".join("*" + e for e in exts), start],
                       capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    path = r.stdout.strip()
    if not path:
        return {}
    if kind != "captions":
        return {"path": path, "name": Path(path).name}
    p = Path(path)
    if p.stat().st_size > 5_000_000:
        raise AppError("O arquivo de transcrição é grande demais (máx. 5 MB).", "Escolha um .srt, .vtt ou .txt menor.")
    return {"name": p.name, "text": p.read_text("utf-8", errors="replace")}


def state():
    cfg = store.load_config()
    q, m = transcribe.pick(cfg["quality"])
    om = llm.models()
    return {
        "config": cfg, "has_token": bool(store.get_token()), "gpu": transcribe.has_gpu(),
        "whisper": {"active": q, "models": {k: {**v, "downloaded": transcribe.downloaded(v["name"])}
                                            for k, v in transcribe.models().items()}},
        "ollama": {"running": om is not None, "models": om or [],
                   "installed": om is not None and any(x == cfg["ollama_model"] or x == cfg["ollama_model"] + ":latest"
                                                       for x in om)},
        "sources": {k: {"id": v[0], "label": v[1]} for k, v in sources.STATUS.items()},
        "formats": sources.MEDIA, "images": sources.IMAGES, "job": jobs.snapshot(), "recording": record.status(),
        "covers": {"ready": imagegen.ready(), "label": imagegen.ENGINES[imagegen.DEFAULT_ENGINE]["label"],
                   "size": imagegen.ENGINES[imagegen.DEFAULT_ENGINE]["size"]},
        "vision": {"model": vision.MODEL, "size": vision.SIZE,
                   "installed": om is not None and any(x in (vision.MODEL, vision.MODEL + ":latest") for x in om)},
    }


def inspect(spec):
    src = sources.resolve(spec)
    cfg, token = store.load_config(), store.get_token()
    _, m = transcribe.pick(cfg["quality"])
    dup = store.history().get(src["key"])
    if dup and token and not notion.page_url(token, dup["page_id"]):
        dup = None  # página foi apagada no Notion
    resumable = (jobs.work_dir(src["key"]) / "transcript.json").exists()
    needs_tr = not src.get("captions") and bool(src.get("path")) and not resumable
    return {
        "title": src["title"], "label": src["label"], "link": src["link"], "author": src.get("author"),
        "info": src["info"], "duration": src["duration"], "duplicate": dup, "resumable": resumable,
        "has_captions": bool(src.get("captions")), "segments": len(src.get("captions") or []),
        "needs_transcript": not src.get("captions") and not src.get("path") and src["kind"] != "captures",
        "captures": len(src.get("paths") or []),
        "needs_transcription": needs_tr, "whisper_model": m["label"], "whisper_ready": transcribe.downloaded(m["name"]),
        "estimate": eta.transcribe_seconds(src["duration"], m["name"]) if needs_tr and src["duration"] else None,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # não registra URLs nem corpos
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self'; connect-src 'self'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # a janela foi fechada enquanto a resposta estava sendo enviada

    def _allowed(self):
        # Protege contra DNS rebinding e outras páginas abertas no navegador.
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            return False
        return not self.path.startswith("/api/") or secrets.compare_digest(
            self.headers.get("X-Lumen-Token", "") or self._query().get("t", ""), TOKEN)

    def _query(self):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20_000_000:
            raise AppError("Pedido grande demais.", "Use um arquivo de transcrição menor.")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        global last_seen, bye_at
        if not self._allowed():
            return self._send(403, {"error": {"message": "Acesso negado."}})
        last_seen = time.monotonic()
        path = urllib.parse.urlsplit(self.path).path
        try:
            if method == "GET" and path in STATIC:
                name, ctype = STATIC[path]
                body = (WEB / name).read_bytes()
                if name in ("index.html", "widget.html"):
                    body = body.replace(b"{{TOKEN}}", TOKEN.encode())
                return self._send(200, body, ctype)
            if (method, path) == ("POST", "/api/bye"):  # janela fechada (sendBeacon)
                bye_at = time.monotonic()
                return self._send(200, {})
            fn = ROUTES.get((method, path))
            if not fn:
                return self._send(404, {"error": {"message": "Não encontrado."}})
            out = fn(self)
            return self._send(200, out, "image/jpeg" if isinstance(out, bytes) else "application/json")
        except AppError as e:
            return self._send(400, {"error": {"message": str(e), "action": e.action}})
        except (ValueError, KeyError, TypeError):
            return self._send(400, {"error": {"message": "Pedido inválido.", "action": "Recarregue a janela."}})
        except Exception as e:
            log.error("erro na API %s: %s", path, type(e).__name__)
            return self._send(500, {"error": {"message": f"Erro inesperado ({type(e).__name__}).",
                                              "action": "Tente de novo."}})


def _settings(h):
    body = h._json()
    if body.get("notion_token"):
        tok = body["notion_token"].strip()
        notion.search_pages(tok)  # valida antes de guardar (fora da trava: depende da rede)
        store.set_token(tok)
    with store.LOCK:
        cfg = _apply_settings(body)
    if h._query().get("view") == "settings":
        return {"config": cfg, "has_token": bool(store.get_token())}
    return state()


def _apply_settings(body):
    cfg = store.load_config()
    if "root_page" in body:
        if body["root_page"]:
            cfg["root_page_id"] = notion.page_id(body["root_page"])
            cfg["root_page_title"] = str(body.get("root_page_title") or "")[:200]
        else:
            cfg["root_page_id"] = cfg["root_page_title"] = ""
    if body.get("quality") in transcribe.BY_HARDWARE:
        cfg["quality"] = body["quality"]
    if body.get("page_language") in ("pt", "original"):
        cfg["page_language"] = body["page_language"]
    if isinstance(body.get("ollama_model"), str) and body["ollama_model"].strip():
        cfg["ollama_model"] = body["ollama_model"].strip()[:100]
    if "keep_temp" in body:
        cfg["keep_temp"] = bool(body["keep_temp"])
    if "watch_screen" in body:
        cfg["watch_screen"] = body["watch_screen"] is True
    if body.get("widget") in ("off", "left", "right", "top", "bottom", "free"):
        cfg["widget"] = body["widget"]
    if "autostart" in body:
        if not isinstance(body["autostart"], bool):
            raise AppError("Opção de inicialização inválida.", "Escolha ligar ou desligar.")
        set_autostart(body["autostart"])
        cfg["autostart"] = body["autostart"]
    store.save_config(cfg)
    return cfg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(on):
    """Liga/desliga “Iniciar com o Windows” na chave Run deste usuário, sem pedir administrador."""
    if sys.platform != "win32":
        raise AppError("A inicialização automática está disponível no Windows.", "Abra pelo Lumen.exe no Windows.")
    import winreg
    exe = Path(__file__).resolve().parent.parent / "Lumen.exe"
    if on and not exe.is_file():
        raise AppError("Lumen.exe não encontrado.", "Compile ou restaure o aplicativo antes de ativar esta opção.")
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "Lumen", 0, winreg.REG_SZ, f'"{exe}" --background')
            else:
                try:
                    winreg.DeleteValue(k, "Lumen")
                except FileNotFoundError:
                    pass
    except OSError as e:
        raise AppError("O Windows não permitiu alterar a inicialização.", "Confira as permissões e tente de novo.") from e


def _widget(h):
    """Estado enxuto para a barrinha flutuante (consultada a cada segundo)."""
    if h._query().get("view") == "settings":
        return {"config": store.load_config(), "has_token": bool(store.get_token())}
    j = jobs.snapshot()
    job = {k: j.get(k) for k in ("status", "kind", "stage", "detail", "progress", "eta", "eta_total", "error")}
    res = j.get("result") if isinstance(j.get("result"), dict) else {}
    job["title"] = res.get("title") or (j.get("spec") or {}).get("title") or ""
    job["url"] = res.get("url") or ""
    job["review"] = bool(res.get("review"))  # transcrição pronta, esperando revisão no app
    return {"job": job, "recording": record.status(), "watch": bool(store.load_config()["watch_screen"])}


def _need_token():
    tok, cfg = store.get_token(), store.load_config()
    if not tok:
        raise AppError("O Notion ainda não foi conectado.", "Abra Configurações e cole o token da integração.")
    return tok, cfg


def _courses(h):
    tok, cfg = _need_token()
    pages, root = notion.list_pages(tok), cfg["root_page_id"]
    return {"courses": pages, "root": root, "root_ok": any(p["id"] == root for p in pages)}


_previews = {}  # id → (enfeite, png); guarda só as últimas prévias


def _cover_png(decor, title, seed):
    """Capa: ilustração com IA (Z-Image, se instalado) ou o desenho com emojis (sempre disponível)."""
    if imagegen.ready():
        png = imagegen.generate(decor.get("image_prompt") or title, seed=seed)
        if png:
            return png, "ia"
    return cover.render(decor, seed=seed), "emojis"


def _preview(h):
    """Prévia do enfeite: IA escolhe ícone/paleta/emojis e a capa é desenhada no PC."""
    import base64
    body = h._json()
    title = str(body.get("title") or "").strip()[:200]
    if not title:
        raise AppError("Digite o nome da página.", "")
    variant = int(body.get("variant") or 0)
    decor = llm.decorate(title, str(body.get("parent_path") or "")[:300], store.load_config()["ollama_model"],
                         variant=variant)
    png, kind = _cover_png(decor, title, seed=secrets.randbelow(2**31))
    pid = secrets.token_hex(6)
    _previews[pid] = (decor, png)
    for old in list(_previews)[:-6]:
        _previews.pop(old, None)
    return {"preview_id": pid, "decor": decor, "kind": kind,
            "image": "data:image/png;base64," + base64.b64encode(png).decode() if png else None}


def _new_course(h):
    """Cria uma página (curso, módulo…) dentro da página indicada; sem `parent_id`, dentro da raiz."""
    tok, cfg = _need_token()
    body = h._json()
    parent = notion.page_id(body["parent_id"]) if body.get("parent_id") else cfg["root_page_id"]
    if not parent:
        raise AppError("Escolha a página raiz dos cursos.", "Abra Ajustes e escolha a página do Notion.")
    decor, png, note = None, None, None
    if body.get("decorate") and str(body.get("title") or "").strip():
        if body.get("preview_id") in _previews:  # usa exatamente a prévia que o usuário viu
            decor, png = _previews[body["preview_id"]]
        else:
            try:
                decor = llm.decorate(str(body["title"]).strip()[:200], str(body.get("parent_path") or "")[:300],
                                     cfg["ollama_model"])
                png, _ = _cover_png(decor, str(body["title"]).strip(), seed=secrets.randbelow(2**31))
            except AppError as e:  # IA fora do ar ou resposta ruim: cria sem enfeites e avisa
                note = f"{e} A página foi criada sem enfeites."
    made = notion.create_course(tok, parent, body.get("title"), decor, png)
    return {**made, "decor": decor, "note": note or made.pop("cover_note", None)}


def _upload(h):
    name = Path(h._query().get("name", "")).name
    image = Path(name).suffix.lower() in sources.IMAGES  # captura de tela (arrastada ou colada com Ctrl+V)
    if not image and Path(name).suffix.lower() not in sources.MEDIA:
        raise AppError("Formato não suportado.", "Use um destes formatos: " + ", ".join(sources.MEDIA + sources.IMAGES) + ".")
    n = int(h.headers.get("Content-Length") or 0)
    if image and n > sources.MAX_IMAGE_BYTES:
        raise AppError("A imagem é grande demais (máx. 25 MB).", "Reduza a imagem ou tire outra captura.")
    up = store.WORK / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(up).free < n + 500_000_000:
        raise AppError("Sem espaço em disco para copiar o arquivo.", "Libere espaço ou use “Escolher arquivo”.")
    dest = up / f"{secrets.token_hex(4)}_{name}"
    with open(dest, "wb") as f:
        while n > 0:
            chunk = h.rfile.read(min(n, 1 << 20))
            if not chunk:
                break
            f.write(chunk)
            n -= len(chunk)
    if n > 0:
        dest.unlink(missing_ok=True)
        raise AppError("A cópia do arquivo foi interrompida.", "Arraste o arquivo de novo.")
    return {"path": str(dest), "name": name}


def _download(h):
    body = h._json()
    if body.get("what") == "covers":
        jobs.start("download", jobs.download_covers)
        return jobs.snapshot()
    if body.get("what") in ("ollama", "vision"):
        if llm.models() is None:
            raise AppError("O Ollama não está rodando.", "Instale/abra o Ollama (ollama.com) e tente de novo.")
        model = vision.MODEL if body["what"] == "vision" else store.load_config()["ollama_model"]
        jobs.start("download", jobs.download_ollama, model)
    else:
        q = body.get("quality")
        jobs.start("download", jobs.download_whisper, transcribe.pick(q)[1]["name"])
    return jobs.snapshot()


def _clear(h):
    if record.status()["active"]:
        raise AppError("Há uma gravação em andamento.", "Pare a gravação antes de limpar os dados.")
    if jobs.busy():
        raise AppError("Há uma tarefa em andamento.", "Cancele ou aguarde antes de limpar os dados.")
    store.clear_local_data()
    if h._json().get("forget_token"):
        store.delete_token()
        with store.LOCK:
            cfg = store.load_config()
            cfg["root_page_id"] = cfg["root_page_title"] = ""
            store.save_config(cfg)
    return state()


def _screen(h):
    """Miniatura de uma tela capturada, para a revisão (só de dentro da pasta de trabalho da aula)."""
    q = h._query()
    folder = jobs.work_dir(str(q["key"])) / "screens"
    try:
        return vision.Shots(folder).image(int(q["id"]))
    except (OSError, ValueError):
        raise AppError("Tela não encontrada.", "") from None


def _captures_add(body):  # o corpo do pedido só pode ser lido uma vez
    return jobs.add_captures(body.get("key"), body.get("paths"))


def _capture_thumb(h):
    """Miniatura de uma captura enviada (só de dentro da pasta de uploads do Lumen), para a lista da aba Capturas."""
    p = Path(h._query().get("path", "")).resolve()
    if p.parent != (store.WORK / "uploads").resolve() or p.suffix.lower() not in sources.IMAGES or not p.is_file():
        raise AppError("Captura não encontrada.", "")
    return vision.image_jpeg(p)


def _start(h):
    body = h._json()
    jobs.start("process", jobs.process, body, spec=body)
    return jobs.snapshot()


def _finish(h):
    body = h._json()
    jobs.start("process", jobs.finish, body, spec=body)
    return jobs.snapshot()


ROUTES = {
    ("GET", "/api/state"): lambda h: state(),
    ("GET", "/api/job"): lambda h: jobs.snapshot(),
    ("GET", "/api/widget"): _widget,
    ("POST", "/api/settings"): _settings,
    ("GET", "/api/notion/pages"): lambda h: {"pages": notion.list_pages(_need_token()[0])},
    ("GET", "/api/courses"): _courses,
    ("POST", "/api/courses"): _new_course,
    ("POST", "/api/decor/preview"): _preview,
    ("POST", "/api/pick"): lambda h: pick_file(h._json().get("kind")),
    ("POST", "/api/captures/add"): lambda h: _captures_add(h._json()),
    ("POST", "/api/upload"): _upload,
    ("POST", "/api/inspect"): lambda h: inspect(h._json()),
    ("POST", "/api/start"): _start,
    ("GET", "/api/screen"): _screen,
    ("GET", "/api/capture"): _capture_thumb,
    ("POST", "/api/finish"): _finish,
    ("POST", "/api/cancel"): lambda h: (jobs.cancel(), jobs.snapshot())[1],
    ("POST", "/api/download"): _download,
    ("POST", "/api/clear"): _clear,
    ("GET", "/api/record"): lambda h: record.status(),
    ("GET", "/api/history"): lambda h: {"items": sorted(store.history().values(), key=lambda x: x.get("created", ""), reverse=True)},
    ("POST", "/api/record/start"): lambda h: (record.start(h._json().get("title")), record.status())[1],
    ("POST", "/api/record/stop"): lambda h: record.stop(),
    ("POST", "/api/record/discard"): lambda h: (record.discard(), record.status())[1],
}


def serve(port=0):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
