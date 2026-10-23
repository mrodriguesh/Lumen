"""Servidor local (somente 127.0.0.1) que serve a interface e a API usada por ela."""
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import (AppError, cover, eta, imagegen, jobs, llm, music, notion, obsidian, pomodoro, record, sources, store,
               transcribe, understanding, vault, vision)

log = logging.getLogger("lumen")
WEB = Path(__file__).parent / "web"
STATIC = {"/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
          "/app.js": ("app.js", "text/javascript"), "/widget": ("widget.html", "text/html"),
          "/widget.css": ("widget.css", "text/css"), "/widget.js": ("widget.js", "text/javascript"),
          "/note": ("note.html", "text/html"), "/note.js": ("note.js", "text/javascript"),
          "/understanding-editor.js": ("understanding-editor.js", "text/javascript"),
          "/pomodoro.js": ("pomodoro.js", "text/javascript"),
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


_PICK_DIR = """import sys, tkinter as t
from tkinter import filedialog as f
r = t.Tk(); r.withdraw(); r.attributes('-topmost', 1)
print(f.askdirectory(title=sys.argv[1], initialdir=sys.argv[2] or None, mustexist=True) or '')"""


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
    if kind == "vault":  # pasta do cofre do Obsidian (validada ao salvar em Ajustes)
        r = subprocess.run([sys.executable, "-c", _PICK_DIR, "Escolher o cofre do Obsidian", str(Path.home())],
                           capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"path": str(Path(r.stdout.strip())) if r.stdout.strip() else ""}
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
        "formats": sources.MEDIA, "images": sources.IMAGES, "job": job_view(), "recording": record.status(),
        "pending": understanding.pending(),
        "covers": {"ready": imagegen.ready(), "label": imagegen.ENGINES[imagegen.DEFAULT_ENGINE]["label"],
                   "size": imagegen.ENGINES[imagegen.DEFAULT_ENGINE]["size"]},
        "vision": {"model": vision.MODEL, "size": vision.SIZE,
                   "installed": om is not None and any(x in (vision.MODEL, vision.MODEL + ":latest") for x in om)},
        "music": {"ready": music.ready(), "size": music.SIZE},  # só confere os arquivos; nenhum modelo é carregado
        "obsidian": obsidian_view(cfg),
    }


def obsidian_view(cfg):
    """Cofres detectados (o usuário escolhe; nunca em silêncio) e a pasta onde as notas vão ficar."""
    out = {"vaults": [{**v, "folder": vault.default_folder(Path(v["path"])) if v["ok"] else ""} for v in vault.vaults()],
           "folder": "", "error": None}
    if cfg["obsidian_vault"]:
        try:
            root, notes, _ = obsidian.folders(cfg)
            out["folder"] = notes.relative_to(root).as_posix()
        except AppError as e:
            out["error"] = f"{e} {e.action}".strip()
    return out


def job_view():
    """A tarefa como a interface a vê: o conteúdo da aula só depois da compreensão (understanding.guard)."""
    return understanding.guard(jobs.snapshot())


