"""Servidor local (somente 127.0.0.1) que serve a interface e a API usada por ela."""
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import (AppError, area, catalog, cover, diagnostics, eta, gdrive, hardware, hyperbooklm, imagegen, jobs, llm, music, notion, obsidian, onlocal,
               opennotebook, package, pomodoro, protection, record, repair, sources, store, transcribe, understanding, vault, vision, visual3d)

from .study import api as study_api  # noqa: E402 — Lúmen Study AI (rotas /api/study/*)
from .study import listen as study_voice  # noqa: E402 — a voz dos Estudos (/api/study/voice/*, fase 6)
from .study import practice as study_practice  # noqa: E402 — Treino falado (/api/study/practice, fase 6)
from .study import voice_admin as study_voice_admin  # noqa: E402 — modelos, máquina, pronúncias e vozes (fase 6)
from .study import call as study_call  # noqa: E402 — conversa por voz em tempo real (/api/study/call*, fase 6 parte 3)
from . import listening  # noqa: E402 — modo escuta: chamada transcrita ao vivo no Notion e no Obsidian (/api/listen*)

log = logging.getLogger("lumen")
WEB = Path(__file__).parent / "web"
STATIC = {"/lumen.png": ("lumen.png", "image/png"), "/lumen-meteor.png": ("lumen-meteor.png", "image/png"), "/lumen-meteor-new.png": ("lumen-meteor-new.png", "image/png"), "/lumen-meteor-lib.png": ("lumen-meteor-lib.png", "image/png"), "/lumen-meteor-integ.png": ("lumen-meteor-integ.png", "image/png"), "/lumen-meteor-settings.png": ("lumen-meteor-settings.png", "image/png"), "/lumen-meteor-widget.png": ("lumen-meteor-widget.png", "image/png"), "/favicon.ico": ("favicon.ico", "image/x-icon"),
          "/protection.js": ("protection.js", "text/javascript"), "/protection.css": ("protection.css", "text/css"),
          "/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
          "/app.js": ("app.js", "text/javascript"), "/widget": ("widget.html", "text/html"),
          "/widget.css": ("widget.css", "text/css"), "/widget.js": ("widget.js", "text/javascript"),
          "/note": ("note.html", "text/html"), "/note.js": ("note.js", "text/javascript"),
          "/understanding-editor.js": ("understanding-editor.js", "text/javascript"),
          "/pomodoro.js": ("pomodoro.js", "text/javascript"),
          "/study.js": ("study.js", "text/javascript"), "/study.css": ("study.css", "text/css"),
          "/md.js": ("md.js", "text/javascript"), "/chat.js": ("chat.js", "text/javascript"), "/chat.css": ("chat.css", "text/css"),
    "/voice.js": ("voice.js", "text/javascript"), "/opennotebook.js": ("opennotebook.js", "text/javascript"), "/hyperbooklm.js": ("hyperbooklm.js", "text/javascript"), "/study-call.js": ("study-call.js", "text/javascript"),
          "/study-learn.js": ("study-learn.js", "text/javascript"), "/study-diagram.js": ("study-diagram.js", "text/javascript"), "/study-settings.js": ("study-settings.js", "text/javascript"),
          "/ui.css": ("ui.css", "text/css"), "/ui.js": ("ui.js", "text/javascript"),
          "/glass.css": ("glass.css", "text/css"), "/glass.js": ("glass.js", "text/javascript"),
          "/cursor.js": ("cursor.js", "text/javascript"),
          "/icons.svg": ("icons.svg", "image/svg+xml"), "/design": ("design.html", "text/html"),
          "/design.js": ("design.js", "text/javascript"),
          "/fonts/inter-latin.woff2": ("fonts/inter-latin.woff2", "font/woff2"),
          "/fonts/inter-latin-ext.woff2": ("fonts/inter-latin-ext.woff2", "font/woff2")}
TOKEN = secrets.token_urlsafe(24)
last_seen = time.monotonic()
bye_at = None

# Interface em memória: o WebView2 pede app.js/app.css/fontes a cada recarga. O arquivo só é relido quando muda
# (mtime + tamanho), e o ETag evita reenviar o corpo quando o navegador já tem a mesma versão (304).
_STATIC_CACHE = {}
_STATIC_LOCK = threading.Lock()


def _static(path):
    """(bytes, content-type, etag) de um item de STATIC, com cache invalidado pelo próprio arquivo."""
    name, ctype = STATIC[path]
    file = WEB / name
    st = file.stat()
    key = (st.st_mtime_ns, st.st_size)
    with _STATIC_LOCK:
        hit = _STATIC_CACHE.get(path)
    if hit and hit[0] == key:
        return hit[1], ctype, hit[2]
    body = file.read_bytes()
    if name.endswith(".html"):
        body = body.replace(b"{{TOKEN}}", TOKEN.encode())
    etag = '"%s"' % hashlib.sha1(body).hexdigest()
    with _STATIC_LOCK:
        _STATIC_CACHE[path] = (key, body, etag)
    return body, ctype, etag


def _page_marks(body):
    """A janela principal, a barra e a nota com o estilo da interface (classic | glass) no atributo do <html>.
    Só um valor fixo entra na página: o estilo vem de store.UI_STYLES."""
    cfg = store.load_config()
    style = cfg.get("ui_style") if cfg.get("ui_style") in store.UI_STYLES else "classic"
    body = body.replace(b"{{UI_STYLE}}", style.encode())
    return body, '"%s"' % hashlib.sha1(body).hexdigest()

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


