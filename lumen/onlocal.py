"""Open Notebook instalado neste PC (instalação nativa no Windows): inicia, só a pedido, os serviços que estão parados —
banco (SurrealDB), API, worker e interface, nessa ordem. Caminhos fixos e argumentos em lista (nada vem da interface),
tudo em 127.0.0.1, sem janela de console, e a saída de cada serviço vai para a pasta de logs. Quem já responde é
reaproveitado; porta ocupada por outro programa vira um erro claro e ninguém é encerrado. Os serviços continuam abertos
quando o Lúmen fecha: o worker pode estar processando.

shortcut: os caminhos são os desta instalação; viram ajustes se o Open Notebook mudar de pasta."""
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

from . import OWN_ENV, AppError, store
from .opennotebook import _OPENER

log = logging.getLogger("lumen")
REPO = Path(r"D:\Aplicativos\open-notebook")
SURREAL = Path(r"D:\Aplicativos\OpenNotebookTools\SurrealDB\surreal.exe")
# LUMEN_ON_DATA: outra pasta de banco e de logs, para testar com um banco descartável sem tocar no de verdade
DATA = Path(os.environ.get("LUMEN_ON_DATA") or r"D:\Aplicativos\OpenNotebookData")
LOGS = DATA / "logs"
DB, API, UI = "http://127.0.0.1:8000", "http://127.0.0.1:5055", "http://127.0.0.1:3000"
UI_PORTS = tuple(range(3000, 3011))
STEPS = (("db", "Banco de dados"), ("api", "API"), ("worker", "Worker"), ("ui", "Interface"))
_LOCK = threading.Lock()
# A última partida, para a interface acompanhar. tied: algum serviço ficou preso ao Lúmen (fecha junto com ele).
_run = {"active": False, "error": "", "tied": False, "steps": []}


def _port(url):
    return int(url.rsplit(":", 1)[1])


def _busy(url):
    """Há alguém escutando? (No Windows, uma porta fechada demora ~2 s para recusar: o limite curto evita essa espera.)"""
    u = urllib.parse.urlsplit(url)
    try:
        with socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)), timeout=0.3):
            return True
    except OSError:
        return False


