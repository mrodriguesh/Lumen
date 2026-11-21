"""Grava o som que sai do PC (loopback do Windows) enquanto a aula toca em qualquer site ou app.

Nada é baixado: o áudio é capturado localmente, salvo em WAV 16 kHz mono e depois transcrito pelo Whisper.
"""
import json
import logging
import os
import re
import secrets
import shutil
import struct
import threading
import time
import warnings
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from . import AppError, store, vision

RATE = 48000                 # captura; gravado a 16 kHz (média de 3 amostras = filtro passa-baixa simples)
log = logging.getLogger("lumen")
_lock = threading.Lock()
_controls = threading.Lock()  # serializa os cliques da janela principal e da barra flutuante
_state = {"active": False}
_stop = threading.Event()
_pause = threading.Event()   # “Pausar captura”: a sessão continua, mas nada do som nem da tela é guardado
_thread = None
_watch = None  # vision.Watch da gravação atual (“Assistir a tela junto”); para junto com o som
_watch_lock = threading.Lock()


def active():
    return bool(_state.get("active"))


def status():
    """seconds = tempo gravado (sem as pausas; é o tempo da aula e das telas); elapsed = tempo real desde o início."""
    with _lock:
        st = {k: v for k, v in _state.items() if k not in ("path", "pauses")}
        pauses = list(_state.get("pauses") or [])
    w = _watch
    st["screens"] = w.counts() if w and st.get("active") else None
    if st.get("active"):
        now = time.time()
        st["elapsed"] = now - st["started"]
        st["paused_for"] = now - pauses[-1]["from"] if st.get("paused") and pauses else 0.0
        st["pause_count"] = len(pauses)
    else:
        st["recovered"] = _recovered()
    return st


def _set(**kw):
    with _lock:
        _state.update(kw)


def start(title=""):
    with _controls:
        _start(title)


def _start(title):
    global _thread, _watch
    if _state.get("active"):
        raise AppError("Já existe uma gravação em andamento.", "Pare a gravação atual antes de começar outra.")
    up = store.WORK / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(up).free < 500_000_000:
        raise AppError("Pouco espaço em disco para gravar.", "Libere pelo menos 500 MB (a gravação usa ≈ 115 MB por hora).")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "").strip()[:80] \
        or datetime.now().strftime("Gravação %Y-%m-%d %H-%M")
    path = up / f"{secrets.token_hex(4)}_{name}.wav"
    _stop.clear()
    _pause.clear()
    with _lock:
        _state.clear()
        _state.update(active=True, seconds=0.0, level=0.0, heard=False, error=None, path=path, paused=False,
                      started=time.time(), pauses=[])
    ready, failed = threading.Event(), []
    _thread = threading.Thread(target=_run, args=(path, ready, failed), daemon=True)
    _thread.start()
    ready.wait(15)
    if failed or not ready.is_set():
        _stop.set()
        path.unlink(missing_ok=True)
        raise AppError("Não foi possível acessar o som do PC.",
                       "Confira se há uma saída de áudio ativa (alto-falante ou fone) e tente de novo.")
    try:
        watch = _start_watch(path) if store.load_config()["watch_screen"] else None
    except Exception:  # opcional: se a tela não puder ser assistida, o som segue sendo gravado
        watch = None
    with _watch_lock:
        old, _watch = _watch, watch
    if old:  # não deveria sobrar nenhuma; se sobrou, não fica rodando sem dono
        old.stop()
    _save_session()
    with _lock:
        alive = _state.get("active")
    if not alive:  # o som parou enquanto a tela começava: não deixa a captura sozinha
        _stop_watch()


def _start_watch(path):
    """Assiste a tela junto: as telas novas vão para <gravação>.screens e são lidas enquanto a aula toca (com GPU e
    o modelo de visão instalado; senão, ao processar a aula)."""
    from . import jobs, transcribe

    def clock():
        with _lock:
            return _state.get("seconds", 0.0)
    live = transcribe.has_gpu() and vision.ready(vision.MODEL)
    return vision.Watch(path.with_suffix(".screens"), clock, vision.MODEL, paused=jobs.busy, live=live,
                        hold=_pause.is_set)


