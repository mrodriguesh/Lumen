"""Diagnóstico do sistema do Lúmen: tudo o que o app usa, conferido só com leituras.

Cada verificação diz se o recurso é obrigatório ou opcional, se está ligado, e separa cinco etapas: instalado,
configurado, autenticado, alcançável e utilizável (True, False ou None = não se aplica / não conferido). O estado final
é um só: ok | missing | misconfigured | unreachable | disabled | unverified | blocked.

Regras (docs/DECISOES.md D186):
- Só leituras com prazo curto: nada é instalado, baixado, iniciado, parado, gravado, enviado ou reconfigurado; nenhum
  áudio é gravado e nenhuma credencial é alterada (a renovação do Google é feita aqui sem gravar nada no cofre).
- Um pacote instalado ou um processo aberto não prova que a integração funciona: “utilizável” exige a sonda mais funda
  que é segura (a API responder com a credencial, o modelo ou o arquivo ser lido). O que não pode ser provado sem usar de
  verdade fica dito em `limit` e, quando não há prova nenhuma, o estado é “unverified”.
- Nenhum segredo sai daqui: os valores conhecidos (token do Notion, autorização do Drive, senha do Open Notebook,
  código do HyperbookLM, chave da proteção) são trocados por •••• em todo o resultado.
- “100% operacional” só quando todas as verificações obrigatórias rodaram e passaram. Cobertura (o que rodou) e
  prontidão (o que passou) são contadas à parte; opcional desligado é configuração opcional, nunca “verificado”.

Esquema (compatível com a tela antiga): {timestamp, score, summary{total, ok, warn, error, info, state, message,
coverage, readiness, operational, states}, categories[{id, title, icon, status, items[{name, status, detail, action?,
required, enabled, state, stages, next, limit, ms}]}]}."""
import concurrent.futures
import datetime
import importlib
import importlib.metadata
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import store

log = logging.getLogger("lumen.diagnostics")
ROOT = Path(__file__).resolve().parent.parent
DEADLINE_S = 30          # o diagnóstico inteiro; o que não terminou vira “não verificado (tempo esgotado)”
LOCAL_S, NET_S = 3, 6    # prazos das sondas: serviços deste PC e serviços na internet
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STAGES = ("installed", "configured", "authenticated", "reachable", "usable")
STATE_LABEL = {"ok": "OK", "missing": "Faltando", "misconfigured": "Configuração incorreta", "unreachable": "Inacessível",
               "disabled": "Desativado", "unverified": "Não verificado", "blocked": "Bloqueado"}
WEBVIEW2_CLIENT = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CATEGORIES = [
    ("python", "Aplicativo e ambiente", "cpu"),
    ("desktop", "Janela e serviços locais", "screen"),
    ("audio", "Áudio e captura", "wave"),
    ("whisper", "Transcrição (Whisper e Parakeet)", "wave"),
    ("ollama", "IA local (Ollama)", "cpu"),
    ("study", "Estudos (Cérebro)", "brain"),
    ("voicestudio", "Voz (Voice Studio e Chatterbox)", "volume"),
    ("integrations", "Destinos e integrações", "plug"),
    ("protection", "Proteção do cérebro e Google Drive", "shield"),
    ("media", "Capas, PDFs, filtro de música e 3D", "image"),
    ("hardware", "Placa de vídeo", "gpu"),
]
_SECRET_RE = re.compile(r"(?i)\b(?:bearer\s+\S+|ntn_[A-Za-z0-9]{8,}|secret_[A-Za-z0-9]{8,}|ya29\.[\w-]{10,}|1//[\w-]{10,})")


