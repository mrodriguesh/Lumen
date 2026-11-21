"""Instalar / reparar o que o Diagnóstico achou faltando (D187). Só roda depois do clique do estudante.

O que pode ser feito vem só de manifestos e lockfiles do próprio projeto, nunca de texto do diagnóstico nem do pedido:
- "python": os pacotes do requirements.txt que NÃO estão instalados, na versão fixada, com o pip do próprio ambiente
  (sys.executable). Versão diferente não é trocada com o Lúmen aberto (arquivos em uso): o caminho é o Iniciar Lumen.bat.
  Opcionais (OPTIONAL_DISTS) nunca são instalados só para subir a nota.
- "hyperbooklm": o HyperbookLM deste PC (repositório conferido pela rota da ponte). Dependências do package.json
  conferidas contra o yarn.lock e o node_modules; faltando, instala com o Yarn 1 e --frozen-lockfile (o lockfile não muda);
  depois sobe o `npm run dev` existente na porta salva (ou na primeira livre de 3000–3010, se a salva é de outro
  programa) e só dá por pronto quando /api/lumen responde como a ponte do HyperbookLM. Um HyperbookLM já de pé é
  reaproveitado; outro programa numa porta nunca é parado.

Nunca: elevação de administrador, comandos vindos de texto, sobrescrever .env.local, o código de pareamento, a pasta
.lumen (fontes), lockfiles, backups ou dados do estudante. Cancelar encerra só o que este reparo iniciou e ainda não
ficou pronto."""
import importlib.metadata
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from . import OWN_ENV, AppError, store

log = logging.getLogger("lumen")
ROOT = Path(__file__).resolve().parent.parent
HB_REPO = Path(os.environ.get("LUMEN_HYPERBOOKLM_DIR") or r"D:\Aplicativos\hyperbooklm")
HB_PORTS = range(3000, 3011)
YARN_CLASSIC = "yarn@1.22.22"  # o yarn.lock dele é “yarn lockfile v1”: Yarn 1 (via corepack quando o yarn não está instalado)
INSTALL_S, HEALTH_S = 1800, 180   # instalar dependências; o `next dev` compilar e a ponte responder
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)

_LOCK = threading.RLock()
_cancel = threading.Event()
_job = {"id": None, "status": "idle", "title": "", "steps": [], "message": "", "action": "", "started": None, "finished": None}
_procs = []  # processos que ESTE reparo iniciou e que cancelar pode encerrar


# --- o que falta (só leituras) -----------------------------------------------------------------------------------

def python_missing():
    """[(dist, versão)] do requirements.txt que não estão instalados (os opcionais ficam de fora)."""
    from .diagnostics import OPTIONAL_DISTS, _pins
    out = []
    for dist, want in _pins("requirements.txt") or []:
        if dist in OPTIONAL_DISTS:
            continue
        try:
            importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            out.append((dist, want))
    return out


def yarn_lock(text):
    """yarn lockfile v1 → {nome: {faixa: versão}}."""
    out, specs = {}, []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            specs = [s.strip().strip('"') for s in line.rstrip()[:-1].split(",")]
        elif specs and line.startswith("  version "):
            version = line.split(None, 1)[1].strip().strip('"')
            for spec in specs:
                at = spec.rfind("@")
                if at > 0:
                    out.setdefault(spec[:at], {})[spec[at + 1:]] = version
            specs = []
    return out


def hb_repo(repo=None):
    """O repositório do HyperbookLM com a ponte do Lúmen, ou None (nunca uma pasta qualquer)."""
    repo = Path(repo or HB_REPO)
    ok = (repo / "package.json").is_file() and (repo / "app" / "api" / "lumen" / "route.ts").is_file()
    return repo if ok else None


def hb_deps(repo):
    """{"lock", "checked", "missing", "mismatch"}: as dependências do package.json contra o yarn.lock e o node_modules."""
    pkg = json.loads((repo / "package.json").read_text("utf-8"))
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    lockfile = repo / "yarn.lock"
    lock = yarn_lock(lockfile.read_text("utf-8")) if lockfile.is_file() else {}
    missing, mismatch = [], []
    for name, rng in sorted(deps.items()):
        want = (lock.get(name) or {}).get(rng)
        try:
            have = json.loads((repo / "node_modules" / name / "package.json").read_text("utf-8")).get("version")
        except (OSError, ValueError):
            have = None
        if not have:
            missing.append(name)
        elif want and have != want:
            mismatch.append(f"{name} {have} (lock {want})")
    return {"lock": lockfile.name if lockfile.is_file() else None, "checked": len(deps), "missing": missing, "mismatch": mismatch}


