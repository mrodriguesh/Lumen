"""Filtro de música externa (Ajustes → “Filtrar música externa”, desligado por padrão).

Protege a transcrição da música que toca junto com a aula. Desligado, nenhum modelo é carregado e a transcrição
segue exatamente como antes (o módulo só guarda regras e rótulos; os modelos abrem em _session).

Ordem (docs/DECISOES.md, “Filtro de música externa”):
1. isolar a fonte: na gravação, o som dos apps de música nem é gravado (lumen/record.py);
2. detectar (YAMNet, AudioSet): fala, canto/rap e música a cada 0,48 s, com confiança;
3. separar a voz (MDX-Net, na GPU se houver) só onde há música e a fala não se ouve com clareza;
4. validar a fala, combinando sinais: a sonda (voz separada + mistura + o quanto a voz segue a batida, para o
   rap), a dominância da música e a voz dos locutores da aula (lumen/speaker.py: referência tirada da fala limpa
   da própria aula). A voz separada só entra onde há fala com certeza e a música domina; voz parecida com a de quem
   ensina é protegida; na dúvida (letra, rap, voz diferente), fica o original e o trecho é marcado como incerto;
5. o ASR recebe um WAV derivado, em cache na pasta da aula. O arquivo original nunca é alterado.
Os modos (conservador, balanceado, agressivo) só mudam os limiares de MODES.
Na dúvida, preserva a fala: é melhor sobrar um pouco de música do que perder uma explicação. O que o benchmark
mostrou e mudou neste desenho está em docs/DECISOES.md."""
import hashlib
import json
import logging
import os
import time
import wave
from pathlib import Path

import numpy as np

from . import AppError, Cancelled, audio, speaker

log = logging.getLogger("lumen")
VERSION = 2  # muda com a regra de decisão: invalida o cache
# (repositório, revisão fixa, arquivo). YAMNet: Google, Apache-2.0. UVR-MDX-NET 3 (9662): MDX-Net do Ultimate Vocal
# Remover, espelho do python-audio-separator. Escolha e medições em docs/DECISOES.md e bench/music_bench.py.
DETECTOR = ("zeropointnine/yamnet-onnx", "ac2ca3bd45d12ec1f19f1144205ea529b4e9dedf", "yamnet.onnx")
SEPARATOR = ("nomadkaraoke/public_uvr_models", "f47f33a33c05035e6829432e3063c2e37a99263f", "UVR_MDXNET_3_9662.onnx")
SEP = {"n_fft": 6144, "dim_f": 2048, "dim_t": 256, "compensate": 1.035}  # do model_data.json do UVR
SIZE = "≈ 72 MB"  # detector 16 + separador 30 + voz 26
HOP = 7680  # 0,48 s a 16 kHz: o YAMNet dá um quadro a cada HOP amostras (cada um olha 0,96 s)
SPEECH, SING, MUSIC = slice(0, 4), slice(24, 33), slice(132, 277)  # classes do AudioSet (yamnet_class_map.csv)

# GPU para o separador e a voz: DirectML (qualquer GPU DirectX 12 no Windows: NVIDIA, AMD, Intel; pacote
# onnxruntime-directml) ou CUDA (onnxruntime-gpu). Sem nenhum dos dois, ou se a GPU falhar, a CPU. O detector fica
# sempre na CPU: é leve (750× o tempo real) e a sonda foi treinada com a saída dele na CPU.
GPU = ("DmlExecutionProvider", "CUDAExecutionProvider")
_sessions = {}
_gpu_failed = False  # a GPU falhou uma vez neste processo: não insiste


def _file(model, local=True):
    from huggingface_hub import hf_hub_download
    repo, rev, name = model
    return hf_hub_download(repo, name, revision=rev, local_files_only=local)


def _have(*models):
    try:
        for m in models:
            _file(m)
        return True
    except Exception:
        return False


def ready():
    return _have(DETECTOR, SEPARATOR, speaker.MODEL)


def download():
    try:
        for m in (DETECTOR, SEPARATOR, speaker.MODEL):
            _file(m, local=False)
    except Exception as e:
        raise AppError("Não foi possível baixar o filtro de música.",
                       "Verifique a internet e o espaço em disco e tente de novo.") from e


