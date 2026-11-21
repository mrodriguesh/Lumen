"""Captura oficial do Notion e cópias navegáveis; nunca escreve nas origens."""
import hashlib
import http.client
import ipaddress
import json
import mimetypes
import os
import posixpath
import re
import shutil
import socket
import ssl
import urllib.parse
import unicodedata
from pathlib import Path

from . import AppError, notion
from . import protection as p

KNOWN = {"paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "to_do",
         "toggle", "quote", "callout", "code", "equation", "divider", "table", "table_row", "column", "column_list",
         "image", "file", "pdf", "audio", "video", "bookmark", "embed", "link_preview", "child_page", "child_database",
         "link_to_page", "synced_block", "table_of_contents", "breadcrumb"}


def fetch_file(url, dest, limit=512 * 1024 * 1024):
    """No service credentials; public HTTPS only, DNS pinned for each validated redirect."""
    dest = Path(dest)
    for _ in range(6):
        u = urllib.parse.urlsplit(url)
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None, 443):
            raise AppError("Anexo com endereço não permitido.")
        addresses = socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
            raise AppError("Anexo aponta para uma rede privada ou endereço reservado.")
        conn = http.client.HTTPSConnection(u.hostname, timeout=30)
        raw = socket.create_connection((addresses[0][4][0], 443), timeout=30)
        conn.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=u.hostname)
        try:
            conn.request("GET", urllib.parse.urlunsplit(("", "", u.path or "/", u.query, "")),
                         headers={"User-Agent": "Lumen-Protection/1"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, r.getheader("Location", ""))
                continue
            if r.status != 200:
                raise AppError(f"Anexo indisponível (HTTP {r.status}).")
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp = dest.with_name(dest.name + ".part")
            size = 0
            try:
                with temp.open("wb") as f:
                    while data := r.read(1024 * 1024):
                        size += len(data)
                        if size > limit or shutil.disk_usage(dest.parent).free < len(data) + p.MIN_FREE:
                            raise AppError("Anexo excede o limite de captura ou o espaço livre.", "Limite atual: 512 MB por anexo.")
                        f.write(data)
                if r.getheader("Content-Length") and size != int(r.getheader("Content-Length")):
                    raise AppError("Anexo recebido parcialmente.")
                os.replace(temp, dest)
            finally:
                temp.unlink(missing_ok=True)
            return p.digest(dest)
        finally:
            conn.close()
    raise AppError("Anexo com redirecionamentos excessivos.")


def text(rich):
    return "".join(t.get("plain_text") or t.get("text", {}).get("content", "") or
                   t.get("equation", {}).get("expression", "") for t in rich or [])


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items() if k not in
                ("created_time", "last_edited_time", "created_by", "last_edited_by", "request_id", "expiry_time")}
    if isinstance(value, list):
        return [canonical(x) for x in value]
    if isinstance(value, str) and value.startswith("https://"):
        u = urllib.parse.urlsplit(value)
        if "amazonaws.com" in (u.hostname or "") or "notion" in (u.hostname or ""):
            return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))
    return value


def hash_json(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def pages(token, path, body=None):
    cursor = None
    while True:
        if body is None:
            q = urllib.parse.urlencode({"page_size": 100, **({"start_cursor": cursor} if cursor else {})})
            result = notion.request("GET", path + ("&" if "?" in path else "?") + q, token)
        else:
            result = notion.request("POST", path, token, {**body, "page_size": 100, **({"start_cursor": cursor} if cursor else {})})
        yield from result.get("results", [result] if result.get("object") == "property_item" else [])
        if not result.get("has_more"):
            return
        next_cursor = result.get("next_cursor")
        if not next_cursor or next_cursor == cursor:
            raise AppError("Paginação incompleta no Notion.")
        cursor = next_cursor


def tree(token, pid):
    blocks = notion.all_children(token, pid)
    for b in blocks:
        if b.get("has_children") and b["type"] not in ("child_page", "child_database"):
            b["children"] = tree(token, b["id"])
    return blocks


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def attachments(raw, folder, old=None):
    found, pending = {}, []
    for obj in walk(raw):
        if obj.get("type") not in ("file", "external"):
            continue
        url = obj.get(obj["type"], {}).get("url")
        if not url or url in found:
            continue
        canonical_url = canonical(url)
        name = hashlib.sha256(canonical_url.encode()).hexdigest()[:32]
        suffix = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).suffix[:12]
        suffix = suffix if re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", suffix) else ".bin"
        rel = "attachments/" + name + suffix
        try:
            if obj["type"] != "external" and old and old.get(canonical_url, {}).get("sha256") and (folder / rel).exists():
                sha = p.digest(folder / rel)
                if sha != old[canonical_url]["sha256"]:
                    sha = fetch_file(url, folder / rel)
            else:
                sha = fetch_file(url, folder / rel)
            found[canonical_url] = {"path": rel, "sha256": sha}
        except (OSError, AppError, ValueError):
            pending.append("Anexo não capturado: " + name)
    return found, pending


