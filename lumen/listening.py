"""Modo escuta: transcreve uma chamada (microfone + som do PC) e escreve o texto, ao vivo, numa página do Notion e numa
nota do Obsidian.

Cada lado tem o seu VAD (o mesmo Silero da conversa por voz) e vira falas curtas; o modelo de transcrição dos Ajustes
(transcribe.transcribe, como o "apertar para falar") transforma cada fala em texto. As falas entram primeiro num diário
local (DATA/escuta/<sessão>/falas.jsonl); o Notion e o Obsidian copiam desse diário, cada um com o seu contador. Um destino
que falha espera e retoma do ponto em que parou: nada se perde e nada se repete (um envio ao Notion sem resposta é
conferido na própria página antes de seguir). Parar fecha a captura, transcreve o que faltava e grava o fim nos dois."""
import json
import logging
import os
import queue
import tempfile
import threading
import time
import wave
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

from . import AppError, notion, obsidian, store, transcribe, vault

log = logging.getLogger("lumen")
DIR = store.DATA / "escuta"
RATE, FRAME = 48000, 512                 # captura em 48 kHz; quadros de 32 ms em 16 kHz (Silero VAD v5)
START_P, KEEP_P = 0.5, 0.35              # histerese do VAD, como na conversa por voz (study/call.py)
END_FRAMES = 22                          # ≈ 0,7 s de silêncio fecha a fala
MAX_FRAMES = 20 * 16000 // FRAME         # uma fala longa é cortada a cada ≈ 20 s (o texto aparece sem esperar o fim)
MIN_FRAMES = 12                          # falas com menos de ≈ 0,4 s de voz são ruído
PREROLL = 10                             # 320 ms antes do início da fala (a 1ª sílaba não se perde)
ECHO = 0.35                              # sem fone, o microfone ouve a outra pessoa: a mesma frase dos dois lados vale uma vez
WHO = {"mic": "Você", "system": "Chamada"}
BATCH = 50                               # blocos por envio ao Notion (o limite da API é 100)
_lock = threading.Lock()
_session = None


def clock(t):
    t = int(max(0, t))
    return f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def line(seg):
    """O texto de um trecho, igual nos dois destinos (e o que identifica o trecho na página do Notion)."""
    if seg.get("end"):
        return f"Fim da escuta · {clock(seg['t'])}"
    return f"{clock(seg['t'])} · {WHO.get(seg['who'], seg['who'])}  {seg['text']}"


class Segmenter:
    """Quadros de 32 ms → falas (t0, áudio). t0 em segundos desde o início da escuta."""

    def __init__(self, vad):
        self.vad, self.pre, self.buf, self.voiced, self.quiet, self.t0 = vad, deque(maxlen=PREROLL), None, 0, 0, 0.0

    def feed(self, frame, t):
        p = self.vad.prob(frame)
        if self.buf is None:
            self.pre.append(frame)
            if p >= START_P:
                self.buf, self.voiced, self.quiet = list(self.pre), 1, 0
                self.t0 = max(0.0, t - len(self.buf) * FRAME / 16000)
                self.pre.clear()
            return None
        self.buf.append(frame)
        if p >= KEEP_P:
            self.voiced, self.quiet = self.voiced + 1, 0
        else:
            self.quiet += 1
        if self.quiet >= END_FRAMES:
            return self._emit(keep=False)
        if len(self.buf) >= MAX_FRAMES:
            return self._emit(keep=True)
        return None

    def flush(self):
        return self._emit(keep=False) if self.buf is not None else None

    def _emit(self, keep):
        buf, voiced, t0 = self.buf, self.voiced, self.t0
        if keep:  # a fala continua: o próximo pedaço começa onde este parou
            self.buf, self.voiced, self.quiet, self.t0 = [], 0, 0, t0 + len(buf) * FRAME / 16000
        else:
            self.buf = None
        return (t0, np.concatenate(buf)) if voiced >= MIN_FRAMES else None


# --- Destinos ---------------------------------------------------------------------------------------------------------