def _session(model):
    """Sessão ONNX: na GPU (GPU, acima) se houver, senão na CPU."""
    if model not in _sessions:
        import onnxruntime
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = max(2, (os.cpu_count() or 4) // 2)  # mais threads não acelerou (bench) e trava o PC
        # sem o “arena” do onnxruntime: pico 0,65 GB em vez de 1,2 GB no separador, mesma velocidade (medido);
        # sem “memory pattern”: o DirectML exige
        opts.enable_cpu_mem_arena = opts.enable_mem_pattern = False
        gpu = [] if model == DETECTOR or _gpu_failed else [
            p for p in GPU if p in onnxruntime.get_available_providers()]
        try:
            _sessions[model] = onnxruntime.InferenceSession(_file(model), opts, providers=gpu + ["CPUExecutionProvider"])
        except Exception as e:  # noqa: BLE001 — GPU sem memória ou driver: CPU
            if not gpu:
                raise
            _gpu_off(e)
            _sessions[model] = onnxruntime.InferenceSession(_file(model), opts, providers=["CPUExecutionProvider"])
    return _sessions[model]


def _gpu_off(e):
    global _gpu_failed
    _gpu_failed = True
    log.warning("filtro de música: GPU indisponível (%s); seguindo na CPU", type(e).__name__)


def _run(model, feeds, names=None):
    """Roda um modelo. Se a GPU falhar no meio (driver, memória), refaz a sessão na CPU e roda de novo."""
    s = _session(model)
    try:
        return s.run(names, feeds)
    except Exception as e:  # noqa: BLE001
        if s.get_providers()[0] == "CPUExecutionProvider":
            raise
        _gpu_off(e)
        del _sessions[model]
        return _session(model).run(names, feeds)


def device():
    s = _sessions.get(SEPARATOR)
    return "GPU" if s and s.get_providers()[0] != "CPUExecutionProvider" else "CPU"


def release():
    """Solta os modelos (≈ 300 MB de RAM) depois de preparar o áudio: a transcrição vem em seguida."""
    _sessions.clear()


# ---------------------------------------------------------------- detecção

def detect(x):
    """Confiança (0–1) de fala, canto/rap e música, o embedding (1024) e o nível (RMS) de cada quadro de 0,48 s."""
    n = max(1, -(-len(x) // HOP))
    step = 125  # 1 min por vez: de 10 em 10 min o YAMNet chegava a 3 GB de RAM
    sc, emb = [], []
    for i in range(0, n, step):
        seg = np.ascontiguousarray(x[i * HOP:(i + step + 1) * HOP], dtype=np.float32)
        if len(seg) < 2 * HOP:
            seg = np.pad(seg, (0, 2 * HOP - len(seg)))
        a, b = _run(DETECTOR, {"waveform": seg}, ["output_0", "output_1"])
        sc.append(a[:step])
        emb.append(b[:step])
    sc, emb = (np.pad(v, ((0, max(0, n - len(v))), (0, 0)), mode="edge")[:n]
               for v in (np.concatenate(sc), np.concatenate(emb)))
    pad = np.pad(x, (0, n * HOP - len(x)))
    rms = np.sqrt(np.mean(pad.reshape(n, HOP) ** 2, axis=1) + 1e-12)
    return {"speech": sc[:, SPEECH].max(1), "sing": sc[:, SING].max(1), "music": sc[:, MUSIC].max(1), "emb": emb,
            "rms": rms}


LEVEL_RMS = 0.03  # nível típico de uma aula; abaixo disso o detector recebe o áudio mais alto (só ele)


def level_gain(x):
    """Ganho para o detector: o YAMNet perde a música abaixo de ≈ −50 dBFS (aula gravada muito baixa: música
    detectada em 0–2% dos quadros, contra 53–63% no volume normal). Áudio quieto sobe até LEVEL_RMS, no máximo 30 dB;
    áudio no volume normal fica como está, e o que vai para o ASR nunca muda de volume."""
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0
    return float(np.clip(LEVEL_RMS / max(rms, 1e-9), 1.0, 31.6))


# ---------------------------------------------------------------- separação (MDX-Net)

SR_SEP, HOP_SEP = 44100, 1024


def _stft(x, n_fft, win):
    """[canais, amostras] → [canais, bins, quadros] complexo, igual a torch.stft(center=True, reflect)."""
    xp = np.pad(x, ((0, 0), (n_fft // 2, n_fft // 2)), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(xp, n_fft, axis=-1)[:, ::HOP_SEP] * win
    return np.fft.rfft(frames, axis=-1).transpose(0, 2, 1)


def _istft(spec, n_fft, win, length):
    frames = np.fft.irfft(spec.transpose(0, 2, 1), n=n_fft, axis=-1).astype(np.float32) * win
    total = n_fft + HOP_SEP * (frames.shape[1] - 1)
    out = np.zeros((spec.shape[0], total), np.float32)
    norm = np.zeros(total, np.float32)
    for t in range(frames.shape[1]):
        out[:, t * HOP_SEP:t * HOP_SEP + n_fft] += frames[:, t]
        norm[t * HOP_SEP:t * HOP_SEP + n_fft] += win ** 2
    out /= np.maximum(norm, 1e-8)
    return out[:, n_fft // 2:n_fft // 2 + length]


def separate(x, check=lambda: None):
    """Voz (fala ou canto) sem os instrumentos, mono 16 kHz, do mesmo tamanho de x. Como o UVR: blocos de
    HOP_SEP × (dim_t − 1) amostras a 44,1 kHz, sobrepostos 25% com janela de Hann."""
    n_fft, dim_f, dim_t = SEP["n_fft"], SEP["dim_f"], SEP["dim_t"]
    win = np.hanning(n_fft + 1)[:-1].astype(np.float32)  # Hann periódica, como torch.hann_window
    chunk, trim = HOP_SEP * (dim_t - 1), n_fft // 2
    m = audio.resample(np.ascontiguousarray(x, dtype=np.float32), audio.SR, SR_SEP)
    gen = chunk - 2 * trim
    mix = np.concatenate([np.zeros(trim, np.float32), m, np.zeros(gen + trim - len(m) % gen, np.float32)])
    mix = np.stack([mix, mix])  # o modelo é estéreo; a entrada do ASR é mono
    out, weight = np.zeros_like(mix), np.zeros(mix.shape[1], np.float32)
    fade = np.hanning(chunk).astype(np.float32)
    for i in range(0, mix.shape[1], int(0.75 * chunk)):
        check()
        part = mix[:, i:i + chunk]
        n = part.shape[1]
        spec = _stft(np.pad(part, ((0, 0), (0, chunk - n))), n_fft, win)[:, :dim_f]
        spec[:, :3] = 0
        inp = np.stack([spec.real, spec.imag], 1).reshape(1, 4, dim_f, dim_t).astype(np.float32)  # E re/im, D re/im
        pred = _run(SEPARATOR, {"input": inp})[0].reshape(2, 2, dim_f, dim_t)
        full = np.zeros((2, n_fft // 2 + 1, dim_t), np.complex64)
        full[:, :dim_f] = pred[:, 0] + 1j * pred[:, 1]
        out[:, i:i + n] += (_istft(full, n_fft, win, chunk) * fade)[:, :n]
        weight[i:i + n] += fade[:n]
    voc = (out / np.maximum(weight, 1e-8))[:, trim:trim + len(m)].mean(0) * SEP["compensate"]
    return audio.resample(voc, SR_SEP, audio.SR)[:len(x)]


# ---------------------------------------------------------------- modos (o único lugar com os limiares)

# Ajustes → Filtrar música externa → Modo. Cada limiar e de onde ele vem (medições em docs/DECISOES.md):
# - music_on: confiança de música na mistura (YAMNet) a partir da qual o trecho é tratado como música;
# - speech_clear: fala na mistura acima disto deixa o trecho como está (a música não a cobre; não vale separar).
#   Música sozinha, com ou sem letra, ficou abaixo de 0,12 em todas as faixas do MUSDB18 e no hip-hop do GTZAN;
# - keep: probabilidade de fala da sonda (média em ≈ 5 s) a partir da qual há fala da aula com certeza; abaixo, o
#   trecho é marcado como incerto (música ao fundo);
# - sep_keep: probabilidade de fala a partir da qual a voz separada pode entrar (com a música dominando). Pode ser
#   menor que keep: a dominância já barra a letra (o cantor entra na “voz” e a música fica só 1–3,6 dB acima).
#   Medido (balanceado): 0,6 → 0,5 perdeu 5% menos palavras da fala nas aulas do conjunto v2 com o mesmo total de
#   erros (+0,5%) e recuperou fala curta sob instrumental (+5 dB: WER 57% → 51,5%); abaixo de 0,5, a fala rápida
#   e a de dois professores pioravam (a voz separada traz artefatos). Sem mudança na letra transcrita;
# - dominant_db: a voz separada só substitui o original onde a música está pelo menos isto acima da voz. Fala sob
#   instrumental a +5 a +15 dB dá 7,7 a 19 dB; música com letra, 1 a 3,6 dB (o cantor entra na “voz”). Abaixo de
#   ≈ 7 dB a voz isolada trazia artefatos e fazia o ASR transcrever a letra que, na mistura, ele ignorava;
# - teacher_sim: voz parecida assim com um locutor da aula (lumen/speaker.py) é de quem ensina: nunca é silenciada
#   nem marcada, e a voz separada pode entrar mesmo com a sonda em dúvida;
# - other_sim: voz diferente assim de todos os locutores da aula (cantor, rapper, voz da música): o trecho é
#   marcado mesmo com a sonda achando que é fala (−1 = desligado). Medido no balanceado (conjunto v2): a 0,2, a letra
#   sem marca caiu de 69 para 24 palavras, mas a fala do professor marcada subiu de 849 para 1601 (sob música, um
#   quarto das janelas do próprio professor fica abaixo de 0,25). Por isso só no agressivo;
# - mute: silencia onde a sonda tem certeza de que só há música (0 = nunca); mute_other: silencia também a voz
#   diferente dos locutores da aula com a sonda em dúvida. Os dois só valem na música que toca por baixo da
#   aula (external), nunca na música que toca sozinha.
MODES = {
    "conservador": {"music_on": 0.3, "speech_clear": 0.3, "keep": 0.7, "sep_keep": 0.6, "dominant_db": 7.0, "teacher_sim": 0.4,
                    "other_sim": -1.0, "mute": 0.0, "mute_other": False, "min_mute_s": 4.0},
    "balanceado": {"music_on": 0.3, "speech_clear": 0.3, "keep": 0.6, "sep_keep": 0.5, "dominant_db": 7.0, "teacher_sim": 0.4,
                   "other_sim": -1.0, "mute": 0.0, "mute_other": False, "min_mute_s": 2.5},
    "agressivo": {"music_on": 0.25, "speech_clear": 0.5, "keep": 0.6, "sep_keep": 0.3, "dominant_db": 5.0, "teacher_sim": 0.4,
                  "other_sim": 0.2, "mute": 0.3, "mute_other": True, "min_mute_s": 2.5},
}
MODE = "balanceado"
MIN_SEP_S = 3.0    # trechos mais curtos de voz separada ficam com o original: uma ilha de 1 s mudava toda a
                   # decodificação do Whisper (num caso, de 2 para 42 palavras de letra)
MIN_MUSIC_S = 2.0  # menos música que isso na aula toda: não mexe em nada
EXTERNAL_S = 3.0   # música que cobre pelo menos isto de fala é música ao fundo (externa); sem fala por baixo, é a
                   # própria aula (o professor tocando uma música, vinheta) ou uma faixa sozinha: não é silenciada
CONTEXT_S = 2      # contexto de cada lado ao separar um bloco
BLOCK_S = 60       # separa até 1 min por vez (≈ 20 MB por bloco a 44,1 kHz)
FADE = 320         # 20 ms de transição entre original, voz separada e silêncio
WINDOW = 5         # a decisão olha a média da sonda em ±5 quadros (≈ 5 s): a sonda oscila de um quadro a outro


# ---------------------------------------------------------------- sinais

def _probe():
    if "probe" not in _sessions:
        p = json.loads((Path(__file__).parent / "music_probe.json").read_text("utf-8"))
        _sessions["probe"] = (np.asarray(p["w"], np.float32), float(p["b"]))
    return _sessions["probe"]


def features(voice, mixture, rh):
    """O que a sonda vê em cada quadro: os embeddings do YAMNet da voz separada e da mistura e o ritmo da voz
    (rhythm). Só a voz não basta: o YAMNet acha que canto e rap separados são fala; a mistura mostra a música em
    volta; o ritmo separa o rap (voz presa à batida) de alguém falando por cima de uma música."""
    return np.concatenate([voice["emb"], mixture["emb"], rh], 1)


def speech_probability(voice, mixture, rh):
    """Probabilidade de haver fala da aula em cada quadro (sonda linear treinada por bench/music_bench.py)."""
    w, b = _probe()
    return 1 / (1 + np.exp(-np.clip(features(voice, mixture, rh) @ w + b, -30, 30)))


def _onset(x):
    """Ataques (subidas de energia) a 100 por segundo."""
    n = max(1, -(-len(x) // 160))
    e = np.log(np.mean(np.pad(x, (0, n * 160 - len(x)))[:n * 160].reshape(n, 160) ** 2, 1) + 1e-8)
    return np.maximum(0, np.diff(e, prepend=e[:1]))


def _sync(ov, oa):
    """(periodicidade da voz no período da batida, correlação entre os ataques da voz e os do acompanhamento)."""
    ov, oa = ov - ov.mean(), oa - oa.mean()
    ac = lambda o: np.fft.irfft(np.abs(np.fft.rfft(o, 2 * len(o))) ** 2)[:len(o)] / (np.sum(o ** 2) + 1e-9)
    aa, av = ac(oa), ac(ov)
    beat = 25 + int(np.argmax(aa[25:150]))  # 0,25–1,5 s: 40–240 batidas por minuto
    per = max(av[beat], av[beat // 2] if beat // 2 >= 12 else 0, av[2 * beat] if 2 * beat < len(av) else 0)
    xc = np.fft.irfft(np.fft.rfft(ov, 2 * len(ov)) * np.conj(np.fft.rfft(oa, 2 * len(oa))))
    xc = np.concatenate([xc[-3:], xc[:4]]).max() / (np.sqrt(np.sum(ov ** 2) * np.sum(oa ** 2)) + 1e-9)
    return per, xc


def rhythm(v, x, frames):
    """Quanto a voz separada v segue a batida da música (x − v), em ±3 s de cada quadro marcado em `frames`; zero
    nos outros. Medido (AUC rap × professor sobre música): 0,73 e 0,76; canto também fica alto."""
    ov, oa = _onset(v), _onset(x - v)
    out = np.zeros((len(frames), 2), np.float32)
    for j in np.flatnonzero(frames):
        c = (j + 1) * HOP // 160
        a, b = max(0, c - 300), min(len(ov), c + 300)
        if b - a >= 200:
            out[j] = _sync(ov[a:b], oa[a:b])
    return out


def voices(x, v, d, music, region, check=lambda: None):
    """(similaridade de cada quadro de `region` com o locutor da aula mais parecido — NaN onde não foi medida —,
    número de locutores). Os locutores vêm da fala limpa da própria aula (sem música; se não houver, fala clara
    sobre música baixa), agrupados por voz: dois professores, entrevista ou aluno perguntando dão dois ou mais.
    Quem só fala sob música alta não vira referência, mas também não é tratado como música só por isso: a voz
    diferente só muda a decisão junto com a sonda. Sem o modelo de voz ou sem fala limpa: (None, 0)."""
    if not _have(speaker.MODEL):
        return None, 0
    run = lambda f: _run(speaker.MODEL, {"feats": f})[0]
    W = 6  # quadros por janela (≈ 3 s)
    clear = (_near(d["speech"], 1, np.min) >= 0.5) & ~region
    for mask in (clear & ~_near(music, 2, np.max), clear):
        wins = [(a + i, a + i + W) for a, b in _runs(mask) for i in range(0, b - a - W + 1, W)]
        if len(wins) >= 4:
            break
    if len(wins) < 2:
        return None, 0
    pick = np.unique(np.linspace(0, len(wins) - 1, min(len(wins), speaker.ENROLL_MAX)).astype(int))
    span = lambda a, b, y: y[a * HOP + HOP // 2:b * HOP + HOP // 2]
    E = np.stack([speaker.embed(run, span(*wins[i], x)) for i in pick])
    spk = [(c, w) for c, w in speaker.cluster(E, np.ones(len(E)), speaker.CLUSTER_SIM) if w >= 2]
    if not spk:
        return None, 0
    acc, cnt = np.zeros(len(region)), np.zeros(len(region))
    quiet = 0.05 * np.sqrt(np.mean(x ** 2) + 1e-12)
    for a, b in _runs(region):
        for s in range(a, max(a + 1, b - W + 1), W // 2):
            check()
            e = min(b, s + W)
            seg = span(s, e, v)
            if len(seg) >= 3 * HOP and np.sqrt(np.mean(seg ** 2)) > quiet:
                acc[s:e] += speaker.similarity(speaker.embed(run, seg), spk)
                cnt[s:e] += 1
    return np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan), len(spk)


# ---------------------------------------------------------------- decisão

def _runs(mask):
    """[(início, fim)] dos trechos True, em quadros."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def _near(a, k, fn):
    """Máximo (ou mínimo, ou mediana) de cada quadro com os k vizinhos de cada lado."""
    return fn(np.lib.stride_tricks.sliding_window_view(np.pad(a, k, mode="edge"), 2 * k + 1), axis=1)


def _splice(y, src, a, b):
    """y[quadros a:b] = src (None = silêncio), com transição de FADE amostras. O quadro j do YAMNet é centrado em
    (j + 1) · HOP: vale para as amostras de j · HOP + HOP/2 a (j + 1) · HOP + HOP/2."""
    s0 = 0 if a == 0 else min(a * HOP + HOP // 2, len(y))  # o último quadro pode começar depois do fim do áudio
    s1 = len(y) if b * HOP + HOP // 2 >= len(y) else b * HOP + HOP // 2
    if s1 <= s0:
        return
    g = np.ones(s1 - s0, np.float32)
    f = min(FADE, (s1 - s0) // 2)
    if f and s0 > 0:
        g[:f] = np.linspace(0, 1, f, dtype=np.float32)
    if f and s1 < len(y):
        g[-f:] = np.minimum(g[-f:], np.linspace(1, 0, f, dtype=np.float32))
    new = 0 if src is None else src[s0:s1]
    y[s0:s1] = y[s0:s1] * (1 - g) + new * g


def regions(d, cfg=MODES[MODE]):
    """(quadros com música, quadros a separar): música estável por ≈ 2 s, com um quadro de margem, menos onde a fala
    se ouve com clareza na própria mistura (lá a voz separada nunca seria usada; não vale gastar CPU)."""
    music = _near(d["music"], 2, np.median) >= cfg["music_on"]
    region = _near(music, 1, np.max)
    return music, region & (_near(d["speech"], WINDOW, np.max) < cfg["speech_clear"])


def dominance(x, v):
    """Quanto a música (x − v) está acima da voz separada v, em dB, por quadro (energias em ±WINDOW quadros)."""
    n = max(1, -(-len(x) // HOP))
    blocks = lambda a: np.mean(np.pad(a, (0, n * HOP - len(a))).reshape(n, HOP).astype(np.float64) ** 2, axis=1)
    acc, voice = _near(blocks(x - v), WINDOW, np.mean), _near(blocks(v), WINDOW, np.mean)
    return 10 * np.log10((acc + 1e-10) / (voice + 1e-10))


def external(music, talk):
    """Quadros de música que toca também por baixo da fala (`talk`): música ao fundo. Buracos de até ≈ 4 s entre
    trechos de música contam como a mesma música (troca de faixa, pausa)."""
    sec = HOP / audio.SR
    out = np.zeros(len(music), bool)
    for a, b in _runs(_near(music, 4, np.max)):
        if talk[a:b].sum() * sec >= EXTERNAL_S:
            out[a:b] = True
    return out & music


def decide(p, dom, region, cfg, sim=None, music=None, speech=None):
    """Máscaras por quadro a partir dos sinais, dentro da região a separar. O benchmark escolhe a sonda e os
    limiares com esta mesma função. Sem `sim` (sem modelo de voz ou sem fala limpa), a decisão é a da versão 1.

    - professor (teacher): voz parecida com um locutor da aula; protegida;
    - fala (talk): a sonda tem certeza de fala, ou é o professor;
    - silenciar (só nos modos que silenciam, só na música ao fundo): a sonda tem certeza de que não há fala, ou a voz
      é diferente dos locutores da aula e a sonda está em dúvida, por ≥ min_mute_s;
    - voz separada: há fala e a música domina a voz (é onde o ASR erra);
    - dúvida (marcada, fica o original): a sonda está em dúvida ou a voz é diferente da dos locutores da aula."""
    sec = HOP / audio.SR
    p = _near(p, WINDOW, np.mean)  # a sonda oscila de quadro a quadro; a média em ≈ 5 s é estável
    s = np.full(len(p), np.nan) if sim is None else sim
    teacher = region & (np.nan_to_num(s, nan=-1) >= cfg["teacher_sim"])
    other = region & (np.nan_to_num(s, nan=1) < cfg["other_sim"])
    talk = (p >= cfg["keep"]) | teacher
    ext = region if music is None else external(music, (speech >= 0.5 if speech is not None else False) | (region & talk))
    mute = region & ext & ~teacher & ((p < cfg["mute"]) | (cfg["mute_other"] & other & (p < cfg["keep"])))
    for a, b in _runs(mute):
        if (b - a) * sec < cfg["min_mute_s"]:  # pausa curta entre frases não é “só música”
            mute[a:b] = False
    sep = region & ~mute & ((p >= cfg["sep_keep"]) | teacher) & (dom >= cfg["dominant_db"])
    for a, b in _runs(sep):
        if (b - a) * sec < MIN_SEP_S:
            sep[a:b] = False
    doubt = region & ~mute & ~teacher & ((p < cfg["keep"]) | other)
    return {"p": p, "mute": mute, "sep": sep, "doubt": doubt, "teacher": teacher, "other": other, "external": ext}


def clean(x, check=lambda: None, progress=lambda p: None, mode=MODE):
    """(áudio para o ASR, relatório) a partir de x (mono 16 kHz). x não é alterado.

    Sem música, ou com a fala clara por cima dela: devolve o próprio x. Com música alta (ver decide): onde há fala,
    a voz separada (sem os instrumentos); na dúvida, o original, marcado; nos modos que silenciam, silêncio onde há
    certeza de que só há música ao fundo."""
    mode = mode if mode in MODES else MODE
    cfg = MODES[mode]
    t0, sec = time.monotonic(), HOP / audio.SR
    g = level_gain(x)
    d = detect(x * g if g > 1 else x)
    music, region = regions(d, cfg)
    rep = {"version": VERSION, "mode": mode, "music_detected": False, "filtered": False, "separated": False,
           "music_s": round(min(float(music.sum() * sec), len(x) / audio.SR), 1), "removed_s": 0.0,
           "separated_s": 0.0, "doubt_s": 0.0,
           "music_confidence": round(float(d["music"][music].mean()), 2) if music.any() else 0.0,
           "speech_confidence": None, "separation_confidence": None, "removed": [], "doubt": []}
    if rep["music_s"] < MIN_MUSIC_S:
        rep["seconds"] = round(time.monotonic() - t0, 1)
        return x, rep
    rep["music_detected"] = True
    if not region.any():  # música, mas a fala se ouve bem o tempo todo: o ASR já se vira com o original
        rep["seconds"] = round(time.monotonic() - t0, 1)
        return x, rep
    v = np.zeros_like(x)  # voz separada, só nos trechos com música
    spans = [(int(a) * HOP, min(len(x), int(b) * HOP + HOP)) for a, b in _runs(region)]
    total, done, block, ctx = sum(b - a for a, b in spans), 0, BLOCK_S * audio.SR, CONTEXT_S * audio.SR
    for a, b in spans:
        for s in range(a, b, block):
            e = min(b, s + block)
            lo, hi = max(0, s - ctx), min(len(x), e + ctx)
            v[s:e] = separate(x[lo:hi], check)[s - lo:e - lo]
            done += e - s
            progress(0.9 * done / total)
    dv = detect(v * g if g > 1 else v)
    dom = dominance(x, v)
    rh = rhythm(v, x, region)
    try:
        sim, n_spk = voices(x, v, d, music, region, check)
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 — sem a voz, decide como a versão 1
        log.warning("filtro de música: referência de voz falhou (%s); decidindo sem ela", type(e).__name__)
        sim, n_spk = None, 0
    m = decide(speech_probability(dv, d, rh), dom, region, cfg, sim, music, d["speech"])
    p, mute, sep, doubt = m["p"], m["mute"], m["sep"], m["doubt"]
    y = x.copy()
    for a, b in _runs(sep):
        _splice(y, v, a, b)
    for a, b in _runs(mute):
        _splice(y, None, a, b)
    spans_s = lambda m: [[round(a * sec + sec / 2, 2), round(b * sec + sec / 2, 2)] for a, b in _runs(m)]
    dur = len(x) / audio.SR
    secs = lambda m: round(min(float(m.sum() * sec), dur), 1)
    measured = region & ~np.isnan(sim) if sim is not None else np.zeros(len(region), bool)
    rep.update(filtered=bool(sep.any() or mute.any()), separated=bool(sep.any()), removed_s=secs(mute),
               separated_s=secs(sep), doubt_s=secs(doubt),
               speech_confidence=round(float(p[region].mean()), 2),
               separation_confidence=round(float(dv["speech"][sep].mean()), 2) if sep.any() else None,
               dominance_db=round(float(np.median(dom[region])), 1),
               speakers=n_spk, speaker_similarity=round(float(np.median(sim[measured])), 2) if measured.any() else None,
               teacher_s=secs(m["teacher"]), other_voice_s=secs(m["other"]), background_s=secs(m["external"]),
               rhythm=round(float(rh[region, 1].mean()), 3),
               removed=spans_s(mute), doubt=spans_s(doubt), seconds=round(time.monotonic() - t0, 1), device=device())
    progress(1.0)
    return y, rep


def mark(segments, rep):
    """Depois do ASR (tempos do arquivo): trecho quase todo dentro do que foi silenciado (letra de música que o
    modelo ainda “ouviu”) sai; trecho com voz e música juntas, sem certeza, fica marcado para revisão. O texto
    nunca é trocado."""
    def inside(seg, spans):
        a, b = seg["start"] or 0, seg["end"] or seg["start"] or 0
        return sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans) / max(b - a, 0.01)
    out = []
    for s in segments:
        if rep.get("removed") and inside(s, rep["removed"]) >= 0.6:
            continue
        if rep.get("doubt") and inside(s, rep["doubt"]) >= 0.3:
            s["uncertain"] = s["music"] = True
        out.append(s)
    return out


def _key(x, mode):
    h = hashlib.sha256(np.ascontiguousarray(x).tobytes())
    voice = f"{speaker.MODEL[1]}|{speaker.VERSION}" if _have(speaker.MODEL) else "sem voz"
    h.update(f"{VERSION}|{mode}|{json.dumps(MODES.get(mode), sort_keys=True)}|{DETECTOR[1]}|{SEPARATOR[1]}|"
             f"{SEPARATOR[2]}|{voice}|{_probe_digest()}".encode())
    return h.hexdigest()[:16]


def _probe_digest():
    return hashlib.sha256((Path(__file__).parent / "music_probe.json").read_bytes()).hexdigest()[:8]


def prepare(path, folder, check=lambda: None, progress=lambda p: None, mode=MODE):
    """(caminho do áudio para o ASR, relatório). O áudio limpo é um WAV derivado em `folder` (cache pelo conteúdo
    do áudio, versão da regra, modelos e modo). Sem música, ou se algo falhar, devolve o próprio `path`: o filtro
    nunca impede a transcrição e o relatório diz por quê."""
    try:
        if not _have(DETECTOR, SEPARATOR):  # o modelo de voz é opcional: sem ele, decide sem a referência de voz
            raise AppError("os modelos do filtro de música não estão baixados")
        x = audio.load(path)
        key = _key(x, mode)
        wav, js = folder / f"music-{key}.wav", folder / f"music-{key}.json"
        try:
            rep = json.loads(js.read_text("utf-8"))
            if not rep.get("filtered") or wav.exists():
                log.info("filtro de música: cache reaproveitado")
                return (str(wav) if rep.get("filtered") else str(path)), {**rep, "cached": True}
        except (OSError, ValueError):
            pass
        y, rep = clean(x, check, progress, mode)
        del x
        if rep["filtered"]:
            tmp = wav.with_suffix(".tmp")
            try:
                with wave.open(str(tmp), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(audio.SR)
                    w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
                os.replace(tmp, wav)
            finally:
                tmp.unlink(missing_ok=True)
        js.write_text(json.dumps(rep), "utf-8")
        _log(rep)
        return (str(wav) if rep["filtered"] else str(path)), rep
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 — qualquer falha: transcreve o original e diz que não filtrou
        log.warning("filtro de música falhou (%s): transcrevendo o áudio original", type(e).__name__)
        return str(path), {"version": VERSION, "filtered": False, "error": str(e) if isinstance(e, AppError)
                           else f"falha no filtro ({type(e).__name__})"}
    finally:
        release()


def _log(rep):
    """Diagnóstico sem conteúdo da aula: só confianças e durações."""
    log.info("filtro de música: musicDetected=%s musicConfidence=%s speechConfidence=%s separationConfidence=%s "
             "sourceSeparationUsed=%s removido=%ss separado=%ss incerto=%ss locutores=%s speakerSimilarity=%s "
             "professor=%ss outraVoz=%ss modo=%s tempo=%ss (%s)",
             rep["music_detected"], rep["music_confidence"], rep["speech_confidence"], rep["separation_confidence"],
             rep["separated"], rep["removed_s"], rep["separated_s"], rep["doubt_s"], rep.get("speakers"),
             rep.get("speaker_similarity"), rep.get("teacher_s"), rep.get("other_voice_s"), rep.get("mode"),
             rep.get("seconds"), rep.get("device", "CPU"))