def markdown(raw, media):
    lines = []
    for b in raw.get("blocks", []):
        kind = b["type"]
        data = b.get(kind, {})
        rich = data.get("rich_text") or data.get("caption") or []
        parts = []
        for rt in rich:
            value = text([rt])
            link = rt.get("href") or (rt.get("text", {}).get("link") or {}).get("url")
            mention = rt.get("mention", {})
            if mention.get("type") == "page":
                link = mention["page"]["id"] + ".md"
            elif link and (urllib.parse.urlsplit(link).hostname or "").endswith(("notion.so", "notion.site")):
                try:
                    link = notion.page_id(link) + ".md"
                except AppError:
                    pass
            parts.append(f"[{value}]({link})" if link else value)
        value = "".join(parts)
        if kind.startswith("heading_"):
            value = "#" * int(kind[-1]) + " " + value
        elif kind in ("bulleted_list_item", "numbered_list_item"):
            value = "- " + value
        elif kind == "to_do":
            value = ("- [x] " if data.get("checked") else "- [ ] ") + value
        elif kind == "code":
            value = "```" + data.get("language", "") + "\n" + value + "\n```"
        elif kind in ("child_page", "child_database"):
            value = f'[{data.get("title", "Página")}]({b["id"]}.md)'
        elif kind == "link_to_page":
            pid = data.get(data.get("type"))
            value = f"[Página relacionada]({pid}.md)"
        elif kind == "table_row":
            value = " | ".join(text(cell) for cell in data.get("cells", []))
        elif kind == "equation":
            value = "$$\n" + data.get("expression", "") + "\n$$"
        elif kind == "divider":
            value = "---"
        for obj in walk(data):
            url = obj.get(obj.get("type"), {}).get("url") if obj.get("type") in ("file", "external") else None
            if url and canonical(url) in media:
                local = media[canonical(url)]["path"]
                value += f'\n{"!" if kind == "image" else ""}[Anexo]({local})'
        if not value and kind not in ("column", "column_list", "table"):
            value = f"[{kind}: consulte os dados estruturados desta página.]"
        lines.append(value)
        if b.get("children"):
            lines.append(markdown({"blocks": b["children"]}, media))
    return "\n\n".join(lines)


