"""Área de estudos no cofre (ex.: “B02 Estudos”): onde cada aula fica, a Base, a Home, a nota de cada curso, mover,
renomear e migrar o que estava na pasta antiga do Lumen.

Estrutura (pastas criadas só quando usadas; nada vazio é apagado sozinho):

    <área>/00 - Estudos.md, Estudos.base
    01 - Cursos/<Curso>/00 - <Curso>.md, [NN - ]<Módulo>/[NN - ]<Aula>/
    02 - Conteúdo gratuito/[<Tema>/]<Material>/
    03 - Aulas avulsas/[<Tema>/]<Aula>/
    90 - A organizar/<Aula>/

Cada aula tem a sua pasta: a nota (`Título.md`), `Mapa - Título.canvas`, `Painel - Título.canvas` e `Anexos/`. Os nomes
de arquivo continuam únicos no cofre (a convenção dele: `[[Nome]]` sem caminho), então mover uma pasta só invalida o
`file` dos Canvas, que este módulo reescreve. Mover é um `os.rename` (atômico no mesmo disco) e qualquer falha depois
dele desfaz tudo; a migração guarda um diário em DATA para desfazer até se o Lumen for fechado no meio."""
import hashlib
import json
import logging
import os
import re
import shutil
import unicodedata
import zipfile
from datetime import date, datetime
from pathlib import Path

from . import AppError, canvas, catalog, obsidian, store, vault
from .canvas import md
from .obsidian import BEGIN, clean, compose, block_hash, merge_fields, parts

log = logging.getLogger("lumen")
SECTIONS = {"course": "01 - Cursos", "free": "02 - Conteúdo gratuito", "single": "03 - Aulas avulsas",
            "inbox": "90 - A organizar"}
HOME, BASE = "00 - Estudos.md", "Estudos.base"
LIMIT = 180  # pasta da aula: abaixo dela cabem “Anexos/” e o nome de uma imagem sem passar de 260 no Windows
JOURNAL = "migration.json"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2} - ")
USER_COURSE = ("\n\n## Sobre\n%% Área sua: o Lumen nunca altera nada daqui para baixo. %%\n\n"
               "## Materiais relacionados\n\n## Notas permanentes geradas\n")
USER = "\n\n## Minhas anotações\n%% Área sua: o Lumen nunca altera nada daqui para baixo. %%\n"


# --- Caminhos -------------------------------------------------------------------------------------------------

def course_dir(home, name):
    return home / SECTIONS["course"] / clean(name, 40)


def module_name(name, order=None):
    return (f"{int(order):02d} - " if order else "") + clean(name, 40)


def lesson_dir(home, cls, title, lid=None):
    """A pasta de uma aula pela classificação. Uma pasta com outra aula dentro nunca é reaproveitada."""
    cls = cls or catalog.INBOX
    t = cls.get("type") if cls.get("type") in SECTIONS else "inbox"
    base = home / SECTIONS[t]
    if t == "course":
        base = course_dir(home, cls["course"])
        if cls.get("module"):
            base = base / module_name(cls["module"], cls.get("module_order"))
    elif t in ("free", "single") and cls.get("category"):
        base = base / clean(cls["category"], 40)
    name = (f"{int(cls['lesson']):02d} - " if cls.get("lesson") else "") + clean(title, 60)
    while len(str(base / name)) > LIMIT and len(name) > 24:
        name = name[:-8].rstrip(" .")
    d = base / name
    if lid and d.exists() and _owners(d) - {lid}:
        d = base / f"{name} · {lid[3:9]}"
    return obsidian._within(d, home) if d.exists() else _inside(d, home)


def _inside(p, home):
    """O caminho (que pode ainda não existir) fica dentro da área, inclusive seguindo junctions do que já existe."""
    if not (p == home or home in p.parents):
        raise AppError("O Lumen tentou gravar fora da área de estudos.", "Confira a área em Integrações → Obsidian.")
    up = p
    while not up.exists() and up != home:
        up = up.parent
    if up.exists():
        r = up.resolve()
        if r != home.resolve() and home.resolve() not in r.parents:
            raise AppError("Uma pasta da área de estudos aponta para fora do cofre.", "Troque o atalho por uma pasta comum.")
    return p


def _owners(d):
    """lumen-ids das notas de estudo que estão direto nesta pasta."""
    out = set()
    for f in d.glob("*.md"):
        try:
            lid = vault.fields(vault.split(f.read_text("utf-8"))[0]).get("lumen-id")
        except (OSError, UnicodeDecodeError):
            continue
        if lid:
            out.add(str(lid))
    return out