def inspect(spec):
    src = sources.resolve(spec)
    cfg, token = store.load_config(), store.get_token()
    _, m = transcribe.pick(cfg["quality"])
    dup = store.history().get(src["key"])
    if dup and dup.get("page_id") and token and not notion.page_url(token, dup["page_id"]):
        dup = {k: v for k, v in dup.items() if k not in ("page_id", "url", "block_ids")}  # página apagada no Notion
    if dup and not (dup.get("page_id") or (dup.get("obsidian") or {}).get("status") == "ok"):
        dup = None
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
                if name.endswith(".html"):
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
    if "music_filter" in body:
        cfg["music_filter"] = body["music_filter"] is True
    if body.get("music_mode") in music.MODES:
        cfg["music_mode"] = body["music_mode"]
    if body.get("widget") in ("off", "left", "right", "top", "bottom", "free"):
        cfg["widget"] = body["widget"]
    if body.get("destinations") in ("notion", "obsidian", "both"):
        cfg["destinations"] = body["destinations"]
    if body.get("study_level") in ("rapido", "balanceado", "profundo"):
        cfg["study_level"] = body["study_level"]
    if "obsidian_vault" in body:
        raw = str(body["obsidian_vault"] or "").strip()
        cfg["obsidian_vault"] = str(vault.check(raw)) if raw else ""
    for k in ("obsidian_folder", "obsidian_canvas_folder"):
        if k in body:
            rel = str(body[k] or "").strip().replace("\\", "/").strip("/")[:200]
            vault.inside(Path(cfg["obsidian_vault"] or "."), rel)  # recusa “..”, caminho absoluto e pasta oculta
            cfg[k] = rel
    for k in ("obsidian_canvas", "obsidian_connections", "obsidian_review", "obsidian_attachments", "obsidian_open"):
        if k in body:
            cfg[k] = body[k] is True
    if "review_intervals" in body:
        iv = body["review_intervals"]
        days = [int(x) for x in re.findall(r"\d+", iv)] if isinstance(iv, str) else iv
        if not (isinstance(days, list) and 1 <= len(days) <= 10
                and all(isinstance(d, int) and 1 <= d <= 365 for d in days) and days == sorted(set(days))):
            raise AppError("Intervalos de revisão inválidos.", "Use dias crescentes entre 1 e 365, como 1, 3, 7, 14, 30, 60.")
        cfg["review_intervals"] = days
    if ("destinations" in body or "obsidian_vault" in body) and cfg["destinations"] != "notion":
        obsidian.folders(cfg)  # Obsidian ligado sem cofre válido: diz o que falta antes de salvar
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
    # notas que ainda estão sendo escritas: a barra lateral mostra “Minha compreensão” da aula ativa
    writing = understanding.pending(extra=j.get("key") if j.get("status") == "running" else None)  # escrevendo, analisando ou analisada (ainda não salva no Notion): a nota segue visível
    cfg = store.load_config()
    return {"job": job, "recording": record.status(), "watch": bool(cfg["watch_screen"]), "music": cfg["music_filter"],
            "notes": writing, "pomodoro": pomodoro.view()}


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
        return job_view()
    if body.get("what") == "music":
        jobs.start("download", jobs.download_music)
        return job_view()
    if body.get("what") in ("ollama", "vision"):
        if llm.models() is None:
            raise AppError("O Ollama não está rodando.", "Instale/abra o Ollama (ollama.com) e tente de novo.")
        model = vision.MODEL if body["what"] == "vision" else store.load_config()["ollama_model"]
        jobs.start("download", jobs.download_ollama, model)
    else:
        q = body.get("quality")
        jobs.start("download", jobs.download_whisper, transcribe.pick(q)[1]["name"])
    return job_view()


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
    understanding.reveal(str(q["key"]))  # as telas da aula também seriam cola antes da compreensão
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


def _deliver(h):
    """“Tentar de novo só o Obsidian/Notion”, “Substituir mesmo assim” e “Salvar no Obsidian” da Biblioteca."""
    body = h._json()
    jobs.start("process", jobs.deliver, body, spec=body)
    return job_view()


def _open(h):
    """Abre no Obsidian a nota, o mapa ou o painel de uma aula. Só arquivos do cofre configurado, achados pelo
    manifesto; o endereço obsidian:// é montado aqui (nenhum vem da interface)."""
    body = h._json()
    root, folder, _ = obsidian.folders(store.load_config())
    if body.get("what") == "dashboard":
        path = folder / "Lumen Dashboard.md"
    else:
        ob = (store.history().get(str(body.get("key") or "")) or {}).get("obsidian") or {}
        rel = ob.get("canvas" if body.get("what") == "canvas" else "note")
        if not rel:
            raise AppError("Esta aula ainda não foi salva no Obsidian.", "Use “Salvar no Obsidian”.")
        path = root / rel
    path = path.resolve()
    if root not in path.parents or not path.is_file():
        raise AppError("O arquivo não foi encontrado no cofre.", "Ele pode ter sido movido para fora da pasta ou apagado.")
    obsidian.open_path(path)
    return {}