def capture(token, roots, folder, previous=None, discover=True):
    folder = Path(folder)
    previous = previous or {}
    m = {"source": "notion", "started": p.now(), "items": {}, "pending": [], "excluded": [], "roots": roots,
         "coverage": "Authorized roots and search discovery; search is not exhaustive", "consistency": "per item read/recheck"}
    owned = p.read(p.HOME / "notion-mirror.json")
    excluded_ids = {x.get("id") for x in owned.values() if isinstance(x, dict)} - {None}
    queue = [("unknown", notion.page_id(x)) for x in roots]
    if discover:
        try:
            queue.extend((x["object"], x["id"]) for x in pages(token, "/search", {"sort": {"direction": "descending", "timestamp": "last_edited_time"}}))
        except AppError:
            m["pending"].append("Descoberta indisponível; raízes conhecidas continuam sendo capturadas.")
    seen = set()
    while queue:
        kind, iid = queue.pop(0)
        if iid in seen or iid in excluded_ids:
            continue
        seen.add(iid)
        p.report_work("reading", done=len(seen), unit="pages")
        old = previous.get("items", {}).get(iid, {})
        try:
            if kind == "unknown":
                for candidate in ("pages", "databases", "data_sources"):
                    try:
                        obj = notion.request("GET", f"/{candidate}/{iid}", token)
                        kind = obj["object"]
                        break
                    except AppError as e:
                        if getattr(e, "status", None) not in (400, 404):
                            raise
                else:
                    raise AppError("Raiz sem acesso.")
            else:
                endpoint = {"page": "pages", "database": "databases", "data_source": "data_sources"}[kind]
                obj = notion.request("GET", f"/{endpoint}/{iid}", token)
            parent = obj.get("parent", {})
            if parent.get(parent.get("type")) in excluded_ids:
                excluded_ids.add(iid)
                m["excluded"].append(iid)
                continue
            if obj.get("in_trash") or obj.get("archived"):
                m["pending"].append(iid + ": exclusão na origem; última captura preservada.")
                if old:
                    m["items"][iid] = {**old, "deleted": True}
                continue
            raw_path = folder / (iid + ".json")
            cached = p.read(raw_path) if old and raw_path.exists() else {}
            external_files = any(x.get("type") == "external" and x.get("external", {}).get("url") for x in walk(cached))
            cached_ok = cached and all(p.target(folder, name).is_file() and p.digest(p.target(folder, name)) == sha for name, sha in old.get("files", {}).items())
            if kind == "page" and cached_ok and canonical(cached.get("object")) == canonical(obj) and old.get("edited") == obj.get("last_edited_time") and not old.get("pending") and not external_files:
                raw = cached
            else:
                raw = {"object": obj, "blocks": [], "properties": {}}
                if kind == "page":
                    for attempt in range(2):
                        raw["blocks"] = [b for b in tree(token, iid) if b["id"] not in excluded_ids]
                        after = notion.request("GET", f"/pages/{iid}", token)
                        if obj.get("last_edited_time") == after.get("last_edited_time"):
                            break
                        obj = after
                        raw["object"] = obj
                    else:
                        raise AppError("Página mudou durante a captura.")
                    for key, prop in obj.get("properties", {}).items():
                        if prop.get("type") in ("relation", "rich_text", "title", "people", "rollup"):
                            pid = urllib.parse.quote(prop["id"], safe="")
                            raw["properties"][key] = list(pages(token, f"/pages/{iid}/properties/{pid}"))
                media, pending = attachments(raw, folder, old.get("attachments"))
                unknown = sorted({x["type"] for x in walk(raw["blocks"]) if x.get("object") == "block" and x.get("type") not in KNOWN})
                pending.extend("Bloco sem representação legível: " + x for x in unknown)
                if any("lumen-protection-origin: " in text(b.get(b.get("type"), {}).get("rich_text")) for b in raw["blocks"]):
                    excluded_ids.add(iid)
                    m["excluded"].append(iid)
                    continue
                p.write(raw_path, raw)
                title = notion._title(obj) if kind == "page" else text(obj.get("title")) or kind
                md = "---\nlumen-protection-origin: notion\nlumen-protection-id: " + iid + "\n---\n\n# " + title + "\n\n"
                md += "Origem: Notion · Captura: " + p.now() + "\n\n" + markdown(raw, media)
                (folder / (iid + ".md")).write_text(md, "utf-8")
                files = {iid + ".json": p.digest(raw_path), iid + ".md": p.digest(folder / (iid + ".md"))}
                files.update({x["path"]: x["sha256"] for x in media.values()})
                old = {"id": iid, "title": title, "kind": kind, "parent": obj.get("parent", {}), "edited": obj.get("last_edited_time"),
                       "captured": p.now(), "sha256": hash_json({"raw":raw, "attachments":media}), "files": files, "attachments": media, "pending": pending}
            m["items"][iid] = old
            m["pending"].extend(iid + ": " + x for x in old.get("pending", []))
            for b in walk(raw.get("blocks", [])):
                if b.get("type") in ("child_page", "child_database"):
                    queue.append(("page" if b["type"] == "child_page" else "database", b["id"]))
            if kind == "database":
                queue.extend(("data_source", d["id"]) for d in obj.get("data_sources", []))
            elif kind == "data_source":
                queue.extend(("page", x["id"]) for x in pages(token, f"/data_sources/{iid}/query", {}))
        except (AppError, OSError, KeyError, ValueError) as e:
            m["pending"].append(iid + ": " + (str(e) if isinstance(e, AppError) else type(e).__name__))
            if old:
                m["items"][iid] = {**old, "stale": True}
    for iid, item in previous.get("items", {}).items():
        if iid not in m["items"] and iid not in excluded_ids:
            m["items"][iid] = {**item, "stale": True}
            m["pending"].append(iid + ": ausente da leitura; última captura preservada, sem inferir exclusão.")
    m["finished"] = p.now()
    return m


def vault_layout(manifest, folder):
    """The readable copy follows parents; original capture paths stay unchanged."""
    items = manifest["items"]
    block_owners = {}
    for iid, item in items.items():
        raw = p.read(p.target(folder, iid + ".json")) if iid + ".json" in item["files"] else {}
        for block in walk(raw.get("blocks", [])):
            if block.get("object") == "block" and block.get("id"):
                block_owners[block["id"]] = iid
    parents = {}
    for iid, item in items.items():
        parent = item.get("parent", {})
        kind = parent.get("type")
        pid = parent.get(kind) if kind else None
        if kind == "block_id":
            pid = block_owners.get(pid)
        parents[iid] = pid if isinstance(pid, str) and pid in items else (
            None if kind in (None, "workspace") else "missing")

    names, used = {}, {}
    for iid, item in sorted(items.items()):
        title = unicodedata.normalize("NFC", item.get("title") or iid)
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title).strip(" .")[:70].rstrip(" .") or "Sem título"
        if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", stem):
            stem = "_" + stem
        siblings = used.setdefault(parents[iid], set())
        name = stem
        if name.casefold() in siblings or (name + ".md").casefold() in siblings:
            name += " ~" + hashlib.sha256(iid.encode()).hexdigest()[:12]
        siblings.update((name.casefold(), (name + ".md").casefold()))
        names[iid] = name
    paths, incomplete = {}, []
    for iid in items:
        chain, current = [], iid
        while current in items and current not in chain:
            chain.append(current)
            current = parents[current]
        if current is not None:
            incomplete.append(iid)
            # Keep the page accessible when an ancestor is unavailable or cyclic.
            branch = "/".join(names[x] for x in reversed(chain)) if current == "missing" else (
                names[iid] + " ~" + hashlib.sha256(iid.encode()).hexdigest()[:12])
            paths[iid] = "Estrutura a conferir/" + branch + ".md"
        else:
            paths[iid] = "Particular/" + "/".join(names[x] for x in reversed(chain)) + ".md"
    return paths, incomplete


