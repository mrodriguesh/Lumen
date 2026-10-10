"""Fontes de vídeo: arquivo local, YouTube (link + transcrição fornecida pelo usuário) e Telegram (arquivo salvo)."""
import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import av

from . import AppError

# Somente formatos testados (ver tests/ e docs/DECISOES.md).
MEDIA = {
    ".mp4": "MP4 (H.264/AAC)", ".mkv": "MKV (H.264/AAC)", ".webm": "WebM (VP9/Opus)",
    ".mov": "MOV (H.264/AAC)", ".mp3": "MP3", ".m4a": "M4A (AAC)", ".wav": "WAV (PCM)",
}
CAPTIONS = (".srt", ".vtt", ".txt")

STATUS = {
    "recording": ("compativel", "Compatível"),
    "file": ("compativel", "Compatível"),
    "youtube": ("limitado", "Compatível com limitações"),
    "telegram": ("manual", "Requer importação manual"),
}


def probe(path):
    p = Path(path)
    if not p.is_file():
        raise AppError("Arquivo não encontrado.", "Escolha o arquivo novamente.")
    if p.suffix.lower() not in MEDIA:
        raise AppError(f"O formato “{p.suffix or 'sem extensão'}” não é suportado.",
                       "Use um destes formatos: " + ", ".join(MEDIA) + ".")
    try:
        with av.open(str(p)) as c:
            audio = next((s for s in c.streams if s.type == "audio"), None)
            if audio is None:
                raise AppError("Este arquivo não tem faixa de áudio.", "Escolha um arquivo com som.")
            codec = audio.codec_context.name
            next(c.decode(audio), None)  # garante que o codec existe e decodifica
            duration = c.duration / 1_000_000 if c.duration else None
    except av.error.FFmpegError:
        raise AppError("Não foi possível ler o áudio deste arquivo (corrompido ou codec ausente).",
                       "Converta para MP4 (H.264/AAC) ou MP3 e tente de novo.") from None
    return {"name": p.name, "format": MEDIA[p.suffix.lower()], "codec": codec,
            "duration": duration, "size": p.stat().st_size}


def file_key(path):
    """Identifica o arquivo pelo conteúdo (tamanho + primeiro MB), não pelo nome."""
    p = Path(path)
    with open(p, "rb") as f:
        head = f.read(1 << 20)
    return "file:" + hashlib.sha256(str(p.stat().st_size).encode() + head).hexdigest()[:32]


# --- YouTube ---------------------------------------------------------------

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
             "youtu.be", "www.youtube-nocookie.com"}


def youtube_id(url):
    url = (url or "").strip()
    if "://" not in url:
        url = "https://" + url
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    parts = [x for x in u.path.split("/") if x]
    vid = ""
    if u.scheme in ("http", "https") and host in _YT_HOSTS:
        if host == "youtu.be":
            vid = parts[0] if parts else ""
        elif parts[:1] == ["watch"]:
            vid = urllib.parse.parse_qs(u.query).get("v", [""])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
            vid = parts[1]
    if not _YT_ID.match(vid):
        raise AppError("Isso não parece um link de vídeo do YouTube.",
                       "Cole um link como https://www.youtube.com/watch?v=…")
    return vid


def youtube_url(vid, seconds=None):
    return f"https://www.youtube.com/watch?v={vid}" + (f"&t={int(seconds)}s" if seconds is not None else "")


def youtube_meta(vid):
    """Título e canal pelo oEmbed público oficial. Vídeo privado/indisponível → {}."""
    q = urllib.parse.urlencode({"url": youtube_url(vid), "format": "json"})
    try:
        with urllib.request.urlopen(f"https://www.youtube.com/oembed?{q}", timeout=8) as r:
            d = json.load(r)
        return {"title": str(d.get("title", ""))[:300], "author": str(d.get("author_name", ""))[:200]}
    except (OSError, ValueError):
        return {}


# --- Legendas / transcrições importadas -----------------------------------

