"""Anexos do chat dos Estudos (Study AI 2.0, fase 4): clipe, arrastar ou colar (inclusive print com Ctrl+V), e o /tela.

- O tipo vem dos bytes iniciais, nunca da extensão; um tipo desconhecido é recusado. Cada tipo tem um teto de tamanho.
  Nada é executado: o arquivo é guardado sem extensão e só lido.
- O arquivo fica em MEDIA/anexos/<id>/ (no D:, D22) e é apagado com a conversa. Antes de enviar e nas conversas
  temporárias, o registro fica só na memória (D13); no início do Lúmen, o que sobrou sem conversa salva é apagado.
- Leitura em segundo plano: texto e documentos do Office na hora; PDF pelo pypdf, e as páginas sem texto (escaneadas)
  pela visão; imagem pela visão local (descrição e texto lido); áudio e vídeo transcritos, com os quadros-chave do
  vídeo também pela visão. A visão e a transcrição, uma por vez, esperam a aula que estiver sendo processada.
- Na conversa, cada anexo pronto vira uma fonte S# em toda resposta, embrulhada como dado (tools.wrap). As imagens
  nunca saem do PC: o Claude, se for o provedor, recebe só o texto que a visão local leu.
- "Adicionar ao índice" guarda o texto como documento da origem "arquivos", para as próximas conversas."""
import codecs
import posixpath
import re
import shutil
import threading
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile

from .. import AppError, Cancelled, llm, protection, vault
from . import db, index, providers
from .images import jpeg as _jpeg_pil, note_text, see
from .sources import Doc, web

MB = 1 << 20
LIMIT = {"text": 5 * MB, "pdf": 60 * MB, "office": 60 * MB, "image": 25 * MB, "audio": 500 * MB, "video": 2048 * MB}
LABEL = {"text": "Texto", "pdf": "PDF", "office": "Documento", "image": "Imagem", "audio": "Áudio", "video": "Vídeo",
         "holo": "Holograma 3D"}
HEAD = 64 * 1024        # bytes lidos para decidir o tipo
MAX_TEXT = 400_000      # texto guardado por anexo (o modelo recebe os trechos mais ligados à pergunta)
MAX_PER_CONV = 10
PDF_PAGES, VISION_PAGES = 300, 20  # páginas lidas e, das sem texto, quantas vão para a visão
ZIP_TOTAL = 300 * MB    # soma descompactada de um docx/pptx/xlsx/odt/epub (contra "zip bomb")
XML_MAX = 60 * MB       # um XML lido por inteiro na memória
TAKE = 6                # trechos do anexo por resposta (das notas são 3)
STAGED_HOURS = 24

_live, _lock, _heavy = {}, threading.RLock(), threading.Lock()


def folder(aid):
    return db.MEDIA / "anexos" / aid


# --- Tipo real ---------------------------------------------------------------------------------------------------

def sniff(head):
    """O tipo pelos bytes iniciais: pdf, office (zip), image, audio, video, text ou None (recusado)."""
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "office"
    if head.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or head[:4] == b"RIFF" and head[8:12] == b"WEBP" \
            or head[:2] == b"BM" and head[6:10] == b"\0\0\0\0":
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE" or head.startswith((b"ID3", b"OggS", b"fLaC")) \
            or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio"
    if head[4:8] == b"ftyp":
        if head[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"avif", b"avis"):
            return None  # foto HEIC/AVIF (iPhone): a visão local não abre; exporte em JPG
        return "audio" if head[8:12] in (b"M4A ", b"M4B ") else "video"
    if head.startswith(b"\x1aE\xdf\xa3"):  # mkv e webm
        return "video"
    if head and b"\0" not in head:
        try:
            codecs.getincrementaldecoder("utf-8")().decode(head)  # um caractere cortado no fim do pedaço não conta
            return "text"
        except UnicodeDecodeError:  # texto antigo do Windows (cp1252): quase nada de controle
            if sum(b < 9 or 13 < b < 32 for b in head) < len(head) / 100:
                return "text"
    return None


def _name(raw):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(raw or "").replace("\\", "/").rsplit("/", 1)[-1]).strip(" .")
    return name[:120] or "anexo"


