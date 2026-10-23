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
    "watch_screen": False,      # “Assistir a tela junto”: lê slides/quadro da tela ou do vídeo (lumen/vision.py)
    "music_filter": False,      # “Filtrar música externa”: protege a transcrição da música de fundo (lumen/music.py)
    "music_mode": "balanceado",  # conservador | balanceado | agressivo (music.MODES)
    "widget": "left",           # off | left | right | top | bottom | free
    "autostart": False,         # abrir com o Windows (chave Run do usuário)
    # Destinos do material (o mesmo StudyPackage para os dois; lumen/package.py)
    "destinations": "notion",   # notion | obsidian | both
    "study_level": "balanceado",  # rapido (1 passada) | balanceado (+ conexões) | profundo (+ crítica do material)
    "obsidian_vault": "",       # pasta do cofre (escolhida pelo usuário; vault.vaults() só sugere)
    "obsidian_folder": "",      # pasta das notas dentro do cofre; vazio = vault.default_folder
    "obsidian_canvas_folder": "",  # pasta dos mapas (.canvas); vazio = a mesma das notas
    "obsidian_canvas": True,    # mapa mental como Canvas
    "obsidian_connections": True,  # procurar conexões no cofre (IA local, só no PC)
    "obsidian_review": True,    # revisões espaçadas na nota e no painel
    "obsidian_attachments": True,  # telas e gráficos copiados para o cofre (nunca o vídeo)
    "obsidian_open": False,     # abrir a nota no Obsidian ao terminar
    "review_intervals": [1, 3, 7, 14, 30, 60],  # dias depois do estudo
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
    """Manifesto de sincronização: uma entrada por aula (Notion, Obsidian, pacote). Junta ao que já havia."""
    with LOCK:
        h = history()
        h[key] = {**(h.get(key) or {}), **entry}
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
    """Remove gravações, cópias, telas capturadas e áudio do filtro de música esquecidos com mais de `days` dias. As
    telas de uma aula (as imagens são o que mais ocupa) também saem depois desse prazo; a transcrição fica para
    retomar."""
    cutoff = time.time() - days * 86400
    for f in [*(WORK / "uploads").glob("*"), *WORK.glob("*/screens"), *WORK.glob("*/music-*.wav")]:
        try:
            if f.stat().st_mtime < cutoff:
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink()
        except OSError:
            pass


def clear_local_data():
    """Apaga histórico, transcrições, notas de compreensão guardadas e arquivos temporários (não toca no Notion
    nem no token). A interface avisa das notas antes de confirmar."""
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(DATA / "understanding", ignore_errors=True)
    shutil.rmtree(DATA / "packages", ignore_errors=True)
    (DATA / "history.json").unlink(missing_ok=True)
    try:  # o log fica aberto pelo app; esvaziar funciona no Windows, apagar não
        open(DATA / "lumen.log", "w").close()
    except OSError:
        pass