class Down(Exception):
    """A sonda não teve resposta (porta fechada, tempo esgotado ou sem internet). `kind`: closed | timeout | offline."""

    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def http(url, *, method="GET", headers=None, data=None, timeout=LOCAL_S, local=True):
    """(status, corpo, cabeçalhos) de um pedido curto; HTTP de erro também volta (o status conta como resposta).
    Sem resposta: Down. Pedidos deste PC não usam proxy nem seguem redirecionamento."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    opener = _LOCAL if local else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read(2_000_000), r.headers
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read(200_000), e.headers
    except (TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (TimeoutError,)) or "timed out" in str(reason).lower():
            raise Down("timeout") from None
        if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower() or "10061" in str(reason):
            raise Down("closed") from None
        raise Down("offline") from None


def _json(body):
    try:
        out = json.loads(body or b"null")
    except ValueError:
        return None
    return out


def R(state, detail, *, required=False, enabled=True, stages=None, next=None, action=None, limit=None, repair=None):
    """O resultado de uma verificação. `stages` só leva as etapas que se aplicam a ela. `repair`: o id de um reparo de
    lumen/repair.py que resolve isto com um clique (o diagnóstico só aponta; quem decide e roda é o estudante)."""
    return {"state": state, "detail": detail, "required": bool(required), "enabled": bool(enabled),
            "stages": {k: (stages or {}).get(k) for k in STAGES}, "next": next, "action": action, "limit": limit, "repair": repair}


def _status(item):
    """O status de cor (compatível com a tela antiga) a partir do estado e de ser obrigatório."""
    s = item["state"]
    if s == "ok":
        return "ok"
    if s == "disabled":
        return "info"
    if s in ("unverified", "blocked"):
        return "warn" if item["required"] else "info"
    return "error" if item["required"] else "warn"


def _gb(n):
    return f"{n / 1024 ** 3:.1f} GB".replace(".", ",")


def _version_ok(have, want):
    return have == want or have.split("+")[0] == want


class Ctx:
    """O que várias verificações leem: carregado uma vez, sob trava, na primeira que pedir."""

    def __init__(self, request=None):
        self.request = request or {}
        self.cfg = store.load_config()
        self.secrets = set()
        self._lock = threading.Lock()
        self._memo = {}

    def memo(self, key, fn):
        with self._lock:
            box = self._memo.get(key)
            first = box is None
            if first:
                box = self._memo[key] = {"done": threading.Event()}
        if not first:
            return self._get(box)
        try:
            box["value"] = fn()
        except Exception as e:  # noqa: BLE001 - quem lê decide o que fazer com a falha
            box["error"] = e
        box["done"].set()
        return self._get(box)

    def _get(self, box):
        box["done"].wait(DEADLINE_S)
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def secret(self, value):
        if value and isinstance(value, str) and len(value) >= 6:
            with self._lock:
                self.secrets.add(value)
        return value

    def study(self):
        def load():
            from .study import settings
            return settings.load()
        return self.memo("study", load)

    def ollama(self):
        """{version, models} do Ollama, ou Down. Lê /api/version e /api/tags (só leitura)."""
        def load():
            from . import llm
            code, body, _ = http(llm.OLLAMA + "/api/version")
            version = (_json(body) or {}).get("version") if code == 200 else None
            code, body, _ = http(llm.OLLAMA + "/api/tags")
            if code != 200:
                raise Down("closed")
            return {"version": version, "models": [m["name"] for m in (_json(body) or {}).get("models", []) if m.get("name")]}
        return self.memo("ollama", load)

    def show(self, model):
        """Os metadados de um modelo do Ollama (POST /api/show é leitura: não carrega nem roda o modelo)."""
        def load():
            from . import llm
            code, body, _ = http(llm.OLLAMA + "/api/show", method="POST", data=json.dumps({"model": model}).encode(),
                                 headers={"Content-Type": "application/json"}, timeout=5)
            return _json(body) if code == 200 else None
        return self.memo("show:" + model, load)

    def vs(self):
        def load():
            from . import voicestudio
            return voicestudio.status()
        return self.memo("vs", load)

    def protection(self):
        def load():
            from . import protection
            return protection.view()
        return self.memo("protection", load)

    def hf_cache(self):
        try:
            from huggingface_hub import constants
            return Path(constants.HF_HUB_CACHE)
        except Exception:  # noqa: BLE001
            return Path.home() / ".cache" / "huggingface" / "hub"


def has(names, model):
    return bool(model) and any(n in (model, model + ":latest") or (model.endswith(":latest") and n == model[:-7]) for n in names)


# =====================================================================================================================
# 1. Aplicativo e ambiente
# =====================================================================================================================

def check_python(ctx):
    v = sys.version_info
    inside = Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
    text = f"Python {v.major}.{v.minor}.{v.micro} ({platform.architecture()[0]}) em {sys.executable}"
    if v < (3, 11):
        return R("misconfigured", text + ". O Lúmen precisa do 3.11 ou mais novo.", required=True,
                 stages={"installed": True, "usable": False}, next="Instale o Python 3.11+ e rode o Iniciar Lumen.bat para recriar o ambiente.")
    return R("ok", text + ("" if inside else " (fora do .venv do projeto)"), required=True,
             stages={"installed": True, "configured": inside or None, "usable": True})


def _pins(name):
    out = []
    try:
        lines = (ROOT / name).read_text("utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        m = re.match(r"\s*([A-Za-z0-9_.-]+)\s*==\s*([^\s#]+)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


MODULES = {"faster-whisper": "faster_whisper", "av": "av", "soundcard": "soundcard", "onnx-asr": "onnx_asr", "keyring": "keyring",
           "pillow": "PIL", "pypdf": "pypdf", "websocket-client": "websocket", "pyaec": "pyaec"}
OPTIONAL_DISTS = {"pyaec"}  # pyaec: só a conversa por voz


def check_packages(ctx):
    pins = _pins("requirements.txt")
    if pins is None:
        return R("missing", "requirements.txt não encontrado em " + str(ROOT), required=True, stages={"installed": False},
                 next="Restaure o requirements.txt da cópia do projeto.")
    missing, wrong, broken, fine = [], [], [], []
    for dist, want in pins:
        try:
            have = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            (fine if dist in OPTIONAL_DISTS else missing).append(f"{dist} (falta)" if dist not in OPTIONAL_DISTS else f"{dist}: opcional, ausente")
            continue
        if not _version_ok(have, want):
            wrong.append(f"{dist} {have} (fixado {want})")
        mod = MODULES.get(dist.lower())
        if mod:
            try:
                importlib.import_module(mod)
            except Exception as e:  # noqa: BLE001
                broken.append(f"{dist} não carrega ({type(e).__name__})")
                continue
        fine.append(f"{dist} {have}")
    stages = {"installed": not missing, "configured": not wrong, "usable": not missing and not broken}
    if missing or broken:
        return R("missing", "; ".join(missing + broken) + ".", required=True, stages=stages, repair="python" if missing else None,
                 next=("Use “Instalar / reparar” para instalar só os que faltam, na versão fixada; " if missing else "")
                 + "ou feche o Lúmen e rode o Iniciar Lumen.bat. O diagnóstico em si não instala nada.")
    if wrong:
        return R("misconfigured", "Versões diferentes das testadas: " + "; ".join(wrong) + ".", required=True, stages=stages,
                 next="Rode o Iniciar Lumen.bat para voltar às versões fixadas no requirements.txt.")
    return R("ok", f"{len(pins)} pacotes do requirements.txt nas versões fixadas e importáveis: " + ", ".join(fine) + ".",
             required=True, stages=stages)


def check_gpu_packages(ctx):
    from . import hardware
    gpu = ctx.memo("nvidia", hardware.nvidia)
    pins = _pins("requirements-gpu.txt") or []
    rows = []
    for dist, want in pins:
        try:
            rows.append((dist, importlib.metadata.version(dist), want))
        except importlib.metadata.PackageNotFoundError:
            rows.append((dist, None, want))
    ort = next((d for d in ("onnxruntime-directml", "onnxruntime-gpu", "onnxruntime") if _dist(d)), None)
    detail = "; ".join(f"{d} {h or 'ausente'}" for d, h, _ in rows) + f"; onnxruntime: {ort + ' ' + _dist(ort) if ort else 'ausente'}"
    if not gpu:
        return R("disabled", "Sem GPU NVIDIA: a transcrição usa a CPU. " + detail, enabled=False, stages={"installed": all(h for _, h, _ in rows) or None})
    absent = [d for d, h, _ in rows if not h]
    if absent:
        return R("missing", "GPU NVIDIA presente, mas faltam " + ", ".join(absent) + ". " + detail, stages={"installed": False},
                 next="Rode o Iniciar Lumen.bat: ele oferece instalar o requirements-gpu.txt. O diagnóstico não instala nada.")
    return R("ok", detail, stages={"installed": True, "configured": all(_version_ok(h, w) for _, h, w in rows)})


def _dist(name):
    try:
        return importlib.metadata.version(name)
    except (importlib.metadata.PackageNotFoundError, ValueError, TypeError):
        return None


def check_data(ctx):
    data = store.DATA
    if not data.is_dir():
        return R("missing", f"A pasta de dados {data} não existe.", required=True, stages={"configured": False},
                 next="Abra o Lúmen pelo Lumen.exe uma vez: ele cria a pasta.")
    writable = os.access(data, os.W_OK)
    free = shutil.disk_usage(data).free
    detail = f"{data} · {_gb(free)} livres no disco" + (" · LUMEN_DATA (pasta isolada)" if os.environ.get("LUMEN_DATA") else "")
    stages = {"configured": True, "usable": writable and free > 1024 ** 3}
    if not writable:
        return R("blocked", detail + ". Sem permissão de escrita.", required=True, stages=stages,
                 next="Confira as permissões da pasta no Explorer.", limit="Permissão conferida pelo sistema, sem gravar arquivo de teste.")
    if free < 1024 ** 3:
        return R("misconfigured", detail + ". Menos de 1 GB livre: gravações e aulas podem falhar.", required=True, stages=stages,
                 next="Libere espaço nesse disco.")
    return R("ok", detail, required=True, stages=stages, limit="Escrita conferida pela permissão, sem gravar arquivo de teste.")


def check_models_disk(ctx):
    cache = ctx.hf_cache()
    base = cache
    while not base.exists() and base.parent != base:
        base = base.parent
    free = shutil.disk_usage(base).free
    detail = f"Cache de modelos do Hugging Face em {cache} · {_gb(free)} livres"
    if free < 2 * 1024 ** 3:
        return R("misconfigured", detail + ". Pouco espaço para baixar ou atualizar modelos.", required=True,
                 stages={"configured": True, "usable": False}, next="Libere espaço nesse disco antes de baixar modelos.")
    return R("ok", detail, required=True, stages={"configured": True, "usable": True})


def check_keyring(ctx):
    import keyring
    backend = keyring.get_keyring()
    name = type(backend).__name__
    try:
        keyring.get_password(store.APP, "diagnostico-sonda-inexistente")  # leitura de uma entrada que não existe
    except Exception as e:  # noqa: BLE001
        return R("blocked", f"Cofre {name} recusou a leitura ({type(e).__name__}).", required=True,
                 stages={"installed": True, "reachable": False}, next="Confira o Gerenciador de Credenciais do Windows.")
    if "fail" in name.lower() or "null" in name.lower():
        return R("misconfigured", f"Sem cofre do sistema (keyring: {name}): tokens e chaves não podem ser guardados.", required=True,
                 stages={"installed": True, "configured": False}, next="Rode o Iniciar Lumen.bat para reinstalar o keyring.")
    return R("ok", f"Gerenciador de Credenciais do Windows ({name}) responde a leituras.", required=True,
             stages={"installed": True, "configured": True, "reachable": True, "usable": True},
             limit="Só leitura: nenhuma credencial é criada nem alterada.")


# =====================================================================================================================
# 2. Janela e serviços locais
# =====================================================================================================================

def check_server(ctx):
    req = ctx.request
    bind, port = req.get("bind"), req.get("port")
    if not req:
        return R("unverified", "Chamado fora de um pedido HTTP (teste ou linha de comando): o servidor não foi conferido.", required=True)
    local = bind == "127.0.0.1"
    detail = f"Respondeu a este pedido em {bind}:{port}, com o token de sessão conferido"
    if not local:
        return R("misconfigured", detail + f", mas escuta em {bind} (deveria ser só 127.0.0.1).", required=True,
                 stages={"installed": True, "configured": False, "authenticated": True, "reachable": True, "usable": True},
                 next="Reinicie o Lúmen pelo Lumen.exe.")
    return R("ok", detail + "; só este PC (127.0.0.1) e o Host conferido.", required=True,
             stages={"installed": True, "configured": True, "authenticated": True, "reachable": True, "usable": True})


def _reg(hive, path, value):
    try:
        import winreg
        with winreg.OpenKey(hive, path) as k:
            return winreg.QueryValueEx(k, value)[0]
    except (OSError, ImportError):
        return None


def webview2_version():
    import winreg
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, WEBVIEW2_CLIENT), (winreg.HKEY_CURRENT_USER, WEBVIEW2_CLIENT.replace("WOW6432Node\\", ""))):
        v = _reg(hive, path, "pv")
        if v and v != "0.0.0.0":
            return v
    return None


def check_shell(ctx):
    exe, dlls = ROOT / "Lumen.exe", [ROOT / "launcher" / "bin" / n for n in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll")]
    wv = webview2_version() if os.name == "nt" else None
    m = re.search(r"LumenShell/(\d+)", ctx.request.get("ua") or "")
    shell = int(m.group(1)) if m else None
    missing = [p.name for p in [exe, *dlls] if not p.exists()]
    detail = f"Lumen.exe: {'presente' if exe.exists() else 'ausente'} · WebView2 Runtime {wv or 'não encontrado'}"
    stages = {"installed": not missing and bool(wv)}
    if missing or not wv:
        return R("missing", detail + (f" · faltam {', '.join(missing)}" if missing else "") + ".", required=True, stages=stages,
                 next="Instale o Microsoft Edge WebView2 Runtime (site da Microsoft) ou restaure o Lumen.exe e launcher/bin da distribuição.")
    if shell is None:
        return R("unverified", detail + ". Esta página não está aberta pelo Lumen.exe (navegador comum): a janela nativa não foi conferida.",
                 required=True, stages={**stages, "configured": True},
                 next="Abra o Lúmen pelo Lumen.exe e rode o diagnóstico de novo.")
    return R("ok", detail + f" · esta página está aberta nele agora (LumenShell/{shell}).", required=True,
             stages={**stages, "configured": True, "reachable": True, "usable": True},
             limit="A ponte de mensagens da janela é usada por esta página; os painéis (HyperbookLM, Perplexity) não são abertos aqui.")


def edge_version(exe):
    try:
        names = [d.name for d in Path(exe).parent.iterdir() if d.is_dir() and re.fullmatch(r"\d+(\.\d+){3}", d.name)]
        return max(names, key=lambda s: tuple(map(int, s.split(".")))) if names else None
    except OSError:
        return None


def check_edge(ctx):
    from . import cdp
    exe = cdp.edge()
    if not exe:
        return R("missing", "Microsoft Edge não encontrado: capas, PDFs, gráficos e a pesquisa /web não funcionam.", stages={"installed": False},
                 next="Instale ou repare o Microsoft Edge pelo Windows.")
    ver = edge_version(exe)
    return R("ok", f"{exe} (versão {ver or 'desconhecida'}).", stages={"installed": True, "configured": True, "usable": True},
             limit="O Edge não é aberto pelo diagnóstico: só se confirma de verdade ao gerar uma capa, um PDF ou usar /web.")


def check_autostart(ctx):
    on = bool(ctx.cfg.get("autostart"))
    if os.name != "nt":
        return R("disabled", "Só no Windows.", enabled=False)
    import winreg
    value = _reg(winreg.HKEY_CURRENT_USER, RUN_KEY, "Lumen")
    if not on:
        return R("disabled", "Abrir com o Windows: desligado." + (" Há uma entrada antiga no registro." if value else ""), enabled=False,
                 action={"label": "Ajustes", "cat": "general"})
    m = re.match(r'\s*"([^"]+)"', value or "")
    target = Path(m.group(1)) if m else None
    if not target or not target.is_file():
        return R("misconfigured", "Abrir com o Windows está ligado, mas a entrada do registro " + ("não existe" if not value else f"aponta para {target}, que não existe") + ".",
                 stages={"configured": False}, next="Em Ajustes → Geral, desligue e ligue “Abrir com o Windows”.", action={"label": "Ajustes", "cat": "general"})
    return R("ok", f"Abre com o Windows: {target}.", stages={"configured": True, "usable": True})


# =====================================================================================================================
# 3. Áudio
# =====================================================================================================================

def _com():
    if os.name == "nt":
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # o áudio do Windows (COM) é por thread; já inicializado é inofensivo


def check_loopback(ctx):
    import soundcard as sc
    _com()
    try:
        spk = sc.default_speaker()
    except Exception as e:  # noqa: BLE001
        return R("missing", f"Nenhuma saída de áudio padrão no Windows ({type(e).__name__}).", required=True, stages={"installed": False},
                 next="Conecte ou ative fones/caixas em Configurações → Som.")
    try:
        sc.get_microphone(id=str(spk.name), include_loopback=True)
    except Exception as e:  # noqa: BLE001
        return R("misconfigured", f"Saída “{spk.name}” sem captura loopback ({type(e).__name__}).", required=True,
                 stages={"installed": True, "configured": False}, next="Escolha outra saída padrão em Configurações → Som.")
    return R("ok", f"Saída padrão “{spk.name}” com captura loopback disponível ({spk.channels} canais).", required=True,
             stages={"installed": True, "configured": True, "usable": True},
             limit="Nenhum áudio é gravado: a captura só se confirma ao gravar uma aula.")


def check_microphone(ctx):
    import soundcard as sc
    _com()
    try:
        mic = sc.default_microphone()
    except Exception:  # noqa: BLE001
        mic = None
    if not mic:
        return R("missing", "Nenhum microfone padrão: conversa por voz e apertar para falar ficam indisponíveis.", stages={"installed": False},
                 next="Conecte um microfone e permita o acesso em Configurações → Privacidade → Microfone.")
    return R("ok", f"Microfone padrão “{mic.name}”.", stages={"installed": True, "configured": True},
             limit="O microfone não é aberto: a permissão do Windows só se confirma ao falar.")


def check_decoder(ctx):
    import av
    missing = []
    for name in ("aac", "mp3", "opus", "pcm_s16le", "h264"):
        try:
            av.codec.Codec(name, "r")
        except Exception:  # noqa: BLE001
            missing.append(name)
    try:
        av.codec.Codec("aac", "w")
        enc = True
    except Exception:  # noqa: BLE001
        enc = False
    detail = f"PyAV {av.__version__} (FFmpeg {'.'.join(map(str, av.library_versions.get('libavcodec', ())))})"
    if missing or not enc:
        return R("misconfigured", detail + f": faltam decodificadores {', '.join(missing) or '—'}" + ("" if enc else " e o codificador AAC") + ".",
                 required=True, stages={"installed": True, "usable": False}, next="Rode o Iniciar Lumen.bat para reinstalar o av fixado.")
    return R("ok", detail + ": decodifica AAC, MP3, Opus, PCM e H.264 e codifica AAC.", required=True, stages={"installed": True, "usable": True})


def check_echo(ctx):
    try:
        import pyaec  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return R("missing", f"Cancelamento de eco (pyaec) ausente ({type(e).__name__}): na conversa por voz, use fones.", stages={"installed": False},
                 next="Rode o Iniciar Lumen.bat para instalar o requirements.txt.")
    return R("ok", f"pyaec {_dist('pyaec') or ''} carregado para a conversa por voz.", stages={"installed": True, "usable": True})


# =====================================================================================================================
# 4. Transcrição
# =====================================================================================================================

def check_asr_runtime(ctx):
    import ctranslate2
    import faster_whisper
    try:
        import onnx_asr  # noqa: F401
        onnx = _dist("onnx-asr")
    except Exception:  # noqa: BLE001
        onnx = None
    detail = f"faster-whisper {faster_whisper.__version__} · CTranslate2 {ctranslate2.__version__} · onnx-asr {onnx or 'ausente'}"
    if not onnx:
        return R("misconfigured", detail + ": o Parakeet (CPU) não roda.", required=True, stages={"installed": False},
                 next="Rode o Iniciar Lumen.bat para reinstalar o requirements.txt.")
    return R("ok", detail, required=True, stages={"installed": True, "usable": True})


def check_cuda(ctx):
    from . import hardware, transcribe
    gpu = ctx.memo("nvidia", hardware.nvidia)
    if not gpu:
        return R("disabled", "Sem GPU NVIDIA: transcrição na CPU (mais lenta, mas completa).", enabled=False)
    count = hardware.cuda()
    libs = transcribe.has_gpu()
    if count and libs:
        return R("ok", f"{gpu['name']}: CTranslate2 vê a GPU e carrega cuBLAS 12 e cuDNN 9.", stages={"installed": True, "configured": True, "usable": True})
    return R("misconfigured", f"{gpu['name']} presente, mas " + ("o CTranslate2 não vê a GPU" if not count else "cuBLAS 12/cuDNN 9 não carregam") + ": transcrição na CPU.",
             stages={"installed": bool(count), "configured": False}, next="Rode o Iniciar Lumen.bat e aceite o requirements-gpu.txt.",
             action={"label": "Transcrição", "cat": "transcription"})


def _model_path(name):
    from faster_whisper.utils import download_model
    return Path(download_model(name, local_files_only=True))


def check_asr_model(ctx):
    from . import transcribe
    quality, m = transcribe.pick(ctx.cfg.get("quality"))
    name = m["name"]
    action = {"label": "Transcrição", "cat": "transcription"}
    try:
        if name in transcribe.ONNX_REPOS:
            folder = Path(transcribe._onnx_dir(name))
            files = list(folder.glob("*.onnx"))
            ok = bool(files) and all(f.stat().st_size > 1_000_000 for f in files)
            where = f"{folder}"
        else:
            folder = _model_path(name)
            weights = folder / "model.bin"
            ok = weights.is_file() and weights.stat().st_size > 10_000_000
            where = f"{weights}"
    except Exception:  # noqa: BLE001 - não está no cache
        return R("missing", f"Modo “{m['label']}” usa {name} ({m['size']}), que não está baixado.", required=True,
                 stages={"configured": True, "installed": False}, next="Em Ajustes → Transcrição, baixe o modelo (o diagnóstico não baixa).", action=action)
    if not ok:
        return R("misconfigured", f"{name}: arquivos incompletos em {where}.", required=True, stages={"configured": True, "installed": False},
                 next="Em Ajustes → Transcrição, baixe o modelo de novo.", action=action)
    return R("ok", f"Modo “{m['label']}”: {name} completo em {where}.", required=True,
             stages={"installed": True, "configured": True, "usable": True},
             limit="O modelo não é carregado nem roda aqui (gastaria a placa): os arquivos são conferidos.")


# =====================================================================================================================
# 5. IA local
# =====================================================================================================================

OLLAMA_ACTION = {"label": "IA local", "cat": "ai"}


def _ollama_or(ctx, required):
    try:
        return ctx.ollama(), None
    except Down as e:
        what = {"timeout": "não respondeu em 3 s", "closed": "não está rodando (porta 11434 fechada)"}.get(e.kind, "não respondeu")
        return None, R("unreachable", f"O Ollama {what}.", required=required, stages={"reachable": False},
                       next="Abra o Ollama pelo menu Iniciar (o diagnóstico não o inicia).", action=OLLAMA_ACTION)


def check_ollama(ctx):
    ol, bad = _ollama_or(ctx, True)
    if bad:
        return bad
    return R("ok", f"Ollama {ol['version'] or ''} em 127.0.0.1:11434 com {len(ol['models'])} modelo(s).", required=True,
             stages={"installed": True, "reachable": True, "usable": bool(ol["models"]) or None})


def _model_check(ctx, model, *, purpose, required, enabled=True, capability=None, off_text=None):
    if not enabled:
        return R("disabled", off_text or f"{purpose}: desligado.", enabled=False, action=OLLAMA_ACTION)
    if not model:
        return R("misconfigured", f"{purpose}: nenhum modelo escolhido.", required=required, stages={"configured": False},
                 next="Escolha o modelo em Ajustes → IA local.", action=OLLAMA_ACTION)
    ol, bad = _ollama_or(ctx, required)
    if bad:
        bad["detail"] = f"{purpose} ({model}): " + bad["detail"]
        return bad
    if not has(ol["models"], model):
        return R("missing", f"{purpose}: {model} não está instalado no Ollama.", required=required, stages={"configured": True, "installed": False},
                 next=f"Baixe {model} em Ajustes → IA local (o diagnóstico não baixa).", action=OLLAMA_ACTION)
    info = ctx.show(model)
    if not info:
        return R("unverified", f"{purpose}: {model} listado, mas o Ollama não devolveu os metadados.", required=required,
                 stages={"configured": True, "installed": True, "reachable": True}, next="Abra o Ollama e confira o modelo com “ollama show”.")
    caps = info.get("capabilities") or []
    det = info.get("details") or {}
    desc = " · ".join(x for x in (det.get("parameter_size"), det.get("quantization_level")) if x)
    if capability and caps and capability not in caps:
        return R("misconfigured", f"{purpose}: {model} não declara “{capability}” ({', '.join(caps)}).", required=required,
                 stages={"configured": True, "installed": True, "reachable": True, "usable": False},
                 next="Escolha um modelo com essa capacidade em Ajustes → IA local.", action=OLLAMA_ACTION)
    return R("ok", f"{purpose}: {model} ({desc or 'metadados lidos'}{', ' + ', '.join(caps) if caps else ''}).", required=required,
             stages={"installed": True, "configured": True, "reachable": True, "usable": True},
             limit="O modelo não é carregado nem roda aqui: só os metadados do Ollama são lidos.")


def check_lesson_model(ctx):
    return _model_check(ctx, ctx.cfg.get("ollama_model"), purpose="Material das aulas", required=True, capability="completion")


def check_vision_model(ctx):
    from . import vision
    s = ctx.study()
    on = bool(ctx.cfg.get("watch_screen")) or bool(s["search"].get("images"))
    return _model_check(ctx, vision.MODEL, purpose="Visão (telas e imagens das notas)", required=False, enabled=on, capability="vision",
                        off_text="“Assistir a tela junto” e a leitura de imagens das notas estão desligados.")


# =====================================================================================================================
# 6. Estudos
# =====================================================================================================================

def check_study_db(ctx):
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        fts = True
    except sqlite3.OperationalError:
        fts = False
    finally:
        con.close()
    from .study import db
    path = db.HOME / "study.db"
    detail = f"SQLite {sqlite3.sqlite_version} {'com' if fts else 'sem'} FTS5"
    if not fts:
        return R("misconfigured", detail + ": a busca dos Estudos não funciona.", stages={"installed": True, "usable": False},
                 next="Reinstale o Python oficial (python.org), que traz o FTS5.")
    if not path.is_file():
        return R("ok", detail + f"; o banco ({path}) é criado no primeiro uso dos Estudos.", stages={"installed": True, "configured": None, "usable": True})
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            docs = con.execute("SELECT count(*) FROM documents").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as e:
        return R("blocked", detail + f"; o banco {path} não abriu para leitura ({type(e).__name__}).", stages={"installed": True, "usable": False},
                 next="Feche outras cópias do Lúmen e tente de novo.")
    return R("ok", detail + f"; {path} aberto só para leitura com {docs} documento(s) indexado(s).",
             stages={"installed": True, "configured": True, "usable": True})


def check_study_models(ctx):
    from .study import settings
    s = ctx.study()
    names = {"principal": settings.local_model(s), "rápido": settings.fast_model(s), "máximo": settings.max_model(s)}
    ol, bad = _ollama_or(ctx, False)
    if bad:
        bad["detail"] = "Modelos do chat: " + bad["detail"]
        return bad
    absent = [f"{k} ({v})" for k, v in names.items() if not has(ol["models"], v)]
    detail = "Modelos do chat: " + ", ".join(f"{k} {v}" for k, v in names.items())
    if absent:
        return R("missing", detail + ". Não instalados: " + ", ".join(absent) + ".", stages={"configured": True, "installed": False, "reachable": True},
                 next="Baixe-os em Cérebro → Configurações → Modelos ou escolha outros.", action={"label": "Cérebro", "view": "study"})
    return R("ok", detail + ", todos instalados.", stages={"installed": True, "configured": True, "reachable": True},
             limit="Nenhuma resposta é gerada: a presença no Ollama é conferida.")


def check_embed_model(ctx):
    s = ctx.study()
    return _model_check(ctx, s["models"].get("embed"), purpose="Busca por significado", required=False, enabled=bool(s["search"].get("hybrid")),
                        capability="embedding", off_text="Busca híbrida desligada: só palavras.")


def check_adult_model(ctx):
    from .study import settings
    s = ctx.study()
    on = bool(s["adult"].get("enabled"))
    return _model_check(ctx, s["adult"].get("model") or settings.ADULT_RECOMMENDED if on else "", purpose="Perfil adulto", required=False,
                        enabled=on, off_text="Perfil adulto desligado.")


def check_folders(ctx):
    s = ctx.study()
    folders = s["connectors"].get("folders") or []
    if not folders or not s["search"].get("files"):
        return R("disabled", "Nenhuma pasta autorizada para os Estudos lerem." if not folders else "Busca em arquivos locais desligada.", enabled=False,
                 action={"label": "Cérebro", "view": "study"})
    gone = [f for f in folders if not Path(f).is_dir() or not os.access(f, os.R_OK)]
    if gone:
        return R("unreachable", f"{len(gone)} de {len(folders)} pasta(s) autorizada(s) indisponível(is): " + "; ".join(map(str, gone)) + ".",
                 stages={"configured": True, "reachable": False}, next="Reconecte o disco ou tire a pasta em Cérebro → Configurações → Fontes.",
                 action={"label": "Cérebro", "view": "study"})
    return R("ok", f"{len(folders)} pasta(s) autorizada(s) acessível(is) para leitura.", stages={"configured": True, "reachable": True, "usable": True})


def check_web_search(ctx):
    from . import cdp
    s = ctx.study()
    if not s["search"].get("web"):
        return R("disabled", "Pesquisa na internet (/web) desligada nos Estudos.", enabled=False, action={"label": "Cérebro", "view": "study"})
    if not cdp.edge():
        return R("missing", "Pesquisa /web ligada, mas o Edge não foi encontrado.", stages={"configured": True, "installed": False},
                 next="Instale ou repare o Microsoft Edge.")
    return R("unverified", "Ligada; usa o Edge em modo de leitura. Nenhuma pesquisa é feita pelo diagnóstico.", stages={"configured": True, "installed": True},
             limit="Só se confirma ao pesquisar: o diagnóstico não envia consultas à internet.")


def check_policy(ctx):
    from .study import settings
    m = ctx.study()["models"]  # em vigor: a política já valeu na leitura
    cloud = [k for k in ("anthropic", "openai", "image_openai", "video_model") if m.get(k)]
    if m.get("provider") != "ollama" or cloud or m.get("image_provider") != "local":
        return R("misconfigured", f"Ajustes em vigor pedem IA em nuvem ({m.get('provider')}, {', '.join(cloud) or '—'}).",
                 required=True, stages={"configured": False}, next="Abra Cérebro → Configurações → Modelos e salve de novo.")
    raw = settings._merged()["models"]  # como está no arquivo, sem a política
    old = [k for k in ("anthropic", "openai", "image_openai", "video_model") if raw.get(k)] + (["provider"] if raw.get("provider") != "ollama" else [])
    return R("ok", "Só IA local: nuvem paga bloqueada pela política (lumen/study/policy.py)."
             + (f" Ajuste antigo no arquivo ({', '.join(old)}) é neutralizado na leitura." if old else ""), required=True, stages={"configured": True})


# =====================================================================================================================
# 7. Voz
# =====================================================================================================================

VS_ACTION = {"label": "Voice Studio", "view": "integrations", "tab": "voicestudio"}


def _vs_enabled(ctx):
    v = ctx.study()["voice"]
    return v.get("engine") == "voicestudio"


def check_vs_install(ctx):
    from . import voicestudio
    on = _vs_enabled(ctx)
    if not voicestudio.installed():
        return R("missing" if on else "disabled", "Voice Studio não instalado em " + str(voicestudio.APP) + ".", enabled=on,
                 stages={"installed": False}, next="Instale o Voice Studio (opcional) e escolha-o em Integrações." if on else None, action=VS_ACTION)
    ver = voicestudio._version(voicestudio.APP / "resources" / "pyproject.toml")
    problem = voicestudio.launch_problem()
    detail = f"Voice Studio {ver or '(versão não lida)'} em {voicestudio.APP}"
    if not on:
        return R("disabled", detail + "; a voz dos Estudos usa outro motor.", enabled=False, stages={"installed": True}, action=VS_ACTION)
    if problem:
        why = {"setup": "a instalação do backend não terminou", "update": "o app foi atualizado e ainda não foi aberto",
               "custom": "usa pastas escolhidas no app (só ele sobe o backend)"}.get(problem, problem)
        return R("misconfigured", detail + f": {why}.", stages={"installed": True, "configured": False},
                 next="Abra o Voice Studio uma vez pelo menu Iniciar para ele concluir.", action=VS_ACTION)
    return R("ok", detail + "; o Lúmen pode subir o backend sob demanda.", stages={"installed": True, "configured": True})


def check_vs_backend(ctx):
    from . import voicestudio
    on = _vs_enabled(ctx)
    if not voicestudio.installed():
        return R("disabled", "Sem Voice Studio instalado.", enabled=False)
    st = ctx.vs()
    if st.get("foreign"):
        return R("misconfigured", f"Outro programa responde em {voicestudio.url()}.", enabled=on, stages={"reachable": False},
                 next="Feche o programa que usa essa porta ou mude a porta no Voice Studio.", action=VS_ACTION)
    if not st.get("running"):
        return R("unverified" if on else "disabled", f"Backend fechado em {voicestudio.url()}; o Lúmen o abre quando a voz é usada.",
                 enabled=on, stages={"installed": True, "reachable": False},
                 limit="O diagnóstico não inicia o Voice Studio: modelos e vozes não puderam ser lidos.")
    model = st.get("model") or {}
    eng = (st.get("engine") or {}).get("name") or "motor desconhecido"
    load = "carregado na VRAM" if model.get("loaded") else "carregando" if model.get("loading") else "carrega no primeiro uso"
    if model.get("error"):
        return R("misconfigured", f"Backend {st.get('version') or ''} ({eng}) com erro no modelo.", enabled=on,
                 stages={"installed": True, "reachable": True, "usable": False}, next="Abra o Voice Studio e veja o erro do modelo.", action=VS_ACTION)
    return R("ok" if on else "disabled", f"Backend {st.get('version') or ''} em {voicestudio.url()} · {st.get('device') or 'dispositivo ?'} {st.get('gpu') or ''} · {eng} {load}.",
             enabled=on, stages={"installed": True, "reachable": True, "usable": True})


def check_vs_models(ctx):
    from . import voicestudio
    on = _vs_enabled(ctx)
    if not voicestudio.installed() or not ctx.vs().get("running"):
        return R("unverified" if on and voicestudio.installed() else "disabled",
                 "Pacote de modelos não lido: o backend está fechado." if voicestudio.installed() else "Sem Voice Studio.", enabled=on)
    cat = voicestudio.catalog()
    tier = cat.get("tier") or "max"
    pack = (cat.get("packs") or {}).get(tier, {})
    where = cat.get("models_dir")
    where = (where.get("effective") or where.get("configured")) if isinstance(where, dict) else where
    free = cat.get("disk_free_gb")
    tail = f" em {where}" + (f" · {free:.1f} GB livres".replace(".", ",") if isinstance(free, (int, float)) else "")
    if pack.get("missing"):
        return R("missing", f"Perfil “{tier}”: faltam {len(pack['missing'])} modelo(s) ({pack.get('download_gb')} GB){tail}.", enabled=on,
                 stages={"installed": False, "reachable": True}, next="Baixe em Integrações → Voice Studio → Modelos de voz (o diagnóstico não baixa).", action=VS_ACTION)
    return R("ok" if on else "disabled", f"Perfil “{tier}”: {len(pack.get('models') or [])} modelo(s) instalados ({pack.get('total_gb')} GB){tail}.",
             enabled=on, stages={"installed": True, "reachable": True, "usable": True})


def check_vs_voice(ctx):
    from . import voicestudio
    on = _vs_enabled(ctx)
    want = ctx.study()["voice"].get("voice_id")
    if not voicestudio.installed() or not ctx.vs().get("running"):
        return R("unverified" if on and voicestudio.installed() else "disabled", f"Voz escolhida ({want or 'nenhuma'}) não conferida: backend fechado." if voicestudio.installed() else "Sem Voice Studio.", enabled=on)
    voices = voicestudio.voices()
    chosen = next((v for v in voices if v["id"] == want), None)
    if not chosen:
        return R("misconfigured", f"A voz escolhida ({want or 'nenhuma'}) não está entre os {len(voices)} perfis do Voice Studio.", enabled=on,
                 stages={"configured": False, "reachable": True}, next="Escolha outra voz em Integrações → Voice Studio.", action=VS_ACTION)
    return R("ok" if on else "disabled", f"Voz “{chosen['name']}” presente entre {len(voices)} perfil(is).", enabled=on,
             stages={"configured": True, "reachable": True, "usable": True}, limit="Nenhuma fala é gerada pelo diagnóstico.")


def check_chatterbox(ctx):
    from . import voice
    v = ctx.study()["voice"]
    on = "chatterbox" in (v.get("engine"), v.get("fallback"))
    if not voice.available():
        return R("missing" if on else "disabled", f"Chatterbox não instalado ({voice.PYTHON}).", enabled=on, stages={"installed": False},
                 next="Instale o ambiente do Chatterbox em D:\\Lumen\\voz (opcional)." if on else None)
    return R("ok" if on else "disabled", f"Chatterbox pronto para abrir sob demanda ({voice.PYTHON}).", enabled=on,
             stages={"installed": True}, limit="O motor não é aberto pelo diagnóstico.")


# =====================================================================================================================
# 8. Destinos e integrações
# =====================================================================================================================

def _notion(ctx, path, token):
    from . import notion
    return http(notion.API + path, headers={"Authorization": "Bearer " + token, "Notion-Version": notion.VERSION}, timeout=NET_S, local=False)


def check_notion(ctx):
    need = ctx.cfg.get("destinations") in ("notion", "both")
    action = {"label": "Notion", "view": "integrations", "tab": "notion"}
    token = ctx.secret(store.get_token())
    root = ctx.cfg.get("root_page_id")
    if not token:
        return R("misconfigured" if need else "disabled", "Notion não conectado (sem token no cofre).", required=need, enabled=need,
                 stages={"configured": False}, next="Cole o token da integração em Integrações → Notion." if need else None, action=action)
    try:
        code, body, _ = _notion(ctx, "/users/me", token)
    except Down as e:
        return R("unreachable", f"api.notion.com não respondeu ({e.kind}).", required=need, enabled=True, stages={"configured": True, "reachable": False},
                 next="Confira a internet e rode o diagnóstico de novo.")
    if code in (401, 403):
        return R("misconfigured", f"O Notion recusou o token (HTTP {code}).", required=need, stages={"configured": True, "authenticated": False, "reachable": True},
                 next="Gere um token novo e cole em Integrações → Notion.", action=action)
    if code != 200:
        return R("unverified", f"O Notion respondeu HTTP {code} à identificação.", required=need, stages={"configured": True, "reachable": True},
                 next="Tente de novo em alguns minutos.")
    bot = ((_json(body) or {}).get("bot") or {}).get("workspace_name") or "workspace"
    if not root:
        return R("misconfigured", f"Token válido ({bot}), mas nenhuma página raiz escolhida.", required=need,
                 stages={"configured": False, "authenticated": True, "reachable": True}, next="Escolha a página raiz em Integrações → Notion.", action=action)
    code, body, _ = _notion(ctx, "/pages/" + urllib.parse.quote(root), token)
    page = _json(body) or {}
    stages = {"configured": True, "authenticated": True, "reachable": True}
    if code in (403, 404):
        return R("misconfigured", f"Token válido ({bot}), mas sem acesso à página raiz “{ctx.cfg.get('root_page_title') or root}” (HTTP {code}).",
                 required=need, stages={**stages, "usable": False}, next="No Notion, abra a página raiz → ••• → Conexões → adicione a integração.", action=action)
    if code != 200:
        return R("unverified", f"A página raiz respondeu HTTP {code}.", required=need, stages=stages, next="Tente de novo em alguns minutos.")
    if page.get("in_trash") or page.get("archived"):
        return R("misconfigured", "A página raiz está na lixeira do Notion.", required=need, stages={**stages, "usable": False},
                 next="Restaure a página no Notion ou escolha outra raiz.", action=action)
    return R("ok", f"Token válido ({bot}); página raiz “{ctx.cfg.get('root_page_title') or root}” acessível.", required=need, enabled=True,
             stages={**stages, "usable": True}, limit="Só leituras (GET): a permissão de escrita só se confirma ao publicar uma aula.")


def check_obsidian(ctx):
    need = ctx.cfg.get("destinations") in ("obsidian", "both")
    action = {"label": "Obsidian", "view": "integrations", "tab": "obsidian"}
    raw = ctx.cfg.get("obsidian_vault")
    if not raw:
        return R("misconfigured" if need else "disabled", "Nenhum cofre do Obsidian escolhido.", required=need, enabled=need,
                 stages={"configured": False}, next="Escolha o cofre em Integrações → Obsidian." if need else None, action=action)
    p = Path(raw)
    if not p.is_dir():
        return R("unreachable", f"Cofre não encontrado em {p} (disco desconectado ou pasta movida).", required=need, stages={"configured": True, "reachable": False},
                 next="Reconecte o disco ou escolha o cofre de novo.", action=action)
    from . import vault
    area = p / (ctx.cfg.get("obsidian_folder") or vault.default_folder(p))
    marker = (p / ".obsidian").is_dir()
    writable = os.access(p, os.W_OK) and (not area.exists() or os.access(area, os.W_OK))
    detail = f"Cofre “{p.name}” em {p}{'' if marker else ' (sem .obsidian: o Obsidian ainda não abriu esta pasta)'}; área {area.name} {'existe' if area.is_dir() else 'será criada na primeira aula'}"
    if not writable:
        return R("blocked", detail + "; sem permissão de escrita.", required=need, stages={"configured": True, "reachable": True, "usable": False},
                 next="Confira as permissões da pasta.", action=action)
    return R("ok", detail + ".", required=need, enabled=True, stages={"configured": marker or None, "reachable": True, "usable": True},
             limit="Escrita conferida pela permissão, sem criar arquivo de teste no cofre.")


def check_opennotebook(ctx):
    from . import opennotebook
    cfg = ctx.cfg
    action = {"label": "Open Notebook", "view": "integrations", "tab": "opennotebook"}
    if not cfg.get("opennotebook_on"):
        return R("disabled", "Open Notebook desligado.", enabled=False, action=action)
    url = cfg["opennotebook_url"]
    pw = ctx.secret(opennotebook._password())
    headers = {"Accept": "application/json", **({"Authorization": "Bearer " + pw} if pw else {})}
    try:
        code, body, _ = http(url + "/api/config", headers=headers, timeout=LOCAL_S, local=url.startswith("http://127.") or "localhost" in url)
    except Down as e:
        return R("unreachable", f"A API em {url} não respondeu ({e.kind}).", stages={"configured": True, "reachable": False},
                 next="Abra o Open Notebook (há “Iniciar Open Notebook” em Integrações).", action=action)
    if code == 401:
        return R("misconfigured", "O Open Notebook pede senha" + (" e a guardada foi recusada." if pw else "."), stages={"configured": True, "authenticated": False, "reachable": True},
                 next="Informe a senha em Integrações → Open Notebook.", action=action)
    conf = _json(body) or {}
    if code != 200 or "dbStatus" not in conf:
        return R("misconfigured", f"{url} respondeu HTTP {code}, mas não como o Open Notebook.", stages={"configured": False, "reachable": True},
                 next="Confira o endereço da API.", action=action)
    if conf.get("dbStatus") != "online":
        return R("unreachable", "A API respondeu, mas o banco de dados dele está fora do ar.", stages={"configured": True, "authenticated": True, "reachable": False},
                 next="Inicie o banco do Open Notebook.", action=action)
    book = cfg.get("opennotebook_notebook")
    code, body, _ = http(url + "/api/notebooks", headers=headers, timeout=LOCAL_S, local=True)
    books = {n.get("id") for n in (_json(body) or []) if isinstance(n, dict)} if code == 200 else set()
    stages = {"installed": True, "configured": bool(book), "authenticated": True, "reachable": True}
    if not book or book not in books:
        return R("misconfigured", f"Open Notebook {conf.get('version') or ''} conectado, mas o caderno de destino " + ("não foi escolhido." if not book else "não existe mais."),
                 stages={**stages, "configured": False}, next="Escolha o caderno em Integrações → Open Notebook.", action=action)
    return R("ok", f"Open Notebook {conf.get('version') or ''} com banco online; caderno “{cfg.get('opennotebook_notebook_name') or book}” existe.",
             stages={**stages, "usable": True}, limit="Nenhuma transcrição é enviada pelo diagnóstico.")


def check_hyperbooklm(ctx):
    from . import hyperbooklm
    cfg = ctx.cfg
    action = {"label": "HyperbookLM", "view": "integrations", "tab": "hyperbooklm"}
    if not cfg.get("hyperbooklm_on"):
        return R("disabled", "HyperbookLM desligado.", enabled=False, action=action)
    url, token = cfg["hyperbooklm_url"], ctx.secret(hyperbooklm._token())
    try:
        code, body, _ = http(url + "/api/lumen", headers={"Accept": "application/json", **({"Authorization": "Bearer " + token} if token else {})}, timeout=LOCAL_S)
    except Down as e:
        return _hyperbooklm_down(url, e.kind, action)
    info = _json(body) if code == 200 else None
    if not isinstance(info, dict) or info.get("app") != "hyperbooklm":
        return R("misconfigured", f"{url} respondeu (HTTP {code}), mas não é a ponte do HyperbookLM.", stages={"configured": False, "reachable": True},
                 next="Confira o endereço em Integrações → HyperbookLM.", action=action)
    if not token or not info.get("paired"):
        return R("misconfigured", "Ponte encontrada, mas sem pareamento.", stages={"configured": True, "authenticated": False, "reachable": True},
                 next="Gere o código de pareamento em Integrações → HyperbookLM.", action=action)
    feats = info.get("features") or {}
    text = feats.get("text") is True
    return R("ok" if text else "misconfigured", "Ponte pareada" + ("; IA de texto do HyperbookLM com chave." if text else "; falta a chave de IA de texto no .env.local dele."),
             stages={"installed": True, "configured": True, "authenticated": True, "reachable": True, "usable": text},
             next=None if text else "Configure a chave no .env.local do HyperbookLM.", action=action, limit="Nenhuma transcrição é enviada pelo diagnóstico.")


def _hyperbooklm_down(url, kind, action):
    """A ponte não respondeu: servidor parado, porta salva desatualizada ou dependências faltando? Só leituras."""
    from . import hyperbooklm, repair
    found = hyperbooklm.detect()
    if found:
        return R("misconfigured", f"Nada responde em {url}, mas o HyperbookLM está de pé em {found}: o endereço salvo está desatualizado.",
                 stages={"configured": False, "reachable": True}, next="“Instalar / reparar” só corrige o endereço salvo (nada é iniciado).",
                 action=action, repair="hyperbooklm")
    repo = repair.hb_repo()
    if not repo:
        return R("unreachable", f"A ponte em {url} não respondeu ({kind}) e o repositório não foi encontrado em {repair.HB_REPO}.",
                 stages={"configured": True, "installed": False, "reachable": False}, next="Instale o HyperbookLM nessa pasta (README do Lúmen).", action=action)
    deps = repair.hb_deps(repo)
    need = deps["missing"] + deps["mismatch"]
    where = f"Repositório em {repo}: " + (f"faltam ou diferem {len(need)} de {deps['checked']} dependências do {deps['lock'] or 'package.json'} ({', '.join(need[:4])}{'…' if len(need) > 4 else ''})"
                                          if need else f"{deps['checked']} dependências completas ({deps['lock'] or 'package.json'})")
    return R("missing" if need else "unreachable", f"A ponte em {url} não respondeu ({kind}): servidor parado. {where}.",
             stages={"installed": not need, "configured": True, "reachable": False},
             next=("“Instalar / reparar” instala as dependências travadas e inicia o HyperbookLM" if need else "“Instalar / reparar” inicia o npm run dev dele")
             + " e confere /api/lumen. Opcional: não afeta a prontidão do Lúmen.", action=action, repair="hyperbooklm")


def check_perplexity(ctx):
    m = re.search(r"LumenShell/(\d+)", ctx.request.get("ua") or "")
    shell = int(m.group(1)) if m else None
    profile = store.DATA / "webview-perplexity"
    stages = {"installed": shell is None or shell >= 3}
    if not profile.is_dir():  # nunca aberto neste PC: nada é consultado na internet
        return R("disabled", "Ainda não usado (sem perfil do painel). Use em Integrações → Perplexity ou /perplexity no Cérebro.", enabled=False,
                 action={"label": "Perplexity", "view": "integrations", "tab": "perplexity"})
    try:
        code, _, _ = http("https://www.perplexity.ai/opensearch.xml", timeout=NET_S, local=False)
        reach = code == 200
    except Down:
        code, reach = None, False
    where = "abre no painel do Lumen.exe" if shell and shell >= 3 else "Lumen.exe antigo ou navegador: abre no navegador padrão" if shell else "fora do Lumen.exe: abre no navegador padrão"
    detail = f"{where}; site oficial {'alcançável' if reach else 'sem resposta'}; perfil {'já usado' if profile.is_dir() else 'ainda não criado'} ({profile})"
    if not reach:
        return R("unreachable", detail + ".", stages={**stages, "reachable": False}, next="Confira a internet.",
                 action={"label": "Perplexity", "view": "integrations", "tab": "perplexity"})
    return R("ok", detail + ".", stages={**stages, "configured": True, "reachable": True},
             limit="O login fica no painel e nunca é lido pelo Lúmen: a conta não é conferida.",
             action={"label": "Perplexity", "view": "integrations", "tab": "perplexity"})


# =====================================================================================================================
# 9. Proteção do cérebro e Google Drive
# =====================================================================================================================

PROT_ACTION = {"label": "Proteção", "cat": "protection"}


def _prot_on(ctx):
    v = ctx.protection()
    c = v["config"]
    return bool(c.get("enabled") or c.get("local")), v


def check_restic(ctx):
    from . import protection
    on, _ = _prot_on(ctx)
    if not protection.RESTIC.is_file():
        return R("missing" if on else "disabled", f"restic.exe não encontrado em {protection.RESTIC}.", enabled=on, stages={"installed": False},
                 next="Restaure launcher/tools/restic.exe da distribuição." if on else None, action=PROT_ACTION)
    try:
        out = subprocess.run([str(protection.RESTIC), "version"], capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW)
        ver = (out.stdout or "").split()[1] if out.returncode == 0 and out.stdout.startswith("restic") else None
    except (OSError, subprocess.SubprocessError, IndexError):
        ver = None
    if not ver:
        return R("misconfigured", f"{protection.RESTIC} não respondeu a “restic version”.", enabled=on, stages={"installed": True, "usable": False},
                 next="Restaure launcher/tools/restic.exe da distribuição.", action=PROT_ACTION)
    return R("ok" if on else "disabled", f"restic {ver} em {protection.RESTIC}.", enabled=on, stages={"installed": True, "usable": True},
             action=None if on else PROT_ACTION)


def check_protection_repo(ctx):
    import keyring

    from . import protection
    on, v = _prot_on(ctx)
    c = v["config"]
    if not on:
        return R("disabled", "Proteção do cérebro não configurada (nenhuma pasta escolhida).", enabled=False, action=PROT_ACTION)
    key = ctx.secret(keyring.get_password(store.APP, "protection-" + c["set_id"])) if c.get("set_id") else None
    stages = {"configured": bool(c.get("local")), "authenticated": None}
    if not key:
        return R("misconfigured", "A chave de recuperação não está neste Windows.", stages={**stages, "authenticated": False},
                 next="Em Proteção do cérebro → Segurança, importe a chave exportada.", action=PROT_ACTION)
    if not v.get("local_available"):
        return R("unreachable", f"O disco da pasta de backup ({c.get('local') or '—'}) não está disponível.", stages={**stages, "reachable": False},
                 next="Reconecte o disco original (nenhum substituto é criado).", action=PROT_ACTION)
    repo = protection.HOME / "repository"
    if not (repo / "config").is_file():
        return R("unverified", f"Ainda não há repositório em {repo}: ele nasce no primeiro backup.", stages={**stages, "reachable": True},
                 next="Faça o primeiro backup em Proteção do cérebro.", action=PROT_ACTION)
    env = {**os.environ, "RESTIC_PASSWORD": key}
    try:
        out = subprocess.run([str(protection.RESTIC), "-r", str(repo), "--no-lock", "--no-cache", "cat", "config"], env=env,
                             capture_output=True, timeout=15, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return R("unverified", f"Restic não terminou a leitura ({type(e).__name__}).", stages={**stages, "reachable": True},
                 next="Rode o diagnóstico de novo com a proteção parada.", action=PROT_ACTION)
    if out.returncode:
        return R("misconfigured", f"Restic não abriu o repositório com a chave deste Windows (código {out.returncode}).",
                 stages={**stages, "authenticated": False, "reachable": True}, next="Importe a chave correta em Proteção do cérebro.", action=PROT_ACTION)
    versions = len((v.get("state") or {}).get("versions") or [])
    return R("ok", f"Repositório {repo} aberto com a chave deste Windows (leitura sem trava); {versions} versão(ões) registrada(s).",
             stages={**stages, "authenticated": True, "reachable": True, "usable": True},
             limit="Lê só a configuração do repositório: a integridade dos dados é conferida pela própria proteção (restic check).")


def check_protection_copies(ctx):
    on, v = _prot_on(ctx)
    if not on:
        return R("disabled", "Sem cópias: a proteção não está configurada.", enabled=False, action=PROT_ACTION)
    places = v.get("places") or {}
    local = (places.get("local") or {}).get("state")
    names = {"ok": "confirmada", "behind": "versão anterior; atualização pendente", "first": "aguardando a primeira cópia",
             "attention": "precisa de atenção", "unavailable": "destino indisponível", "queued": "na fila", "copying": "copiando", "checking": "conferindo",
             "unknown": "ainda não foi possível confirmar pelos recibos", "setup": "falta configurar", "disabled": "desativada"}
    if local == "ok":
        return R("ok", "Cópia neste computador confirmada pelos recibos da proteção.", stages={"usable": True})
    state = "unreachable" if local == "unavailable" else "misconfigured" if local == "attention" else "unverified"
    return R(state, f"Cópia neste computador: {names.get(local, local or 'sem recibo')}.", stages={"usable": False if state != "unverified" else None},
             next="Abra Proteção do cérebro e faça um backup.", action=PROT_ACTION)


def _drive_token(c):
    """Renova o acesso do Google para esta sonda, sem gravar nada no cofre (a do app grava a expiração)."""
    from . import gdrive
    data = urllib.parse.urlencode({"client_id": c.get("client_id", ""), "client_secret": c.get("client_secret", ""),
                                   "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
    code, body, _ = http(gdrive.TOKEN, method="POST", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=NET_S, local=False)
    out = _json(body) or {}
    return code, out.get("access_token"), out.get("error")


def check_drive(ctx):
    from . import gdrive
    on, v = _prot_on(ctx)
    action = {"label": "Google Drive", "view": "integrations", "tab": "drive"}
    want = bool(v["config"].get("drive_enabled"))
    c = gdrive._creds()
    for k in ("refresh_token", "client_secret"):
        ctx.secret(c.get(k))
    if not want:
        return R("disabled", "Cópia no Google Drive desligada." + (" Conta conectada." if c.get("refresh_token") else ""), enabled=False, action=action)
    if not c.get("client_id"):
        return R("misconfigured", "Cópia no Drive ligada, mas sem cliente OAuth.", stages={"configured": False},
                 next="Escolha o JSON do cliente em Integrações → Google Drive.", action=action)
    if not c.get("refresh_token"):
        return R("misconfigured", "Cópia no Drive ligada, mas a conta não está conectada" + (" (autorização expirada)." if c.get("expired") else "."),
                 stages={"configured": True, "authenticated": False}, next="Clique em “Entrar com Google” em Integrações → Google Drive.", action=action)
    try:
        code, access, err = _drive_token(c)
    except Down as e:
        return R("unreachable", f"O Google não respondeu ({e.kind}).", stages={"configured": True, "reachable": False}, next="Confira a internet.")
    if not access:
        ctx.secret(access)
        why = "a autorização expirou ou foi removida" if err == "invalid_grant" else "o cliente OAuth foi recusado" if err in ("invalid_client", "unauthorized_client") else f"HTTP {code}"
        return R("misconfigured", f"O Google recusou a renovação: {why}.", stages={"configured": True, "authenticated": False, "reachable": True},
                 next="Entre com Google de novo em Integrações → Google Drive.", action=action,
                 limit="Nada foi gravado no cofre: o app marca a expiração só no próximo uso real.")
    ctx.secret(access)
    q = "appProperties has { key='lumen' and value='catalog' } and trashed = false"
    try:
        code, body, _ = http(gdrive.API + "/files?" + urllib.parse.urlencode({"q": q, "fields": "files(id)", "pageSize": 1, "spaces": "drive"}),
                             headers={"Authorization": "Bearer " + access}, timeout=NET_S, local=False)
    except Down as e:
        return R("unreachable", f"A API do Drive não respondeu ({e.kind}).", stages={"configured": True, "authenticated": True, "reachable": False})
    if code != 200:
        return R("misconfigured", f"A API do Drive recusou a leitura (HTTP {code}).", stages={"configured": True, "authenticated": True, "reachable": True, "usable": False},
                 next="Confira a Google Drive API no projeto do Google Cloud.", action=action)
    found = bool((_json(body) or {}).get("files"))
    return R("ok", f"Conta {c.get('email') or 'conectada'}: autorização renovada e API respondendo; catálogo do Lúmen {'encontrado' if found else 'ainda não publicado'}.",
             stages={"installed": True, "configured": True, "authenticated": True, "reachable": True, "usable": True},
             limit="Só leitura (lista de arquivos do app): nada é enviado nem apagado.")


# =====================================================================================================================
# 10. Mídia e placa de vídeo
# =====================================================================================================================

def check_imagegen(ctx):
    from . import imagegen
    f = imagegen.folder()
    if not imagegen.ready():
        return R("disabled", f"Gerador de imagens não baixado ({f}): capas desenhadas com emojis.", enabled=False,
                 action={"label": "Capas", "cat": "covers"})
    return R("ok", f"stable-diffusion.cpp (Vulkan) e os pesos do {imagegen.ENGINES[imagegen.DEFAULT_ENGINE]['label']} em {f}.",
             stages={"installed": True, "configured": True}, limit="Nenhuma imagem é gerada pelo diagnóstico.")


def check_music(ctx):
    from . import hardware, music
    on = bool(ctx.cfg.get("music_filter"))
    try:
        import onnxruntime
        providers = onnxruntime.get_available_providers()
        ort = onnxruntime.__version__
    except Exception:  # noqa: BLE001
        providers, ort = [], None
    ready = music.ready()
    gpu = "DirectML" if hardware.directml() else "CUDA" if "CUDAExecutionProvider" in providers else "CPU"
    detail = f"onnxruntime {ort or 'ausente'} ({gpu}); modelos {'baixados' if ready else 'não baixados'} ({music.SIZE})"
    if not on:
        return R("disabled", "Filtro de música desligado. " + detail + ".", enabled=False, action={"label": "Captura", "cat": "capture"})
    if not ort or not ready:
        return R("missing", detail + ".", stages={"configured": True, "installed": False}, next="Em Ajustes → Captura, baixe o filtro de música.",
                 action={"label": "Captura", "cat": "capture"})
    return R("ok", detail + ".", stages={"installed": True, "configured": True, "usable": True}, limit="Os modelos não são carregados aqui.")


def check_visual3d(ctx):
    mode = ctx.cfg.get("visual_3d")
    if mode == "off":
        return R("disabled", "Visualização 3D desligada.", enabled=False)
    import PIL
    return R("ok", f"Visualização 3D “{'animada' if mode == 'animated' else 'estática'}” com Pillow {PIL.__version__} (desenhada no PC).",
             stages={"installed": True, "configured": True})


def check_gpu(ctx):
    from . import hardware
    g = ctx.memo("nvidia", hardware.nvidia)
    if not g:
        return R("disabled", "Nenhuma GPU NVIDIA (nvidia-smi não respondeu): tudo roda na CPU.", enabled=False)
    used = f" · {_gb(g['used_mb'] * 1024 ** 2)} em uso" if g.get("used_mb") else ""
    return R("ok", f"{g['name']} · {_gb(g['vram_mb'] * 1024 ** 2)}{used} · driver {g.get('driver') or '?'}.", stages={"installed": True, "usable": True})


# =====================================================================================================================
# Execução
# =====================================================================================================================

CHECKS = [
    ("python", "Python do Lúmen", check_python),
    ("python", "Pacotes do requirements.txt", check_packages),
    ("python", "Pacotes de GPU (requirements-gpu.txt)", check_gpu_packages),
    ("python", "Pasta de dados do Lúmen", check_data),
    ("python", "Espaço para modelos", check_models_disk),
    ("python", "Cofre de credenciais do Windows", check_keyring),
    ("desktop", "Servidor local do Lúmen", check_server),
    ("desktop", "Janela do Lumen.exe (WebView2)", check_shell),
    ("desktop", "Microsoft Edge (capas, PDFs e /web)", check_edge),
    ("desktop", "Abrir com o Windows", check_autostart),
    ("audio", "Som do PC (captura loopback)", check_loopback),
    ("audio", "Microfone", check_microphone),
    ("audio", "Decodificador de áudio e vídeo (PyAV/FFmpeg)", check_decoder),
    ("audio", "Cancelamento de eco (conversa por voz)", check_echo),
    ("whisper", "Motores de transcrição", check_asr_runtime),
    ("whisper", "Modelo de transcrição escolhido", check_asr_model),
    ("whisper", "Aceleração CUDA", check_cuda),
    ("ollama", "Serviço Ollama", check_ollama),
    ("ollama", "Modelo do material das aulas", check_lesson_model),
    ("ollama", "Modelo de visão", check_vision_model),
    ("study", "Política de IA (só local)", check_policy),
    ("study", "Banco dos Estudos (SQLite FTS5)", check_study_db),
    ("study", "Modelos do chat", check_study_models),
    ("study", "Modelo de busca por significado", check_embed_model),
    ("study", "Perfil adulto", check_adult_model),
    ("study", "Pastas autorizadas", check_folders),
    ("study", "Pesquisa na internet (/web)", check_web_search),
    ("voicestudio", "Instalação do Voice Studio", check_vs_install),
    ("voicestudio", "Backend do Voice Studio", check_vs_backend),
    ("voicestudio", "Modelos de voz", check_vs_models),
    ("voicestudio", "Voz escolhida", check_vs_voice),
    ("voicestudio", "Chatterbox (voz local de reserva)", check_chatterbox),
    ("integrations", "Notion", check_notion),
    ("integrations", "Obsidian", check_obsidian),
    ("integrations", "Open Notebook", check_opennotebook),
    ("integrations", "HyperbookLM", check_hyperbooklm),
    ("integrations", "Perplexity", check_perplexity),
    ("protection", "Restic", check_restic),
    ("protection", "Repositório e chave da proteção", check_protection_repo),
    ("protection", "Cópia neste computador", check_protection_copies),
    ("protection", "Google Drive", check_drive),
    ("media", "Gerador de imagens das capas", check_imagegen),
    ("media", "Filtro de música externa", check_music),
    ("media", "Visualização 3D", check_visual3d),
    ("hardware", "GPU NVIDIA", check_gpu),
]


def redact(value, secrets):
    """Troca segredos conhecidos e formatos de token por ••••, em qualquer texto do resultado."""
    if isinstance(value, str):
        for s in sorted(secrets, key=len, reverse=True):
            value = value.replace(s, "••••")
        return _SECRET_RE.sub("••••", value)
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    return value


def _run_one(fn, ctx):
    t = time.monotonic()
    try:
        out = fn(ctx)
    # Sem resultado, não se sabe se o recurso era obrigatório: conta como obrigatório (nunca esconde uma falha no “100%”).
    except Down as e:
        out = R("unreachable", f"Sem resposta ({e.kind}).", required=True, stages={"reachable": False})
    except PermissionError as e:
        out = R("blocked", f"Acesso negado ({type(e).__name__}).", required=True, next="Confira as permissões e rode de novo.")
    except Exception as e:  # noqa: BLE001 - uma verificação quebrada nunca vira sucesso nem derruba as outras
        log.warning("diagnóstico: %s falhou (%s)", fn.__name__, type(e).__name__)
        out = R("unverified", f"A verificação falhou ({type(e).__name__}).", required=True, next="Rode o diagnóstico de novo; se repetir, veja o lumen.log.")
    out["ms"] = int((time.monotonic() - t) * 1000)
    return out


def run_diagnostics(request=None, checks=None, deadline=DEADLINE_S):
    """Roda todas as verificações em paralelo (cada uma com o prazo dela) dentro de `deadline` segundos.
    request: {"ua", "bind", "port"} do pedido HTTP, para conferir o servidor e a janela que chamaram."""
    ctx, started = Ctx(request), datetime.datetime.now().astimezone()
    checks = checks or CHECKS
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=12, thread_name_prefix="lumen-diag")
    futures = [pool.submit(_run_one, fn, ctx) for _, _, fn in checks]
    done, _ = concurrent.futures.wait(futures, timeout=deadline)
    pool.shutdown(wait=False, cancel_futures=True)
    items = {}
    for (cat, name, fn), fut in zip(checks, futures):
        out = fut.result() if fut in done else R("unverified", f"Tempo esgotado ({deadline} s): a verificação não terminou.",
                                                 required=True, next="Rode o diagnóstico de novo.")
        out.setdefault("ms", deadline * 1000)
        item = {"name": name, **out}
        item["status"] = _status(item)
        for key in ("action", "repair"):
            if not item.get(key):
                item.pop(key, None)
        items.setdefault(cat, []).append(item)
    categories = []
    for cid, title, icon in CATEGORIES:
        rows = items.get(cid) or []
        if not rows:
            continue
        status = "error" if any(i["status"] == "error" for i in rows) else "warn" if any(i["status"] == "warn" for i in rows) else "ok"
        categories.append({"id": cid, "title": title, "icon": icon, "status": status, "items": rows})
    out = {"timestamp": started.isoformat(timespec="seconds"), "categories": categories, **summarize(categories)}
    return redact(out, ctx.secrets)


def summarize(categories):
    rows = [i for c in categories for i in c["items"]]
    states = {s: sum(1 for i in rows if i["state"] == s) for s in STATE_LABEL}
    counts = {k: sum(1 for i in rows if i["status"] == k) for k in ("ok", "warn", "error", "info")}
    req = [i for i in rows if i["required"]]
    req_ok = sum(1 for i in req if i["state"] == "ok")
    opt_on = [i for i in rows if not i["required"] and i["enabled"]]
    opt_on_ok = sum(1 for i in opt_on if i["state"] == "ok")
    ran = sum(1 for i in rows if i["state"] not in ("unverified", "blocked"))
    operational = bool(req) and req_ok == len(req)
    readiness = int(req_ok * 100 / len(req)) if req else 0
    problems = [i for i in req if i["state"] != "ok"]
    if problems:
        state = "error" if any(i["status"] == "error" for i in problems) else "warn"
        message = (f"{req_ok} de {len(req)} verificações obrigatórias passaram. Pendentes: "
                   + "; ".join(f"{i['name']} ({STATE_LABEL[i['state']].lower()})" for i in problems[:6]) + ("…" if len(problems) > 6 else "") + ".")
    else:
        bad_opt = [i for i in opt_on if i["state"] != "ok"]
        state = "warn" if any(i["status"] == "warn" for i in bad_opt) else "ok"
        message = (f"Operacional: as {len(req)} verificações obrigatórias rodaram e passaram." +
                   (f" Opcionais ligadas: {opt_on_ok} de {len(opt_on)} ok." if opt_on else "") +
                   (f" {states['disabled']} recurso(s) opcional(is) desligado(s) — configuração opcional, não verificados." if states["disabled"] else ""))
    return {"score": readiness, "summary": {
        "total": len(rows), **counts, "state": state, "message": message, "operational": operational, "states": states,
        "coverage": {"checks": len(rows), "ran": ran, "unverified": states["unverified"], "blocked": states["blocked"],
                     "pct": int(ran * 100 / len(rows)) if rows else 0},
        "readiness": {"required": len(req), "required_ok": req_ok, "optional_enabled": len(opt_on), "optional_enabled_ok": opt_on_ok,
                      "optional_disabled": states["disabled"], "pct": readiness}}}
