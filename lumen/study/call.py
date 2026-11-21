"""Conversa por voz em tempo real nos Estudos (fase 6, parte 3): uma chamada por vez, em turnos falados.

Máquina de estados:
  preparing → listening → user_speaking → end_of_speech → transcribing → thinking → speaking → listening (→ ended)

Caminho da fala:
- Microfone contínuo (`listen.MIC.start_continuous`): quadros de 32 ms (48 → 16 kHz) com anel de 320 ms antes da fala.
- VAD Silero ONNX na CPU (~0,14 ms por quadro) para detectar início e fim da fala nos três perfis de silêncio.
- Resposta antecipada (`call_early`): aos 250 ms de silêncio já transcreve e inicia o modelo com `_commit_gate`; se o
  estudante voltar a falar antes do fim da fala, cancela transcrição, modelo e síntese sem deixar rastro na tela, no
  banco ou no disco.
- Transcrição em memória (sem arquivo WAV temporário): Parakeet TDT 0.6b v3 ONNX int8 na CPU por padrão (0 MB de VRAM,
  ~212 ms mediana), ou Whisper quando escolhido e com VRAM livre suficiente; nunca chama `llm.release_vram()`.
- Modelo de texto pelo mesmo orquestrador (`agent.turn`), mantendo o `num_ctx` fixo (D24) e `keep_alive = "30m"`.
- Síntese frase a frase (`listen.synth_sentence` + `listen._first_cut`) e reprodução pelo Python (`loopback.speaker`),
  permitindo cancelamento de eco (`pyaec` + barreira de energia), interrupção imediata com fade-out de 50 ms e chamada
  ativa mesmo com a janela minimizada ou em outra aba do Lúmen."""
from collections import deque
import io
import json
import logging
import os
import queue
import re
import threading
import time
import unicodedata
import uuid
import wave
from pathlib import Path

import numpy as np

from .. import AppError, Cancelled, loopback, record, transcribe, voice, voicestudio
from . import activity, agent, api, chats, explain, learn, listen, mastery, providers, search, settings, tools, writes

log = logging.getLogger("lumen")

SILENCE_MS = {"fast": 450, "normal": 700, "patient": 1100}
EARLY_MS = 250
PARTIAL_INTERVAL_S = 1.2
HANDSFREE_PARTIAL = False   # Medido (4.3.3): parcial a cada 650 ms atrasa o ASR final do Parakeet em +116 ms (270,7 -> 386,5 ms)
MAX_TURN_S = 60.0
MIN_SPEECH_FRAMES = 4       # 128 ms mínimos para considerar fala real
PLAY_SR = 24000             # taxa nativa do OmniVoice / Chatterbox
PLAY_CHUNK = 480            # 20 ms em 24 kHz
FADE_SAMPLES = 1200         # 50 ms em 24 kHz (descida suave na interrupção)
FIRST_CALL_CHARS = 32       # 1ª oração mais curta na chamada: antecipa o 1º som sem quebrar palavras
FILLER_AFTER_S = 1.9
FILLER_TEXT = "Deixa eu ver."

HOLD_MAX_MS = 900           # espera extra, uma vez, quando a frase claramente não terminou ("…porque", "…o", vírgula)
SPEECH_ON, SPEECH_KEEP = 0.5, 0.35   # histerese do VAD: começar a falar exige 0,5; manter a fala aceita 0,35 (fim de palavra)
BARGE_SETTLE_S = 0.4        # depois de fechar o turno, o som de "entendi" ainda pode vazar no microfone
MERGE_WINDOW_S = 4.0        # retomar a fala até 4 s depois de fechar o turno, antes de qualquer som: é a mesma frase (pausa longa no meio)
MIC_STALL_S = 2.5           # microfone sem entregar nenhum quadro por tanto tempo = aparelho perdido
MIC_RETRY_S = 1.0           # espera entre as 3 tentativas de reabrir o microfone
RING = 400                  # eventos guardados para reenviar a quem reconectou (nível do microfone não entra)
LONG_ASK_RE = re.compile(
    r"\b(?:explica|explique|explicar|me conta|conta|detalha|detalhe|descreve|descreva)\b.{0,40}\b(?:detalhad|completa?|completo|"
    r"com calma|passo a passo|em profundidade|a fundo|tudo|bem direitinho|minuciosa)|"
    r"\b(?:explicacao|resposta|resumo)\s+(?:detalhad|complet|longa|bem feita)|"
    r"\bfal(?:a|e) (?:mais|bastante) (?:sobre|disso)\b|\baprofunda\b|\bme explica tudo\b")

STATE_LABELS = {
    "preparing": "Preparando a voz…",
    "listening": "Ouvindo",
    "user_speaking": "Ouvindo você…",
    "end_of_speech": "Entendi",
    "transcribing": "Transcrevendo…",
    "thinking": "Preparando a resposta…",
    "speaking": "Falando",
    "reconnecting": "Reconectando o microfone…",
    "ended": "Chamada encerrada",
}
# Etapas reais do agente durante "thinking" (só aparecem quando a etapa começa de verdade; ver agent._turn)
PHASE_LABELS = {
    "searching": "Consultando suas notas…",
    "tool": "Consultando uma nota…",
    "web": "Pesquisando…",
    "screen": "Olhando a tela…",
    "visual": "Montando o material…",
    "reviewing": "Revisando a resposta…",
    "compacting": "Resumindo a conversa…",
    "slow": "Ainda preparando a resposta…",   # >6 s sem som: modelo recarregando, busca longa ou raciocínio profundo
}
SLOW_AFTER_S = 6.0
VAULT_SOURCES = ("notion", "obsidian", "files")

# Comandos rápidos locais (sem passar pelo modelo, 4.3.10 e 4.5)
STOP_CMD_RE = re.compile(r"^(?:lumen\s+)?(?:para|pare|pode parar|para de falar|silencio)$")
END_CMD_RE = re.compile(
    r"^(?:lumen\s+)?(?:encerr(?:a|e|ar)(?: a)? (?:chamada|conversa|ligacao)|"
    r"deslig(?:a|ue|ar)(?: a)? (?:chamada|conversa|ligacao)?|terminar chamada|sair da chamada)$"
)
REPEAT_CMD_RE = re.compile(r"^(?:lumen\s+)?(?:repete|repita|pode repetir|fala de novo|diz de novo|como assim repete)$")
SLOWER_CMD_RE = re.compile(r"^(?:lumen\s+)?(?:fala |fale )?(?:mais devagar|bem devagar|diminui(?:r)? a velocidade)$")
FASTER_CMD_RE = re.compile(r"^(?:lumen\s+)?(?:fala |fale )?(?:mais rapido|aumenta(?:r)? a velocidade)$")
QUIETER_CMD_RE = re.compile(r"^(?:lumen\s+)?(?:fala(?:r)? |fale )?(?:mais baixo|baixinho)|^(?:abaixa|baixa|diminui)(?:r)? o volume$")
LOUDER_CMD_RE = re.compile(r"^(?:lumen\s+)?(?:fala(?:r)? |fale )?(?:mais alto)|^aumenta(?:r)? o volume$")
VOICE_SWITCH_RE = re.compile(
    r"^(?:lumen\s+)?(?:fala(?:r)?|fale|conversa(?:r)?|troca(?:r)?|muda(?:r)?|usa(?:r)?)\s+"
    r"(?:com\s+|para\s+)?a\s+voz\s+(?:d[aeo]\s+)?(.+?)$"
)

# Livre/Notas por voz. Só comandos curtos e inteiros (^…$): "o que é o modo livre?", "ativar modo livre" entre aspas ou
# dentro de uma pergunta não trocam nada, porque não casam com a frase inteira.
_POLITE = r"(?:(?:lumen|por favor|pode|poderia|consegue|vamos|agora|entao|bom|ok)[,\s]+)*"
_TAIL = r"(?:\s+(?:por favor|agora|de novo|novamente|pra mim|para mim))*"
FREE_ON_RE = re.compile(
    rf"^{_POLITE}(?:ativ(?:a|e|ar)|lig(?:a|ue|ar)|entr(?:a|e|ar)\s+(?:no|em)|mud(?:a|e|ar)\s+para|pass(?:a|e|ar)\s+para|"
    rf"us(?:a|e|ar)|volt(?:a|e|ar)\s+(?:para|ao|pro))\s+(?:o\s+|no\s+)?modo\s+livre{_TAIL}$")
FREE_OFF_RE = re.compile(
    rf"^{_POLITE}(?:(?:desativ|deslig)(?:a|e|ar)|sa(?:i|ir|ia)\s+d[oa]|sair\s+do)\s+(?:o\s+)?modo\s+livre{_TAIL}$")
NOTES_ON_RE = re.compile(
    rf"^{_POLITE}(?:(?:us(?:a|e|ar)|consult(?:a|e|ar)|ativ(?:a|e|ar)|lig(?:a|ue|ar)|"
    rf"volt(?:a|e|ar)\s+(?:para|a|as|pra|pras|ao))\s+(?:as\s+|a\s+|o\s+|no\s+)?(?:minhas\s+)?notas?|"
    rf"(?:ativ(?:a|e|ar)|us(?:a|e|ar)|mud(?:a|e|ar)\s+para)\s+(?:o\s+)?modo\s+notas){_TAIL}$")
NOTES_ONLY_RE = re.compile(
    rf"^{_POLITE}(?:us(?:a|e|ar)|consult(?:a|e|ar))\s+(?:so|apenas|somente)\s+(?:o\s+|no\s+|as\s+)?(obsidian|notion|notas do obsidian|notas do notion){_TAIL}$")

# Pedidos especiais por voz (4.5)
QUIZ_EXIT_RE = re.compile(r"^(?:parar|sair|encerrar|cancelar|terminar)\s+(?:o\s+)?(?:quiz|questionario|revisao)$")
CHOICE_RE = re.compile(
    r"^(?:acho que (?:e|eh)\s+|(?:e|eh)\s+)?(?:(?:a\s+)?(?:letra|opcao|alternativa)\s+([abcde])\b|([abcde])$)"
)
ORDINAL_CHOICE = {"primeira": 0, "primeiro": 0, "segunda": 1, "segundo": 1, "terceira": 2, "terceiro": 2,
                  "quarta": 3, "quarto": 3, "quinta": 4, "quinto": 4}
MASTERY_WRONG_RE = re.compile(
    r"\bo que (?:eu )?(?:mais )?errei\b|\bmeus erros\b|\bonde (?:eu )?errei\b|\bassuntos que (?:eu )?errei\b"
)
FEYNMAN_RE = re.compile(
    r"^(?:vou te explicar|deixa eu (?:te )?explicar|quero te explicar|minha explicacao (?:sobre|de))\s+(.+)$", re.S
)
SCREEN_RE = re.compile(
    r"\b(?:olha|olhe|veja|ve|analis[ae]|leia|le)\s+(?:a\s+)?minha\s+tela\b|"
    r"\bo que (?:esta|tem|aparece) na minha tela\b"
)
REVIEW_DUE_RE = re.compile(
    r"\brevisao d[eo] (?:dia|hoje)\b|\bo que (?:eu )?tenho para revisar\b|\bcartoes (?:de hoje|para revisar)\b"
)
SAVE_RE = re.compile(
    r"\b(?:salv(?:a|e|ar)|guard(?:a|e|ar)|cri(?:a|e|ar)\s+(?:uma\s+)?(?:nota|pagina))\b.*\b(obsidian|notion)\b"
)

_ASR_LOCK = threading.Lock()
_ASR_MODELS = {}
_asr_used = 0.0  # última fala reconhecida (time.monotonic): sem chamada por transcribe.IDLE_S, os modelos saem da memória
_TTS_WARM = threading.Event()   # esta execução do Lúmen já sintetizou ao menos uma frase com a voz do Voice Studio
_FILLER_CACHE = {}  # {(voice_id, steps, text): (wav_bytes, seconds)} só na memória (máx. 16 entradas)


# --- Texto: frase inacabada, símbolos para a fala, fontes ------------------------------------------------------

# Palavras que quase nunca terminam uma frase em português: o estudante parou para pensar, não acabou de falar.
CONTINUATION = frozenset(
    "e ou mas porque pois que se quando como entao tipo de da do das dos em na no nas nos para pra com por a o as os "
    "um uma uns umas ao aos pelo pela sobre entre ate onde qual quais quem tambem ainda alem sem desde durante apos "
    "antes depois enquanto embora porem contudo logo assim ai".split())


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text or "").casefold()) if not unicodedata.combining(c))


def looks_unfinished(text, punctuation=True):
    """True quando a transcrição parece parar no meio: vírgula, reticências, travessão, uma palavra de ligação no fim
    ("…como funciona o") ou, em quatro palavras ou mais, nenhuma pontuação final. Medido (08/11/2026, 10 falas sintéticas
    completas e 10 cortes): o Parakeet fecha toda fala completa com "." ou "?", então a falta de pontuação final sugere áudio
    cortado; o ponto final em si não prova nada (ele o põe até em corte no meio). "?" e "!" fecham a frase."""
    t = str(text or "").strip()
    if not t:
        return False
    if t[-1] in "?!":
        return False
    if re.search(r"(?:[,;:—–-]|\.\.\.|…)\s*$", t):
        return True
    words = re.findall(r"[a-z0-9]+", fold(t))
    if words and words[-1] in CONTINUATION:
        return True
    return punctuation and len(words) >= 4 and t[-1] not in ".!?…"


_SYMBOL_WORDS = (
    (r"(\d)\s*%", r"\1 por cento"), (r"%", " por cento"), (r"\s*[→⇒➜➔]\s*", ", "), (r"\s*[←⇐]\s*", ", "),
    (r"\s*≈\s*", " aproximadamente "), (r"\s*≠\s*", " diferente de "), (r"\s*[≤]\s*", " menor ou igual a "),
    (r"\s*[≥]\s*", " maior ou igual a "), (r"(\d)\s*[x×]\s*(\d)", r"\1 vezes \2"), (r"\s*×\s*", " vezes "),
    (r"\s*÷\s*", " dividido por "), (r"\s*=\s*", " igual a "), (r"\s*&\s*", " e "), (r"(\d)\s*°\s*C\b", r"\1 graus Celsius"),
    (r"(\d)\s*°", r"\1 graus"), (r"(?<=\d)\s*\+\s*(?=\d)", " mais "), (r"\bkm\s*/\s*h\b", "quilômetros por hora"),
    (r"\bm\s*/\s*s\b", "metros por segundo"), (r"\b[eE]\s*/\s*ou\b", "e ou"),
    (r"\b([^\W\d_]{3,})\s*/\s*([^\W\d_]{3,})\b", r"\1 ou \2"), (r"(?<=\w)\s*/\s*(?=\w)", " "),
    (r"\s*[·•▪◦]\s*", ", "), (r"[​-‏﻿]", ""), (r"[_~^`|<>{}\[\]\\]", " "), (r"\s*\(\s*\)", ""),
)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


