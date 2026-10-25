"""Organização dos estudos: a StudyClassification (tipo → curso → módulo → aula; conteúdo gratuito → tema; aula avulsa;
A organizar) e o catálogo de cursos e módulos.

A classificação é do estudo, não de um destino: fica no StudyPackage e no manifesto, e cada destino a traduz (area.py:
pasta no cofre; jobs._notion_parent: página no Notion). Curso e módulo têm id estável, então renomear não muda a
identidade. Os nomes viram pastas e títulos. DATA/catalog.json não sai com “Limpar dados locais”, porque é organização
e não conteúdo de aula."""
import difflib
import re
import secrets
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta

from . import AppError, store
from .package import _SECRET, norm

TYPES = ("course", "free", "single", "inbox")
LABELS = {"course": "Cursos", "free": "Conteúdo gratuito", "single": "Aulas avulsas", "inbox": "A organizar"}
FILE = "catalog.json"
INBOX = {"type": "inbox"}


def _text(v, limit):
    t = " ".join(unicodedata.normalize("NFC", str(v or "")).split())[:limit].strip()
    if _SECRET.search(t):
        raise AppError("Esse campo parece conter uma senha ou um token.",
                       "O Lumen não guarda credenciais: use o seu gerenciador de senhas.")
    return t


def _url(v):
    """Endereço da plataforma, só http(s) e sem usuário/senha embutidos (nunca guardamos credenciais)."""
    raw = _text(v, 500)
    if not raw:
        return ""
    p = urllib.parse.urlsplit(raw if "://" in raw else "https://" + raw)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise AppError("O endereço da plataforma não é válido.", "Use um link como https://plataforma.com/curso.")
    return urllib.parse.urlunsplit((p.scheme, p.hostname + (f":{p.port}" if p.port else ""), p.path, p.query, ""))


def load():
    cat = store._read(FILE, {})
    cat.setdefault("courses", [])
    cat.setdefault("meta", {})
    return cat


def save(cat):
    store._write(FILE, cat)


def course(cat, cid):
    return next((c for c in cat["courses"] if c["id"] == cid), None)


def module(c, mid):
    return next((m for m in (c or {}).get("modules") or [] if m["id"] == mid), None)


def similar(names, name):
    """Nomes iguais (sem acento e caixa) ou muito parecidos: candidatos à mesma entidade, nunca unidos sozinhos."""
    n = norm(name)
    same = [x for x in names if norm(x) == n]
    near = [x for x in names if norm(x) != n and difflib.SequenceMatcher(None, norm(x), n).ratio() >= 0.85]
    return same, near


def _check_new(names, name, what):
    if not name:
        raise AppError(f"Dê um nome ao {what}.", "")
    same, _ = similar(names, name)
    if same:  # numa pasta do Windows, “Edição” e “EDIÇÃO” seriam a mesma: nunca dois
        raise AppError(f"Já existe o {what} “{same[0]}”.", f"Escolha o {what} existente ou use outro nome.")


def create_course(name, platform="", url="", notion_page_id=None):
    with store.LOCK:
        cat = load()
        name = _text(name, 80)
        _check_new([c["name"] for c in cat["courses"]], name, "curso")
        c = {"id": "c-" + secrets.token_hex(4), "name": name, "platform": _text(platform, 60), "url": _url(url),
             "created": date.today().isoformat(), "notion_page_id": notion_page_id, "modules": []}
        cat["courses"].append(c)
        save(cat)
        return c


def update_course(cid, **kw):
    """Renomeia ou edita (plataforma, link, página do Notion). Devolve (antes, depois)."""
    with store.LOCK:
        cat = load()
        c = course(cat, cid)
        if not c:
            raise AppError("Curso não encontrado.", "Recarregue a Biblioteca.")
        old = dict(c)
        if "name" in kw:
            name = _text(kw["name"], 80)
            _check_new([x["name"] for x in cat["courses"] if x["id"] != cid], name, "curso")
            c["name"] = name
        if "platform" in kw:
            c["platform"] = _text(kw["platform"], 60)
        if "url" in kw:
            c["url"] = _url(kw["url"])
        if "notion_page_id" in kw:
            c["notion_page_id"] = kw["notion_page_id"]
        save(cat)
        return old, dict(c)


def create_module(cid, name, order=None, notion_page_id=None):
    with store.LOCK:
        cat = load()
        c = course(cat, cid)
        if not c:
            raise AppError("Curso não encontrado.", "Escolha o curso de novo.")
        name = _text(name, 80)
        _check_new([m["name"] for m in c["modules"]], name, "módulo")
        m = {"id": "m-" + secrets.token_hex(4), "name": name, "order": _order(order), "notion_page_id": notion_page_id}
        c["modules"].append(m)
        save(cat)
        return m


def update_module(cid, mid, **kw):
    with store.LOCK:
        cat = load()
        c = course(cat, cid)
        m = module(c, mid)
        if not m:
            raise AppError("Módulo não encontrado.", "Recarregue a Biblioteca.")
        old = dict(m)
        if "name" in kw:
            name = _text(kw["name"], 80)
            _check_new([x["name"] for x in c["modules"] if x["id"] != mid], name, "módulo")
            m["name"] = name
        if "order" in kw:
            m["order"] = _order(kw["order"])
        if "notion_page_id" in kw:
            m["notion_page_id"] = kw["notion_page_id"]
        save(cat)
        return old, dict(m)


def _order(v):
    if v in (None, ""):
        return None
    n = int(v)
    if not 1 <= n <= 99:
        raise AppError("A ordem do módulo vai de 1 a 99.", "")
    return n