_T = r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CUE = re.compile(_T + r"\s*-->\s*" + _T)
_LINE_TS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})(?:\s+(.*))?$")


def _secs(h, m, s, ms=None):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int((ms or "0").ljust(3, "0")) / 1000


def parse_captions(text):
    """SRT, WebVTT ou texto copiado do painel “Mostrar transcrição” do YouTube → segmentos."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    segs = []
    if _CUE.search(text):
        prev = set()
        for block in re.split(r"\n\s*\n", text):
            lines = block.strip().split("\n")
            for i, line in enumerate(lines):
                m = _CUE.search(line)
                if not m:
                    continue
                g = m.groups()
                body = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in lines[i + 1:]]
                body = [x for x in body if x]
                # legendas automáticas repetem a linha anterior a cada cue
                new = [x for x in body if x not in prev]
                prev = set(body)
                if new:
                    segs.append({"start": _secs(*g[:4]), "end": _secs(*g[4:]), "text": " ".join(new)})
                break
    else:
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = _LINE_TS.match(line)
            if m:
                segs.append({"start": _secs(*m.groups()[:3]), "end": None, "text": (m.group(4) or "").strip()})
            elif segs:
                segs[-1]["text"] = (segs[-1]["text"] + " " + line).strip()
            else:
                segs.append({"start": None, "end": None, "text": line})
        segs = [s for s in segs if s["text"]]
        for a, b in zip(segs, segs[1:]):
            a["end"] = b["start"]
    if not segs:
        raise AppError("Nenhum texto foi encontrado na transcrição.",
                       "Confira se o arquivo é .srt, .vtt ou o texto copiado do YouTube.")
    return segs


LABELS = {"file": "Arquivo local", "telegram": "Telegram (arquivo importado)",
          "recording": "Gravação do áudio do PC"}


def lesson_link(url):
    """Referência opcional: YouTube normalizado para o player do Notion; outros links ficam como texto."""
    url = (url or "").strip()
    if not url:
        return None
    try:
        u = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
        host = u.hostname or ""
    except ValueError:
        raise AppError("O link da aula não parece válido.", "Confira o endereço ou deixe em branco.") from None
    if (len(url) > 2000 or any(c.isspace() for c in url) or u.username or u.password
            or u.scheme not in ("http", "https") or "." not in host):
        raise AppError("O link da aula não parece válido.", "Cole um endereço começando com https:// ou deixe em branco.")
    if host.lower() in _YT_HOSTS:
        return youtube_url(youtube_id(u.geturl()))
    return u.geturl()


def resolve(spec):
    """Valida o pedido da interface e devolve a descrição da fonte."""
    kind = spec.get("kind")
    if kind in LABELS:
        info = probe(spec.get("path", ""))
        title = re.sub(r"^[0-9a-f]{8}_", "", Path(spec["path"]).stem)  # prefixo das cópias internas
        return {"kind": kind, "key": file_key(spec["path"]), "title": title, "label": LABELS[kind],
                "link": lesson_link(spec.get("link")),
                "path": spec["path"], "duration": info["duration"], "info": info}
    if kind == "youtube":
        vid = youtube_id(spec.get("url"))
        meta = youtube_meta(vid)
        src = {"kind": kind, "key": "yt:" + vid, "yt_id": vid, "title": meta.get("title") or f"Vídeo {vid}",
               "author": meta.get("author"), "label": "YouTube", "link": youtube_url(vid),
               "path": None, "duration": None, "info": None, "captions": None}
        if (spec.get("captions") or "").strip():
            src["captions"] = parse_captions(spec["captions"])
            ends = [s["end"] or s["start"] for s in src["captions"] if (s["end"] or s["start"]) is not None]
            src["duration"] = max(ends) if ends else None
        elif spec.get("path"):
            src["info"] = probe(spec["path"])
            src["path"], src["duration"] = spec["path"], src["info"]["duration"]
        return src
    raise AppError("Fonte desconhecida.", "Escolha arquivo local, YouTube ou Telegram.")