def _stop_watch():
    global _watch
    with _watch_lock:
        w, _watch = _watch, None
    if w:
        w.stop()


def _open_loopback():
    # O áudio do Windows (COM) precisa ser inicializado em cada thread que o usa; o soundcard só faz
    # isso na thread que o importou. Tudo da captura roda nesta thread.
    import soundcard as sc  # inicializa o COM na thread que o importa (só a primeira vez)
    if os.name == "nt":  # nas demais threads; se já estiver inicializado, devolve S_FALSE, inofensivo
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 0)
    return sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)


def _open_recorder():
    """Gravador do som do PC, já aberto. Com “Filtrar música externa”, o app de música aberto (Spotify…) fica de
    fora da gravação (lumen/loopback.py); se o Windows não permitir, grava todo o som, como sem o filtro."""
    mic = _open_loopback()
    if store.load_config()["music_filter"]:
        _set(music_filter=True)
        try:
            from . import loopback
            app = loopback.music_app() if os.name == "nt" else None
            if app:
                rec = loopback.recorder(app[0], RATE, 2)
                rec.__enter__()
                _set(isolated=app[1])
                log.info("filtro de música: sourceIsolationUsed=true (%s fora da gravação)", app[1])
                return rec
            log.info("filtro de música: sourceIsolationUsed=false (nenhum app de música aberto)")
        except Exception as e:  # noqa: BLE001 — Windows antigo ou áudio indisponível: segue com a gravação normal
            log.warning("filtro de música: isolamento indisponível (%s); gravando todo o som", type(e).__name__)
    rec = mic.recorder(samplerate=RATE, channels=2)
    rec.__enter__()
    return rec


def _run(path, ready, failed):
    try:
        try:
            rec = _open_recorder()  # abre já aqui para avisar falhas a start(); fechado no finally abaixo
        except Exception:
            failed.append(True)
            return
        finally:
            ready.set()
        try:
            _capture(rec, path)
        finally:
            rec.__exit__(None, None, None)
    except Exception as e:
        _set(error=f"A gravação foi interrompida ({type(e).__name__}).")
    finally:
        _set(active=False, level=0.0)
        _stop_watch()  # o som parou (fim, falha, disco cheio, saída do app): a tela para junto