class Sink:
    """Copia o diário para um destino, do ponto em que parou. `push(batch)` grava e devolve quantos trechos ficaram."""
    name = ""

    def __init__(self, s):
        self.s, self.sent, self.error, self.wake, self.done = s, 0, None, threading.Event(), False

    def view(self):
        total = len(self.s.segments)
        pending = total - self.sent
        state = "setup" if self.error and getattr(self.error, "setup", False) else "error" if self.error \
            else "done" if self.done else "sending" if pending > 0 else "live"
        out = {"state": state, "pending": pending, "message": "" if not self.error else
               " ".join(x for x in (str(self.error), getattr(self.error, "action", "")) if x)}
        return {**out, **self.where()}

    def where(self):
        return {}

    def prepare(self):
        """Cria a página ou a nota já no início, para a pessoa poder abri-la antes da primeira fala."""

    def run(self):
        wait, ready = 1.0, False
        while True:
            if not ready:
                try:
                    self.prepare()
                    ready, self.error, wait = True, None, 1.0
                except Exception as e:  # noqa: BLE001 — sem destino ainda: as falas esperam no diário
                    self.error = e if isinstance(e, AppError) else AppError("Não foi possível gravar agora.", "O Lúmen tenta de novo sozinho.")
                    wait = min(wait * 2, 30.0)
            self.wake.wait(timeout=wait if self.error else 1.0)
            self.wake.clear()
            while ready and self.sent < len(self.s.segments):
                try:
                    batch = self.s.segments[self.sent:self.sent + BATCH]
                    self.sent += self.push(batch)
                    self.error, wait = None, 1.0
                    self.s.save()
                except Exception as e:  # noqa: BLE001 — o destino volta sozinho; o diário guarda tudo até lá
                    self.error = e if isinstance(e, AppError) else AppError("Não foi possível gravar agora.", "O Lúmen tenta de novo sozinho.")
                    log.warning("escuta: %s: %s", self.name, type(e).__name__)
                    wait = min(wait * 2, 30.0)
                    break
            if self.s.closed and self.sent >= len(self.s.segments):
                self.done = True
                self.s.save()
                return


def _setup(message, action):
    e = AppError(message, action)
    e.setup = True
    return e


