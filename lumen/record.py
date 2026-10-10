"""Grava o som que sai do PC (loopback do Windows) enquanto a aula toca em qualquer site ou app.

Nada é baixado: o áudio é capturado localmente, salvo em WAV 16 kHz mono e depois transcrito pelo Whisper.
"""
import os
import re
import secrets
import shutil
import threading
import warnings
import wave
from datetime import datetime

import numpy as np

from . import AppError, store, vision

RATE = 48000                 # captura; gravado a 16 kHz (média de 3 amostras = filtro passa-baixa simples)
_lock = threading.Lock()
_controls = threading.Lock()  # serializa os cliques da janela principal e da barra flutuante
_state = {"active": False}
_stop = threading.Event()
_thread = None
_watch = None  # vision.Watch da gravação atual (“Assistir a tela junto”); para junto com o som
_watch_lock = threading.Lock()


def status():
    with _lock:
        st = {k: v for k, v in _state.items() if k != "path"}
    w = _watch
    st["screens"] = w.counts() if w and st.get("active") else None
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
    with _lock:
        _state.clear()
        _state.update(active=True, seconds=0.0, level=0.0, heard=False, error=None, path=path)
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
    return vision.Watch(path.with_suffix(".screens"), clock, vision.MODEL, paused=jobs.busy, live=live)


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


def _run(path, ready, failed):
    try:
        try:
            rec = _open_loopback().recorder(samplerate=RATE, channels=2)
            rec.__enter__()  # abre já aqui para avisar falhas a start(); fechado no finally abaixo
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
            mono = rec.record(numframes=RATE // 4).mean(axis=1)
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


def stop():
    """Para e devolve o arquivo gravado, pronto para seguir o fluxo de arquivo local."""
    with _controls:
        return _finish_recording()


def _finish_recording():
    _stop.set()
    if _thread:
        _thread.join(timeout=5)
        if _thread.is_alive():
            raise AppError("O áudio ainda está sendo finalizado.", "Aguarde alguns segundos e tente parar de novo.")
    with _lock:
        path, st = _state.get("path"), dict(_state)
    _stop_watch()
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
    _stop_watch()
    if path:
        path.unlink(missing_ok=True)
        shutil.rmtree(path.with_suffix(".screens"), ignore_errors=True)
    _set(seconds=0.0, heard=False, error=None, path=None)
