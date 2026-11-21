"""Identidade dos estudos no Graph View do Obsidian: Color Groups nativos (`.obsidian/graph.json`), instalados uma vez.

- Notas de estudo, em azul: vêm do frontmatter que o Lumen já escreve (`type: ai-study` nas aulas, `type: course` na
  página do curso), não da pasta. Mover ou renomear uma aula não muda a cor, e nenhuma nota precisa de tag ou campo a
  mais.
- Canvas dos estudos, em violeta: todo `.canvas` dentro da área de estudos (Mapa, Painel e os que vierem, mais um
  Canvas que o usuário puser na pasta de uma aula). Canvas é JSON, sem frontmatter: o que o identifica é o lugar. Os
  Canvas fora da área ficam com a cor de sempre.

Anexos, a Home (`type: system`) e as notas do usuário ficam de fora. As duas consultas não se cruzam (uma só casa `.md`
com `type`, a outra só `.canvas`), então a ordem entre elas não importa; as duas entram antes dos grupos do usuário,
porque o Obsidian pinta o nó com o primeiro grupo que casa.

Regras: cada grupo é criado só se não existir nenhum com a mesma consulta (a cor que o usuário escolher fica); nada mais
do graph.json muda (forças, filtros, órfãos, anexos, outros grupos); JSON inválido nunca é sobrescrito; com o Obsidian
aberto, espera (ele guarda o graph na memória e regravaria por cima); depois de instalado num cofre, um grupo não é
recriado (se o usuário apagar, ficou apagado). Escrita atômica, com um backup único `graph.json.lumen-backup` antes da
primeira mudança."""
import json
import logging
import os
import re
import subprocess
import sys

from . import catalog, store

log = logging.getLogger("lumen")
STUDY_QUERY = "[type:ai-study] OR [type:course]"
STUDY_COLOR = "#5B8CFF"  # Lumen Study Blue
CANVAS_COLOR = "#A78BFA"  # Lumen Canvas Purple


def canvas_query(area):
    """Os `.canvas` da área. Regex ancorada nas duas pontas, porque no Obsidian 1.14 `path:"B02 Estudos"` também casa
    `B04 Archives/B02 Estudos antigo/` e `file:.canvas` casa a nota `Ideias.canvas.md`."""
    rx = re.sub(r"[\\^$.|?*+()\[\]{}/]", r"\\\g<0>", area)
    return f"path:/^{rx}\\// file:/\\.canvas$/"


def groups(area):
    """Os grupos do Lumen, na ordem em que entram. Um grupo novo (projetos, livros…) seria mais uma linha aqui."""
    return {"canvas": (canvas_query(area), CANVAS_COLOR), "study": (STUDY_QUERY, STUDY_COLOR)}


def _rgb(hex_color):
    return int(hex_color.lstrip("#"), 16)


def _obsidian_running():
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe", "/NH"], capture_output=True,
                                timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return True  # na dúvida, espera
    # tasklist usa a página OEM do Windows; só o nome ASCII do processo importa aqui.
    return result.returncode != 0 or b"obsidian.exe" in result.stdout.lower()


def ensure(vault, area, running=None):
    """Garante os grupos do Lumen no graph.json do cofre (`area`: a área de estudos, relativa ao cofre). Devolve o que
    aconteceu: created, present, installed (já instalados antes: nada a fazer), busy (Obsidian aberto), invalid
    (graph.json corrompido) ou no-config."""
    key = os.path.normcase(str(vault))
    done = _installed(key)
    todo = {name: g for name, g in groups(area).items() if name not in done}
    if not todo:
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
    mine = data.get("colorGroups", [])
    have = {g["query"].strip() for g in mine if isinstance(g, dict) and isinstance(g.get("query"), str)}
    present = [name for name, (query, _) in todo.items() if query in have]
    missing = {name: g for name, g in todo.items() if name not in present}
    if present:
        _done(key, present)
    if not missing:
        return "present"
    if (running or _obsidian_running)():
        return "busy"
    data["colorGroups"] = [*({"query": q, "color": {"a": 1, "rgb": _rgb(c)}} for q, c in missing.values()), *mine]
    if raw is not None:
        backup = conf / "graph.json.lumen-backup"
        if not backup.exists():
            backup.write_text(raw, "utf-8")
        if path.stat().st_mtime_ns != stamp:  # mudou enquanto líamos: não passa por cima
            return "busy"
    tmp = conf / ".graph.json.lumen-tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)
    _done(key, missing)
    log.info("graph: grupo(s) criado(s): %s", ", ".join(missing))
    return "created"


def _installed(key):
    """Os grupos já instalados no cofre. A marca é `cofre|grupo`; até 26/10/2026 era só o cofre, e só havia o dos
    estudos (`|` não existe em caminho do Windows)."""
    out = set()
    for mark in catalog.load()["meta"].get("graph_installed", []):
        where, _, name = mark.partition("|")
        if where == key:
            out.add(name or "study")
    return out


def _done(key, names):
    with store.LOCK:
        cat = catalog.load()
        cat["meta"]["graph_installed"] = sorted(set(cat["meta"].get("graph_installed", [])) |
                                                {f"{key}|{n}" for n in names})
        catalog.save(cat)
