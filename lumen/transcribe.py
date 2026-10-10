"""Transcrição local: Whisper (faster-whisper/CTranslate2) na GPU NVIDIA ou CPU; Parakeet (ONNX) na CPU.

Modelos por modo e hardware escolhidos pelo benchmark em bench/RESULTADOS.md."""
import ctypes
import difflib
import re
import glob
import os
import time
from contextlib import contextmanager

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

try:  # DLLs CUDA opcionais instaladas via pip (requirements-gpu.txt)
    import nvidia
    for _d in (d for p in nvidia.__path__ for d in glob.glob(os.path.join(p, "*", "bin"))):
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(_d)
        os.environ["PATH"] = _d + os.pathsep + os.environ["PATH"]
except ImportError:
    pass

import ctranslate2  # noqa: E402
from faster_whisper import WhisperModel, download_model  # noqa: E402

from . import AppError, audio  # noqa: E402

PARAKEET = "parakeet-tdt-0.6b-v3"
ONNX_REPOS = {PARAKEET: "istupakov/parakeet-tdt-0.6b-v3-onnx", "silero": "istupakov/silero-vad-onnx"}
SIZES = {"small": "≈ 480 MB", "large-v3-turbo": "≈ 1,6 GB", "large-v3": "≈ 3,1 GB", PARAKEET: "≈ 640 MB"}
LABELS = {"rapido": "Rápido", "equilibrado": "Equilibrado", "maximo": "Maior precisão"}
BY_HARDWARE = {  # (com GPU, sem GPU)
    "rapido": ("small", PARAKEET),
    "equilibrado": ("large-v3-turbo", PARAKEET),
    "maximo": ("large-v3", "large-v3-turbo"),
}
_gpu = None
_loaded = {}


def has_gpu():
    global _gpu
    if _gpu is None:
        try:
            _gpu = ctranslate2.get_cuda_device_count() > 0
            if _gpu and os.name == "nt":
                ctypes.WinDLL("cublas64_12.dll")
                ctypes.WinDLL("cudnn64_9.dll")
        except Exception:
            _gpu = False
    return _gpu


# Pico de VRAM medido no benchmark (GB, float16) + folga; usado para não carregar modelo que não cabe.
VRAM_NEED_GB = {"small": 1.0, "large-v3-turbo": 2.6, "large-v3": 3.2}  # large-v3 int8_float16: pico 2,7 GB com o small (bench/fast)
# Com o modelo já carregado, a inferência ainda precisa desta memória de trabalho (medido: large-v3 0,74 GB,
# turbo e small 0,24 GB; aula de 6 min, RTX 3060) + folga.
WORK_GB = {"small": 0.5, "large-v3-turbo": 0.5, "large-v3": 1.0}


def gpu_free_gb():
    """VRAM livre agora (nvidia-smi). None se não for possível medir — aí vale a tentativa com recuo para CPU."""
    import subprocess
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return int(out.split()[0]) / 1024
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def _vram(name):
    """(VRAM livre, VRAM necessária) para transcrever com `name` agora.

    Já carregado na GPU: precisa só da memória de trabalho (WORK_GB). Medir como se fosse carregar de novo mandava
    o large-v3 para a CPU (339 s em vez de 26 s). Se nem isso houver, ou se o modelo não está carregado, os modelos
    do Lumen são descarregados e a medida vale para carregar o modelo inteiro (VRAM_NEED_GB)."""
    if (name, "cuda") in _loaded:
        free = gpu_free_gb()
        if free is None or free >= WORK_GB[name]:
            return free, WORK_GB[name]
    if _loaded:
        _loaded.clear()
        import gc
        gc.collect()
    return gpu_free_gb(), VRAM_NEED_GB[name]


def make_room(name, release):
    """Antes de transcrever: sem VRAM para o modelo, chama release() (descarrega o modelo de texto do Ollama, que o
    próprio Lumen deixou carregado) e espera a memória voltar. Nos logs reais, era o que mandava o large-v3 para o
    turbo ou para a CPU (“Pouca memória livre… 0,9 GB”)."""
    if not has_gpu() or name not in VRAM_NEED_GB:
        return
    free, need = _vram(name)
    if free is None or free >= need or not release():
        return
    for _ in range(20):
        free = gpu_free_gb()
        if free is None or free >= need:
            return
        time.sleep(0.25)


