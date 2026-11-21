"""Voice Studio (o app de vozes do estudante, AGPL-3.0) como motor de voz dos Estudos (D46, D53 a D59).

O Lúmen fala com ele só por HTTP e WebSocket no loopback: nada dele é importado nem copiado. Quando a voz é pedida e o
app está fechado, o Lúmen sobe o backend dele sozinho e sem janela (BACKEND, D53), com o mesmo comando, a mesma pasta e
o mesmo ambiente que o próprio app usa, e o desliga depois de um tempo parado. O app do estudante, se for aberto, se
conecta ao mesmo backend.

- status(): nunca levanta e nunca sobe nada; {"running": False} com o app fechado.
- voices(), sample(id), image(id): a galeria (perfis), a referência e a imagem do perfil.
- speak()/synth(): uma frase → WAV ou PCM (POST /v1/audio/speech, que não grava nada no histórico dele), com os
  passos (num_step) do uso; stream(): a mesma fala pelo /ws/tts (16 passos fixos), com cancelamento.
- Escritas nos ajustes dele (nível, motor, instalar e remover modelos, pronúncias, vozes novas): só por write(), que
  só as rotas de ação do Lúmen chamam, cada uma a partir de um clique do estudante (D57). Apagar vozes, apagar o
  histórico dele e desligar a marca d'água continuam proibidos: nenhuma função aqui faz isso."""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque
from pathlib import Path

from . import OWN_ENV, AppError, Cancelled

APP = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "VoiceStudio"
EXE = APP / "VoiceStudio.exe"
USER_DATA = Path(os.environ.get("APPDATA", "")) / "VoiceStudio"       # a pasta do Electron dele
PROJECT = USER_DATA / "runtime" / "project"                            # a cópia do backend que o app prepara
PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"
LUMEN_D = Path(r"D:\Lumen")
STATE_S, GEN_S = 2, 300   # segundos: estado e lista; gerar (o prazo dele, generate_timeout_s, vale mais)
START_S = 240             # subir o backend a frio (o app espera até 180 s mais a carga em PC lento)
SR = 24000                # o PCM do /ws/tts e do formato pcm: 24 kHz, 16 bits, mono
ID = re.compile(r"[\w-]{1,64}")
REPO = re.compile(r"[\w.-]{1,96}/[\w.-]{1,96}")
MARK = "x-omnivoice-backend"   # o cabeçalho que só o backend do Voice Studio põe em toda resposta
CLOSED = ("O Voice Studio está fechado.", "Abrir o Voice Studio")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
log = logging.getLogger("lumen")

# Os pacotes da tela "Pacotes de modelos" do Voice Studio 0.5.7 (a lista fica na tela dele; a API não a entrega).
# Só os que /models diz que existem e servem neste PC aparecem.
PACKS = {
    "fast": ["k2-fsa/OmniVoice", "Systran/faster-whisper-base", "csukuangfj/sherpa-onnx-whisper-tiny"],
    "balanced": ["k2-fsa/OmniVoice", "deepdml/faster-whisper-large-v3-turbo-ct2", "csukuangfj/sherpa-onnx-whisper-tiny",
                 "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"],
    "quality": ["k2-fsa/OmniVoice", "Systran/faster-whisper-large-v3", "csukuangfj/sherpa-onnx-whisper-tiny",
                "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", "facebook/nllb-200-distilled-600M"],
}
PACKS["max"] = PACKS["quality"]
TIERS = ("fast", "balanced", "quality", "max")
MIN_FREE_GB = 10  # o mínimo do próprio Voice Studio (min_free_gb): nenhum download deixa o disco abaixo disto


def _port():
    """A porta do backend vem da configuração do próprio app (ports.backend); 3900 é a de fábrica."""
    try:
        return int(json.loads((APP / "resources" / "config" / "app.json").read_text("utf-8"))["ports"]["backend"])
    except (OSError, ValueError, KeyError, TypeError):
        return 3900


def url():
    return os.environ.get("LUMEN_VOICESTUDIO_URL") or f"http://127.0.0.1:{_port()}"


def installed():
    return EXE.exists() or bool(os.environ.get("LUMEN_VOICESTUDIO_URL"))


def _error(e):
    """A mensagem que o Voice Studio deu (formato da OpenAI ou do FastAPI), curta."""
    try:
        body = json.loads(e.read() or b"{}")
        msg = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("detail")
    except (ValueError, AttributeError, OSError):
        msg = None
    return str(msg or f"HTTP {e.code}")[:240]


