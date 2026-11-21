"""Notion pela API oficial, com o token da integração interna já guardado nos Ajustes (store.get_token).

A busca da API (POST /search) só procura em títulos e só enxerga o que foi compartilhado com a integração: ela é usada
aqui para ENUMERAR as páginas acessíveis (paginada, com last_edited_time). O conteúdo vem dos blocos (GET
/blocks/{id}/children, recursivo e paginado), lido só quando a página mudou desde a última sincronização. A busca de
texto e de significado acontece depois, no índice local.

Ficam de fora: páginas na lixeira, as páginas que a Proteção cria no Notion com as notas do Obsidian (notion-mirror.json)
e as filhas delas (indexá-las duplicaria o cofre), e páginas com o bloco-marcador da Proteção."""
from ... import AppError, notion, protection, protection_notion as pn, store
from .. import images, settings
from . import Doc, web

MAX_CHARS = 400_000


def _token():
    token = store.get_token()
    if not token:
        raise AppError("O Notion não está conectado.", "Conecte o Notion em Integrações.")
    return token


def rich(items):
    """Texto de um rich_text, com links em Markdown quando há endereço."""
    out = []
    for t in items or []:
        piece = t.get("plain_text") or t.get("text", {}).get("content", "") or t.get("equation", {}).get("expression", "")
        href = t.get("href") or ((t.get("text") or {}).get("link") or {}).get("url")
        ann = t.get("annotations") or {}
        if piece and ann.get("code"):
            piece = f"`{piece}`"
        elif piece and ann.get("bold"):
            piece = f"**{piece}**"
        if piece and href and str(href).startswith("http"):
            piece = f"[{piece}]({href})"
        out.append(piece)
    return "".join(out)


LISTS = {"bulleted_list_item", "numbered_list_item", "to_do", "toggle"}


def markdown(blocks, depth=0, links=None, picture=None):
    """Blocos do Notion em Markdown, mantendo a hierarquia: filhos de listas e toggles ficam recuados embaixo do item;
    colunas e blocos sincronizados entram no mesmo nível. Mídias viram uma referência (nome/legenda), não o arquivo;
    picture(bloco de imagem) pode trocar a referência pelo que a visão leu (sincronização com imagens ligadas)."""
    links = [] if links is None else links
    out, pad = [], "  " * depth
    for b in blocks or []:
        kind = b.get("type", "")
        v = b.get(kind) or {}
        txt = rich(v.get("rich_text"))
        inner = depth + 1 if kind in LISTS or kind in ("quote", "callout") else depth
        if kind.startswith("heading_") and kind[-1].isdigit():
            out.append("#" * int(kind[-1]) + " " + txt)
        elif kind == "paragraph":
            out.append(pad + txt if txt else "")
        elif kind == "bulleted_list_item":
            out.append(pad + "- " + txt)
        elif kind == "numbered_list_item":
            out.append(pad + "1. " + txt)
        elif kind == "to_do":
            out.append(pad + ("- [x] " if v.get("checked") else "- [ ] ") + txt)
        elif kind == "toggle":
            out.append(pad + "- " + txt)
        elif kind == "quote":
            out.append(pad + "> " + txt)
        elif kind == "callout":
            icon = (v.get("icon") or {}).get("emoji") or ""
            out.append(pad + "> " + (icon + " " if icon else "") + txt)
        elif kind == "code":
            out += [pad + "```" + (v.get("language") or ""), *[pad + line for line in pn.text(v.get("rich_text")).splitlines()], pad + "```"]
        elif kind == "equation":
            out.append(pad + "$$" + (v.get("expression") or "") + "$$")
        elif kind == "divider":
            out.append(pad + "---")
        elif kind == "table":
            rows = [[rich(cell) for cell in (r.get("table_row") or {}).get("cells", [])] for r in b.get("children") or []]
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                out.append(pad + "| " + " | ".join(rows[0]) + " |")
                out.append(pad + "|" + " --- |" * width)
                out += [pad + "| " + " | ".join(r) + " |" for r in rows[1:]]
            continue
        elif kind == "child_page":
            out.append(pad + f"[Subpágina: {v.get('title') or 'sem título'}]")
            links.append(b.get("id", ""))
        elif kind == "child_database":
            out.append(pad + f"[Base de dados: {v.get('title') or 'sem título'}]")
        elif kind == "image" and picture and picture(v):
            out.append(pad + picture(v))
        elif kind in ("image", "file", "pdf", "video", "audio"):
            caption = rich(v.get("caption"))
            name = v.get("name") or (v.get("file") or v.get("external") or {}).get("url", "").split("?")[0].rsplit("/", 1)[-1]
            out.append(pad + f"[{ {'image': 'Imagem', 'pdf': 'PDF', 'video': 'Vídeo', 'audio': 'Áudio'}.get(kind, 'Arquivo') }"
                       + (f": {caption}" if caption else f": {name}" if name else "") + "]")
        elif kind in ("bookmark", "embed", "link_preview"):
            url = v.get("url") or ""
            caption = rich(v.get("caption"))
            out.append(pad + (f"[{caption or url}]({url})" if url.startswith("http") else caption))
        elif kind == "link_to_page":
            target = v.get("page_id") or v.get("database_id") or ""
            out.append(pad + "[Link para outra página]")
            links.append(target)
        elif txt:
            out.append(pad + txt)
        if b.get("children") and kind != "table":
            child = markdown(b["children"], inner, links, picture)
            if child:
                out.append(child)
    return "\n".join(x for x in out if x is not None)