def mirror_markdown(data, rel, paths):
    def link(match):
        original = match[1]
        name = urllib.parse.unquote(original)
        if name.endswith(".md") and name[:-3] in paths:
            target = paths[name[:-3]]
        elif name.startswith("attachments/"):
            target = "Anexos/" + name[len("attachments/"):]
        else:
            return match[0]
        relative = posixpath.relpath(target, posixpath.dirname(rel))
        return "](" + urllib.parse.quote(relative, safe="/.-_~") + ")"
    return re.sub(r"\]\(([^)\n]+)\)", link, data.decode("utf-8")).encode("utf-8")


class CaptureChanged(AppError):
    """The capture folder no longer matches its manifest (a reading was interrupted mid-way)."""


def mirror_to_vault(vault, manifest, capture_folder=None):
    vault = Path(vault).resolve(strict=True)
    source = Path(capture_folder or p.HOME / "capture" / "notion")
    # Checked before any write: an interrupted reading must not leave a half-updated copy.
    for item in manifest["items"].values():
        for rel, sha in item["files"].items():
            if p.digest(p.target(source, rel)) != sha:
                raise CaptureChanged("Um arquivo da captura do Notion não passou na conferência.")
    owner = p.configuration()["set_id"]
    candidates = []
    for directory, dirs, files in os.walk(vault, followlinks=False):
        dirs[:] = [x for x in dirs if not p.redirected(Path(directory) / x)]
        if p.MARKER in files:
            mark = p.read(Path(directory) / p.MARKER)
            if mark.get("kind") == "notion-mirror" and mark.get("owner") == owner:
                candidates.append(Path(directory))
    if len(candidates) > 1:
        raise AppError("Há duas áreas com a mesma identidade de cópia.", "Preserve ambas e escolha qual manter antes de retomar.")
    dest = candidates[0] if candidates else vault / "Lumen - Backup do Notion"
    if dest.exists() and not candidates:
        raise AppError("A pasta da cópia do Notion já existe sem identificação.", "Preserve-a; escolha outra área antes de retomar.")
    dest.mkdir(exist_ok=True)
    mark = p.read(dest / p.MARKER)
    mark.update(owner=owner, kind="notion-mirror")
    p.write(dest / p.MARKER, mark)
    previous = mark.setdefault("files", {})
    # A run stopped between a write and the final receipt left these; a file still matching one is our own write.
    for rel, sha in mark.pop("writing", {}).items():
        if p.target(dest, rel).is_file() and p.digest(p.target(dest, rel)) == sha:
            previous[rel] = sha
    paths, incomplete = vault_layout(manifest, source)
    old_pages = mark.setdefault("pages", {})
    edited_pages = {}
    for iid in manifest["items"]:
        old_rel = old_pages.get(iid, iid + ".md")
        old_out = p.target(dest, old_rel)
        if old_rel in previous and old_out.is_file() and p.digest(old_out) != previous[old_rel]:
            captured = p.target(source, iid + ".md")
            expected = manifest["items"][iid]["files"].get(iid + ".md")
            # A crash can leave the new bytes on disk before the receipt. Exact comparison only.
            if expected and captured.is_file() and p.digest(captured) == expected and old_out.read_bytes() == mirror_markdown(captured.read_bytes(), old_rel, paths):
                continue
            edited_pages[iid] = old_rel
            paths[iid] = old_rel
    desired = set()
    conflicts, confirmed = [], []
    for iid, item in manifest["items"].items():
        ok = True
        old_md = old_pages.get(iid, iid + ".md")
        edited = iid in edited_pages
        for rel, sha in item["files"].items():
            src = p.target(source, rel)
            if rel == iid + ".md":
                new_rel = paths[iid]
                data = mirror_markdown(src.read_bytes(), new_rel, paths)
            else:
                new_rel = "Anexos/" + rel[len("attachments/"):] if rel.startswith("attachments/") else "Dados originais/" + rel
                data = None
            desired.add(new_rel)
            out = p.target(dest, new_rel)
            expected = hashlib.sha256(data).hexdigest() if data is not None else sha
            if (rel == iid + ".md" and edited) or (out.exists() and p.digest(out) not in (expected, previous.get(new_rel))):
                kept = old_md if rel == iid + ".md" and edited else new_rel  # an attachment keeps its own path
                conflicts.append(kept)
                desired.add(kept)
                ok = False
                continue
            if not out.exists() or p.digest(out) != expected:
                mark.setdefault("writing", {})[new_rel] = expected
                p.write(dest / p.MARKER, mark)  # intent first, so a stop mid-run is not mistaken for a user edit
                if data is None:
                    p.stable_copy(src, out)
                else:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    temp = out.with_name(out.name + ".lumen-part")
                    try:
                        temp.write_bytes(data)
                        if p.digest(temp) != expected:
                            raise AppError("Não foi possível conferir a cópia legível do Notion.")
                        os.replace(temp, out)
                    finally:
                        temp.unlink(missing_ok=True)
            previous[new_rel] = expected
            if rel == iid + ".md":
                old_pages[iid] = new_rel
        if ok:
            confirmed.append(iid)
    mark.pop("writing", None)  # every finished write is now in previous
    mark["layout"] = "notion-hierarchy-1"
    # Save new receipts before removing only unchanged files owned by the old layout.
    p.write(dest / p.MARKER, mark)
    for rel in list(previous):
        if rel in desired:
            continue
        old = p.target(dest, rel)
        if old.is_file() and p.digest(old) != previous[rel]:
            conflicts.append(rel)
            continue
        old.unlink(missing_ok=True)
        del previous[rel]
        parent = old.parent
        while parent != dest:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    p.write(dest / p.MARKER, mark)
    p.status_of("notion_obsidian", status="conflict" if conflicts else "confirmed", confirmed=p.now(),
                path=str(dest), layout=mark["layout"], items=len(confirmed), conflicts=conflicts, structure_pending=incomplete,
                message="Diferenças preservadas. Confira as notas antes de reorganizar; a causa ainda precisa ser confirmada." if conflicts else "Cópia legível e anexos conferidos.")
    if (manifest.get("pending") or incomplete) and not conflicts:
        p.status_of("notion_obsidian", status="partial", message="Algumas páginas precisam de acesso ou conferência. Veja também a pasta Estrutura a conferir." if incomplete else "Cópia disponível com pendências na captura do Notion.")