def _bridge(url, timeout=2):
    """O que responde em url/api/lumen: "hyperbooklm" | "other" | "down". Só leitura, sem o código de pareamento."""
    from .diagnostics import Down, _json, http
    try:
        code, body, _ = http(url.rstrip("/") + "/api/lumen", headers={"Accept": "application/json"}, timeout=timeout)
    except Down:
        return "down"
    info = _json(body) if code == 200 else None
    return "hyperbooklm" if isinstance(info, dict) and info.get("app") == "hyperbooklm" else "other"


def _port(url):
    return urllib.parse.urlsplit(url).port or 80


def _url(port):
    return f"http://127.0.0.1:{port}"


def _installer():
    """O Yarn 1 para o yarn.lock dele: o instalado, senão pelo corepack (que baixa só o Yarn fixado). None se nenhum."""
    yarn = shutil.which("yarn")
    if yarn:
        return [yarn, "install", "--frozen-lockfile", "--non-interactive"]
    corepack = shutil.which("corepack")
    if corepack:
        return [corepack, YARN_CLASSIC, "install", "--frozen-lockfile", "--non-interactive"]
    return None


def _pip_cmd(specs):
    """O pip do próprio ambiente do Lúmen, só com nomes==versões do requirements.txt (sem administrador)."""
    return [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *specs]


def _npm_dev(port):
    npm = shutil.which("npm")
    if not npm:
        raise AppError("O npm não foi encontrado neste PC.", "Instale o Node.js LTS (nodejs.org) e clique de novo.")
    return [npm, "run", "dev", "--", "-p", str(port)]


def plan(cfg=None):
    """Os reparos possíveis agora, conferidos de novo a cada pedido (o cliente só escolhe o id)."""
    cfg = cfg or store.load_config()
    out = []
    missing = python_missing()
    if missing:
        specs = [f"{d}=={v}" for d, v in missing]
        out.append({"id": "python", "title": "Instalar pacotes do Lúmen que faltam",
                    "detail": f"{len(specs)} pacote(s) do requirements.txt não instalado(s): {', '.join(specs)}.",
                    "commands": [" ".join([Path(sys.executable).name, "-m", "pip", "install", *specs])]})
    repo = hb_repo()
    if cfg.get("hyperbooklm_on") and repo and _bridge(cfg["hyperbooklm_url"]) != "hyperbooklm":
        deps = hb_deps(repo)
        need = deps["missing"] or deps["mismatch"]
        cmds = ([" ".join(Path(c).name if i == 0 else c for i, c in enumerate(_installer() or ["yarn", "install", "--frozen-lockfile"]))] if need else [])
        cmds.append(f"npm run dev -- -p {_port(cfg['hyperbooklm_url'])}  (em {repo}, só no 127.0.0.1)")
        out.append({"id": "hyperbooklm", "title": ("Instalar dependências e iniciar" if need else "Iniciar") + " o HyperbookLM",
                    "detail": (f"Faltam {len(deps['missing'])} e diferem {len(deps['mismatch'])} dependência(s) do {deps['lock'] or 'package.json'}. " if need
                               else f"Dependências completas ({deps['checked']} conferidas com o {deps['lock'] or 'package.json'}); o servidor está parado. ")
                              + "O .env.local, o código de pareamento e as fontes (.lumen) não são tocados.",
                    "commands": cmds})
    return out


# --- a tarefa ----------------------------------------------------------------------------------------------------

def view():
    with _LOCK:
        job = json.loads(json.dumps(_job))
    return {"job": job, "plan": plan() if job["status"] != "running" else []}


def action(body):
    what = (body or {}).get("action")
    if what == "cancel":
        cancel()
        return view()
    if what != "start":
        raise AppError("Ação de reparo desconhecida.")
    start(str((body or {}).get("id") or ""))
    return view()


def start(rid):
    with _LOCK:
        if _job["status"] == "running":
            raise AppError("Já há um reparo em andamento.", "Espere terminar ou cancele.")
        item = next((p for p in plan() if p["id"] == rid), None)
        if not item:
            raise AppError("Este reparo não é mais necessário ou não é permitido.", "Rode o diagnóstico de novo.")
        _cancel.clear()
        _procs.clear()
        _job.update(id=rid, status="running", title=item["title"], steps=[], message="", action="",
                    started=time.time(), finished=None)
    threading.Thread(target=_run, args=(rid,), daemon=True, name="lumen-repair").start()


def cancel():
    _cancel.set()
    with _LOCK:
        procs = list(_procs)
    for p in procs:
        _kill(p)


def _kill(p):
    """Encerra um processo que ESTE reparo iniciou, com os filhos dele (npm → node). Nunca outro."""
    if p.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=15, creationflags=NO_WINDOW)
        else:
            p.kill()
    except (OSError, subprocess.SubprocessError):
        pass


