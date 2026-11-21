"""Criações fora do Lúmen: prévia, confirmação ou autonomia restrita às áreas da IA.

prepare() registra o destino e conteúdo; finish() só cria automaticamente quando há pedido explícito
e a permissão permite esse destino. confirm() atende a confirmação da prévia.

Nada é sobrescrito: no cofre, um nome já usado ganha " (2)"; no Notion, a criação vai com once=True e, se a resposta
se perder (Unconfirmed), a ação fica "a conferir" em vez de criar de novo. Editar ou apagar originais não existe aqui."""
import json
import hashlib
import os
import re
import shutil
import threading
from datetime import date

from .. import AppError, notion, obsidian, store, vault
from . import activity, db, settings
from .sources import notion as notion_source

KINDS = ("obsidian-note", "notion-page")
AI_FOLDER = "C04 Claude Obsidian/01 Outputs"
LOCK = threading.RLock()


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def automatic(preview):
    """Só a área fixa da IA autoriza criar sem prévia; mudar o destino não amplia a permissão."""
    if settings.load()["privacy"]["organize"] != "ai":
        return False
    if preview["kind"] == "notion-page":
        return True  # _write_notion sempre cria dentro do contêiner Study AI
    root = vault.check(store.load_config()["obsidian_vault"])
    folder = vault.inside(root, preview["path"]).parent
    area = root / AI_FOLDER
    return (folder == area or area in folder.parents) and not preview.get("protected")


def finish(action, requested=False):
    """A permissão de criar vem do pedido do estudante, nunca de uma fonte lida pela IA."""
    if requested and automatic(action):
        return {**confirm(action["id"], automatic=True), "status": "done"}
    return {**action, "status": "pending"}


def completed(conversation_id):
    return [{"id": r["id"], "kind": r["kind"], "title": r["title"], "status": r["status"],
             **{k: v for k, v in db.loads(r["result"], {}).items() if not k.startswith("_")}}
            for r in db.rows("SELECT * FROM pending_actions WHERE conversation_id = ? AND status IN ('done','undone') ORDER BY created", conversation_id)]