def owned_page(token, parent, key, title, journal, origin="obsidian"):
    entry = journal.setdefault(key, {})
    if entry.get("id"):
        return entry["id"]
    marker = "lumen-protection-origin: " + origin + " · " + p.configuration()["set_id"] + " · " + key
    if entry.get("pending"):
        for b in notion.all_children(token, parent):
            if b["type"] == "child_page":
                children = notion.all_children(token, b["id"])
                if any(marker == text(x.get(x["type"], {}).get("rich_text")) for x in children):
                    entry.update(id=b["id"], pending=False)
                    p.write(p.HOME / "notion-mirror.json", journal)
                    return b["id"]
        raise notion.Unconfirmed("Criação anterior da cópia ainda não confirmada.", "Aguarde e confira novamente; nada foi duplicado.")
    entry["pending"] = True
    p.write(p.HOME / "notion-mirror.json", journal)
    try:
        page = notion.request("POST", "/pages", token, {"parent": {"page_id": parent},
            "properties": {"title": {"title": notion._rt(title[:150])}},
            "children": [notion._b("paragraph", notion._rt(marker))]}, once=True)
    except notion.Unconfirmed:
        raise
    except AppError:
        entry["pending"] = False
        p.write(p.HOME / "notion-mirror.json", journal)
        raise
    entry.update(id=page["id"], pending=False)
    p.write(p.HOME / "notion-mirror.json", journal)
    return page["id"]


def note_blocks(path, item):
    if path.suffix.lower() != ".md":
        return [notion._b("paragraph", notion._rt("Arquivo original: " + item["path"] +
               ". Canvas, Bases e plugins permanecem arquivos; não são recursos nativos do Notion."))]
    raw = path.read_text("utf-8-sig")
    result = []
    code, code_lines = False, []
    for line in raw.splitlines():
        if line.startswith("```"):
            if code:
                result.append(notion._b("code", notion._rt("\n".join(code_lines)), language="plain text"))
                code_lines = []
            code = not code
            continue
        if code:
            code_lines.append(line)
            continue
        kind = "paragraph"
        for prefix, block in (("### ", "heading_3"), ("## ", "heading_2"), ("# ", "heading_1"), ("- ", "bulleted_list_item")):
            if line.startswith(prefix):
                kind, line = block, line[len(prefix):]
                break
        if line:
            result.append(notion._b(kind, notion._rt(line)))
    if code_lines:
        result.append(notion._b("code", notion._rt("\n".join(code_lines)), language="plain text"))
    if len(result) > 1000 or len(raw.encode()) > 400000:
        return [notion._b("paragraph", notion._rt("Nota extensa: consulte o arquivo original anexado e o backup recuperável."))]
    return result