class ObsidianSink(Sink):
    name = "obsidian"

    def __init__(self, s, path=None):
        super().__init__(s)
        self.path = Path(path) if path else None

    def where(self):
        return {"path": str(self.path) if self.path else ""}

    def prepare(self):
        self._note()

    def _note(self):
        if self.path:
            return self.path
        try:
            root = vault.check(store.load_config()["obsidian_vault"])
        except AppError as e:
            raise _setup(str(e), e.action) from None
        folder = vault.inside(root, "Chamadas")
        folder.mkdir(parents=True, exist_ok=True)
        stem = obsidian.clean(self.s.begun.strftime("%Y-%m-%d %H-%M") + " Chamada")
        path, n = folder / (stem + ".md"), 2
        while path.exists():
            path, n = folder / f"{stem} {n}.md", n + 1
        head = (f"---\ntype: call-transcript\nsource: lumen-escuta\ncreated: {self.s.begun.isoformat(timespec='minutes')}\n---\n\n"
                f"# {self.s.title}\n\n*Transcrição ao vivo pelo Lúmen: microfone e som do PC.*\n\n")
        with open(path, "x", encoding="utf-8", newline="\n") as f:  # "x": nunca sobrescreve uma nota que já existe
            f.write(head)
        self.path = path
        self.s.save()
        return path

    def push(self, batch):
        text = "".join(("\n---\n\n*" + line(x) + ".*\n") if x.get("end") else
                       f"**{clock(x['t'])} · {WHO.get(x['who'], x['who'])}** {x['text']}\n\n" for x in batch)
        with open(self._note(), "a", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        return len(batch)


def _plain(block):
    data = block.get(block.get("type"), {}) or {}
    return "".join(t.get("plain_text") or t.get("text", {}).get("content", "") for t in data.get("rich_text") or [])


class NotionSink(Sink):
    name = "notion"

    def __init__(self, s, page=None, url=""):
        super().__init__(s)
        self.page, self.url, self.unsure = page, url, False

    def where(self):
        return {"url": self.url}

    def prepare(self):
        self._page(*self._token())

    def _token(self):
        token, root = store.get_token(), store.load_config()["root_page_id"]
        if not token or not root:
            raise _setup("O Notion ainda não foi conectado.", "Conecte o Notion e escolha a página raiz em Integrações.")
        return token, root

    def _page(self, token, root):
        if self.page:
            return self.page
        parent = container(token, root)
        body = {"parent": {"page_id": parent}, "icon": {"type": "emoji", "emoji": "🎧"},
                "properties": {"title": {"title": notion._rt(self.s.title)}},
                "children": [notion._b("paragraph", notion._rt("Transcrição ao vivo pelo Lúmen: microfone e som do PC.",
                                                               italic=True, color="gray"))]}
        try:
            made = notion.request("POST", "/pages", token, body, once=True)
        except notion.Unconfirmed:  # a página pode ter sido criada: procura pelo título (único, com os segundos)
            made = next(({"id": b["id"]} for b in notion.all_children(token, parent)
                         if b.get("type") == "child_page" and b["child_page"].get("title") == self.s.title), None)
            if not made:
                raise
        self.page = made["id"]
        self.url = made.get("url") or "https://www.notion.so/" + self.page.replace("-", "")
        self.s.save()
        return self.page

    def push(self, batch):
        token, root = self._token()
        page = self._page(token, root)
        if self.unsure:  # o último envio saiu sem resposta: só segue depois de ver o que a página já tem
            have = {_plain(b) for b in notion.all_children(token, page)}
            landed = 0
            while landed < len(batch) and line(batch[landed]) in have:
                landed += 1
            self.unsure = False
            if landed:
                return landed
        blocks = [notion._b("paragraph", notion._rt(line(x), italic=True, color="gray")) if x.get("end") else
                  notion._b("paragraph", notion._rt(f"{clock(x['t'])} · {WHO.get(x['who'], x['who'])}", bold=True, color="gray")
                            + notion._rt("  " + x["text"])) for x in batch]
        try:
            notion.request("PATCH", f"/blocks/{page}/children", token, {"children": blocks})
        except notion.Unconfirmed:
            self.unsure = True
            raise
        return len(batch)


def _hidden_file():
    return DIR / "notion.json"


def container_id():
    """A página “Chamadas” do Lúmen dentro da raiz: a lista de cursos não a mostra."""
    try:
        return json.loads(_hidden_file().read_text("utf-8")).get("container") or ""
    except (OSError, ValueError):
        return ""


def container(token, root):
    cid = container_id()
    if cid:
        try:
            if not notion.request("GET", f"/pages/{cid}", token).get("in_trash"):
                return cid
        except AppError as e:
            if getattr(e, "status", None) not in (404,):
                raise
    try:
        cid = notion.request("POST", "/pages", token, {"parent": {"page_id": root}, "icon": {"type": "emoji", "emoji": "🎧"},
                                                       "properties": {"title": {"title": notion._rt("Chamadas")}}}, once=True)["id"]
    except notion.Unconfirmed:
        cid = next((b["id"] for b in notion.all_children(token, root)
                    if b.get("type") == "child_page" and b["child_page"].get("title") == "Chamadas"), None)
        if not cid:
            raise
    DIR.mkdir(parents=True, exist_ok=True)
    _hidden_file().write_text(json.dumps({"container": cid}), "utf-8")
    return cid


# --- Sessão -----------------------------------------------------------------------------------------------------------

def _wav_text(audio, language):
    """Uma fala → texto, pelo modelo dos Ajustes (o mesmo caminho do “apertar para falar”)."""
    from . import llm
    name = transcribe.pick(store.load_config()["quality"])[1]["name"]
    with tempfile.TemporaryDirectory(prefix="lumen-escuta-") as d:
        path = Path(d) / "fala.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        out = transcribe.transcribe(path, name, lambda *a: None, lambda: None, second=False, release=llm.release_vram,
                                    language=language)
    text = " ".join(str(s.get("text") or "").strip() for s in out.get("segments") or []).strip()
    return text, out.get("language")


def _open_mic():
    from . import loopback
    return loopback.microphone(RATE, 1)


def _open_system():
    from . import record
    return record._open_loopback().recorder(samplerate=RATE, channels=2)