# --- Recebimento ---------------------------------------------------------------------------------------------------

def public(rec):
    return {k: rec.get(k) for k in ("id", "name", "kind", "size", "status", "message", "doc_id", "conversation_id")} | \
        {"label": LABEL[rec["kind"]], "chars": len(rec.get("text") or ""), "thumb": rec["kind"] == "image"}


def receive(read, n, raw_name):
    """Guarda um anexo enviado (read(k) lê o corpo) e começa a lê-lo. Devolve o registro para a tela."""
    _expire()
    name = _name(raw_name)
    if n <= 0:
        raise AppError(f"“{name}” está vazio.", "Escolha outro arquivo.")
    head = read(min(n, HEAD))
    kind = sniff(head)
    if not kind:
        raise AppError(f"O Lúmen não sabe ler “{name}”.",
                       "Envie texto, PDF, docx, pptx, xlsx, odt, epub, imagem (png, jpg, webp), áudio ou vídeo.")
    if n > LIMIT[kind]:
        raise AppError(f"“{name}” é grande demais ({n / MB:.0f} MB).", f"O limite para {LABEL[kind].lower()} é {LIMIT[kind] // MB} MB.")
    base = db.MEDIA / "anexos"
    base.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(base).free < n + 500 * MB:
        raise AppError("Sem espaço em disco para guardar o anexo.", f"Libere espaço em {base.anchor}.")
    aid = uuid.uuid4().hex
    folder(aid).mkdir()
    path, left = folder(aid) / "arquivo", n - len(head)
    try:
        with open(path, "wb") as f:
            f.write(head)
            while left > 0:
                chunk = read(min(left, MB))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left > 0:
            raise AppError("O envio do anexo foi interrompido.", "Anexe o arquivo de novo.")
    except BaseException:
        shutil.rmtree(folder(aid), ignore_errors=True)
        raise
    rec = {"id": aid, "conversation_id": "", "temporary": False, "name": name, "kind": kind, "size": n, "created": db.now(),
           "at": time.monotonic(), "status": "reading", "message": "Lendo…", "text": "", "meta": {}, "doc_id": "", "gone": False}
    with _lock:
        _live[aid] = rec
    threading.Thread(target=_work, args=(rec,), name="Lumen study attachment", daemon=True).start()
    return public(rec)


def _expire():
    """Anexos que nunca foram enviados somem em 24 h."""
    limit = time.monotonic() - STAGED_HOURS * 3600
    with _lock:
        old = [a for a, r in _live.items() if not r["conversation_id"] and r["at"] < limit]
    for aid in old:
        remove(aid)


def _work(rec):
    def check():
        if rec["gone"]:
            raise Cancelled()
    try:
        text = READ[rec["kind"]](folder(rec["id"]) / "arquivo", rec, check)
        text = text.strip()
        if not text:
            raise AppError("Não encontrei texto neste anexo.", "Se for uma imagem ou um PDF escaneado, confira se o modelo de visão está instalado.")
        rec.update(text=text[:MAX_TEXT], status="ready",
                   message="Texto cortado no limite." if len(text) > MAX_TEXT else rec["meta"].get("partial", ""))
    except Cancelled:
        return
    except AppError as e:
        rec.update(status="error", message=(str(e) + " " + e.action).strip())
    except Exception as e:  # noqa: BLE001 — arquivo estranho: o anexo falha, o Lúmen não
        rec.update(status="error", message=f"Não foi possível ler este anexo ({type(e).__name__}).")
    _store(rec, final=True)


def _progress(rec, label, p):
    rec["message"] = f"{label}… {round(100 * p)}%" if p is not None else f"{label}…"


def _wait(rec, check):
    """A GPU é da aula enquanto ela é processada ou gravada; uma leitura pesada por vez."""
    while protection.foreground_busy():
        check()
        rec["message"] = "Esperando a aula em processamento terminar…"
        time.sleep(2)


# --- Leitura por tipo --------------------------------------------------------------------------------------------

def _text(path, rec, check):
    raw = path.read_bytes()
    try:
        s = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        s = raw.decode("cp1252", errors="replace")
    if rec["name"].lower().endswith((".html", ".htm")) or s.lstrip()[:15].lower().startswith(("<!doctype html", "<html")):
        return web.html_to_text(s)[1]
    return s