def classification(raw, cat=None):
    """Valida e completa a classificação pelo catálogo (os nomes vêm de lá: renomear um curso vale para todas as aulas).
    Curso ou módulo que o catálogo não conhece (dados locais apagados) volta a ele a partir do que o pacote guardou."""
    raw = raw if isinstance(raw, dict) else {}
    t = raw.get("type") if raw.get("type") in TYPES else "inbox"
    out = {"type": t}
    lesson = raw.get("lesson")
    if lesson not in (None, ""):
        lesson = int(lesson)
        if not 1 <= lesson <= 999:
            raise AppError("O número da aula vai de 1 a 999.", "")
        out["lesson"] = lesson
    if t == "course":
        cat = cat or load()
        c = course(cat, raw.get("course_id"))
        if not c and raw.get("course_id") and raw.get("course"):
            c = _adopt(raw)
        if not c:
            raise AppError("Escolha o curso desta aula.", "Ou escolha “Organizar depois”.")
        out.update(course_id=c["id"], course=c["name"])
        if c.get("platform"):
            out["platform"] = c["platform"]
        if raw.get("module_id"):
            m = module(c, raw["module_id"]) or (_adopt_module(c["id"], raw) if raw.get("module") else None)
            if not m:
                raise AppError("O módulo escolhido não existe mais neste curso.", "Escolha o módulo de novo.")
            out.update(module_id=m["id"], module=m["name"])
            if m.get("order"):
                out["module_order"] = m["order"]
    elif t in ("free", "single"):
        cat_name = _text(raw.get("category"), 40)
        if cat_name:
            out["category"] = cat_name
    return out


def _adopt(raw):
    """Curso que o pacote conhece pelo id e o catálogo não (catalog.json apagado): volta com o mesmo id."""
    if not re.fullmatch(r"c-[0-9a-f]{8}", str(raw["course_id"])):
        return None
    with store.LOCK:
        cat = load()
        c = {"id": raw["course_id"], "name": _text(raw["course"], 80), "platform": _text(raw.get("platform"), 60),
             "url": "", "created": date.today().isoformat(), "notion_page_id": None, "modules": []}
        cat["courses"].append(c)
        save(cat)
        return c


def _adopt_module(cid, raw):
    if not re.fullmatch(r"m-[0-9a-f]{8}", str(raw["module_id"])):
        return None
    with store.LOCK:
        cat = load()
        c = course(cat, cid)
        m = {"id": raw["module_id"], "name": _text(raw["module"], 80), "order": raw.get("module_order"),
             "notion_page_id": None}
        c["modules"].append(m)
        save(cat)
        return m


def signature(cls):
    """O que decide o lugar da aula (nomes ficam de fora: renomear move o curso inteiro, não a aula)."""
    cls = cls or INBOX
    return "|".join(str(cls.get(k) or "") for k in ("type", "course_id", "module_id", "lesson", "category"))


def breadcrumb(cls):
    cls = cls or INBOX
    out = [LABELS[cls.get("type", "inbox")]]
    if cls.get("type") == "course":
        out += [cls.get("course"), cls.get("module")]
    elif cls.get("category"):
        out.append(cls["category"])
    out = [x for x in out if x]
    if cls.get("lesson"):
        out[-1] += f" · Aula {cls['lesson']:02d}"
    return out


def remember(cls):
    with store.LOCK:
        cat = load()
        cat["last"] = {**{k: v for k, v in (cls or {}).items() if k in ("type", "course_id", "module_id", "lesson",
                                                                         "category")},
                       "at": datetime.now().isoformat(timespec="seconds")}
        save(cat)


def suggest(title="", link="", path="", cat=None):
    """Sugestões para a Nova aula (nunca aplicadas sozinhas): continuar onde parou, nas últimas 12 h, com a próxima
    aula, e o curso cujo nome aparece no título, no link ou no caminho do arquivo. Link do YouTube sem curso que
    combine sugere Conteúdo gratuito."""
    cat = cat or load()
    out = []
    last = cat.get("last") or {}
    try:
        recent = datetime.now() - datetime.fromisoformat(last.get("at") or "") < timedelta(hours=12)
    except ValueError:
        recent = False
    if recent and last.get("type") in TYPES and last["type"] != "inbox":
        nxt = {k: v for k, v in last.items() if k != "at"}
        if nxt.get("lesson"):
            nxt["lesson"] = min(999, int(nxt["lesson"]) + 1)
        try:
            out.append({"why": "continuar", "classification": classification(nxt, cat)})
        except (AppError, ValueError, TypeError):
            pass
    hay = norm(f"{title} {path} {urllib.parse.unquote(link or '')}")
    for c in cat["courses"]:
        if len(norm(c["name"])) >= 4 and norm(c["name"]) in hay and not any(
                s["classification"].get("course_id") == c["id"] for s in out):
            out.append({"why": "nome", "classification": classification({"type": "course", "course_id": c["id"]}, cat)})
    if not any(s["why"] == "nome" for s in out) and re.search(r"youtu\.?be", link or "", re.I):
        out.append({"why": "youtube", "classification": {"type": "free"}})
    return out[:3]


def categories(items):
    """Temas já usados (conteúdo gratuito e aulas avulsas), para o seletor sugerir em vez de criar parecidos."""
    seen = {}
    for it in items:
        c = (it.get("classification") or {}).get("category")
        if c:
            seen.setdefault(norm(c), c)
    return sorted(seen.values(), key=norm)