def _history():
    """Biblioteca: aulas salvas em algum destino, com a chave (para abrir no Obsidian ou salvar de novo)."""
    items = [{**v, "key": k} for k, v in store.history().items()
             if v.get("url") or (v.get("obsidian") or {}).get("status") == "ok"]
    when = lambda x: x.get("created") or (x.get("obsidian") or {}).get("at") or ""  # noqa: E731
    return {"items": sorted(items, key=when, reverse=True)}


def _start(h):
    body = h._json()
    jobs.start("process", jobs.process, body, spec=body)
    return job_view()


def _finish(h):
    body = h._json()
    jobs.start("process", jobs.finish, body, spec=body)
    return job_view()


def _draft(h):
    """Autosave de “Minha compreensão” (também por sendBeacon ao fechar a janela, com o token na URL)."""
    body = h._json()
    return understanding.save_draft(str(body.get("key") or ""), body.get("text"), body.get("at"))


def _context():
    """O que bloqueia “Processar” além da nota: gravação em andamento e outra tarefa rodando (understanding.readiness)."""
    return {"recording": record.active(), "job": jobs.running_info()}


understanding.context = _context


def _submit(h):
    """“Processar minha compreensão”: confere os pré-requisitos (a mesma regra que as interfaces mostram), guarda a
    nota e só então começa a análise da IA, com a nota já travada para edição."""
    body = h._json()
    key = str(body.get("key") or "")
    rec = understanding.load(key)
    if rec and understanding.readiness(rec)["phase"] in ("recording", "busy", "preparing", "prep_failed"):
        r = understanding.readiness(rec)
        raise AppError(r["label"], r["detail"] or "Sua compreensão continua salva.")
    understanding.submit(key, body.get("text"), body.get("at"))
    understanding.begin_analysis(key)
    try:
        jobs.start("analyze", jobs.analyze, key, spec={"key": key})
    except Exception:
        understanding.end_analysis()  # o job não começou: a nota não pode ficar travada
        raise
    return job_view()


ROUTES = {
    ("GET", "/api/state"): lambda h: state(),
    ("GET", "/api/job"): lambda h: job_view(),
    ("GET", "/api/understanding"): lambda h: understanding.get(h._query()["key"]),
    ("POST", "/api/understanding/draft"): _draft,
    ("POST", "/api/understanding/submit"): _submit,
    ("GET", "/api/review"): lambda h: jobs.review(h._query()["key"]),
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
    ("POST", "/api/cancel"): lambda h: (jobs.cancel(), job_view())[1],
    ("POST", "/api/download"): _download,
    ("POST", "/api/clear"): _clear,
    ("GET", "/api/record"): lambda h: record.status(),
    ("GET", "/api/history"): lambda h: _history(),
    ("POST", "/api/deliver"): _deliver,
    ("POST", "/api/open"): _open,
    ("POST", "/api/record/start"): lambda h: (record.start(h._json().get("title")), record.status())[1],
    ("POST", "/api/record/stop"): lambda h: record.stop(keep=h._json().get("exit") is True),
    ("POST", "/api/record/discard"): lambda h: (record.discard(), record.status())[1],
    ("POST", "/api/record/pause"): lambda h: (record.pause(), record.status())[1],
    ("POST", "/api/record/resume"): lambda h: (record.resume(), record.status())[1],
    ("POST", "/api/record/recover"): lambda h: record.recover(h._json().get("use") is True) or record.status(),
    ("GET", "/api/pomodoro"): lambda h: pomodoro.view(),
    ("POST", "/api/pomodoro"): lambda h: (lambda b: pomodoro.act(b.get("action"), b.get("settings")))(h._json()),
}


def serve(port=0):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