def _req(path, body=None, timeout=STATE_S, raw=False, method=None, data=None, headers=None):
    if data is None and body is not None:
        data, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
    req = urllib.request.Request(url() + path, data=data, method=method or ("GET" if data is None else "POST"),
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = r.read()
    except urllib.error.HTTPError as e:
        with e:
            raise AppError("O Voice Studio recusou o pedido.", _error(e)) from None
    except urllib.error.URLError:
        # não conectou: no Windows, a porta fechada do loopback também chega aqui como tempo esgotado (≈ 2 s)
        raise AppError(*CLOSED) from None
    except TimeoutError:  # conectou, mas a resposta não veio no prazo
        raise AppError("O Voice Studio demorou demais para responder.", "Tente de novo.") from None
    except OSError:
        raise AppError(*CLOSED) from None
    return out if raw else json.loads(out or b"{}")


def write(method, path, body=None, timeout=30, data=None, headers=None):
    """Toda escrita nos ajustes, modelos, pronúncias ou vozes do Voice Studio passa por aqui (D57): só as rotas de ação
    do Lúmen a chamam, a partir de um clique do estudante, e cada uma fica no log."""
    log.info("voicestudio: escrita pedida pelo estudante: %s %s", method, path.split("?")[0])
    return _req(path, body, timeout=timeout, method=method, data=data, headers=headers)


def health():
    """("ok" | "starting" | "other" | "closed", corpo). Só o backend do Voice Studio responde com o cabeçalho
    x-omnivoice-backend; durante a subida, o /health dele dá 503 com o passo atual."""
    try:
        with urllib.request.urlopen(url() + "/health", timeout=STATE_S) as r:
            marked, data = r.headers.get(MARK), r.read()
    except urllib.error.HTTPError as e:
        with e:
            marked, data = e.headers.get(MARK), e.read()
    except (OSError, ValueError):
        return "closed", {}
    if not marked:
        return "other", {}
    try:
        body = json.loads(data or b"{}")
    except ValueError:
        body = {}
    return ("ok" if body.get("status") == "ok" else "starting"), body


def status():
    """Estado para a tela: aberto ou fechado (e quem o abriu: o app ou o Lúmen), subindo, carregando o modelo (com o
    progresso), versão, GPU e motor ativo. Nunca sobe o backend."""
    out = {"installed": installed(), "running": False, "owner": None, "backend": dict(BACKEND.state),
           "app_open": app_open()}
    try:
        info = _req("/system/info")
    except AppError as e:
        if str(e) != CLOSED[0]:  # algo respondeu: o Voice Studio subindo (503) ou outro programa na porta
            out["foreign"] = health()[0] == "other"
        return out
    out.update(running=True, version=info.get("app_version"), gpu=info.get("gpu_name"), device=info.get("device"),
               timeout=info.get("generate_timeout_s") or GEN_S, owner="lumen" if BACKEND.ours() else "app")
    _limits["gen"] = float(out["timeout"])
    try:
        m = _req("/model/status")
        out["model"] = {"loaded": bool(m.get("loaded")), "loading": bool(m.get("loading")),
                        "progress": m.get("progress"), "stage": m.get("sub_stage") or m.get("detail"),
                        "error": m.get("error")}
        out["engine"] = engine()
    except AppError:
        pass  # o app respondeu o principal; o resto aparece na próxima consulta
    return out


_engine = {"at": -1e9, "value": None}
_limits = {"gen": GEN_S}  # o prazo de gerar do próprio Voice Studio (generate_timeout_s), visto no último status()


def engine():
    """O motor ativo dele. A rota leva cerca de 2 s (lista 600 idiomas) e só muda quando o estudante troca de motor:
    fica guardada por 10 min."""
    if time.monotonic() - _engine["at"] > 600:
        eng = _req("/engines/tts", timeout=8)
        active = next((b for b in eng.get("backends") or [] if b.get("id") == eng.get("active")), {})
        _engine.update(at=time.monotonic(), value={
            "id": eng.get("active"), "name": active.get("display_name") or eng.get("active"),
            "cloning": bool(active.get("supports_cloning")), "instruct": active.get("instruct_vocabulary") or "freeform",
            "max_ref_s": active.get("max_ref_seconds")})
    return _engine["value"]


def voices():
    """Os perfis do estudante (clonados e criados), só os campos que a tela usa."""
    rows = _req("/profiles")
    return [{"id": p["id"], "name": str(p.get("name") or p["id"])[:80], "kind": p.get("kind") or "clone",
             "language": p.get("language") or "Auto", "image": bool(p.get("image_url")),
             "demo": bool(p.get("is_demo")), "seed": p.get("seed")}
            for p in rows if isinstance(p, dict) and ID.fullmatch(str(p.get("id") or ""))]


def _id(voice):
    if not isinstance(voice, str) or not ID.fullmatch(voice):
        raise AppError("Voz inválida.", "Escolha uma voz da lista.")
    return voice


def sample(voice):
    """O áudio de referência do perfil (WAV), para ouvir na galeria."""
    return _req(f"/profiles/{_id(voice)}/audio", timeout=10, raw=True)


def image(voice):
    try:
        return _req(f"/profiles/{_id(voice)}/image", timeout=5, raw=True)
    except AppError:
        return None


# --- pronúncias (D58) ---------------------------------------------------------------------------------------------------
# O dicionário do Voice Studio só vale no /generate dele: o /v1/audio/speech e o /ws/tts não o aplicam (conferido no
# código da 0.5.7). O Lúmen pede ao próprio Voice Studio o texto já trocado (/pronunciation/test: só leitura, sem
# modelo), então a regra é exatamente a dele. Sem nenhuma entrada, não há pedido a mais.

_pron = {"at": -1e9, "n": 0}


def pronunciations():
    rows = _req("/pronunciation", timeout=5)
    _pron.update(at=time.monotonic(), n=sum(1 for r in rows if r.get("enabled")))
    return rows


def pronounce(text, language=None):
    """O texto com as pronúncias do estudante aplicadas (o mesmo que o /generate dele faria)."""
    try:
        if time.monotonic() - _pron["at"] > 30:
            pronunciations()
        if not _pron["n"]:
            return text
        return str(_req("/pronunciation/test", {"text": text, "language": language or None}, timeout=5)
                   .get("substituted") or text)
    except AppError:
        return text  # sem o dicionário, fala o texto como está


def _body(text, voice, speed, language, seed, style, steps=None):
    body = {"model": "omnivoice", "input": pronounce(str(text)[:4096], language), "voice": _id(voice),
            "speed": float(speed)}
    if language:
        body["language"] = language
    if seed is not None:
        body["seed"] = int(seed)
    if style:
        body["instruct"] = style
    if steps:
        body["num_step"] = int(steps)
    return body


def synth(text, voice, speed=1.0, language="pt", seed=None, style="", steps=None, fmt="wav", timeout=None):
    """Uma frase → bytes: WAV, ou PCM16 de 24 kHz (fmt="pcm"). `steps`: os passos (num_step) do pedido, sem mexer no
    nível global do Voice Studio (D56). O prazo é o do próprio Voice Studio, com folga para a carga."""
    with BACKEND.use():
        return _req("/v1/audio/speech", {**_body(text, voice, speed, language, seed, style, steps), "response_format": fmt},
                    timeout=timeout or max(_limits["gen"], GEN_S) + 60, raw=True)


def speak(text, out, voice, speed=1.0, language="pt", seed=None, style="", check=lambda: None, timeout=None, steps=None):
    """Uma frase → `out` (WAV mono). Devolve a duração em segundos. Cancelar vale entre frases: o pedido HTTP em
    andamento termina (uma frase leva poucos segundos)."""
    check()
    data = synth(text, voice, speed, language, seed, style, steps, "wav", timeout)
    check()
    tmp = Path(out).with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(out)
    import wave
    with wave.open(str(out)) as w:
        return w.getnframes() / w.getframerate()


def stream(text, voice, speed=1.0, language="pt", seed=None, style="", cancel=None, stats=None):
    """Gerador de pedaços de PCM16 (24 kHz, mono) pelo /ws/tts (16 passos, fixos nele). `cancel` (threading.Event)
    fecha a conexão no próximo pedaço; `stats` (dict) recebe o "done" dele (ttfa_ms, rtf, duration_s)."""
    import websocket  # websocket-client (requirements.txt)
    cancel = cancel or threading.Event()
    body = _body(text, voice, speed, language, seed, style)
    req = {"text": body["input"], "voice": body["voice"], "speed": body["speed"]}
    for k in ("language", "instruct"):
        if k in body:
            req[k] = body[k]
    try:
        ws = websocket.create_connection(url().replace("http", "ws", 1) + "/ws/tts", timeout=GEN_S,
                                         suppress_origin=True)
    except (OSError, websocket.WebSocketException):
        raise AppError(*CLOSED) from None
    try:
        with BACKEND.use():
            ws.send(json.dumps(req))
            while True:
                if cancel.is_set():
                    raise Cancelled
                op, data = ws.recv_data()
                if op == websocket.ABNF.OPCODE_BINARY:
                    yield data
                    continue
                if op == websocket.ABNF.OPCODE_CLOSE:
                    raise AppError("O Voice Studio parou no meio.", "Tente de novo.")
                try:
                    msg = json.loads(data or b"{}")
                except ValueError:
                    continue  # algo que não é o protocolo dele: ignora
                if msg.get("type") == "done":
                    if stats is not None:
                        stats.update(msg)
                    return
                if msg.get("type") == "error":
                    raise AppError("O Voice Studio recusou o pedido.", str(msg.get("detail") or "")[:240])
    except (OSError, websocket.WebSocketException):
        raise AppError("O Voice Studio parou no meio.", "Tente de novo.") from None
    finally:
        ws.close()


def open_app(minimized=False):
    """Abre o app do estudante (não fecha nem reinicia nunca)."""
    if not EXE.exists():
        raise AppError("O Voice Studio não está instalado neste PC.", "Instale o Voice Studio ou escolha outro motor.")
    if minimized and os.name == "nt":  # SW_SHOWMINNOACTIVE: abre minimizado, sem roubar o foco
        import ctypes
        ctypes.windll.shell32.ShellExecuteW(None, "open", str(EXE), None, None, 7)
        return
    os.startfile(str(EXE))  # noqa: S606 — o executável fixo do app, nunca um caminho vindo da página


_app = {"at": -1e9, "open": False}


def app_open():
    """O VoiceStudio.exe (a janela do app) está aberto? Guardado por 10 s (tasklist leva ≈ 0,1 s)."""
    if os.name != "nt":
        return False
    if time.monotonic() - _app["at"] > 10:
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq VoiceStudio.exe", "/NH"], capture_output=True, text=True,
                                 errors="replace", timeout=10, creationflags=NO_WINDOW).stdout or ""
        except (OSError, subprocess.SubprocessError):
            out = ""
        _app.update(at=time.monotonic(), open="voicestudio.exe" in out.lower())
    return _app["open"]


