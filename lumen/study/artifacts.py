"""Produtos dos Estudos: a fila existente gera, os anexos guardam e a conversa mostra.

Um produto nunca entra como fonte nem no índice. A pasta e o registro seguem a vida da conversa.
"""
import errno
import hashlib
import io
import re
import shutil
import threading
import time

from .. import AppError, imagegen, jobs, llm, record, visual3d
from . import attachments, chats, db

LABEL = "Gerada por IA, pode conter erros"
HOLO_MIME = {"gif": "image/gif", "png": "image/png"}  # o holograma 3D: animação (ou, na queda, o PNG) e o PNG de reserva
SIZES = {"quadrada": (1024, 1024), "paisagem": (1152, 768), "retrato": (768, 1152), "capa": (1536, 640)}


def request(text):
    from . import holo
    spec = holo.parse(text)  # /elegrama 3d e /holograma 3d; um comando incompleto levanta o exemplo de uso
    if spec:
        return spec
    match = re.match(r"^/(imagem|video|pdf)(?:\s+(.*))?$", text, re.S | re.I)
    if not match:
        return None
    kind, topic = match[1].lower(), (match[2] or "").strip()
    option, _, rest = topic.partition(" ")
    if kind == "imagem":
        shape = option if option in SIZES else "quadrada"
        topic = rest.strip() if option in SIZES else topic
        spec = {"kind": "image", "shape": shape}
    elif kind == "video":
        spec = {"kind": "video"}
    else:
        from . import pdf
        form = option if option in pdf.TYPES else "apostila"
        topic = rest.strip() if option in pdf.TYPES else topic
        spec = {"kind": "pdf", "form": form}
    if not topic or len(topic) > 1500:
        raise AppError("Descreva o assunto em até 1.500 caracteres.")
    return {**spec, "topic": topic}


def save(cid, kind, title, content, sources, meta, blob, *, suffix=None, files=None, verify=None, show=None):
    """Só publica o arquivo completo. A transação impede a conversa apagada de ressuscitar. suffix: a extensão quando não é a
    do tipo; files: outros arquivos da pasta ({nome: bytes}, o PNG de reserva do holograma); verify(pasta): relê o que foi
    gravado e levanta AppError se não confere, antes de publicar; show: campos a mais do cartão da mensagem."""
    aid = db.new_id()
    folder = attachments.folder(aid)
    suffix = suffix or {"image": ".png", "video": ".mp4", "pdf": ".pdf"}[kind]
    if kind == "image":
        from PIL import Image  # Pillow só carrega quando há imagem
        from PIL.PngImagePlugin import PngInfo
        with Image.open(io.BytesIO(blob)) as im:
            tag, out = PngInfo(), io.BytesIO()
            tag.add_text("Lumen-Generated", "true")
            im.save(out, "PNG", pnginfo=tag)
            blob = out.getvalue()
    try:
        with db.tx():
            conv = chats.get(cid, False)
            rec = {"id": aid, "conversation_id": cid, "name": title[:100] + suffix,
                   "kind": kind, "size": len(blob), "created": db.now(), "status": "generated", "message": "",
                   "text": "", "meta": {"generated": True, "sources": [{k: v for k, v in src.items() if k != "chunks"} for src in sources], **meta}, "doc_id": "", "gone": False,
                   "temporary": conv["temporary"]}
            folder.mkdir(parents=True)
            (folder / "file").write_bytes(blob)
            for name, data in (files or {}).items():
                (folder / name).write_bytes(data)
            if verify:
                verify(folder)
            if conv["temporary"]:
                with attachments._lock:
                    attachments._live[aid] = rec
            attachments._store(rec, final=True)
            return chats.add_message(cid, "assistant", content, sources, {"artifact": {"id": aid, "kind": kind,
                                     "name": rec["name"], "size": len(blob), **(show or {})}, **meta})
    except BaseException:
        with attachments._lock:
            attachments._live.pop(aid, None)
        shutil.rmtree(folder, ignore_errors=True)
        raise


def get(aid):
    rec = attachments.get(aid)
    if not rec["meta"].get("generated") or rec["status"] != "generated":
        raise AppError("Arquivo gerado não encontrado.")
    return rec