def own_dir(home, d, lid):
    """A pasta é só desta aula? (então mover = renomear a pasta). Pastas de estrutura (área, seções, curso, módulo,
    tema) e pastas com outra aula ou com subpastas além de Anexos nunca são movidas inteiras."""
    if d == home or home not in d.parents or d.parent == home:
        return False
    try:
        kids = list(d.iterdir())
    except OSError:
        return False
    if any(k.is_dir() and k.name != "Anexos" for k in kids) or any(k.name.startswith("00 - ") for k in kids):
        return False
    return _owners(d) <= {lid}


# --- Os arquivos de uma aula -------------------------------------------------------------------------------------

_EMBED = re.compile(r"!\[\[([^\]|#\n]+?)(?:[|#][^\]\n]*)?\]\]")


def lesson_files(root, note, lid, ob):
    """Nota, mapa, painel e anexos de uma aula (pelo manifesto, pelos ids estáveis dos Canvas e pelos embeds da
    nota). Só arquivos que existem e que estão na pasta da nota ou abaixo dela."""
    here = note.parent
    out = {"note": note, "canvas": None, "board": None, "attachments": []}
    for kind, head in (("canvas", canvas.center_id(lid)), ("board", obsidian.board.head_id(lid))):
        rel = ob.get(kind)
        f = root / rel if rel else None
        if not (f and f.is_file()):
            f = next((x for x in sorted(here.glob("*.canvas")) if head in _read(x)), None)
        out[kind] = f if f and here in f.parents else None
    seen = set()

    def add(f):
        if f and f.is_file() and (f.parent == here or here in f.parents) and f.suffix.lower() not in (".md", ".canvas"):
            k = str(f).casefold()
            if k not in seen:
                seen.add(k)
                out["attachments"].append(f)
    for rel in (ob.get("files") or {}):
        add(root / rel)
    for name in _EMBED.findall(_read(note)):
        name = name.strip()
        add(next((x for x in (here / "Anexos" / name, here / name) if x.is_file()), None))
    for c in (out["canvas"], out["board"]):
        for rel in _canvas_files(c):
            add(root / rel)
    return out


def _read(f):
    try:
        return f.read_text("utf-8")
    except (OSError, UnicodeDecodeError, AttributeError, TypeError):
        return ""


def _canvas_files(f):
    try:
        data = json.loads(_read(f) or "{}")
    except ValueError:
        return []
    return [n["file"] for n in data.get("nodes") or [] if isinstance(n, dict) and n.get("type") == "file" and n.get("file")]


# --- Mover com segurança ------------------------------------------------------------------------------------------

def _rel(root, p):
    return Path(p).relative_to(root).as_posix()


def _apply(root, moves, journal=None):
    """Renomeia (origem → destino) um por um; uma falha desfaz os já feitos, do último para o primeiro. Com diário, cada
    passo fica gravado antes de acontecer: se o Lumen for fechado no meio, recover() desfaz na próxima vez."""
    done = []
    try:
        for src, dst in moves:
            if dst.exists():
                raise AppError(f"Já existe “{dst.name}” no destino; nada foi movido.", "Renomeie ou mova o arquivo e tente de novo.")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if journal:
                store._write(journal, {"status": "running", "done": [[_rel(root, a), _rel(root, b)] for a, b in done + [(src, dst)]]})
            os.rename(src, dst)
            done.append((src, dst))
    except BaseException:
        _undo(done)
        if journal:
            (store.DATA / journal).unlink(missing_ok=True)
        raise
    return done


def _undo(done):
    for src, dst in reversed(done):
        try:
            if dst.exists() and not src.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                os.rename(dst, src)
        except OSError:
            log.error("área: não foi possível desfazer um movimento")


def recover(cfg):
    """Migração interrompida (o Lumen fechou no meio): volta cada arquivo para onde estava."""
    j = store._read(JOURNAL, None)
    if not j or j.get("status") != "running":
        return 0
    root, _ = obsidian.folders(cfg)
    pairs = [(root / a, root / b) for a, b in j.get("done") or []]
    _undo(pairs)
    (store.DATA / JOURNAL).unlink(missing_ok=True)
    log.warning("área: migração interrompida desfeita (%d arquivos)", len(pairs))
    return len(pairs)