def fit_gpu(name):
    """Se o modelo não cabe na VRAM livre, troca por um que caiba (ou pelo Parakeet na CPU). Devolve (nome, aviso)."""
    if not has_gpu() or name not in VRAM_NEED_GB:
        return name, None
    free, need = _vram(name)
    if free is None or free >= need:
        return name, None
    for alt in ("large-v3-turbo", "small"):
        if VRAM_NEED_GB[alt] <= free and downloaded(alt):
            return alt, f"Pouca memória livre na placa de vídeo ({free:.1f} GB): usei {alt} em vez de {name}."
    alt = PARAKEET if downloaded(PARAKEET) else name
    return alt, f"Pouca memória livre na placa de vídeo ({free:.1f} GB): a transcrição foi feita na CPU."


def for_speed(name, speed):
    """Escolhe o modelo para fala acelerada (bench/ultra):
    2x: Parakeet e small reprovam (36% e 26%) → turbo. 4x: o turbo teve o menor erro de todos (53%) → turbo."""
    ultra = (f"4× Ultra é experimental: no teste com fala real acelerada 4×, o melhor modelo ainda errou cerca de "
             f"{ULTRA_WER:.0%} das palavras. Revise com atenção; se puder, use o arquivo em velocidade normal ou 2×.")
    if speed == 4:
        if downloaded("large-v3-turbo"):
            return "large-v3-turbo", ultra
        return name, ultra + " Baixe o modelo large-v3-turbo (modo Equilibrado com GPU ou Maior precisão sem GPU) para o melhor resultado."
    weak = speed == 2 and name in (PARAKEET, "small")
    if weak and downloaded("large-v3-turbo"):
        return "large-v3-turbo", None
    if weak:
        return name, ("O modelo deste modo erra bem mais em fala acelerada. Para melhorar, baixe o modo "
                      "“Maior precisão” em Ajustes e transcreva de novo.")
    return name, None


def models():
    """Modo → {name, size, label} para o hardware detectado."""
    k = 0 if has_gpu() else 1
    return {q: {"name": m[k], "size": SIZES[m[k]], "label": LABELS[q]} for q, m in BY_HARDWARE.items()}


def pick(quality):
    quality = quality if quality in BY_HARDWARE else "equilibrado"  # “auto”/“preciso” antigos = equilibrado
    return quality, models()[quality]


def _onnx_dir(key, local=True):
    from huggingface_hub import snapshot_download
    patterns = ["*.json", "*.txt", "*int8.onnx"] if key == PARAKEET else ["config.json", "silero_vad.onnx"]
    return snapshot_download(ONNX_REPOS[key], local_files_only=local, allow_patterns=patterns)


def downloaded(name):
    try:
        if name in ONNX_REPOS:
            _onnx_dir(name)
            _onnx_dir("silero")
        else:
            download_model(name, local_files_only=True)
        return True
    except Exception:
        return False


def download(name):
    try:
        if name in ONNX_REPOS:
            _onnx_dir(name, local=False)
            _onnx_dir("silero", local=False)
        else:
            download_model(name)
    except Exception as e:
        raise AppError("Não foi possível baixar o modelo de transcrição.",
                       "Verifique a internet e o espaço em disco e tente de novo.") from e


def speed_factor(name):
    """Vezes mais rápido que o tempo real (benchmark: RTX 3060 / i5-11400F), arredondado para baixo."""
    gpu = {"small": 25, "large-v3-turbo": 20, "large-v3": 14}   # medido: 29,7 / 23,5 / 14,6 (int8_float16)
    cpu = {"small": 4, "large-v3-turbo": 1.5, PARAKEET: 15}     # medido: 4,6 / 1,6 / 19,2
    return (gpu if has_gpu() and name in gpu else cpu).get(name, 1)


def _loaded_compute(name, device):
    m = _loaded.get((name, device))
    return getattr(getattr(m, "model", None), "compute_type", None) or COMPUTE.get((name, device)) or _compute(name, device)


def _model(name, device):
    if (name, device) not in _loaded:
        _loaded.clear()
        if name == PARAKEET:
            import onnx_asr
            import onnxruntime
            opts = onnxruntime.SessionOptions()
            opts.intra_op_num_threads = cpu_threads(PARAKEET)
            asr = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", _onnx_dir(PARAKEET), quantization="int8", sess_options=opts)
            _loaded[(name, device)] = asr.with_vad(onnx_asr.load_vad("silero", _onnx_dir("silero")), batch_size=1)
            return _loaded[(name, device)]
        ct = COMPUTE.get((name, device)) or _compute(name, device)
        _loaded[(name, device)] = WhisperModel(name, device=device, compute_type=ct,
                                               cpu_threads=cpu_threads(), local_files_only=True)
    return _loaded[(name, device)]


