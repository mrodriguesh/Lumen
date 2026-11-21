"""A voz nos Estudos (fase 6, D46 a D52): quem fala em cada uso, a fala do chat frase a frase, apertar para falar e
os áudios gerados em segundo plano (o resumo de uma aula e a revisão dos Estudos), com capítulos.

Quem fala (who): o motor dos ajustes, com a voz do uso ou a padrão. A voz sumiu do Voice Studio → a primeira clonada,
com aviso; o Voice Studio está fechado → a reserva escolhida (Chatterbox), com aviso. Nunca troca de voz em silêncio.
Uma voz na placa por vez: com o Voice Studio como motor, o Chatterbox não abre (e fecha, se estava aberto).

O navegador nunca fala com o Voice Studio (a CSP é connect-src 'self'): o áudio volta por estas rotas."""
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from .. import AppError, Cancelled, eta, jobs, llm, package, store, transcribe, voice, voicestudio
from . import db, learn, settings

USES = ("chat", "summary", "review", "practice", "call")
AUDIO = db.MEDIA / "audio"
AID = re.compile(r"aula-lm-[0-9a-f]{16}|rev-[0-9a-f]{32}")
SAMPLE = "Olá! Eu sou a voz dos seus estudos no Lúmen. Vamos revisar juntos o que você aprendeu hoje."
CPS = 15.0                 # caracteres por segundo de fala em português (estimativa antes da 1ª medida)
PRIOR_RTF = {"voicestudio": 0.6, "chatterbox": 1.1}  # geração ÷ fala, medidos neste PC (02/11 e 01/11)
GAP, THINK, AFTER = 0.35, 3.0, 1.0  # pausas (s): entre frases, para pensar na pergunta, depois da resposta
MIC_RATE, MIC_MAX_S = 48000, 120
FRAME_16K, PREROLL_FRAMES = 512, 10  # 32 ms por quadro (Silero VAD v5) e 320 ms de anel antes da fala (4.3.1)
# Na fala ao vivo, a 1ª frase com mais que isto é cortada (na vírgula): medido em 02/11, uma 1ª frase de ≈ 220
# caracteres levou 11,4 s até o primeiro som; uma de ≈ 90, cerca de 2,7 s (16 passos). Com 12 passos, 39 caracteres
# saem em 1,51 s e 88 em 1,99 s (o resto da frase é gerado enquanto o 1º pedaço toca).
FIRST_CHARS = 50
# Qualidade por uso → passos do OmniVoice por pedido (num_step, D56); o nível global do Voice Studio não muda.
STEPS = {"fast": 8, "balanced": 12, "quality": 16, "max": 32}
AHEAD = 2           # frases prontas à frente da que está tocando, no máximo (D59)
LAST = {}           # os últimos tempos da fala (painel "Esta máquina")


# --- quem fala --------------------------------------------------------------------------------------------------------

def _names_file():
    return db.HOME / "voice_names.json"


