"""Configuração, histórico e token. Nada de segredo em arquivo: o token vai para o cofre do sistema."""
import json
import os
import shutil
import tempfile
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
    "notion_open": False,       # abrir a página da aula no navegador ao terminar
    "notion_free_page_id": "",  # “Conteúdo gratuito” no Notion: uma página por material (catalog: tipo free)
    "notion_free_page_title": "",
    "quality": "equilibrado",   # rapido | equilibrado | maximo (ver lumen/transcribe.py)
    "ollama_model": "qwen3:8b",
    "page_language": "pt",      # pt | original
    "keep_temp": False,
    "image_dir": "",          # vazio preserva o destino legado; a migração verifica a cópia antes de mudar
    "watch_screen": False,      # “Assistir a tela junto”: lê slides/quadro da tela ou do vídeo (lumen/vision.py)
    "music_filter": False,      # “Filtrar música externa”: protege a transcrição da música de fundo (lumen/music.py)
    "music_mode": "balanceado",  # conservador | balanceado | agressivo (music.MODES)
    "widget": "left",           # off | left | right | top | bottom | free
    "autostart": False,         # abrir com o Windows (chave Run do usuário)
    # Destinos do material (o mesmo StudyPackage para os dois; lumen/package.py)
    "destinations": "notion",   # notion | obsidian | both
    "study_level": "balanceado",  # rapido (1 passada) | balanceado (+ conexões) | profundo (+ crítica do material)
    "obsidian_vault": "",       # pasta do cofre (escolhida pelo usuário; vault.vaults() só sugere)
    "obsidian_folder": "",      # área de estudos dentro do cofre; vazio = vault.default_folder (ex.: B02 Estudos)
    "obsidian_canvas": True,    # mapa conceitual como Canvas
    "obsidian_board": True,     # painel visual: segundo Canvas, com as imagens reais da aula (precisa dos anexos)
    "obsidian_board_density": "equilibrado",  # compacto (até 5 imagens) | equilibrado (até 10) | visual (até 15)
    "obsidian_connections": True,  # procurar conexões no cofre (IA local, só no PC)
    "obsidian_review": False,   # revisões espaçadas (datas e checklist) na nota e nos painéis; opcional, só ligada a pedido
    "obsidian_attachments": True,  # telas e gráficos copiados para o cofre (nunca o vídeo)
    "obsidian_open": False,     # abrir a nota no Obsidian ao terminar
    "visual_3d": "animated",    # Visualização 3D nas páginas novas: animated (GIF) | static (PNG) | off (lumen/visual3d.py)
    "review_intervals": [1, 3, 7, 14, 30, 60],  # dias depois do estudo
    "ui_style": "classic",      # estilo da interface: classic (o de sempre) | glass (Lúmen Glass 2026; só a apresentação muda)
    # Open Notebook (lumen/opennotebook.py): só a transcrição em texto, pela API dele; a senha fica no cofre do sistema
    "opennotebook_on": False,
    "opennotebook_url": "http://127.0.0.1:5055",  # API
    "opennotebook_ui": "http://127.0.0.1:3000",   # interface (para “Abrir no Open Notebook”)
    "opennotebook_notebook": "",       # id do caderno de destino
    "opennotebook_notebook_name": "",
    "opennotebook_auto": False,        # enviar a transcrição ao terminar cada aula
    # HyperbookLM (lumen/hyperbooklm.py): só o título e a transcrição, à mão, pela ponte local dele; o código de
    # pareamento fica no cofre do sistema
    "hyperbooklm_on": False,
    "hyperbooklm_url": "http://127.0.0.1:3000",
}
UI_STYLES = ("classic", "glass")


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
    """Remove gravações, cópias, telas capturadas e áudio do filtro de música esquecidos com mais de `days` dias (e as
    pastas temporárias do Lumen com mais de um dia: o Edge às vezes as segura e elas não saem na hora). As
    telas de uma aula (as imagens são o que mais ocupa) também saem depois desse prazo; a transcrição fica para
    retomar."""
    cutoff, day = time.time() - days * 86400, time.time() - 86400
    temp = list(Path(tempfile.gettempdir()).glob("lumen-*"))
    for f in [*(WORK / "uploads").glob("*"), *WORK.glob("*/screens"), *WORK.glob("*/music-*.wav"), *temp]:
        try:
            if f in temp and (f == DATA or f in DATA.parents):  # os dados deste Lumen (testes rodam em %TEMP%)
                continue
            if f.stat().st_mtime < (day if f in temp else cutoff):
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink()
        except OSError:
            pass


def clear_local_data():
    """Apaga histórico, transcrições, notas de compreensão guardadas e arquivos temporários (não toca no Notion
    nem no token). A interface avisa das notas antes de confirmar."""
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(DATA / "understanding", ignore_errors=True)
    shutil.rmtree(DATA / "packages", ignore_errors=True)
    shutil.rmtree(DATA / "notebook", ignore_errors=True)  # dados legados do Gemini Notebook (a integração foi retirada)
    shutil.rmtree(DATA / "visuals", ignore_errors=True)  # visualizações 3D desenhadas (refeitas quando preciso)
    (DATA / "history.json").unlink(missing_ok=True)
    try:  # o log fica aberto pelo app; esvaziar funciona no Windows, apagar não
        open(DATA / "lumen.log", "w").close()
    except OSError:
        pass