def properties(page):
    """Propriedades de uma página (linhas de uma base): texto curto 'Nome: valor', e as tags (select/multi_select)."""
    lines, tags = [], []
    for name, prop in (page.get("properties") or {}).items():
        kind = prop.get("type")
        v = prop.get(kind)
        if kind == "title" or v in (None, [], ""):
            continue
        if kind in ("rich_text",):
            value = rich(v)
        elif kind == "select" or kind == "status":
            value = (v or {}).get("name", "")
            tags.append(value)
        elif kind == "multi_select":
            value = ", ".join(x.get("name", "") for x in v)
            tags += [x.get("name", "") for x in v]
        elif kind == "date":
            value = (v or {}).get("start", "") + (" → " + v["end"] if (v or {}).get("end") else "")
        elif kind in ("number", "checkbox", "url", "email", "phone_number"):
            value = str(v)
        else:
            continue
        if value:
            lines.append(f"{name}: {value}")
    return lines, [t for t in tags if t]


class Notion:
    name, label = "notion", "Notion"

    def status(self):
        if not store.get_token():
            return {"connected": False, "message": "Conecte o Notion em Integrações (token da integração interna)."}
        return {"connected": True, "message": ""}

    def test(self):
        token = _token()
        me = notion.request("GET", "/users/me", token)
        total = sum(1 for _ in self._search(token, lambda: None))
        bot = (me.get("name") or "integração")
        return {"connected": True, "message": f"Conectado como “{bot}”: {total} páginas compartilhadas com a integração."}

    def _excluded(self):
        journal = protection.read(protection.HOME / "notion-mirror.json") if (protection.HOME / "notion-mirror.json").is_file() else {}
        return {notion.page_id(v["id"]) for v in journal.values() if isinstance(v, dict) and v.get("id")}

    def _search(self, token, check):
        for page in pn.pages(token, "/search", {"filter": {"property": "object", "value": "page"},
                                                "sort": {"direction": "descending", "timestamp": "last_edited_time"}}):
            check()
            if page.get("object") != "page" or page.get("in_trash") or page.get("archived"):
                continue
            yield page

    def versions(self, check):
        token = _token()
        notion.backup_rate_enabled = True  # 0,4 s entre pedidos, o mesmo ritmo do backup (os dois dividem o limite)
        excluded, found = self._excluded(), {}
        for page in self._search(token, check):
            found[notion.page_id(page["id"])] = page
        # As filhas de uma página excluída também ficam de fora (uma passada por nível, até não mudar).
        changed = True
        while changed:
            changed = False
            for pid, page in found.items():
                parent = page.get("parent") or {}
                if pid not in excluded and notion.page_id(parent.get("page_id") or "0" * 32) in excluded:
                    excluded.add(pid)
                    changed = True
        return {pid: (page.get("last_edited_time", ""), {"page": page}) for pid, page in found.items() if pid not in excluded}

    def load(self, source_id, info, check):
        token = _token()
        page = info.get("page") or notion.request("GET", f"/pages/{source_id}", token)
        blocks = pn.tree(token, source_id)
        check()
        for b in blocks:  # o marcador da Proteção é sempre um bloco do nível de cima (ícones e menções têm "type" de texto)
            v = b.get(b.get("type") or "") if isinstance(b, dict) else None
            if isinstance(v, dict) and "lumen-protection-origin: " in pn.text(v.get("rich_text")):
                return None  # página criada pela Proteção (cópia de uma nota do Obsidian)
        links, pics = [], {}
        props, tags = properties(page)
        body = markdown(blocks, 0, links, (lambda v: self._picture(v, pics, check)) if settings.load()["search"]["images"] else None)
        text = ("\n".join(props) + "\n\n" if props else "") + body
        parent = page.get("parent") or {}
        return Doc(source="notion", source_id=source_id, title=notion._title(page), text=text[:MAX_CHARS],
                   url=page.get("url") or "https://www.notion.so/" + source_id.replace("-", ""),
                   kind="row" if parent.get("type") in ("database_id", "data_source_id") else "page",
                   tags=tags[:40], links=[x for x in links if x][:200], updated=page.get("last_edited_time", ""),
                   meta={"parent_type": parent.get("type", ""),
                         "parent_id": notion.page_id(parent["page_id"]) if parent.get("type") == "page_id" else "",
                         **({"images": [{"hash": x["hash"], "name": x["name"]} for x in pics.values()]} if pics else {})})

    @staticmethod
    def _picture(v, pics, check):
        """Imagem enviada ao Notion: baixada agora (o endereço expira em cerca de 1 h) e trocada pelo que a visão leu.
        Uma por bloco (o resultado fica em pics, porque markdown pergunta duas vezes); imagens de outros sites ficam
        como referência. None = sem imagem."""
        url = (v.get("file") or {}).get("url") or ""
        if url in pics:
            return pics[url]["text"]
        if v.get("type") != "file" or not url.startswith("https://") or len(pics) >= images.PER_DOC:
            return None
        name = rich(v.get("caption")) or url.split("?")[0].rsplit("/", 1)[-1] or "imagem"
        try:
            check()
            status, _, data, _ = web._get(url, check, limit=images.MAX_BYTES)
        except AppError:
            return None
        h = images.register(data, name[:120], "notion") if status == 200 else None
        if not h:
            return None
        pics[url] = {"hash": h, "name": name[:120], "text": images.inline(h, name[:120])}
        return pics[url]["text"]

    def read(self, source_id):
        token = _token()
        return markdown(pn.tree(token, notion.page_id(source_id)))

    def open(self, doc):
        import webbrowser
        url = "https://www.notion.so/" + notion.page_id(doc["source_id"]).replace("-", "")
        webbrowser.open(url)
        return {"notice": "Página aberta no Notion."}

    def uri(self, doc):
        return "https://www.notion.so/" + notion.page_id(doc["source_id"]).replace("-", "")