def mirror_to_notion(token, parent, manifest, capture_folder=None):
    journal = p.read(p.HOME / "notion-mirror.json")
    root = owned_page(token, parent, "root", "Backup do Obsidian", journal)
    pending, confirmed = (["A captura original tem pendências; consulte a cobertura."] if manifest.get("pending") else []), []
    for rel, item in manifest["items"].items():
        if rel.startswith(".obsidian/") or item.get("stale"):
            continue  # settings/plugins are preserved in the encrypted backup, never executed or published as notes.
        try:
            directory = root
            for depth in range(1, len(Path(rel).parts)):
                name = "/".join(Path(rel).parts[:depth])
                directory = owned_page(token, directory, "dir-" + hashlib.sha256(name.encode()).hexdigest(), Path(name).name, journal)
            key = "item-" + item["id"]
            pid = owned_page(token, directory, key, Path(rel).name, journal)
            entry = journal[key]
            current = tree(token, pid)
            page_title = notion._title(notion.request("GET", f"/pages/{pid}", token))
            if entry.get("title") and page_title != entry["title"]:
                pending.append(rel + ": título editado na cópia; edição preservada.")
                continue
            if entry.get("hash") and hash_json(current) != entry["hash"] and not entry.get("sending"):
                pending.append(rel + ": diferença preservada; compare as versões antes de retomar.")
                continue
            if entry.get("source_hash") == item["sha256"] and not entry.get("sending"):
                confirmed.append(key)
                if entry.get("limitation"):
                    pending.append(rel + ": " + entry["limitation"])
                continue
            path = Path(capture_folder or p.HOME / "capture" / "obsidian") / "files" / rel
            if p.digest(path) != item["sha256"]:
                raise AppError("Arquivo mudou desde a captura; aguardando a próxima versão estável.")
            if not entry.get("sending"):
                blocks = [notion._b("paragraph", notion._rt("Origem: Obsidian · " + rel + " · " + item["captured"]))]
                blocks.extend(note_blocks(path, item))
                limitation = None
                if path.stat().st_size <= 5 * 1024 * 1024:
                    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    filename = "original" + path.suffix
                    if path.suffix in (".canvas", ".base"):
                        mime, filename = "application/json", filename + ".json"
                    try:
                        raw = path.read_bytes()
                        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                            raise AppError("Arquivo mudou durante a leitura da cópia.")
                        upload = notion.upload_image(token, raw, filename, mime)
                        kind = "image" if mime.startswith("image/") else "pdf" if mime == "application/pdf" else "file"
                        blocks.append({"object": "block", "type": kind, kind: {"type": "file_upload", "file_upload": {"id": upload}}})
                    except AppError as e:
                        if getattr(e, "status", None) != 400:
                            raise
                        limitation = "A API não aceita este anexo; o original está preservado nos snapshots local e Drive."
                        blocks.append(notion._b("paragraph", notion._rt(limitation)))
                else:
                    limitation = "Anexo acima de 5 MB: bytes preservados no backup; cópia Notion parcial."
                    blocks.append(notion._b("paragraph", notion._rt(limitation)))
                old_ids = entry.get("content_ids", [x["id"] for x in current[1:]] if entry.get("hash") else [])
                entry["sending"] = {"blocks": blocks, "old": old_ids,
                                    "old_hashes": {x["id"]: hash_json(x) for x in current if x["id"] in old_ids},
                                    "source_hash": item["sha256"], "journal": {}, "limitation": limitation}
                p.write(p.HOME / "notion-mirror.json", journal)
            sending = entry["sending"]
            def save(j):
                sending["journal"] = j
                p.write(p.HOME / "notion-mirror.json", journal)
            _, _, added = notion.publish(token, pid, Path(rel).name, sending["blocks"], lambda: None,
                                         journal=sending["journal"], save=save)
            persisted = tree(token, pid)
            actual = [x for x in persisted if x["id"] in added]
            expected = [notion._b("heading_1", notion._rt(Path(rel).name)), *sending["blocks"]]
            if not notion._matches(expected, actual):
                raise AppError("Os blocos da cópia não correspondem ao envio.")
            for b in actual:
                if b["type"] in ("file", "image", "pdf"):
                    url = b[b["type"]].get("file", {}).get("url")
                    with __import__("tempfile").TemporaryDirectory(dir=p.HOME) as temp:
                        if fetch_file(url, Path(temp) / "attachment") != sending["source_hash"]:
                            raise AppError("Anexo do Notion não passou na comparação de bytes.")
            # Delete only previously owned blocks, after confirming the replacement on the server.
            old_current = {x["id"]: x for x in tree(token, pid) if x["id"] in sending["old"]}
            if any(hash_json(x) != sending.get("old_hashes", {}).get(bid) for bid, x in old_current.items()):
                raise AppError("Uma edição foi feita durante a atualização da cópia.", "Os blocos anteriores e os novos foram preservados para conferência.")
            for bid in sending["old"]:
                if bid in old_current:
                    notion.request("DELETE", f"/blocks/{bid}", token)
            entry.update(source_hash=sending["source_hash"], hash=hash_json(tree(token, pid)), confirmed=p.now(),
                         limitation=sending["limitation"], title=page_title, content_ids=added)
            del entry["sending"]
            p.write(p.HOME / "notion-mirror.json", journal)
            confirmed.append(key)
            if entry.get("limitation"):
                pending.append(rel + ": " + entry["limitation"])
        except (AppError, OSError, UnicodeError) as e:
            pending.append(rel + ": " + (str(e) if isinstance(e, AppError) else type(e).__name__))
    p.status_of("obsidian_notion", status="partial" if pending else "confirmed", confirmed=p.now(), items=len(confirmed),
                pending=pending, url="https://www.notion.so/" + root.replace("-", ""))