def _remapper(pairs):
    """Função caminho antigo → novo (relativos ao cofre): arquivos movidos e pastas movidas (com tudo dentro)."""
    exact = {a: b for a, b in pairs}

    def f(rel):
        if rel in exact:
            return exact[rel]
        for a, b in pairs:
            if rel.startswith(a + "/"):
                return b + rel[len(a):]
        return rel
    return f


def _rewrite_canvases(root, home, remap, lid):
    """Os `file` dos Canvas da área que apontam para o que mudou de lugar. Devolve [(arquivo, texto antigo)] para
    desfazer. Backup da versão anterior em DATA/obsidian-backups."""
    changed = []
    try:
        for f in sorted(home.rglob("*.canvas")):
            raw = _read(f)
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            hit = False
            for n in data.get("nodes") or []:
                if isinstance(n, dict) and n.get("type") == "file" and isinstance(n.get("file"), str):
                    new = remap(n["file"])
                    if new != n["file"]:
                        n["file"], hit = new, True
            if hit:
                obsidian._backup(f, lid)
                obsidian._write(f, canvas.dumps(data))
                changed.append((f, raw))
    except BaseException:
        for f, raw in changed:
            obsidian._write(f, raw)
        raise
    return changed


def _remap_history(remap, only=None, extra=None):
    """Caminhos do manifesto (nota, canvas, painel, anexos) depois de mover. only: chaves das aulas a mudar."""
    with store.LOCK:
        h = store.history()
        for key, e in h.items():
            ob = e.get("obsidian")
            if not isinstance(ob, dict) or (only is not None and key not in only):
                continue
            for k in ("note", "canvas", "board"):
                if ob.get(k):
                    ob[k] = remap(ob[k])
            if isinstance(ob.get("files"), dict):
                ob["files"] = {remap(r): s for r, s in ob["files"].items()}
            if isinstance(ob.get("images"), dict):
                ob["images"] = {i: remap(r) for i, r in ob["images"].items()}
            if extra and key in extra:
                e.update(extra[key])
        store._write("history.json", h)


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def relocate(root, home, note, target, lid, ob):
    """Move a aula para `target` (a pasta dela inteira, ou só os arquivos dela se a nota divide a pasta com outras).
    Reescreve os Canvas e devolve o caminho novo da nota. `ob` (o manifesto da aula) é atualizado no lugar."""
    src = note.parent
    if src == target:
        return note
    if target.exists() and any(target.iterdir()):
        target = target.with_name(f"{target.name} · {lid[3:9]}")
        if target.exists():
            raise AppError("Já existe uma pasta com o nome desta aula no destino.", "Renomeie a pasta antiga e tente de novo.")
    _inside(target, home)
    if target.is_dir():
        target.rmdir()  # vazia (sobrou de outra vez): o Windows não renomeia por cima de uma pasta
    files = lesson_files(root, note, lid, ob)
    if own_dir(home, src, lid):
        moves = [(src, target)]
    else:
        moves = [(f, target / f.name) for f in (note, files["canvas"], files["board"]) if f]
        moves += [(f, target / "Anexos" / f.name) for f in files["attachments"]]
    pairs = [(_rel(root, a), _rel(root, b)) for a, b in moves]
    remap = _remapper(pairs)
    before = {k: _hash(_read(root / ob[k])) for k in ("canvas", "board") if ob.get(k)}
    done = _apply(root, moves)
    try:
        _rewrite_canvases(root, home, remap, lid)
    except BaseException:
        _undo(done)
        raise
    for k, h in (("canvas", "canvas_hash"), ("board", "board_hash")):  # Canvas puro continua puro (sem “edição”)
        if ob.get(k):
            new = remap(ob[k])
            if ob.get(h) and before.get(k) == ob[h]:
                ob[h] = _hash(_read(root / new))
            ob[k] = new
    if isinstance(ob.get("files"), dict):
        ob["files"] = {remap(r): s for r, s in ob["files"].items()}
    if isinstance(ob.get("images"), dict):
        ob["images"] = {i: remap(r) for i, r in ob["images"].items()}
    log.info("área: aula movida (%d itens)", len(moves))
    return root / remap(_rel(root, note))