def _names():
    try:
        return json.loads(_names_file().read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def gallery():
    """As vozes do Voice Studio, com a padrão marcada. Guarda os nomes vistos: se uma voz sumir, o aviso diz qual."""
    vs = voicestudio.voices()
    names = {**_names(), **{v["id"]: v["name"] for v in vs}}
    try:
        db.HOME.mkdir(parents=True, exist_ok=True)
        _names_file().write_text(json.dumps(names, ensure_ascii=False), "utf-8")
    except OSError:
        pass
    default = settings.load()["voice"]["voice_id"]
    return [{**v, "default": v["id"] == default} for v in vs]


def _chatterbox(note=None):
    if not voice.available():
        raise AppError("A voz de reserva (Chatterbox) não está instalada neste PC.",
                       "Abra o Voice Studio ou escolha outro motor em Configurações → Voz.")
    return {"engine": "chatterbox", "voice": None, "name": "Chatterbox pt-br", "kind": "local", "image": False,
            "note": note}


def who(use="chat", s=None, closed=False, start=True):
    """`closed`: o estado acabou de dizer que o Voice Studio está fechado (não espera o prazo de conexão de novo, nem
    sobe nada). `start`: com o Voice Studio fechado e "ligar sozinho" ativo, sobe o backend dele sem janela (D53); a
    reserva só entra se isso falhar, sempre dizendo qual voz fala."""
    s = s or settings.load()["voice"]
    _sync(s)
    if s["engine"] == "off":
        raise AppError("A voz está desligada.", "Ligue em Estudos → Configurações → Voz.")
    if s["engine"] == "chatterbox":
        return _chatterbox()
    try:
        if closed:
            raise AppError(*voicestudio.CLOSED)
        vs = gallery()
    except AppError as e:
        foreign = str(e) != voicestudio.CLOSED[0] and voicestudio.health()[0] == "other"
        if str(e) != voicestudio.CLOSED[0] and not foreign:
            raise
        vs, err = None, e
        if foreign:  # outro programa na porta: não há o que subir (D55); a reserva entra, dizendo por quê
            err = AppError("A porta do Voice Studio está ocupada por outro programa.", "Feche o programa que usa essa porta.")
        elif start and s["vs_autostart"] and not closed:
            try:
                voicestudio.BACKEND.ensure()
                vs = gallery()
            except AppError as e2:
                err = e2
        if vs is None:
            if s["fallback"] != "chatterbox" or not voice.available():
                raise err from None
            return _chatterbox(f"{err} Quem fala é a voz de reserva, o Chatterbox pt-br.")
    if voice.ENGINE.alive():
        voice.ENGINE.close()  # o Voice Studio respondeu: uma voz na placa por vez (D46); na reserva, ela fica aberta
    want = s.get(f"{use}_voice") or s["voice_id"]
    hit, note = next((v for v in vs if v["id"] == want), None), None
    if not hit:
        clones = [v for v in vs if v["kind"] == "clone"]
        hit = next((v for v in clones if not v["demo"]), None) or (clones or vs or [None])[0]
        if not hit:
            raise AppError("O Voice Studio não tem nenhuma voz.", "Clone ou crie uma voz no Voice Studio.")
        note = f"A voz “{_names().get(want, want)}” não está mais no Voice Studio. Quem fala é {hit['name']}."
    return {"engine": "voicestudio", "voice": hit["id"], "name": hit["name"], "kind": hit["kind"],
            "image": hit["image"], "note": note}


def _sync(s):
    voicestudio.BACKEND.idle_s = int(s["vs_idle_minutes"]) * 60


def engine_for(w, s, steps=None):
    """O objeto com say(text, out, seed, check) que o voice.synth usa, com o cache de frases (D59)."""
    if w["engine"] == "chatterbox":
        def say_cb(text, out, seed, check):
            key = _key(w, text, s, None, seed)
            data = _cached(key, s)
            if data is None:
                seconds = voice.ENGINE.say(text, out, seed, check)
                _keep(key, Path(out).read_bytes(), s)
                return seconds
            Path(out).write_bytes(data)
            return _seconds(data)
        return SimpleNamespace(say=say_cb)

    def say(text, out, seed, check):
        key = _key(w, text, s, steps, seed if s["seed"] else None)
        data = _cached(key, s)
        if data is not None:
            Path(out).write_bytes(data)
            return _seconds(data)
        seconds = voicestudio.speak(text, out, w["voice"], s["speed"], s["language"], seed if s["seed"] else None,
                                    s["style"], check, steps=steps)
        _keep(key, Path(out).read_bytes(), s)
        return seconds
    return SimpleNamespace(say=say)


# --- cache de frases (D59): "Ouvir" de novo e as frases repetidas saem na hora ------------------------------------------

def _cache_dir():
    return AUDIO / "cache"


def _key(w, text, s, steps, seed):
    """A chave usa o texto como a voz o recebe (com as pronúncias do estudante) e o motor ativo do Voice Studio:
    adicionar uma pronúncia ou trocar de motor nunca toca o áudio antigo."""
    import hashlib
    if w["engine"] == "voicestudio":
        text = voicestudio.pronounce(text, s["language"] or None)
        motor = (voicestudio._engine.get("value") or {}).get("id")
    else:
        motor = None
    raw = json.dumps([w["engine"], motor, w.get("voice"), text, s["speed"], steps, seed, s["language"], s["style"]],
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def clear_cache():
    """“Limpar frases guardadas” e Seus dados → apagar: o cache inteiro sai."""
    shutil.rmtree(_cache_dir(), ignore_errors=True)


def _cached(key, s):
    if int(s["cache_mb"]) <= 0:  # sem cache: nem grava nem lê o que tinha
        return None
    f = _cache_dir() / f"{key}.wav"
    try:
        data = f.read_bytes()
        os.utime(f)  # usado agora: é o último a sair quando o cache enche
        return data
    except OSError:
        return None


def _keep(key, data, s):
    """Guarda a frase e, passando do teto (cache_mb), apaga as usadas há mais tempo."""
    cap = int(s["cache_mb"]) * 1_000_000
    if cap <= 0:
        return
    d = _cache_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{key}.part"
        tmp.write_bytes(data)
        tmp.replace(d / f"{key}.wav")
        files = sorted(((e.stat().st_mtime, e.stat().st_size, e.path) for e in os.scandir(d) if e.name.endswith(".wav")))
        total = sum(sz for _, sz, _ in files)
        for _, sz, path in files:
            if total <= cap:
                break
            os.unlink(path)
            total -= sz
    except OSError:
        pass  # o cache é só um atalho: sem disco, a fala segue


def _seconds(wav_bytes):
    import io
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / w.getframerate()


def seeds(s):
    return (s["seed"], s["seed"] + 1, s["seed"] + 2) if s["seed"] else voice.SEEDS


def first_paragraph(md):
    """“Ler só o começo”: o primeiro parágrafo com texto (um título sozinho não conta)."""
    for block in re.split(r"\n\s*\n", str(md or "")):
        if voice.speakable(re.sub(r"^\s*#{1,6}\s.*$", "", block, flags=re.M)).strip():
            return block
    return ""


# --- a fala do chat ---------------------------------------------------------------------------------------------------

def live(text, use, cancel, parts=None, voice_id=None, language=None, keep=True):
    """Eventos NDJSON: quem fala, cada frase pronta (WAV em base64, tocada assim que chega) e o fim. A fala gera uma
    frase por vez, sem a conferência do Whisper (só nos áudios longos); a tela toca a anterior enquanto a próxima é
    gerada. Fechar a conexão (parar, outra mensagem, o estudante começou a falar) cancela. `parts` (o tour narrado do
    diagrama): uma lista de textos; cada frase volta com o número da parte, e a tela acende a parte que está falando.
    `keep=False` (conversa temporária) e o Treino falado não usam o cache de frases: prometem ficar só na memória."""
    def check():
        if cancel.is_set():
            raise Cancelled
    try:
        use = use if use in USES else "chat"
        s = settings.load()["voice"]
        if voice_id:  # o personagem do Treino falado: a voz dele, só nesta fala
            s = {**s, f"{use}_voice": voice_id}
        if language is not None:
            s = {**s, "language": language}
        if not keep or use == "practice":
            s = {**s, "cache_mb": 0}
        t0 = time.monotonic()
        if s["engine"] == "voicestudio":
            yield from _prepare(s, check)
        w = who(use, s)
        yield {"type": "voice", **w}
        blocks = parts or [first_paragraph(text) if s["read"] == "short" else text]
        items = [(p, x) for p, b in enumerate(blocks) for x in voice.sentences(voice.speakable(b))]
        if items and len(items[0][1]) > FIRST_CHARS:  # o 1º pedaço curto: a fala começa cedo; o resto sai enquanto ele toca
            items[:1] = [(items[0][0], x) for x in _first_cut(items[0][1])]
        steps = STEPS[s["chat_quality"]] if w["engine"] == "voicestudio" else None
        eng, seed, first, gen, spoken = engine_for(w, s, steps), seeds(s)[0], None, 0.0, 0.0
        starts, durs = [], []  # quando cada frase começa a tocar na tela (estimado) e quanto dura
        with tempfile.TemporaryDirectory(prefix="lumen-voz-") as d:
            for i, (part, sentence) in enumerate(items):
                # no máximo AHEAD frases prontas à frente da que toca: parar no meio não gasta a placa à toa
                while i >= AHEAD and starts[i - AHEAD] > time.monotonic():
                    check()
                    time.sleep(0.1)
                check()
                t = time.monotonic()
                data, seconds, cached = synth_sentence(sentence, w, s, steps, seed, check, d, eng)
                if not cached and w["engine"] == "voicestudio":
                    gen, spoken = gen + time.monotonic() - t, spoken + seconds
                now = time.monotonic()
                first = first if first is not None else round(now - t0, 2)
                starts.append(max(now, starts[-1] + durs[-1]) if starts else now)
                durs.append(seconds)
                yield {"type": "sentence", "i": i, "n": len(items), "part": part, "text": sentence,
                       "seconds": round(seconds, 2), "audio": base64.b64encode(data).decode()}
        LAST.update(first_s=first, steps=steps, rtf=round(gen / spoken, 3) if spoken else LAST.get("rtf"), at=db.now())
        yield {"type": "done", "first_s": first, "total_s": round(time.monotonic() - t0, 2)}
    except Cancelled:
        return
    except AppError as e:
        yield {"type": "error", "message": str(e), "action": e.action}


def synth_sentence(sentence, w, s, steps, seed, check, work_dir=None, eng=None):
    """Gera (ou busca no cache, D59) uma frase em WAV: (wav_bytes, segundos, veio_do_cache). Reaproveitada pela fala do
    chat e pela conversa por voz."""
    key = _key(w, sentence, s, steps, seed if s["seed"] else None) if w["engine"] == "voicestudio" else None
    data = _cached(key, s) if key else None
    if data is not None:
        return data, _seconds(data), True
    if w["engine"] == "voicestudio":
        data = _live_vs(sentence, w, s, steps, seed)
        _keep(key, data, s)
        return data, _seconds(data), False
    eng = eng or engine_for(w, s, steps)
    if work_dir:
        out = Path(work_dir) / f"s-{int(time.monotonic() * 1e6)}.wav"
        seconds = eng.say(sentence, out, seed, check)
        data = out.read_bytes()
        out.unlink(missing_ok=True)
        return data, seconds, False
    with tempfile.TemporaryDirectory(prefix="lumen-voz-") as d:
        out = Path(d) / "s.wav"
        seconds = eng.say(sentence, out, seed, check)
        return out.read_bytes(), seconds, False


def _first_cut(s, target=FIRST_CHARS):
    """O 1º pedaço da fala: corta na vírgula perto de `target` (a pausa natural); sem vírgula, só uma frase longa
    (mais de 90 caracteres) é cortada, como antes. Cortar no espaço de uma frase curta soaria quebrado."""
    marks = [m.start() for m in re.finditer(r"[,;] ", s[:target + 30]) if m.start() >= 15]
    if marks:
        cut = min(marks, key=lambda k: abs(k - target))  # a vírgula mais perto do alvo, não a última
        return [s[:cut + 1].strip(), *voice.sentences(s[cut + 1:].strip())]
    return voice.sentences(s, 90 if target >= FIRST_CHARS else 65)


def _live_vs(sentence, w, s, steps, seed):
    """Uma frase do chat no Voice Studio → WAV, pelo /v1/audio/speech em PCM com os passos do uso (D56). Medido em
    02/11: com 16 passos, 2,69 s até o 1º som contra 2,79 s do /ws/tts, que não aceita passos nem semente."""
    return _wav(voicestudio.synth(sentence, w["voice"], s["speed"], s["language"], seed if s["seed"] else None,
                                  s["style"], steps, "pcm"))


VRAM_NEED_GB = 3.0  # o OmniVoice carregado ocupa ≈ 2,7 GB (medido em 02/11), mais folga


def _short_vram():
    """VRAM livre agora, se ela não basta para carregar o modelo de voz (que ainda não está carregado); senão None."""
    free = transcribe.gpu_free_gb()
    if free is None or free >= VRAM_NEED_GB:
        return None
    try:
        if voicestudio._req("/model/status").get("loaded"):
            return None
    except AppError:
        pass  # fechado: vai subir e carregar
    return free


def _make_room(check):
    """Pouca VRAM e o modelo de voz por carregar (D59): pede ao Ollama para soltar a placa (ele recarrega sozinho no
    próximo pedido) e espera a memória voltar, até 30 s. Menos passos não ajudariam: medido, a geração soma ≈ 0,1 GB
    em qualquer número de passos. Só na hora de falar, quando a resposta já terminou."""
    if _short_vram() is None or not llm.release_vram():
        return
    for _ in range(60):
        check()
        time.sleep(0.5)
        free = transcribe.gpu_free_gb()
        if free is None or free >= VRAM_NEED_GB:
            return


def _prepare(s, check):
    """Antes da 1ª frase: o backend no ar (sobe sem janela, se preciso) e o modelo carregado (D54), com o progresso
    para a barra de fala ("Preparando a voz… 40%"), nunca uma caixa de erro. Uma falha aqui deixa o who() decidir
    (reserva com aviso)."""
    b = voicestudio.BACKEND
    _sync(s)
    if not (b._warm and b._warm.is_alive()) and _short_vram() is not None:
        yield {"type": "preparing", "phase": "loading", "label": "Pouca memória na placa: pedindo ao modelo de texto para soltar…"}
        _make_room(check)
    t = b.warm_async(start=s["vs_autostart"])
    while t.is_alive():
        check()
        if b.state.get("phase") in ("starting", "loading"):
            yield {"type": "preparing", **b.state}
        t.join(0.4)


def _wav(pcm, rate=voicestudio.SR):
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def test(text, voice_id=None, use="chat"):
    """Uma frase para ouvir na hora (Testar, a prévia da velocidade): o WAV em base64 e quem falou."""
    s = settings.load()["voice"]
    if voice_id:
        s = {**s, f"{use}_voice": voice_id}
    w = who(use, s)
    with tempfile.TemporaryDirectory(prefix="lumen-voz-") as d:
        out = Path(d) / "teste.wav"
        r = voice.synth(" ".join(str(text or SAMPLE).split())[:400] or SAMPLE, out, verify=False,
                        engine=engine_for(w, s), seeds=seeds(s))
        return {"who": w, "seconds": round(r["seconds"] or 0, 2), "audio": base64.b64encode(out.read_bytes()).decode()}


# --- apertar para falar ----------------------------------------------------------------------------------------------

class Mic:
    """O microfone do Windows: no apertar para falar grava um trecho; na chamada de voz (`start_continuous`) entrega
    quadros contínuos de 32 ms em 16 kHz com um anel de 320 ms antes do início da fala. O áudio fica só na memória."""

    def __init__(self):
        from collections import deque
        self.lock, self.stop_ev, self.thread = threading.Lock(), threading.Event(), None
        self.chunks, self.level, self.error = [], 0.0, None
        self.preroll = deque(maxlen=PREROLL_FRAMES)
        self.last_frame_at = None   # instante do último quadro entregue (a chamada detecta o aparelho que sumiu)
        self._gen = 0               # cada abertura contínua tem a sua geração: uma thread presa num aparelho morto não fala mais

    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        from .. import record
        with self.lock:
            if self.busy():
                raise AppError("O Lúmen já está ouvindo.")
            if record.active():
                raise AppError("Uma aula está sendo gravada.", "Pare a gravação para falar com o Lúmen.")
            self.stop_ev.clear()
            self.chunks, self.level, self.error, ready = [], 0.0, None, threading.Event()
            self.thread = threading.Thread(target=self._run, args=(ready,), daemon=True, name="Lumen mic")
            self.thread.start()
            ready.wait(5)
            if self.error:
                raise AppError(self.error, "Confira o microfone nas configurações de som do Windows.")

    def start_continuous(self, on_frame, mic_id="", open_mic=None):
        """Modo contínuo para a conversa por voz: quadros de 32 ms (48 → 16 kHz), anel de 320 ms e nível ao vivo."""
        from .. import record
        with self.lock:
            if self.busy() and self.stop_ev.is_set():
                self.thread = None   # pediram para parar e a thread não saiu (aparelho travado): é abandonada, não bloqueia a nova
            if self.busy():
                raise AppError("O Lúmen já está ouvindo.")
            if record.active():
                raise AppError("Uma aula está sendo gravada.", "Pare a gravação para falar com o Lúmen.")
            self.stop_ev.clear()
            self.preroll.clear()
            self._gen += 1
            self.last_frame_at = None
            self.chunks, self.level, self.error, ready = [], 0.0, None, threading.Event()
            self.thread = threading.Thread(target=self._run_continuous, args=(ready, on_frame, mic_id, open_mic, self._gen),
                                           daemon=True, name="Lumen call mic")
            self.thread.start()
            ready.wait(5)
            if self.error:
                raise AppError(self.error, "Confira o microfone nas configurações de som do Windows.")

    def preroll_audio(self):
        items = list(self.preroll)
        return np.concatenate(items) if items else np.zeros(0, np.float32)

    def _run(self, ready):
        try:
            import soundcard  # noqa: F401 — inicializa o COM na thread que o importa (só a primeira vez)
            from .. import loopback
            if os.name == "nt":  # o COM do áudio é por thread (ver record._open_loopback)
                import ctypes
                ctypes.windll.ole32.CoInitializeEx(None, 0)
            with loopback.microphone(MIC_RATE, 1) as rec:
                ready.set()
                for _ in range(MIC_MAX_S * 10):
                    if self.stop_ev.is_set():
                        break
                    a = np.asarray(rec.record(numframes=MIC_RATE // 10), np.float32).reshape(-1)
                    n = len(a) // 3 * 3  # 48 → 16 kHz, como a gravação das aulas
                    self.chunks.append(a[:n].reshape(-1, 3).mean(axis=1))
                    self.level = float(np.abs(a).max()) if a.size else 0.0
        except Exception as e:  # noqa: BLE001 — sem microfone ou o Windows negou o acesso
            logging.getLogger("lumen").warning("microfone: %s: %s", type(e).__name__, e)
            self.error = "O microfone não abriu."
        finally:
            ready.set()
            self.level = 0.0

    def _run_continuous(self, ready, on_frame, mic_id, open_mic, gen=0):
        try:
            if open_mic is None:
                import soundcard  # noqa: F401
                from .. import loopback
                if os.name == "nt":
                    import ctypes
                    ctypes.windll.ole32.CoInitializeEx(None, 0)
                ctx = loopback.microphone(MIC_RATE, 1, mic_id)
            else:
                ctx = open_mic(MIC_RATE, 1, mic_id)
            block_48k = FRAME_16K * 3  # 1536 amostras em 48 kHz = 512 em 16 kHz (32 ms)
            buf = np.zeros(0, np.float32)
            with ctx as rec:
                ready.set()
                while not self.stop_ev.is_set() and gen == self._gen:
                    raw = rec.record(numframes=block_48k)
                    if raw is None or gen != self._gen:
                        break
                    a = np.asarray(raw, np.float32).reshape(-1)
                    if a.size == 0:
                        if self.stop_ev.wait(0.01):
                            break
                        continue
                    n = len(a) // 3 * 3
                    f16 = a[:n].reshape(-1, 3).mean(axis=1) if n else np.zeros(0, np.float32)
                    buf = np.concatenate((buf, f16)) if buf.size else f16
                    while buf.size >= FRAME_16K and not self.stop_ev.is_set():
                        frame, buf = buf[:FRAME_16K], buf[FRAME_16K:]
                        self.level = float(np.abs(frame).max())
                        self.last_frame_at = time.monotonic()
                        on_frame(frame, self.level)
                        self.preroll.append(frame)
        except Exception as e:  # noqa: BLE001
            logging.getLogger("lumen").warning("microfone contínuo: %s: %s", type(e).__name__, e)
            if gen == self._gen:
                self.error = "O microfone não abriu."
        finally:
            ready.set()
            if gen == self._gen:
                self.level = 0.0

    def state(self):
        return {"listening": self.busy(), "level": round(self.level, 3),
                "seconds": round(sum(len(c) for c in self.chunks) / 16000, 1)}

    def stop(self):
        self.stop_ev.set()
        if self.thread:
            self.thread.join(3)
        audio, self.chunks = (np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)), []
        return audio


MIC = Mic()


def heard(audio):
    """Fala do estudante → texto, pelo modelo de transcrição dos Ajustes, em português, sem a segunda opinião."""
    if audio.size < 16000 * 0.4 or float(np.abs(audio).max()) < 0.003:
        raise AppError("Não ouvi nada.", "Segure o botão (ou a barra de espaço) enquanto fala.")
    name = transcribe.pick(store.load_config()["quality"])[1]["name"]
    with tempfile.TemporaryDirectory(prefix="lumen-ouvir-") as d:
        path = Path(d) / "fala.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        out = transcribe.transcribe(path, name, lambda *a: None, lambda: None, second=False, release=llm.release_vram,
                                    language="pt")
    return " ".join(str(s.get("text") if isinstance(s, dict) else getattr(s, "text", "")).strip()
                    for s in out.get("segments") or []).strip()


# --- áudios longos (resumo da aula e revisão), pela fila de tarefas ----------------------------------------------------

def lesson_script(key):
    """O resumo que a aula já tem, sem gerar texto de novo: um capítulo para o resumo e um por tópico."""
    pkg = package.load(package.lumen_id(key))
    L = pkg["lesson"]
    chapters = [{"title": "Resumo", "parts": [f"Resumo da aula: {L['title']}.", L.get("summary") or ""], "t": None}]
    for tp in L.get("topics") or []:
        chapters.append({"title": str(tp.get("title") or "")[:80] or f"Parte {len(chapters)}",
                         "parts": [f"{tp.get('title')}.", tp.get("explanation") or "", tp.get("why") or ""],
                         "t": tp.get("timestamp")})
    chapters[-1]["parts"].append("Fim do resumo.")
    return {"id": f"aula-{pkg['lumen_id']}", "kind": "lesson", "use": "summary", "title": L["title"], "ref": key,
            "chapters": chapters}


def review_script(item_id, s=None):
    """O roteiro da revisão (learn.audio_script, já com tetos): pergunta, pausa para lembrar, resposta. A duas vozes
    (D58): o narrador lê o título, as perguntas e o fim; a voz padrão responde, sem o "Resposta:"."""
    it = learn.item(item_id)
    if it["kind"] != "audio":
        raise AppError("Este item não é uma revisão em áudio.")
    s = s or settings.load()["voice"]
    dialog = bool(s["review_dialog"] and s["narrator_voice"])
    n = (lambda t: ("narrator", t)) if dialog else (lambda t: t)
    d = it["data"]
    chapters = [{"title": "Introdução", "parts": [n(f"{d['title']}."), n(d.get("intro") or "")], "t": None}]
    for ch in d["chapters"]:
        parts = [n(f"{ch['title']}.")]
        for q in ch["items"]:
            parts += [n(q["question"]), THINK, q["answer"] if dialog else f"Resposta: {q['answer']}", AFTER]
        chapters.append({"title": ch["title"], "parts": parts, "t": None})
    chapters[-1]["parts"].append(n(d.get("outro") or "Fim da revisão."))
    return {"id": f"rev-{it['id']}", "kind": "review", "use": "review", "title": d["title"], "ref": it["id"],
            "chapters": chapters, "dialog": dialog}


def _sentences(script):
    """[(capítulo, frase | pausa, quem)] na ordem da fala; quem = "narrator" na revisão a duas vozes, senão None."""
    out = []
    for ci, ch in enumerate(script["chapters"]):
        for p in ch["parts"]:
            if isinstance(p, float):
                out.append((ci, p, None))
                continue
            spk, text = p if isinstance(p, (tuple, list)) else (None, p)
            out += [(ci, x, spk) for x in voice.sentences(voice.speakable(text))]
    return out


# Geração ÷ fala do OmniVoice por número de passos (roteiro de 106 palavras, frase a frase, modelo quente, 02/11).
PRIOR_STEPS = {8: 0.27, 12: 0.33, 16: 0.39, 24: 0.53, 32: 0.68}


def _rtf(engine, steps):
    """(chave do eta, valor inicial): o tempo aprendido é separado por motor e por número de passos (D56)."""
    if engine == "voicestudio" and steps:
        return f"voicestudio-{steps}", PRIOR_STEPS.get(steps, PRIOR_RTF["voicestudio"])
    return engine, PRIOR_RTF[engine]


def estimate(script, engine, verify, steps=None):
    chars = sum(len(x) for _, x, _ in _sentences(script) if isinstance(x, str))
    key, prior = _rtf(engine, steps)
    return chars / CPS * eta.value("voice_rtf", key, prior + (0.15 if verify else 0))


def make(script):
    """O áudio inteiro: frase a frase (conferida pelo Whisper com verify_long), pausas, volume igualado, AAC em .m4a
    em MEDIA/audio e os capítulos num .json ao lado. Cancelar não deixa arquivo pela metade: as frases ficam numa
    pasta temporária, apagada no fim, e o encode() grava num temporário."""
    s = settings.load()["voice"]
    jobs._set(stage="voice", detail="Preparando a voz…")
    llm.release_vram()  # a placa para a voz (o Ollama recarrega sozinho no próximo pedido)
    w = who(script["use"], s)
    steps = STEPS[s["long_quality"]] if w["engine"] == "voicestudio" else None
    eng, verify = engine_for(w, s, steps), s["verify_long"]
    engines, names = {None: eng, "narrator": eng}, w["name"]
    if script.get("dialog"):  # revisão a duas vozes: o narrador precisa ser outra voz do mesmo motor
        try:
            wn = who(script["use"], {**s, f"{script['use']}_voice": s["narrator_voice"]})
            if wn["engine"] == w["engine"] and wn.get("voice") != w.get("voice"):
                engines["narrator"], names = engine_for(wn, s, steps), f"{wn['name']} e {w['name']}"
        except AppError:
            pass  # sem o narrador, a revisão sai numa voz só
    plan = eta.Plan([("voice", estimate(script, w["engine"], verify, steps))])
    eta.current = plan
    plan.at("voice")
    before = voicestudio.mark() if w["engine"] == "voicestudio" else None
    work = AUDIO / f".{script['id']}.partes"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        items = _sentences(script)
        total = sum(1 for _, x, _ in items if isinstance(x, str))
        parts, owner, done, gen, spoken, sr = [], [], 0, 0.0, 0.0, None
        jobs._set(stage="voice", detail=f"Gerando a fala · {names}", progress=0.0)
        for ci, x, spk in items:
            jobs.check()
            if isinstance(x, float):
                parts.append(x)
                owner.append(ci)
                continue
            out = work / f"{len(parts)}.wav"
            t = time.monotonic()
            r = voice.synth(x, out, jobs.check, verify, engines[spk], seeds(s))
            gen += time.monotonic() - t
            spoken += r.get("seconds") or 0
            sr = sr or voice.read_wav(out)[1]
            parts += [out, GAP]
            owner += [ci, ci]
            done += 1
            plan.progress(done / total)
            jobs._set(detail=f"Gerando a fala · frase {done} de {total} · {names}", progress=done / total,
                      eta=round(plan.left()))
        jobs.check()
        jobs._set(detail="Juntando as frases e igualando o volume…")
        audio, starts = voice.mix(parts, sr)
        chapters = [{"title": ch["title"], "t": round(starts[owner.index(ci)], 2), "lesson_t": ch.get("t")}
                    for ci, ch in enumerate(script["chapters"]) if ci in owner]
        AUDIO.mkdir(parents=True, exist_ok=True)
        voice.encode(audio, sr, AUDIO / f"{script['id']}.m4a")
        meta = {"id": script["id"], "kind": script["kind"], "title": script["title"], "ref": script["ref"],
                "chapters": chapters, "duration": round(len(audio) / sr, 1), "voice": names, "engine": w["engine"],
                "steps": steps, "note": w["note"], "created": db.now()}
        tmp = AUDIO / f"{script['id']}.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
        tmp.replace(AUDIO / f"{script['id']}.json")
        if spoken:
            eta.learn("voice_rtf", gen / spoken, _rtf(w["engine"], steps)[0])
        if script["kind"] == "review":
            it = learn.item(script["ref"])
            learn.set_data(it["id"], {**it["data"], "audio": {"status": "pronto", "id": script["id"]}})
        return {"audio": meta}
    finally:
        shutil.rmtree(work, ignore_errors=True)
        voicestudio.unload_if_ours(before)


def start(kind, ref):
    """Põe o áudio na fila de tarefas (uma tarefa por vez, a mesma das aulas)."""
    script = lesson_script(ref) if kind == "lesson" else review_script(ref)
    jobs.start("audio", make, script, spec={"key": script["id"], "title": script["title"], "audio_kind": kind})
    return {"ok": True, "id": script["id"]}


AFTER_S = 6  # espera antes de pôr o resumo na fila: jobs.start limpa a tarefa, e a tela precisa ver a aula pronta antes


def after_lesson(kind, spec, result):
    """jobs.ON_DONE: com “Gerar o resumo em áudio no fim da aula” ligado, a aula publicada vira áudio sozinha. A chave
    vem do resultado da publicação (o spec do finish não a traz); uma aula reenviada que já tem o áudio não gera de
    novo."""
    if kind != "process" or not isinstance(result, dict) or not result.get("dests") or not result.get("lumen_id"):
        return
    key = result.get("key") or (spec or {}).get("key")
    if not key or not settings.load()["voice"]["summary_after_lesson"] or (AUDIO / f"aula-{result['lumen_id']}.m4a").exists():
        return

    def later():
        try:
            if not jobs.busy():
                start("lesson", key)
        except AppError:
            pass  # sem pacote ou sem voz: o botão “Gerar resumo em áudio” continua na aula
    threading.Timer(AFTER_S, later).start()


jobs.ON_DONE.append(after_lesson)


def watch(key, t):
    """“Ver na aula (mm:ss)”: o vídeo do YouTube abre no momento exato; um arquivo do PC abre no player do Windows (que
    não aceita começar num tempo: a tela diz para onde pular). O tempo vem do tópico da aula, nunca inventado."""
    pkg = package.load(package.lumen_id(key))
    src, t = pkg.get("source") or {}, max(0, int(float(t or 0)))
    if src.get("yt_id") and re.fullmatch(r"[\w-]{6,20}", str(src["yt_id"])):
        import webbrowser
        webbrowser.open(f"https://www.youtube.com/watch?v={src['yt_id']}&t={t}s")
        return {"opened": "youtube", "t": t}
    try:
        path = Path(json.loads((jobs.work_dir(key) / "source.json").read_text("utf-8")).get("path") or "")
    except (OSError, ValueError):
        path = Path("")
    if path.name and path.is_file():
        os.startfile(str(path))  # noqa: S606 — o arquivo da própria aula, guardado pelo Lúmen
        return {"opened": "file", "t": t}
    raise AppError("O vídeo original desta aula não está mais no PC.", "O tempo citado continua no capítulo.")


def audio_meta(aid):
    if not isinstance(aid, str) or not AID.fullmatch(aid):
        raise AppError("Áudio não encontrado.")
    try:
        return json.loads((AUDIO / f"{aid}.json").read_text("utf-8"))
    except (OSError, ValueError):
        raise AppError("Áudio não encontrado.", "Gere o áudio de novo.") from None


def audios():
    out = []
    for f in sorted(AUDIO.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if AUDIO.is_dir() else []:
        try:
            meta = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if AID.fullmatch(str(meta.get("id"))) and (AUDIO / f"{meta['id']}.m4a").exists():
            out.append(meta)
    return out


# --- rotas -------------------------------------------------------------------------------------------------------------

def _body(h):
    b = h._json()
    if not isinstance(b, dict):
        raise AppError("Pedido inválido.")
    return b


def ram_free_gb():
    """RAM livre agora (GlobalMemoryStatusEx). None fora do Windows."""
    if os.name != "nt":
        return None
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                    ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
    m = MS(len=ctypes.sizeof(MS))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.avail / 2**30, 2), round(m.total / 2**30, 2)


WARM_MIN_RAM_GB = 1.0  # abaixo disto o pré-aquecimento espera (a carga do OmniVoice passa pela RAM); medido em 02/11


def warm(reason="open"):
    """Pré-aquece a voz (D54) quando vale a pena: o motor é o Voice Studio e, se ele estiver fechado, "ligar sozinho"
    está ativo. Com pouca RAM livre, não pré-aquece (a 1ª frase carrega, como antes)."""
    s = settings.load()["voice"]
    if s["engine"] != "voicestudio":
        return {"warming": False, "why": "motor"}
    clicked = reason == "hear"  # "Ligar a voz agora": um clique do estudante liga mesmo sem "ligar sozinho"
    ram = ram_free_gb()
    if ram and ram[0] < WARM_MIN_RAM_GB and not clicked:
        return {"warming": False, "why": "ram", "ram_free_gb": ram[0]}
    if not clicked and _short_vram() is not None:  # não tira o Ollama da placa no meio de uma resposta
        return {"warming": False, "why": "vram"}
    _sync(s)
    voicestudio.BACKEND.warm_async(start=s["vs_autostart"] or clicked)
    return {"warming": True, "state": dict(voicestudio.BACKEND.state)}


def on_start():
    """Na abertura do Lúmen: com "Deixar a voz pronta ao abrir" ligado, sobe o backend e carrega o modelo."""
    try:
        if settings.load()["voice"]["vs_warm_on_open"]:
            warm("open")
    except Exception:  # noqa: BLE001 — a abertura do app nunca falha por causa da voz
        logging.getLogger("lumen").exception("voz: pré-aquecimento na abertura falhou")


def _warm(h):
    b = h._json() if h.command == "POST" else {}
    return warm(b.get("reason") if isinstance(b, dict) and b.get("reason") in ("open", "answer", "hear") else "open")


def _state(h):
    s = settings.load()["voice"]
    out = {"settings": s, "voicestudio": voicestudio.status(), "chatterbox": voice.available(), "uses": USES,
           "listening": MIC.state(), "steps": STEPS, "last": LAST}
    try:
        if s["engine"] == "voicestudio" and s["vs_autostart"] and not out["voicestudio"]["running"] and out["voicestudio"]["installed"]:
            # desligado, mas liga sozinho no 1º uso (D53): quem fala é a voz padrão (o nome visto da última vez)
            vid = s["chat_voice"] or s["voice_id"]
            out["who"] = {"engine": "voicestudio", "voice": vid, "name": _names().get(vid) or "a voz padrão", "kind": "clone",
                          "image": False, "note": None, "starts": True}
            return out
        out["who"] = who("chat", s, closed=not out["voicestudio"]["running"])
    except AppError as e:
        out["who"] = None
        out["problem"] = {"message": str(e), "action": e.action}
    return out


def _voices(h):
    return {"voices": gallery()}


def _sample(h):
    return voicestudio.sample(h._query().get("id", "")), "audio/wav"


def _image(h):
    data = voicestudio.image(h._query().get("id", ""))
    if not data:
        raise AppError("Esta voz não tem imagem.")
    kind = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg"
    return data, kind


def _test(h):
    from .api import limit
    limit("voice-test", 6)
    b = _body(h)
    vid = b.get("voice") if isinstance(b.get("voice"), str) and b.get("voice") else None
    use = b.get("use") if b.get("use") in USES else "chat"
    return test(b.get("text") if isinstance(b.get("text"), str) else "", vid, use)


def _say(h):
    from .api import Stream
    b = _body(h)
    text = b.get("text") if isinstance(b.get("text"), str) else ""
    parts = [str(p)[:2000] for p in b["parts"][:40]] if isinstance(b.get("parts"), list) else None
    if not text.strip() and not parts:
        raise AppError("Nada para ler.")
    vid = b.get("voice") if isinstance(b.get("voice"), str) and settings.VOICE_ID.fullmatch(b["voice"]) else None
    lang = b.get("language") if b.get("language") in ("pt", "en", "") else None
    cancel = threading.Event()
    return Stream(live(text[:20000], b.get("use"), cancel, parts, vid or None, lang, keep=b.get("temporary") is not True),
                  on_close=cancel.set)


def _cache(h):
    """Frases guardadas (D59): o tamanho e "Limpar frases guardadas"."""
    d = _cache_dir()
    if h.command == "POST":
        if _body(h).get("action") != "clear":
            raise AppError("Ação desconhecida.")
        clear_cache()
    size = sum(e.stat().st_size for e in os.scandir(d) if e.name.endswith(".wav")) if d.is_dir() else 0
    return {"bytes": size}


def _listen(h):
    if h.command == "GET":
        return MIC.state()
    action = _body(h).get("action")
    if action == "start":
        MIC.start()
        return MIC.state()
    audio = MIC.stop()
    if action == "cancel":
        return {"text": ""}
    if action != "stop":
        raise AppError("Ação desconhecida.")
    return {"text": heard(audio)}


def _open_vs(h):
    voicestudio.open_app()
    return {"ok": True}


def _make(h):
    b = _body(h)
    kind = b.get("kind")
    if kind == "lesson" and isinstance(b.get("key"), str) and b["key"]:
        return start("lesson", b["key"][:2000])
    if kind == "review" and isinstance(b.get("item_id"), str) and re.fullmatch(r"[0-9a-f]{32}", b["item_id"]):
        return start("review", b["item_id"])
    raise AppError("Pedido inválido.")


def _audios(h):
    q = h._query()
    if q.get("key"):  # o resumo de uma aula, pela chave dela (a Biblioteca e o resultado não sabem o lumen_id)
        try:
            return {"audio": audio_meta(f"aula-{package.lumen_id(q['key'][:2000])}")}
        except AppError:
            return {"audio": None}
    if q.get("id"):
        return {"audio": audio_meta(q["id"])}
    return {"audios": audios()}


def _file(h):
    from .api import File
    meta = audio_meta(h._query().get("id", ""))
    return File(AUDIO / f"{meta['id']}.m4a", "audio/mp4")


def _audio_action(h):
    b = _body(h)
    meta = audio_meta(b.get("id"))
    path = AUDIO / f"{meta['id']}.m4a"
    if b.get("action") == "reveal":
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{path}"')  # caminho do próprio Lúmen (id conferido acima)
        return {"ok": True}
    if b.get("action") == "watch" and meta.get("kind") == "lesson":
        return watch(meta["ref"], b.get("t"))
    if b.get("action") == "delete":
        path.unlink(missing_ok=True)
        (AUDIO / f"{meta['id']}.json").unlink(missing_ok=True)
        return {"ok": True}
    raise AppError("Ação desconhecida.")


def _mics(h):
    from .. import loopback
    ms = loopback.microphones()
    return {"microphones": ms, "mics": ms}


ROUTES = {
    ("GET", "/api/study/voice/state"): _state,
    ("GET", "/api/study/voice/voices"): _voices,
    ("GET", "/api/study/voice/mics"): _mics,
    ("GET", "/api/study/voice/sample"): _sample,
    ("GET", "/api/study/voice/image"): _image,
    ("POST", "/api/study/voice/test"): _test,
    ("POST", "/api/study/voice/say"): _say,
    ("GET", "/api/study/voice/listen"): _listen,
    ("POST", "/api/study/voice/listen"): _listen,
    ("POST", "/api/study/voice/make"): _make,
    ("GET", "/api/study/voice/audios"): _audios,
    ("GET", "/api/study/voice/file"): _file,
    ("POST", "/api/study/voice/audio"): _audio_action,
    ("POST", "/api/voicestudio/open"): _open_vs,
    ("POST", "/api/study/voice/warm"): _warm,
    ("GET", "/api/study/voice/cache"): _cache,
    ("POST", "/api/study/voice/cache"): _cache,
}