def append_recovery(token, parent, blocks, ops, save, uploads, prefix="root"):
    """Append supported blocks in separate nesting levels, with the existing uncertain-write reconciler."""
    bot = notion.request("GET", "/users/me", token)["id"]
    plain = []
    for block in blocks:
        b = json.loads(json.dumps(block))
        if b["type"] not in ("table", "column_list", "column"):
            b[b["type"]].pop("children", None)
        plain.append(b)
    offset = 0
    for index, batch in enumerate(notion.batches(plain)):
        key = prefix + "/" + str(index)
        op = ops.get(key)
        body = {"children": batch}
        if op is None:
            op = {"method": "PATCH", "path": f"/blocks/{parent}/children", "parent": parent,
                  "body": body, "before": [b["id"] for b in notion.all_children(token, parent)], "state": "new"}
            ops[key] = op
        if op["body"] != body:
            raise AppError("A recuperação pendente mudou de conteúdo.", "Retome a mesma captura.")
        if op["state"] == "pending":
            op["response"] = notion._recover_call(token, op, bot)
            op["state"] = "done"
            save()
        if op["state"] != "done":
            op["state"] = "pending"
            save()
            try:
                response = notion.request("PATCH", op["path"], token, body)
            except notion.Unconfirmed:
                raise
            except AppError:
                op["state"] = "new"
                save()
                raise
            op.update(state="done", response={"results": [{"id": b["id"]} for b in response["results"]]})
            save()
        ids = [b["id"] for b in op["response"]["results"]]
        actual = [b for b in notion.all_children(token, parent) if b["id"] in ids]
        if not notion._matches(batch, actual):
            raise AppError("A recuperação no Notion não corresponde aos blocos enviados.")
        for j, (wanted, got) in enumerate(zip(batch, actual)):
            data = wanted[wanted["type"]]
            if data.get("type") == "file_upload":
                sha = uploads[data["file_upload"]["id"]]
                with __import__("tempfile").TemporaryDirectory(dir=p.HOME) as temp:
                    if fetch_file(got[got["type"]]["file"]["url"], Path(temp) / "file") != sha:
                        raise AppError("Anexo recriado no Notion não corresponde ao backup.")
            children = blocks[offset+j][wanted["type"]].get("children", [])
            if children and wanted["type"] not in ("table", "column_list", "column"):
                append_recovery(token, got["id"], children, ops, save, uploads, key + "/" + str(j))
        offset += len(batch)