def _image(path, rec, check):
    from PIL import Image
    try:
        with Image.open(path) as img:  # fechado sempre: arquivo aberto impede o Windows de apagar a pasta
            if img.info.get("Lumen-Generated") == "true":
                raise AppError("Esta ilustração foi gerada por IA e não pode ser usada como fonte.")
            jpeg = _jpeg_pil(img)  # o tamanho em pixels é conferido antes de decodificar
    except AppError:
        raise
    except Exception:  # noqa: BLE001 — imagem corrompida
        raise AppError("Não foi possível abrir esta imagem.", "Confira se o arquivo não está corrompido.") from None
    (folder(rec["id"]) / "miniatura.jpg").write_bytes(jpeg)
    with _heavy:
        _wait(rec, check)
        rec["message"] = "Lendo a imagem…"
        return note_text(see(jpeg, check))


def _pdf(path, rec, check):
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        total = len(reader.pages)
        pages = [(p.extract_text() or "").strip() for p in reader.pages[:PDF_PAGES]]
    except Exception as e:  # noqa: BLE001 — PDF corrompido ou protegido por senha
        raise AppError("Não foi possível ler este PDF.", f"O arquivo pode estar protegido ({type(e).__name__}).") from None
    empty = [i for i, t in enumerate(pages) if len(t) < 20]
    scanned = empty[:VISION_PAGES]
    rec["meta"].update(pages=len(pages), scanned=len(scanned))
    if total > PDF_PAGES or len(empty) > VISION_PAGES:  # lido em parte: a ficha diz o quê
        rec["meta"]["partial"] = (f"Lidas as primeiras {PDF_PAGES} de {total} páginas. " if total > PDF_PAGES else "") + \
            (f"Das {len(empty)} páginas escaneadas, só as {VISION_PAGES} primeiras foram lidas." if len(empty) > VISION_PAGES else "")
    if scanned:  # páginas sem texto (escaneadas ou só imagem): a maior imagem de cada uma vai para a visão
        with _heavy:
            _wait(rec, check)
            for k, i in enumerate(scanned):
                check()
                _progress(rec, f"Lendo as páginas escaneadas ({k + 1} de {len(scanned)})", None)
                try:
                    images = reader.pages[i].images
                    big = max(images, key=lambda im: len(im.data), default=None)
                    if big is not None:
                        pages[i] = note_text(see(_jpeg_pil(big.image), check))
                except AppError:
                    raise
                except Exception:  # noqa: BLE001 — uma imagem que o pypdf não decodifica não para as outras
                    continue
    return "\n\n".join(f"## Página {i + 1}\n{t}" for i, t in enumerate(pages) if t)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
T = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _xml(z, name):
    if z.getinfo(name).file_size > XML_MAX:
        raise AppError("Este documento é grande demais para ler.", "Divida o arquivo em partes menores.")
    data = z.read(name)
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data:  # Office nunca usa; entidade é o jeito de inflar XML
        raise AppError("Documento com estrutura suspeita.", "O Lúmen não lê este arquivo.")
    return ET.fromstring(data)


def _num(name):
    return int(re.findall(r"\d+", name.rsplit("/", 1)[-1])[0])


def _docx(z):
    out = []
    for p in _xml(z, "word/document.xml").iter(W + "p"):
        text = "".join(t.text or "" for t in p.iter(W + "t"))
        if text.strip():
            style = p.find(f"{W}pPr/{W}pStyle")
            level = re.search(r"(?:heading|t[ií]?tulo)\s*(\d)", (style.get(W + "val") or "").casefold()) if style is not None else None
            out.append(("#" * int(level[1]) + " " if level else "") + text)
    return "\n\n".join(out)


def _pptx(z):
    # ponytail: ordem pelo número do arquivo (quase sempre a da apresentação); a ordem exata está em presentation.xml
    out = []
    for k, name in enumerate(sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_num), 1):
        lines = ["".join(t.text or "" for t in p.iter(A + "t")) for p in _xml(z, name).iter(A + "p")]
        out.append(f"## Slide {k}\n" + "\n".join(x for x in lines if x.strip()))
    return "\n\n".join(out)