def rename_dir(cfg, old, new, lid="area"):
    """Renomeia uma pasta de estrutura (curso, módulo) com tudo dentro: Canvas e manifesto acompanham."""
    root, home = obsidian.folders(cfg)
    _inside(new, home)
    if not old.exists() or str(old) == str(new):  # Path no Windows ignora maiúsculas: compara o texto
        return False
    obsidian._within(old, home)
    if new.exists() and os.path.normcase(str(new)) != os.path.normcase(str(old)):
        raise AppError(f"Já existe a pasta “{new.name}” na área de estudos.", "Escolha outro nome.")
    pairs = [(_rel(root, old), _rel(root, new))]
    remap = _remapper(pairs)
    done = _apply(root, [(old, new)]) if os.path.normcase(str(new)) != os.path.normcase(str(old)) else None
    if done is None:  # só maiúsculas/acentos de forma diferente: o Windows vê a mesma pasta; passa por um nome provisório
        tmp = old.with_name(old.name + " · renomeando")
        os.rename(old, tmp)
        os.rename(tmp, new)
        done = [(old, new)]
    try:
        _rewrite_canvases(root, home, remap, lid)
    except BaseException:
        _undo(done)
        raise
    _remap_history(remap)
    return True


def rename_course(cfg, old, new):
    """Curso renomeado (ou com plataforma nova) no Lumen: a pasta vai junto e as aulas do curso, onde estiverem na
    área, ganham o nome novo nas propriedades. O id não muda."""
    root, home = obsidian.folders(cfg)
    rename_dir(cfg, course_dir(home, old["name"]), course_dir(home, new["name"]), new["id"])
    for l in _lessons(home):
        if l["course_id"] == new["id"]:
            obsidian.set_fields(l["path"], {"course": new["name"], "platform": new.get("platform") or None})
    refresh(cfg)


def rename_module(cfg, c, old, new):
    root, home = obsidian.folders(cfg)
    base = course_dir(home, c["name"])
    rename_dir(cfg, base / module_name(old["name"], old.get("order")), base / module_name(new["name"], new.get("order")),
               new["id"])
    for l in _lessons(home):
        if l["module_id"] == new["id"]:
            obsidian.set_fields(l["path"], {"module": new["name"]})
    refresh(cfg)


# --- Base, Home e notas de curso --------------------------------------------------------------------------------

def _lessons(home):
    """As notas de estudo da área, com o que a Home, as notas de curso e a Biblioteca usam."""
    out = []
    for f in sorted(home.rglob("*.md")):
        if f.name.startswith("00 - ") or any(p.startswith(".") for p in f.relative_to(home).parts):
            continue
        try:
            d = vault.fields(vault.split(f.read_text("utf-8"))[0])
        except (OSError, UnicodeDecodeError):
            continue
        if d.get("type") != "ai-study":
            continue
        lesson = str(d.get("lesson") or "")
        out.append({"name": f.stem, "path": f, "type": d.get("study-type") or "inbox", "course_id": d.get("course-id") or "",
                    "module_id": d.get("module-id") or "", "module": d.get("module") or "",
                    "lesson": int(lesson) if lesson.isdigit() else None, "category": d.get("category") or "",
                    "status": d.get("status") or "", "next": d.get("next-review") or "", "created": d.get("created") or "",
                    "stage": d.get("review-stage") or "",
                    "cover": d.get("cover") or "", "lid": d.get("lumen-id") or ""})
    return out


def _link(name, label=None):
    return f"[[{name}|{label}]]" if label and label != name else f"[[{name}]]"


def _lesson_line(l):
    return "- " + _link(l["name"]) + (f" · Aula {l['lesson']:02d}" if l["lesson"] else "")