def _protected_areas(root):
    """Áreas com regra "ask" no .claude/settings.json do cofre (as que o CLAUDE.md protege), se o arquivo existir."""
    try:
        data = json.loads((root / ".claude" / "settings.json").read_text("utf-8"))
        rules = data.get("permissions", {}).get("ask", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [m[1] for m in (re.match(r"^Edit\(/(.+?)(?:/\*\*)?\)$", str(r)) for r in rules) if m]


def _similar_titles(title):
    words = [w for w in re.findall(r"\w{4,}", title.casefold())][:6]
    if not words:
        return []
    rows = db.rows("SELECT id, title, source, path FROM documents WHERE " + " AND ".join(["lower(title) LIKE ?"] * len(words)) +
                   " LIMIT 5", *[f"%{w}%" for w in words])
    return [{"id": r["id"], "title": r["title"], "source": r["source"], "path": r["path"]} for r in rows]


def note_markdown(title, request, answer, sources, unverified="", next_steps=""):
    """Nota no formato `Template - Output IA` do cofre (author: lumen-ai)."""
    linked = [s for s in sources if s.get("source") == "obsidian"]
    related = ", ".join(f'"[[{s["title"]}]]"' for s in linked[:20])
    used = "\n".join(f"- [[{s['title']}]]" if s.get("source") == "obsidian" else
                     f"- {s['title']} (Notion{': ' + s['url'] if s.get('url') else ''})" if s.get("source") == "notion" else
                     f"- {s.get('title', '')} ({s.get('source', '')})" + (f" — {s['url']}" if s.get('url') else "")
                     for s in sources) or "- Nenhuma nota do cofre foi usada."
    return f"""---
type: ai-output
author: lumen-ai
status: review-required
created: {date.today().isoformat()}
source: Lúmen Study AI
related: [{related}]
---

> [!info]- Como usar esta nota
> Entrega do Lúmen Study AI. Revise e mude o status para completed (aproveitado) ou archived (descartado). Nada daqui entra em nota autoral sem autorização.

> [!warning] Conteúdo gerado por IA
> Produzido pelo Lúmen a partir das suas notas. Ainda não representa necessariamente suas conclusões; revise antes de levar ao seu conhecimento permanente.

# {title}

## Pedido
{request.strip() or "—"}

## Resposta
{answer.strip()}

## Notas do cofre utilizadas
{used}

## Não verificado
{unverified.strip() or "Nenhuma afirmação sem fonte foi marcada pelo Lúmen. Confira as referências acima."}

## Próximos passos sugeridos
{next_steps.strip() or "—"}

## Decisão do usuário
- [ ] Aproveitar: reescrever em nota própria ou autorizar incorporação em:
- [ ] Descartar
"""


def prepare(kind, title, content, conversation_id="", meta=None):
    if kind not in KINDS:
        raise AppError("Destino de gravação desconhecido.")
    s = settings.load()
    if s["privacy"]["organize"] == "off":
        raise AppError("Criar notas e páginas está desligado.", "Ligue em Estudos → Configurações → Privacidade.")
    title = obsidian.clean(" ".join(str(title or "").split()) or "Estudo", 90) if kind == "obsidian-note" else \
        " ".join(str(title or "").split())[:150] or "Estudo"
    content = str(content or "")[:200_000]
    if not content.strip():
        raise AppError("Não há conteúdo para salvar.")
    preview = {"kind": kind, "title": title, "content": content, "duplicates": _similar_titles(title), "warnings": []}
    if kind == "obsidian-note":
        root = vault.check(store.load_config()["obsidian_vault"])
        folder_rel = s["connectors"]["obsidian_output"]
        folder = vault.inside(root, folder_rel)
        name = f"{date.today().isoformat()} - {title}.md"
        target = folder / name
        n = 2
        while target.exists():
            target = folder / f"{date.today().isoformat()} - {title} ({n}).md"
            n += 1
        rel = target.relative_to(root).as_posix()
        preview.update(folder=folder_rel, path=rel, vault=root.name, root=str(root))
        if any(rel == a or rel.startswith(a.rstrip("/") + "/") for a in _protected_areas(root)):
            preview["protected"] = True
            preview["warnings"].append("Esta pasta é uma área protegida pelo seu CLAUDE.md (o Claude Code pede confirmação para escrever nela).")
    else:
        if not store.get_token():
            raise AppError("O Notion não está conectado.", "Conecte o Notion em Integrações.")
        parent = s["connectors"]["notion_parent"] or store.load_config()["root_page_id"]
        if not parent:
            raise AppError("Falta escolher a página do Notion onde salvar.", "Escolha a página principal em Integrações → Notion.")
        preview.update(parent=notion.page_id(parent), container="Lúmen Study AI")
    if len(preview["duplicates"]):
        preview["warnings"].append("Já existem notas com título parecido. Confira antes de criar outra.")
    aid = db.new_id()
    with db.tx() as c:
        c.execute("""INSERT INTO pending_actions(id, kind, level, title, preview, payload, status, created, conversation_id)
                     VALUES (?, ?, 2, ?, ?, ?, 'pending', ?, ?)""",
                  (aid, kind, title, db.dumps(preview), db.dumps(meta or {}), db.now(), conversation_id or ""))
    activity.log("preparar-gravacao", tool=kind, target=preview.get("path") or title, result="aguardando confirmação",
                 permission="nível 2", conversation_id=conversation_id)
    return {"id": aid, **preview}


def pending_preview(aid):
    row = db.one("SELECT preview FROM pending_actions WHERE id = ? AND status = 'pending'", aid)
    if not row:
        raise AppError("Esta ação não está mais pendente.")
    return db.loads(row["preview"], {})


def update_preview(aid, preview):
    with db.tx() as c:
        c.execute("UPDATE pending_actions SET preview = ? WHERE id = ? AND status = 'pending'", (db.dumps(preview), aid))


def pending(conversation_id=None):
    if conversation_id:
        rows = db.rows("SELECT * FROM pending_actions WHERE status = 'pending' AND conversation_id = ? ORDER BY created", conversation_id)
    else:
        rows = db.rows("SELECT * FROM pending_actions WHERE status = 'pending' ORDER BY created")
    return [{"id": r["id"], **db.loads(r["preview"], {})} for r in rows]


def cancel(aid):
    with db.tx() as c:
        n = c.execute("UPDATE pending_actions SET status = 'cancelled', decided = ? WHERE id = ? AND status = 'pending'",
                      (db.now(), aid)).rowcount
    if not n:
        raise AppError("Esta ação não está mais pendente.")
    activity.log("cancelar-gravacao", target=aid, result="cancelada pelo usuário", permission="nível 2")
    return {"ok": True}


def confirm(aid, title=None, content=None, automatic=False):
    with LOCK:
        return _confirm(aid, title, content, automatic)


def _confirm(aid, title=None, content=None, auto=False):
    if settings.load()["privacy"]["organize"] == "off":
        raise AppError("Criar notas e páginas está desligado.")
    with db.tx() as c:
        row = c.execute("SELECT * FROM pending_actions WHERE id = ?", (aid,)).fetchone()
        if not row or row["status"] != "pending":
            raise AppError("Esta ação não está mais pendente.")
        if auto and not automatic(db.loads(row["preview"], {})):
            raise AppError("Este destino precisa de prévia e confirmação.")
        c.execute("UPDATE pending_actions SET status = 'running', decided = ? WHERE id = ?", (db.now(), aid))
    preview = db.loads(row["preview"], {})
    if isinstance(content, str) and content.strip():
        preview["content"] = content[:200_000]
    if isinstance(title, str) and title.strip() and row["kind"] == "notion-page":
        preview["title"] = " ".join(title.split())[:150]
    try:
        result = _write_obsidian(preview) if row["kind"] == "obsidian-note" else _write_notion(preview, aid)
        status = "done"
    except notion.Unconfirmed:
        result, status = {"message": "O Notion não confirmou a criação. Confira a página antes de tentar de novo."}, "unconfirmed"
    except (AppError, OSError) as e:
        result, status = {"message": str(e)}, "failed"
    if status != "done":
        partial = db.loads(db.value("SELECT result FROM pending_actions WHERE id = ?", aid), {})
        if partial.get("page"):
            result, status = {**partial, **result}, "unconfirmed"
    with db.tx() as c:
        c.execute("UPDATE pending_actions SET status = ?, result = ? WHERE id = ?", (status, db.dumps(result), aid))
    activity.log("gravar", tool=row["kind"], target=preview.get("path") or preview.get("title", ""), result=status,
                 permission="nível 2 · área IA" if auto else "nível 2 · confirmado", conversation_id=row["conversation_id"])
    if status != "done":
        raise AppError(result["message"])
    return {"ok": True, "id": aid, "kind": row["kind"], "title": row["title"],
            **{k: v for k, v in result.items() if not k.startswith("_")}}


def attachments_dir(root, note_folder):
    """A pasta de anexos do cofre (Obsidian → Arquivos e links → Local padrão dos anexos): a raiz, a pasta da nota,
    uma subpasta dela ("./x") ou uma pasta fixa. Sempre dentro do cofre."""
    try:
        p = str(json.loads((root / ".obsidian" / "app.json").read_text("utf-8")).get("attachmentFolderPath") or "/")
    except (OSError, ValueError, AttributeError):
        p = "/"
    rel = note_folder.relative_to(root).as_posix()
    rel = "" if p in ("", "/") else rel if p == "./" else f"{rel}/{p[2:]}" if p.startswith("./") else p
    return vault.inside(root, rel) if rel else root


def with_audio(preview, aid, src, title):
    """A prévia de uma revisão em áudio no Obsidian ganha o embed (![[...m4a]]) e diz para onde o arquivo vai ser
    copiado. Nada é copiado antes da confirmação."""
    root = vault.check(store.load_config()["obsidian_vault"])
    folder = attachments_dir(root, vault.inside(root, preview["path"]).parent)
    name = obsidian.clean(f"{title} - áudio", 80) + ".m4a"
    preview.update(audio={"id": aid, "file": name, "dir": folder.relative_to(root).as_posix()},
                   content=f"![[{name}]]\n\n" + preview["content"])
    preview["warnings"].append(f"O áudio ({src.stat().st_size / 1e6:.1f} MB) vai ser copiado para "
                               f"“{preview['audio']['dir'] or 'a raiz do cofre'}”, a pasta de anexos do cofre.")
    return preview


def _write_obsidian(preview):
    root = vault.check(store.load_config()["obsidian_vault"])
    if str(root) != preview.get("root", str(root)):
        raise AppError("O cofre mudou desde a prévia.", "Prepare de novo.")
    target = vault.inside(root, preview["path"])
    folder = vault.inside(root, settings.load()["connectors"]["obsidian_output"])
    if target.parent != folder or target.suffix != ".md":
        raise AppError("O destino da nota mudou desde a prévia.", "Prepare de novo.")
    if target.exists():
        raise AppError("Já existe uma nota com este nome.", "Prepare de novo para escolher outro nome.")
    folder.mkdir(parents=True, exist_ok=True)
    if preview.get("audio"):  # a revisão em áudio: o .m4a vai para a pasta de anexos antes da nota que o embute
        from . import listen
        a = preview["audio"]
        src, dest = listen.AUDIO / f"{listen.audio_meta(a['id'])['id']}.m4a", vault.inside(root, f"{a['dir']}/{a['file']}".lstrip("/"))
        if dest.suffix != ".m4a" or not src.exists():
            raise AppError("O áudio não está mais no PC.", "Gere o áudio de novo e prepare a gravação outra vez.")
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
    copied = None
    if preview.get("artifact"):
        a = preview["artifact"]
        blob, _ = _artifact(preview)
        dest_dir = attachments_dir(root, target.parent)
        if dest_dir.relative_to(root).as_posix() != a.get("dir"):
            raise AppError("A pasta de anexos mudou desde a prévia.", "Prepare de novo.")
        dest = vault.inside(root, f'{a["dir"]}/{a["file"]}')
        if dest.exists():
            raise AppError("Já existe um arquivo com este nome.", "Prepare outra prévia.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with dest.open("xb") as out:
                copied = dest
                out.write(blob)
        except BaseException:
            if copied:
                copied.unlink(missing_ok=True)
            raise
    try:
        with target.open("x", encoding="utf-8", newline="\n") as f:
            f.write(preview["content"])
    except BaseException:
        if copied:
            copied.unlink(missing_ok=True)
        raise
    return {"path": preview["path"], "uri": obsidian.uri(target), "message": f"Nota criada em {preview['path']}.",
            "_root": str(root), "_sha256": _hash(target.read_bytes()), "undo": True}


INLINE = re.compile(r"(\*\*[^*]+\*\*|\[[^\]]+\]\(https?://[^)\s]+\)|`[^`]+`)")


def _rich(text):
    out = []
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            out += notion._rt(part[2:-2], bold=True)
        elif part.startswith("[") and "](" in part:
            label, url = part[1:].split("](", 1)
            out += notion._rt(label, link=url[:-1])
        elif part.startswith("`") and part.endswith("`"):
            out += [{**x, "annotations": {**x["annotations"], "code": True}} for x in notion._rt(part[1:-1])]
        else:
            out += notion._rt(part)
    return out or notion._rt("")


def blocks(markdown):
    """Markdown simples → blocos do Notion (títulos, listas, tarefas, citações, código, divisórias, parágrafos)."""
    out, code, lang = [], None, ""
    for line in markdown.splitlines():
        if line.startswith("```"):
            if code is None:
                code, lang = [], line[3:].strip() or "plain text"
            else:
                out.append(notion._b("code", notion._rt("\n".join(code)[:6000]), language="plain text" if lang not in
                                     ("python", "javascript", "json", "bash", "markdown", "sql", "html", "css") else lang))
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            continue
        for prefix, kind in (("### ", "heading_3"), ("## ", "heading_2"), ("# ", "heading_1"), ("- [ ] ", "to_do"),
                             ("- [x] ", "to_do"), ("- ", "bulleted_list_item"), ("* ", "bulleted_list_item"), ("> ", "quote")):
            if stripped.startswith(prefix):
                extra = {"checked": prefix == "- [x] "} if kind == "to_do" else {}
                out.append(notion._b(kind, _rich(stripped[len(prefix):]), **extra))
                break
        else:
            m = re.match(r"^\d+[.)]\s+(.*)", stripped)
            if m:
                out.append(notion._b("numbered_list_item", _rich(m[1])))
            elif stripped in ("---", "***"):
                out.append({"object": "block", "type": "divider", "divider": {}})
            else:
                out.append(notion._b("paragraph", _rich(stripped)))
    if code is not None:
        out.append(notion._b("code", notion._rt("\n".join(code)[:6000]), language="plain text"))
    return out[:900]


def _container(token, parent):
    """A página "Lúmen Study AI" debaixo da página principal: achada pelo título ou criada uma vez."""
    for b in notion.all_children(token, parent):
        if b.get("type") == "child_page" and (b.get("child_page") or {}).get("title") == "Lúmen Study AI":
            return b["id"]
    page = notion.request("POST", "/pages", token, {"parent": {"page_id": parent},
                                                    "properties": {"title": {"title": notion._rt("Lúmen Study AI")}},
                                                    "children": [notion._b("paragraph", notion._rt(
                                                        "Páginas criadas pelo Lúmen Study AI conforme sua permissão de escrita."))]}, once=True)
    return page["id"]


def _write_notion(preview, aid):
    token = store.get_token()
    if not token:
        raise AppError("O Notion não está conectado.")
    parent = settings.load()["connectors"]["notion_parent"] or store.load_config()["root_page_id"]
    if notion.page_id(parent) != preview["parent"]:
        raise AppError("O destino do Notion mudou desde a prévia.", "Prepare de novo.")
    container = _container(token, preview["parent"])
    body = [notion._b("callout", notion._rt("Conteúdo gerado pelo Lúmen Study AI a partir das suas notas. Revise antes de usar."),
                      icon={"type": "emoji", "emoji": "🤖"})] + blocks(preview["content"])
    artifact_bytes = None
    if preview.get("artifact"):
        a = preview["artifact"]
        artifact_bytes, mime = _artifact(preview)
        up = notion.upload_image(token, artifact_bytes, a["file"], mime)
        body.insert(1, {"object": "block", "type": a["kind"], a["kind"]: {
            "type": "file_upload", "file_upload": {"id": up}, "caption": notion._rt(preview["content"])}})
    page = notion.request("POST", "/pages", token, {"parent": {"page_id": container},
                                                    "properties": {"title": {"title": notion._rt(preview["title"])}},
                                                    "children": body[:100]}, once=True)
    with db.tx() as c:
        c.execute("UPDATE pending_actions SET result = ? WHERE id = ?",
                  (db.dumps({"page": page["id"], "url": page.get("url", "")}), aid))
    rest = body[100:]
    for i in range(0, len(rest), 100):
        notion.request("PATCH", f"/blocks/{page['id']}/children", token, {"children": rest[i:i + 100]})
    url = page.get("url") or "https://www.notion.so/" + page["id"].replace("-", "")
    if artifact_bytes is not None:
        try:
            media = [b for b in notion.children(token, page["id"]) if b.get("type") == preview["artifact"]["kind"]]
            confirmed = len(media) == 1 and notion.media_is(token, media[0]["id"], artifact_bytes) is True
        except AppError:
            confirmed = False
        if not confirmed:
            raise notion.Unconfirmed("O Notion criou a página, mas o arquivo não foi confirmado. Confira a página antes de repetir.")
    saved = notion.all_children(token, page["id"])
    actual = notion.request("GET", f"/pages/{page['id']}", token)
    if len(saved) != len(body) or notion_source.markdown(saved) != notion_source.markdown(body) or notion._title(actual) != preview["title"]:
        raise notion.Unconfirmed("A página foi criada, mas o conteúdo não foi confirmado. Confira o destino antes de repetir.")
    return {"url": url, "page": page["id"], "message": f"Página “{preview['title']}” criada no Notion.",
            "_snapshot": _notion_snapshot(token, actual), "undo": True}


def with_diagram(action, spec):
    from . import diagram
    diagram.validate(spec)
    preview = pending_preview(action["id"])
    preview["artifact"] = {"diagram": spec, "kind": "image", "file": f"lumen-{action['id']}.png"}
    if preview["kind"] == "obsidian-note":
        root = vault.check(store.load_config()["obsidian_vault"])
        folder = attachments_dir(root, vault.inside(root, preview["path"]).parent)
        preview["artifact"]["dir"] = folder.relative_to(root).as_posix()
        preview["content"] = f'![[{preview["artifact"]["file"]}]]\n\n' + preview["content"]
    preview["warnings"].append("A imagem do diagrama será renderizada e anexada somente depois de confirmar.")
    update_preview(action["id"], preview)
    return {"id": action["id"], **preview}


def _artifact(preview):
    from . import artifacts, diagram
    a = preview["artifact"]
    if a.get("diagram"):
        return diagram.image(a["diagram"], "png")
    path, mime = artifacts.file(a["id"])
    return path.read_bytes(), mime


def _notion_snapshot(token, page):
    """Inclui filhos, propriedades e datas; URLs assinadas mudam mesmo sem edição do arquivo."""
    count = [0]
    def stable(value, signed=False):
        if isinstance(value, list):
            return [stable(v) for v in value]
        if isinstance(value, dict):
            return {k: (v.split("?")[0] if signed and k == "url" and isinstance(v, str) else stable(v, k == "file"))
                    for k, v in value.items() if k not in ("expiry_time", "request_id")}
        return value
    def children(pid, depth=0):
        if depth > 5:
            raise AppError("A página ficou complexa demais para desfazer automaticamente.")
        out = []
        for b in notion.all_children(token, pid):
            count[0] += 1
            if count[0] > 1000:
                raise AppError("A página ficou grande demais para desfazer automaticamente.")
            if b.get("has_children") or b.get(b.get("type"), {}).get("children"):
                b = {**b, "children": children(b["id"], depth + 1)}
            out.append(b)
        return out
    fields = {k: page.get(k) for k in ("id", "parent", "properties", "icon", "cover", "last_edited_time", "in_trash", "is_locked")}
    return _hash(json.dumps(stable([fields, children(page["id"])]), sort_keys=True, ensure_ascii=False).encode())


def undo(aid):
    """Só desfaz uma criação comprovada, intacta e escolhida pelo estudante na tela."""
    with LOCK:
        row = db.one("SELECT * FROM pending_actions WHERE id = ?", aid)
        if not row or row["status"] != "done":
            raise AppError("Esta criação não está disponível para desfazer.")
        result = db.loads(row["result"], {})
        if not result.get("undo"):
            raise AppError("Esta criação antiga não tem comprovante para desfazer com segurança.")
        if row["kind"] == "obsidian-note":
            root = vault.check(store.load_config()["obsidian_vault"])
            if str(root) != result.get("_root"):
                raise AppError("O cofre mudou. Volte ao cofre da criação para desfazer.")
            path = vault.inside(root, result["path"])
            if path != root / result["path"] or not path.is_file() or _hash(path.read_bytes()) != result["_sha256"]:
                raise AppError("A nota mudou ou não está mais no local original. Ela foi preservada.")
            trash = root / ".trash"
            if trash.is_symlink() or trash.resolve() != trash or (trash.exists() and not trash.is_dir()):
                raise AppError("A lixeira do cofre não é uma pasta local segura.")
            trash.mkdir(exist_ok=True)
            dest = trash / f"lumen-{aid}-{path.name}"
            if dest.exists():
                raise AppError("Já existe uma cópia na lixeira. Confira antes de repetir.")
            os.rename(path, dest)
            message = "Nota movida para a lixeira do cofre. Anexos foram preservados para não quebrar outras notas."
        else:
            token = store.get_token()
            if not token:
                raise AppError("O Notion não está conectado.")
            page = notion.request("GET", f"/pages/{result['page']}", token)
            if _notion_snapshot(token, page) != result.get("_snapshot"):
                raise AppError("A página mudou desde a criação. Ela foi preservada.")
            notion.request("PATCH", f"/pages/{result['page']}", token, {"in_trash": True}, once=True)
            if not notion.request("GET", f"/pages/{result['page']}", token).get("in_trash"):
                raise AppError("O Notion não confirmou o envio à lixeira. Confira a página.")
            message = "Página movida para a lixeira do Notion."
        with db.tx() as c:
            c.execute("UPDATE pending_actions SET status = 'undone', decided = ? WHERE id = ?", (db.now(), aid))
        activity.log("desfazer-criacao", tool=row["kind"], target=aid, permission="pedido do estudante", conversation_id=row["conversation_id"])
        return {"ok": True, "id": aid, "message": message}