def _xlsx(z):
    shared = ["".join(t.text or "" for t in si.iter(X + "t")) for si in _xml(z, "xl/sharedStrings.xml").iter(X + "si")] \
        if "xl/sharedStrings.xml" in z.namelist() else []
    names = [s.get("name") for s in _xml(z, "xl/workbook.xml").iter(X + "sheet")]
    out = []
    for k, name in enumerate(sorted((n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=_num)):
        rows = []
        for row in _xml(z, name).iter(X + "row"):
            cells = []
            for c in row.iter(X + "c"):
                v = c.find(X + "v")
                if c.get("t") == "s" and v is not None and v.text and v.text.isdigit():
                    cells.append(shared[int(v.text)] if int(v.text) < len(shared) else "")
                elif c.get("t") == "inlineStr":
                    cells.append("".join(t.text or "" for t in c.iter(X + "t")))
                else:
                    cells.append(v.text or "" if v is not None else "")
            if any(x.strip() for x in cells):
                rows.append(" | ".join(cells))
            if len(rows) >= 2000:
                break
        out.append(f"## {names[k] if k < len(names) else f'Planilha {k + 1}'}\n" + "\n".join(rows))
    return "\n\n".join(out)


def _odf(z):
    out = []
    for el in _xml(z, "content.xml").iter():
        if el.tag in (T + "h", T + "p"):
            text = "".join(el.itertext()).strip()
            if text:
                out.append(("# " if el.tag == T + "h" else "") + text)
    return "\n\n".join(out)


def _epub(z):
    C, O = "{urn:oasis:names:tc:opendocument:xmlns:container}", "{http://www.idpf.org/2007/opf}"
    opf_path = _xml(z, "META-INF/container.xml").find(f".//{C}rootfile").get("full-path")
    opf, base = _xml(z, opf_path), posixpath.dirname(opf_path)
    items = {i.get("id"): i.get("href") for i in opf.iter(O + "item")}
    out = []
    for ref in opf.iter(O + "itemref"):
        href = items.get(ref.get("idref"))
        if href:
            raw = z.read(posixpath.normpath(posixpath.join(base, urllib.parse.unquote(href))))
            out.append(web.html_to_text(raw.decode("utf-8", errors="replace"))[1])
    return "\n\n".join(out)


def _office(path, rec, check):
    try:
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist()) > ZIP_TOTAL:
                raise AppError("Este documento se expande demais para ler.", "O Lúmen não lê este arquivo.")
            names = set(z.namelist())
            mime = z.read("mimetype")[:80] if "mimetype" in names else b""
            for test, fn in ((lambda: "word/document.xml" in names, _docx), (lambda: any(n.startswith("ppt/slides/") for n in names), _pptx),
                             (lambda: "xl/workbook.xml" in names, _xlsx), (lambda: mime.startswith(b"application/epub+zip"), _epub),
                             (lambda: mime.startswith(b"application/vnd.oasis.opendocument.") and "content.xml" in names, _odf)):
                if test():
                    rec["meta"]["format"] = fn.__name__.lstrip("_")
                    return fn(z)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, AttributeError, ValueError, IndexError):
        raise AppError("Não foi possível ler este documento.", "O arquivo pode estar corrompido.") from None
    raise AppError("Este arquivo zip não é um documento que o Lúmen sabe ler.", "Use docx, pptx, xlsx, odt ou epub.")


def _media(path, rec, check):
    from .. import store, transcribe, vision
    name = transcribe.pick(store.load_config()["quality"])[1]["name"]
    if not transcribe.downloaded(name):
        raise AppError("O modelo de transcrição ainda não foi baixado.", "Baixe-o em Ajustes → Transcrição.")
    with _heavy:
        _wait(rec, check)
        tr = transcribe.transcribe(path, name, lambda p, eta=None: _progress(rec, "Transcrevendo", p), check, second=False,
                                   release=llm.release_vram)
        lines = [(s["start"], s["text"]) for s in tr["segments"]]
        rec["meta"]["duration"] = round(tr["duration"])
        if rec["kind"] == "video" and vision.ready(vision.MODEL):  # quadros-chave pela visão, como nas aulas
            shots = vision.Shots(folder(rec["id"]) / "telas")
            vision.extract(path, shots, vision.MODEL, check, lambda msg, p=None: _progress(rec, "Lendo a tela do vídeo", p),
                           num_ctx=providers.window(vision.MODEL))  # a janela do chat: o modelo não recarrega (D38)
            seen = vision.screen_lines(vision.select(shots.items))
            rec["meta"]["screens"] = len(seen)
            lines += seen
    lines.sort(key=lambda x: x[0] or 0)
    return "\n".join(f"[{llm.fmt_time(t or 0)}] {line}" for t, line in lines)