def _step(key, label, state="running", detail=""):
    with _LOCK:
        for s in _job["steps"]:
            if s["id"] == key:
                s.update(state=state, detail=detail)
                return
        _job["steps"].append({"id": key, "label": label, "state": state, "detail": detail})


def _finish(status, message, action=""):
    with _LOCK:
        for s in _job["steps"]:
            if s["state"] == "running":
                s["state"] = "cancelled" if status == "cancelled" else "failed"
        _job.update(status=status, message=message, action=action, finished=time.time())
        _procs.clear()


class Cancelled(Exception):
    pass


def _check():
    if _cancel.is_set():
        raise Cancelled()


def _log(name):
    folder = store.DATA / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"repair-{name}.log"


def _spawn(args, cwd, name, detach=False, env=None):
    """Sem janela e sem shell (os argumentos são fixos); a saída vai para DATA/logs. detach: sai do grupo de processos do
    Lumen.exe para continuar aberto depois dele (como os serviços do Open Notebook)."""
    out = open(_log(name), "ab")
    base = {k: v for k, v in os.environ.items()
            if not k.startswith("LUMEN_") and k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV") and k not in OWN_ENV}
    kw = {"cwd": str(cwd), "env": {**base, **(env or {})}, "stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT, "shell": False}
    flags = NO_WINDOW | GROUP
    try:
        p = subprocess.Popen(args, creationflags=flags | (BREAKAWAY if detach else 0), **kw)
    except PermissionError:  # Lumen.exe sem saída do grupo: o processo fecha junto com ele
        p = subprocess.Popen(args, creationflags=flags, **kw)
    finally:
        out.close()
    with _LOCK:
        _procs.append(p)
    return p


def _wait(p, seconds):
    """Espera o processo terminar, com cancelamento. Devolve o código de saída; tempo esgotado: None (e o encerra)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _cancel.is_set():  # antes de olhar a saída: um processo encerrado pelo cancelamento não é “falhou”
            _kill(p)
            raise Cancelled()
        if p.poll() is not None:
            if _cancel.is_set():
                raise Cancelled()
            return p.returncode
        time.sleep(0.3)
    _kill(p)
    return None


def _run(rid):
    try:
        (_run_python if rid == "python" else _run_hyperbooklm)()
    except Cancelled:
        _finish("cancelled", "Cancelado. O que este reparo tinha iniciado foi encerrado; nada mais foi alterado.")
    except AppError as e:
        _finish("failed", str(e), e.action)
    except Exception as e:  # noqa: BLE001 - o estado nunca fica “em andamento” para sempre
        log.warning("reparo %s falhou: %s", rid, type(e).__name__)
        _finish("failed", f"O reparo falhou ({type(e).__name__}).", "Veja o lumen.log e tente de novo.")


def _run_python():
    missing = python_missing()
    if not missing:
        _step("check", "Conferir o requirements.txt", "done", "Nada faltando.")
        return _finish("done", "Nenhum pacote faltava.")
    specs = [f"{d}=={v}" for d, v in missing]
    _step("check", "Conferir o requirements.txt", "done", ", ".join(specs))
    _step("install", "Instalar com o pip do Lúmen")
    p = _spawn(_pip_cmd(specs), ROOT, "pip")
    code = _wait(p, INSTALL_S)
    if code != 0:
        raise AppError("O pip não concluiu a instalação" + (" no prazo." if code is None else f" (código {code})."),
                       f"Veja {_log('pip')} e rode o Iniciar Lumen.bat com o Lúmen fechado.")
    _step("install", "Instalar com o pip do Lúmen", "done", ", ".join(specs))
    _step("verify", "Conferir de novo")
    importlib.invalidate_caches()
    left = python_missing()
    if left:
        raise AppError("Ainda faltam: " + ", ".join(d for d, _ in left) + ".", "Rode o Iniciar Lumen.bat com o Lúmen fechado.")
    _step("verify", "Conferir de novo", "done", "Todos instalados na versão fixada.")
    _finish("done", "Pacotes instalados e conferidos. Reabra o Lúmen para carregá-los.")


def _run_hyperbooklm():
    cfg = store.load_config()
    repo = hb_repo()
    _step("repo", "Conferir o repositório do HyperbookLM")
    if not repo:
        raise AppError(f"O HyperbookLM não foi encontrado em {HB_REPO} (com a ponte app/api/lumen).", "Instale-o nessa pasta conforme o README do Lúmen.")
    deps = hb_deps(repo)
    _step("repo", "Conferir o repositório do HyperbookLM", "done", f"{repo} · {deps['checked']} dependências conferidas com o {deps['lock'] or 'package.json'}")
    _check()
    if deps["missing"] or deps["mismatch"]:
        if not deps["lock"]:
            raise AppError("Faltam dependências e não há yarn.lock para instalar versões fixadas.", "Restaure o yarn.lock do repositório do HyperbookLM.")
        cmd = _installer()
        if not cmd:
            raise AppError("O HyperbookLM usa yarn.lock e nem o Yarn nem o corepack estão neste PC.",
                           "Instale o Node.js LTS (traz o corepack) ou o Yarn 1 e clique de novo.")
        _step("deps", "Instalar as dependências travadas (yarn.lock)", "running", " ".join([Path(cmd[0]).name, *cmd[1:]]))
        code = _wait(_spawn(cmd, repo, "hyperbooklm-install", env={"COREPACK_ENABLE_DOWNLOAD_PROMPT": "0", "COREPACK_ENABLE_AUTO_PIN": "0"}), INSTALL_S)
        if code != 0:
            raise AppError("A instalação das dependências não terminou" + (" no prazo." if code is None else f" (código {code})."),
                           f"Veja {_log('hyperbooklm-install')}. O yarn.lock e o .env.local não foram alterados.")
        left = hb_deps(repo)
        if left["missing"] or left["mismatch"]:
            raise AppError("Depois da instalação ainda faltam dependências: " + ", ".join(left["missing"] + left["mismatch"])[:300], f"Veja {_log('hyperbooklm-install')}.")
        _step("deps", "Instalar as dependências travadas (yarn.lock)", "done", f"{left['checked']} conferidas")
    _check()
    # A porta: a salva, se livre ou já for o HyperbookLM; se outro programa a usa (ou o HyperbookLM está em outra), outra.
    _step("port", "Escolher a porta")
    saved = cfg["hyperbooklm_url"]
    from . import hyperbooklm
    found = hyperbooklm.detect()
    if found:
        _step("port", "Escolher a porta", "done", f"O HyperbookLM já está de pé em {found}: reaproveitado (nada foi iniciado).")
        return _ready(found, saved, started=False)
    target = saved if _bridge(saved, timeout=1) == "down" else next((_url(p) for p in HB_PORTS if _bridge(_url(p), timeout=1) == "down"), None)
    if not target:
        raise AppError("As portas 3000 a 3010 estão todas ocupadas por outros programas.", "Feche um deles (o Lúmen nunca encerra outro programa) e tente de novo.")
    _step("port", "Escolher a porta", "done", target + ("" if target == saved else f" ({saved} é usada por outro programa, que não foi mexido)"))
    _step("start", "Iniciar npm run dev")
    p = _spawn(_npm_dev(_port(target)), repo, "hyperbooklm-dev", detach=True)
    _step("start", "Iniciar npm run dev", "done", f"processo {p.pid} · log em {_log('hyperbooklm-dev')}")
    _step("health", "Esperar a ponte responder (/api/lumen)")
    end = time.monotonic() + HEALTH_S
    while True:
        if _cancel.is_set():
            _kill(p)
            raise Cancelled()
        state = _bridge(target, timeout=2)
        if state == "hyperbooklm":
            break
        if p.poll() is not None:
            raise AppError(f"O npm run dev terminou antes de a ponte responder (código {p.returncode}).", f"Veja {_log('hyperbooklm-dev')}.")
        if time.monotonic() > end:
            _kill(p)
            raise AppError(f"A ponte não respondeu em {HEALTH_S} s; o processo iniciado foi encerrado.", f"Veja {_log('hyperbooklm-dev')} e tente de novo.")
        time.sleep(1)
    with _LOCK:  # pronto: o servidor fica aberto; cancelar depois disto não o encerra
        _procs.clear()
    return _ready(target, saved, started=True)


def _ready(url, saved, started):
    _step("health", "Esperar a ponte responder (/api/lumen)", "done", f"{url}/api/lumen respondeu como a ponte do HyperbookLM")
    if url != saved:
        with store.LOCK:
            cfg = store.load_config()
            cfg["hyperbooklm_url"] = url  # só o endereço muda; o código de pareamento e o .env.local ficam
            store.save_config(cfg)
        _step("config", "Atualizar o endereço salvo", "done", f"{saved} → {url}")
    from . import hyperbooklm
    v = hyperbooklm.view()
    if v["state"] == "connected":
        extra = "" if (v.get("features") or {}).get("text") else " Falta a chave de IA de texto no .env.local dele (você configura lá; o Lúmen não lê nem grava)."
        return _finish("done", ("HyperbookLM iniciado e conectado." if started else "HyperbookLM já estava de pé e está conectado.") + extra)
    if v["state"] in ("pairing", "unauthorized"):
        return _finish("done", "A ponte respondeu, mas falta parear: em Integrações → HyperbookLM, gere o código, cole a linha no .env.local dele e reinicie-o.",
                       "Integrações → HyperbookLM")
    return _finish("done", f"A ponte respondeu em {url}. {v.get('message') or ''}".strip())
