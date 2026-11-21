"""Imagens das notas (Study AI 2.0, fase 4): ![[x.png]] e ![](x.png) no cofre, e as imagens enviadas ao Notion.

Na sincronização, cada imagem é identificada pelo hash do conteúdo (a mesma imagem em duas notas é lida uma vez) e
copiada como JPEG para MEDIA/imagens/<hash>.jpg. As do Notion são baixadas ali porque o endereço delas expira em cerca
de 1 h. Uma imagem já lida entra no texto da nota, no lugar onde aparece ("[Imagem “x.png”: …]"), e vira trecho da
seção dela como qualquer parágrafo. As que faltam ficam na fila: depois de cada sincronização, o trabalhador do índice
lê até `performance.images_per_sync` com a visão local, cedendo a vez às aulas, e marca as notas delas para serem
relidas na sincronização seguinte. Ajuste: "Ler as imagens das notas" (search.images)."""
import hashlib
import io
import re

from .. import AppError
from . import db, providers

EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
MAX_BYTES = 25_000_000
PER_DOC = 30            # imagens por nota ou página
MAX_PIXELS = 40_000_000  # ~ 8000 × 5000: acima disto a imagem nem é decodificada (PNG minúsculo que vira GBs na RAM)
HASH = re.compile(r"[0-9a-f]{24}")


def path(h):
    return db.MEDIA / "imagens" / f"{h}.jpg"


def see(jpeg, check):
    """O que a visão local lê numa imagem (descrição e texto), com a janela do chat: o modelo de visão é o mesmo que
    responde no chat, e o Ollama o recarregaria se ela mudasse."""
    from .. import vision
    if not vision.ready(vision.MODEL):
        raise AppError(f"O modelo de visão ({vision.MODEL}) não está instalado no Ollama.", "Baixe-o em Ajustes → Assistir a tela.")
    return vision.read(jpeg, vision.MODEL, check, keep_alive="10m", manual=True, num_ctx=providers.window(vision.MODEL))


def note_text(note):
    """O que a visão leu, como texto de estudo."""
    lines = [note["titulo"]] if note["titulo"] else []
    if note["descricao"]:
        lines.append(f"O que mostra: {note['descricao']}")
    if note["texto"]:
        lines.append(f"Texto lido:\n{note['texto']}")
    return "\n".join(lines)


def jpeg(img):
    """Imagem do Pillow → JPEG de alta qualidade com no máximo a largura da visão."""
    from .. import vision
    if img.width * img.height > MAX_PIXELS:
        raise AppError("A imagem tem pixels demais para ler.", "Reduza a imagem (até cerca de 8000 × 5000).")
    img = img.convert("RGB")
    img.thumbnail((vision.WIDTH, vision.WIDTH * 4))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def register(data, name, source):
    """Guarda a imagem (os bytes do arquivo) na fila e devolve o hash; None se não for uma imagem legível."""
    if not data or len(data) > MAX_BYTES:
        return None
    if "gerada por ia" in name.casefold() or re.fullmatch(r"lumen-[0-9a-f]{32}\.png", name):
        return None
    h = hashlib.sha256(data).hexdigest()[:24]
    if db.one("SELECT 1 AS x FROM images WHERE hash = ?", h) and path(h).is_file():
        return h
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            if img.info.get("Lumen-Generated") == "true":
                return None
            out = jpeg(img)
    except Exception:  # noqa: BLE001 — formato estranho, imagem corrompida ou grande demais (o Pillow recusa)
        return None
    path(h).parent.mkdir(parents=True, exist_ok=True)
    path(h).write_bytes(out)
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO images(hash, source, name, created) VALUES (?, ?, ?, ?)", (h, source, name[:200], db.now()))
    return h


def inline(h, name):
    """O que entra no texto da nota no lugar da imagem: o que a visão leu, ou só o nome enquanto ela não leu."""
    row = db.one("SELECT state, note FROM images WHERE hash = ?", h)
    note = db.loads(row["note"], None) if row and row["state"] == "done" else None
    if not note:
        return f"[Imagem: {name}]"
    return f"[Imagem “{name}”: {note_text({**note, 'texto': note['texto'][:2000]})}]"


def read_pending(check, limit):
    """Lê até `limit` imagens da fila. Devolve quantas leu; as notas delas são relidas na próxima sincronização."""
    from .. import vision
    if not limit or not vision.ready(vision.MODEL):
        return 0
    done = []
    for row in db.rows("SELECT hash FROM images WHERE state = 'pending' ORDER BY created LIMIT ?", int(limit)):
        check()
        h, note = row["hash"], None
        try:
            note = see(path(h).read_bytes(), check)
            state = "done" if note["keep"] else "empty"
        except OSError:
            state = "missing"
        except AppError:
            break  # Ollama fora do ar ou ocupado: a fila espera a próxima rodada
        with db.tx() as c:
            c.execute("UPDATE images SET state = ?, note = ?, read = ? WHERE hash = ?", (state, db.dumps(note) if note else "", db.now(), h))
        if state == "done":
            done.append(h)
    with db.tx() as c:  # versão vazia = a próxima sincronização relê a nota, agora com a descrição no texto
        for h in done:
            c.execute("UPDATE documents SET version = '' WHERE meta LIKE ?", (f'%"{h}"%',))
    return len(done)


def drop():
    """Apaga a fila e as cópias (junto com "Documentos indexados")."""
    with db.tx() as c:
        n = c.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        c.execute("DELETE FROM images")
    folder = db.MEDIA / "imagens"
    for p in folder.glob("*.jpg") if folder.is_dir() else []:
        p.unlink(missing_ok=True)
    return n
