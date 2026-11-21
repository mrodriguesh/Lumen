"""Proteção do cérebro: capturas independentes, snapshots Restic e retomada durável.

Nada aqui remove originais ou versões. O estado fica fora de WORK e da limpeza de aulas.
"""
import ctypes
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import keyring

from . import AppError, gdrive, store

HOME = store.DATA / "protection"
RESTIC = Path(__file__).resolve().parent.parent / "launcher" / "tools" / "restic.exe"
MARKER = ".lumen-protection.json"
LOCK = threading.RLock()
REPO_LOCK = threading.RLock()
NOTION_WRITE_LOCK = threading.RLock()
controller = None
MIN_FREE = 128 * 1024 * 1024
TEMP_ROOT = Path(tempfile.gettempdir())
_disks = {}
ACTIVITY = {}
_space_cache = {}
WORKERS = ("obsidian", "notion", "local", "drive", "obsidian_notion", "notion_obsidian")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
            background_yield()
    return h.hexdigest()


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except FileNotFoundError:
        return {} if default is None else default
    except (ValueError, UnicodeError):
        raise AppError("Um catálogo de proteção está corrompido.", "Preserve a pasta e recupere pelo repositório Restic.") from None


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        f.write(json.dumps(value, ensure_ascii=False, indent=1).encode())
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def state():
    with LOCK:
        return read(HOME / "state.json")


def update(**values):
    with LOCK:
        s = state()
        s.update(values)
        write(HOME / "state.json", s)
        return s


def status_of(name, **values):
    with LOCK:
        s = state()
        s[name] = {**s.get(name, {}), **values}
        write(HOME / "state.json", s)


def configuration():
    c = read(HOME / "config.json")
    cfg = store.load_config()
    return {"enabled": False, "local": "", "identity": None, "set_id": "", "vault": cfg["obsidian_vault"],
            "discover": True,
            "roots": [x for x in (cfg["root_page_id"], cfg["notion_free_page_id"]) if x],
            "notion_parent": cfg["root_page_id"],
            # Optional cloud copy. Until the person chooses, it stays on only where a Drive copy was already confirmed.
            "drive_enabled": c["drive_enabled"] if "drive_enabled" in c else bool(peek().get("drive", {}).get("confirmed")), **c}


_seen = [None, {}]


def peek():
    """state.json only for READING (never modify what it returns; writers keep using state()): with tens of MB, it is
    parsed again only after it changes. The workers check it on every pass (deliver_local every 5 s), the screen every 5 s."""
    try:
        st = (HOME / "state.json").stat()
    except OSError:
        return {}
    # write() always replaces the file with a new one, so the file id changes even when two writes share mtime and size
    key = (str(HOME), st.st_mtime_ns, st.st_size, st.st_ino)
    if _seen[0] != key:
        _seen[:] = [key, state()]
    return _seen[1]


def current_operation():
    """Read-only, for the workers' twice-a-second check."""
    return peek().get("operation", {})


def configure(**values):
    with LOCK:
        c = configuration()
        c.update(values)
        if not c["set_id"]:
            c["set_id"] = uuid.uuid4().hex
        write(HOME / "config.json", c)
        return c