def _pick_one(title, label, exts, start=""):
    """Um arquivo escolhido no diálogo do Windows (o caminho fica no servidor quando quem chama não o devolve)."""
    r = subprocess.run([sys.executable, "-c", _PICK, title, label, " ".join("*" + e for e in exts), start],
                       capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.strip()


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
    path = _pick_one(title, label, exts, start)
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
                   "size": imagegen.ENGINES[imagegen.DEFAULT_ENGINE]["size"],
                   "license": imagegen.ENGINES[imagegen.DEFAULT_ENGINE]["license"], "folder": str(imagegen.folder())},
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
            root, home = obsidian.folders(cfg)
            out["folder"] = home.relative_to(root).as_posix()
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
    if dup:
        dup = {**dup, "key": src["key"], "classification": _classified(dup)}  # “Abrir”: aula que só está no Obsidian
    resumable = (jobs.work_dir(src["key"]) / "transcript.json").exists()
    needs_tr = not src.get("captions") and bool(src.get("path")) and not resumable
    return {
        "suggest": catalog.suggest(src["title"], src.get("link") or "", spec.get("path") or ""),
        "title": src["title"], "label": src["label"], "link": src["link"], "author": src.get("author"),
        "info": src["info"], "duration": src["duration"], "duplicate": dup, "resumable": resumable,
        "has_captions": bool(src.get("captions")), "segments": len(src.get("captions") or []),
        "needs_transcript": not src.get("captions") and not src.get("path") and src["kind"] != "captures",
        "captures": len(src.get("paths") or []),
        "needs_transcription": needs_tr, "whisper_model": m["label"], "whisper_ready": transcribe.downloaded(m["name"]),
        "estimate": eta.transcribe_seconds(src["duration"], m["name"]) if needs_tr and src["duration"] else None,
    }


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 mantém a conexão aberta: o WebView2 deixa de abrir um TCP novo a cada /api/job (a cada 800 ms).
    # POST fecha depois da resposta (o corpo pode não ser lido por todas as rotas); GET reaproveita.
    protocol_version = "HTTP/1.1"
    timeout = 60  # conexão ociosa fecha sozinha; sem isto, cada aba deixaria uma thread presa para sempre
    disable_nagle_algorithm = True  # respostas pequenas (polling/NDJSON) saem sem o atraso do Nagle

    def log_message(self, *a):  # não registra URLs nem corpos
        pass

    def _send(self, code, body, ctype="application/json", headers=None, cache="no-store"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self'; connect-src 'self'")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # a janela foi fechada enquanto a resposta estava sendo enviada

    def _not_modified(self, etag):
        """304: a interface já tem esta versão em cache; nenhum byte de corpo volta."""
        self.send_response(304)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()

    def _stream(self, stream):
        """Resposta em NDJSON, um evento por linha, enviada conforme é gerada (a conversa do Lúmen Study AI).
        Conexão fechada pela janela = cancelar a geração."""
        self.close_connection = True  # sem Content-Length: o fim é o fim da conexão
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self'; connect-src 'self'")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in stream.events:
                self.wfile.write((json.dumps(event, ensure_ascii=False, default=str) + "\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            stream.on_close()
        except Exception as e:  # noqa: BLE001 — depois do cabeçalho, o erro vira um evento
            log.error("erro no streaming: %s", type(e).__name__)
            try:
                self.wfile.write((json.dumps({"type": "error", "message": f"Erro inesperado ({type(e).__name__})."}) + "\n").encode())
            except OSError:
                pass
        finally:
            close = getattr(stream.events, "close", None)
            if close:
                close()

    def _file(self, f):
        """Um arquivo com Range (bytes=a-b, a- ou -n): o <audio> pede pedaços para pular de capítulo."""
        try:
            size = f.path.stat().st_size
        except OSError:
            return self._send(404, {"error": {"message": "Arquivo não encontrado."}})
        start, end = 0, size - 1
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        partial = bool(m and (m[1] or m[2]))
        if partial:
            start, end = (int(m[1]), min(int(m[2] or size - 1), size - 1)) if m[1] else (max(size - int(m[2]), 0), size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", f.ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            with open(f.path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0 and (chunk := fh.read(min(left, 1 << 16))):
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # o player pediu outro pedaço e fechou este

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
        if method == "POST":
            # O corpo nem sempre é lido (ex.: /api/bye por sendBeacon). Fechar depois da resposta evita que os
            # bytes restantes sejam lidos como o próximo pedido na mesma conexão.
            self.close_connection = True
        if not self._allowed():
            return self._send(403, {"error": {"message": "Acesso negado."}})
        last_seen = time.monotonic()
        path = urllib.parse.urlsplit(self.path).path
        try:
            if method == "GET" and path in STATIC:
                try:
                    body, ctype, etag = _static(path)
                except OSError:
                    return self._send(404, {"error": {"message": "Arquivo não encontrado."}})
                if path in ("/", "/widget", "/note"):  # estilo da interface já no <html>: a janela abre no visual certo, sem piscar
                    body, etag = _page_marks(body)
                if self.headers.get("If-None-Match") == etag:
                    return self._not_modified(etag)
                return self._send(200, body, ctype, {"ETag": etag}, cache="no-cache")
            if (method, path) == ("POST", "/api/bye"):  # janela fechada (sendBeacon)
                bye_at = time.monotonic()
                return self._send(200, {})
            fn = ROUTES.get((method, path))
            if not fn:
                return self._send(404, {"error": {"message": "Não encontrado."}})
            out = fn(self)
            if isinstance(out, study_api.Stream):
                return self._stream(out)
            if isinstance(out, study_api.File):
                return self._file(out)
            if isinstance(out, tuple):  # (bytes, tipo): imagem que não é JPEG (a visualização 3D)
                return self._send(200, *out)
            return self._send(200, out, "image/jpeg" if isinstance(out, bytes) else "application/json")
        except AppError as e:
            err = {"message": str(e), "action": e.action}
            return self._send(400, {"error": err})
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
    if "obsidian_folder" in body:  # a área de estudos
        rel = str(body["obsidian_folder"] or "").strip().replace("\\", "/").strip("/")[:200]
        vault.inside(Path(cfg["obsidian_vault"] or "."), rel)  # recusa “..”, caminho absoluto e pasta oculta
        cfg["obsidian_folder"] = rel
    if "notion_free_page" in body:  # “Conteúdo gratuito” no Notion
        cfg["notion_free_page_id"] = notion.page_id(body["notion_free_page"]) if body["notion_free_page"] else ""
        cfg["notion_free_page_title"] = str(body.get("notion_free_page_title") or "")[:200] if body["notion_free_page"] else ""
    if body.get("visual_3d") in visual3d.MODES:
        cfg["visual_3d"] = body["visual_3d"]
    if "ui_style" in body:  # Ajustes → Aparência → Estilo da interface: só a apresentação muda (nenhum dado, rota ou comportamento)
        if body["ui_style"] not in store.UI_STYLES:
            raise AppError("Estilo da interface inválido.", "Escolha Clássico ou Lúmen Glass 2026.")
        cfg["ui_style"] = body["ui_style"]
    if body.get("obsidian_board_density") in ("compacto", "equilibrado", "visual"):
        cfg["obsidian_board_density"] = body["obsidian_board_density"]
    for k in ("obsidian_canvas", "obsidian_board", "obsidian_connections", "obsidian_review", "obsidian_attachments",
              "obsidian_open", "notion_open", "opennotebook_auto"):
        if k in body:
            cfg[k] = body[k] is True
    if "review_intervals" in body:
        iv = body["review_intervals"]
        days = [int(x) for x in re.findall(r"\d+", iv)] if isinstance(iv, str) else iv
        if not (isinstance(days, list) and 1 <= len(days) <= 10
                and all(type(d) is int and 1 <= d <= 365 for d in days) and days == sorted(set(days))):
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
            "notes": writing, "pomodoro": pomodoro.view(), "listening": listening.brief(),
            "ui": cfg.get("ui_style") if cfg.get("ui_style") in store.UI_STYLES else "classic"}


def _need_token():
    tok, cfg = store.get_token(), store.load_config()
    if not tok:
        raise AppError("O Notion ainda não foi conectado.", "Abra Integrações e cole o token da integração do Notion.")
    return tok, cfg


def _courses(h):
    tok, cfg = _need_token()
    pages, root = notion.list_pages(tok), cfg["root_page_id"]
    return {"courses": pages, "root": root, "root_ok": any(p["id"] == root for p in pages)}


# Prévias de capa (só no PC, nada vai ao Notion): id → enfeite, PNG, tipo e o contexto para o qual foi feita.
# Ficam na memória (as últimas 6, por até 1 h: o upload do Notion também expira em 1 h sem uso).
_previews = {}
PREVIEW_TTL = 3600
_preview_busy = threading.Lock()  # uma prévia por vez (o gerador já serializa a GPU; isto evita a fila do clique duplo)


def _cover_png(decor, title, seed):
    """Capa: ilustração com IA (Z-Image, se instalado) ou o desenho com emojis (sempre disponível)."""
    if imagegen.ready():
        png = imagegen.generate(decor.get("image_prompt") or title, seed=seed)
        if png:
            return png, "ia"
    png = cover.render(decor, seed=seed)
    return (png, "emojis") if png else (None, "notion")  # nem o desenho saiu: fica a capa de cor do próprio Notion


def _draw(title, parent, variant):
    """A IA local escolhe ícone, paleta, frase e o pedido da ilustração; a capa é desenhada no PC. Uma por vez."""
    if not _preview_busy.acquire(blocking=False):
        raise AppError("Já estou gerando uma capa.", "Espere a prévia atual terminar.")
    try:
        t0 = time.monotonic()
        decor = llm.decorate(title, parent, store.load_config()["ollama_model"], variant=variant)
        png, kind = _cover_png(decor, title, seed=secrets.randbelow(2**31))
        secs = round(time.monotonic() - t0)
    finally:
        _preview_busy.release()
    why = "A ilustração com IA não ficou pronta neste PC" if imagegen.ready() else "O gerador de capas com IA não está instalado"
    note = {"ia": "", "emojis": f"{why}; esta é a capa alternativa, desenhada com emojis.",
            "notion": f"{why} e o desenho com emojis também falhou; a página vai usar uma capa de cor do Notion, "
                      "com o ícone e a frase da prévia."}[kind]
    return decor, png, kind, secs, note


def _keep(entry):
    """Guarda uma prévia (as últimas 6) e devolve o id dela."""
    pid = secrets.token_hex(8)
    _previews[pid] = {**entry, "at": time.monotonic()}
    for old in list(_previews)[:-6]:
        _previews.pop(old, None)
    return pid


def _data_url(png):
    import base64
    return "data:image/png;base64," + base64.b64encode(png).decode() if png else None


def _preview(h):
    """Prévia da capa e do enfeite de um curso novo. Nenhum pedido ao Notion: a publicação só acontece ao criar a
    página, com esta mesma imagem (preview_id)."""
    body = h._json()
    title = str(body.get("title") or "").strip()[:200]
    if not title:
        raise AppError("Digite o nome do curso.", "A capa é feita para esse nome.")
    parent = str(body.get("parent_path") or store.load_config().get("root_page_title") or "")[:300]
    decor, png, kind, secs, note = _draw(title, parent, int(body.get("variant") or 0))
    pid = _keep({"decor": decor, "png": png, "kind": kind, "title": package.norm(title), "parent": parent})
    return {"preview_id": pid, "decor": decor, "kind": kind, "note": note, "seconds": secs, "title": title,
            "parent": parent, "image": _data_url(png)}


def _conn(token):
    """A conexão do Notion em uso (trocar ou tirar o token invalida as prévias feitas com a anterior)."""
    return hashlib.sha256((token or "").encode()).hexdigest()[:16]


_theme = lambda v: " ".join(str(v or "").split())[:300]  # noqa: E731


def _page_preview(h):
    """Capas do Notion: a prévia para uma página que já existe. Só no PC, nenhum pedido ao Notion; fica presa à
    página, ao tema e à conexão, e “Aplicar” usa exatamente esta imagem. Do enfeite, só a imagem é usada."""
    tok, _ = _need_token()
    body = h._json()
    page, theme = notion.page_id(body.get("page_id")), _theme(body.get("theme"))
    subject = theme or str(body.get("title") or "").strip()[:200]
    if not subject:
        raise AppError("Escolha a página primeiro.", "A capa é feita a partir do título dela.")
    _, png, kind, secs, note = _draw(subject, "", int(body.get("variant") or 0))
    if not png:
        raise AppError("Não foi possível desenhar a capa neste PC.",
                       "Tente de novo. Se continuar, confira o gerador em Detalhes técnicos.")
    pid = _keep({"png": png, "kind": kind, "page": page, "theme": theme, "conn": _conn(tok)})
    return {"preview_id": pid, "kind": kind, "note": note, "seconds": secs, "theme": theme, "image": _data_url(png)}


_applying = threading.Lock()  # uma aplicação por vez: o clique duplo não envia a imagem duas vezes


def _cover_apply(h):
    """Aplica a prévia aprovada como capa da página (só o campo cover) e confere lendo a página de novo."""
    tok, _ = _need_token()
    body = h._json()
    page, key = notion.page_id(body.get("page_id")), str(body.get("preview_id") or "")
    p = _previews.get(key)
    why = (("A prévia da capa expirou ou não está mais neste PC.", "Gere a capa de novo.")
           if not p or "page" not in p or time.monotonic() - p["at"] > PREVIEW_TTL else
           ("Esta prévia foi feita para outra página.", "Gere a capa de novo para a página escolhida.") if p["page"] != page else
           ("A conexão com o Notion mudou depois da prévia.", "Escolha a página e gere a capa de novo.") if p["conn"] != _conn(tok) else
           ("O tema mudou depois da prévia.", "Gere a capa de novo com o tema atual.") if p["theme"] != _theme(body.get("theme")) else
           ("Há uma prévia mais nova para esta página.", "Aplique a prévia mais recente.")
           if any(v.get("page") == page and v["at"] > p["at"] for v in _previews.values()) else None)
    if why:
        return {"state": "regenerate", "message": why[0], "action": why[1]}
    if not _applying.acquire(blocking=False):
        raise AppError("Já estou aplicando uma capa.", "Espere a confirmação do Notion.")
    try:
        now = notion.page_info(tok, page)  # de novo: ainda existe, fora da lixeira e com acesso
        state = None
        if p.get("upload"):  # tentativa anterior sem resposta: confere antes de repetir
            ok = notion.cover_is(tok, page, p["png"])
            state = "confirmed" if ok else "unconfirmed" if ok is None else None
        if not state and now["cover"] != body.get("cover"):
            return {"changed": True, "page": now}
        if not state:
            p["upload"], state = notion.apply_cover(tok, page, p["png"], p.get("upload"), f"capa-{key}.png")
        log.info("capa: página %s, envio %s, antes %s, %s", page, p.get("upload"), now["cover"] or "sem capa", state)
        return {"state": state, "page": notion.page_info(tok, page) if state == "confirmed" else now}
    finally:
        _applying.release()


def _approved(pid, title):
    """A prévia que o usuário viu, para este nome. Expirada, de outro nome ou desconhecida: recusa (nunca troca por
    outra imagem sem avisar)."""
    p = _previews.get(str(pid or ""))
    if not p or time.monotonic() - p["at"] > PREVIEW_TTL:
        _previews.pop(str(pid or ""), None)
        raise AppError("A prévia da capa expirou ou não está mais neste PC.", "Gere a prévia de novo antes de criar.")
    if p.get("title") != package.norm(title):
        raise AppError("A prévia foi feita para outro nome.", "Gere a prévia de novo com o nome atual.")
    return p


def _new_course(h):
    """Cria uma página (curso, módulo…) dentro da página indicada; sem `parent_id`, dentro da raiz."""
    tok, cfg = _need_token()
    body = h._json()
    parent = notion.page_id(body["parent_id"]) if body.get("parent_id") else cfg["root_page_id"]
    if not parent:
        raise AppError("Escolha a página raiz dos cursos.", "Abra Integrações e escolha a página raiz do Notion.")
    decor, png, note = None, None, None
    if body.get("decorate") and str(body.get("title") or "").strip():
        if body.get("preview_id"):  # usa exatamente a prévia que o usuário viu (expirada: recusa)
            p = _approved(body["preview_id"], str(body["title"]).strip())
            decor, png = p["decor"], p["png"]
        else:
            try:
                decor = llm.decorate(str(body["title"]).strip()[:200], str(body.get("parent_path") or "")[:300],
                                     cfg["ollama_model"])
                png, _ = _cover_png(decor, str(body["title"]).strip(), seed=secrets.randbelow(2**31))
            except AppError as e:  # IA fora do ar ou resposta ruim: cria sem enfeites e avisa
                note = f"{e} A página foi criada sem enfeites."
    made = notion.create_course(tok, parent, body.get("title"), decor, png)
    return {**made, "decor": decor, "note": note or made.pop("cover_note", None)}


def _refuse(h, n, err):
    """Recusa um envio lendo (e jogando fora) o corpo antes: com o corpo por ler, o Windows às vezes derruba a conexão
    (WinError 10053) e a interface não recebe a mensagem. Acima de 64 MB, fechar é mais barato que ler."""
    while 0 < n <= 64 << 20:
        chunk = h.rfile.read(min(n, 1 << 20))
        if not chunk:
            break
        n -= len(chunk)
    raise err


def _upload(h):
    name = Path(h._query().get("name", "")).name
    image = Path(name).suffix.lower() in sources.IMAGES  # captura de tela (arrastada ou colada com Ctrl+V)
    n = int(h.headers.get("Content-Length") or 0)
    if not image and Path(name).suffix.lower() not in sources.MEDIA:
        _refuse(h, n, AppError("Formato não suportado.", "Use um destes formatos: " + ", ".join([*sources.MEDIA, *sources.IMAGES]) + "."))
    if image and n > sources.MAX_IMAGE_BYTES:
        _refuse(h, n, AppError("A imagem é grande demais (máx. 25 MB).", "Reduza a imagem ou tire outra captura."))
    up = store.WORK / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(up).free < n + 500_000_000:
        _refuse(h, n, AppError("Sem espaço em disco para copiar o arquivo.", "Libere espaço ou use “Escolher arquivo”."))
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
            cfg["root_page_id"] = cfg["root_page_title"] = cfg["notion_free_page_id"] = cfg["notion_free_page_title"] = ""
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


def _visual_file(h):
    """A visualização 3D de uma aula já salva (a prévia no resultado), do cache do Lumen; kind=png: a imagem
    estática (para quem pediu menos movimento no sistema)."""
    q = h._query()
    e = store.history().get(str(q.get("key") or "")) or {}
    v = e.get("visual") or {}
    name = v.get("png") if q.get("kind") == "png" else v.get("file")
    if not (isinstance(name, str) and re.fullmatch(r"[0-9a-f]{16}\.(gif|png)", name)):
        raise AppError("Visualização não encontrada.", "")
    try:
        data = (visual3d._folder(e.get("lumen_id")) / name).read_bytes()
    except (OSError, ValueError):
        raise AppError("Visualização não encontrada.", "") from None
    return data, "image/gif" if name.endswith(".gif") else "image/png"


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
    cfg = store.load_config()
    root, home = obsidian.folders(cfg)
    if body.get("what") in ("home", "dashboard"):
        area.refresh(cfg)  # a Home existe mesmo antes da primeira aula
        path = home / area.HOME
    elif body.get("what") == "course":
        path = area._course_notes(home).get(str(body.get("course_id") or ""))
        if not path:
            raise AppError("A nota deste curso ainda não está no cofre.", "Ela é criada quando o Obsidian está ligado.")
    else:
        ob = (store.history().get(str(body.get("key") or "")) or {}).get("obsidian") or {}
        rel = ob.get({"canvas": "canvas", "board": "board"}.get(body.get("what"), "note"))
        if not rel:
            raise AppError("Esta aula ainda não foi salva no Obsidian.", "Use “Salvar no Obsidian”.")
        path = root / rel
    path = path.resolve()
    if root not in path.parents or not path.is_file():
        raise AppError("O arquivo não foi encontrado no cofre.", "Ele pode ter sido movido para fora da pasta ou apagado.")
    obsidian.open_path(path)
    return {}


def _reviews():
    """Revisões do Obsidian para o Início, com a chave da aula para abrir a nota pelo /api/open."""
    try:
        items = obsidian.due_reviews(store.load_config())
    except (AppError, OSError, ValueError):  # cofre não escolhido ou fora do ar: o Início só não mostra o cartão
        return {"items": []}
    keys = {v.get("lumen_id"): k for k, v in store.history().items() if v.get("lumen_id")}
    return {"items": [{**i, "key": keys.get(i["lumen_id"])} for i in items]}


def _classified(entry):
    """A organização de uma aula da history, com os nomes atuais do catálogo (curso renomeado). Aulas de antes da
    organização (ou com o curso que sumiu) ficam em “A organizar”."""
    try:
        return catalog.classification(entry.get("classification"))
    except (AppError, ValueError, TypeError):
        return dict(catalog.INBOX)


def _history():
    """Biblioteca: aulas salvas em algum destino, com a chave (para abrir no Obsidian ou salvar de novo), a
    organização, a trilha e a revisão (lida das notas do cofre), e o catálogo de cursos."""
    cfg = store.load_config()
    review = {}
    if cfg["destinations"] != "notion" and cfg["obsidian_vault"]:
        try:
            on = cfg["obsidian_review"]  # desligadas: só o status; next-review antigo não cobra revisão na Biblioteca
            review = {l["lid"]: {"next": str(l["next"] or "") if on else "", "stage": str(l["stage"] or "") if on else "",
                                 "status": l["status"]} for l in area._lessons(obsidian.folders(cfg)[1]) if l["lid"]}
        except (AppError, OSError):
            pass
    items = []
    for k, v in store.history().items():
        if not (v.get("url") or (v.get("obsidian") or {}).get("status") == "ok"):
            continue
        cls = _classified(v)
        it = {**{x: y for x, y in v.items() if x not in ("block_ids", "spec")}, "key": k, "classification": cls,
              "crumbs": catalog.breadcrumb(cls), "review": review.get(v.get("lumen_id"))}
        if isinstance(it.get("obsidian"), dict):
            it["obsidian"] = {x: y for x, y in it["obsidian"].items() if x not in ("board_layout", "board_user", "files")}
        items.append(it)
    when = lambda x: x.get("created") or (x.get("obsidian") or {}).get("at") or ""  # noqa: E731
    cat = catalog.load()
    return {"items": sorted(items, key=when, reverse=True), "courses": cat["courses"],
            "categories": catalog.categories(items)}


def _catalog(h):
    """Organização: cursos e módulos do catálogo, temas usados e, com ?notion=1, as páginas de curso do Notion que
    ainda não estão no catálogo (para adotar em vez de criar outra). Sem rede, sem Notion: só o local."""
    q, cfg = h._query(), store.load_config()
    cat = catalog.load()
    out = {"courses": cat["courses"], "categories": catalog.categories(_history()["items"]),
           "last": cat.get("last")}
    if q.get("notion") and store.get_token() and cfg["root_page_id"] and cfg["destinations"] != "obsidian":
        tok = store.get_token()
        linked = {c.get("notion_page_id") for c in cat["courses"]}
        try:
            if q.get("course_id"):  # módulos: subpáginas da página do curso
                c = catalog.course(cat, q["course_id"]) or {}
                mods = {m.get("notion_page_id") for m in c.get("modules") or []}
                out["notion"] = [p for p in notion.list_courses(tok, c["notion_page_id"])
                                 if p["id"] not in mods] if c.get("notion_page_id") else []
            else:
                out["notion"] = [p for p in notion.list_courses(tok, cfg["root_page_id"])
                                 if p["id"] not in linked and p["title"] != notion.NO_COURSE]
            out["root_ok"] = True
        except AppError as e:
            out["notion_error"], out["root_ok"] = f"{e} {e.action}".strip(), False
    return out


def _notion_course(cfg, name, parent=None, preview=None):
    """Página do curso (ou módulo) no Notion: a filha de mesmo nome se houver exatamente uma (adotada como está, sem
    mexer em título, ícone, capa ou conteúdo), senão uma nova — com a capa e o enfeite da prévia aprovada, se houver
    (a mesma imagem, sem gerar outra). Devolve (id ou None, aviso, resultado da capa)."""
    tok = store.get_token()
    parent = parent or cfg["root_page_id"]
    if not (tok and parent and cfg["destinations"] != "obsidian"):
        return None, ("O Notion não está em uso: a capa não foi publicada." if preview else None), None
    try:
        same = [c for c in notion.list_courses(tok, parent) if package.norm(c["title"]) == package.norm(name)]
        if len(same) == 1:
            return same[0]["id"], (f"A página “{same[0]['title']}” já existia no Notion e foi adotada como está; a capa "
                                   "não foi aplicada." if preview else None), {"adopted": True} if preview else None
        made = notion.create_course(tok, parent, name, preview and preview["decor"], preview and preview["png"])
    except AppError as e:
        return None, f"No Notion não foi possível criar a página ({e} {e.action}".strip() + ")", None
    if not preview:
        return made["id"], None, None
    kind = preview["kind"] if made.get("cover_confirmed") else "notion"  # upload falhou: ficou a capa de cor do Notion
    return made["id"], made.get("cover_note"), {"kind": kind, "confirmed": bool(made.get("cover_confirmed"))}


def _rerender(cfg, keep):
    """Reescreve no cofre as notas das aulas escolhidas (sem IA): a trilha do bloco acompanha um curso renomeado."""
    if cfg["destinations"] == "notion" or not cfg["obsidian_vault"]:
        return
    for k, v in store.history().items():
        ob = v.get("obsidian") or {}
        if ob.get("status") != "ok" or not keep(v.get("classification") or {}):
            continue
        try:
            pkg = package.load(v.get("lumen_id") or package.lumen_id(k))
            pkg["classification"] = catalog.classification(pkg.get("classification"))
            out = obsidian.deliver(pkg, cfg, prev=ob, notion=v.get("url"))
            store.remember(k, {"obsidian": {**ob, **out, "status": "ok"}})
        except (AppError, OSError, ValueError, KeyError) as e:
            log.warning("renomear: nota não reescrita (%s)", type(e).__name__)


def _catalog_course(h):
    """Criar (nome e plataforma bastam) ou editar/renomear um curso. Renomear muda pasta, nota do curso, propriedades
    das aulas e o título da página no Notion; o id fica."""
    body, cfg = h._json(), store.load_config()
    uses_ob = cfg["destinations"] != "notion" and bool(cfg["obsidian_vault"])
    note = None
    if body.get("id"):
        kw = {k: body[k] for k in ("name", "platform", "url") if k in body}
        old, new = catalog.update_course(body["id"], **kw)
        if uses_ob:
            area.rename_course(cfg, old, new)
        if old["name"] != new["name"]:
            if new.get("notion_page_id") and store.get_token():
                try:
                    notion.set_title(store.get_token(), new["notion_page_id"], new["name"])
                except AppError as e:
                    note = f"No Notion o título não mudou ({e})."
            _rerender(cfg, lambda c: c.get("course_id") == new["id"])
        return {"course": new, "note": note}
    adopt = notion.page_id(body["notion_page_id"]) if body.get("notion_page_id") else None
    # capa: só a prévia aprovada (conferida antes de criar qualquer coisa); a página adotada fica como está
    preview = _approved(body.get("preview_id"), str(body.get("name") or "").strip()) if body.get("decorate") is True and not adopt else None
    c = catalog.create_course(body.get("name"), body.get("platform"), body.get("url"), adopt)
    cover_out = None
    if not c["notion_page_id"]:
        pid, note, cover_out = _notion_course(cfg, c["name"], preview=preview)
        if pid:
            _, c = catalog.update_course(c["id"], notion_page_id=pid)
    if uses_ob:
        try:
            area.refresh(cfg)  # pasta do curso + nota inicial
        except (AppError, OSError) as e:
            note = " ".join(filter(None, [note, f"No Obsidian a pasta do curso fica para a primeira aula ({e})."]))
    return {"course": c, "note": note, "cover": cover_out}


def _catalog_module(h):
    body, cfg = h._json(), store.load_config()
    uses_ob = cfg["destinations"] != "notion" and bool(cfg["obsidian_vault"])
    c = catalog.course(catalog.load(), body.get("course_id"))
    if not c:
        raise AppError("Curso não encontrado.", "Escolha o curso de novo.")
    note = None
    if body.get("id"):
        kw = {k: body[k] for k in ("name", "order") if k in body}
        old, new = catalog.update_module(c["id"], body["id"], **kw)
        if uses_ob:
            area.rename_module(cfg, c, old, new)
        if old["name"] != new["name"] and new.get("notion_page_id") and store.get_token():
            try:
                notion.set_title(store.get_token(), new["notion_page_id"], new["name"])
            except AppError as e:
                note = f"No Notion o título não mudou ({e})."
        if (old["name"], old.get("order")) != (new["name"], new.get("order")):
            _rerender(cfg, lambda x: x.get("module_id") == new["id"])
        return {"module": new, "note": note}
    m = catalog.create_module(c["id"], body.get("name"), body.get("order"),
                              notion.page_id(body["notion_page_id"]) if body.get("notion_page_id") else None)
    if not m["notion_page_id"] and c.get("notion_page_id"):
        pid, note, _ = _notion_course(cfg, m["name"], parent=c["notion_page_id"])
        if pid:
            _, m = catalog.update_module(c["id"], m["id"], notion_page_id=pid)
    if uses_ob:
        try:
            area.refresh(cfg)
        except (AppError, OSError):
            pass
    return {"module": m, "note": note}


def _organize_preview(h):
    """Para onde a aula vai em cada destino, em palavras (sem rede e sem criar nada)."""
    body, cfg = h._json(), store.load_config()
    cls = catalog.classification(body.get("classification"))
    title = str(body.get("title") or "")[:200]
    root = cfg["root_page_title"] or "Cursos"
    crumbs = catalog.breadcrumb(cls)
    if cls["type"] == "course":
        nt = " › ".join([root, cls["course"]] + ([cls["module"]] if cls.get("module") else []))
    elif cls["type"] == "free":
        nt = (cfg.get("notion_free_page_title") or "Conteúdo gratuito") + (f" › {title}" if title else " › página do material")
    else:
        nt = f"{root} › {notion.NO_COURSE}"
    entry = store.history().get(str(body.get("key") or "")) or {}
    if cls["type"] == "inbox" and entry.get("page_id"):  # não há “a organizar” no Notion: a aula não sai de onde está
        nt = f"{entry.get('course') or 'a página atual'} (continua onde está)"
    ob = " / ".join(["Estudos"] + crumbs[:1] + [x.split(" · Aula")[0] for x in crumbs[1:]])
    path = None
    if cfg["obsidian_vault"]:
        try:
            r, home = obsidian.folders(cfg)
            path = area.lesson_dir(home, cls, title or "Aula").parent.relative_to(r).as_posix()
        except AppError:
            pass
    return {"classification": cls, "crumbs": crumbs, "notion": nt, "obsidian": ob, "obsidian_path": path,
            "notion_ready": cls["type"] != "free" or bool(cfg.get("notion_free_page_id"))}


def _organize(h):
    body = h._json()
    jobs.start("organize", jobs.organize, body, spec=body)
    return job_view()


def _migration(h):
    cfg = store.load_config()
    if h.command == "GET":
        return area.plan_view(cfg) if cfg["obsidian_vault"] else {"lessons": [], "folders": []}
    jobs.start("migrate", jobs.migrate, spec={})
    return job_view()


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


def _drive_client(h):
    path = _pick_one("Escolher o JSON do cliente OAuth (App para computador)", "JSON do cliente", (".json",))
    if not path:
        return gdrive.status()
    if Path(path).stat().st_size > 64_000:
        raise AppError("Este arquivo é grande demais para ser um cliente OAuth.", "Escolha o JSON baixado do Google Cloud.")
    return gdrive.set_client(Path(path).read_bytes())


def _protection_dialog(kind, title):
    script = """import sys, tkinter as t
from tkinter import filedialog as f
r=t.Tk(); r.withdraw(); r.attributes('-topmost', 1)
options=dict(parent=r,title=sys.argv[2])
if sys.argv[1]=='folder': value=f.askdirectory(**options,mustexist=True)
elif sys.argv[1]=='save': value=f.asksaveasfilename(**options,initialfile='Lumen-chave-recuperacao.json',defaultextension='.json')
else: value=f.askopenfilename(**options,filetypes=[('Chave JSON','*.json')])
print(value or '')
r.destroy()
"""
    r = subprocess.run([sys.executable, "-c", script, kind, title], capture_output=True,
                       encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                       creationflags=0x08000000 if os.name == "nt" else 0)
    if r.returncode:
        raise AppError("Não foi possível abrir o seletor do Windows.", "Tente novamente com a janela do Lúmen aberta.")
    return r.stdout.strip()


def _protection_folder(title):
    return _protection_dialog("folder", title)


def _protection_action(h):
    from . import protection_drive
    import keyring
    body = h._json()
    action = body.get("action")
    if action == "attention":
        return protection.attention_details()
    if action == "open-place":
        return protection.open_destination(body.get("place"), body.get("path"))
    if action == "choose":
        folder = _protection_folder("Escolher destino local da Proteção do cérebro")
        return protection.choose_local(folder) if folder else {**protection.view(), "cancelled": True}
    if action == "open":
        os.startfile(str(protection.local_folder()))
    elif action in ("start", "pause"):
        protection.enable(action == "start")
    elif action == "now":
        return protection.backup_now()
    elif action == "drive-enable":
        protection.configure(drive_enabled=bool(body.get("enabled")))
        protection.wake()
    elif action == "prepare-key":
        protection.password(create=True)
    elif action == "export-key":
        selected = _protection_dialog("save", "Guardar chave em lugar separado do backup")
        if selected:
            secret = protection.password(create=True)
            path = Path(selected).resolve()
            c = protection.configuration()
            if any(protection.inside(path, root) for root in (protection.HOME, c["vault"], c["local"]) if root):
                raise AppError("Guarde a chave fora das origens e do backup.", "Prefira outro dispositivo ou um gerenciador de senhas.")
            protection.write(path, {"format": "lumen-recovery-key-1", "set_id": c["set_id"], "password": secret})
            protection.update(key_exported=protection.now())
        else:
            return {"cancelled": True}
    elif action == "import-key":
        path = _protection_dialog("open", "Importar chave de recuperação do Lúmen")
        if path:
            if Path(path).stat().st_size > 4096:
                raise AppError("Arquivo de chave inválido.")
            key = protection.read(path)
            if key.get("format") != "lumen-recovery-key-1" or not re.fullmatch(r"[a-f0-9]{32}", key.get("set_id", "")) or not isinstance(key.get("password"), str) or not 20 <= len(key["password"]) <= 512:
                raise AppError("Arquivo de chave inválido.")
            c = protection.configuration()
            if c["set_id"] == key["set_id"] and (protection.HOME / "repository" / "config").exists():
                protection.snapshots(secret=key["password"])
            keyring.set_password(store.APP, protection.recovery_label(), key["password"])
            if c["set_id"] == key["set_id"] or not c["set_id"]:
                protection.configure(set_id=key["set_id"])
                keyring.set_password(store.APP, "protection-" + key["set_id"], key["password"])
            protection.update(key_imported=True)
        else:
            return {"cancelled": True}
    elif action == "page-titles":
        titles = {}
        token = _need_token()[0]
        for iid in protection.configuration()["roots"]:
            try:
                page = notion.request("GET", "/pages/" + iid, token)
                title = notion._title(page)
                titles[iid] = {"title": title, "accessible": True}
            except AppError as e:
                if getattr(e, "status", None) in (400, 404):
                    try:
                        database = notion.request("GET", "/databases/" + iid, token)
                        titles[iid] = {"title": "".join(t.get("plain_text") or t.get("text", {}).get("content", "") for t in database.get("title", [])) or "Base sem título", "accessible": True}
                        continue
                    except AppError:
                        pass
                titles[iid] = {"title": "Precisamos conferir o acesso a esta página", "accessible": False}
        protection.update(page_titles=titles)
        return {"page_titles": titles}
    elif action == "roots":
        values = body.get("roots", [])
        if not isinstance(values, list) or len(values) > 100:
            raise AppError("Informe até 100 raízes do Notion.")
        roots = list(dict.fromkeys(notion.page_id(x) for x in values if str(x).strip()))
        changed = roots != protection.configuration()["roots"]
        protection.configure(roots=roots)
        if changed:
            protection.status_of("notion", status="pending", message="Vamos conferir as páginas que você escolheu.")
            protection.wake()
    elif action == "versions":
        repo = protection.HOME / "repository"
        location = "Capturas guardadas pelo Lúmen neste Windows"
        if not body.get("external"):
            try:
                local = protection.local_folder() / "repository"
                if (local / "config").is_file():
                    repo = local
                    location = "Pasta de backup escolhida"
            except (AppError, OSError):
                pass  # still offer the application repository, with an explicit location.
        if body.get("external"):
            folder = _protection_folder("Escolher repositório Restic existente (pasta repository)")
            if not folder:
                return {"versions": [], "cancelled": True}
            repo = Path(folder)
            location = "Pasta escolhida para recuperação"
        secret = keyring.get_password(store.APP, protection.recovery_label()) if body.get("external") else None
        return {"versions": protection.snapshots(repo, secret), "repository": str(repo), "location": location}
    elif action == "drive-catalogs":
        return {"catalogs": protection_drive.catalogs()}
    elif action == "rebuild-notion":
        from . import protection_notion
        folder = _protection_folder("Escolher a pasta recuperada que contém a subpasta notion")
        if not folder:
            return {"cancelled": True}
        c = protection.configuration()
        with protection.NOTION_WRITE_LOCK:
            return protection_notion.rebuild(_need_token()[0], folder, c["notion_parent"])
    elif action == "recover":
        folder = _protection_folder("Escolher pasta para criar uma NOVA área de recuperação")
        if not folder:
            return {"cancelled": True}
        secret = keyring.get_password(store.APP, protection.recovery_label()) if body.get("external") else None
        if body.get("drive_id"):
            root, manifest = protection_drive.download_repository(body["drive_id"], folder)
            repo, sid = root / "repository", manifest["snapshot"]
            protection.run_restic(repo, "check", "--read-data", secret=secret)
        else:
            repo = Path(body.get("repository") or protection.HOME / "repository").resolve(strict=True)
            sid = body.get("snapshot", "")
        return protection.restore(repo, sid, folder, secret)
    elif action == "stop":
        protection.stop()
    else:
        raise AppError("Ação de proteção desconhecida.")
    return protection.view()


def _diagnostics(h):
    """O diagnóstico confere o próprio pedido: o endereço em que o servidor escuta e a janela que chamou (User-Agent)."""
    bind, port = h.server.server_address[:2]
    return diagnostics.run_diagnostics({"ua": h.headers.get("User-Agent", ""), "bind": bind, "port": port})


ROUTES = {
    ("GET", "/api/monitor"): lambda h: hardware.monitor_stats(),
    ("POST", "/api/monitor/release-vram"): lambda h: (llm.release_vram(), hardware.monitor_stats())[1],
    ("GET", "/api/diagnostics"): lambda h: _diagnostics(h),
    ("POST", "/api/diagnostics"): lambda h: _diagnostics(h),
    ("GET", "/api/repair"): lambda h: repair.view(),  # o que dá para instalar/reparar agora e o andamento (D187)
    ("POST", "/api/repair"): lambda h: repair.action(h._json()),  # só {action: start, id} vindo de um clique, ou {action: cancel}
    ("GET", "/api/protection"): lambda h: protection.view(),
    ("POST", "/api/protection"): _protection_action,
    ("GET", "/api/state"): lambda h: state(),
    ("GET", "/api/job"): lambda h: job_view(),
    ("GET", "/api/understanding"): lambda h: understanding.get(h._query()["key"]),
    ("POST", "/api/understanding/draft"): _draft,
    ("POST", "/api/understanding/submit"): _submit,
    ("GET", "/api/review"): lambda h: jobs.review(h._query()["key"]),
    ("GET", "/api/widget"): _widget,
    ("POST", "/api/settings"): _settings,
    ("GET", "/api/notion/pages"): lambda h: {"pages": notion.list_pages(_need_token()[0])},
    ("GET", "/api/notion/search"): lambda h: notion.search_pages(_need_token()[0], h._query().get("q", "").strip()[:200],
                                                                 h._query().get("cursor") or None),
    ("GET", "/api/notion/page"): lambda h: notion.page_info(_need_token()[0], h._query().get("ref", "")),
    ("POST", "/api/cover/preview"): _page_preview,
    ("POST", "/api/cover/apply"): _cover_apply,
    ("GET", "/api/courses"): _courses,
    ("POST", "/api/courses"): _new_course,
    ("POST", "/api/decor/preview"): _preview,
    ("POST", "/api/pick"): lambda h: pick_file(h._json().get("kind")),
    ("POST", "/api/captures/add"): lambda h: _captures_add(h._json()),
    ("POST", "/api/upload"): _upload,
    ("POST", "/api/inspect"): lambda h: inspect(h._json()),
    ("POST", "/api/start"): _start,
    ("GET", "/api/screen"): _screen,
    ("GET", "/api/visual"): _visual_file,
    ("GET", "/api/capture"): _capture_thumb,
    ("POST", "/api/finish"): _finish,
    ("POST", "/api/cancel"): lambda h: (jobs.cancel(), job_view())[1],
    ("POST", "/api/download"): _download,
    ("POST", "/api/clear"): _clear,
    ("GET", "/api/record"): lambda h: record.status(),
    ("GET", "/api/history"): lambda h: _history(),
    ("GET", "/api/catalog"): _catalog,
    ("POST", "/api/catalog/course"): _catalog_course,
    ("POST", "/api/catalog/module"): _catalog_module,
    ("POST", "/api/organize/preview"): _organize_preview,
    ("POST", "/api/organize"): _organize,
    ("GET", "/api/migration"): _migration,
    ("POST", "/api/migration"): _migration,
    ("GET", "/api/reviews"): lambda h: _reviews(),
    ("POST", "/api/deliver"): _deliver,
    ("POST", "/api/open"): _open,
    # Open Notebook (lumen/opennotebook.py): conexão, caderno de destino e o envio da transcrição de uma aula
    ("GET", "/api/opennotebook"): lambda h: opennotebook.view(),
    ("POST", "/api/opennotebook/connect"): lambda h: opennotebook.connect(h._json()),
    ("POST", "/api/opennotebook/disconnect"): lambda h: opennotebook.disconnect(),
    ("POST", "/api/opennotebook/notebook"): lambda h: opennotebook.choose(h._json()),
    ("POST", "/api/opennotebook/send"): lambda h: opennotebook.send(str(h._json().get("key") or "")),
    ("POST", "/api/opennotebook/start"): lambda h: onlocal.start(store.load_config()),  # só a pedido: “Iniciar Open Notebook”
    ("GET", "/api/opennotebook/local"): lambda h: onlocal.status(),
    ("GET", "/api/opennotebook/lesson"): lambda h: opennotebook.status(h._query().get("key", ""), h._query().get("check") == "1"),
    # HyperbookLM (lumen/hyperbooklm.py): conexão, pareamento e o envio manual do título e da transcrição de uma aula
    ("GET", "/api/hyperbooklm"): lambda h: hyperbooklm.view(),
    ("POST", "/api/hyperbooklm/connect"): lambda h: hyperbooklm.connect(h._json()),
    ("POST", "/api/hyperbooklm/pair"): lambda h: hyperbooklm.pair(),
    ("POST", "/api/hyperbooklm/disconnect"): lambda h: hyperbooklm.disconnect(),
    ("POST", "/api/hyperbooklm/send"): lambda h: hyperbooklm.send(str(h._json().get("key") or "")),
    ("GET", "/api/hyperbooklm/lesson"): lambda h: hyperbooklm.status(h._query().get("key", ""), h._query().get("check") == "1"),
    ("POST", "/api/record/start"): lambda h: (record.start(h._json().get("title")), record.status())[1],
    ("POST", "/api/record/stop"): lambda h: record.stop(keep=h._json().get("exit") is True),
    ("POST", "/api/record/reveal"): lambda h: (record.reveal(h._json().get("path")), {})[1],
    ("POST", "/api/record/discard"): lambda h: (record.discard(), record.status())[1],
    ("POST", "/api/record/pause"): lambda h: (record.pause(), record.status())[1],
    ("POST", "/api/record/resume"): lambda h: (record.resume(), record.status())[1],
    ("POST", "/api/record/recover"): lambda h: record.recover(h._json().get("use") is True) or record.status(),
    ("GET", "/api/drive"): lambda h: gdrive.status(),  # a conta do Google Drive da proteção (cópia de segurança)
    ("POST", "/api/drive/client"): _drive_client,
    ("POST", "/api/drive/login"): lambda h: gdrive.login(),
    ("POST", "/api/drive/logout"): lambda h: gdrive.logout(),
    ("GET", "/api/pomodoro"): lambda h: pomodoro.view(),
    ("POST", "/api/pomodoro"): lambda h: (lambda b: pomodoro.act(b.get("action"), b.get("settings")))(h._json()),
}


ROUTES.update(study_api.ROUTES)
from .study import artifacts as study_artifacts
ROUTES.update(study_artifacts.routes())
ROUTES.update(study_voice.ROUTES)
ROUTES.update(study_voice_admin.ROUTES)
ROUTES.update(study_practice.ROUTES)
ROUTES.update(study_call.ROUTES)
ROUTES.update(listening.ROUTES)


def serve(port=0):
    try:
        study_api.migrate_legacy()  # a retirada do Gemini: ajustes antigos voltam à IA local e a chave antiga sai do cofre
    except Exception:  # noqa: BLE001 — a migração nunca impede o app de abrir; a política já vale na leitura dos ajustes
        log.warning("Migração da retirada do Gemini adiada.")
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