def speech_text(text, clause=False):
    """O que realmente vai para a síntese: `voice.speakable` (sem Markdown, [S#], código e URLs) mais símbolos lidos como
    palavras ("%", "=", "→") e sem emojis, para a voz não soletrar nem tropeçar. `clause`: o trecho é só o começo de uma
    frase (cortado numa vírgula ou conjunção para a voz sair mais cedo); termina em vírgula, não em ponto, para a entonação
    seguir para o trecho seguinte em vez de "cair" como numa frase acabada."""
    t = _EMOJI.sub("", voice.speakable(text))
    for pat, rep in _SYMBOL_WORDS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\s{2,}", " ", re.sub(r"\s+([,.;:!?])", r"\1", t)).strip(" ,")
    if clause and t.endswith(".") and str(text).rstrip()[-1:] not in ".!?…":
        t = t[:-1].rstrip() + ","
    return t


# Tamanho máximo (em caracteres) do 1º, 2º e 3º pedaço falado; depois, CHUNK_REST. Sem o modelo de texto disputando a GPU, a síntese leva
# ~0,9 s + ~0,22 s por segundo de fala (12 passos; medido em 08/11/2026) e só não deixa a voz muda se o pedaço seguinte for sintetizado
# ANTES de o anterior acabar de tocar. Depois de um 1º pedaço de ~2 s de fala, um 2º de 10 s fazia a voz parar por 0,4 a 1,5 s (medido);
# a partir do 3º, o áudio já à frente cobre pedaços maiores.
CHUNK_CHARS = (64, 60, 110)
CHUNK_REST = 150


def chunk_limit(i):
    return CHUNK_CHARS[i] if i < len(CHUNK_CHARS) else CHUNK_REST


def split_chunk(text, limit):
    """Quebra `text` em (pedaço, resto) com o pedaço de até `limit` caracteres: na vírgula, ponto e vírgula ou dois-pontos mais
    perto do limite; sem pontuação útil, no último espaço (nunca no meio de palavra). O pedaço que não fecha a frase termina em
    vírgula, para a entonação seguir para o pedaço seguinte. Texto que cabe no limite volta inteiro, com resto vazio."""
    text = text.strip()
    if len(text) <= limit:
        return text, ""
    window = text[:limit + 1]
    cut = max(window.rfind(", "), window.rfind("; "), window.rfind(": "))
    if cut >= limit * 0.4:
        return text[:cut + 1].strip(), text[cut + 1:].strip()
    sp = window.rfind(" ")
    if sp < limit * 0.5:
        sp = text.find(" ", limit)
        if sp < 0:
            return text, ""
    return text[:sp].rstrip(" ,;:") + ",", text[sp:].strip()


def clean_sources(value):
    """None = todas as fontes; senão, só as que existem (notion/obsidian/files), sem repetir. Lista vazia ou inválida = erro."""
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise AppError("Fontes inválidas.", "Use Notion, Obsidian ou arquivos.")
    out = []
    for x in value:
        if x not in VAULT_SOURCES:
            raise AppError("Fonte desconhecida.", "Use Notion, Obsidian ou arquivos.")
        if x not in out:
            out.append(x)
    if not out:
        raise AppError("Escolha ao menos uma fonte de notas, ou use o modo livre.")
    return out


# --- VAD, cancelamento de eco e som de "entendi" ---------------------------------------------------------------------

class EnergyVAD:
    """Reserva leve caso o Silero ONNX não esteja disponível (ex.: ambiente de teste isolado)."""

    def __init__(self, threshold=0.015):
        self.threshold = threshold

    def reset(self):
        pass

    def prob(self, frame):
        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        return min(1.0, rms / max(self.threshold, 1e-4) * 0.6)


class SileroVAD:
    """Silero VAD v5 em ONNX na CPU (1 thread, ~0,14 ms por quadro de 32 ms em 16 kHz)."""

    def __init__(self, model_path):
        import onnxruntime
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.sess = onnxruntime.InferenceSession(str(model_path), sess_options=opts,
                                                 providers=["CPUExecutionProvider"])
        self.sr = np.array(16000, dtype=np.int64)
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)

    def prob(self, frame):
        x = np.asarray(frame, dtype=np.float32).reshape(1, 512)
        inp = np.concatenate((self.context, x), axis=1)
        out, self.state = self.sess.run(None, {"input": inp, "state": self.state, "sr": self.sr})
        self.context = x[:, -64:]
        return float(np.asarray(out).squeeze())


def load_vad():
    try:
        path = Path(transcribe._onnx_dir("silero")) / "silero_vad.onnx"
        if path.is_file():
            return SileroVAD(path)
    except Exception:  # noqa: BLE001 — recua para energia em ambiente de teste sem modelos
        pass
    return EnergyVAD()


class EchoGuard:
    """Desconta o que está saindo na caixa de som (`pyaec` SpeexDSP em 16 kHz) + barreira de energia calibrada nas
    primeiras frases faladas da chamada (4.4)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.ref_buf = np.zeros(0, dtype=np.float32)
        self.ref_frames = deque(maxlen=40)
        self.echo_ratio = 0.25
        self.calibrated = 0
        self.aec = None
        try:
            import pyaec
            self.aec = pyaec.Aec(512, 3200, 16000, True)
        except Exception:  # noqa: BLE001 — barreira de energia continua ativa mesmo sem pyaec
            self.aec = None

    def reset(self):
        with self.lock:
            self.ref_buf = np.zeros(0, dtype=np.float32)
            self.ref_frames.clear()

    def push_speaker_24k(self, samples_24k):
        """Recebe amostras em 24 kHz enviadas ao alto-falante e guarda quadros de 512 amostras em 16 kHz."""
        a = np.asarray(samples_24k, dtype=np.float32).reshape(-1)
        if a.size == 0:
            return
        # 24 kHz → 16 kHz (proporção exata 3:2) por interpolação linear rápida
        n16 = int(round(a.size * 16000 / PLAY_SR))
        if n16 <= 0:
            return
        idx = np.linspace(0, a.size - 1, n16, dtype=np.float32)
        f16 = np.interp(idx, np.arange(a.size, dtype=np.float32), a).astype(np.float32)
        with self.lock:
            self.ref_buf = np.concatenate((self.ref_buf, f16)) if self.ref_buf.size else f16
            while self.ref_buf.size >= 512:
                self.ref_frames.append(self.ref_buf[:512])
                self.ref_buf = self.ref_buf[512:]

    def process(self, mic_frame_512, headphones=False):
        """Devolve `(clean_frame, rms_clean, rms_ref, above_barrier)`."""
        mic = np.asarray(mic_frame_512, dtype=np.float32).reshape(512)
        with self.lock:
            ref = self.ref_frames.popleft() if self.ref_frames else None
        if ref is None:
            rms = float(np.sqrt(np.mean(mic * mic)))
            return mic, rms, 0.0, rms >= 0.012
        rms_ref = float(np.sqrt(np.mean(ref * ref)))
        if headphones:
            rms = float(np.sqrt(np.mean(mic * mic)))
            return mic, rms, rms_ref, rms >= 0.012
        clean = mic
        if self.aec is not None and rms_ref > 1e-4:
            mic_i16 = np.clip(mic * 32767.0, -32768, 32767).astype(np.int16)
            ref_i16 = np.clip(ref * 32767.0, -32768, 32767).astype(np.int16)
            out_i16 = np.asarray(self.aec.cancel_echo(mic_i16, ref_i16), dtype=np.int16)
            clean = out_i16.astype(np.float32) / 32768.0
        rms_clean = float(np.sqrt(np.mean(clean * clean)))
        # Calibra o acoplamento acústico nos primeiros quadros de eco puro (quando o resíduo ainda é moderado)
        if rms_ref > 0.015 and self.calibrated < 25 and rms_clean < max(0.06, rms_ref * 0.9):
            obs = max(0.05, min(0.85, rms_clean / max(rms_ref, 1e-4)))
            self.echo_ratio = 0.85 * self.echo_ratio + 0.15 * obs
            self.calibrated += 1
        gate = max(0.022, rms_ref * self.echo_ratio * 2.2)
        return clean, rms_clean, rms_ref, rms_clean > gate


def make_earcon(sr=PLAY_SR):
    """Som curto e suave de 'entendi' (~95 ms, duas notas ascendentes suaves com envelope Hann, sem clique)."""
    n1, n2 = int(sr * 0.045), int(sr * 0.050)
    t1 = np.arange(n1, dtype=np.float32) / sr
    t2 = np.arange(n2, dtype=np.float32) / sr
    tone1 = np.sin(2.0 * np.pi * 528.0 * t1) * np.hanning(n1)
    tone2 = np.sin(2.0 * np.pi * 660.0 * t2) * np.hanning(n2)
    return (np.concatenate((tone1, tone2)) * 0.075).astype(np.float32)


EARCON_PCM = make_earcon()


def wav_to_float24k(wav_bytes):
    """Converte WAV PCM em `np.float32` mono em 24 kHz para tocar pelo `loopback.speaker`."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != PLAY_SR and a.size > 1:
        n24 = int(round(a.size * PLAY_SR / sr))
        a = np.interp(np.linspace(0, a.size - 1, n24, dtype=np.float32),
                      np.arange(a.size, dtype=np.float32), a).astype(np.float32)
    return a


# --- Transcrição em memória da chamada (sem tocar em disco nem soltar a VRAM do Ollama/OmniVoice) --------------------

def pick_call_asr(choice):
    """Escolhe entre Parakeet (CPU int8) e Whisper turbo (GPU) conforme o ajuste e a VRAM livre na hora."""
    parakeet_ok = transcribe.downloaded(transcribe.PARAKEET)
    free = transcribe.gpu_free_gb() if transcribe.has_gpu() else None
    if choice == "parakeet":
        if parakeet_ok:
            return "parakeet"
    elif choice == "whisper":
        if transcribe.has_gpu() and (("whisper", "large-v3-turbo") in _ASR_MODELS or free is None or free >= 2.6):
            if transcribe.downloaded("large-v3-turbo"):
                return "whisper"
        if parakeet_ok:
            return "parakeet"
    # Automático: com Ollama + OmniVoice na RTX 3060 de 12 GB sobram ~3,8 GB antes do pico de geração (+2,2 GB), então
    # o Parakeet na CPU (0 MB de VRAM, ~212 ms mediana) é preferido; com >= 6,5 GB livres ou sem Parakeet, usa Whisper.
    if parakeet_ok and (free is None or free < 6.5):
        return "parakeet"
    if transcribe.has_gpu() and (free is None or free >= 2.6) and transcribe.downloaded("large-v3-turbo"):
        return "whisper"
    if parakeet_ok:
        return "parakeet"
    return "whisper_cpu"


def _load_call_asr(kind):
    if kind == "parakeet":
        if ("parakeet", "cpu") not in _ASR_MODELS:
            import onnx_asr
            import onnxruntime
            opts = onnxruntime.SessionOptions()
            opts.intra_op_num_threads = transcribe.cpu_threads(transcribe.PARAKEET)
            _ASR_MODELS[("parakeet", "cpu")] = onnx_asr.load_model(
                "nemo-parakeet-tdt-0.6b-v3", transcribe._onnx_dir(transcribe.PARAKEET),
                quantization="int8", sess_options=opts, providers=["CPUExecutionProvider"]
            )
        return _ASR_MODELS[("parakeet", "cpu")]
    if kind == "whisper":
        key = ("whisper", "large-v3-turbo")
        if key not in _ASR_MODELS:
            from faster_whisper import WhisperModel
            _ASR_MODELS[key] = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16",
                                            cpu_threads=transcribe.cpu_threads(), local_files_only=True)
        return _ASR_MODELS[key]
    key = ("whisper", "small")
    if key not in _ASR_MODELS:
        from faster_whisper import WhisperModel
        _ASR_MODELS[key] = WhisperModel("small", device="cpu", compute_type="int8",
                                        cpu_threads=transcribe.cpu_threads(), local_files_only=True)
    return _ASR_MODELS[key]


def transcribe_call_audio(audio_16k, choice="auto"):
    """Transcreve `audio_16k` (`np.float32` 16 kHz) direto da memória: `(texto, ms, motor_usado)`."""
    a = np.asarray(audio_16k, dtype=np.float32).reshape(-1)
    if a.size < int(16000 * 0.22) or float(np.abs(a).max()) < 0.003:
        return "", 0.0, "none"
    global _asr_used
    t0 = _asr_used = time.monotonic()
    with _ASR_LOCK:
        kind = pick_call_asr(choice)
        model = _load_call_asr(kind)
        if kind == "parakeet":
            res = model.recognize(a, sample_rate=16000, language="pt")
            text = res if isinstance(res, str) else getattr(res, "text", str(res or ""))
        else:
            segs, _ = model.transcribe(a, language="pt", beam_size=1, vad_filter=False,
                                       condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segs if getattr(s, "text", "").strip())
    ms = (time.monotonic() - t0) * 1000.0
    return " ".join(str(text).split()).strip(), round(ms, 1), kind


def release_idle():
    """Chamada a cada segundo pelo laço de lumen/__main__.py: sem chamada aberta e sem fala há transcribe.IDLE_S, o
    Parakeet (~0,7 GB de RAM) e o Whisper da chamada (VRAM) saem da memória. A próxima chamada os carrega de novo
    enquanto mostra "Preparando" (_warm_asr_safe); o Voice Studio também já terá desligado sozinho nesse prazo."""
    if _ASR_MODELS and not CALL.active and time.monotonic() - _asr_used > transcribe.IDLE_S and _ASR_LOCK.acquire(False):
        try:
            _ASR_MODELS.clear()
        finally:
            _ASR_LOCK.release()
        import gc
        gc.collect()


# --- Auxiliares de cartões e quiz por voz ----------------------------------------------------------------------------

def card_speech(item):
    """Fala curta comentando um cartão visual gerado na chamada (4.1 e 4.5)."""
    kind, d = item.get("kind"), item.get("data") or {}
    if kind == "mindmap":
        n = sum(1 for x in (d.get("diagram") or {}).get("nodes") or [] if x.get("parent", -1) < 0)
        return f"Pronto, o mapa mental tem {n} {'ramo' if n == 1 else 'ramos'}; está na tela."
    if kind == "flashcards":
        n = len(d.get("cards") or [])
        return f"Pronto, criei {n} {'cartão' if n == 1 else 'cartões'}; estão na tela."
    if kind == "plan":
        n = len(d.get("steps") or [])
        return f"Pronto, montei o plano de estudo com {n} {'etapa' if n == 1 else 'etapas'}; está na tela."
    if kind == "map":
        return "Pronto, o mapa conceitual está na tela."
    if kind == "gaps":
        n = len(d.get("missing") or [])
        return f"Pronto, encontrei {n} {'assunto' if n == 1 else 'assuntos'} para reforçar; o quadro está na tela."
    return "Pronto, o material está na tela."


def quiz_question_speech(q, idx, total):
    head = f"Pergunta {idx + 1} de {total}: {voice.speakable(q.get('question') or '')}"
    if q.get("kind") == "multipla" and q.get("options"):
        letters = "ABCDE"
        opts = "; ".join(f"{letters[i]}) {voice.speakable(opt)}" for i, opt in enumerate(q["options"][:5]))
        return f"{head} As opções são: {opts}."
    if q.get("kind") == "vf":
        return f"{head} Verdadeiro ou falso?"
    return head