def _plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def _course_block(c, mine, today):
    by_mod = {}
    for l in sorted(mine, key=lambda x: (x["lesson"] or 999, x["name"].casefold())):
        by_mod.setdefault(l["module_id"], []).append(l)
    done = sum(1 for l in mine if l["status"] == "completed")
    due = sum(1 for l in mine if l["next"] and str(l["next"]) <= today)
    s = [f"# {md(c['name'])}"]
    acc = [f"- **Plataforma:** {md(c['platform'])}" if c.get("platform") else "- **Plataforma:** não informada"]
    if c.get("url"):
        acc.append(f"- **Endereço:** [Abrir o curso]({obsidian._url(c['url'])})")
    acc.append("- **Login e senha:** no seu gerenciador de senhas. O Lumen não guarda credenciais.")
    s.append("## Acesso\n" + "\n".join(acc))
    s.append("## Progresso\n" + (f"- {_plural(len(mine), 'aula processada', 'aulas processadas')} · "
                                 f"{_plural(done, 'concluída', 'concluídas')} · {due} para revisar hoje"
                                 if mine else "- Nenhuma aula processada ainda."))
    mods = sorted(c.get("modules") or [], key=lambda m: (m.get("order") or 999, m["name"].casefold()))
    if mods:
        body = []
        for m in mods:
            items = by_mod.pop(m["id"], [])
            body.append(f"### {md(module_name(m['name'], m.get('order')))}\n"
                        + ("\n".join(map(_lesson_line, items)) if items else "*Nenhuma aula ainda.*"))
        rest = [l for ls in by_mod.values() for l in ls]
        if rest:
            body.append("### Sem módulo\n" + "\n".join(map(_lesson_line, rest)))
        s.append("## Módulos\n" + "\n\n".join(body))
    elif mine:
        s.append("## Aulas\n" + "\n".join(_lesson_line(l) for ls in by_mod.values() for l in ls))
    s.append(f"""## Para revisar
```base
filters:
  and:
    - 'type == "ai-study"'
    - 'note["course-id"] == "{c['id']}"'
    - 'note["next-review"] <= today()'
views:
  - type: table
    name: Para revisar
    order:
      - file.name
      - module
      - review-stage
      - next-review
    sort:
      - property: next-review
        direction: ASC
```""")
    return "\n\n".join(s)


COURSE_INFO = """> [!info]- Como usar esta nota
> Página inicial do curso, mantida pelo Lumen: acesso, progresso, módulos e aulas em ordem e o que revisar. As aulas ficam nas pastas abaixo desta. Escreva o que quiser a partir de "Sobre": o Lumen nunca altera essa parte."""

HOME_INFO = """> [!info]- Como usar esta nota
> Central dos estudos. As listas vêm da base [[Estudos.base|Estudos]] (Bases, nativo do Obsidian) e se atualizam sozinhas; sem Bases, os links de cursos e temas abaixo e as pastas continuam servindo. O Lumen mantém o bloco de cima; o que você escrever em "Minhas anotações" nunca é alterado."""


def _home_block(cat, lessons, today, names):
    by_course = {}
    for l in lessons:
        by_course.setdefault(l["course_id"], []).append(l)
    courses = sorted(cat["courses"], key=lambda c: c["name"].casefold())
    s = ["# Estudos",
         "> [!summary] Central de estudos\n> Tudo o que o Lumen processou, organizado por tipo: cursos (curso, módulo e "
         "aula), conteúdo gratuito (por tema), aulas avulsas e o que ainda falta organizar.",
         "## Para revisar hoje\n![[Estudos.base#Para revisar]]",
         "## Continuar estudando\n![[Estudos.base#Continuar estudando]]"]
    lines = [f"- {_link(names.get(c['id']) or '00 - ' + clean(c['name'], 40), c['name'])} · "
             f"{_plural(len(by_course.get(c['id'], [])), 'aula', 'aulas')}" + (f" · {md(c['platform'])}" if c.get("platform") else "")
             for c in courses]
    s.append("## Cursos\n" + ("\n".join(lines) if lines else "*Nenhum curso ainda. Crie o primeiro no Lumen, em Nova aula → "
                                                             "Organização.*"))
    for t, title in (("free", "Conteúdo gratuito"), ("single", "Aulas avulsas")):
        mine = [l for l in lessons if l["type"] == t]
        if not mine:
            continue
        groups = {}
        for l in sorted(mine, key=lambda x: x["created"], reverse=True):
            groups.setdefault(l["category"] or "Sem tema", []).append(l)
        s.append(f"## {title}\n" + "\n".join(
            f"- **{md(g)}** · {len(ls)}: " + ", ".join(_link(l["name"]) for l in ls[:5]) + (f" e mais {len(ls) - 5}" if len(ls) > 5 else "")
            for g, ls in sorted(groups.items(), key=lambda x: x[0].casefold())))
    todo = [l for l in lessons if l["type"] == "inbox"]
    if todo:
        s.append(f"## Materiais para organizar\n> [!todo] {_plural(len(todo), 'material espera', 'materiais esperam')} "
                 "organização\n> No Lumen: Biblioteca → A organizar → Organizar. A aula vai inteira para o lugar certo "
                 "(nota, mapas e anexos).\n\n![[Estudos.base#A organizar]]")
    s.append("## Adicionados recentemente\n![[Estudos.base#Recentes]]")
    return "\n\n".join(s)


