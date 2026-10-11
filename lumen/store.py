"""Configuração, histórico e token. Nada de segredo em arquivo: o token vai para o cofre do sistema."""
import json
import os
import shutil
import threading
import time
from pathlib import Path

import keyring

APP = "Lumen"
DATA = Path(os.environ.get("LUMEN_DATA") or os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / APP
WORK = DATA / "work"
LOCK = threading.RLock()  # config.json e history.json: leia-altere-grave sem pisar em outro pedido

DEFAULTS = {
    "root_page_id": "",
    "root_page_title": "",
    "quality": "equilibrado",   # rapido | equilibrado | maximo (ver lumen/transcribe.py)
    "ollama_model": "qwen3:8b",
    "page_language": "pt",      # pt | original
    "keep_temp": False,
    "brand_cover": True,        # logo da marca citada na capa e no banner da aula (lumen/brands.py)
    "watch_screen": False,      # “Assistir a tela junto”: lê slides/quadro da tela ou do vídeo (lumen/vision.py)
    "widget": "left",           # off | left | right | top | bottom | free
    "autostart": False,         # abrir com o Windows (chave Run do usuário)
}


def _read(name, default):
    try:
        return json.loads((DATA / name).read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write(name, data):
    with LOCK:
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = DATA / (name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, DATA / name)


def load_config():
    cfg = {**DEFAULTS, **_read("config.json", {})}
    return {k: cfg[k] for k in DEFAULTS}


def save_config(cfg):
    _write("config.json", {k: cfg[k] for k in DEFAULTS})


def history():
    return _read("history.json", {})


def remember(key, entry):
    with LOCK:
        h = history()
        h[key] = entry
        _write("history.json", h)


def get_token():
    try:
        return keyring.get_password(APP, "notion")
    except keyring.errors.KeyringError:
        return None


def set_token(token):
    keyring.set_password(APP, "notion", token)


def delete_token():
    try:
        keyring.delete_password(APP, "notion")
    except keyring.errors.KeyringError:
        pass


def purge_old_uploads(days=7):
    """Remove gravações, cópias e telas capturadas esquecidas com mais de `days` dias. As telas de uma aula (as
    imagens são o que mais ocupa) também saem depois desse prazo; a transcrição fica para retomar."""
    cutoff = time.time() - days * 86400
    for f in [*(WORK / "uploads").glob("*"), *WORK.glob("*/screens")]:
        try:
            if f.stat().st_mtime < cutoff:
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink()
        except OSError:
            pass


def clear_local_data():
    """Apaga histórico, transcrições guardadas e arquivos temporários (não toca no Notion nem no token)."""
    shutil.rmtree(WORK, ignore_errors=True)
    (DATA / "history.json").unlink(missing_ok=True)
    try:  # o log fica aberto pelo app; esvaziar funciona no Windows, apagar não
        open(DATA / "lumen.log", "w").close()
    except OSError:
        pass
