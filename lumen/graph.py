"""Identidade dos estudos no Graph View do Obsidian: um Color Group nativo (`.obsidian/graph.json`), instalado uma vez.

Quem é estudo vem do frontmatter que o Lumen já escreve (`type: ai-study` nas aulas, `type: course` na página do curso),
não da pasta: mover ou renomear uma aula não muda a cor, e nenhuma nota precisa de tag ou campo a mais. Anexos, Canvas,
a Home (`type: system`) e as notas do usuário ficam de fora.

Regras: o grupo é criado só se não existir nenhum com a consulta de estudos (a cor que o usuário escolher fica); nada
mais do graph.json muda (forças, filtros, órfãos, outros grupos); o grupo entra em primeiro, porque o Obsidian pinta o
nó com o primeiro grupo que casa; JSON inválido nunca é sobrescrito; com o Obsidian aberto, espera (ele guarda o graph
na memória e regravaria por cima); depois de instalado num cofre, não é recriado (se o usuário apagar o grupo, ficou
apagado). Escrita atômica, com um backup único `graph.json.lumen-backup` antes da primeira mudança."""
import json
import logging
import os
import subprocess
import sys

from . import catalog, store

log = logging.getLogger("lumen")
# Hoje só os estudos; outros grupos (projetos, livros…) entrariam aqui com a consulta e a cor de cada um.
STUDY_QUERY = "[type:ai-study] OR [type:course]"
STUDY_COLOR = "#5B8CFF"  # Lumen Study Blue


def _rgb(hex_color):
    return int(hex_color.lstrip("#"), 16)


def _obsidian_running():
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe", "/NH"], capture_output=True, text=True,
                             timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # na dúvida, espera
    return "obsidian.exe" in out.casefold()


def ensure(vault, query=STUDY_QUERY, color=STUDY_COLOR, running=None):
    """Garante o grupo dos estudos no graph.json do cofre. Devolve o que aconteceu: created, present, installed (já
    instalado antes: nada a fazer), busy (Obsidian aberto), invalid (graph.json corrompido) ou no-config."""
    key = os.path.normcase(str(vault))
    cat = catalog.load()
    if key in cat["meta"].get("graph_installed", []):
        return "installed"
    conf = vault / ".obsidian"
    if not conf.is_dir():
        return "no-config"
    path = conf / "graph.json"
    raw, stamp = None, None
    if path.exists():
        raw, stamp = path.read_text("utf-8"), path.stat().st_mtime_ns
        try:
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict) or not isinstance(data.get("colorGroups", []), list):
                raise ValueError
        except ValueError:
            log.warning("graph: graph.json inválido; nada foi alterado")
            return "invalid"
    else:
        data = {}
    groups = data.get("colorGroups", [])
    if any(isinstance(g, dict) and g.get("query", "").strip() == query for g in groups):
        _done(key)
        return "present"
    if (running or _obsidian_running)():
        return "busy"
    data["colorGroups"] = [{"query": query, "color": {"a": 1, "rgb": _rgb(color)}}, *groups]
    if raw is not None:
        backup = conf / "graph.json.lumen-backup"
        if not backup.exists():
            backup.write_text(raw, "utf-8")
        if path.stat().st_mtime_ns != stamp:  # mudou enquanto líamos: não passa por cima
            return "busy"
    tmp = conf / ".graph.json.lumen-tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)
    _done(key)
    log.info("graph: grupo dos estudos criado")
    return "created"


def _done(key):
    with store.LOCK:
        cat = catalog.load()
        cat["meta"]["graph_installed"] = sorted(set(cat["meta"].get("graph_installed", [])) | {key})
        catalog.save(cat)