def _capture(rec, path):
    with wave.open(str(path), "wb") as w, warnings.catch_warnings():
        warnings.simplefilter("ignore")  # avisos de descontinuidade do driver não afetam a fala
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE // 3)
        frames, heard = 0, False
        while not _stop.is_set():
            was = _pause.is_set()
            mono = rec.record(numframes=RATE // 4).mean(axis=1)
            if was or _pause.is_set():  # pausada: o som segue sendo lido (o Windows não acumula) e é descartado
                _set(level=0.0)
                continue
            n = len(mono) // 3 * 3
            out = np.clip(mono[:n].reshape(-1, 3).mean(axis=1), -1, 1)
            w.writeframes((out * 32767).astype("<i2").tobytes())
            frames += len(out)
            peak = float(np.abs(mono).max()) if len(mono) else 0.0
            heard = heard or peak > 0.005
            _set(seconds=frames / (RATE // 3), level=peak, heard=heard)
            if frames % (RATE // 3 * 30) < len(out) and shutil.disk_usage(path.parent).free < 200_000_000:
                _set(error="O disco ficou quase cheio; a gravação foi parada.")
                break


def pause():
    """Pausa a captura sem encerrar a sessão: o som e a tela desse intervalo não entram na aula, nem como silêncio
    (o tempo gravado e o das telas ficam parados). Não mexe no player nem em outro programa."""
    with _controls:
        with _lock:
            if not _state.get("active"):
                raise AppError("Nenhuma gravação em andamento.", "Clique em Iniciar gravação.")
            if _state["paused"]:
                return
            _pause.set()
            _state.update(paused=True, level=0.0)
            _state["pauses"].append({"at": round(_state["seconds"], 2), "from": time.time(), "to": None})
        _save_session()
        log.info("gravação pausada em %.0f s", _state["seconds"])


def resume():
    """Continua a mesma gravação, no mesmo arquivo, a partir de onde parou."""
    with _controls:
        with _lock:
            if not _state.get("active"):
                raise AppError("Nenhuma gravação em andamento.", "Clique em Iniciar gravação.")
            if not _state["paused"]:
                return
            last = _state["pauses"][-1]
            last["to"] = time.time()
            _state["paused"] = False
            _pause.clear()
        _save_session()
        log.info("gravação retomada (pausa de %.0f s)", last["to"] - last["from"])


# Cada gravação em andamento tem, ao lado do WAV, um <gravação>.session (início e pausas). Se o app fechar de
# repente, a gravação é reconhecida na próxima abertura e pode ser usada; o WAV continua válido (o wave regrava o
# cabeçalho a cada trecho). Parar ou descartar apaga o .session; sair do app guardando a gravação o mantém.
def _save_session():
    with _lock:
        if not _state.get("path"):
            return
        f = _state["path"].with_suffix(".session")
        data = {"started": _state["started"], "pauses": _state["pauses"]}
    try:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        os.replace(tmp, f)
    except OSError as e:
        log.warning("sessão da gravação não salva (%s)", type(e).__name__)


def _end_session(path=None):
    path = path or _state.get("path")
    if path:
        path.with_suffix(".session").unlink(missing_ok=True)


def _read_session():
    """A gravação mais recente de uma sessão que não terminou (o app fechou no meio, ou saiu guardando a gravação),
    ou None. A gravação em andamento não conta. Só olha a pasta de gravações do Lumen."""
    with _lock:
        live = _state.get("path") if _state.get("active") else None
    found = []
    for f in (store.WORK / "uploads").glob("*.session"):
        try:
            found.append((f.stat().st_mtime, f))
        except OSError:
            pass
    for _, f in sorted(found, reverse=True):
        path = f.with_suffix(".wav")
        if path == live:
            continue
        if not path.is_file():
            f.unlink(missing_ok=True)  # a gravação já foi usada ou apagada
            continue
        try:
            pauses = list(json.loads(f.read_text("utf-8")).get("pauses") or [])
        except (OSError, ValueError, TypeError, AttributeError):
            pauses = []  # o app fechou no meio de gravar o .session: a gravação vale do mesmo jeito
        return {"path": path, "pauses": pauses}
    return None


def _recovered():
    s = _read_session()
    if not s:
        return None
    seconds = max(0, s["path"].stat().st_size - 44) / 2 / (RATE // 3)
    return {"name": s["path"].name.split("_", 1)[-1], "seconds": seconds, "pauses": len(s["pauses"])}


def _repair_wav(path):
    """Acerta os tamanhos do cabeçalho pelo tamanho do arquivo (o app pode ter fechado no meio de um trecho)."""
    with open(path, "r+b") as f:
        head = f.read(44)
        if len(head) < 44 or head[:4] != b"RIFF" or head[8:16] != b"WAVEfmt " or head[36:40] != b"data":
            raise AppError("A gravação interrompida não pôde ser lida.", "Grave a aula de novo.")
        data = (path.stat().st_size - 44) // 2 * 2
        f.truncate(44 + data)
        f.seek(4)
        f.write(struct.pack("<I", 36 + data))
        f.seek(40)
        f.write(struct.pack("<I", data))
    return data / 2 / (RATE // 3)


def recover(use):
    """Usa (devolve como stop()) ou descarta a gravação de uma sessão que não terminou."""
    with _controls:
        if _state.get("active"):
            raise AppError("Há uma gravação em andamento.", "Pare a gravação atual antes.")
        s = _read_session()
        if not s:
            raise AppError("Nenhuma gravação interrompida.", "")
        path, screens = s["path"], s["path"].with_suffix(".screens")
        _end_session(path)
        try:
            ok = use and _repair_wav(path) >= 3
        except AppError:  # não é um WAV do Lumen: não serve para a aula; sai com a gravação e avisa
            path.unlink(missing_ok=True)
            shutil.rmtree(screens, ignore_errors=True)
            raise
        if ok:
            if screens.is_dir():
                vision.Shots(screens).close()  # o índice é gravado a cada tela; fecha a pasta como numa parada
            log.info("gravação interrompida recuperada (%d pausa(s))", len(s["pauses"]))
            return {"path": str(path), "name": path.name.split("_", 1)[1],
                    "warning": "Gravação recuperada de uma sessão que não terminou."}
        path.unlink(missing_ok=True)
        shutil.rmtree(screens, ignore_errors=True)
        if use:
            raise AppError("A gravação interrompida ficou curta demais.", "Grave a aula de novo.")
        return None


def stop(keep=False):
    """Para e devolve o arquivo gravado, pronto para seguir o fluxo de arquivo local. keep (ao sair do app): a
    gravação fica guardada e é oferecida na próxima abertura."""
    with _controls:
        return _finish_recording(keep)


def _finish_recording(keep=False):
    _stop.set()
    if _thread:
        _thread.join(timeout=5)
        if _thread.is_alive():
            raise AppError("O áudio ainda está sendo finalizado.", "Aguarde alguns segundos e tente parar de novo.")
    with _lock:
        if _state.get("paused"):  # parada durante a pausa: a pausa termina aqui
            _state["pauses"][-1]["to"] = time.time()
        _state["paused"] = False
        _pause.clear()
        path, st = _state.get("path"), dict(_state)
    _stop_watch()
    if st.get("pauses"):
        log.info("gravação: %d pausa(s), %.0f s fora da aula", len(st["pauses"]),
                 sum(p["to"] - p["from"] for p in st["pauses"]))
    if keep and path and path.exists() and st.get("heard"):
        _save_session()
        return {"path": str(path), "name": path.name.split("_", 1)[1], "warning": st.get("error")}
    _end_session()
    if not path or not path.exists():
        if path:
            shutil.rmtree(path.with_suffix(".screens"), ignore_errors=True)
        raise AppError("Nenhuma gravação encontrada.", "Clique em Iniciar gravação.")
    if not st.get("heard") or st.get("seconds", 0) < 3:
        shutil.rmtree(path.with_suffix(".screens"), ignore_errors=True)
        path.unlink(missing_ok=True)
        raise AppError("Nenhum som foi captado." if not st.get("heard") else "A gravação ficou curta demais.",
                       "Dê play na aula com o volume do PC ligado (não no mudo) e grave de novo.")
    return {"path": str(path), "name": path.name.split("_", 1)[1], "warning": st.get("error")}


def reveal(raw):
    """Mostra a gravação no Explorer (só arquivos de work/uploads; nunca um caminho qualquer vindo da página)."""
    path = Path(raw or "").resolve()
    if not raw or path.parent != (store.WORK / "uploads").resolve() or not path.is_file():
        raise AppError("A gravação não está mais no PC.", "Ela é apagada após o uso se “Guardar gravações” estiver desligado.")
    if os.name == "nt":
        import subprocess
        subprocess.Popen(f'explorer /select,"{path}"')  # caminho do próprio Lumen (sem aspas no nome)


def discard():
    with _controls:
        _discard_recording()


def _discard_recording():
    _stop.set()
    if _thread:
        _thread.join(timeout=5)
        if _thread.is_alive():
            raise AppError("O áudio ainda está sendo finalizado.", "Aguarde alguns segundos antes de descartar.")
    path = _state.get("path")
    _pause.clear()
    _set(paused=False)
    _stop_watch()
    _end_session()
    if path:
        path.unlink(missing_ok=True)
        shutil.rmtree(path.with_suffix(".screens"), ignore_errors=True)
    _set(seconds=0.0, heard=False, error=None, path=None)