READ = {"text": _text, "pdf": _pdf, "office": _office, "image": _image, "audio": _media, "video": _media}


# --- Conversa ------------------------------------------------------------------------------------------------------

COLS = ("id", "conversation_id", "name", "kind", "size", "created", "status", "message", "text", "meta", "doc_id")


def _store(rec, final=False):
    """Grava no banco o anexo de uma conversa salva (os outros ficam na memória). Terminada a leitura, sai da memória."""
    with _lock:
        if rec["gone"]:
            return
        saved = rec["conversation_id"] and not rec["temporary"]
        if saved:
            with db.tx() as c:
                c.execute(f"INSERT OR REPLACE INTO attachments({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                          tuple(db.dumps(rec[k]) if k == "meta" else rec[k] for k in COLS))
            if final or rec["status"] != "reading":
                _live.pop(rec["id"], None)


def claim(ids, cid, temporary):
    """Liga à conversa os anexos enviados com a pergunta. Devolve os registros (os de outra conversa ficam de fora)."""
    out = []
    taken = sum(not r["meta"].get("generated") for r in listing(cid))
    for aid in [i for i in ids if isinstance(i, str)][:MAX_PER_CONV]:
        with _lock:
            rec = _live.get(aid)
            if not rec or rec["conversation_id"] or taken >= MAX_PER_CONV:
                continue
            rec.update(conversation_id=cid, temporary=temporary)
        taken += 1
        _store(rec)
        out.append(rec)
    return out


def _row(r):
    return {**r, "meta": db.loads(r["meta"], {}), "temporary": False, "gone": False}


def listing(cid):
    """Os anexos de uma conversa, na ordem em que chegaram."""
    with _lock:
        live = {a: r for a, r in _live.items() if r["conversation_id"] == cid}
    rows = [_row(r) for r in db.rows("SELECT * FROM attachments WHERE conversation_id = ? ORDER BY created", cid)]
    return [live.pop(r["id"], r) for r in rows] + list(live.values())


def get(aid):
    with _lock:
        rec = _live.get(aid)
    if rec:
        return rec
    row = db.one("SELECT * FROM attachments WHERE id = ?", str(aid))
    if not row:
        raise AppError("Anexo não encontrado.", "Ele pode ter sido apagado com a conversa.")
    return _row(row)


def pick(rec, question, n=TAKE):
    """Os trechos do anexo mais ligados à pergunta (por palavras), na ordem do arquivo. Anexo curto vai inteiro."""
    parts = index.chunks(rec["text"])
    chosen = range(len(parts))
    if len(parts) > n:
        q = set(vault.tokens(question))
        best = sorted(range(len(parts)), key=lambda i: (-len(q & set(vault.tokens(parts[i][0] + " " + parts[i][1]))), i))
        chosen = sorted(best[:n])
    return [{"id": f"{rec['id']}:{i}", "heading": parts[i][0], "text": parts[i][1]} for i in chosen]


def item(rec, question):
    """A fonte S# do anexo para a resposta."""
    if rec["meta"].get("generated"):
        raise AppError("Um arquivo gerado por IA não é fonte nem evidência.")
    return {"id": "anexo:" + rec["id"], "source": "anexo", "title": rec["name"], "path": f"Anexo · {LABEL[rec['kind']]}",
            "author": "user", "chunks": pick(rec, question), "take": TAKE, "images": ["a=" + rec["id"]] if rec["kind"] == "image" else []}


def text(doc_ref):
    """O texto inteiro de um anexo (read_document numa fonte S# de anexo)."""
    rec = get(str(doc_ref).removeprefix("anexo:"))
    if rec["meta"].get("generated"):
        raise AppError("Um arquivo gerado por IA não é fonte nem evidência.")
    return rec["text"]


def remove(aid):
    """Tira um anexo que ainda não foi enviado."""
    with _lock:
        rec = _live.get(aid)
        if not rec or rec["conversation_id"]:  # só um id conhecido chega a virar caminho de pasta
            raise AppError("Este anexo já faz parte da conversa.", "Ele é apagado junto com a conversa.")
        rec["gone"] = True
        _live.pop(aid, None)
    shutil.rmtree(folder(rec["id"]), ignore_errors=True)
    return {"ok": True}


def drop(cids=None):
    """Apaga os anexos das conversas (todas, com None): registros e arquivos. Os documentos já indexados ficam."""
    with _lock:
        gone = [r for r in _live.values() if r["conversation_id"] and (cids is None or r["conversation_id"] in cids)]
        for r in gone:
            r["gone"] = True
            _live.pop(r["id"], None)
    ids = [r["id"] for r in gone]
    with db.tx() as c:
        if cids is None:
            ids += [r[0] for r in c.execute("SELECT id FROM attachments").fetchall()]
            c.execute("DELETE FROM attachments")
        else:
            for cid in cids:
                ids += [r[0] for r in c.execute("SELECT id FROM attachments WHERE conversation_id = ?", (cid,)).fetchall()]
                c.execute("DELETE FROM attachments WHERE conversation_id = ?", (cid,))
    for aid in set(ids):
        shutil.rmtree(folder(aid), ignore_errors=True)
    return len(set(ids))


_swept = []


def sweep():
    """Uma vez por execução: apaga as pastas de anexos sem conversa salva (de antes de fechar o Lúmen)."""
    if _swept:
        return
    _swept.append(1)
    base = db.MEDIA / "anexos"
    keep = {r["id"] for r in db.rows("SELECT id FROM attachments")}
    with _lock:
        keep |= set(_live)
        live = set(_live)
    # leitura que o Lúmen fechado interrompeu: a ficha avisa, em vez de ficar em "Lendo…" e a IA nunca ver o anexo
    with db.tx() as c:
        for aid in [r[0] for r in c.execute("SELECT id FROM attachments WHERE status = 'reading'").fetchall() if r[0] not in live]:
            c.execute("UPDATE attachments SET status = 'error', message = ? WHERE id = ?",
                      ("A leitura foi interrompida quando o Lúmen fechou. Anexe o arquivo de novo.", aid))
    for p in base.iterdir() if base.is_dir() else []:
        if p.is_dir() and p.name not in keep:
            shutil.rmtree(p, ignore_errors=True)


def add_to_index(aid):
    """Guarda o texto do anexo no índice (origem "arquivos"), para as próximas conversas. O arquivo continua sendo
    apagado com a conversa; o documento indexado fica até ser tirado do índice."""
    rec = get(aid)
    if rec["meta"].get("generated"):
        raise AppError("Um arquivo gerado por IA não pode ser adicionado como fonte.")
    if rec["status"] != "ready":
        raise AppError("O anexo ainda não foi lido.", "Espere terminar e tente de novo.")
    stem = rec["name"].rsplit(".", 1)[0] if "." in rec["name"] else rec["name"]
    did = index.upsert(Doc(source="files", source_id="anexo:" + rec["id"], title=stem, text=rec["text"],
                           path=f"Anexo · {rec['name']}", kind=rec["kind"], author="user", updated=rec["created"],
                           meta={"attachment": rec["id"]}))
    rec["doc_id"] = did
    if rec["conversation_id"] and not rec["temporary"]:
        with db.tx() as c:
            c.execute("UPDATE attachments SET doc_id = ? WHERE id = ?", (did, rec["id"]))
    index.request()  # o trabalhador calcula os vetores
    return public(rec)


# --- /tela ---------------------------------------------------------------------------------------------------------

def screen(check):
    """A janela que o estudante usava antes do Lúmen, lida pela visão local. Nada vai para o disco: a imagem fica só na
    memória enquanto é lida. Devolve (rótulo da janela, texto)."""
    from .. import vision
    jpeg, label = vision.window_jpeg()
    return label, note_text(see(jpeg, check))