# --- o backend sem janela (D53 a D55) -----------------------------------------------------------------------------------

def _version(path):
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"', path.read_text("utf-8"), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def launch_problem():
    """Por que o Lúmen não pode subir o backend sozinho agora ("" quando pode). Uma cópia velha (o app foi atualizado e
    ainda não foi aberto) ou uma pasta de dados escolhida no app pedem o próprio app."""
    if not PYTHON.exists() or not (PROJECT / ".runtime-ready").exists():
        return "setup"
    if _version(PROJECT / "pyproject.toml") != _version(APP / "resources" / "pyproject.toml"):
        return "update"
    custom = [USER_DATA / "runtime-location.json"] + [
        Path(os.environ.get(v, "")) / "com.debpalash.omnivoice-studio" / "config.json" for v in ("LOCALAPPDATA", "APPDATA")]
    if any(p.exists() for p in custom):
        return "custom"  # o app passa ao backend uma pasta de dados ou de modelos escolhida: só ele sabe montar isso
    return ""


def _env(port):
    """O ambiente que o próprio app passa ao backend (out/main/index.js, childEnv), sem a telemetria dele e sem trocar
    as pastas de modelos (HF_HOME e OMNIVOICE_CACHE_DIR ficam como o estudante deixou). O TEMP vai para o D:."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHOME", "PYTHONPATH") and k not in OWN_ENV and not k.startswith("POSTHOG_")}
    env.update(PYTHONUNBUFFERED="1", PYTHONUTF8="1", OMNIVOICE_DESKTOP_CONTAINED="1", OMNIVOICE_PORT=str(port),
               TORCHDYNAMO_DISABLE="1", HF_HUB_DISABLE_SYMLINKS="1", HF_HUB_DISABLE_SYMLINKS_WARNING="1",
               FOR_DISABLE_CONSOLE_CTRL_HANDLER="1")
    uv = APP / "resources" / "tools" / "uv.exe"
    if uv.exists():
        env["OMNIVOICE_BUNDLED_UV"] = str(uv)
    if LUMEN_D.is_dir():
        tmp = LUMEN_D / "cache" / "voicestudio-tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        env.update(TEMP=str(tmp), TMP=str(tmp))
    return env


def _command(port):
    """(argv, pasta) do backend: o mesmo `python -m uvicorn main:app --app-dir backend` que o app roda."""
    return ([str(PYTHON), "-m", "uvicorn", "main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port",
             str(port)], str(PROJECT))


def _logger():
    """O que o backend imprime vai para D:\\Lumen\\logs\\voicestudio.log (2 MB, mais uma cópia antiga)."""
    lg = logging.getLogger("lumen.voicestudio.backend")
    if not lg.handlers:
        from logging.handlers import RotatingFileHandler
        from . import store
        folder = LUMEN_D / "logs" if LUMEN_D.is_dir() and not os.environ.get("LUMEN_DATA") else store.DATA / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(folder / "voicestudio.log", maxBytes=2_000_000, backupCount=1, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        lg.propagate = False
    return lg


class Backend:
    """O backend que o próprio Lúmen sobe, sem janela, quando a voz é pedida com o app fechado (D53).

    Ele é dono só do que subiu: se a porta já responde como Voice Studio (o app aberto, ou outro Lúmen), só usa. A
    entrada padrão do processo é um pipe que o Lúmen segura: se o Lúmen fechar ou cair, o backend sai sozinho
    (OMNIVOICE_DESKTOP_CONTAINED, o mesmo vigia do app). Desliga depois de `idle_s` sem uso, a menos que o app esteja
    aberto. A trava em DATA impede que duas instâncias do Lúmen subam dois backends."""

    def __init__(self):
        self.proc, self.lock_fh, self.used, self.busy = None, None, 0.0, 0
        self.idle_s, self.mutex, self.tail = 15 * 60, threading.Lock(), deque(maxlen=30)
        self.state, self._watch, self._warm, self.failed, self.failed_at = {"phase": "off"}, None, None, None, 0.0

    def ours(self):
        return self.proc is not None and self.proc.poll() is None

    def use(self):
        """Conta um pedido em andamento (o desligamento por uso parado espera ele terminar)."""
        b = self

        class _Use:
            def __enter__(self):
                b.busy += 1
                b.used = time.monotonic()

            def __exit__(self, *exc):
                b.busy -= 1
                b.used = time.monotonic()
        return _Use()

    def _lock(self):
        from . import store
        store.DATA.mkdir(parents=True, exist_ok=True)
        fh = open(store.DATA / "voicestudio.lock", "a+b")  # noqa: SIM115 — fica aberto enquanto o backend é nosso
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fh.close()
            return False
        self.lock_fh = fh
        return True

    def _unlock(self):
        fh, self.lock_fh = self.lock_fh, None
        if fh:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            fh.close()

    def _spawn(self):
        """Sobe o backend (ou abre o app, se só ele pode). Sem trava (outro Lúmen subindo), só espera."""
        with self.mutex:
            if self.ours():
                return
            problem = launch_problem()
            if problem == "setup":
                raise AppError("O Voice Studio ainda não terminou de instalar.", "Termine a instalação no Voice Studio.")
            if problem:
                why = ("O Voice Studio foi atualizado: abrindo o app uma vez, minimizado, para ele preparar a versão nova."
                       if problem == "update" else "O Voice Studio usa uma pasta escolhida no app: abrindo o app, minimizado.")
                self.state = {"phase": "starting", "label": why}
                log.info("voicestudio: %s", why)
                open_app(minimized=True)
                return
            if not self._lock():
                return
            self.used = time.monotonic()  # o vigia de uso parado não conta a subida como tempo parado
            port = urllib.parse.urlsplit(url()).port or _port()
            argv, cwd = _command(port)
            try:
                self.proc = subprocess.Popen(argv, cwd=cwd, env=_env(port), stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            except OSError as e:
                self._unlock()
                raise AppError("O Voice Studio não abriu.", str(e)[:200]) from None
            log.info("voicestudio: backend sem janela iniciado (pid %s)", self.proc.pid)
            self.tail.clear()
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True, name="Lumen VS log").start()
            if not (self._watch and self._watch.is_alive()):
                self._watch = threading.Thread(target=self._idle, daemon=True, name="Lumen VS idle")
                self._watch.start()

    def _pump(self, proc):
        lg = _logger()
        for line in iter(proc.stdout.readline, b""):  # esvazia o pipe: um pipe cheio travaria o backend
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                self.tail.append(text)
                lg.info(text)
        lg.info("--- backend encerrado (código %s)", proc.wait())

    def _progress(self):
        try:
            snap = _req("/startup/progress")
            steps = snap.get("steps") or []
            return round(100 * sum(1 for s in steps if s.get("state") == "done") / max(len(steps), 1))
        except AppError:
            return None

    def _fail(self, message, action):
        self.failed, self.failed_at = AppError(message, action), time.monotonic()
        self.state = {"phase": "failed", "error": message, "action": action}
        raise self.failed

    def ensure(self, check=lambda: None, timeout=START_S, start=True):
        """Garante o backend respondendo: usa o que já está aberto ou (com `start`) sobe o dele, sem janela. Devolve
        quem é o dono ("app" ou "lumen"). Depois de uma falha, espera 60 s antes de tentar subir de novo."""
        h, body = health()
        if h == "other":
            raise AppError(f"A porta {urllib.parse.urlsplit(url()).port} está ocupada por outro programa.",
                           "Feche o programa que usa essa porta ou mude a porta do Voice Studio no app dele.")
        if h == "closed":
            if not start:
                raise AppError(*CLOSED)
            if self.failed and time.monotonic() - self.failed_at < 60 and not self.ours():
                raise self.failed
            if app_open():  # o app está abrindo (ele copia o backend para runtime\project antes de subir): só espera
                self.state = {"phase": "starting", "label": "O Voice Studio está abrindo…"}
            else:
                self.state = {"phase": "starting", "pct": 0, "label": "Ligando a voz…"}
                try:
                    self._spawn()
                except AppError as e:
                    self._fail(str(e), e.action)
        with self.use():  # subindo conta como "em uso": o vigia não desliga no meio da subida
            self._wait_ok(h, body, check, timeout)
        self.used, self.failed = time.monotonic(), None
        self.state = {"phase": "ready"}
        return "lumen" if self.ours() else "app"

    def _wait_ok(self, h, body, check, timeout):
        end = time.monotonic() + timeout
        while h != "ok":
            check()
            if self.proc is not None and self.proc.poll() is not None:
                last = next((x for x in reversed(self.tail) if x.strip()), "")
                with self.mutex:
                    self.proc = None
                    self._unlock()
                if health()[0] == "ok":  # outro (o app) ficou com a porta no mesmo instante: usa o dele
                    break
                self._fail("O Voice Studio não conseguiu ligar.", last[:200] or "Abra o Voice Studio para ver o motivo.")
            if time.monotonic() > end:
                self._fail("O Voice Studio demorou demais para ligar.", "Abra o Voice Studio para ver o motivo.")
            if h == "starting":
                self.state = {"phase": "starting", "pct": self._progress(), "label": body.get("label") or "Ligando a voz…"}
            time.sleep(0.5)
            h, body = health()
            if h == "other":
                self._fail("Outro programa respondeu na porta do Voice Studio.", "Feche o programa que usa essa porta.")

    def warm(self, check=lambda: None, start=True):
        """Backend no ar e modelo carregado antes da 1ª frase (D54): a carga a frio corre junto com o texto."""
        self.ensure(check, start=start)
        with self.use():  # carregando conta como "em uso"
            m = _req("/model/status")
            if not m.get("loaded"):
                if not m.get("loading"):
                    _req("/setup/warmup", {}, timeout=10)  # carrega em segundo plano; não muda ajuste nenhum
                end = time.monotonic() + START_S
                while not m.get("loaded"):
                    check()
                    if m.get("error"):
                        self._fail("O modelo de voz não carregou.", str(m["error"])[:200])
                    if time.monotonic() > end:
                        self._fail("O modelo de voz demorou demais para carregar.", "Tente de novo ou abra o Voice Studio.")
                    p = m.get("progress")
                    self.state = {"phase": "loading", "pct": round(p * 100) if isinstance(p, (int, float)) and p <= 1 else None,
                                  "label": "Carregando o modelo de voz…"}
                    time.sleep(0.5)
                    m = _req("/model/status")
        self.state = {"phase": "ready", "loaded": True}

    def warm_async(self, start=True):
        """warm() numa thread (uma por vez); a tela lê `state`."""
        with self.mutex:
            if self._warm and self._warm.is_alive():
                return self._warm

            def run():
                try:
                    self.warm(start=start)
                except AppError as e:
                    if str(e) != CLOSED[0]:  # fechado sem "ligar sozinho" não é falha: o who() decide
                        self.state = {"phase": "failed", "error": str(e), "action": e.action}
            self._warm = threading.Thread(target=run, daemon=True, name="Lumen VS warm")
            self._warm.start()
            return self._warm

    def _idle(self):
        while True:
            time.sleep(20)
            if not self.ours():
                if self.proc is not None:
                    with self.mutex:
                        self.proc = None
                        self._unlock()
                        self.state = {"phase": "off"}
                continue
            if self.busy or time.monotonic() - self.used < self.idle_s or app_open():
                continue  # com o app aberto, o estudante pode estar usando
            log.info("voicestudio: desligando o backend sem janela (%d min sem uso)", self.idle_s // 60)
            self.stop()

    def stop(self):
        """Desliga só o backend que o Lúmen subiu: fecha o pipe (ele sai sozinho) e, se não sair em 10 s, encerra a
        árvore dele (só processos que o Lúmen criou)."""
        with self.mutex:
            p, self.proc = self.proc, None
            if p and p.poll() is None:
                try:
                    p.stdin.close()
                except OSError:
                    pass
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=20,
                                   creationflags=NO_WINDOW)
            self._unlock()
            self.state = {"phase": "off"}


BACKEND = Backend()


# --- a placa ---------------------------------------------------------------------------------------------------------

def _loaded_ids():
    return {m.get("id") for m in _req("/model/loaded").get("models") or []}


def loaded():
    """Os modelos carregados (com a VRAM de cada um) e a memória livre do PC, como o Voice Studio vê."""
    return _req("/model/loaded")


def mark():
    """Antes de uma tarefa longa: o que já estava carregado e quantas gerações o estudante já fez (o histórico dele só
    conta as dele: o /v1/audio/speech não entra)."""
    try:
        ids = _loaded_ids()
        return {"loaded": "tts" in ids, "ids": ids, "takes": _req("/stats/usage").get("takes"), "t": time.monotonic()}
    except AppError:
        return None


def unload_if_ours(before, min_seconds=120):
    """Depois de uma tarefa longa: descarrega só o que o Lúmen carregou (o OmniVoice, "tts", e o Whisper dele, "asr",
    que não estavam carregados antes), e só se o estudante não gerou nada no Voice Studio enquanto isso. Senão, o
    próprio app descarrega depois de ficar parado (idle_timeout_seconds, 15 min). Com o backend sem janela do Lúmen, o
    desligamento por uso parado já libera tudo."""
    if not before or before["loaded"] or time.monotonic() - before["t"] < min_seconds:
        return False
    try:
        if _req("/stats/usage").get("takes") != before["takes"]:
            return False
        ids = [i for i in ("tts", "asr") if i in _loaded_ids() and i not in before.get("ids", set())]
        for mid in ids:
            _req(f"/model/unload/{mid}", {}, timeout=30)
        return bool(ids)
    except AppError:
        return False


# --- modelos, pacotes e motores (D55, D57) -----------------------------------------------------------------------------

def catalog():
    """Tudo o que a seção "Modelos de voz" mostra, só com leituras: os modelos (tamanho, instalado, licença), os
    pacotes de cada nível, o nível atual, os downloads em andamento, a pasta e o disco."""
    models = _req("/models", timeout=15)
    rows = {m["repo_id"]: m for m in models.get("models") or [] if isinstance(m, dict) and m.get("repo_id")}
    prof = _req("/api/settings/performance-profile", timeout=10)
    packs = {}
    for tier in TIERS:
        ms = [rows[r] for r in PACKS[tier] if r in rows and rows[r].get("supported", True) is not False]
        missing = [m for m in ms if not m.get("installed")]
        packs[tier] = {"models": [m["repo_id"] for m in ms], "missing": [m["repo_id"] for m in missing],
                       "download_gb": round(sum(m.get("size_gb") or 0 for m in missing), 2),
                       "total_gb": round(sum(m.get("size_gb") or 0 for m in ms), 2)}
    return {"models": [_model_row(m) for m in rows.values()], "packs": packs, "tier": prof.get("global"),
            "resolved": (prof.get("plan") or {}).get("resolved"), "effective": prof.get("effective") or {},
            "selections": prof.get("selections") or {}, "jobs": _req("/models/install/status").get("jobs") or [],
            "disk_free_gb": models.get("disk_free_gb"), "models_dir": _req("/api/settings/storage/models-dir")}


def _model_row(m):
    lic = m.get("license_info") if isinstance(m.get("license_info"), dict) else {}
    full = str(lic.get("license") or "")  # ex.: "CC-BY-NC (version unspecified); Higgs Audio 2; Meta Llama 3", "mit"
    name = full.split(";")[0].split("(")[0].strip()[:40]
    return {"repo_id": m["repo_id"], "label": str(m.get("label") or m["repo_id"])[:120], "role": m.get("role"),
            "size_gb": m.get("size_gb"), "installed": bool(m.get("installed")), "required": bool(m.get("required")),
            "disk_bytes": m.get("size_on_disk_bytes"),
            "license": "" if name.upper() in ("", "NOASSERTION") else name,
            "personal": "nc" in re.split(r"[^a-z]+", full.lower()),  # CC-BY-NC: pesos só para uso pessoal
            "curated": bool(m.get("curated") or m.get("required"))}


def _repo(repo):
    if not isinstance(repo, str) or not REPO.fullmatch(repo):
        raise AppError("Modelo inválido.")
    return repo


def engines(family):
    """Os motores de uma família ("tts" ou "asr"), com o motivo dos indisponíveis e se clonam."""
    eng = _req(f"/engines/{'tts' if family == 'tts' else 'asr'}", timeout=10)
    return {"active": eng.get("active"), "model": eng.get("active_model"), "engines": [{
        "id": b["id"], "name": str(b.get("display_name") or b["id"])[:120], "available": bool(b.get("available")),
        "reason": str(b.get("reason") or "")[:200] or None, "cloning": bool(b.get("supports_cloning")),
        "one_click": bool(b.get("one_click_install")), "min_vram_gb": b.get("min_vram_gb"),
        "languages": len(b.get("supported_language_names") or []) or None,
        "portuguese": _speaks_pt(b)} for b in eng.get("backends") or [] if isinstance(b, dict) and b.get("id")]}


def _speaks_pt(b):
    names = [str(x).lower() for x in b.get("supported_language_names") or []]
    if not names:
        return None  # o motor não declara: a tela não afirma nada
    return any("portug" in n for n in names)


def disk_free_gb(path):
    import shutil
    try:
        p = Path(path)
        return shutil.disk_usage(p.anchor if p.anchor else p).free / 1e9
    except OSError:
        return None


def models_dir():
    return _req("/api/settings/storage/models-dir")


def storage():
    return _req("/api/settings/storage", timeout=30)


# --- vozes por descrição (D58) ------------------------------------------------------------------------------------------

def describe(text):
    """Uma descrição em texto → as tags de estilo do OmniVoice (só leitura, sem modelo)."""
    return _req("/design/describe", {"description": str(text)[:2000]}, timeout=10)


def _form(fields):
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in fields.items()]
    return ("".join(parts) + f"--{boundary}--\r\n").encode("utf-8"), {
        "Content-Type": f"multipart/form-data; boundary={boundary}"}


def create_design_voice(name, instruct, attrs, language="pt", seed=None):
    """Cria uma voz por descrição no Voice Studio, com o nome marcado "(Lúmen)". Só a partir do clique do estudante."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:60] or "Personagem"
    if not name.endswith("(Lúmen)"):
        name = f"{name} (Lúmen)"
    data, headers = _form({"name": name, "kind": "design", "instruct": str(instruct or "")[:400], "language": language or "Auto",
                           "vd_states": json.dumps(attrs if isinstance(attrs, dict) else {}), "seed": str(int(seed or 42))})
    return write("POST", "/profiles", data=data, headers=headers, timeout=120)


def _main():  # pragma: no cover — uso: python -m lumen.voicestudio up|down (testes manuais)
    if sys.argv[1:] == ["up"]:
        print(BACKEND.ensure())
        input("Enter desliga o backend…")
        BACKEND.stop()


if __name__ == "__main__":  # pragma: no cover
    _main()