def map_quiz_spoken_answer(q, text):
    """Converte 'letra B', 'a segunda', 'verdadeiro' ou 'não sei' na resposta que `learn.answer` espera."""
    if learn.is_dont_know(text):
        return text
    f = search._fold(text).strip(" .,!?")
    if q.get("kind") == "multipla" and q.get("options"):
        opts = q["options"]
        for word, idx in ORDINAL_CHOICE.items():
            if re.search(rf"\b{word}\b", f) and idx < len(opts):
                return opts[idx]
        m = CHOICE_RE.match(f)
        if m:
            letter = m.group(1) or m.group(2)
            idx = "abcde".index(letter)
            if idx < len(opts):
                return opts[idx]
        for opt in opts:
            of = search._fold(opt).strip(" .,!?")
            if of and (f == of or (len(f) >= 4 and f in of)):
                return opt
    elif q.get("kind") == "vf":
        if re.search(r"\bverdadeir[oa]\b", f) and not re.search(r"\bfals[oa]\b", f):
            return "Verdadeiro"
        if re.search(r"\bfals[oa]\b", f) and not re.search(r"\bverdadeir[oa]\b", f):
            return "Falso"
    return text


# --- Execução especulativa (resposta antecipada, 4.3.5) ---------------------------------------------------------------

class SpeculativeTurn:
    """Roda transcrição + busca + começo do modelo durante o silêncio (250 ms), retendo tudo na memória até o fim da
    fala confirmar (`commit_gate`). Cancelado antes disso, nada vai para o banco, para o disco ou para a tela."""

    def __init__(self, audio_16k, vault=None, profile=""):
        self.audio = audio_16k
        self.vault = vault or {"free": False, "sources": None}   # a fotografia de Livre/Notas em que ELA nasceu
        self.profile = profile
        self.cancel_ev = threading.Event()
        self.commit_gate = threading.Event()
        self.asr_done = threading.Event()
        self.turn_id = "call-spec-" + uuid.uuid4().hex[:12]
        self.text = ""
        self.asr_ms = 0.0
        self.asr_engine = "none"
        self.kind = "none"      # "agent" | "special" | "empty"
        self.events = queue.Queue()
        self.llm_started_at = None
        self.llm_first_at = None
        self.started_at = time.monotonic()
        self.thread = None

    def cancel(self):
        self.cancel_ev.set()
        agent.cancel(self.turn_id)


class Turn:
    """Tudo o que pertence a UM turno da chamada: o cancelamento, a fotografia de Livre/Notas, o que foi falado e a
    mensagem salva. Cada thread do turno (transcrição, modelo, síntese, reprodução) guarda o SEU `Turn`; um turno novo é
    outro objeto, então o que sobrou do antigo continua cancelado para sempre: nunca fala, escreve na legenda nem muda o
    estado no turno seguinte (antes, um `Event` único era "limpo" pelo turno novo e a síntese atrasada do antigo revivia)."""

    def __init__(self, vault, profile=""):
        self.id = "call-" + uuid.uuid4().hex[:12]
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.vault = vault               # {"free": bool, "sources": [...] | None}: vale só para este turno
        self.profile = profile
        self.spoken = []                 # frases tocadas até o fim
        self.current = ""                # a frase que está tocando
        self.frac = 0.0                  # quanto dela já tocou
        self.generated = []              # tudo o que o modelo escreveu (pode ser mais do que foi falado)
        self.mid = None                  # mensagem do assistente salva no histórico
        self.sources = []
        self.agent_id = None             # id do turno no agent.turn (para cancelar o modelo)
        self.marks = {}                  # etapa do agente → instante em que realmente começou
        self.created = time.monotonic()
        self.finalized = False           # a interrupção já foi registrada no histórico
        self.audio = None                # a fala que fechou este turno (some quando o 1º som toca): serve para mesclar uma retomada
        self.user_mid = None             # a pergunta salva no histórico por este turno
        self.plain = False               # turno comum pelo agente (os especiais e os comandos nunca são mesclados)

    @property
    def alive(self):
        return not self.cancel.is_set()


# --- Gerenciador da chamada (uma por vez) ----------------------------------------------------------------------------