def file(aid, variant=""):
    """(caminho, tipo) do arquivo. No holograma 3D, variant="poster" é o PNG de reserva (quando o arquivo principal é a
    animação); sem ele, o principal, com o tipo gravado na hora (image/gif ou image/png)."""
    rec = get(aid)
    folder = attachments.folder(rec["id"])
    if rec["kind"] == "holo":
        info = rec["meta"].get("holo") or {}
        if variant == "poster" and info.get("format") == "gif":
            path, mime = folder / "poster.png", "image/png"
        else:
            path, mime = folder / "file", HOLO_MIME.get(info.get("format"))
        if not mime:
            raise AppError("Arquivo gerado não encontrado.")
    else:
        path, mime = folder / "file", {"image": "image/png", "video": "video/mp4", "pdf": "application/pdf"}[rec["kind"]]
    if not path.is_file():
        raise AppError("O arquivo não está mais no PC.", "Gere o material novamente.")
    return path, mime


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def save_holo(cid, vs, content, sources, cited, out, alt, origin):
    """O holograma 3D como artefato da conversa: a animação (ou, se ela não coube, o PNG) em "file" e, com animação, o PNG de
    reserva em "poster.png". Antes de publicar, os dois arquivos são relidos do disco e conferidos de novo (assinatura,
    quadros, movimento, tamanho, hash). Só então a mensagem entra na conversa."""
    gif = out["gif"]
    fmt, blob, info = ("gif", gif, out["gif_info"]) if gif else ("png", out["png"], out["png_info"])
    poster = out["png"] if gif else None
    hashes = {"file": _sha(blob), "poster": _sha(poster) if poster else ""}

    def verify(folder):
        try:
            got = (folder / "file").read_bytes()
            visual3d.inspect(got, fmt, info["width"], info["height"], info["frames"])
            if _sha(got) != hashes["file"]:
                raise ValueError("hash")
            if poster:
                again = (folder / "poster.png").read_bytes()
                visual3d.inspect(again, "png", visual3d.W, visual3d.H)
                if _sha(again) != hashes["poster"]:
                    raise ValueError("hash do PNG")
        except (OSError, ValueError):
            raise AppError("Os arquivos gravados não passaram na conferência.", "Tente gerar de novo.") from None

    title = attachments._name("Holograma 3D · " + vs["title"])[:100]
    holo = {"format": fmt, "mime": HOLO_MIME[fmt], "spec": vs, "renderer": visual3d.RENDERER, "state": out["state"],
            "reason": out["reason"] or "", "seconds": out["render_s"], "colors": out.get("colors"), "sha256": hashes}
    show = {"format": fmt, "animated": bool(gif), "poster": bool(poster), "width": info["width"], "height": info["height"],
            "frames": info["frames"], "duration_ms": info["duration_ms"], "alt": alt, "state": out["state"],
            "reason": out["reason"] or "", "family": vs["family"], "schematic": True, "origin": origin}
    return save(cid, "holo", title, content, [s for s in sources if s["sid"] in cited],
                {"generated": True, "holo": holo}, blob, suffix="." + fmt, files={"poster.png": poster} if poster else None,
                verify=verify, show=show)


def image_blob(prompt, width, height, check=jobs.check, *, missing_ok=False):
    """A imagem vem só do gerador local (imagegen); não existe geração de imagem em nuvem."""
    if not imagegen.ready():
        if missing_ok:
            return None
        raise AppError("O gerador de imagens não está instalado no destino configurado.", "Confira a instalação do gerador de capas.")
    llm.release_vram()
    check()
    blob = imagegen.generate(prompt, width=width, height=height, check=check)
    if not blob:
        if missing_ok:
            return None
        raise AppError("A imagem não ficou pronta.", "Tente novamente quando a placa estiver livre.")
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(blob)) as im:
        im = ImageOps.fit(im.convert("RGB"), (width, height))
        normalized = io.BytesIO()
        im.save(normalized, "PNG")
        blob = normalized.getvalue()
    return blob


def image(spec, cid):
    t0 = time.monotonic()
    width, height = SIZES[spec["shape"]]
    jobs._set(stage="artifact", detail="Liberando a placa para a imagem…", progress=None)
    jobs._set(detail="Gerando a imagem no seu PC…")
    blob = image_blob(spec["topic"], width, height, jobs.check)
    if not blob:
        raise AppError("A imagem não ficou pronta.", "Tente novamente quando a placa estiver livre.")
    model = imagegen.DEFAULT_ENGINE
    from PIL import Image
    with Image.open(io.BytesIO(blob)) as im:
        im.verify()
    jobs.check()
    return save(cid, "image", spec["topic"], LABEL + ".", [],
                {"generated": True, "shape": spec["shape"], "provider": "local",
                 "model": model, "seconds": round(time.monotonic() - t0, 2)}, blob)


