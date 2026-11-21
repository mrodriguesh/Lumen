"""Abrir destinos conhecidos, sem shell ou argumentos produzidos pelo modelo."""
import os
import subprocess
from pathlib import Path
from urllib.parse import quote

from .. import AppError, cdp, notion, store, vault
from . import activity, settings

LABELS = {"obsidian": "Obsidian", "notion": "Notion", "edge": "Microsoft Edge", "vault": "Pasta do cofre", "calculator": "Calculadora"}


def open_app(name, *, confirmed=False, conversation_id=""):
    s = settings.load()
    if not isinstance(name, str) or name not in LABELS or s["agent"].get(name) is not True:
        raise AppError("Este aplicativo não está na lista permitida.", "Confira Configurações → Privacidade e permissões.")
    if not confirmed and not s["privacy"]["open_windows"]:
        return {"opened": False, "app": name, "title": LABELS[name]}
    try:
        if name in ("obsidian", "vault"):
            root = vault.check(store.load_config()["obsidian_vault"])
            os.startfile("obsidian://open?vault=" + quote(root.name, safe="") if name == "obsidian" else str(root))
        elif name == "notion":
            parent = s["connectors"]["notion_parent"] or store.load_config()["root_page_id"]
            os.startfile("https://www.notion.so/" + notion.page_id(parent).replace("-", "") if parent else "https://www.notion.so")
        elif name == "edge":
            exe = cdp.edge()
            if not exe:
                raise AppError("Microsoft Edge não encontrado.")
            subprocess.Popen([str(exe), "--new-window", "about:blank"], shell=False)
        else:
            subprocess.Popen([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "calc.exe")], shell=False)
    except OSError as e:
        raise AppError(f"Não foi possível abrir {LABELS[name]}.", "Confira se o aplicativo está instalado.") from e
    activity.log("abrir-aplicativo", target=name, permission="clique do estudante" if confirmed else "abertura autorizada", conversation_id=conversation_id)
    return {"opened": True, "app": name, "title": LABELS[name]}