def rebuild(token, folder, parent):
    """Reconstruct supported content into a NEW area; retain raw data/offline files as the fidelity reference."""
    folder = Path(folder).resolve(strict=True)
    m = p.read(folder / "notion" / "manifest.json")
    if m.get("source") != "notion":
        raise AppError("Escolha a pasta de uma recuperação que contenha a origem Notion.")
    p.verify_restored(folder)
    base = folder / "notion"
    journal = p.read(p.HOME / "notion-mirror.json")
    run = "recovery-" + hashlib.sha256(str(folder).encode()).hexdigest()[:24]
    root = owned_page(token, parent, run, "Recuperação do Notion · " + p.now()[:10], journal, "recovery")
    def save():
        p.write(p.HOME / "notion-mirror.json", journal)
    mapping = {}
    for iid, item in m["items"].items():
        original_parent = item.get("parent", {})
        parent_id = mapping.get(original_parent.get(original_parent.get("type")), root)
        mapping[iid] = owned_page(token, parent_id, run + "-" + iid, item.get("title", iid), journal, "recovery")
    pending, done = [], []
    for iid, item in m["items"].items():
        entry = journal[run + "-" + iid]
        if entry.get("rebuilt"):
            done.append(iid)
            pending.extend(entry.get("limitations", []))
            continue
        limits = []
        if item.get("kind") != "page":
            limits.append(iid + ": esquema e propriedades de base preservados no JSON; esta recuperação cria páginas de consulta.")
        raw = p.read(p.target(base, iid + ".json"))
        uploads = entry.setdefault("uploads", {})
        def rich(values):
            result = []
            for rt in values or []:
                if rt.get("type") == "equation":
                    result.append({"type":"equation","equation":rt["equation"]})
                else:
                    link = rt.get("href") or (rt.get("text", {}).get("link") or {}).get("url")
                    mention = rt.get("mention", {})
                    mid = mention.get("page", {}).get("id")
                    if mid in mapping:
                        link = "https://www.notion.so/" + mapping[mid].replace("-", "")
                    converted = notion._rt(text([rt]), link=link)
                    for part in converted:
                        if rt.get("annotations"):
                            part["annotations"] = rt["annotations"]
                    result.extend(converted)
            return result
        def convert(blocks):
            result = []
            for b in blocks:
                kind = b["type"]
                data = b.get(kind, {})
                if kind in ("child_page", "child_database"):
                    if b["id"] in mapping:
                        result.append({"object":"block","type":"link_to_page","link_to_page":{"type":"page_id","page_id":mapping[b["id"]]}})
                    continue
                if kind in ("synced_block", "unsupported", "link_preview") or kind not in KNOWN:
                    limits.append(iid + ": bloco " + kind + " disponível no JSON original.")
                    result.append(notion._b("paragraph", notion._rt("Bloco " + kind + ": consulte a captura estruturada offline.")))
                    continue
                d = {k: v for k, v in data.items() if k in ("color","checked","language","is_toggleable","table_width","has_column_header","has_row_header","expression","url")}
                if "rich_text" in data:
                    d["rich_text"] = rich(data["rich_text"])
                if "caption" in data:
                    d["caption"] = rich(data["caption"])
                if "cells" in data:
                    d["cells"] = [rich(cell) for cell in data["cells"]]
                if kind == "callout":
                    icon = data.get("icon", {})
                    if icon.get("type") == "emoji":
                        d["icon"] = icon
                if kind == "link_to_page":
                    old = data.get(data.get("type"))
                    if old in mapping:
                        d = {"type":"page_id", "page_id":mapping[old]}
                    else:
                        result.append(notion._b("paragraph", notion._rt("Referência original: " + str(old))))
                        continue
                if kind in ("image","file","pdf","audio","video"):
                    url = data.get(data.get("type"), {}).get("url")
                    asset = item.get("attachments", {}).get(canonical(url or ""))
                    if not asset or p.target(base, asset["path"]).stat().st_size > 5*1024*1024:
                        limits.append(iid + ": anexo sem envio compatível; consulte o arquivo offline.")
                        result.append(notion._b("paragraph", notion._rt("Anexo preservado na recuperação offline; não recriado nesta página.")))
                        continue
                    local = p.target(base, asset["path"])
                    uid = notion.upload_image(token, local.read_bytes(), "restaurado"+local.suffix, mimetypes.guess_type(local.name)[0] or "application/octet-stream")
                    uploads[uid] = asset["sha256"]
                    d.update(type="file_upload", file_upload={"id":uid})
                if b.get("children"):
                    d["children"] = convert(b["children"])
                result.append({"object":"block","type":kind,kind:d})
            return result
        if not entry.get("prepared"):
            entry["prepared"] = [notion._b("paragraph", notion._rt("Recuperado de captura Notion: " + iid + ". Propriedades e representação completa permanecem no JSON offline.")), *convert(raw.get("blocks", []))]
            entry["limitations"] = limits
            save()
        append_recovery(token, mapping[iid], entry["prepared"], entry.setdefault("ops", {}), save, uploads)
        entry["rebuilt"] = p.now()
        save()
        done.append(iid)
        pending.extend(entry.get("limitations", []))
    result = {"url":"https://www.notion.so/"+root.replace("-", ""), "pages":len(done), "limitations":pending, "at":p.now()}
    p.update(last_notion_recovery=result)
    return result
