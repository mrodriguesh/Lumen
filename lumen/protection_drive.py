"""Transporte binário retomável, objetos imutáveis e catálogo publicado por último."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import AppError, gdrive
from . import protection as p

FIELDS = "id,name,size,md5Checksum,sha256Checksum,trashed,parents,webViewLink"
CHUNK = 4 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(method, url, body=None, headers=None):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname != "www.googleapis.com" or u.username or u.password:
        raise AppError("Endereço de transferência do Drive inválido.")
    for attempt in range(3):
        req = urllib.request.Request(url, body, method=method,
                                     headers={"Authorization": "Bearer " + gdrive._token(), **(headers or {})})
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=45) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            if e.code in (308, 404, 410, 409):
                return e.code, dict(e.headers), e.read()
            if e.code == 401 and attempt == 0:
                gdrive._access.update(token=None, until=0)
                continue
            if e.code == 429 or e.code >= 500:
                delay = gdrive._after(e, attempt)
                e.close()
                time.sleep(delay)
                # Never repeat an uncertain create/chunk; the caller probes its session/ID on the next cycle.
                raise AppError("O Drive pediu uma nova tentativa.", "O envio será reconciliado e retomado.") from None
            raise gdrive._error(e.code, gdrive._reason(e)) from None
        except (urllib.error.URLError, OSError):
            raise AppError("Transferência interrompida.", "Os bytes recebidos serão consultados antes da retomada.") from None
    raise AppError("Reconecte o Google Drive.")


def metadata(fid):
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,200}", fid):
        raise AppError("Identificador do Drive inválido.")
    try:
        return gdrive._call("GET", f"{gdrive.API}/files/{fid}?fields={FIELDS}")
    except gdrive.NotFound:
        return None


def reserve(entry, save):
    if not entry.get("id"):
        entry["id"] = gdrive._call("GET", gdrive.API + "/files/generateIds?count=1&space=drive&type=files")["ids"][0]
        save()
    return entry["id"]


def folder(journal, save):
    entry = journal.setdefault("folder", {})
    fid = reserve(entry, save)
    current = metadata(fid)
    if current:
        if current.get("trashed"):
            raise AppError("A pasta de backup está na lixeira do Drive.", "Restaure a pasta no Drive para retomar.")
        return fid
    body = {"id": fid, "name": "Lumen - Protecao do cerebro", "mimeType": "application/vnd.google-apps.folder",
            "appProperties": {"lumen": "protection-" + p.configuration()["set_id"]}}
    try:
        gdrive._call("POST", gdrive.API + "/files?fields=id", json.dumps(body).encode(), "application/json", idempotent=False)
    except gdrive.Unconfirmed:
        if not metadata(fid):
            raise
    return fid


def upload(path, name, parent, entry, save):
    path = Path(path)
    size, sha, md5 = path.stat().st_size, p.digest(path), p.digest(path, "md5")
    if entry.get("sha256") not in (None, sha):
        raise AppError("O objeto de envio mudou durante a transferência.", "Preserve a fila e recapture uma versão estável.")
    entry.update(sha256=sha, size=size)
    fid = reserve(entry, save)
    p.report_work("checking")
    remote = metadata(fid)
    if remote and not remote.get("trashed") and int(remote.get("size", -1)) == size and remote.get("md5Checksum") == md5:
        entry.update(confirmed=p.now(), offset=size)
        entry.pop("session", None)
        save()
        return {"id": fid, "name": name, "size": size, "sha256": sha, "md5": md5}
    if remote:
        raise AppError("Um objeto imutável no Drive foi alterado ou removido.", "Restaure o objeto original; não será sobrescrito silenciosamente.")
    offset = 0
    if entry.get("session"):
        code, headers, _ = request("PUT", entry["session"], b"", {"Content-Range": f"bytes */{size}", "Content-Length": "0"})
        if code in (200, 201):
            entry.pop("session", None)
            save()
            return upload(path, name, parent, entry, save)
        if code in (404, 410):
            entry.pop("session", None)
            save()
        elif code == 308:
            offset = int(headers.get("Range", headers.get("range", "bytes=0--1")).split("-")[-1]) + 1 if any(k.lower() == "range" for k in headers) else 0
        else:
            raise AppError("O Drive não confirmou o estado do upload.")
    if not entry.get("session"):
        body = json.dumps({"id": fid, "name": name, "parents": [parent], "mimeType": "application/octet-stream"}).encode()
        code, headers, _ = request("POST", gdrive.UPLOAD + "/files?uploadType=resumable&fields=" + FIELDS,
                                    body, {"Content-Type": "application/json", "X-Upload-Content-Type": "application/octet-stream",
                                           "X-Upload-Content-Length": str(size)})
        if code == 409:
            raise AppError("Criação já recebida pelo Drive.", "Será conferida novamente pelo mesmo ID.")
        entry["session"] = headers.get("Location") or headers.get("location")
        if not entry["session"]:
            raise AppError("O Drive não devolveu a sessão retomável.")
        save()
    with path.open("rb") as f:
        while offset < size:
            p.report_work("uploading", done=offset, total=size, unit="bytes", scope="file")
            f.seek(offset)
            data = f.read(CHUNK)
            code, headers, _ = request("PUT", entry["session"], data,
                {"Content-Type": "application/octet-stream", "Content-Length": str(len(data)),
                 "Content-Range": f"bytes {offset}-{offset + len(data) - 1}/{size}"})
            if code in (200, 201):
                offset = size
            elif code == 308:
                value = headers.get("Range") or headers.get("range")
                new_offset = int(value.split("-")[-1]) + 1 if value else 0
                if new_offset <= offset:
                    raise AppError("O Drive ainda não confirmou novos bytes.")
                offset = new_offset
            else:
                if code in (404, 410):
                    entry.pop("session", None)
                save()
                raise AppError("Sessão de envio interrompida.", "O Lúmen retomará pelo mesmo identificador.")
            entry["offset"] = offset
            save()
            p.status_of("drive", status="uploading", file=name, bytes_sent=offset, bytes_total=size)
            p.report_work("checking" if offset == size else "uploading", **({} if offset == size else {"done": offset, "total": size, "unit": "bytes", "scope": "file"}))
    return upload(path, name, parent, entry, save)


def publish(sid, source):
    journal = p.read(p.HOME / "drive-queue.json")
    def save():
        p.write(p.HOME / "drive-queue.json", journal)
    parent = folder(journal, save)
    repo = p.HOME / "cloud-repository"
    local_sid = p.copy_snapshot(repo, sid)
    objects = journal.setdefault("objects", {})
    manifest = {"format": "lumen-restic-1", "created": p.now(), "snapshot": local_sid, "original_snapshot": sid,
                "source": source, "objects": [], "encryption": "Restic authenticated encryption; key stored separately"}
    # Only this worker mutates cloud-repository, and copy/check finished before this inventory.
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or "locks" in path.relative_to(repo).parts:
            continue
        sha = p.digest(path)
        name = "object-" + sha + ".bin"
        obj = upload(path, name, parent, objects.setdefault(sha, {}), save)
        manifest["objects"].append({**obj, "path": path.relative_to(repo).as_posix()})
    # The catalog contains no note contents/password and is committed only after every object is verified.
    catalog = p.HOME / "cloud-catalogs" / (sid + ".json")
    if not catalog.exists():
        p.write(catalog, manifest)
    else:
        manifest = p.read(catalog)
    entry = journal.setdefault("catalogs", {}).setdefault(sid, {})
    catalog_info = upload(catalog, "snapshot-" + source + "-" + sid + ".json", parent, entry, save)
    for asset in (Path(__file__).parent.parent / "docs" / "recuperar-drive.py", Path(__file__).parent.parent / "docs" / "RECUPERAR-PROTECAO.md"):
        upload(asset, asset.name, parent, journal.setdefault("helpers", {}).setdefault(p.digest(asset), {}), save)
    return {"id": catalog_info["id"], "catalog_sha256": catalog_info["sha256"], "snapshot": local_sid, "confirmed": p.now(), "objects": len(manifest["objects"]),
            "folder": "https://drive.google.com/drive/folders/" + parent}


def download(fid, out, expected=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,200}", fid):
        raise AppError("Identificador do Drive inválido.")
    req = urllib.request.Request(f"{gdrive.API}/files/{fid}?alt=media", headers={"Authorization": "Bearer " + gdrive._token()})
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_name(out.name + ".part")
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=45) as r, temp.open("wb") as f:
            while data := r.read(1024 * 1024):
                if shutil_free(out.parent) < len(data) + p.MIN_FREE:
                    raise AppError("Sem espaço para baixar o backup.")
                f.write(data)
        if expected and (temp.stat().st_size != expected["size"] or p.digest(temp) != expected["sha256"]):
            raise AppError("O objeto baixado do Drive está incompleto ou corrompido.")
        temp.replace(out)
    finally:
        temp.unlink(missing_ok=True)


def verify_catalog(receipt):
    import tempfile
    with tempfile.TemporaryDirectory(dir=p.HOME) as folder:
        path = Path(folder) / "catalog.json"
        download(receipt["id"], path)
        if receipt.get("catalog_sha256") and p.digest(path) != receipt["catalog_sha256"]:
            raise AppError("O catálogo do Drive foi alterado após a confirmação.")
        catalog = p.read(path)
        if catalog.get("format") != "lumen-restic-1" or not catalog.get("objects"):
            raise AppError("Catálogo incompleto no Drive.")
        for obj in catalog["objects"]:
            current = metadata(obj["id"])
            if not current or current.get("trashed") or int(current.get("size", -1)) != obj["size"] or current.get("md5Checksum") != obj["md5"]:
                raise AppError("Um objeto do backup no Drive está ausente ou alterado.", "As versões anteriores foram preservadas; consulte outra versão.")


def shutil_free(path):
    import shutil
    return shutil.disk_usage(path).free


def download_repository(catalog_id, destination):
    dest = p.check_destination(destination)
    root = dest / ("Lumen Drive recuperacao " + __import__("uuid").uuid4().hex[:10])
    root.mkdir()
    download(catalog_id, root / "catalog.json")
    manifest = p.read(root / "catalog.json")
    if manifest.get("format") != "lumen-restic-1" or not manifest.get("objects"):
        raise AppError("Catálogo do Drive inválido.")
    seen = set()
    for obj in manifest["objects"]:
        rel = p.safe_rel(obj["path"]).as_posix()
        if rel in seen:
            raise AppError("Caminho duplicado no catálogo.")
        seen.add(rel)
        download(obj["id"], p.target(root / "repository", rel), obj)
    return root, manifest


def catalogs():
    journal = p.read(p.HOME / "drive-queue.json")
    fid = journal.get("folder", {}).get("id")
    if not fid:
        # Recovery after loss of local catalog: discovery uses Drive metadata, not the installation database.
        found = gdrive.find("protection-" + p.configuration()["set_id"])
        if not found:
            return []
        fid = found["id"]
    q = f"'{fid}' in parents and trashed=false and name contains 'snapshot-'"
    result, cursor = [], None
    while True:
        args = {"q": q, "pageSize": 100, "orderBy": "createdTime desc", "fields": "nextPageToken,files(id,name,size,createdTime)"}
        if cursor:
            args["pageToken"] = cursor
        data = gdrive._call("GET", gdrive.API + "/files?" + urllib.parse.urlencode(args))
        result.extend(data.get("files", []))
        cursor = data.get("nextPageToken")
        if not cursor:
            return result