def inside(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or b in a.parents


def redirected(p):
    return bool(p.lstat().st_file_attributes & 0x400) if os.name == "nt" else p.is_symlink()


def safe_rel(name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise AppError("Caminho inseguro no backup.", "O arquivo foi recusado.")
    p = PurePosixPath(name)
    reserved = r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?"
    if p.is_absolute() or any(x in (".", "..", "") or re.fullmatch(reserved, x) or
                              re.search(r'[<>:"|?*\x00-\x1f]', x) or x.endswith((" ", "."))
                              for x in name.split("/")):
        raise AppError("Caminho inseguro no backup.", "O arquivo foi recusado.")
    return p


def target(root, name):
    p = Path(root).joinpath(*safe_rel(name).parts)
    if not inside(p, root):
        raise AppError("Um redirecionamento sai da pasta de recuperação.", "Escolha uma pasta vazia.")
    for part in [p, *p.parents]:
        if part == Path(root).parent:
            break
        if part.exists() and redirected(part):
            raise AppError("Links e junctions não são destinos de recuperação.", "Escolha uma pasta vazia.")
    return p


def identity(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino]


def check_destination(path, cfg=None, backup=False):
    cfg = cfg or configuration()
    p = Path(path).resolve(strict=True)
    if not p.is_dir():
        raise AppError("Escolha uma pasta existente.", "Conecte o disco e tente novamente.")
    protected = [HOME, store.DATA, Path(__file__).resolve().parent.parent]
    if cfg.get("vault"):
        protected.append(Path(cfg["vault"]))
    if backup:
        protected.append(TEMP_ROOT)
    for ancestor in [p, *p.parents]:
        if (ancestor / MARKER).exists() and read(ancestor / MARKER).get("kind") == "repository":
            raise AppError("O destino fica dentro de outro repositório de backup.", "Escolha uma pasta separada.")
    for source in protected:
        if inside(p, source) or inside(source, p):
            raise AppError("Esta pasta se sobrepõe à origem ou aos dados do Lúmen.", "Escolha outra pasta para evitar recursão.")
    if shutil.disk_usage(p).free < MIN_FREE:
        raise AppError("Há menos de 128 MB livres neste destino.", "Escolha outro disco ou libere espaço.")
    with tempfile.TemporaryFile(dir=p) as f:
        f.write(b"Lumen write check")
        f.flush()
        os.fsync(f.fileno())
    return p


def choose_local(path):
    c = configuration()
    p = check_destination(path, c, backup=True)
    folder = p / "Lumen - Protecao do cerebro"
    if folder.exists():
        marker = read(folder / MARKER)
        if marker.get("owner") != c["set_id"] or not c["set_id"]:
            raise AppError("Já existe uma área de backup que não pertence a este conjunto.",
                           "Escolha outra pasta; use Recuperar para consultar um backup existente.")
    c = configure()
    folder.mkdir(exist_ok=True)
    write(folder / MARKER, {"owner": c["set_id"], "kind": "repository"})
    configure(local=str(folder), identity=identity(folder))
    status_of("local", status="pending", message="Destino escolhido; aguardando cópia e verificação.", confirmed=None)
    wake()
    return view()


def local_folder(c=None):
    c = c or configuration()
    if not c["local"]:
        raise AppError("Escolha a pasta local.", "Use Escolher pasta em Proteção do cérebro.")
    p = Path(c["local"])
    if not p.is_dir() or identity(p) != c["identity"] or read(p / MARKER).get("owner") != c["set_id"]:
        raise AppError("O disco de backup correto está indisponível.", "Reconecte o destino original; nenhum substituto foi criado.")
    return p


def password(create=False):
    c = configuration()
    if not c["set_id"]:
        c = configure()
    label = "protection-" + c["set_id"]
    value = keyring.get_password(store.APP, label)
    if not value and create:
        if (HOME / "repository" / "config").exists():
            raise AppError("A chave de recuperação não está neste Windows.", "Importe a chave exportada; não crie outro conjunto.")
        value = secrets.token_urlsafe(48)
        keyring.set_password(store.APP, label, value)
    if not value:
        raise AppError("Prepare ou importe a chave de recuperação.", "A chave não fica dentro do backup.")
    return value


def recovery_label():
    return "protection-recovery-" + hashlib.sha256(str(HOME.resolve()).encode()).hexdigest()[:20]


def run_restic(repo, *args, secret=None, cwd=None, extra_env=None):
    if args and args[0] in ("backup", "copy", "check", "restore"):
        report_work("checking" if args[0] == "check" else "saving" if args[0] == "backup" else "copying")
    if not RESTIC.is_file():
        raise AppError("Restic não está instalado nesta cópia do Lúmen.", "Restaure launcher/tools/restic.exe da distribuição verificada.")
    env = os.environ.copy()
    env.update(RESTIC_PASSWORD=secret or password(), RESTIC_CACHE_DIR=str(HOME / "restic-cache"),
               RESTIC_PACK_SIZE="16", GOMAXPROCS="1" if foreground_busy() else "2")
    env.update(extra_env or {})
    try:
        r = subprocess.run([str(RESTIC), "-r", str(repo), *map(str, args)], env=env, cwd=cwd,
                           capture_output=True, timeout=1800,
                           creationflags=0x08004000 if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        raise AppError("A operação de backup ultrapassou 30 minutos.", "O checkpoint foi preservado; confira o disco antes de retomar.") from None
    if r.returncode:
        # Paths and source contents can appear in stderr; only the exit code reaches the UI/log.
        raise AppError(f"Restic não confirmou a operação (código {r.returncode}).",
                       "Confira disco, chave e integridade. O ponto anterior foi preservado.")
    return r.stdout.decode("utf-8", "replace")


def init_repo(repo, secret=None):
    repo = Path(repo)
    if not (repo / "config").exists():
        if repo.exists() and any(repo.iterdir()):
            raise AppError("O repositório está incompleto.", "Preserve-o e use outro destino para recuperação.")
        run_restic(repo, "init", secret=secret)


def snapshots(repo=None, secret=None):
    return json.loads(run_restic(repo or HOME / "repository", "snapshots", "--json", secret=secret)) or []


def copy_snapshot(destination, sid):
    with REPO_LOCK:
        init_repo(destination)
        run_restic(destination, "copy", "--from-repo", HOME / "repository", sid,
                   extra_env={"RESTIC_FROM_PASSWORD": password()})
        run_restic(destination, "check", "--read-data")
        return next(x["id"] for x in snapshots(destination) if x["id"].startswith(sid) or x.get("original", "").startswith(sid))


def stable_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = source.stat()
    if redirected(source) or not stat.S_ISREG(before.st_mode):
        raise OSError("redirected source")
    if shutil.disk_usage(destination.parent).free < before.st_size + MIN_FREE:
        raise OSError("insufficient disk space")
    tmp = destination.with_name(destination.name + ".lumen-part")
    try:
        h = hashlib.sha256()
        with source.open("rb") as src, tmp.open("wb") as out:
            for data in iter(lambda: src.read(1024 * 1024), b""):
                out.write(data)
                h.update(data)
                background_yield()
            out.flush()
            os.fsync(out.fileno())
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise OSError("source changed while reading")
        if digest(tmp) != h.hexdigest():
            raise OSError("copy checksum mismatch")
        os.replace(tmp, destination)
        os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
        return h.hexdigest(), before
    finally:
        tmp.unlink(missing_ok=True)


def capture_vault(root, out, previous=None):
    root, out = Path(root).resolve(strict=True), Path(out)
    old = (previous or {}).get("items", {})
    manifest = {"source": "obsidian", "root": str(root), "root_identity": identity(root), "started": now(),
                "items": {}, "pending": [], "excluded": [], "consistency": "stable per file; no vault transaction"}
    if previous and previous.get("root_identity") != identity(root):
        raise AppError("A identidade do cofre mudou.", "Confirme o cofre antes de retomar; as versões anteriores permanecem guardadas.")
    if inside(out, root) or inside(root, out):
        raise AppError("A captura não pode ficar dentro do cofre.")
    visited = set()
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=lambda e: manifest["pending"].append(type(e).__name__)):
        base = Path(directory)
        if (base / MARKER).exists():
            mark = read(base / MARKER)
            if mark.get("kind") in ("notion-mirror", "repository") and mark.get("owner"):
                manifest["excluded"].append(base.relative_to(root).as_posix() + " (área gerada, ID persistente)")
                dirs[:] = []
                continue
        for name in list(dirs):
            p = base / name
            if redirected(p):
                manifest["pending"].append(p.relative_to(root).as_posix() + " (link/junction não seguido)")
                dirs.remove(name)
        for name in files:
            p = base / name
            rel = p.relative_to(root).as_posix()
            visited.add(rel)
            report_work("reading", done=len(visited), unit="files")
            if rel in (".obsidian/workspace.json", ".obsidian/workspace-mobile.json"):
                manifest["excluded"].append(rel + " (estado transitório de janelas)")
                continue
            try:
                if redirected(p):
                    raise OSError("redirected source")
                if p.suffix.lower() == ".md":
                    with p.open("rb") as f:
                        if b"lumen-protection-origin: notion" in f.read(512):
                            manifest["excluded"].append(rel + " (nota gerada movida)")
                            continue
                dest = target(out / "files", rel)
                s = p.stat()
                prior = old.get(rel, {})
                if prior.get("mtime_ns") == s.st_mtime_ns and prior.get("size") == s.st_size and dest.exists() and digest(dest) == prior.get("sha256") and digest(p) == prior["sha256"]:
                    item = dict(prior)
                    item.pop("stale", None)
                else:
                    sha, s = stable_copy(p, dest)
                    matches = [v["id"] for v in old.values() if v.get("file_identity") == [s.st_dev, s.st_ino]]
                    iid = prior.get("id") or (matches[0] if len(matches) == 1 else uuid.uuid4().hex)
                    item = {"id": iid, "path": rel, "sha256": sha, "size": s.st_size, "mtime_ns": s.st_mtime_ns,
                            "file_identity": [s.st_dev, s.st_ino], "captured": now(), "attachments": "original bytes"}
                manifest["items"][rel] = item
            except (OSError, AppError) as e:
                manifest["pending"].append(rel + " (" + type(e).__name__ + ")")
                if rel in old:
                    manifest["items"][rel] = {**old[rel], "stale": True}
    missing = set(old) - visited
    if missing and (manifest["pending"] or len(missing) > max(5, len(old) * .25)):
        manifest["pending"].append("Desaparecimento em massa ou leitura incompleta: última captura mantida.")
        for rel in missing:
            manifest["items"][rel] = {**old[rel], "stale": True}
    else:
        for rel in missing:
            target(out / "files", rel).unlink(missing_ok=True)
    manifest["deleted"] = sorted(missing) if not manifest["pending"] else []
    manifest["finished"] = now()
    return manifest


def capture_signature(manifest):
    items = {k: v.get("sha256") for k, v in manifest.get("items", {}).items()}
    return hashlib.sha256(json.dumps([items, manifest["pending"]], sort_keys=True).encode()).hexdigest()


def commit_capture(source, manifest):
    folder = HOME / "capture" / source
    signature = capture_signature(manifest)
    changed = peek().get(source, {}).get("signature") != signature
    write(folder / "manifest.json", manifest)
    status_of(source, status="partial" if manifest["pending"] else "captured", captured=manifest["finished"],
              items=len(manifest["items"]), pending=manifest["pending"], excluded=manifest.get("excluded", []),
              window=[manifest["started"], manifest["finished"]])
    if source == "notion":
        status_of(source, captured_roots=manifest.get("roots", []))
    if not changed:
        return None
    status_of(source, detected=manifest["finished"])
    with REPO_LOCK:
        init_repo(HOME / "repository")
        output = run_restic(HOME / "repository", "backup", source, "--tag", source, "--tag", "lumen-protection",
                            "--json", cwd=HOME / "capture")
        summary = next(json.loads(line) for line in reversed(output.splitlines()) if json.loads(line).get("message_type") == "summary")
        sid = summary["snapshot_id"]
        run_restic(HOME / "repository", "check")
    with LOCK:
        s = state()
        s[source]["signature"] = signature
        s[source]["snapshot"] = sid
        s[source]["snapshot_created"] = now()
        s.setdefault("versions", []).append({"id": sid, "source": source, "captured": now(),
                                              "items": len(manifest["items"]), "partial": bool(manifest["pending"]),
                                              "item_versions": {v["id"]: v["sha256"] for v in manifest["items"].values()},
                                              "local": None, "drive": None})
        write(HOME / "state.json", s)
    return sid


GUIDE = """# Recuperar sem o Lúmen

Mantenha a chave exportada em outro lugar. Use Restic oficial (https://restic.net).
Abra um terminal nesta pasta. A senha será pedida; ela não está neste backup.

    restic -r repository snapshots
    restic -r repository check --read-data
    restic -r repository restore ID --target NOVA_PASTA

Obsidian: os bytes originais estão em obsidian/files; manifest.json contém SHA-256 e cobertura.
Notion: notion contém páginas Markdown, anexos locais e JSON bruto; a API não expõe tudo do workspace.
Não abra plugins/scripts restaurados automaticamente. Mantenha .obsidian isolado até conferir os plugins.
Atual é uma cópia de consulta, sujeita às permissões do disco. Repository é criptografado.
Não substitua originais sem comparar e guardar o estado atual. Todas as versões são mantidas nesta política.
Drive: baixe um catálogo completo e todos os objetos listados; use recuperar-drive.py (Python padrão)
para montar e verificar o repositório. Ele funciona sem instalação ou catálogo do Lúmen.
"""


def verify_restored(folder):
    count = 0
    for source in ("obsidian", "notion"):
        base = Path(folder) / source
        if not base.exists():
            continue
        m = read(base / "manifest.json")
        for rel, item in m.get("items", {}).items():
            # A Notion item owns several files; the manifest lists their exact hashes.
            files = item.get("files") or {"files/" + rel: item["sha256"]}
            for name, expected in files.items():
                p = target(base, name)
                if not p.is_file() or digest(p) != expected:
                    raise AppError("A recuperação não passou na comparação SHA-256.", "Preserve o backup e consulte outra versão.")
                count += 1
    if not count:
        raise AppError("Nenhum arquivo recuperável foi confirmado.")
    return count


def restore(repo, sid, destination, secret=None):
    if not re.fullmatch(r"[a-f0-9]{8,64}", sid):
        raise AppError("Escolha uma versão válida.")
    dest = check_destination(destination)
    # Validate every archived path/type before giving Restic a new target.
    listing = run_restic(repo, "ls", sid, "--json", secret=secret)
    paths = set()
    for line in listing.splitlines():
        item = json.loads(line)
        if item.get("struct_type") == "node":
            rel = str(safe_rel(item["path"].lstrip("/")))
            if rel.casefold() in paths:
                raise AppError("Há nomes que colidem neste sistema de arquivos.", "Recupere manualmente em um sistema compatível.")
            paths.add(rel.casefold())
            if item.get("type") not in ("file", "dir"):
                raise AppError("Este snapshot contém links ou tipos especiais.", "Recupere-o manualmente em ambiente isolado.")
    out = dest / ("Lumen recuperado " + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    out.mkdir()
    run_restic(repo, "restore", sid, "--target", out, secret=secret)
    count = verify_restored(out)
    update(last_recovery={"at": now(), "files": count, "path": str(out), "snapshot": sid})
    return {"path": str(out), "files": count, "verified": True}


def view():
    c, s = configuration(), peek()
    cached = _space_cache.get(str(HOME), {})
    if time.monotonic() - cached.get("at", -10) > 5:
        cached = {"at": time.monotonic(), "bytes": sum(p.stat().st_size for p in (HOME / "repository").rglob("*") if p.is_file())}
        _space_cache[str(HOME)] = cached
    occupied = cached["bytes"]
    disk_path = HOME
    while not disk_path.exists():
        disk_path = disk_path.parent
    free = shutil.disk_usage(disk_path).free
    try:
        local_folder(c)
        local_available = True
    except (AppError, OSError):
        local_available = False
    current = copies_current(s, c)
    current["local"] = current["local"] and local_available
    activity, notion_connected = dict(ACTIVITY), bool(store.get_token())
    drive = gdrive.status()
    summary = places(s, c, local_available, drive["connected"], notion_connected, activity)
    saved = {place: [source for source in ("obsidian", "notion") if source in summary["places"][place]["held"]] for place in ("local", "drive")}
    # The screen (every 5 s) uses only id/source/dates of each version: the per-item receipts (item_versions, nearly all of
    # a state.json of tens of MB) stay in the server instead of being serialized and parsed on every refresh.
    public = {**s, "versions": [{k: x for k, x in v.items() if k != "item_versions"} for v in s["versions"]]} if "versions" in s else s
    return {"config": c, "state": public, "running": bool(controller and controller.started),
            "activity": activity, "current": current, "saved": saved, "local_available": local_available, "drive": drive,
            "notion_connected": notion_connected, **summary,
            # Changes whenever a note-level notice appears or is resolved; the screen reloads those notices then.
            "attention_key": hashlib.sha256(json.dumps([s.get("notion", {}).get("pending") or [], s.get("notion_obsidian", {}).get("conflicts") or [],
                                                        s.get("notion_obsidian", {}).get("structure_pending") or [], s.get("obsidian_notion", {}).get("pending") or []],
                                                       sort_keys=True, default=str).encode()).hexdigest()[:16],
            "has_key": bool(keyring.get_password(store.APP, "protection-" + c["set_id"])) if c["set_id"] else False,
            "bytes": occupied, "free": free, "same_device": same_device(c), "retention": "Todas as versões; sem exclusão automática.",
            "coverage": "Cofre original inteiro, exceto áreas geradas identificadas e estado transitório de janelas. Notion: raízes autorizadas e descoberta; não garante todo o workspace."}


def attention_details():
    """Read note metadata only on demand; never infer a user's edit from a hash.

    Each item: `cause` groups items with the same reason, `tone` is "review" (content to check, nothing blocks a
    copy) or "info" (no action needed), `headline`/`summary` are the short reading, `details` the full explanation,
    `action` what the single contextual button does. Sentences only state what the receipts support."""
    from . import protection_notion as pn
    s = state()
    source = HOME / "capture" / "notion"
    manifest = read(source / "manifest.json")
    items = manifest.get("items", {})
    details, seen = [], set()

    def add(cause, title, headline, summary, more, tone="review", action=None, **extra):
        if (cause, title, extra.get("page"), extra.get("path")) in seen:
            return
        seen.add((cause, title, extra.get("page"), extra.get("path")))
        kind = cause if cause in ("difference", "structure", "preserved") else "notion-copy" if cause.startswith("notion-") else "capture"
        details.append({"kind": kind, "cause": cause, "tone": tone, "title": title, "headline": headline, "summary": summary,
                        "details": more, "action": action, **extra})
    for pending in s.get("notion", {}).get("pending", []):
        iid, _, reason = pending.partition(": ")
        title = items.get(iid, {}).get("title", "Captura do Notion")
        page = {"page": iid} if iid in items else {}
        open_page = "notion-page" if page else None
        if "Bloco sem representação legível" in reason:
            add("unsupported", title, "Uma parte desta página não é disponibilizada pelo Notion",
                "O restante da página foi lido. Essa parte só pode ser vista no próprio Notion.",
                ["O Notion entrega esse bloco sem conteúdo legível. O texto acessível e os dados que o Notion retornou foram capturados.",
                 "Se precisar dessa parte fora do Notion, abra a página e exporte-a por lá. Repetir o backup não muda o que o Notion entrega."],
                action=open_page, **page)
        elif "exclusão na origem" in reason:
            add("deleted", title, "Esta página não está mais disponível no Notion",
                "Ela foi excluída ou saiu do acesso da conexão. A última leitura dela foi mantida.",
                ["Se a exclusão não foi intencional, restaure a página no Notion. O Lúmen não apaga a leitura anterior."], **page)
        elif "ausente da leitura" in reason:
            add("missing", title, "Esta página não apareceu na última leitura",
                "O Lúmen não supõe que ela foi excluída. A leitura anterior foi mantida.",
                ["Confira no Notion se a conexão ainda tem acesso a ela."], action=open_page, **page)
        elif pending.startswith("Descoberta indisponível"):
            add("discovery", "Páginas escolhidas no Notion", "Não foi possível procurar páginas novas",
                "As páginas já conhecidas continuam sendo lidas.",
                ["Páginas criadas recentemente dentro das páginas escolhidas podem ainda não ter sido encontradas.",
                 "Confira a conexão do Notion em Integrações."], action="connect-notion")
        elif "Anexo não capturado" in reason:
            raw = read(source / (iid + ".json")) if iid in items else {}
            icon = None
            for node in _nodes(raw):
                url = node.get("external", {}).get("url", "") if node.get("type") == "external" and isinstance(node.get("external"), dict) else ""
                if url and not url.startswith("https://") and hashlib.sha256(pn.canonical(url).encode()).hexdigest()[:32] in reason:
                    icon = "da página" if node is raw.get("object", {}).get("icon") else "de um bloco de destaque"
                    break
            if icon:
                add("icon", title, "Um ícone desta página não pôde ser incluído",
                    "O texto da página foi lido. Só o ícone ficou de fora.",
                    [f"O ícone {icon} veio do Notion como um símbolo, sem endereço de arquivo, e por isso não pode ser baixado.",
                     "Se o ícone importar, confira-o no Notion. Repetir o backup não muda o que o Notion entrega."],
                    action=open_page, **page)
            else:
                add("attachment", title, "Um arquivo desta página não pôde ser baixado",
                    "O restante da página foi lido. Confira o arquivo no Notion.",
                    ["Pode ser um arquivo removido ou sem acesso para a conexão. Depois de conferir, o próximo backup tenta de novo."],
                    action=open_page, **page)
        else:
            add("read", title, "Esta página não pôde ser lida por completo",
                "A leitura anterior dela foi mantida.",
                ["Confira o acesso à página no Notion. O próximo backup tenta ler de novo."], action=open_page, **page)
    mirror = s.get("notion_obsidian", {})
    dest = Path(mirror["path"]) if mirror.get("path") else None
    mark = read(dest / MARKER) if dest and dest.is_dir() else {}
    page_paths = {rel: iid for iid, rel in mark.get("pages", {}).items()}
    for rel in mirror.get("conflicts", []):
        iid = page_paths.get(rel, Path(rel).stem)
        item = items.get(iid, {})
        why = "Pode ser uma edição feita na cópia ou uma atualização interrompida; a causa não foi confirmada."
        reason = "unconfirmed"
        if dest and rel.endswith(".md") and iid in items:
            actual = target(dest, rel)
            captured = source / (iid + ".md")
            if actual.is_file() and captured.is_file() and digest(captured) == item.get("files", {}).get(iid + ".md"):
                # Only the generated timestamp and Windows line endings; no content/space normalization.
                pattern = rb"(\A---\nlumen-protection-origin: notion\nlumen-protection-id: [^\n]+\n---\n\n#[^\n]*\n\nOrigem: Notion .*? Captura: )[^\n]+"
                left, right = actual.read_bytes().replace(b"\r\n", b"\n"), captured.read_bytes().replace(b"\r\n", b"\n")
                if re.match(pattern, left) and re.match(pattern, right) and re.sub(pattern, rb"\1", left, count=1) == re.sub(pattern, rb"\1", right, count=1):
                    reason = "capture_time_only"
                    why = "O conteúdo coincide com a leitura do Notion; muda só a data gerada pelo Lúmen ou as quebras de linha do Windows."
        add("difference", item.get("title") or Path(rel).name, "Esta nota está diferente da última cópia",
            "O Lúmen manteve o arquivo como está, sem sobrescrever nada. Compare quando puder.",
            [why, "Nenhuma edição precisa ser desfeita. O arquivo continua no caminho anterior até você decidir."],
            action="locate", path=rel, reason=reason)
    for iid in mirror.get("structure_pending", []):
        add("structure", items.get(iid, {}).get("title", "Página com ancestral indisponível"), "Uma página acima desta não está acessível",
            "A parte conhecida está na pasta Estrutura a conferir.",
            ["Confira, no Notion, se a conexão tem acesso às páginas acima dela."],
            action="notion-page" if iid in items else None, **({"page": iid} if iid in items else {}))
    for item in mark.get("preserved_copies", []):
        add("preserved", item["title"], "Versão antiga preservada para comparação",
            "Nenhuma ação necessária.",
            ["A diferença era só a data da captura ou as quebras de linha. A nota atual já está organizada; esta versão anterior foi guardada intacta em Versões preservadas."],
            tone="info", action="locate", path=item["path"])
    for pending in s.get("obsidian_notion", {}).get("pending") or []:
        rel, _, reason = pending.partition(": ")
        limited = "5 MB" in reason or "não aceita este anexo" in reason
        add("notion-attachment" if limited else "notion-copy", PurePosixPath(rel).stem or rel,
            "Um anexo desta nota não coube no Notion" if limited else "Esta nota não foi copiada por completo para o Notion",
            "A página foi criada no Notion sem esse anexo." if limited else "A nota original continua no seu cofre do Obsidian.",
            ["Consulte o anexo no Obsidian." if limited else "O próximo backup tenta de novo. Se continuar, confira a conexão do Notion."],
            action="notion-area")
    return {"items": details}


def _nodes(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _nodes(v)
    elif isinstance(value, list):
        for v in value:
            yield from _nodes(v)


def open_destination(place, relative=None):
    """Open recorded destinations, with no client-controlled arbitrary path or URL."""
    import webbrowser
    s, c = state(), configuration()
    if place == "local":
        os.startfile(str(local_folder(c)))
    elif place == "notion_obsidian":
        value = s.get(place, {}).get("path")
        if not value:
            raise AppError("A cópia navegável ainda não foi criada.")
        dest = Path(value)
        marker = read(dest / MARKER)
        if marker.get("owner") != c["set_id"] or marker.get("kind") != "notion-mirror":
            raise AppError("A pasta das notas não está disponível ou sua identidade mudou.")
        if relative:
            allowed = s.get(place, {}).get("conflicts", []) + [x["path"] for x in marker.get("preserved_copies", [])]
            if relative not in allowed:
                raise AppError("Esta nota não está na lista de diferenças preservadas.")
            dest = target(dest, relative)
        elif (dest / "Particular").is_dir():
            dest = dest / "Particular"
        if not dest.exists():
            raise AppError("A nota ou pasta não está disponível neste momento.")
        # Reveal notes without invoking file associations that could execute restored content.
        if dest.is_file():
            subprocess.Popen(["explorer.exe", "/select,", str(dest)])
        else:
            os.startfile(str(dest))
    else:
        if place == "drive":
            fid = read(HOME / "drive-queue.json").get("folder", {}).get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{5,200}", fid):
                raise AppError("Ainda não há uma pasta de backup confirmada no Drive.")
            url = "https://drive.google.com/drive/folders/" + fid
        elif place == "obsidian_notion":
            url = s.get(place, {}).get("url", "")
            if not re.fullmatch(r"https://www\.notion\.so/[a-f0-9]{32}", url):
                raise AppError("A área de notas no Notion ainda não foi criada.")
        elif place == "source":
            if relative not in read(HOME / "capture/notion/manifest.json").get("items", {}):
                raise AppError("Esta página não está na captura.")
            url = "https://www.notion.so/" + relative.replace("-", "")
        else:
            raise AppError("Destino desconhecido.")
        webbrowser.open(url)
    return {"notice": "Destino aberto."}


def wake():
    if controller:
        controller.request_now()


def enable(on=True):
    password(create=True)
    configure(enabled=bool(on))
    wake()
    return view()


def mark_version(sid, destination, confirmation):
    with LOCK:
        s = state()
        for v in s.get("versions", []):
            if v["id"] == sid:
                v[destination] = confirmation
                receipts = read(HOME / "receipts.json")
                for iid, sha in v.get("item_versions", {}).items():
                    item = receipts.setdefault(v["source"] + ":" + iid + ":" + sha, {"source": v["source"], "id": iid, "sha256": sha})
                    item[destination] = {"snapshot": sid, **confirmation}
                write(HOME / "receipts.json", receipts)
        write(HOME / "state.json", s)


def deliver_local(versions=None):
    dest = local_folder()
    s = peek()  # read-only here: mark_version/status_of read and write state.json themselves
    prior_status = s.get("local", {})
    versions = s.get("versions", []) if versions is None else versions
    if not versions:
        raise AppError("Aguardando o primeiro snapshot recuperável.")
    confirmed = 0
    for version in versions:
        if isinstance(version.get("local"), dict) and version["local"].get("path") == str(dest):
            continue
        sid = copy_snapshot(dest / "repository", version["id"])
        (dest / "RECUPERAR.md").write_text(GUIDE, "utf-8")
        mark_version(version["id"], "local", {"path": str(dest), "snapshot": sid, "confirmed": now()})
        confirmed += 1
    if confirmed:  # mark_version changed the receipts; otherwise the list read above is current
        selected = {v["id"] for v in versions}
        versions = [v for v in state().get("versions", []) if v["id"] in selected]
    # Atual is materialized from a verified snapshot, never from a capture being modified.
    for source in ("obsidian", "notion"):
        latest = next((v for v in reversed(versions) if v["source"] == source and
                       isinstance(v.get("local"), dict) and v["local"]["path"] == str(dest)), None)
        if not latest:
            continue
        mark_path = dest / ("current-" + source + ".json")
        mark = read(mark_path)
        if mark.get("snapshot") == latest["id"]:
            continue
        stage = dest / (".restore-" + source)
        stage.mkdir(exist_ok=True)
        run_restic(dest / "repository", "restore", latest["local"]["snapshot"], "--target", stage)
        verify_restored(stage)
        incoming = stage / source
        manifest = read(incoming / "manifest.json")
        valid = {"manifest.json"}
        for rel, item in manifest["items"].items():
            valid.update(item.get("files") or ["files/" + rel])
        current = dest / "Atual" / source
        current.mkdir(parents=True, exist_ok=True)
        owned = mark.get("files", {})
        conflicts, hashes = [], {}
        for f in incoming.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(incoming).as_posix()
            if rel not in valid:
                continue
            out = target(current, rel)
            sha = digest(f)
            if out.exists() and digest(out) not in (sha, owned.get(rel)):
                conflicts.append(rel)
                continue
            stable_copy(f, out)
            hashes[rel] = sha
        for rel, old_sha in owned.items():
            if rel in valid:
                continue
            out = target(current, rel)
            if out.exists():
                if digest(out) == old_sha:
                    out.unlink()  # owned, unchanged current copy; its historical snapshot was already verified above.
                else:
                    conflicts.append(rel)
        write(mark_path, {"snapshot": latest["id"] if not conflicts else None, "files": {**owned, **hashes}})
        if conflicts:
            status_of("local", status="conflict", conflicts=conflicts, message="Edições em Atual foram preservadas; o histórico criptografado foi confirmado.")
            return
        confirmed += 1  # the readable copy was just materialized and verified too.
        # Stage contains only generated restored data, no user files; keep it reusable for crash recovery.
    if configuration()["local"] != str(dest):
        raise AppError("O destino foi alterado; a cópia anterior permanece preservada.", "A próxima passagem verificará o novo destino.")
    latest = {v["source"]: v for v in versions}
    if not confirmed and prior_status.get("status") in ("confirmed", "partial") and prior_status.get("path") == str(dest) \
            and prior_status.get("source_versions") == {source: v["id"] for source, v in latest.items()}:
        return  # nothing new: every 5 s this would rewrite tens of MB of state and receipts
    write(dest / "receipts.json", read(HOME / "receipts.json"))
    if not confirmed and prior_status.get("status") not in ("confirmed", "partial"):
        run_restic(dest / "repository", "check", "--read-data")
        confirmed += 1
    confirmation = now() if confirmed else prior_status.get("confirmed")
    latest = {v["source"]: v for v in versions}
    partial = len(latest) < 2 or any(v["partial"] for v in latest.values())
    status_of("local", status="partial" if partial else "confirmed", confirmed=confirmation, path=str(dest), free=shutil.disk_usage(dest).free,
              source_versions={source: v["id"] for source, v in latest.items()},
              message="Snapshots verificados; há origens ou itens ainda pendentes." if partial else "Snapshots verificados; Atual legível. Versões anteriores mantidas.")


def foreground_busy():
    from . import jobs, record
    return jobs.busy() or record.active()


def report_work(stage, **progress):
    name = threading.current_thread().name.removeprefix("Lumen protection ")
    if name in WORKERS:
        with LOCK:
            ACTIVITY[name] = {"stage": stage, **progress}


def backup_now():
    """One durable request; it does not change the automatic-backup preference."""
    with LOCK:
        s = state()
        if s.get("operation", {}).get("status") == "running":
            return view()
        password(create=True)
        if not controller or not controller.started:
            start()
        s["operation"] = {"id": uuid.uuid4().hex, "status": "running", "started": now(), "steps": {}, "targets": {},
                          "previous_targets": {v["source"]: v["id"] for v in s.get("versions", [])}}
        write(HOME / "state.json", s)
    wake()
    return view()


def finish_step(oid, name, error=None):
    with LOCK:
        s = state()
        op = s.get("operation", {})
        if op.get("id") != oid or op.get("status") != "running":
            return
        current = s.get(name, {})
        result = "failed" if error else "partial" if current.get("status") in ("partial", "pending", "conflict") else "done"
        op["steps"][name] = {"status": result, "finished": now(), "message": error or current.get("message", "")}
        if name in ("obsidian", "notion") and not error and current.get("snapshot"):
            op["targets"][name] = current["snapshot"]
        if all(worker in op["steps"] for worker in WORKERS):
            results = [x["status"] for x in op["steps"].values()]
            op.update(status="completed" if all(x == "done" for x in results) else "failed" if all(x == "failed" for x in results) else "partial", finished=now())
            if op["status"] == "completed":
                op["outcome"] = "unchanged" if op["targets"] and op["targets"] == op.get("previous_targets") else "saved"
        write(HOME / "state.json", s)


def copies_current(s, c):
    latest = {v["source"]: v for v in s.get("versions", [])}
    clean = {source: source in latest and not latest[source].get("partial") and not s.get(source, {}).get("pending") and s.get(source, {}).get("status") != "pending" for source in ("obsidian", "notion")}
    if c["roots"]:
        clean["notion"] = clean["notion"] and s.get("notion", {}).get("captured_roots") == c["roots"]
    local = all(clean.values()) and s.get("local", {}).get("status") == "confirmed"
    drive = all(clean.values()) and s.get("drive", {}).get("status") == "confirmed"
    for source in ("obsidian", "notion"):
        receipt = latest.get(source, {}).get("local") or {}
        local = local and receipt.get("path") == c["local"] and bool(receipt.get("confirmed")) and s["local"].get("confirmed", "") >= receipt.get("confirmed", "")
        local = local and s.get("local", {}).get("source_versions", {}).get(source) == latest.get(source, {}).get("id")
        drive = drive and bool(latest.get(source, {}).get("drive"))
    result = {"local": bool(local), "drive": bool(drive)}
    for name, source in (("obsidian_notion", "obsidian"), ("notion_obsidian", "notion")):
        result[name] = bool(clean[source] and s.get(name, {}).get("status") == "confirmed" and s[name].get("source_snapshot") == latest[source]["id"])
    return result


def _after(a, b):
    """a is a later timestamp than b; a missing b counts as never. Restic and Python formats both parse."""
    try:
        a, b = (datetime.fromisoformat(x) if x else None for x in (a, b))
    except (TypeError, ValueError):
        return False
    return bool(a) and (b is None or a > b)


ORIGINS = {"local": ("obsidian", "notion"), "drive": ("obsidian", "notion"),
           "notion_obsidian": ("notion",), "obsidian_notion": ("obsidian",)}


def places(s, c, local_available, drive_connected, notion_connected, activity):
    """One state code per destination, from persisted receipts and live activity only.

    `held` is the version of each origin the destination really confirmed, which may be older than the newest
    capture. The interface turns codes into words and never upgrades them: a connection, an existing folder, an
    accepted request or an old success is not a current confirmation."""
    versions = s.get("versions", [])
    latest = {v["source"]: v for v in versions}
    op = s.get("operation", {})
    sources = {}
    for o in ("obsidian", "notion"):
        st = s.get(o, {})
        failed = _after(st.get("failed"), st.get("captured"))
        sources[o] = {"read": st.get("captured"), "version": latest.get(o, {}).get("captured"),
                      "pending": len(st.get("pending") or []), "failed": failed, "message": st.get("message", "") if failed else "",
                      # changes read but not yet in a snapshot, or chosen pages that the last reading did not cover
                      "unsaved": _after(st.get("detected"), st.get("snapshot_created")) or
                                 (o == "notion" and bool(c["roots"]) and "captured" in st and st.get("captured_roots") != c["roots"])}
    result = {}
    for place, origins in ORIGINS.items():
        st = s.get(place, {})
        held = {}
        for o in origins:
            if place in ("local", "drive"):
                v = next((v for v in reversed(versions) if v["source"] == o and isinstance(v.get(place), dict) and v[place].get("confirmed")
                          and (place != "local" or v[place].get("path") == c["local"])), None)
                confirmed = v and v[place]["confirmed"]
            else:
                v = next((v for v in versions if v["id"] == st.get("source_snapshot")), None) if st.get("confirmed") else None
                confirmed = st.get("confirmed")
            if v:
                held[o] = {"version": v.get("captured"), "confirmed": confirmed, "partial": bool(v.get("partial")), "newest": v["id"] == latest[o]["id"]}
                if place == "drive":
                    held[o]["objects"] = v[place].get("objects")
        fresh = len(held) == len(origins) and all(h["newest"] for h in held.values()) and not any(sources[o]["unsaved"] for o in origins)
        settled = st.get("status") in ("confirmed", "partial") and (
            place != "local" or all(st.get("source_versions", {}).get(o) == latest.get(o, {}).get("id") for o in origins))
        own = st.get("structure_pending") if place == "notion_obsidian" else st.get("pending") if place == "obsidian_notion" else None
        mirror = place in ("notion_obsidian", "obsidian_notion")
        live = activity.get(place)
        if place == "local" and not c["local"] or place == "notion_obsidian" and not c["vault"]:
            code = "setup"
        elif place == "drive" and not c["drive_enabled"]:
            code = "disabled"
        elif place == "drive" and not drive_connected or mirror and not notion_connected:
            code = "unavailable" if held else "setup"
        elif place == "local" and not local_available:
            code = "unavailable"
        elif live:
            code = "checking" if live.get("stage") in ("checking", "reading") else "copying"
        elif op.get("status") == "running" and place not in op.get("steps", {}):
            code = "queued"
        elif _after(st.get("failed"), st.get("confirmed")) or st.get("status") == "conflict" or fresh and settled and own:
            code = "attention"
        elif not held:
            code = "first"
        elif fresh and settled:
            code = "ok"
        elif not fresh:
            code = "behind"
        else:
            code = "unknown"
        link = (bool(c["local"]) and local_available if place == "local" else bool(held) if place == "drive" else
                bool(st.get("path")) and Path(st["path"]).is_dir() if place == "notion_obsidian" else
                bool(re.fullmatch(r"https://www\.notion\.so/[a-f0-9]{32}", st.get("url", ""))))
        result[place] = {"state": code, "held": held, "confirmed": st.get("confirmed"), "link": link,
                         "message": st.get("message", "") if code == "attention" else "",
                         "items": st.get("items") if mirror else None, "organized": st.get("layout") == "notion-hierarchy-1",
                         "conflicts": len(st.get("conflicts") or []), "own_pending": len(own or [])}
    return {"places": result, "sources": sources}


def mirrored(st, snapshot, settled, where):
    """The automatic pass already copied this snapshot to this destination and nothing failed since."""
    return bool(snapshot) and st.get("source_snapshot") == snapshot and st.get("where") == where and st.get("status") in settled \
        and not _after(st.get("failed"), st.get("confirmed"))


def background_yield():
    if threading.current_thread().name.startswith("Lumen protection") and foreground_busy():
        time.sleep(.125)  # bound backup I/O to roughly 8 MiB/s while the lesson has priority.


def reconcile_snapshots():
    """A crash after Restic committed but before state.json was written must not strand a snapshot."""
    if not (HOME / "repository" / "config").exists():
        return
    known = {x["id"] for x in state().get("versions", [])}
    missing = [x for x in snapshots() if x["id"] not in known and "lumen-protection" in x.get("tags", [])]
    for snapshot in missing:
        source = next((x for x in snapshot["tags"] if x in ("obsidian", "notion")), None)
        if not source:
            continue
        manifest = json.loads(run_restic(HOME / "repository", "dump", snapshot["id"], source + "/manifest.json"))
        with LOCK:
            s = state()
            s.setdefault("versions", []).append({"id": snapshot["id"], "source": source, "captured": snapshot["time"],
                "items": len(manifest["items"]), "partial": bool(manifest["pending"]),
                "item_versions": {v["id"]: v["sha256"] for v in manifest["items"].values()}, "local": None, "drive": None})
            s["versions"].sort(key=lambda x: datetime.fromisoformat(x["captured"]).timestamp())
            latest = next(v for v in reversed(s["versions"]) if v["source"] == source)
            if latest["id"] == snapshot["id"]:
                s.setdefault(source, {}).update(signature=capture_signature(manifest), snapshot=snapshot["id"],
                    snapshot_created=snapshot["time"])
            write(HOME / "state.json", s)


def same_device(c):
    if not c.get("local") or not c.get("vault"):
        return None
    def number(path):
        drive = Path(path).drive.rstrip(":").upper()
        if not re.fullmatch("[A-Z]", drive):
            return None
        if drive not in _disks:
            command = f"(Get-Partition -DriveLetter {drive} -ErrorAction Stop).DiskNumber"
            try:
                r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                   capture_output=True, timeout=10, creationflags=0x08000000)
                _disks[drive] = int(r.stdout.strip()) if r.returncode == 0 else None
            except (OSError, ValueError, subprocess.TimeoutExpired):
                _disks[drive] = None
        return _disks[drive]
    a, b = number(c["vault"]), number(c["local"])
    return a == b if a is not None and b is not None else None


class Watch:
    """Windows recursive change notification; periodic reconciliation covers dropped notifications."""
    def __init__(self, root):
        self.handle = None
        if os.name == "nt" and root and Path(root).is_dir():
            k = ctypes.windll.kernel32
            k.FindFirstChangeNotificationW.restype = ctypes.c_void_p
            k.FindFirstChangeNotificationW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint]
            k.FindNextChangeNotification.argtypes = [ctypes.c_void_p]
            k.FindCloseChangeNotification.argtypes = [ctypes.c_void_p]
            k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            self.handle = k.FindFirstChangeNotificationW(str(root), True, 0x1 | 0x2 | 0x8 | 0x10)
            if self.handle == ctypes.c_void_p(-1).value:
                self.handle = None

    def changed(self):
        if self.handle and ctypes.windll.kernel32.WaitForSingleObject(self.handle, 0) == 0:
            ctypes.windll.kernel32.FindNextChangeNotification(self.handle)
            return True
        return False

    def close(self):
        if self.handle:
            ctypes.windll.kernel32.FindCloseChangeNotification(self.handle)
            self.handle = None


class Controller:
    def __init__(self):
        self.stop_event = threading.Event()
        self.threads = []
        self.started = False
        self.file = None
        self.source_locks = {x: threading.Lock() for x in ("obsidian", "notion")}
        self.requested = 0
        self.recovered = False
        self.recovery_lock = threading.Lock()

    def request_now(self):
        self.requested += 1

    def start(self):
        if self.started:
            return
        HOME.mkdir(parents=True, exist_ok=True)
        self.file = (HOME / "controller.lock").open("a+b")
        try:
            self.file.seek(0)
            if self.file.read(1) == b"":
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise AppError("Já existe um controlador de proteção usando este conjunto.") from None
        self.started = True
        from . import notion
        notion.backup_rate_enabled = True
        for name, fn, seconds in (("obsidian", self.vault_cycle, 60), ("notion", self.notion_cycle, 30),
                                  ("local", deliver_local, 5), ("drive", self.drive_cycle, 10),
                                  ("obsidian_notion", self.mirror_cycle, 60), ("notion_obsidian", self.vault_mirror_cycle, 30)):
            t = threading.Thread(target=self.loop, args=(name, fn, seconds), daemon=True, name="Lumen protection " + name)
            self.threads.append(t)
            t.start()

    def recover(self):
        with self.recovery_lock, REPO_LOCK:
            if self.recovered:
                return
            repos = [HOME / "repository", HOME / "cloud-repository"]
            try:
                repos.append(local_folder() / "repository")
            except (AppError, OSError):
                pass  # an offline local disk must not stop the independent cloud capture.
            for repo in repos:
                if (repo / "config").exists():
                    run_restic(repo, "unlock")  # only stale locks, after our exclusive controller lock.
            reconcile_snapshots()
            self.recovered = True

    def loop(self, name, fn, seconds):
        watch = Watch(configuration()["vault"]) if name == "obsidian" else None
        next_run, first, last, requested, deferred = 0.0, None, None, -1, None
        while not self.stop_event.wait(.5):
            c = configuration()
            op = current_operation()
            manual =op.get("status") == "running" and name not in op["steps"]
            if manual and name not in ("obsidian", "notion") and not all(source in op["steps"] for source in ("obsidian", "notion")):
                continue
            if not c["enabled"] and not manual:
                continue
            if name == "drive" and not c["drive_enabled"] and not manual:
                continue
            moment = time.monotonic()
            if watch and watch.changed():
                first = first or moment
                last = moment
                status_of(name, event_detected=now())
            due = manual or moment >= next_run or requested != self.requested or (first and (moment - last >= 2 or moment - first >= 20))
            if not due:
                continue
            if name not in ("obsidian", "notion") and foreground_busy():
                if deferred is None:
                    deferred = moment
                    status_of(name, scheduling="Aula em andamento: envio adiado por até 30 s; captura continua com prioridade reduzida.")
                if moment - deferred < 30:
                    continue
            wanted = self.requested
            error = None
            report_work("reading" if name in ("obsidian", "notion") else "copying")
            # Also used by callers/tests that run loop outside a named worker thread.
            with LOCK:
                ACTIVITY[name] = {"stage": "reading" if name in ("obsidian", "notion") else "copying"}
            try:
                if not self.recovered:
                    self.recover()
                if name == "local" and not c["local"]:
                    raise AppError("Escolha uma pasta para guardar suas cópias neste computador.")
                elif manual and name not in ("obsidian", "notion"):
                    self.request_step(name, op)
                else:
                    fn()
            except Exception as e:
                error = (str(e) + " " + e.action).strip() if isinstance(e, AppError) else "Não foi possível terminar. Sua cópia anterior continua guardada."
                status_of(name, status="pending", message=error, failed=now())
            finally:
                with LOCK:
                    ACTIVITY.pop(name, None)
            if manual:
                finish_step(op["id"], name, error)
            interval = peek().get("notion", {}).get("poll_seconds", seconds) if name == "notion" else seconds
            next_run = time.monotonic() + interval
            requested = wanted
            first = last = None
            deferred = None
        if watch:
            watch.close()

    def request_step(self, name, op):
        targets = set(op["targets"].values())
        versions = peek().get("versions", [])
        chosen = [v for v in versions if v["id"] in targets]
        if name in ("local", "drive"):
            if not chosen:
                raise AppError("Primeiro precisamos conseguir ler suas notas.")
            # Include older pending versions, but never extend this request to later automatic edits.
            last = max(i for i, v in enumerate(versions) if v["id"] in targets)
            if name == "local":
                deliver_local(versions[:last + 1])
            else:
                self.drive_cycle(versions[:last + 1])
        else:
            source = "obsidian" if name == "obsidian_notion" else "notion"
            sid = op["targets"].get(source)
            if not sid:
                raise AppError("Ainda falta ler as notas do " + ("Obsidian" if source == "obsidian" else "Notion") + ".")
            if source == "obsidian":
                self.mirror_cycle(sid)
            else:
                self.vault_mirror_cycle(sid)

    def vault_cycle(self):
        with self.source_locks["obsidian"]:
            folder = HOME / "capture" / "obsidian"
            m = capture_vault(configuration()["vault"], folder, read(folder / "manifest.json"))
            commit_capture("obsidian", m)

    def notion_cycle(self):
        from . import protection_notion as pn
        token = store.get_token()
        if not token:
            raise AppError("Conecte o Notion nas integrações.")
        with self.source_locks["notion"]:
            folder = HOME / "capture" / "notion"
            folder.mkdir(parents=True, exist_ok=True)
            c = configuration()
            m = pn.capture(token, c["roots"], folder, read(folder / "manifest.json"), discover=c["discover"])
            changed = commit_capture("notion", m)
            interval = 30 if changed else min(60, peek().get("notion", {}).get("poll_seconds", 30) * 1.5)
            status_of("notion", poll_seconds=interval, expected_delay="30–60 s após a última leitura, mais a duração da captura e eventuais limites da API.")

    def drive_cycle(self, versions=None):
        from . import protection_drive as pd
        if not configuration()["drive_enabled"]:
            return  # optional cloud copy: a manual request still finishes this step without an error.
        versions = peek().get("versions", []) if versions is None else versions
        if not versions:
            raise AppError("Aguardando o primeiro snapshot recuperável.")
        completed = []
        for v in versions:
            if self.stop_event.is_set() or not configuration()["drive_enabled"]:
                return  # checked between versions, never in the middle of an upload.
            if not v.get("drive"):
                receipt = pd.publish(v["id"], v["source"])
                mark_version(v["id"], "drive", receipt)
                completed.append(receipt["confirmed"])
        previous = peek().get("drive", {})
        latest = {v["source"]: v for v in peek().get("versions", [])}
        if not completed and (previous.get("status") not in ("confirmed", "partial") or time.time() - previous.get("verified_epoch", 0) > 3600):
            for version in latest.values():
                pd.verify_catalog(version["drive"])
            completed.append(now())
        if completed:
            partial = len(latest) < 2 or any(v["partial"] for v in latest.values())
            status_of("drive", status="partial" if partial else "confirmed", confirmed=max(completed), verified_epoch=time.time(),
                      message="Objetos e catálogos conferidos; há origens ou itens pendentes." if partial else "Objetos criptografados e catálogos conferidos no Drive.")

    def mirror_cycle(self, sid=None):
        from . import protection_notion as pn
        latest = next((v for v in reversed(peek().get("versions", [])) if v["source"] == "obsidian" and (sid is None or v["id"] == sid)), None)
        if not latest or sid is None and mirrored(peek().get("obsidian_notion", {}), latest["id"], ("confirmed",), configuration()["notion_parent"]):
            return  # re-checking every page each minute only spent the Notion API quota
        # Network backoff in the mirror must never hold the source capture lock.
        stage = HOME / "mirror-snapshot"
        with NOTION_WRITE_LOCK:
            if read(stage / "version.json").get("id") != latest["id"]:
                with REPO_LOCK:
                    run_restic(HOME / "repository", "restore", latest["id"], "--target", stage)
                verify_restored(stage)
                write(stage / "version.json", {"id": latest["id"]})
            m = read(stage / "obsidian" / "manifest.json")
            pn.mirror_to_notion(store.get_token(), configuration()["notion_parent"], m, stage / "obsidian")
            status_of("obsidian_notion", source_snapshot=latest["id"], where=configuration()["notion_parent"])

    def vault_mirror_cycle(self, sid=None):
        from . import protection_notion as pn
        with self.source_locks["notion"]:
            folder = HOME / "capture" / "notion"
            s = peek()
            # partial here means pending pages in the Notion reading itself, which a new pass cannot fix
            if not sid and mirrored(s.get("notion_obsidian", {}), s.get("notion", {}).get("snapshot"), ("confirmed", "partial"), configuration()["vault"]):
                return
            if not sid:
                m = read(folder / "manifest.json")
                try:
                    if m:
                        pn.mirror_to_vault(configuration()["vault"], m, folder)
                        status_of("notion_obsidian", source_snapshot=peek().get("notion", {}).get("snapshot"), where=configuration()["vault"])
                    return
                except pn.CaptureChanged:
                    # Lúmen closed mid-reading: the live folder is half new; the last snapshot is whole.
                    sid = peek().get("notion", {}).get("snapshot")
                    if not sid:
                        raise
            stage = HOME / "request-notion-mirror"
            if read(stage / "version.json").get("id") != sid:
                with REPO_LOCK:
                    run_restic(HOME / "repository", "restore", sid, "--target", stage)
                verify_restored(stage)
                write(stage / "version.json", {"id": sid})
            folder = stage / "notion"
            m = read(folder / "manifest.json")
            if m:
                pn.mirror_to_vault(configuration()["vault"], m, folder)
                status_of("notion_obsidian", source_snapshot=sid, where=configuration()["vault"])

    def stop(self):
        self.stop_event.set()
        deadline = time.monotonic() + 5
        for t in self.threads:
            t.join(max(0, deadline - time.monotonic()))
        # Keep the OS lock until process exit if a network call is still unwinding.
        if all(not t.is_alive() for t in self.threads) and self.file:
            self.file.close()
            self.started = False


def start():
    global controller
    if controller is None or not controller.started:
        controller = Controller()
        controller.start()
        import atexit
        atexit.register(stop)


def stop():
    if controller:
        controller.stop()