def base_text(home_rel):
    folder = home_rel.replace('"', '\\"')
    return f"""filters:
  and:
    - file.inFolder("{folder}")
    - 'file.ext == "md"'
    - not:
        - 'file.name.startsWith("00 - ")'
properties:
  file.name:
    displayName: Aula
  note.course:
    displayName: Curso
  note.module:
    displayName: Módulo
  note.lesson:
    displayName: Nº
  note.category:
    displayName: Tema
  note.study-type:
    displayName: Tipo
  note.next-review:
    displayName: Próxima revisão
  note.review-stage:
    displayName: Revisões feitas
  note.created:
    displayName: Processada em
views:
  - type: cards
    name: Biblioteca
    filters:
      and:
        - 'type == "ai-study"'
    order:
      - file.name
      - course
      - module
      - next-review
    sort:
      - property: created
        direction: DESC
    image: note.cover
  - type: table
    name: Para revisar
    filters:
      and:
        - 'note["next-review"] <= today()'
    order:
      - file.name
      - course
      - module
      - review-stage
      - next-review
    sort:
      - property: next-review
        direction: ASC
  - type: table
    name: Continuar estudando
    filters:
      and:
        - 'note["review-stage"] > 0'
        - 'note["next-review"] > today()'
    order:
      - file.name
      - course
      - module
      - next-review
    sort:
      - property: next-review
        direction: ASC
  - type: cards
    name: Recentes
    limit: 12
    order:
      - file.name
      - course
      - category
    sort:
      - property: created
        direction: DESC
    image: note.cover
  - type: table
    name: Cursos
    filters:
      and:
        - 'note["study-type"] == "course"'
    order:
      - file.name
      - module
      - lesson
      - next-review
    sort:
      - property: module
        direction: ASC
      - property: lesson
        direction: ASC
    groupBy:
      property: course
      direction: ASC
  - type: table
    name: Conteúdo gratuito
    filters:
      and:
        - 'note["study-type"] == "free"'
    order:
      - file.name
      - created
      - next-review
    groupBy:
      property: category
      direction: ASC
  - type: table
    name: Aulas avulsas
    filters:
      and:
        - 'note["study-type"] == "single"'
    order:
      - file.name
      - created
      - next-review
    groupBy:
      property: category
      direction: ASC
  - type: table
    name: A organizar
    filters:
      and:
        - 'note["study-type"] == "inbox"'
    order:
      - file.name
      - created
    sort:
      - property: created
        direction: DESC
  - type: table
    name: Gerados pelo Lumen
    filters:
      and:
        - 'author == "lumen-ai"'
    order:
      - file.name
      - study-type
      - course
      - created
    sort:
      - property: created
        direction: DESC
  - type: table
    name: Todos
    order:
      - file.name
      - study-type
      - course
      - module
      - category
      - created
    sort:
      - property: created
        direction: DESC
"""


def _managed(path, fm_new, block, info, user, owned):
    """Cria a nota (callout, bloco do Lumen, área do usuário) ou atualiza só o que é do Lumen: o bloco, se ninguém o
    editou, e as chaves `owned` do frontmatter. Nada é gravado se nada mudou."""
    if not path.exists():
        obsidian._write(path, compose(merge_fields([], fm_new), "\n" + info + "\n\n" + BEGIN, block, user))
        return True
    text = path.read_text("utf-8").replace("\r\n", "\n")
    p = parts(text)
    if not p:
        return False  # perdeu as marcas: é do usuário agora
    fm, before, old, saved, after = p
    keep = old if saved != block_hash(old) else block  # editado à mão: o bloco fica
    calm = {k: v for k, v in fm_new.items() if k != "updated"}
    out = compose(merge_fields(fm, calm, owned=owned), before, keep, after)
    if out == text:
        return False
    out = compose(merge_fields(fm, fm_new, owned=owned), before, keep, after)
    obsidian._write(path, out)
    return True


def _course_notes(home):
    """course-id → nota do curso, onde estiver na área."""
    out = {}
    for f in home.rglob("00 - *.md"):
        try:
            d = vault.fields(vault.split(f.read_text("utf-8"))[0])
        except (OSError, UnicodeDecodeError):
            continue
        if d.get("type") == "course" and d.get("course-id"):
            out[str(d["course-id"])] = f
    return out