def _compute(name, device):
    if device != "cuda":
        return "int8"
    return "float16"


def cpu_threads(name=None):
    """Threads de CPU para a inferência (bench/ultra responsive, i5-11400F 6c/12t):
    Parakeet (onnxruntime) ficou MAIS rápido e o PC mais leve com 1/3 dos núcleos lógicos (12 thr: 18,7 s e outro
    programa 2,9× mais lento; 4 thr: 9,5 s e 1,4×). Whisper na CPU: todos os núcleos foi o mais rápido dentro do
    limite de responsividade (1,8×)."""
    n = os.cpu_count() or 4
    if name == PARAKEET:
        return max(2, n // 3)
    return max(1, n - CPU_RESERVE)


# Valores calibrados no benchmark (bench/RESULTADOS.md). Não são probabilidades.
FAST_WPS = 2.9            # palavras/s (janela de 120 s): acima, a fala parece acelerada (bench rate/rate4)
AUTO_MARGIN = 0.6         # perto do limite a detecção é só sugestão: a revisão pede confirmação
LOW_WPS = 1.2             # abaixo disto (fala normal medida: ≥ 1,48) o modelo “não entendeu” o áudio: no teste,
                          # é o que acontece com fala 4× (0,06–0,9). Aí o app pede para você escolher a velocidade.
# Preparação do áudio acelerado, por (modelo, velocidade): fator do atempo (preserva o tom) antes do modelo.
# 1.0 = transcrever direto. Medido em bench/app_check (ver bench/RESULTADOS.md).
PREP = {("large-v3-turbo", 2): 0.5, ("large-v3-turbo", 4): 0.5}
SPEED_OPTIONS = {4: {"condition_on_previous_text": False}}  # 4x: evita repetições em cadeia (53,2% x 54,6%)
ULTRA_WER = 0.53  # melhor erro medido em fala 4x (bench/ultra): o modo é experimental
# (modelo, dispositivo) → tipo numérico. bench/fast (10/10/2026): large-v3 em int8_float16 teve a mesma precisão
# que float32 nas 200 falas (10,6% x 10,6%), a melhor na aula longa (11,3% x 12,1%; timestamps 0,23 s x 0,87 s),
# 1,7× a velocidade e metade da VRAM. A regra antiga (float32, critério 14) se apoiava em 0,57 ponto num só áudio.
COMPUTE = {("large-v3", "cuda"): "int8_float16"}
CPU_RESERVE = 0    # núcleos lógicos deixados livres durante a inferência na CPU
LOW_PRIORITY = False  # prioridade “abaixo do normal” do processo enquanto transcreve (não mexe em clock/energia)


@contextmanager
def _background_priority():
    """No Windows, baixa a prioridade do processo durante a transcrição e restaura depois."""
    if not (LOW_PRIORITY and os.name == "nt"):
        yield
        return
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.GetPriorityClass.argtypes = [ctypes.c_void_p]
    h = k32.GetCurrentProcess()
    old = k32.GetPriorityClass(h) or 0x20  # NORMAL_PRIORITY_CLASS
    k32.SetPriorityClass(h, 0x4000)       # BELOW_NORMAL_PRIORITY_CLASS
    try:
        yield
    finally:
        k32.SetPriorityClass(h, old)
UNCERTAIN_LOGPROB = -1.0  # trecho marcado como incerto abaixo deste avg_logprob
DIVERGENCE = 0.2          # segundo ouvinte (small): acima disto marca para revisão; regra do adendo em bench/CRITERIOS.md
# Auditoria (bench variants): condition_on_previous_text=True foi melhor na aula longa (11,5% x 12,8%);
# sem VAD apareceu texto em trecho sem fala; hotwords quebraram os timestamps (erro mediano 15 s) e não são usados.
OPTIONS = dict(beam_size=5, vad_filter=True, condition_on_previous_text=True)


def _segments(model, samples, check, opts=None):
    if not hasattr(model, "transcribe"):  # Parakeet (onnx-asr + VAD): sem confiança por trecho
        for r in model.recognize(samples, sample_rate=audio.SR):
            check()
            yield _OnnxSeg(r.start, r.end, r.text), _OnnxInfo
        return
    it, info = model.transcribe(samples, **{**OPTIONS, **(opts or {})})
    for s in it:
        check()
        yield s, info


def split_words(segments, max_s=12.0, gap=0.8):
    """Em lote, o Whisper devolve trechos de até 30 s (timestamps grosseiros, bench/RESULTADOS.md). Com o tempo de
    cada palavra, corta de novo em frases: fim de frase, pausa > gap ou trecho > max_s. Confiança = média do log da
    probabilidade das palavras (mesma escala do avg_logprob por token, usada para marcar “incerto”)."""
    import math
    from types import SimpleNamespace
    out = []
    for s in segments:
        words = [w for w in (s.words or []) if w.word.strip()]
        if not words:
            out.append(SimpleNamespace(start=s.start, end=s.end, text=s.text, avg_logprob=s.avg_logprob))
            continue
        cur = []
        for i, w in enumerate(words):
            cur.append(w)
            nxt = words[i + 1] if i + 1 < len(words) else None
            sentence = w.word.strip()[-1] in ".?!" and w.end - cur[0].start >= 2
            if nxt is None or sentence or nxt.start - w.end > gap or nxt.end - cur[0].start > max_s:
                lp = sum(math.log(max(x.probability, 1e-6)) for x in cur) / len(cur)
                out.append(SimpleNamespace(start=cur[0].start, end=cur[-1].end, avg_logprob=lp,
                                           text="".join(x.word for x in cur)))
                cur = []
    return out


class _OnnxSeg:
    avg_logprob = 0.0  # o Parakeet não fornece confiança calibrada; não marca “incerto”

    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class _OnnxInfo:
    language = None


def _words(text):
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def disagreement(a, b):
    """1 − semelhança entre as palavras de duas transcrições do mesmo trecho (0 = idênticas)."""
    wa, wb = _words(a), _words(b)
    if not wa and not wb:
        return 0.0
    return 1 - difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()


def second_opinion(samples, scale, segs, main_name, check):
    """Na GPU, transcreve de novo com outro modelo e marca trechos em que os dois discordam.

    Só marca para revisão e guarda a alternativa; nunca troca o texto. Sem GPU ou sem o outro modelo: não faz nada."""
    other = "small" if main_name != "small" else "large-v3-turbo"
    if not has_gpu() or not downloaded(other):
        return False
    free = gpu_free_gb()
    if free is not None and free < VRAM_NEED_GB[other]:  # sem VRAM para o segundo modelo: segue sem conferir
        return False
    model = WhisperModel(other, device="cuda", compute_type="float16", local_files_only=True)
    words = []
    it, _ = model.transcribe(samples, word_timestamps=True, **OPTIONS)
    for s in it:
        check()
        words += [((w.start + w.end) / 2 / scale, w.word) for w in s.words or []]
    del model
    for seg in segs:
        alt = "".join(w for t, w in words if seg["start"] <= t < seg["end"]).strip()
        if disagreement(seg["text"], alt) > DIVERGENCE:
            seg["diverges"], seg["alt"] = True, alt
    return True


def suggest_speed(wps):
    """(velocidade sugerida, incerto?, aviso). 2× e 4× não se separam com segurança (bench rate4): nunca afirma 4×."""
    if wps is None or wps < LOW_WPS:
        return 1.0, True, ("Quase nada foi reconhecido nos primeiros minutos. Isso acontece com fala muito acelerada "
                           "(4×) ou com áudio sem fala. Se o conteúdo estiver acelerado, escolha 2× ou 4× abaixo.")
    if wps >= FAST_WPS:
        return 2.0, True, "A fala parece acelerada; pode ser 2× ou 4×. Confirme abaixo."
    return 1.0, abs(wps - FAST_WPS) < AUTO_MARGIN, None


def speech_rate(path, name, check, seconds=120):
    """Palavras por segundo de fala nos primeiros minutos (estimativa para o modo Automático)."""
    x = audio.load(path)[:audio.SR * seconds]
    device = "cuda" if has_gpu() and name != PARAKEET else "cpu"
    words = speech = 0.0
    try:
        for s, _ in _segments(_model(name, device), x, check):
            words += len(s.text.split())
            speech += max(s.end - s.start, 0.0)
    except RuntimeError:
        return None
    return words / speech if speech >= 5 else None


def transcribe(path, name, progress, check, speed=1.0, second=True, release=None):
    """Devolve {segments, language, duration, device, prep}; tempos sempre na linha do tempo do arquivo.

    speed (1, 2 ou 4) é a velocidade real do conteúdo do arquivo, não a do player. Se PREP pedir, o áudio é
    desacelerado pelo fator f (atempo, sem mudar o tom) e cada tempo volta ao arquivo como t × f.
    `check()` levanta Cancelled. `release()` libera VRAM de outros programas (Ollama) se a GPU encher no meio."""
    if not downloaded(name):
        raise AppError("O modelo de transcrição ainda não foi baixado.", "Abra Configurações e baixe o modelo.")
    samples = audio.load(path)
    duration = len(samples) / audio.SR
    factor = PREP.get((name, int(speed)), 1.0)
    if factor != 1.0:
        samples = audio.tempo(samples, factor)
    scale = 1.0 / factor  # t_arquivo = t_processado / scale
    with _background_priority():
        # 4x: o small erra ~100% (bench/ultra); a conferência só marcaria tudo, então não roda
        return _run(samples, name, progress, check, duration, factor, scale, second and int(speed) != 4,
                    SPEED_OPTIONS.get(int(speed)), release)


def _run(samples, name, progress, check, duration, factor, scale, second, opts=None, release=None):
    devices = ["cuda", "cpu"] if has_gpu() and name != PARAKEET else ["cpu"]
    if devices[0] == "cuda" and name in VRAM_NEED_GB:
        free, need = _vram(name)
        if free is not None and free < need:
            devices = ["cpu"]  # não tenta a GPU sem memória; make_room()/fit_gpu() já deveriam ter evitado isso
    if devices[0] == "cuda" and release:
        devices.insert(1, "cuda")  # GPU encheu no meio: libera o Ollama e continua na GPU antes de ir para a CPU
    # Nova tentativa recomeça do início do áudio. Retomar do meio (bench/RESULTADOS.md, “Retomada”) perdia 3 a 15
    # palavras na emenda e, com o texto anterior como contexto, numa falha o Whisper repetiu 165 palavras.
    # Do início, na GPU, o resultado é igual ao de uma transcrição sem falha; o custo é refazer o trecho já feito.
    info, total, model = None, len(samples) / audio.SR, None
    for i, device in enumerate(devices):
        if i:  # nova tentativa: o modelo que falhou sai da VRAM ANTES de carregar o substituto (medido na RTX 3060:
            model = None  # sem isto, ~2 GB do large-v3 continuavam presos e os dois precisavam caber juntos)
            _loaded.clear()
            import gc
            gc.collect()  # o traceback da falha e o gerador do Whisper podem formar ciclos que seguram o modelo
        segs = []
        try:
            model = _model(name, device)
            t0 = time.monotonic()
            for s, info in _segments(model, samples, check, opts):
                segs.append({"start": round(s.start / scale, 2), "end": round(s.end / scale, 2), "text": s.text.strip(),
                             "uncertain": s.avg_logprob < UNCERTAIN_LOGPROB})
                done = s.end / total if total else None
                eta = (time.monotonic() - t0) / done * (1 - done) if done and done > 0.02 else None
                progress(done, eta)
            segs = [s for s in segs if s["text"]]
            for s in segs:  # o Whisper às vezes estima fim além do áudio; nenhum tempo passa da duração do arquivo
                s["start"], s["end"] = min(s["start"], round(duration, 2)), min(s["end"], round(duration, 2))
            checked = False
            if device == "cuda" and second:
                progress(None, None)
                try:
                    checked = second_opinion(samples, scale, segs, name, check)
                except RuntimeError:  # VRAM cheia: segue sem a conferência
                    checked = False
            return {"segments": segs, "language": info.language if info else None, "duration": duration,
                    "device": device, "second_opinion": checked, "prep": factor,
                    "compute": "int8 (ONNX)" if name == PARAKEET else _loaded_compute(name, device)}
        except MemoryError:
            raise AppError("Memória insuficiente para transcrever.",
                           "Feche outros programas ou escolha a qualidade “Rápido” em Configurações.") from None
        except RuntimeError as e:
            # Falha de CUDA (DLL ausente, VRAM cheia): libera memória e transcreve de novo (GPU, depois CPU).
            if device == "cuda" and i + 1 < len(devices):
                if devices[i + 1] == "cuda" and not release():
                    devices[i + 1] = "cpu"  # nada a liberar: tentar a GPU de novo daria o mesmo erro
                continue
            if "out of memory" in str(e).lower():
                raise AppError("Memória insuficiente para transcrever.",
                               "Escolha a qualidade “Rápido” em Configurações.") from None
            raise