class Session:
    def __init__(self, sources=None, transcriber=None, vad_factory=None):
        self.begun = datetime.now()
        self.id = self.begun.strftime("%Y%m%d-%H%M%S")
        self.dir = DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.title = "Chamada · " + self.begun.strftime("%d/%m/%Y %H:%M:%S")
        self.t0 = time.monotonic()
        self.stop_ev, self.closed, self.error, self.language = threading.Event(), False, None, None
        self.save_lock = threading.Lock()
        self.segments, self.queue = [], queue.Queue()
        self.levels, self.sources = {"mic": 0.0, "system": 0.0}, {"mic": "starting", "system": "starting"}
        self.ended_at = None
        self._sources = sources or {"mic": _open_mic, "system": _open_system}
        self._text = transcriber or _wav_text
        self._vad = vad_factory
        self.sinks = {"notion": NotionSink(self), "obsidian": ObsidianSink(self)}
        self.threads = []

    def now(self):
        return time.monotonic() - self.t0

    def start(self):
        for who, opener in self._sources.items():
            self._spawn(self._capture, who, opener)
        self._spawn(self._transcribe)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and "starting" in self.sources.values():
            time.sleep(.05)
        if not any(v == "on" for v in self.sources.values()):
            self.stop()  # nada foi criado no Notion nem no Obsidian: os destinos só começam depois daqui
            raise AppError("Não foi possível abrir o microfone nem o som do PC.",
                           "Confira o microfone e a saída de áudio nas configurações de som do Windows.")
        for sink in self.sinks.values():
            self._spawn(sink.run)
        self.save()

    def _spawn(self, fn, *args):
        t = threading.Thread(target=fn, args=args, daemon=True, name="Lumen escuta " + fn.__name__.strip("_"))
        self.threads.append(t)
        t.start()

    def _capture(self, who, opener):
        try:
            if os.name == "nt":  # o COM do áudio é por thread (ver record._open_loopback)
                import soundcard  # noqa: F401
                import ctypes
                ctypes.windll.ole32.CoInitializeEx(None, 0)
            if self._vad:
                vad = self._vad()
            else:
                from .study import call
                vad = call.load_vad()
            seg, buf = Segmenter(vad), np.zeros(0, np.float32)
            with opener() as rec:
                self.sources[who] = "on"
                while not self.stop_ev.is_set():
                    raw = rec.record(numframes=FRAME * 3)
                    a = np.asarray(raw, np.float32)
                    a = a.mean(axis=1) if a.ndim > 1 else a.reshape(-1)
                    n = len(a) // 3 * 3
                    if not n:
                        continue
                    buf = np.concatenate((buf, a[:n].reshape(-1, 3).mean(axis=1)))
                    while buf.size >= FRAME:
                        frame, buf = buf[:FRAME], buf[FRAME:]
                        self.levels[who] = float(np.abs(frame).max())
                        utt = seg.feed(frame, self.now())
                        if utt:
                            self.queue.put((who, *utt))
                last = seg.flush()
                if last:
                    self.queue.put((who, *last))
        except Exception as e:  # noqa: BLE001 — um lado sem som (sem microfone, sem saída) não derruba o outro
            log.warning("escuta: %s: %s: %s", who, type(e).__name__, e)
            self.sources[who] = "off"
        finally:
            self.levels[who] = 0.0
            if self.sources[who] == "on":
                self.sources[who] = "done"
            self.queue.put((who, None, None))  # este lado terminou

    def _transcribe(self):
        open_sides, stopped = set(self._sources), None
        while open_sides:
            try:
                who, t0, audio = self.queue.get(timeout=.5)
            except queue.Empty:
                stopped = stopped or (time.monotonic() if self.stop_ev.is_set() else None)
                if stopped and time.monotonic() - stopped > 4:
                    break  # o som do PC em silêncio pode prender a leitura: parar não espera por ele
                continue
            if audio is None:
                open_sides.discard(who)
                continue
            try:
                text, lang = self._text(audio, self.language)
            except AppError as e:
                self.error = e
                continue
            except Exception as e:  # noqa: BLE001 — uma fala perdida não para a escuta
                log.warning("escuta: transcrição: %s", type(e).__name__)
                continue
            if lang and not self.language and len(audio) >= 3 * 16000:
                self.language = lang  # a primeira fala longa decide o idioma; falas curtas detectam mal
            if text and not self._echo(who, t0, text):
                self._add({"who": who, "t": round(t0, 1), "text": text})
        self.ended_at = self.now()
        self._add({"end": True, "t": round(self.ended_at, 1)})
        self.closed = True
        for sink in self.sinks.values():
            sink.wake.set()

    def _echo(self, who, t0, text):
        return any(x.get("who") not in (None, who) and abs(x["t"] - t0) < 8 and transcribe.disagreement(text, x["text"]) < ECHO
                   for x in self.segments[-10:])

    def _add(self, seg):
        seg["n"] = len(self.segments)
        with open(self.dir / "falas.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
        self.segments.append(seg)
        for sink in self.sinks.values():
            sink.wake.set()

    def stop(self):
        self.stop_ev.set()

    def save(self):
        n, o = self.sinks["notion"], self.sinks["obsidian"]
        data = {"id": self.id, "title": self.title, "notion": {"page": n.page, "url": n.url, "sent": n.sent},
                "obsidian": {"path": str(o.path or ""), "sent": o.sent}, "closed": self.closed}
        with self.save_lock:  # os dois destinos salvam o próprio contador; no Windows, dois os.replace juntos falham
            tmp = self.dir / "sessao.json.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            os.replace(tmp, self.dir / "sessao.json")

    def finished(self):
        return self.closed and all(s.done for s in self.sinks.values())

    def view(self):
        live = not self.stop_ev.is_set()
        phase = "live" if live else "done" if self.finished() else "finishing"
        lines = [{"n": x["n"], "t": clock(x["t"]), "who": WHO.get(x["who"], x["who"]), "text": x["text"]}
                 for x in self.segments if not x.get("end")][-8:]
        return {"active": live, "phase": phase, "seconds": round(self.ended_at if self.ended_at is not None else self.now(), 1),
                "levels": {k: round(v, 3) for k, v in self.levels.items()}, "sources": dict(self.sources),
                "lines": lines, "count": sum(1 for x in self.segments if not x.get("end")), "title": self.title,
                "error": " ".join(x for x in (str(self.error), self.error.action) if x) if self.error else "",
                "notion": self.sinks["notion"].view(), "obsidian": self.sinks["obsidian"].view()}


# --- API --------------------------------------------------------------------------------------------------------------

def start():
    global _session
    with _lock:
        if _session and not _session.stop_ev.is_set():
            raise AppError("O modo escuta já está ligado.")
        name = transcribe.pick(store.load_config()["quality"])[1]["name"]
        if not transcribe.downloaded(name):
            raise AppError("O modelo de transcrição ainda não foi baixado.", "Abra Ajustes → Transcrição e baixe o modelo.")
        s = Session()
        s.start()
        _session = s
    return view()


def stop():
    with _lock:
        if _session:
            _session.stop()
    return view()


def view():
    s = _session
    if not s:
        return {"active": False, "phase": "idle"}
    return s.view()


def brief():
    """Para a barra flutuante (lida a cada segundo): só se está ligado e há quanto tempo."""
    s = _session
    if not s:
        return {"active": False, "phase": "idle"}
    v = s.view()
    return {"active": v["active"], "phase": v["phase"], "seconds": v["seconds"]}


def open_target(target):
    s = _session
    if not s:
        raise AppError("Nenhuma escuta para abrir.")
    if target == "obsidian":
        path = s.sinks["obsidian"].path
        if not path or not path.exists():
            raise AppError("A nota ainda não foi criada no Obsidian.")
        obsidian.open_path(path)
        return {"opened": True}
    url = s.sinks["notion"].url
    if not url:
        raise AppError("A página ainda não foi criada no Notion.")
    return {"url": url}


ROUTES = {
    ("GET", "/api/listen"): lambda h: view(),
    ("POST", "/api/listen/start"): lambda h: start(),
    ("POST", "/api/listen/stop"): lambda h: stop(),
    ("POST", "/api/listen/open"): lambda h: open_target(str(h._json().get("target") or "")),
}
