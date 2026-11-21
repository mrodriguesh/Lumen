"""Leitura de páginas públicas da internet, com proteção contra SSRF.

Só http/https. O nome é resolvido aqui e TODO endereço resultante precisa ser público: loopback (inclusive o próprio
servidor do Lúmen em 127.0.0.1), rede privada, link-local, multicast e reservados são recusados. A conexão vai para o
IP já conferido (sem nova resolução, contra DNS rebinding) e cada redirecionamento é validado de novo. Teto de 2 MB,
sem compressão, e o texto vira Markdown simples. Nada de cookies nem do token do Lúmen sai daqui."""
import html
import http.client
import ipaddress
import re
import socket
import ssl
import urllib.parse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from ... import AppError
from .. import db

MAX_BYTES = 2_000_000
TIMEOUT = 15
AGENT = "Mozilla/5.0 (compatible; Lumen-Study/1.0; +local study assistant)"
SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "form", "nav", "footer", "header", "aside"}
BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "main", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
         "pre", "table", "ul", "ol", "dd", "dt", "figcaption"}


def public_ips(host):
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise AppError("Não foi possível encontrar este endereço.", "Confira o link e a internet.") from None
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or ip.is_multicast or (mapped is not None and not mapped.is_global):
            raise AppError("Este endereço aponta para a rede local e foi bloqueado.",
                           "A IA só lê páginas públicas da internet.")
        ips.append(str(ip))
    if not ips:
        raise AppError("Não foi possível encontrar este endereço.")
    return ips


def check_url(url):
    if not isinstance(url, str) or len(url) > 2000:
        raise AppError("Endereço inválido.")
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise AppError("Só endereços http e https públicos podem ser abertos.")
    return parts


class _Pinned(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedPlain(http.client.HTTPConnection):
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port=port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


def _get(url, check=lambda: None, hops=4, limit=MAX_BYTES):
    for _ in range(hops + 1):
        check()
        parts = check_url(url)
        ip = public_ips(parts.hostname)[0]
        port = parts.port or (443 if parts.scheme == "https" else 80)
        conn = (_Pinned if parts.scheme == "https" else _PinnedPlain)(parts.hostname, ip, port, TIMEOUT)
        path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
        try:
            conn.request("GET", path, headers={"User-Agent": AGENT, "Accept": "text/html,text/plain,application/pdf;q=0.9,*/*;q=0.5",
                                               "Accept-Encoding": "identity", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
                url = urllib.parse.urljoin(url, r.getheader("Location"))
                continue
            data = r.read(limit + 1)
            if len(data) > limit:
                data = data[:limit]
            return r.status, r.getheader("Content-Type") or "", data, url
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            raise AppError("Não foi possível ler esta página.", f"Confira a internet ({type(e).__name__}).") from None
        finally:
            conn.close()
    raise AppError("A página redirecionou vezes demais.")


class _Text(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.out, self.skip, self.title, self.links = base, [], 0, "", []
        self._in_title, self._href, self._heading = False, None, ""
        self.main_start = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("main", "article") and self.main_start is None:
            self.main_start = len(self.out)
        if tag in BLOCK:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.out.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.out.append("- ")
        if tag == "a" and a.get("href"):
            self._href = urllib.parse.urljoin(self.base, a["href"])

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in BLOCK:
            self.out.append("\n")
        if tag == "a":
            self._href = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)
            if self._href and data.strip() and self._href.startswith("http") and len(self.links) < 60:
                self.links.append({"text": " ".join(data.split())[:120], "url": self._href})


def html_to_text(raw, base=""):
    p = _Text(base)
    p.feed(raw)
    parts = p.out[p.main_start:] if p.main_start is not None and len("".join(p.out[p.main_start:])) > 400 else p.out
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return html.unescape(p.title.strip()), text, p.links


def pdf_text(data, limit_pages=300):
    try:
        import io

        from pypdf import PdfReader
    except ImportError:
        raise AppError("A leitura de PDF não está instalada.", "Instale as dependências do Lúmen (pypdf).") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages[:limit_pages]).strip()
    except Exception as e:  # noqa: BLE001 — PDF corrompido ou protegido
        raise AppError("Não foi possível ler este PDF.", f"O arquivo pode estar protegido ({type(e).__name__}).") from None


def fetch(url, check=lambda: None, cache_days=7, *, cache=True):
    """{"url", "title", "text", "links", "cached"} de uma página pública. Usa o cache se ainda for válido."""
    check_url(url)
    hit = db.one("SELECT * FROM web_cache WHERE url = ?", url) if cache else None
    if hit and cache_days and hit["status"] == 200:
        fetched = datetime.fromisoformat(hit["fetched"])
        if datetime.now(timezone.utc) - fetched < timedelta(days=cache_days):
            return {"url": url, "title": hit["title"], "text": hit["text"], "links": [], "cached": True}
    status, ctype, data, final = _get(url, check)
    if status >= 400:
        raise AppError(f"A página respondeu com erro (HTTP {status}).", "Confira o endereço.")
    if "pdf" in ctype:
        title, text, links = final.rsplit("/", 1)[-1], pdf_text(data), []
    elif any(t in ctype for t in ("html", "xml")) or not ctype:
        charset = (re.search(r"charset=([\w-]+)", ctype) or [None, "utf-8"])[1]
        try:
            raw = data.decode(charset, errors="replace")
        except LookupError:
            raw = data.decode("utf-8", errors="replace")
        title, text, links = html_to_text(raw, final)
    elif ctype.startswith("text/") or "json" in ctype:
        title, text, links = final, data.decode("utf-8", errors="replace"), []
    else:
        raise AppError("Este tipo de arquivo não pode ser lido.", "A IA lê páginas, textos e PDFs.")
    text = text[:200_000]
    if cache:
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO web_cache(url, fetched, title, text, status) VALUES (?, ?, ?, ?, ?)",
                      (url, db.now(), title[:300], text, 200))
    return {"url": final, "title": title[:300] or final, "text": text, "links": links, "cached": False}