def refresh(cfg):
    """Base, Home e a nota de cada curso, a partir das notas da área e do catálogo."""
    root, home = obsidian.folders(cfg)
    home.mkdir(parents=True, exist_ok=True)
    cat, today = catalog.load(), date.today().isoformat()
    lessons = _lessons(home)
    # Estudos.base: o Obsidian regrava o arquivo quando o usuário ajusta uma visão; só o que o Lumen gravou é trocado
    bpath, btext = home / BASE, base_text(home.relative_to(root).as_posix())
    cur = _read(bpath) if bpath.exists() else None
    if cur != btext and (cur is None or _hash(cur) == cat["meta"].get("base_hash")):
        obsidian._write(bpath, btext)
        with store.LOCK:
            c2 = catalog.load()
            c2["meta"]["base_hash"] = _hash(btext)
            catalog.save(c2)
    notes, names = _course_notes(home), {}
    for c in cat["courses"]:
        mine = [l for l in lessons if l["course_id"] == c["id"]]
        want = course_dir(home, c["name"]) / f"00 - {clean(c['name'], 40)}.md"
        have = notes.get(c["id"])
        if have and have != want and have.parent == want.parent and not want.exists():
            os.rename(have, want)  # curso renomeado: a pasta já foi; falta o nome da nota
            have = want
        path = have or want
        cover = next((l["cover"] for l in mine if l["cover"]), None)
        fm = {"type": "course", "author": "lumen-ai", "status": "active", "course": c["name"], "course-id": c["id"],
              "platform": c.get("platform") or "", "url": c.get("url") or "", "created": c.get("created") or today,
              "updated": today, "lessons": len(mine), "completed": sum(1 for l in mine if l["status"] == "completed"),
              "cover": cover}
        path.parent.mkdir(parents=True, exist_ok=True)
        names[c["id"]] = path.stem
        _managed(path, fm, _course_block(c, mine, today), COURSE_INFO, USER_COURSE,
                 {"course", "course-id", "platform", "url", "lessons", "completed", "updated"})
    fm = {"type": "system", "author": "lumen-ai", "status": "active", "created": today, "updated": today}
    _managed(home / HOME, fm, _home_block(cat, lessons, today, names), HOME_INFO, USER, {"updated"})


# --- Migração da pasta antiga ----------------------------------------------------------------------------------

def _title(note, n):
    return (n.get("aliases") or [None])[0] or _DATE.sub("", note.stem)


def plan(cfg):
    """O que a migração faria, sem tocar em nada: as aulas da pasta antiga do Lumen, com os arquivos de cada uma, e
    para onde iriam (A organizar: a classificação delas não é conhecida, então nada é adivinhado)."""
    root, home = obsidian.folders(cfg)
    hist = store.history()
    by_lid = {v.get("lumen_id"): (k, v) for k, v in hist.items() if v.get("lumen_id")}
    olds = {p for p in vault.legacy_folders(root)}
    for k, v in hist.items():
        rel = (v.get("obsidian") or {}).get("note")
        if rel and (root / rel).is_file() and home not in (root / rel).resolve().parents:
            olds.add((root / rel).parent.resolve())
    olds = {d for d in olds if d != home and home not in d.parents and d not in home.parents}
    lessons, refs = [], {}
    for n in vault.index(root):
        note = (root / n["path"]).resolve()
        if not (n["lumen_id"] and n["type"] == "ai-study" and note.parent in olds):
            continue
        key, entry = by_lid.get(n["lumen_id"], (None, {}))
        files = lesson_files(root, note, n["lumen_id"], entry.get("obsidian") or {})
        title = clean(_title(note, n), 80)
        lessons.append({"lid": n["lumen_id"], "key": key, "title": title, "files": files,
                        "target": lesson_dir(home, catalog.INBOX, title, n["lumen_id"])})
        for f in files["attachments"]:
            refs.setdefault(str(f).casefold(), set()).add(n["lumen_id"])
    targets = {}
    for l in lessons:  # duas aulas antigas com o mesmo título: pastas diferentes
        k = str(l["target"]).casefold()
        if k in targets:
            l["target"] = l["target"].with_name(f"{l['target'].name} · {l['lid'][3:9]}")
        targets[str(l["target"]).casefold()] = l
        l["shared"] = [f for f in l["files"]["attachments"] if len(refs.get(str(f).casefold(), ())) > 1]
    dash = [d / "Lumen Dashboard.md" for d in olds if (d / "Lumen Dashboard.md").is_file()]
    return {"root": root, "home": home, "folders": sorted(olds), "lessons": lessons, "dashboards": dash}