def _get(url, timeout=3):
    try:
        with _OPENER.open(url, timeout=timeout) as r:
            return r.read(20000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


def _json(url, timeout=3):
    try:
        data = json.loads(_get(url, timeout))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


# Quem está na porta é mesmo o componente do Open Notebook?
def _is_db():
    return _get(DB + "/version").startswith("surrealdb")


def _db_status():
    return _json(API + "/api/config").get("dbStatus")  # None: quem responde não é a API do Open Notebook


def _same_api(a, b):
    norm = lambda u: str(u or "").strip().rstrip("/").replace("//localhost:", "//127.0.0.1:").lower()  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


def ui_state(url=UI, api=API):
    """"ok" (é a interface do Open Notebook), "down" (ninguém escuta) ou "other" (escuta, mas /config não aponta para a API
    configurada: outro Next.js na porta, ou a interface ainda compilando). Só o apiUrl igual ao da API vale."""
    if not _busy(url):
        return "down"
    # em modo dev, a primeira resposta espera a rota compilar
    return "ok" if _same_api(_json(url + "/config", timeout=8).get("apiUrl"), api) else "other"


def is_ui(url=UI, api=API):
    return ui_state(url, api) == "ok"


def _ui_url(port):
    return f"http://127.0.0.1:{port}"


def find_ui(first=UI, api=API):
    """Endereço de uma interface do Open Notebook já de pé (o salvo primeiro, depois as portas 3000–3010 no loopback), ou None."""
    if urllib.parse.urlsplit(first).hostname not in ("127.0.0.1", "localhost"):
        return None
    for url in dict.fromkeys([first, *map(_ui_url, UI_PORTS)]):
        if _busy(url) and is_ui(url, api):
            return url
    return None


def remember_ui(url):
    """Guarda o endereço real da interface (e só ele) na configuração do Lúmen."""
    with store.LOCK:
        cfg = store.load_config()
        if cfg["opennotebook_ui"] != url:
            cfg["opennotebook_ui"] = url
            store.save_config(cfg)


def _ps(script):
    """Uma consulta ao Windows (script fixo; nada da interface entra aqui). Vazio se não deu para consultar."""
    try:
        return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                              text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _worker_running():
    return bool(_ps("(Get-CimInstance Win32_Process -Filter \"Name like 'python%' and CommandLine like "
                    "'%surreal_commands.cli.worker%'\").ProcessId"))


def _owner(url):
    name = _ps(f"(Get-Process -Id (Get-NetTCPConnection -LocalPort {_port(url)} -State Listen)[0].OwningProcess).ProcessName")
    return name.splitlines()[0][:60] if name else "programa não identificado"


def _dotenv():
    out = {}
    for line in (REPO / ".env").read_text("utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            out[key.strip()] = value.strip().strip("\"'")
    return out


def available(cfg):
    """Há uma instalação nativa neste PC e a integração aponta para ela?"""
    return (cfg["opennotebook_url"].replace("//localhost:", "//127.0.0.1:") == API and SURREAL.is_file()
            and (REPO / "run_api.py").is_file() and (REPO / ".env").is_file() and (REPO / "frontend" / "package.json").is_file())


def view(cfg):
    """Para o cartão de Integrações: dá para iniciar por aqui, o que está parado e a partida em curso."""
    out = {"available": available(cfg), "missing": [], "run": status()}
    if out["available"] and not out["run"]["active"]:
        closed = {"db": not _busy(DB), "api": not _busy(API), "ui": not find_ui(cfg["opennotebook_ui"])}
        closed["worker"] = not closed["api"] and not _worker_running()  # com a API parada, a partida confere o worker
        out["missing"] = [label for key, label in STEPS if closed[key]]
    return out


def status():
    with _LOCK:
        return {**_run, "steps": [dict(s) for s in _run["steps"]]}


def _set(key, state, detail=""):
    with _LOCK:
        next(s for s in _run["steps"] if s["id"] == key).update(state=state, detail=detail)


def _spawn(name, args, cwd, env):
    """Inicia um serviço sem janela, com a saída no log dele, fora do grupo de processos que fecha junto com o Lúmen."""
    LOGS.mkdir(parents=True, exist_ok=True)
    base = {k: v for k, v in os.environ.items()
            if not k.startswith("LUMEN_") and k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHON_KEYRING_BACKEND")
            and k not in OWN_ENV}
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(LOGS / f"lumen-{name}.log", "ab") as out:
        kw = {"cwd": str(cwd), "env": {**base, **env}, "stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT,
              "shell": False}
        try:
            return subprocess.Popen(args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
        except PermissionError:  # Lumen.exe anterior a esta função: não deixa sair do grupo, e o serviço fecha com ele
            log.warning("open notebook: %s iniciado dentro do grupo do Lúmen (fecha junto com ele)", name)
            with _LOCK:
                _run["tied"] = True  # a interface avisa: a promessa de continuar aberto não vale para este
            return subprocess.Popen(args, creationflags=flags, **kw)


def _wait(ok, seconds, proc=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if ok():
            return True
        if proc is not None and proc.poll() is not None:  # o processo saiu: não adianta esperar
            return ok()
        time.sleep(0.5)
    return False


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise AppError(f"O programa “{name}” não foi encontrado neste PC.", "Ele faz parte da instalação nativa do Open Notebook.")
    return path


def _ensure(key, what, url, present, ready, args, cwd, env, timeout, note=""):
    """Um serviço com porta: reaproveita o que já responde, recusa a porta ocupada por outro programa, inicia o que falta."""
    if _busy(url):
        if not _wait(present, 15):
            raise AppError(f"A porta {_port(url)} está ocupada por outro programa ({_owner(url)}), que não é {what}.",
                           "Nada foi encerrado. Feche esse programa e tente de novo.")
        if not _wait(ready, 60):
            raise AppError(f"{what[0].upper() + what[1:]} está aberta, mas não alcança o banco de dados.",
                           f"Feche-a e tente de novo. Logs em {LOGS}.")
        return "reused"
    _set(key, "starting", note)
    proc = _spawn(key, args(), cwd, env())
    if not _wait(ready, timeout, proc):
        raise AppError(f"{what[0].upper() + what[1:]} não iniciou.", f"Veja o log: {LOGS / f'lumen-{key}.log'}")
    return "started"


def _start_db():
    def env():  # as credenciais do .env vão pelo ambiente do processo: nem na linha de comando nem no log
        cfg = _dotenv()
        return {"SURREAL_USER": cfg.get("SURREAL_USER") or "root", "SURREAL_PASS": cfg.get("SURREAL_PASSWORD") or "root"}
    return _ensure("db", "o banco de dados do Open Notebook (SurrealDB)", DB, _is_db, _is_db,
                   lambda: [str(SURREAL), "start", "--bind", "127.0.0.1:8000", f"rocksdb:{DATA / 'surrealdb'}"], SURREAL.parent, env, 60)


def _start_api():
    return _ensure("api", "a API do Open Notebook", API, lambda: _db_status() is not None, lambda: _db_status() == "online",
                   lambda: [_tool("uv"), "run", "--env-file", ".env", "run_api.py"], REPO,
                   lambda: {"API_RELOAD": "false", "API_HOST": "127.0.0.1", "API_PORT": "5055"}, 300,
                   "na primeira vez demora mais: o banco é preparado")


def _start_worker():
    if _worker_running():
        return "reused"
    _set("worker", "starting")
    proc = _spawn("worker", [_tool("uv"), "run", "--env-file", ".env", "python", "-m", "surreal_commands.cli.worker",
                             "--import-modules", "commands"], REPO, {"PYTHONPATH": str(REPO), "PYTHONIOENCODING": "utf-8"})
    time.sleep(8)  # o worker não tem porta: basta continuar de pé depois de carregar
    if proc.poll() is not None:
        raise AppError("O worker do Open Notebook não iniciou.", f"Veja o log: {LOGS / 'lumen-worker.log'}")
    return "started"


def _start_ui():
    """Reaproveita a interface do Open Notebook onde ela estiver; senão a inicia na primeira porta livre (3000 é de outro
    programa, p. ex. o HyperbookLM, que nunca é tocado). O endereço real é guardado."""
    url = find_ui()
    if url:
        remember_ui(url)
        return "reused"
    port = next((p for p in UI_PORTS if not _busy(_ui_url(p))), None)
    if port is None:
        raise AppError(f"As portas {UI_PORTS[0]} a {UI_PORTS[-1]} estão ocupadas por outros programas.",
                       "Nada foi encerrado. Feche um deles ou inicie a interface do Open Notebook por fora e informe o endereço.")
    url = _ui_url(port)
    _set("ui", "starting", "" if url == UI else f"a porta {_port(UI)} é de outro programa; usando {port}")
    proc = _spawn("ui", [_tool("npm"), "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(port)], REPO / "frontend", {})
    if not _wait(lambda: is_ui(url), 180, proc):
        raise AppError("A interface do Open Notebook não iniciou.", f"Veja o log: {LOGS / 'lumen-ui.log'}")
    remember_ui(url)
    return "started"


_STARTERS = {"db": _start_db, "api": _start_api, "worker": _start_worker, "ui": _start_ui}


def start(cfg):
    """“Iniciar Open Notebook”: uma partida por vez (repetir o clique só devolve o andamento), em segundo plano."""
    with _LOCK:
        if _run["active"]:
            return {**_run, "steps": [dict(s) for s in _run["steps"]]}
        if not available(cfg):
            raise AppError("Só dá para iniciar por aqui o Open Notebook instalado neste PC, no endereço padrão.",
                           "Confira o endereço da API (http://127.0.0.1:5055) ou inicie o seu Open Notebook por fora.")
        _run.update(active=True, error="", tied=False, steps=[{"id": k, "label": v, "state": "pending", "detail": ""} for k, v in STEPS])
    threading.Thread(target=_work, daemon=True).start()
    return status()


def _work():
    key = STEPS[0][0]
    try:
        for key, _label in STEPS:
            _set(key, "checking")
            _set(key, _STARTERS[key]())
        error = ""
    except AppError as e:
        error = f"{e} {e.action}".strip()
    except Exception as e:  # noqa: BLE001 — a partida nunca derruba o servidor do Lúmen
        log.error("open notebook: erro inesperado ao iniciar %s (%s)", key, type(e).__name__)
        error = f"Erro inesperado ao iniciar ({type(e).__name__})."
    if error:
        _set(key, "failed", error)
    with _LOCK:
        _run.update(active=False, error=error)