class CallManager:
    def __init__(self, *, mic=None, mic_open=None, speaker_factory=None, vad_factory=None, asr_fn=None,
                 turn_fn=None, synth_fn=None, warm_fn=None, persist_settings=True):
        self._lock = threading.RLock()
        self._speaker_lock = threading.Lock()
        self._subs = []
        self._seq = 0
        self._ring = deque(maxlen=RING)
        self._tl = threading.local()     # o `Turn` da thread atual (só threads de turno)
        self._custom_mic = mic
        self._mic_open = mic_open
        self._custom_speaker = speaker_factory
        self._custom_vad = vad_factory
        self._custom_asr = asr_fn
        self._custom_turn = turn_fn
        self._custom_synth = synth_fn
        self._warm_fn = warm_fn
        self._persist_settings = persist_settings

        self.active = False
        self.state = "ended"
        self.muted = False
        self.ptt_active = False
        self.volume = 1.0
        self.conversation_id = None
        self.project_id = None
        self.temporary = False
        self.who = None
        self.started_at = 0.0
        self.last_activity = 0.0
        self.turn_count = 0
        self.last_spoken_answer = ""
        # Livre/Notas e perfil da CHAMADA: vêm da tela ao abrir e mudam durante a chamada; cada turno tira uma fotografia
        self.vault_free = False
        self.vault_sources = None
        self.profile = ""
        self.phase = ""                  # etapa real do agente durante "thinking" (PHASE_LABELS)
        self.ready_ms = None
        self._mic_failures = 0
        self._started_mono = 0.0
        self._last_frame_at = 0.0

        self._vad = None
        self._echo = EchoGuard()
        self._turn_frames = []
        self._speech_frames = 0
        self._silence_frames = 0
        self._barge_frames = 0
        self._last_speech_at = 0.0
        self._last_partial_at = 0.0
        self._partial_busy = False
        self._partial_text = ""
        self._prefetched = None
        self._last_mic_emit = 0.0
        self._last_voice_emit = 0.0

        self._spec = None
        self._turn = None                # o `Turn` em andamento (ou o último)
        self._committed_at = 0.0
        self._barge_len = 0
        self._barge_pending = False     # uma interrupção por voz está em andamento: os quadros do microfone esperam aqui
        self._barge_buf = []
        self._barge_since = 0.0
        self._worker = None
        self._watchdog = None

        self._quiz = None
        self._review = None
        self._feynman_topic = None
        self._s = None

    @property
    def _mic(self):
        return self._custom_mic or listen.MIC

    def _speaker_factory(self):
        return self._custom_speaker() if self._custom_speaker is not None else loopback.speaker(PLAY_SR, 1, buffer_ms=80)

    def _vad_factory(self):
        return self._custom_vad() if self._custom_vad is not None else load_vad()

    def _asr_fn(self, audio_16k, choice="auto"):
        return (self._custom_asr or transcribe_call_audio)(audio_16k, choice)

    def _turn_fn(self, payload, turn_id):
        return (self._custom_turn or agent.turn)(payload, turn_id)

    def _synth_fn(self, sentence, w, s, steps, seed, check, work_dir=None, eng=None):
        return (self._custom_synth or listen.synth_sentence)(sentence, w, s, steps, seed, check, work_dir, eng)

    # --- Assinantes de eventos NDJSON (/api/study/call/events) ---

    def subscribe(self, since=None):
        """Novo assinante. Com `since` (o `seq` do último evento que a tela recebeu), reenvia primeiro o que ela perdeu
        enquanto reconectava e só depois o estado atual: a tela descarta `seq` repetido, então nada é falado ou
        escrito duas vezes. Sem `since` (ou fora do que foi guardado), só o estado atual."""
        q = queue.Queue(maxsize=600)
        with self._lock:
            self._subs.append(q)
            if since is not None:
                for ev in self._ring:
                    if ev.get("seq", 0) > since:
                        q.put_nowait(ev)
            snap = self._state_event()
            self._seq += 1
            snap["seq"] = self._seq
        q.put(snap)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _emit(self, ev):
        """Entrega o evento a todos os assinantes. Evento de um turno já cancelado é descartado aqui, no ponto único de
        saída: a síntese, o modelo ou o reconhecimento atrasados do turno antigo não chegam à tela."""
        turn = getattr(self._tl, "turn", None)
        if turn is not None:
            if turn.cancel.is_set():
                return
            ev.setdefault("turn_id", turn.id)
        with self._lock:
            self._seq += 1
            ev["seq"] = self._seq
            if ev.get("type") not in ("level", "ping"):
                self._ring.append(ev)
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(ev)
                except queue.Empty:
                    pass

    def _vault_snapshot(self):
        return {"free": bool(self.vault_free), "sources": list(self.vault_sources) if self.vault_sources else None}

    def _state_event(self):
        label = "Microfone mudo" if self.muted and self.state == "listening" else STATE_LABELS.get(self.state, self.state)
        if self.state == "thinking" and self.phase in PHASE_LABELS:
            label = PHASE_LABELS[self.phase]
        turn = self._turn
        busy = self.state in ("end_of_speech", "transcribing", "thinking", "speaking")
        now_vault = self._vault_snapshot()
        return {
            "type": "state",
            "active": self.active,
            "state": self.state,
            "phase": self.phase if self.state == "thinking" else "",
            "label": label,
            "muted": self.muted,
            "ptt": self.ptt_active,
            "mode": (self._s or {}).get("call_mode", "handsfree"),
            "captions": bool((self._s or {}).get("call_captions", True)),
            "timings": bool((self._s or {}).get("call_timings", False)),
            "who": self.who,
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "temporary": bool(self.temporary),
            "started_at": self.started_at,
            "quiz_active": bool(self._quiz),
            # Livre/Notas: o que vale a partir do PRÓXIMO turno e o que o turno em andamento usa (se for outro)
            "vault": now_vault,
            "vault_turn": turn.vault if (busy and turn is not None) else None,
            "vault_pending": bool(busy and turn is not None and turn.vault != now_vault),
            "profile": self.profile,
            "ready_ms": self.ready_ms,
        }

    def _set_state(self, st, phase=""):
        turn = getattr(self._tl, "turn", None)
        if turn is not None and (turn.cancel.is_set() or turn is not self._turn):
            return   # um turno antigo não muda o estado do turno atual
        with self._lock:
            if not self.active and st != "ended":
                return
            if st == self.state and phase == self.phase and st != "thinking":
                return
            self.state = st
            self.phase = phase if st == "thinking" else ""
            ev = self._state_event()
        self._emit(ev)

    def snapshot(self):
        with self._lock:
            ev = self._state_event()
        ev.pop("type", None)
        return ev

    # --- Ciclo de vida da chamada ---

    def start(self, conversation_id=None, project_id=None, temporary=None, free=None, sources=None, profile=None):
        """Abre a chamada. `free`/`sources`/`profile` vêm da tela e são os MESMOS do chat escrito (skip_vault, vault_sources,
        profile): a chamada nasce no modo em que o estudante estava digitando."""
        if record.active():
            raise AppError("Uma aula está sendo gravada.", "Pare a gravação para iniciar uma conversa por voz.")
        sources = clean_sources(sources) if free is not True else None
        if profile not in (None, "", "main", "adult"):
            raise AppError("Perfil inválido.")
        with self._lock:
            if self.active:
                return self.snapshot()
            full_s = settings.load()
            vs = dict(full_s["voice"])
            if vs["engine"] == "off":
                raise AppError("A voz está desligada.", "Ligue em Estudos → Configurações → Voz.")
            self._s = vs
            self.active = True
            self.muted = False
            self.ptt_active = False
            self.volume = 1.0
            self.started_at = time.time()
            self._started_mono = time.monotonic()
            self.ready_ms = None
            self.last_activity = time.monotonic()
            self._last_frame_at = time.monotonic()
            self._mic_failures = 0
            self.turn_count = 0
            self.last_spoken_answer = ""
            self.vault_free = bool(free)
            self.vault_sources = sources
            self.profile = profile or ""
            self.phase = ""
            self._turn = None
            self._quiz = None
            self._review = None
            self._feynman_topic = None
            self._turn_frames = []
            self._speech_frames = 0
            self._silence_frames = 0
            self._barge_frames = 0
            self._partial_text = ""
            self._prefetched = None
            self._ring.clear()
            self._echo.reset()

            is_temp = (bool(temporary) if temporary is not None else (vs["call_save"] == "temporary")) or not full_s["memory"]["history"]
            if conversation_id:
                conv = chats.get(conversation_id, with_messages=False)
                self.conversation_id = conv["id"]
                self.project_id = conv.get("project_id")
                self.temporary = bool(conv.get("temporary", False))
            else:
                self.conversation_id = None
                self.project_id = project_id or None
                self.temporary = is_temp
            self.state = "preparing"
            self.who = None

        providers.KEEP_ALIVE = "30m"
        self._emit(self._state_event())

        try:
            self._vad = self._vad_factory()
            self._vad.reset()
            self._mic.start_continuous(self._on_mic_frame, mic_id=vs.get("call_mic", ""), open_mic=self._mic_open)
        except Exception:
            self._cleanup_after_stop()
            raise

        threading.Thread(target=self._warm_and_ready, daemon=True, name="Lumen call warm").start()
        self._watchdog = threading.Thread(target=self._idle_loop, daemon=True, name="Lumen call idle")
        self._watchdog.start()
        return self.snapshot()

    def _warm_and_ready(self):
        try:
            if self._warm_fn is not None:
                self.who = self._warm_fn(self._s, self._emit)
            else:
                llm_t = threading.Thread(target=lambda: providers.warm_local(keep_alive="30m"), daemon=True)
                asr_t = threading.Thread(target=self._warm_asr_safe, daemon=True)
                llm_t.start()
                asr_t.start()
                if self._s["engine"] == "voicestudio":
                    for ev in listen._prepare(self._s, lambda: (_ for _ in ()).throw(Cancelled()) if not self.active else None):
                        self._emit(ev)
                self.who = listen.who("call", self._s)
                self._warm_first_sound(self.who)
                llm_t.join(timeout=5.0)
                asr_t.join(timeout=2.0)
            # "Ouvindo" só aparece com o microfone entregando áudio de verdade (abrir o aparelho não basta)
            if hasattr(self._mic, "last_frame_at"):
                end = time.monotonic() + 4.0
                while self.active and getattr(self._mic, "last_frame_at", None) is None and time.monotonic() < end:
                    time.sleep(0.02)
                if self.active and getattr(self._mic, "last_frame_at", None) is None:
                    raise AppError("O microfone abriu, mas não está enviando som.",
                                   "Confira o microfone em Configurações → Voz ou nas configurações de som do Windows.")
            if self.active and self.state == "preparing":
                self.last_activity = time.monotonic()
                self.ready_ms = round((time.monotonic() - self._started_mono) * 1000.0, 1)
                self._set_state("listening")
        except Cancelled:
            pass
        except AppError as e:
            self._emit({"type": "error", "message": str(e), "action": e.action})
            self.stop(reason="error")
        except Exception as e:  # noqa: BLE001
            log.warning("aquecimento da chamada: %s: %s", type(e).__name__, e)
            self._emit({"type": "error", "message": "Não foi possível preparar a voz da chamada.", "action": ""})
            self.stop(reason="error")

    def _warm_asr_safe(self):
        """Carrega o reconhecedor E faz uma inferência de mentira: medido (08/11/2026), a 1ª inferência do Parakeet depois
        de carregar levou ~4 s (o ONNX monta o plano de execução nela); sem isto, quem pagava era a 1ª fala do estudante."""
        try:
            choice = self._s.get("call_asr", "auto")
            with _ASR_LOCK:
                _load_call_asr(pick_call_asr(choice))
            dummy = np.zeros(16000, dtype=np.float32)
            dummy[1000:6000] = 0.05 * np.sin(2 * np.pi * 220 * np.arange(5000, dtype=np.float32) / 16000.0)
            transcribe_call_audio(dummy, choice)
        except Exception:  # noqa: BLE001
            pass

    def _warm_first_sound(self, who):
        """O 1º som de uma voz recém-subida custa muito mais que os seguintes (o motor monta o que falta na 1ª frase;
        medido: minutos num arranque a frio). Fazer isso aqui, com a tela dizendo "Aquecendo a voz…", tira o custo da 1ª
        resposta. Uma vez por execução do Lúmen: com a voz já aquecida, a chamada abre sem esta espera."""
        if _TTS_WARM.is_set():
            return
        s_tts = {**self._s, "speed": self._s.get("call_speed", 1.0), "cache_mb": 0}
        steps = listen.STEPS.get(s_tts.get("call_quality", "balanced"), 12) if who["engine"] == "voicestudio" else None
        self._emit({"type": "preparing", "phase": "first_sound", "label": "Aquecendo a voz…"})

        def check():
            if not self.active:
                raise Cancelled()

        self._synth_fn("Pronto.", who, s_tts, steps, listen.seeds(s_tts)[0], check, None, listen.engine_for(who, s_tts, steps))
        _TTS_WARM.set()

    def _idle_loop(self):
        while self.active:
            time.sleep(0.5)
            if not self.active:
                break
            self._watch_mic()
            mins = int((self._s or {}).get("call_autostop") or 0)
            if mins > 0 and self.state == "listening" and (time.monotonic() - self.last_activity) >= mins * 60:
                self._emit({"type": "status_note", "text": f"Chamada encerrada após {mins} min em silêncio."})
                self.stop(reason="autostop")
                break

    # --- Microfone perdido (aparelho desligado ou trocado) ---

    def _watch_mic(self):
        """O fluxo do microfone morreu, ou parou de entregar quadros: tenta reabrir (até 3 vezes) e, se não der, encerra
        com a mensagem certa em vez de ficar "ouvindo" para sempre."""
        if not self.active or self.state in ("preparing", "ended", "reconnecting"):
            return
        busy = getattr(self._mic, "busy", None)
        dead = bool(busy) and not busy()
        last = getattr(self._mic, "last_frame_at", None)
        stalled = last is not None and (time.monotonic() - last) > MIC_STALL_S
        if dead or stalled:
            self._reconnect_mic()

    def _reconnect_mic(self):
        prev = self.state
        # um turno em andamento termina em paz (a resposta falada segue); só o ouvir fica indisponível por instantes
        if prev not in ("speaking", "thinking", "transcribing", "end_of_speech"):
            self._set_state("reconnecting")
        self._emit({"type": "status_note", "text": "O microfone parou de responder. Tentando reconectar…"})
        for attempt in range(3):
            if not self.active:
                return
            try:
                self._mic.stop()
                self._mic.start_continuous(self._on_mic_frame, mic_id=(self._s or {}).get("call_mic", ""), open_mic=self._mic_open)
                self._last_frame_at = time.monotonic()
                self._mic_failures = 0
                self._turn_frames, self._speech_frames, self._silence_frames = [], 0, 0
                if self.state == "reconnecting":
                    self._set_state("listening")
                self._emit({"type": "status_note", "text": "Microfone reconectado."})
                return
            except Exception as e:  # noqa: BLE001
                log.warning("reconexão do microfone (%d/3): %s", attempt + 1, type(e).__name__)
                time.sleep(MIC_RETRY_S)
        self._emit({"type": "error", "message": "O microfone não está disponível.",
                    "action": "Conecte o aparelho de novo ou escolha outro em Configurações → Voz e inicie outra chamada."})
        self.stop(reason="mic")

    def _cleanup_after_stop(self):
        with self._lock:
            self.active = False
            self.state = "ended"
            self.phase = ""
            spec, self._spec = self._spec, None
            turn = self._turn
        if turn:
            turn.cancel.set()
            if turn.agent_id:
                agent.cancel(turn.agent_id)
        if spec:
            spec.cancel()
        self._mic.stop()
        self._turn_frames = []
        providers.KEEP_ALIVE = "10m"
        self._emit(self._state_event())

    def stop(self, reason="user"):
        cid = self.conversation_id
        if self.active:
            turn = self._turn
            if turn is not None and self.state in ("speaking", "thinking", "transcribing", "end_of_speech"):
                turn.cancel.set()               # primeiro para o áudio e o modelo; depois guarda só o que foi falado
                if turn.agent_id:
                    agent.cancel(turn.agent_id)
                if self._worker and self._worker.is_alive() and threading.current_thread() is not self._worker:
                    self._worker.join(timeout=0.25)
                self._finalize_interrupted(turn)
            self._cleanup_after_stop()
        return {"ok": True, "reason": reason, "conversation_id": cid}

    # --- Comandos da tela (POST /api/study/call) ---

    def set_mute(self, muted=None):
        with self._lock:
            self.muted = (not self.muted) if muted is None else bool(muted)
            if self.muted:
                self.ptt_active = False
                spec, self._spec = self._spec, None
                self._turn_frames = []
                self._speech_frames = 0
                self._silence_frames = 0
                if self.state == "user_speaking":
                    self.state = "listening"
            else:
                spec = None
            self.last_activity = time.monotonic()
            ev = self._state_event()
        if spec:
            spec.cancel()
        self._emit(ev)
        return self.snapshot()

    def set_vault(self, free=None, sources="keep", profile=None, source="screen"):
        """Troca Livre/Notas (e o perfil) NO MEIO da chamada, sem outra conversa nem reiniciar a sessão. O turno que já
        começou termina como começou; o novo valor vale a partir do próximo. Uma resposta antecipada nascida com o valor
        antigo é descartada na hora de fechar o turno (ver `_run_turn`), e o estado enviado à tela diz o que vale."""
        if sources != "keep":
            sources = clean_sources(sources)
        if profile not in (None, "", "main", "adult"):
            raise AppError("Perfil inválido.")
        with self._lock:
            before = (self._vault_snapshot(), self.profile)
            if free is not None:
                self.vault_free = bool(free)
            if free is True:
                self.vault_sources = None          # Livre ignora fontes (como no chat: setVaultState(true, null))
            elif sources != "keep":
                self.vault_sources = sources
                if sources is not None and free is None:
                    self.vault_free = False        # escolher uma fonte é voltar às notas
            if profile is not None:
                self.profile = profile
            changed = before != (self._vault_snapshot(), self.profile)
            spec = None
            if changed:
                spec, self._spec = self._spec, None   # a antecipada nasceu no modo antigo
            ev = self._state_event()
        if spec:
            spec.cancel()
        if self.active and changed:
            self._emit(ev)
            self._emit({"type": "vault", "vault": self._vault_snapshot(), "source": source})
        return self.snapshot()

    def interrupt(self, from_barge_in=False, seed_frames=None, merge=False):
        """Interrompe o Lúmen (botão 'Falar agora', barra de espaço ou voz por cima): para o áudio, cancela o modelo e a
        síntese DESTE turno e deixa o estado certo para o próximo. Com `merge` (retomada da fala antes de qualquer som, até
        `MERGE_WINDOW_S` depois de fechar o turno), a fala anterior e a nova viram UMA só: a pergunta salva é retirada e a
        transcrição recebe as duas partes, porque quem fez uma pausa longa no meio da frase não terminou de falar."""
        if not self.active:
            self._barge_pending = False
            return self.snapshot()
        self.last_activity = time.monotonic()
        turn = self._turn
        was_busy = self.state in ("speaking", "thinking", "transcribing", "end_of_speech")
        can_merge = bool(merge and from_barge_in and seed_frames and turn is not None and turn.plain and turn.audio is not None
                         and self.state in ("end_of_speech", "transcribing", "thinking") and not turn.spoken and not turn.current
                         and time.monotonic() - turn.created <= MERGE_WINDOW_S)
        if turn is not None:
            turn.cancel.set()
            if turn.agent_id:
                agent.cancel(turn.agent_id)
        spec, self._spec = self._spec, None
        if spec:
            spec.cancel()
        if self._worker and self._worker.is_alive() and threading.current_thread() is not self._worker:
            self._worker.join(timeout=0.25)
        merged_audio = None
        if can_merge:
            # O agente só grava a pergunta (e a resposta) quando termina de escrever: ainda pode não haver nada salvo; se já houver
            # e nada foi falado, a resposta e a pergunta são retiradas (nessa ordem) para a fala inteira virar um turno só.
            cid = self.conversation_id
            if cid and turn.mid is not None:
                chats.drop_last_answer(cid)
            gone = turn.user_mid is None or (bool(cid) and chats.drop_trailing_user(cid, turn.user_mid))
            if gone:
                merged_audio = turn.audio
                turn.mid = None
                self.turn_count = max(0, self.turn_count - 1)
                self._emit({"type": "retract", "message_id": turn.user_mid, "turn_id": turn.id})
        if was_busy and turn is not None and merged_audio is None:
            self._finalize_interrupted(turn)
        if from_barge_in and seed_frames:
            with self._lock:
                head = [merged_audio] if merged_audio is not None else []
                self._turn_frames = head + list(seed_frames) + list(self._barge_buf)
                self._barge_buf, self._barge_pending = [], False
                self._speech_frames = len(self._turn_frames)
                self._silence_frames = 0
                self._last_speech_at = time.monotonic()
                self._partial_text = ""
                self._prefetched = None
            self._set_state("user_speaking")
        else:
            self._barge_pending = False
            if self.active:
                self._set_state("listening")
        return self.snapshot()

    def ptt_down(self):
        if not self.active:
            return self.snapshot()
        self.last_activity = time.monotonic()
        mode = self._s.get("call_mode", "handsfree")
        if mode == "tap" and self.ptt_active:
            return self.ptt_up()
        if self.state in ("speaking", "thinking", "transcribing", "end_of_speech"):
            self.interrupt()
        with self._lock:
            self.muted = False
            self.ptt_active = True
            pre = self._mic.preroll_audio()
            self._turn_frames = [pre] if pre.size else []
            self._speech_frames = 1
            self._silence_frames = 0
            self._last_speech_at = time.monotonic()
        self._set_state("user_speaking")
        return self.snapshot()

    def ptt_up(self):
        if not self.active:
            return self.snapshot()
        self.last_activity = time.monotonic()
        with self._lock:
            if not self.ptt_active and self.state != "user_speaking":
                return self.snapshot()
            self.ptt_active = False
            frames = list(self._turn_frames)
            self._turn_frames = []
            self._speech_frames = 0
            self._silence_frames = 0
            eos_at = time.monotonic()
        if frames:
            self._commit_user_turn(np.concatenate(frames), eos_at, eos_at, None)
        else:
            self._set_state("listening")
        return self.snapshot()

    def update_settings(self, patch, persist=None):
        if not isinstance(patch, dict):
            raise AppError("Ajustes inválidos.")
        do_persist = self._persist_settings if persist is None else bool(persist)
        if do_persist:
            saved = settings.save({"voice": patch})["voice"]
        else:
            cur = dict(self._s or settings.load()["voice"])
            for k, v in patch.items():
                settings._check("voice", k, v)
                cur[k] = round(float(v), 2) if k == "call_speed" and not isinstance(v, bool) else v
            saved = cur
        with self._lock:
            if self._s is not None:
                self._s.update(saved)
        if "call_voice" in patch and self.active and self._s:
            try:
                self.who = listen.who("call", self._s, start=False)
            except AppError:
                pass
        if self.active:
            self._emit(self._state_event())
        return self.snapshot()

    # --- Entrada contínua de quadros de 32 ms do microfone ---

    def _on_mic_frame(self, frame, level):
        self._last_frame_at = time.monotonic()
        try:
            self._handle_mic_frame(frame, level)
        except Exception as e:  # noqa: BLE001 — uma falha neste quadro (VAD, eco) não pode matar a thread do microfone
            self._frame_errors = getattr(self, "_frame_errors", 0) + 1
            if self._frame_errors <= 3:
                log.warning("quadro do microfone: %s", type(e).__name__)

    def _handle_mic_frame(self, frame, level):
        if not self.active or self.state in ("preparing", "ended", "reconnecting"):
            return
        now = self._last_frame_at
        if self.muted:
            return
        if self._barge_pending:   # a interrupção ainda está parando o áudio e o modelo: guarda o começo da fala nova
            with self._lock:
                if now - self._barge_since <= 2.0:
                    self._barge_buf.append(np.asarray(frame, dtype=np.float32).copy())
                    return
                self._barge_pending, self._barge_buf = False, []   # a interrupção travou: não segura o microfone para sempre
        s = self._s or {}
        mode = s.get("call_mode", "handsfree")

        # Nível do microfone para o orbe (~16 Hz)
        if self.state in ("listening", "user_speaking") and now - self._last_mic_emit >= 0.06:
            self._last_mic_emit = now
            self._emit({"type": "level", "source": "mic", "level": round(min(1.0, level * 2.2), 3)})

        # Interrupção falando por cima enquanto o Lúmen fala (4.4)
        if self.state == "speaking":
            if mode != "handsfree" or not s.get("call_barge_in", True):
                return
            headphones = bool(s.get("call_headphones", False))
            clean, _, _, above = self._echo.process(frame, headphones=headphones)
            prob = self._vad.prob(clean) if self._vad else 0.0
            thresh = 0.55 if headphones else 0.65
            need_frames = 3 if headphones else 5
            if above and prob >= thresh:
                self._barge_frames += 1
                if self._barge_frames >= need_frames:
                    self._barge_frames = 0
                    pre = self._mic.preroll_audio()
                    seed = ([pre] if pre.size else []) + [clean.copy()]
                    self._barge_pending, self._barge_buf, self._barge_since = True, [], time.monotonic()
                    threading.Thread(target=self.interrupt, kwargs={"from_barge_in": True, "seed_frames": seed},
                                     daemon=True, name="Lumen call barge-in").start()
            else:
                self._barge_frames = 0
            return

        # Falou de novo enquanto o Lúmen ainda transcreve/pensa (nada tocou ainda): cancela esse turno e escuta a nova fala.
        # O som de "entendi" ainda pode vazar no microfone nos primeiros instantes, por isso a pequena folga.
        if self.state in ("end_of_speech", "transcribing", "thinking"):
            if mode != "handsfree" or not s.get("call_barge_in", True) or now - self._committed_at < BARGE_SETTLE_S:
                return
            prob = self._vad.prob(frame) if self._vad else 0.0
            if prob >= 0.6 and level >= 0.01:
                self._barge_frames += 1
                if self._barge_frames >= 5:        # 160 ms seguidos de voz
                    self._barge_frames = 0
                    pre = self._mic.preroll_audio()
                    seed = ([pre] if pre.size else []) + [frame.copy()]
                    self._barge_pending, self._barge_buf, self._barge_since = True, [], time.monotonic()
                    threading.Thread(target=self.interrupt, kwargs={"from_barge_in": True, "seed_frames": seed, "merge": True},
                                     daemon=True, name="Lumen call barge-in").start()
            else:
                self._barge_frames = 0
            return

        if self.state not in ("listening", "user_speaking"):
            return

        # Modo apertar / tocar para falar: grava enquanto `ptt_active` estiver ligado
        if mode in ("ptt", "tap"):
            if self.ptt_active:
                self.last_activity = now
                self._turn_frames.append(frame.copy())
                if len(self._turn_frames) * 0.032 >= MAX_TURN_S:
                    threading.Thread(target=self.ptt_up, daemon=True).start()
                elif s.get("call_captions", True) and now - self._last_partial_at >= PARTIAL_INTERVAL_S and not self._partial_busy:
                    self._spawn_partial(list(self._turn_frames), s)
            return

        # Modo mãos livres: VAD Silero ONNX por quadro. Histerese: para COMEÇAR a fala o VAD precisa de 0,5; já falando, o
        # fim de uma palavra (energia baixa, probabilidade 0,35 a 0,5) ainda conta como fala, e a pausa não começa cedo demais.
        prob = self._vad.prob(frame) if self._vad else 0.0
        speaking_now = self.state == "user_speaking"
        is_speech = prob >= (SPEECH_KEEP if speaking_now else SPEECH_ON) and level >= (0.004 if speaking_now else 0.006)

        if self.state == "listening":
            if is_speech:
                self._speech_frames += 1
                if self._speech_frames >= 2:  # 64 ms seguidos de voz confirmam início da fala; o anel guarda os 320 ms anteriores
                    self.last_activity = now
                    pre = self._mic.preroll_audio()
                    self._turn_frames = ([pre] if pre.size else []) + [frame.copy()]
                    self._silence_frames = 0
                    self._last_speech_at = now
                    self._last_partial_at = now
                    self._partial_text = ""
                    self._prefetched = None
                    self._set_state("user_speaking")
            else:
                self._speech_frames = 0
            return

        # Estado `user_speaking` em mãos livres
        self._turn_frames.append(frame.copy())
        if is_speech:
            self.last_activity = now
            self._speech_frames += 1
            self._silence_frames = 0
            self._last_speech_at = now
            if self._spec is not None:
                # O estudante voltou a falar antes do fim da fala: descarta a resposta antecipada sem deixar rastro
                spec, self._spec = self._spec, None
                spec.cancel()
            if HANDSFREE_PARTIAL and s.get("call_captions", True) and now - self._last_partial_at >= PARTIAL_INTERVAL_S and not self._partial_busy:
                self._spawn_partial(list(self._turn_frames), s)
        else:
            self._silence_frames += 1

        silence_ms = self._silence_frames * 32.0
        target_ms = SILENCE_MS.get(s.get("call_silence", "normal"), 700)
        turn_s = sum(f.size for f in self._turn_frames) / 16000.0

        # Resposta antecipada aos ~250 ms de silêncio (4.3.5)
        if (s.get("call_early", True) and self._spec is None and self._speech_frames >= MIN_SPEECH_FRAMES
                and EARLY_MS <= silence_ms < target_ms and not self._quiz and not self._review):
            self._start_speculative(np.concatenate(self._turn_frames), dict(s))

        # Fim da fala pelo silêncio escolhido (mais uma espera, uma vez, se a frase claramente não terminou) ou pelo teto de 60 s
        hold_ms = self._hold_extra_ms(s) if (silence_ms >= target_ms and turn_s < MAX_TURN_S - 2.0) else 0.0
        if silence_ms >= target_ms + hold_ms or turn_s >= MAX_TURN_S:
            audio = np.concatenate(self._turn_frames)
            last_speech_at = self._last_speech_at or now
            spec, self._spec = self._spec, None
            self._turn_frames = []
            self._speech_frames = 0
            self._silence_frames = 0
            if self._vad:
                self._vad.reset()
            self._commit_user_turn(audio, last_speech_at, now, spec)

    def _hold_extra_ms(self, s):
        """Quanto esperar além do silêncio escolhido: `HOLD_MAX_MS` se a transcrição antecipada já mostra uma frase que
        parou no meio ("…porque", "…o", vírgula), senão 0. No perfil "rápido" nunca espera; sem resposta antecipada não há
        transcrição para olhar. Se o estudante continuar, o turno segue sem corte; se não, só custou esta espera."""
        if s.get("call_silence") == "fast":
            return 0.0
        spec = self._spec
        if spec is None or not spec.asr_done.is_set() or not spec.text or self._is_command(spec.text):
            return 0.0
        # a regra da pontuação final só vale para o Parakeet, o reconhecedor em que foi medida
        return float(HOLD_MAX_MS) if looks_unfinished(spec.text, punctuation=spec.asr_engine == "parakeet") else 0.0

    # --- Legenda parcial + pré-busca nas notas ---

    def _spawn_partial(self, frames, s):
        self._last_partial_at = time.monotonic()
        self._partial_busy = True
        # Transcreve até os últimos 4,5 s para manter a legenda parcial leve (< 220 ms)
        tail = np.concatenate(frames)[-int(16000 * 4.5):]

        def work():
            try:
                if not self.active or self.state != "user_speaking":
                    return
                txt, _, _ = self._asr_fn(tail, s.get("call_asr", "auto"))
                if not txt or not self.active or self.state != "user_speaking":
                    return
                if txt != self._partial_text:
                    self._partial_text = txt
                    self._emit({"type": "partial", "text": txt})
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._partial_busy = False

        threading.Thread(target=work, daemon=True, name="Lumen call partial").start()

    # --- Resposta antecipada (especulativa) ---

    def _start_speculative(self, audio_16k, s):
        # A resposta antecipada nasce com a fotografia de Livre/Notas do instante: se o estudante trocar o modo antes de
        # fechar o turno, `_run_turn` a descarta (o texto transcrito é reaproveitado) e refaz com o modo certo.
        spec = SpeculativeTurn(audio_16k, self._vault_snapshot(), self.profile)
        self._spec = spec

        def work():
            try:
                txt, asr_ms, eng = self._asr_fn(spec.audio, s.get("call_asr", "auto"))
                spec.text, spec.asr_ms, spec.asr_engine = txt, asr_ms, eng
                spec.asr_done.set()
                if spec.cancel_ev.is_set() or not txt:
                    spec.kind = "empty"
                    spec.events.put(None)
                    return
                if self._is_special_or_fast(txt):
                    spec.kind = "special"
                    spec.events.put(None)
                    return
                spec.kind = "agent"
                spec.llm_started_at = time.monotonic()
                payload = self._build_agent_payload(txt, s, spec.vault, spec.profile, commit_gate=spec.commit_gate)
                for ev in self._turn_fn(payload, spec.turn_id):
                    if spec.cancel_ev.is_set():
                        break
                    if ev.get("type") == "delta" and spec.llm_first_at is None:
                        spec.llm_first_at = time.monotonic()
                    spec.events.put(ev)
            except Exception as e:  # noqa: BLE001
                spec.events.put({"type": "error", "message": str(e), "action": getattr(e, "action", "")})
            finally:
                spec.events.put(None)

        spec.thread = threading.Thread(target=work, daemon=True, name="Lumen call spec")
        spec.thread.start()

    COMMAND_RES = (STOP_CMD_RE, END_CMD_RE, REPEAT_CMD_RE, SLOWER_CMD_RE, FASTER_CMD_RE, QUIETER_CMD_RE, LOUDER_CMD_RE,
                   VOICE_SWITCH_RE, FREE_ON_RE, FREE_OFF_RE, NOTES_ON_RE, NOTES_ONLY_RE)

    def _is_command(self, text):
        """Comando curto e inteiro ("para", "mais devagar", "usar minhas notas"): nunca é uma frase inacabada."""
        f = search._fold(text).strip(" .,!?")
        return any(rx.search(f) for rx in self.COMMAND_RES)

    def _is_special_or_fast(self, text):
        f = search._fold(text).strip(" .,!?")
        if self._quiz or self._review or self._feynman_topic:
            return True
        if self._is_command(text):
            return True
        for rx in (MASTERY_WRONG_RE, FEYNMAN_RE, REVIEW_DUE_RE, SAVE_RE):
            if rx.search(f):
                return True
        return False

    @staticmethod
    def _call_length(text, s):
        """Tamanho da resposta falada: o ajuste do estudante, salvo quando ele PEDE uma explicação longa na própria fala
        ("explica com calma", "quero a explicação completa"): aí vale a detalhada só neste turno."""
        base = s.get("call_length", "short")
        return "detailed" if LONG_ASK_RE.search(fold(text)) else base

    def _build_agent_payload(self, text, s, vault, profile="", commit_gate=None):
        """O mesmo conteúdo que o chat escrito envia: conversa, projeto, privacidade e, agora também, Livre/Notas
        (`skip_vault`/`vault_sources`) e o perfil escolhido. `vault` é a fotografia do turno, não o valor "de agora"."""
        f = search._fold(text)
        want_screen = bool(SCREEN_RE.search(f))
        # busca antecipada só vale no modo Notas e para as MESMAS fontes; no Livre ela nunca entra (nem por cache)
        pre = self._prefetched if (isinstance(self._prefetched, dict) and not vault["free"]
                                   and self._prefetched.get("_vault") == (list(vault["sources"]) if vault["sources"] else None)) else None
        return {
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "temporary": self.temporary,
            "text": text,
            "screen": want_screen,
            "skip_vault": bool(vault["free"]),
            **({"vault_sources": list(vault["sources"])} if vault["sources"] and not vault["free"] else {}),
            **({"profile": profile} if profile else {}),
            "prefetched_search": pre,
            "call": {"length": self._call_length(text, s), "effort": s.get("call_effort", "auto")},
            **({"_commit_gate": commit_gate} if commit_gate is not None else {}),
        }

    # --- Confirmação e execução completa de um turno ---

    @staticmethod
    def _iter_spec(spec, turn):
        """Eventos da resposta antecipada. Acorda a cada 100 ms para notar o cancelamento: interromper enquanto o modelo
        ainda não escreveu nada (o estado "pensando") não deixa o turno preso esperando a primeira palavra."""
        while True:
            try:
                ev = spec.events.get(timeout=0.1)
            except queue.Empty:
                if turn.cancel.is_set() or spec.cancel_ev.is_set():
                    return
                continue
            if ev is None:
                return
            yield ev

    def _t(self):
        """O turno desta thread (threads de turno) ou o corrente (quem chama de fora, como a tela)."""
        return getattr(self._tl, "turn", None) or self._turn

    def _commit_user_turn(self, audio_16k, last_speech_at, eos_at, spec):
        prev = self._turn
        if prev is not None and not prev.done.is_set():   # nunca dois turnos vivos ao mesmo tempo
            prev.cancel.set()
            if prev.agent_id:
                agent.cancel(prev.agent_id)
        turn = Turn(self._vault_snapshot(), self.profile)   # a fotografia de Livre/Notas deste turno
        turn.audio = audio_16k
        self._turn = turn
        self._committed_at = time.monotonic()
        self._barge_frames = 0
        self._set_state("end_of_speech")
        self._worker = threading.Thread(
            target=self._run_turn, args=(turn, audio_16k, last_speech_at, eos_at, spec),
            daemon=True, name="Lumen call turn"
        )
        self._worker.start()

    def _play_earcon(self, turn=None):
        if not (self._s or {}).get("call_earcon", True):
            return None
        t0 = time.monotonic()
        try:
            with self._speaker_lock:
                if turn is not None and turn.cancel.is_set():
                    return None
                with self._speaker_factory() as sp:
                    t_start = time.monotonic()
                    sp.play(EARCON_PCM * self.volume)
            return round((t_start - t0) * 1000.0, 1)
        except Exception:  # noqa: BLE001
            return None

    def _run_turn(self, turn, audio_16k, last_speech_at, eos_at, spec):
        self._tl.turn = turn
        s = dict(self._s or settings.load()["voice"])
        eos_ms = round(max(0.0, (eos_at - last_speech_at) * 1000.0), 1)
        earcon_box = [None]
        if s.get("call_earcon", True):
            def _earcon_worker():
                if self._play_earcon(turn) is not None:
                    earcon_box[0] = round((time.monotonic() - eos_at) * 1000.0, 1)
            threading.Thread(target=_earcon_worker, daemon=True, name="Lumen call earcon").start()

        try:
            self._set_state("transcribing")
            early_hit = False
            reuse = None
            # Mudou Livre/Notas (ou o perfil) depois que a resposta antecipada nasceu: ela vale para o modo ANTIGO e é
            # descartada; só o texto já transcrito é reaproveitado, para não pagar o reconhecimento duas vezes.
            if spec is not None and (spec.vault != turn.vault or spec.profile != turn.profile):
                spec.cancel()
                if spec.asr_done.is_set() and spec.text:
                    reuse = (spec.text, spec.asr_ms, spec.asr_engine)
                spec = None
            if spec is not None:
                spec.asr_done.wait(timeout=10.0)
                text, asr_ms, asr_eng = spec.text, spec.asr_ms, spec.asr_engine
                early_hit = bool(text)
            elif reuse:
                text, asr_ms, asr_eng = reuse
            else:
                text, asr_ms, asr_eng = self._asr_fn(audio_16k, s.get("call_asr", "auto"))

            if turn.cancel.is_set() or not self.active:
                if spec:
                    spec.cancel()
                return

            if not text:
                if spec:
                    spec.cancel()
                self._set_state("listening")
                return

            # 1. Comandos rápidos sem passar pelo modelo (4.3.10)
            if self._handle_fast_command(text, s):
                if spec:
                    spec.cancel()
                return

            self.turn_count += 1
            self._set_state("thinking")

            # 2. Intenções interativas próprias (quiz ativo, revisão ativa, Feynman, "o que eu errei", salvar)
            if self._handle_special_intent(text, s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_box):
                if spec:
                    spec.cancel()
                return

            # 3. Fluxo padrão pelo `agent.turn` (com ou sem resposta antecipada já iniciada)
            if spec is not None and spec.kind == "agent":
                turn.agent_id = spec.turn_id
                spec.commit_gate.set()
                ev_iter = self._iter_spec(spec, turn)
                llm_started = spec.llm_started_at or spec.started_at
            else:
                if spec is not None:
                    spec.cancel()
                tid = "call-" + uuid.uuid4().hex[:12]
                turn.agent_id = tid
                llm_started = time.monotonic()
                payload = self._build_agent_payload(text, s, turn.vault, turn.profile)
                ev_iter = self._turn_fn(payload, tid)

            self._consume_agent_stream(ev_iter, text, s, last_speech_at, eos_ms, asr_ms, asr_eng,
                                       earcon_box, early_hit, llm_started, spec)
        except Cancelled:
            if spec:
                spec.cancel()
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
        except AppError as e:
            if spec:
                spec.cancel()
            self._emit({"type": "error", "message": str(e), "action": e.action})
            if self.active:
                self._set_state("listening")
        except Exception as e:  # noqa: BLE001
            if spec:
                spec.cancel()
            log.warning("turno da chamada: %s: %s", type(e).__name__, e)
            self._emit({"type": "error", "message": "Houve uma falha neste turno da chamada.", "action": ""})
            if self.active:
                self._set_state("listening")
        finally:
            turn.done.set()
            self._tl.turn = None

    # --- Comandos rápidos locais (sem LLM) ---

    def _handle_fast_command(self, text, s):
        f = search._fold(text).strip(" .,!?")
        if STOP_CMD_RE.match(f):
            self._emit({"type": "final", "text": text, "fast": "stop"})
            self._set_state("listening")
            return True
        if END_CMD_RE.match(f):
            self._emit({"type": "final", "text": text, "fast": "end"})
            self.stop(reason="voice_command")
            return True
        if REPEAT_CMD_RE.match(f):
            self._emit({"type": "final", "text": text, "fast": "repeat"})
            msg = self.last_spoken_answer or "Ainda não falei nenhuma resposta nesta chamada."
            self._speak_sentences([x for x in voice.sentences(voice.speakable(msg))], s, record_answer=False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True
        if SLOWER_CMD_RE.match(f):
            self._emit({"type": "final", "text": text, "fast": "slower"})
            new_spd = max(0.7, round(float(s.get("call_speed", 1.0)) - 0.15, 2))
            self.update_settings({"call_speed": new_spd})
            s["call_speed"] = new_spd
            self._speak_sentences(["Pronto, vou falar mais devagar."], s, record_answer=False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True
        if FASTER_CMD_RE.match(f):
            self._emit({"type": "final", "text": text, "fast": "faster"})
            new_spd = min(1.3, round(float(s.get("call_speed", 1.0)) + 0.15, 2))
            self.update_settings({"call_speed": new_spd})
            s["call_speed"] = new_spd
            self._speak_sentences(["Pronto, vou falar mais rápido."], s, record_answer=False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True
        if QUIETER_CMD_RE.match(f):
            self._emit({"type": "final", "text": text, "fast": "quieter"})
            self.volume = max(0.25, round(self.volume * 0.65, 2))
            self._speak_sentences(["Pronto, baixei o volume."], s, record_answer=False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True
        if LOUDER_CMD_RE.match(f):
            self._emit({"type": "final", "text": text, "fast": "louder"})
            self.volume = min(1.0, round(self.volume / 0.65, 2))
            self._speak_sentences(["Pronto, aumentei o volume."], s, record_answer=False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True
        # Livre/Notas por voz: só vale daqui para o PRÓXIMO turno, e a tela é avisada (estado + evento `vault`)
        vault_cmd = None
        if FREE_ON_RE.match(f):
            vault_cmd = ("free", dict(free=True), "Pronto, modo livre ligado. Não vou consultar suas notas nas próximas respostas.")
        elif FREE_OFF_RE.match(f) or NOTES_ON_RE.match(f):
            vault_cmd = ("notes", dict(free=False, sources=None), "Pronto, voltei a usar suas notas.")
        else:
            mo = NOTES_ONLY_RE.match(f)
            if mo:
                src = "obsidian" if "obsidian" in mo.group(1) else "notion"
                vault_cmd = ("notes_" + src, dict(free=False, sources=[src]),
                             f"Pronto, vou usar só o {'Obsidian' if src == 'obsidian' else 'Notion'}.")
        if vault_cmd:
            kind, change, reply = vault_cmd
            self._emit({"type": "final", "text": text, "fast": "vault", "vault_mode": kind})
            self.set_vault(source="voice", **change)
            self._speak_sentences([reply], s, record_answer=False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True
        m = VOICE_SWITCH_RE.match(f)
        if m:
            want = m.group(1).strip()
            self._emit({"type": "final", "text": text, "fast": "voice"})
            vs = listen.gallery()
            hit = None
            if "demo" in want:
                hit = next((v for v in vs if v.get("demo") or "demo" in search._fold(v["name"])), None)
            if not hit:
                hit = next((v for v in vs if want in search._fold(v["name"]) or search._fold(v["name"]) in want), None)
            if not hit:
                self._speak_sentences(["Não encontrei essa voz no Voice Studio."], s, record_answer=False)
            else:
                self.update_settings({"call_voice": hit["id"]})
                s["call_voice"] = hit["id"]
                self.who = listen.who("call", self._s, start=False)
                self._emit(self._state_event())
                self._speak_sentences([f"Pronto, agora quem fala é {hit['name']}."], s, record_answer=False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True
        return False

    # --- Intenções especiais da chamada (quiz, revisão, Feynman, mastery, salvar com prévia) ---

    def _ensure_conversation(self, first_text):
        if not self.conversation_id:
            conv = chats.create(self.project_id, first_text[:80], temporary=self.temporary)
            self.conversation_id = conv["id"]
            self._emit({"type": "conversation", "conversation": {k: conv[k] for k in ("id", "title", "project_id", "temporary") if k in conv}})
            self._emit(self._state_event())
        return self.conversation_id

    def _check_cancel(self):
        t = self._t()
        if not self.active or (t is not None and t.cancel.is_set()):
            raise Cancelled()

    def _set_reply(self, mid, sources):
        t = self._t()
        if t is not None:
            t.mid, t.sources = mid, sources

    def _turn_vault(self):
        """Livre/Notas deste turno (a fotografia), no formato que `tools.Ctx` e `search.search` entendem."""
        t = self._t()
        return t.vault if t is not None else self._vault_snapshot()

    def _ctx(self, cid, proj, provider_name):
        v = self._turn_vault()
        return tools.Ctx(cid, proj, provider_name, self._check_cancel, skip_vault=v["free"],
                         allowed_sources=[] if v["free"] else v["sources"])

    def _provider(self):
        full_s = settings.load()
        proj = chats.project(self.project_id) if self.project_id else None
        chain, reasons = providers.chain(full_s)
        if not chain:
            raise AppError("Nenhuma IA disponível agora. " + " ".join(reasons))
        return chain[0], proj

    def _handle_special_intent(self, text, s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms):
        f = search._fold(text).strip(" .,!?")

        # Sair de quiz / revisão ativos se pedido ou se pedir outro artefato claro
        if (self._quiz or self._review) and (QUIZ_EXIT_RE.match(f) or search.heuristic(text)["intent"] in ("mindmap", "flashcards", "plan", "map")):
            self._quiz = None
            self._review = None
            if QUIZ_EXIT_RE.match(f):
                cid = self._ensure_conversation(text)
                um = chats.add_message(cid, "user", text, meta={"call": True})
                self._emit({"type": "final", "text": text, "message_id": um["id"]})
                reply = "Combinado, encerramos por aqui. Sobre o que quer conversar agora?"
                am = chats.add_message(cid, "assistant", reply, [], {"mode": "chat", "call": True})
                self._set_reply(am["id"], [])
                self._emit({"type": "token", "text": reply, "replace": True})
                self._speak_sentences([reply], s)
                if self.active and self.state != "user_speaking":
                    self._set_state("listening")
                return True

        # 1. Resposta falada a uma questão do quiz ativo
        if self._quiz:
            cid = self._ensure_conversation(text)
            um = chats.add_message(cid, "user", text, meta={"call": True})
            self._emit({"type": "final", "text": text, "message_id": um["id"]})
            it = learn.item(self._quiz["item_id"])
            idx = self._quiz["index"]
            qs = it["data"]["questions"]
            q = qs[idx]
            mapped = map_quiz_spoken_answer(q, text)
            prov = None
            if q.get("kind") not in ("multipla", "vf") and not learn.is_dont_know(mapped):
                prov, _ = self._provider()
            res = learn.answer(it["id"], idx, mapped, prov, self._check_cancel, record=not self.temporary)
            it_after = learn.item(it["id"])
            spoken = [x for x in voice.sentences(voice.speakable(res["feedback"]))]
            if idx + 1 < len(qs):
                self._quiz["index"] = idx + 1
                nxt = quiz_question_speech(qs[idx + 1], idx + 1, len(qs))
                spoken += [x for x in voice.sentences(nxt)]
                full_reply = f"{res['feedback']}\n\n**{nxt}**"
            else:
                ans_map = it_after["data"].get("answers") or {}
                hits = sum(1 for v in ans_map.values() if v.get("correct"))
                end_line = f"Fim do quiz! Você acertou {hits} de {len(qs)}."
                spoken.append(end_line)
                full_reply = f"{res['feedback']}\n\n{end_line}"
                self._quiz = None
            am = chats.add_message(cid, "assistant", full_reply, [], {"mode": "quiz", "item": it["id"], "call": True})
            self._set_reply(am["id"], [])
            self._emit({"type": "card", "kind": "item", "item": it_after, "quiz_result": {"index": idx, **res}})
            self._emit({"type": "token", "text": full_reply, "replace": True})
            t_play = self._speak_sentences(spoken, s)
            self._record_timings(s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, 0.0, t_play, False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True

        # 2. Resposta falada à revisão espaçada do dia
        if self._review:
            cid = self._ensure_conversation(text)
            um = chats.add_message(cid, "user", text, meta={"call": True})
            self._emit({"type": "final", "text": text, "message_id": um["id"]})
            cards = self._review["cards"]
            idx = self._review["index"]
            card = cards[idx]
            prov, _ = (None, None) if learn.is_dont_know(text) else self._provider()
            res = learn.grade(card["question"], card["answer"], "", text, prov, self._check_cancel)
            if not self.temporary:
                grade_num = 3 if res["score"] >= 0.9 else 2 if res["correct"] else 0
                learn.review(card["id"], grade_num)
            spoken = [x for x in voice.sentences(voice.speakable(res["feedback"]))]
            if idx + 1 < len(cards):
                self._review["index"] = idx + 1
                nxt = f"Próximo cartão: {voice.speakable(cards[idx + 1]['question'])}"
                spoken.append(nxt)
                full_reply = f"{res['feedback']}\n\n{nxt}"
            else:
                spoken.append("Revisão de hoje concluída!")
                full_reply = f"{res['feedback']}\n\nRevisão de hoje concluída!"
                self._review = None
            am = chats.add_message(cid, "assistant", full_reply, [], {"mode": "review", "call": True})
            self._set_reply(am["id"], [])
            self._emit({"type": "token", "text": full_reply, "replace": True})
            t_play = self._speak_sentences(spoken, s)
            self._record_timings(s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, 0.0, t_play, False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True

        # 3. Segunda etapa de Feynman ("vou te explicar X" seguido da explicação no turno seguinte)
        if self._feynman_topic:
            topic, self._feynman_topic = self._feynman_topic, None
            return self._execute_feynman(topic, text, text, s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms)

        # 4. Início de Feynman ("vou te explicar ...")
        mf = FEYNMAN_RE.match(f)
        if mf:
            plain = text.strip(" .,!?…")   # o reconhecedor fecha a frase com ponto: o recorte usa o tamanho do texto sem ele
            raw_rest = plain[len(plain) - len(mf.group(1)):].strip(" :,-.")
            parts = re.split(r"[:.;,-]\s+", raw_rest, maxsplit=1)
            if len(parts) == 2 and len(parts[1].split()) >= 5:
                return self._execute_feynman(parts[0], parts[1], text, s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms)
            if len(raw_rest.split()) >= 10:
                words = raw_rest.split()
                return self._execute_feynman(" ".join(words[:3]), raw_rest, text, s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms)
            topic = raw_rest[:120] or "este assunto"
            cid = self._ensure_conversation(text)
            um = chats.add_message(cid, "user", text, meta={"call": True})
            self._emit({"type": "final", "text": text, "message_id": um["id"]})
            self._feynman_topic = topic
            reply = f"Pode explicar {topic} com as suas palavras; estou ouvindo."
            am = chats.add_message(cid, "assistant", reply, [], {"mode": "feynman", "call": True})
            self._set_reply(am["id"], [])
            self._emit({"type": "token", "text": reply, "replace": True})
            t_play = self._speak_sentences([reply], s)
            self._record_timings(s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, 0.0, t_play, False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True

        # 5. "O que eu errei" (modelo do estudante, mastery)
        if MASTERY_WRONG_RE.search(f):
            cid = self._ensure_conversation(text)
            um = chats.add_message(cid, "user", text, meta={"call": True})
            self._emit({"type": "final", "text": text, "message_id": um["id"]})
            rows = [r for r in mastery.listing()
                    if (r.get("wrong") or 0) > 0 and (not self.project_id or r.get("project_id") == self.project_id)]
            rows.sort(key=lambda r: (-int(r.get("wrong") or 0), int(r.get("correct") or 0)))
            if not rows:
                reply = "Você ainda não tem erros registrados nos seus estudos. Continue praticando!"
            else:
                top = rows[:4]
                names = ", ".join(f"{r['label']} ({r['wrong']} {'erro' if r['wrong'] == 1 else 'erros'})" for r in top)
                reply = f"Os assuntos em que você mais errou até agora são: {names}. Quer revisar algum deles?"
            am = chats.add_message(cid, "assistant", reply, [], {"mode": "mastery", "call": True})
            self._set_reply(am["id"], [])
            self._emit({"type": "card", "kind": "mastery", "items": rows[:8]})
            self._emit({"type": "token", "text": reply, "replace": True})
            t_play = self._speak_sentences([x for x in voice.sentences(voice.speakable(reply))], s)
            self._record_timings(s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, 0.0, t_play, False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True

        # 6. "Revisão do dia"
        if REVIEW_DUE_RE.search(f):
            cid = self._ensure_conversation(text)
            um = chats.add_message(cid, "user", text, meta={"call": True})
            self._emit({"type": "final", "text": text, "message_id": um["id"]})
            d = learn.due(limit=10, project_id=self.project_id)
            self._emit({"type": "card", "kind": "review", "due": d})
            if d["cards"]:
                self._review = {"cards": d["cards"], "index": 0}
                q0 = voice.speakable(d["cards"][0]["question"])
                reply = f"Você tem {d['total']} {'cartão' if d['total'] == 1 else 'cartões'} para revisar hoje. Primeiro: {q0}"
            elif d["topics"]:
                names = ", ".join(t["label"] for t in d["topics"][:3])
                reply = f"Não há flashcards vencidos hoje, mas vale revisar {names}."
            else:
                reply = "Você está em dia: não há cartões nem assuntos pendentes de revisão agora."
            am = chats.add_message(cid, "assistant", reply, [], {"mode": "review", "call": True})
            self._set_reply(am["id"], [])
            self._emit({"type": "token", "text": reply, "replace": True})
            t_play = self._speak_sentences([x for x in voice.sentences(voice.speakable(reply))], s)
            self._record_timings(s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, 0.0, t_play, False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True

        # 7. Salvar no Obsidian ou no Notion → SEMPRE abre prévia, nunca grava direto (D11 e 4.4)
        ms = SAVE_RE.search(f)
        if ms:
            dest = "obsidian-note" if ms.group(1) == "obsidian" else "notion-page"
            cid = self._ensure_conversation(text)
            conv_full = chats.get(cid)
            prev_msgs = conv_full.get("messages") or []
            last_bot = next((m for m in reversed(prev_msgs) if m["role"] == "assistant" and m.get("content")), None)
            last_usr = next((m for m in reversed(prev_msgs) if m["role"] == "user" and m.get("content")), None)
            um = chats.add_message(cid, "user", text, meta={"call": True})
            self._emit({"type": "final", "text": text, "message_id": um["id"]})
            vault_ctx = self._ctx(cid, chats.project(self.project_id) if self.project_id else None, "")
            if not vault_ctx.allowed(ms.group(1)):
                # Mesma regra do chat: no modo livre (ou com a fonte desligada) nenhuma nota é criada ou preparada
                where = "Obsidian" if ms.group(1) == "obsidian" else "Notion"
                reply = (f"Estamos no modo livre, que não usa o {where}. Diga “usar minhas notas” e peça de novo."
                         if self._turn_vault()["free"] else f"O {where} não está liberado para esta chamada nas fontes escolhidas.")
                am = chats.add_message(cid, "assistant", reply, [], {"call": True})
                self._set_reply(am["id"], [])
                self._emit({"type": "token", "text": reply, "replace": True})
                t_play = self._speak_sentences([reply], s)
            elif not last_bot:
                reply = "Ainda não há uma resposta nesta conversa para salvar. Peça um resumo ou explicação primeiro."
                am = chats.add_message(cid, "assistant", reply, [], {"call": True})
                self._set_reply(am["id"], [])
                self._emit({"type": "token", "text": reply, "replace": True})
                t_play = self._speak_sentences([reply], s)
            else:
                title = conv_full.get("title") or (last_usr["content"][:60] if last_usr else "Nota de estudo")
                md_body = writes.note_markdown(title, last_usr["content"] if last_usr else text,
                                               last_bot["content"], last_bot.get("sources") or [])
                action = writes.prepare(dest, title, md_body, conversation_id="" if self.temporary else cid)
                reply = "Preparei a nota. A prévia está na tela; confirme lá."
                am = chats.add_message(cid, "assistant", reply, [], {"pending": [action["id"]], "call": True})
                self._set_reply(am["id"], [])
                self._emit({"type": "card", "kind": "pending", "action": action})
                self._emit({"type": "token", "text": reply, "replace": True})
                t_play = self._speak_sentences([reply], s)
            self._record_timings(s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, 0.0, t_play, False)
            if self.active and self.state != "user_speaking":
                self._set_state("listening")
            return True

        return False

    def _execute_feynman(self, topic, explanation, raw_user_text, s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms):
        cid = self._ensure_conversation(raw_user_text)
        um = chats.add_message(cid, "user", raw_user_text, meta={"call": True})
        self._emit({"type": "final", "text": raw_user_text, "message_id": um["id"]})
        prov, proj = self._provider()
        vault = self._turn_vault()
        ctx = self._ctx(cid, proj, prov.name)
        if not vault["free"]:   # Livre: o Feynman é corrigido pelo conhecimento geral, sem abrir Notion nem Obsidian
            u = search.heuristic(topic)
            found = search.search(topic, sources=vault["sources"], project=proj, understanding=u, limit=6)
            for item in found["results"]:
                ctx.cite(item)
        out = explain.feynman(topic, explanation, prov, ctx, self.project_id, self._check_cancel, record=not self.temporary)
        pct = round(out["score"] * 100)
        reply = f"Nota {pct} por cento em {out['topic']}. {out['feedback']}"
        am = chats.add_message(cid, "assistant", reply, tools.public_sources(ctx),
                               {"mode": "feynman", "feynman": out, "call": True})
        self._set_reply(am["id"], am["sources"])
        self._emit({"type": "card", "kind": "feynman", "feynman": out, "message": am})
        self._emit({"type": "token", "text": reply, "replace": True})
        t_play = self._speak_sentences([x for x in voice.sentences(voice.speakable(reply))], s)
        self._record_timings(s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, 0.0, t_play, False)
        if self.active and self.state != "user_speaking":
            self._set_state("listening")
        return True

    # --- Fluxo em streaming: modelo → frases → Voice Studio → som ---

    def _consume_agent_stream(self, ev_iter, user_text, s, last_speech_at, eos_ms, asr_ms, asr_eng,
                              earcon_ms, early_hit, llm_started, spec):
        turn = self._t()
        turn.plain = True
        sentence_q = queue.Queue()
        turn.mid, turn.sources = None, []
        turn.spoken, turn.current, turn.frac, turn.generated = [], "", 0.0, []

        play_stats = {"first_sent_at": None, "tts_first_at": None, "play_first_at": None,
                      "gaps": [], "q_sentence_max": 0, "q_audio_max": 0, "synth_ms": [], "sentences": 0}
        filler_used = [False]
        speaker_thread = threading.Thread(
            target=self._tts_and_play_worker, args=(sentence_q, s, play_stats, True, turn),
            daemon=True, name="Lumen call tts"
        )
        speaker_thread.start()

        # Se "Preencher a espera" estiver ligado e o 1º som demorar > 1,9 s, toca uma frase curta guardada (máx. 1/turno)
        if s.get("call_filler", False):
            def filler_watch():
                time.sleep(FILLER_AFTER_S)
                if (self.active and turn.alive and self.state == "thinking"
                        and play_stats["play_first_at"] is None and not filler_used[0]):
                    filler_used[0] = True
                    sentence_q.put(("filler", FILLER_TEXT))
            threading.Thread(target=filler_watch, daemon=True, name="Lumen call filler").start()

        def slow_watch():
            self._tl.turn = turn
            time.sleep(SLOW_AFTER_S)
            if self.active and turn.alive and self.state == "thinking" and play_stats["play_first_at"] is None:
                self._set_state("thinking", phase="slow")
        threading.Thread(target=slow_watch, daemon=True, name="Lumen call slow").start()

        llm_first_at = spec.llm_first_at if spec else None
        buf_text = ""
        sent_idx = 0
        structured_item = None
        deep_warned = False
        user_emitted = False

        try:
            for ev in ev_iter:
                self._check_cancel()
                etype = ev.get("type")
                if etype == "conversation":
                    self.conversation_id = ev["conversation"]["id"]
                    self._emit(ev)
                    self._emit(self._state_event())
                elif etype == "user":
                    turn.user_mid = ev["message"]["id"]
                    if not user_emitted:   # o evento `understanding` já mostrou a fala deste turno: a legenda não a repete
                        user_emitted = True
                        self._emit({"type": "final", "text": ev["message"]["content"], "message_id": ev["message"]["id"]})
                elif etype == "status":
                    self._on_agent_status(turn, ev)
                elif etype == "understanding":
                    if not user_emitted:
                        user_emitted = True
                        self._emit({"type": "final", "text": user_text, "message_id": None})
                    eff = (ev.get("understanding") or {}).get("effort")
                    if eff in ("profundo", "maximo") and not deep_warned:
                        deep_warned = True
                        wait_msg = ("Vou pensar com bastante cuidado; isso pode levar cerca de um minuto."
                                    if eff == "maximo" else "Vou pensar com calma; pode levar cerca de vinte segundos.")
                        sentence_q.put(("filler", wait_msg))
                elif etype == "sources":
                    turn.marks.setdefault("sources", time.monotonic())
                    turn.sources = ev.get("items") or []
                elif etype == "screen":
                    self._emit({"type": "card", "kind": "screen", "window": ev.get("window", "")})
                elif etype == "pending":
                    self._emit({"type": "card", "kind": "pending", "action": ev["action"]})
                elif etype == "item":
                    structured_item = ev["item"]
                elif etype == "delta":
                    if llm_first_at is None:
                        llm_first_at = time.monotonic()
                    buf_text += ev["text"]
                    turn.generated.append(ev["text"])
                    self._emit({"type": "token", "text": ev["text"]})
                    buf_text, new_sents = self._pop_ready_sentences(buf_text, first=(sent_idx == 0))
                    for st in new_sents:
                        if play_stats["first_sent_at"] is None:
                            play_stats["first_sent_at"] = time.monotonic()
                        while st:
                            piece, st = split_chunk(st, chunk_limit(sent_idx))
                            sentence_q.put(("say", piece))
                            sent_idx += 1
                elif etype == "replace":
                    # `validate` removeu [S#] inexistente ou normalizou citação no fim
                    turn.generated[:] = [ev["text"]]
                    self._emit({"type": "token", "text": ev["text"], "replace": True})
                elif etype == "done":
                    msg = ev["message"]
                    turn.mid = msg["id"]
                    turn.sources = msg.get("sources") or turn.sources
                    turn.marks.setdefault("done", time.monotonic())
                    if structured_item is not None:
                        if self.conversation_id:
                            chats.update_message(self.conversation_id, msg["id"], msg["content"], {"item_card": structured_item})
                        self._emit({"type": "card", "kind": "item", "item": structured_item, "message": msg})
                        if structured_item.get("kind") == "quiz" and (structured_item.get("data") or {}).get("questions"):
                            qs = structured_item["data"]["questions"]
                            self._quiz = {"item_id": structured_item["id"], "index": 0, "total": len(qs)}
                            intro = f"Pronto, fiz um quiz com {len(qs)} {'questão' if len(qs) == 1 else 'questões'}; está na tela."
                            sentence_q.put(("say", intro))
                            for q_part in voice.sentences(quiz_question_speech(qs[0], 0, len(qs))):
                                sentence_q.put(("say", q_part))
                        else:
                            sentence_q.put(("say", card_speech(structured_item)))
                    else:
                        rem = speech_text(buf_text).strip()
                        if rem:
                            for st in voice.sentences(rem):
                                while st:
                                    piece, st = split_chunk(st, chunk_limit(sent_idx))
                                    sentence_q.put(("say", piece))
                                    sent_idx += 1
                        buf_text = ""
                        ex = (msg.get("meta") or {}).get("explain")
                        if ex:
                            self._emit({"type": "card", "kind": "explain", "explain": ex, "message": msg})
                            if ex.get("diagram"):
                                sentence_q.put(("say", "O diagrama está na tela."))
                        if (msg.get("meta") or {}).get("pending") and sent_idx == 0:
                            sentence_q.put(("say", "A prévia está na tela; confirme lá."))
                elif etype == "error":
                    raise AppError(ev.get("message") or "Erro na resposta.", ev.get("action") or "")
                elif etype == "cancelled":
                    raise Cancelled()
        finally:
            sentence_q.put(None)

        speaker_thread.join()

        if turn.cancel.is_set():
            return

        if turn.spoken:
            self.last_spoken_answer = " ".join(turn.spoken)

        marks = turn.marks
        llm_ms = round(max(0.0, (llm_first_at - llm_started) * 1000.0), 1) if llm_first_at else 0.0
        t_sent = play_stats["first_sent_at"] or llm_first_at or llm_started
        llm_clause_ms = round(max(0.0, (t_sent - llm_started) * 1000.0), 1) if play_stats["first_sent_at"] else llm_ms
        tts_ms = round(max(0.0, (play_stats["tts_first_at"] - t_sent) * 1000.0), 1) if play_stats["tts_first_at"] else 0.0
        t_play = play_stats["play_first_at"]
        play_ms = round(max(0.0, (t_play - play_stats["tts_first_at"]) * 1000.0), 1) if (t_play and play_stats["tts_first_at"]) else 0.0
        gaps = play_stats["gaps"]
        extra = {
            # etapas 4 e 5: decisão de intenção/modo + busca nas notas (instantes REAIS em que o agente começou cada etapa)
            "agent_prep_ms": round((marks["writing"] - llm_started) * 1000.0, 1) if "writing" in marks else None,
            "understand_ms": round((marks.get("searching", marks.get("writing")) - marks["understanding"]) * 1000.0, 1)
            if "understanding" in marks and ("searching" in marks or "writing" in marks) else None,
            "search_ms": round((marks.get("sources", marks.get("writing")) - marks["searching"]) * 1000.0, 1)
            if "searching" in marks and ("sources" in marks or "writing" in marks) else 0.0,
            "searched": "searching" in marks,
            "complete_ms": round(max(0.0, (time.monotonic() - last_speech_at) * 1000.0), 1),
            "synth_first_ms": play_stats["synth_ms"][0] if play_stats["synth_ms"] else None,
            "gap_max_ms": round(max(gaps), 1) if gaps else 0.0,
            "gap_total_ms": round(sum(gaps), 1) if gaps else 0.0,
            "underruns": sum(1 for g in gaps if g > 150.0),
            "q_audio_max": play_stats["q_audio_max"],
            "q_sentence_max": play_stats["q_sentence_max"],
            "sentences": play_stats["sentences"],
            "vault_free": bool(turn.vault["free"]),
        }
        self._record_timings(s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, llm_ms, t_play, early_hit,
                             tts_ms=tts_ms, play_ms=play_ms, llm_clause_ms=llm_clause_ms, extra=extra)
        if self.active and self.state != "user_speaking":
            self._set_state("listening")

    def _on_agent_status(self, turn, ev):
        """Etapas REAIS do agente (só chegam quando a etapa começa de fato): alimentam os tempos e o texto do estado
        ("Consultando suas notas…" só aparece se o agente realmente está buscando nas notas)."""
        stage = ev.get("stage")
        if not stage:
            return
        turn.marks.setdefault(stage, time.monotonic())
        phase = ""
        if stage == "searching":
            phase = "searching"
        elif stage == "tool" and ev.get("detail") in ("search_knowledge", "read_document", "follow_links", "open_document"):
            phase = "tool"
        elif stage in ("web", "screen", "visual", "reviewing", "compacting"):
            phase = stage
        if self.state == "thinking":
            self._set_state("thinking", phase=phase)
        self._emit({"type": "activity", "stage": stage, "label": PHASE_LABELS.get(phase, "")})

    @staticmethod
    def _pop_ready_sentences(buf, first=False):
        """Extrai frases já fechadas por pontuação (ou a 1ª oração curta de ~25 a 45 caracteres via `listen._first_cut`)
        e devolve `(resto, [frases])`."""
        ready = []
        while buf:
            # Evita cortar uma citação [S#] ainda aberta no meio do streaming
            open_br = buf.rfind("[") > buf.rfind("]")
            if first and not open_br and len(buf) >= 20:
                m_punc = re.search(r"[,;:\u2014]\s+", buf[14:FIRST_CALL_CHARS + 28])
                if m_punc:
                    cut = 14 + m_punc.end()
                    seg = speech_text(buf[:cut], clause=True).strip()
                    buf = buf[cut:].lstrip()
                    if seg:
                        ready.append(seg)
                        first = False
                        continue
            m_end = re.search(r"[.!?…]+(?:\s+|\n+)", buf)
            if m_end and not (open_br and m_end.end() > buf.rfind("[")):
                cut = m_end.end()
                seg = speech_text(buf[:cut]).strip()
                buf = buf[cut:]
                if seg:
                    ready.append(seg)
                    first = False
                    continue
            if first and not open_br and len(buf) >= 56:
                m_conj = re.search(
                    r"\s+(?:porque|pois|para|quando|onde|enquanto|mas|porém|como|transferindo|mantendo|levando|gerando)\s+",
                    buf[20:56], flags=re.I
                )
                if m_conj:
                    cut = 20 + m_conj.start()
                    seg = speech_text(buf[:cut], clause=True).strip()
                    buf = buf[cut:].lstrip()
                    if seg:
                        ready.append(seg)
                        first = False
                        continue
                parts = listen._first_cut(buf, target=FIRST_CALL_CHARS)
                if len(parts) > 1 and len(parts[0]) >= 20:
                    idx_sp = buf.find(" ", len(parts[0]) - 2)
                    if idx_sp >= 20:
                        seg = speech_text(buf[:idx_sp], clause=True).strip()
                        buf = buf[idx_sp:].lstrip()
                        if seg:
                            ready.append(seg)
                            first = False
                            continue
            break
        return buf, ready

    def _speak_sentences(self, sentences, s, record_answer=True):
        """Sintetiza e toca uma lista pronta de frases (usada em comandos rápidos e intenções especiais)."""
        turn = self._t()
        q = queue.Queue()
        n = 0
        for st in sentences:
            st = (st or "").strip()
            while st:
                piece, st = split_chunk(st, chunk_limit(n))
                q.put(("say", piece))
                n += 1
        q.put(None)
        stats = {"first_sent_at": time.monotonic(), "tts_first_at": None, "play_first_at": None,
                 "gaps": [], "q_sentence_max": 0, "q_audio_max": 0, "synth_ms": [], "sentences": 0}
        if turn is not None:
            turn.spoken, turn.current, turn.frac = [], "", 0.0
        self._tts_and_play_worker(q, s, stats, record_answer, turn)
        if turn is not None and record_answer and turn.spoken and turn.alive:
            self.last_spoken_answer = " ".join(turn.spoken)
        return stats["play_first_at"]

    def _tts_and_play_worker(self, sentence_q, s, stats, record_answer=True, turn=None):
        """Duas filas encadeadas: sintetiza até `listen.AHEAD` frases à frente enquanto o Python toca a frase atual.
        Tudo aqui pertence a `turn`: cancelado o turno, a síntese e a reprodução dele param e nada dele chega à tela."""
        turn = turn or self._t()
        self._tl.turn = turn
        audio_q = queue.Queue(maxsize=listen.AHEAD + 1)
        # Na chamada o áudio nunca vai para o disco (4.2 e 4.4): `cache_mb = 0`; frases de espera ficam só na RAM.
        s_tts = {**s, "speed": s.get("call_speed", 1.0), "cache_mb": 0}

        stop_synth = threading.Event()   # o tocador saiu (cancelamento, erro de áudio ou fim): a síntese também para

        def check():
            if turn.cancel.is_set() or not self.active or stop_synth.is_set():
                raise Cancelled()

        def synth_loop():
            self._tl.turn = turn
            try:
                w = self.who or listen.who("call", s_tts, start=False)
                steps = listen.STEPS.get(s_tts.get("call_quality", "balanced"), 12) if w["engine"] == "voicestudio" else None
                seed = listen.seeds(s_tts)[0]
                eng = listen.engine_for(w, s_tts, steps)
                idx = 0
                while turn.alive and self.active and not stop_synth.is_set():
                    item = sentence_q.get()
                    if item is None:
                        break
                    stats["q_sentence_max"] = max(stats["q_sentence_max"], sentence_q.qsize() + 1)
                    kind, text = item
                    clean = speech_text(text, clause=text.rstrip().endswith((",", ";", ":")))
                    if not clean:
                        continue
                    if stats.get("first_sent_at") is None and kind == "say":
                        stats["first_sent_at"] = time.monotonic()
                    first_steps = s_tts.get("_first_steps") or (
                        listen.STEPS["fast"] if s_tts.get("call_first_quality") == "fast" and steps and steps > listen.STEPS["fast"] else None)
                    cur_steps = (int(first_steps) if (idx == 0 and kind == "say" and first_steps and w["engine"] == "voicestudio")
                                 else steps)
                    fkey = (w.get("voice"), cur_steps, clean) if kind == "filler" else None
                    t_syn = time.monotonic()
                    if fkey and fkey in _FILLER_CACHE:
                        data, secs = _FILLER_CACHE[fkey]
                    else:
                        data, secs, _ = self._synth_fn(clean, w, s_tts, cur_steps, seed, check, None, eng)
                        if fkey and len(_FILLER_CACHE) < 16:
                            _FILLER_CACHE[fkey] = (data, secs)
                    _TTS_WARM.set()
                    if not turn.alive or stop_synth.is_set():
                        break   # a síntese terminou depois da interrupção: o áudio é descartado, nunca entra na fila
                    stats["synth_ms"].append(round((time.monotonic() - t_syn) * 1000.0, 1))
                    if stats["tts_first_at"] is None and kind == "say":
                        stats["tts_first_at"] = time.monotonic()
                    samples = wav_to_float24k(data)
                    while turn.alive and self.active and not stop_synth.is_set():
                        try:
                            audio_q.put((kind, idx, clean, samples, secs), timeout=0.05)
                            stats["q_audio_max"] = max(stats["q_audio_max"], audio_q.qsize())
                            if kind == "say":
                                idx += 1
                            break
                        except queue.Full:
                            continue
            except Cancelled:
                pass
            except AppError as e:
                self._emit({"type": "error", "message": str(e), "action": e.action})
            except Exception as e:  # noqa: BLE001
                log.warning("síntese na chamada: %s: %s", type(e).__name__, e)
                self._emit({"type": "error", "message": "A voz falhou nesta resposta. O texto segue na legenda.", "action": ""})
            finally:
                while True:   # o sinal de fim nunca bloqueia, mesmo com a fila cheia e o tocador já fora
                    try:
                        audio_q.put_nowait(None)
                        break
                    except queue.Full:
                        try:
                            audio_q.get_nowait()
                        except queue.Empty:
                            pass

        synth_t = threading.Thread(target=synth_loop, daemon=True, name="Lumen call synth")
        synth_t.start()

        try:
            first_item = audio_q.get()
            if first_item is not None and turn.alive and self.active:
                with self._speaker_lock, self._speaker_factory() as sp:
                    item = first_item
                    while item is not None and self.active and turn.alive:
                        kind, idx, text, samples, secs = item
                        if self.state != "speaking":
                            self._set_state("speaking")
                        if stats["play_first_at"] is None and kind == "say":
                            stats["play_first_at"] = time.monotonic()
                            turn.audio = None   # já há som: depois disto uma retomada é um turno novo, não a mesma frase
                        if kind == "say":
                            turn.current = text
                            turn.frac = 0.0
                            stats["sentences"] += 1
                            spoken_prefix = (" ".join(turn.spoken) + " " + text).strip()
                            self._emit({"type": "sentence", "i": idx, "text": text, "spoken_so_far": spoken_prefix,
                                        "seconds": round(float(secs), 2)})
                        total = max(1, samples.size)
                        pos = 0
                        while pos < samples.size and self.active:
                            if turn.cancel.is_set():
                                # Descida suave de 50 ms para cortar sem estalo + esvaziar buffer WASAPI (< 70 ms total)
                                rem = samples[pos:pos + FADE_SAMPLES]
                                if rem.size:
                                    env = np.linspace(1.0, 0.0, rem.size, dtype=np.float32)
                                    sp.play(rem * env * self.volume)
                                if hasattr(sp, "flush"):
                                    sp.flush()
                                break
                            chunk = samples[pos:pos + PLAY_CHUNK] * self.volume
                            self._echo.push_speaker_24k(chunk)
                            sp.play(chunk)
                            pos += PLAY_CHUNK
                            if kind == "say":
                                turn.frac = min(1.0, pos / total)
                            now = time.monotonic()
                            if now - self._last_voice_emit >= 0.06:
                                self._last_voice_emit = now
                                amp = float(np.sqrt(np.mean(chunk * chunk))) * 3.2 if chunk.size else 0.0
                                self._emit({"type": "level", "source": "voice", "level": round(min(1.0, amp), 3)})
                        if turn.alive and kind == "say" and record_answer:
                            turn.spoken.append(text)
                            turn.current = ""
                            turn.frac = 0.0
                        if turn.cancel.is_set() or not self.active:
                            break
                        t_wait = time.monotonic()
                        item = audio_q.get()
                        if item is not None:
                            # tempo parado esperando a próxima frase, menos o que ainda restava no buffer da placa (~80 ms)
                            stats["gaps"].append(max(0.0, (time.monotonic() - t_wait) * 1000.0 - 80.0))
        except Exception as e:  # noqa: BLE001
            log.warning("áudio da chamada: %s: %s", type(e).__name__, e)
            if not stats.get("audio_error"):
                stats["audio_error"] = True
                self._emit({"type": "error", "message": "A saída de áudio não abriu. A resposta segue na legenda.",
                            "action": "Confira o alto-falante nas configurações de som do Windows."})
        finally:
            stop_synth.set()
            self._emit({"type": "level", "source": "voice", "level": 0.0})
            synth_t.join(timeout=0.5)

    def _finalize_interrupted(self, turn):
        """Corta e salva na conversa exatamente até onde foi falado antes da interrupção (4.1 e 4.3.9). A mensagem fica
        com o que o estudante OUVIU; o que o modelo já tinha escrito a mais fica em `meta.generated`, para a conversa
        escrita não fingir que a resposta inteira foi lida."""
        if turn is None or getattr(turn, "finalized", False):
            return
        turn.finalized = True
        parts = list(turn.spoken)
        if turn.current and turn.frac > 0.02:
            words = turn.current.split()
            keep_n = max(1, int(round(len(words) * turn.frac)))
            parts.append(" ".join(words[:keep_n]).rstrip(" ,;:") + "…")
        spoken = " ".join(parts).strip()
        generated = "".join(turn.generated).strip()
        turn.spoken, turn.current, turn.frac = [], "", 0.0
        mid = None
        if self.conversation_id:
            saved_text = spoken or "*(interrompida)*"
            meta = {"interrupted": True, "call": True}
            if generated and len(generated) > len(spoken) + 8:
                meta["generated"] = generated[:12000]
                meta["spoken_chars"] = len(spoken)
            if turn.mid is not None:
                chats.update_message(self.conversation_id, turn.mid, saved_text, meta)
                mid = turn.mid
            elif spoken:
                m = chats.add_message(self.conversation_id, "assistant", saved_text, turn.sources, meta)
                mid = m["id"]
        turn.mid = None
        if spoken:
            self.last_spoken_answer = spoken
            self._emit({"type": "interrupted", "text": spoken, "message_id": mid, "turn_id": turn.id})

    def _record_timings(self, s, last_speech_at, eos_ms, asr_ms, asr_eng, earcon_ms, llm_ms, play_first_at,
                        early_hit, tts_ms=0.0, play_ms=0.0, llm_clause_ms=0.0, extra=None):
        if isinstance(earcon_ms, list):
            earcon_ms = earcon_ms[0]
        now = play_first_at or time.monotonic()
        total_ms = round(max(0.0, (now - last_speech_at) * 1000.0), 1)
        after_eos_ms = round(max(0.0, total_ms - eos_ms), 1)
        steps = listen.STEPS.get(s.get("call_quality", "balanced"), 12)
        ev = {
            "type": "timing",
            "turn": self.turn_count,
            "eos_ms": eos_ms,
            "earcon_ms": earcon_ms,
            "asr_ms": asr_ms,
            "llm_first_ms": llm_ms,
            "llm_clause_ms": llm_clause_ms,
            "tts_first_ms": tts_ms,
            "play_first_ms": play_ms,
            "after_eos_ms": after_eos_ms,
            "total_ms": total_ms,
            "early_hit": bool(early_hit),
            "asr_engine": asr_eng,
            "steps": steps,
            **(extra or {}),
        }
        self._emit(ev)
        # Privacidade (4.4): o registro de atividades guarda SÓ os tempos, sem nenhum texto falado ou respondido.
        keys = ("eos_ms", "asr_ms", "llm_first_ms", "tts_first_ms", "play_first_ms", "total_ms", "early_hit",
                "search_ms", "complete_ms", "gap_max_ms")
        detail = json.dumps({k: ev[k] for k in keys if k in ev})
        try:
            activity.log("chamada-turno", provider="local", target=asr_eng, result=f"{total_ms:.0f} ms",
                         conversation_id="" if self.temporary else (self.conversation_id or ""), detail=detail)
        except Exception:  # noqa: BLE001
            pass


CALL = CallManager()


# --- Rotas /api/study/call* -------------------------------------------------------------------------------------------

def _events(h):
    since = h._query().get("since", "")
    q = CALL.subscribe(since=int(since) if since.isdigit() else None)
    closed = threading.Event()

    def gen():
        first = True
        try:
            while not closed.is_set():
                try:
                    ev = q.get(timeout=2.0)
                    yield ev
                    if not first and ev.get("type") == "state" and ev.get("state") == "ended":
                        break
                    first = False
                except queue.Empty:
                    yield {"type": "ping"}
        finally:
            CALL.unsubscribe(q)

    return api.Stream(gen(), on_close=lambda: (closed.set(), CALL.unsubscribe(q)))


def _command(h):
    b = h._json()
    action = b.get("action")
    if action == "start":
        return CALL.start(conversation_id=b.get("conversation_id") or None,
                          project_id=b.get("project_id") or None,
                          temporary=b.get("temporary") if "temporary" in b else None,
                          free=bool(b.get("skip_vault")) if "skip_vault" in b else None,
                          sources=b.get("vault_sources") if b.get("vault_sources") is not None else None,
                          profile=b.get("profile") or None)
    if action == "vault":
        return CALL.set_vault(free=b.get("skip_vault") if "skip_vault" in b else None,
                              sources=b.get("vault_sources") if "vault_sources" in b else "keep",
                              profile=b.get("profile") if "profile" in b else None)
    if action == "stop":
        return CALL.stop(reason="user")
    if action == "mute":
        return CALL.set_mute(b.get("muted") if "muted" in b else None)
    if action == "interrupt":
        return CALL.interrupt()
    if action == "ptt_down":
        return CALL.ptt_down()
    if action == "ptt_up":
        return CALL.ptt_up()
    if action == "settings":
        return CALL.update_settings(b.get("settings") or {}, persist=b.get("persist"))
    if action == "state":
        return CALL.snapshot()
    raise AppError("Comando de chamada desconhecido.")


ROUTES = {
    ("GET", "/api/study/call"): lambda h: CALL.snapshot(),
    ("GET", "/api/study/call/events"): _events,
    ("POST", "/api/study/call"): _command,
}