def plan_view(cfg):
    """O plano para a tela (caminhos relativos ao cofre)."""
    try:
        p = plan(cfg)
    except AppError:
        return {"lessons": [], "folders": []}
    r = lambda f: _rel(p["root"], f)  # noqa: E731
    return {"area": r(p["home"]), "folders": [r(d) for d in p["folders"]], "dashboards": [r(d) for d in p["dashboards"]],
            "lessons": [{"title": l["title"], "target": r(l["target"]), "canvas": bool(l["files"]["canvas"]),
                         "board": bool(l["files"]["board"]), "attachments": len(l["files"]["attachments"]),
                         "shared": len(l["shared"])} for l in p["lessons"]]}


def _zip(root, folders, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d in folders:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    z.write(f, _rel(root, f))
    return out


def migrate(cfg):
    """Move as aulas da pasta antiga para `90 - A organizar/<Aula>/` (nota, mapa, painel e anexos juntos), sem renomear
    arquivos. Antes, um zip da pasta antiga em DATA/obsidian-backups. Rodar de novo não faz nada."""
    recover(cfg)
    p = plan(cfg)
    root, home = p["root"], p["home"]
    if not p["lessons"] and not p["dashboards"]:
        return {"moved": 0, "backup": None, "lessons": []}
    backup = _zip(root, p["folders"], store.DATA / "obsidian-backups" / f"migracao-{datetime.now():%Y%m%d-%H%M%S}.zip")
    moves = []
    for l in p["lessons"]:
        f, t = l["files"], l["target"]
        moves += [(x, t / x.name) for x in (f["note"], f["canvas"], f["board"]) if x]
        moves += [(x, t / "Anexos" / x.name) for x in f["attachments"] if x not in l["shared"]]
    pairs = [(_rel(root, a), _rel(root, b)) for a, b in moves]
    remap = _remapper(pairs)
    done = _apply(root, moves, JOURNAL)
    try:
        _rewrite_canvases(root, home, remap, "migracao")
        sig = catalog.signature(catalog.INBOX)
        extra = {l["key"]: {"classification": dict(catalog.INBOX)} for l in p["lessons"] if l["key"]}
        _remap_history(remap, only=set(extra), extra=extra)
        with store.LOCK:
            h = store.history()
            for k in extra:
                if isinstance(h[k].get("obsidian"), dict):
                    h[k]["obsidian"]["placed"] = sig
            store._write("history.json", h)
        for l in p["lessons"]:
            obsidian.set_fields(root / remap(_rel(root, l["files"]["note"])), obsidian.class_fields(catalog.INBOX))
    except BaseException:
        _undo(done)
        (store.DATA / JOURNAL).unlink(missing_ok=True)
        raise
    (store.DATA / JOURNAL).unlink(missing_ok=True)
    for d in p["dashboards"]:  # o painel antigo virou a Home: sai se ninguém escreveu nele (o zip guarda)
        q = parts(_read(d).replace("\r\n", "\n"))
        mine = q and q[3] == block_hash(q[2]) and not re.sub(r"%%.*?%%|## Minhas anotações", "", q[4], flags=re.S).strip()
        if mine:
            d.unlink()
        elif "00 - Estudos" not in _read(d):
            obsidian._write(d, _read(d).rstrip("\n") + "\n\n> [!note] Substituído\n> O painel de estudos agora é "
                            "[[00 - Estudos]], na área de estudos.\n")
    left = []
    for d in p["folders"]:
        for sub in sorted((x for x in d.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
            if not any(sub.iterdir()):
                sub.rmdir()
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
        elif d.is_dir():
            left.append(d)
            readme = d / "README - Migrado para Estudos.md"
            if not readme.exists():
                obsidian._write(readme, f"---\ntype: system\nauthor: lumen-ai\ncreated: {date.today().isoformat()}\n---\n\n"
                                "> [!info]- Como usar esta nota\n> Esta era a pasta do Lumen. As aulas foram para a área "
                                f"de estudos ({md(_rel(root, home))}); a central é [[00 - Estudos]]. O que ficou aqui não "
                                "foi movido porque não é de uma aula do Lumen ou é usado por mais de uma.\n")
    refresh(cfg)
    log.info("área: migração concluída (%d aulas, %d arquivos)", len(p["lessons"]), len(moves))
    return {"moved": len(p["lessons"]), "files": len(moves), "backup": str(backup),
            "keys": [l["key"] for l in p["lessons"] if l["key"]], "left": [_rel(root, d) for d in left]}
