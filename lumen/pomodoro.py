"""Pomodoro: um timer só, guardado aqui, para a barra flutuante, a janela de “Minha compreensão” e a janela principal.

O tempo vem de horários (ends_at), nunca de ticks somados: fechar ou minimizar uma janela, a interface travar ou o PC
suspender não atrasa nada; ao voltar, as etapas que já terminaram são contadas. É independente da gravação: pausar o
Pomodoro não pausa a captura, e pausar a captura não pausa o Pomodoro (lumen/record.py só é lido, para o som)."""
import io
import logging
import os
import threading
import time
import wave

import numpy as np

from . import AppError, store

log = logging.getLogger("lumen")
PHASES = ("focus", "short", "long")
DEFAULTS = {"focus": 25, "short": 5, "long": 15, "cycles": 4, "auto": False, "sound": True}
LIMITS = {"focus": (1, 180), "short": (1, 60), "long": (1, 90), "cycles": (1, 12)}  # minutos; ciclos
FRESH_S = 90  # um fim mais antigo que isto (o PC estava suspenso) muda o estado, mas não toca nem avisa
_lock = threading.Lock()
_s = None
_thread = None


def _settings(d, base=DEFAULTS):
    out = dict(base)
    for k, (lo, hi) in LIMITS.items():
        v = d.get(k, out[k])
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out[k] = int(min(hi, max(lo, round(v))))
    for k in ("auto", "sound"):
        if isinstance(d.get(k), bool):
            out[k] = d[k]
    return out


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _state():
    """Carrega pomodoro.json uma vez (validado: um arquivo estranho volta ao início, sem quebrar o app)."""
    global _s
    if _s is None:
        d = store._read("pomodoro.json", {})
        d = d if isinstance(d, dict) else {}
        s = {"settings": _settings(d.get("settings") if isinstance(d.get("settings"), dict) else {}),
             "phase": d.get("phase") if d.get("phase") in PHASES else "focus", "running": d.get("running") is True,
             "ends_at": _num(d.get("ends_at")), "remaining": _num(d.get("remaining")),
             "done": int(d["done"]) if isinstance(d.get("done"), int) and d["done"] >= 0 else 0,
             "event": d.get("event") if isinstance(d.get("event"), dict) else None}
        if s["running"] and s["ends_at"] is None:
            s["running"] = False
        if s["remaining"] is None or not 0 <= s["remaining"] <= _dur(s, s["phase"]):
            s["remaining"] = _dur(s, s["phase"])
        _s = s
    return _s


def _dur(s, phase):
    return s["settings"][phase] * 60.0


def _save(s):
    store._write("pomodoro.json", {k: s[k] for k in ("settings", "phase", "running", "ends_at", "remaining", "done",
                                                      "event")})


def _next(s, at, natural):
    """Passa para a etapa seguinte em `at`. natural = o tempo acabou (só então avisa)."""
    ended = s["phase"]
    if ended == "focus":
        s["done"] += 1
        s["phase"] = "long" if s["done"] >= s["settings"]["cycles"] else "short"
    else:
        if ended == "long":
            s["done"] = 0
        s["phase"] = "focus"
    s["remaining"] = _dur(s, s["phase"])
    if s["running"]:
        s["ends_at"] = at + s["remaining"]
    if natural:
        s["event"] = {"id": (s["event"] or {}).get("id", 0) + 1, "ended": ended, "next": s["phase"], "at": at}
        # (Futuro: “pausar a captura durante os intervalos” entraria aqui, desligado por padrão.)


def _advance(s, now):
    """Conta as etapas que terminaram até `now` (várias, se o PC ficou suspenso com o início automático ligado)."""
    moved = False
    while s["running"] and now >= s["ends_at"]:
        end = s["ends_at"]
        if not s["settings"]["auto"]:
            s["running"], s["ends_at"] = False, None
        _next(s, end, True)
        moved = True
    return moved


def _view(s, now):
    left = max(0.0, s["ends_at"] - now) if s["running"] else s["remaining"]
    return {"phase": s["phase"], "running": s["running"], "ends_at": s["ends_at"], "left": left,
            "total": _dur(s, s["phase"]), "done": s["done"], "settings": dict(s["settings"]), "event": s["event"],
            "now": now}


def view(now=None):
    now = time.time() if now is None else now
    with _lock:
        s = _state()
        if _advance(s, now):
            _save(s)
        return _view(s, now)


def act(action, settings=None, now=None):
    """play | pause | reset | skip | settings. Devolve o estado novo."""
    now = time.time() if now is None else now
    with _lock:
        s = _state()
        _advance(s, now)
        if action == "play":
            if not s["running"]:
                s["running"], s["ends_at"] = True, now + s["remaining"]
        elif action == "pause":
            if s["running"]:
                s["running"], s["remaining"], s["ends_at"] = False, max(0.0, s["ends_at"] - now), None
        elif action == "reset":
            if s["running"] or s["remaining"] < _dur(s, s["phase"]):  # volta ao início desta etapa
                s["running"], s["ends_at"], s["remaining"] = False, None, _dur(s, s["phase"])
            else:  # já estava no início: recomeça a sequência pelo foco
                s["phase"], s["done"], s["remaining"] = "focus", 0, _dur(s, "focus")
        elif action == "skip":
            _next(s, now, False)
        elif action == "settings":
            if not isinstance(settings, dict):
                raise AppError("Ajustes do Pomodoro inválidos.", "Confira os tempos e tente de novo.")
            fresh = not s["running"] and s["remaining"] == _dur(s, s["phase"])
            s["settings"] = _settings(settings, s["settings"])
            if fresh:  # etapa ainda não começada: já usa a duração nova
                s["remaining"] = _dur(s, s["phase"])
            s["remaining"] = min(s["remaining"], _dur(s, s["phase"]))
            if s["phase"] == "focus":
                s["done"] = min(s["done"], s["settings"]["cycles"] - 1)
        else:
            raise AppError("Ação do Pomodoro desconhecida.", "")
        _save(s)
        return _view(s, now)


def _tone():
    """Som curto e baixo (duas notas suaves, ≈ 0,7 s), gerado aqui: nenhum arquivo de som no app."""
    rate = 22050
    t = np.arange(int(rate * .35)) / rate
    env = np.exp(-t * 9) * np.minimum(1, t * 200)
    x = np.concatenate([np.sin(2 * np.pi * 659.3 * t) * env, np.sin(2 * np.pi * 880 * t) * env]) * .18
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _chime():
    """Toca o aviso, a não ser que a captura esteja gravando: o som do PC é o que vai para a aula, e o aviso
    entraria na gravação. Com a captura pausada (ou sem gravação), toca."""
    from . import record
    r = record.status()
    if os.name != "nt" or (r.get("active") and not r.get("paused")):
        return
    import winsound
    threading.Thread(target=winsound.PlaySound, args=(_tone(), winsound.SND_MEMORY), daemon=True).start()


def _loop():
    while True:
        time.sleep(1)
        try:
            with _lock:
                s = _state()
                moved = _advance(s, time.time())
                if moved:
                    _save(s)
                    fresh = time.time() - s["event"]["at"] < FRESH_S
                    sound = s["settings"]["sound"] and fresh
            if moved:
                log.info("pomodoro: %s terminou", s["event"]["ended"])
                if sound:
                    _chime()
        except Exception as e:  # noqa: BLE001 — o timer nunca derruba o servidor
            log.warning("pomodoro: %s", type(e).__name__)


def start():
    """Liga o relógio que vira as etapas na hora (mesmo sem nenhuma janela aberta) e toca o aviso."""
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, daemon=True)
        _thread.start()