def video(spec, cid):
    """O Lúmen não gera vídeo: a geração em nuvem foi retirada e não há motor local. Vídeos já guardados continuam no
    histórico e abrem normalmente."""
    raise AppError("O Lúmen não gera vídeo.", "Peça uma imagem (/imagem), um PDF (/pdf) ou um holograma (/elegrama 3d).")


def run(spec, conv, payload, check):
    """Eventos do chat enquanto a mesma fila usada pelas aulas trabalha. Cancelar só alcança este trabalho."""
    from . import call, listen
    if record.active() or call.CALL.active or listen.MIC.busy():
        raise AppError("Termine a gravação ou a conversa por voz antes de gerar este material.")
    done, result = threading.Event(), {}
    key = db.new_id()

    def make():
        try:
            if spec["kind"] == "image":
                msg = image(spec, conv["id"])
            elif spec["kind"] == "video":
                msg = video(spec, conv["id"])
            elif spec["kind"] == "holo":
                from . import holo
                msg = holo.make(spec, conv, payload)
            else:
                from . import pdf
                msg = pdf.make(spec, conv, payload)
            result["message"] = msg
            return {"artifact": msg["meta"]["artifact"]}
        except BaseException as e:
            result["error"] = e
            raise
        finally:
            db.close()
            done.set()

    jobs.start("study_" + spec["kind"], make, spec={"key": key, "title": spec["topic"]})
    try:
        last = None
        while not done.wait(0.2):
            check()
            state = jobs.snapshot()
            detail = state.get("detail")
            if detail != last:
                yield {"type": "status", "stage": "artifact", "detail": detail}
                last = detail
        if "error" in result:
            err = result["error"]
            if isinstance(err, OSError):  # disco cheio ou pasta sem permissão: uma mensagem que diz o que fazer, não "erro inesperado"
                full = err.errno == errno.ENOSPC
                raise AppError("Sem espaço em disco para guardar o arquivo." if full else "Não foi possível guardar o arquivo gerado.",
                               "Libere espaço e tente de novo." if full else "Confira a pasta de dados do Lúmen e tente de novo.") from None
            raise err
        yield {"type": "done", "message": result["message"]}
    finally:
        with jobs._lock:
            if jobs._job.get("status") == "running" and (jobs._job.get("spec") or {}).get("key") == key and not done.is_set():
                jobs.cancel()


def routes():
    from .api import File

    def serve(h):
        q = h._query()
        return File(*file(q.get("id", ""), q.get("variant", "")))
    return {("GET", "/api/study/artifact/file"): serve}


def prepare(aid, destination, title):
    from . import writes
    rec = get(aid)
    if rec["kind"] == "video":
        raise AppError("Vídeos gerados podem ser baixados no Lúmen, mas ainda não podem ser anexados ao Notion ou Obsidian.")
    if rec["temporary"]:
        raise AppError("Salve o material numa conversa do histórico antes de enviar para outro aplicativo.")
    path, _ = file(aid)
    if destination == "notion" and path.stat().st_size > 20_000_000:
        raise AppError("O arquivo ultrapassa o limite de 20 MB deste envio ao Notion.")
    holo = rec["kind"] == "holo"  # no Notion e no Obsidian o holograma é uma imagem (GIF animado ou PNG)
    content = ("Visualização 3D esquemática gerada pelo Lumen. Revise o conteúdo e as fontes." if holo else
               LABEL if rec["kind"] in ("image", "video") else "PDF gerado por IA. Revise o conteúdo e as fontes.")
    if destination == "obsidian":
        content = writes.note_markdown(title, "", content, rec["meta"].get("sources", []))
    preview = writes.prepare("obsidian-note" if destination == "obsidian" else "notion-page", title, content, rec["conversation_id"])
    suffix = rec["meta"]["holo"]["format"] if holo else {"image": "png", "video": "mp4", "pdf": "pdf"}[rec["kind"]]
    preview["artifact"] = {"id": aid, "kind": "image" if holo else rec["kind"], "file": f"lumen-{aid}.{suffix}"}
    if destination == "obsidian":
        from .. import store, vault
        root = vault.check(store.load_config()["obsidian_vault"])
        target = writes.attachments_dir(root, vault.inside(root, preview["path"]).parent)
        preview["artifact"]["dir"] = target.relative_to(root).as_posix()
        preview["content"] = f'![[{preview["artifact"]["file"]}]]\n\n' + preview["content"]
        preview["warnings"].append(f'O arquivo será copiado para {target.relative_to(root).as_posix()} no cofre.')
    else:
        preview["warnings"].append("O arquivo será enviado e anexado à página do Notion somente após confirmar.")
    writes.update_preview(preview["id"], {k: v for k, v in preview.items() if k != "id"})
    return preview
