"""Fase 6, parte 3: medições da Conversa por voz em tempo real nos Estudos.

Roda com `LUMEN_DATA` temporário no D:, o Ollama já aberto do estudante e o backend do Voice Studio na porta 3900
(sem subir um segundo backend se a porta já responder, sem chamar rotas de escrita e com saída WASAPI em ganho zero
para não tocar áudio alto nas caixas de som durante o teste):

    .venv\\Scripts\\python bench/call_bench.py asr        # Parakeet CPU int8 × Whisper turbo (GPU) × Whisper small
    .venv\\Scripts\\python bench/call_bench.py playback   # Python (soundcard WASAPI) × navegador (HTTP base64 + WebAudio)
    .venv\\Scripts\\python bench/call_bench.py echo       # Fone × caixa sem filtro × barreira × pyaec + barreira (20 rodadas)
    .venv\\Scripts\\python bench/call_bench.py ablation   # Silêncio (450/700/1100 ms), resposta antecipada e 1º pedaço (8/12/16p)
    .venv\\Scripts\\python bench/call_bench.py soak       # >= 20 turnos quentes + 10 min contínuos (VRAM e RAM a cada 30 s)
    .venv\\Scripts\\python bench/call_bench.py all        # Executa tudo e grava D:\\Lumen\\voz\\amostras-chamada\\call_bench.json
"""
import atexit
import base64
import ctypes
from ctypes import wintypes
import gc
import http.server
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import wave
from pathlib import Path

# Cada execução usa um diretório PRÓPRIO e novo (nunca apaga o de outra execução nem resíduos herdados) e só remove, ao
# terminar, o que ela mesma criou. Resultado em D:/Lumen/voz-conversa-20261108/bench/<execucao>/ (LUMEN_BENCH_OUT muda).
RUN_ID = os.environ.get("LUMEN_BENCH_RUN") or f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
BENCH_TMP = Path(os.environ.get("LUMEN_BENCH_TMP") or rf"D:\Lumen\cache\lumen-call-bench-{RUN_ID}")
if BENCH_TMP.exists():
    raise SystemExit(f"O diretório {BENCH_TMP} já existe: nada foi apagado. Use outro LUMEN_BENCH_RUN.")
(BENCH_TMP / "tmp").mkdir(parents=True, exist_ok=True)
(BENCH_TMP / "data").mkdir(parents=True, exist_ok=True)

os.environ["TMP"] = str(BENCH_TMP / "tmp")
os.environ["TEMP"] = str(BENCH_TMP / "tmp")
os.environ["LUMEN_DATA"] = str(BENCH_TMP / "data")


def _cleanup_bench_tmp():
    shutil.rmtree(BENCH_TMP, ignore_errors=True)


atexit.register(_cleanup_bench_tmp)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from lumen import loopback, store, transcribe, voice, voicestudio  # noqa: E402
from lumen.study import call, db, index, listen, providers, settings  # noqa: E402

store.get_token = lambda: ""
settings.api_key = lambda: ""

SAMPLES_DIR = Path(r"D:\Lumen\voz\amostras-chamada")
OUT_JSON = Path(os.environ.get("LUMEN_BENCH_OUT") or f"D:/Lumen/voz-conversa-20261108/bench/{RUN_ID}/call_bench.json")

SAMPLES = [
    ("01_sono", "Me explica em poucas palavras como funciona a consolidação da memória durante o sono profundo."),
    ("02_memoria", "Qual é a diferença entre memória de trabalho e memória de longo prazo no cérebro?"),
    ("03_mapa", "Cria um mapa mental sobre fotossíntese e respiração celular."),
    ("04_quiz", "Me faz um quiz rápido sobre keyframes e interpolação no Premiere."),
    ("05_diagrama", "Explica com um diagrama o ciclo cardíaco entre sístole e diástole."),
    ("06_flashcards", "Cria flashcards sobre as leis de Newton para eu revisar hoje."),
    ("07_plano", "Monta um plano de estudo de três dias para revisar biologia celular."),
    ("08_feynman", "Vou te explicar o que entendi: o hipocampo organiza as memórias novas durante o sono."),
    ("09_erros", "O que eu mais errei nos meus estudos até agora?"),
    ("10_comando", "Fala mais devagar, por favor."),
]

# Conversa contínua natural para medir latência de resposta falada (perguntas diretas que passam por ASR -> LLM -> TTS)
CHAT_TURNS = [
    "01_sono",
    "02_memoria",
    "01_sono",
    "02_memoria",
]


# --- Leitura de VRAM e RAM no Windows sem dependências extras --------------------------------------------------------

class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def mem_snapshot():
    """Retorna VRAM usada/livre (MB via nvidia-smi), RSS deste processo Python (MB) e RAM livre do Windows (MB)."""
    vram_used, vram_free = 0, 0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if out:
            u, f = out.splitlines()[0].split(",")
            vram_used, vram_free = int(u.strip()), int(f.strip())
    except Exception:  # noqa: BLE001
        pass

    rss_mb = 0.0
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        pmc = _PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            rss_mb = round(pmc.WorkingSetSize / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass

    ram_free_mb, ram_used_mb = 0.0, 0.0
    try:
        ms = _MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(ms)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            ram_free_mb = round(ms.ullAvailPhys / (1024 * 1024), 1)
            ram_used_mb = round((ms.ullTotalPhys - ms.ullAvailPhys) / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass

    return {
        "vram_used_mb": vram_used,
        "vram_free_mb": vram_free,
        "proc_rss_mb": rss_mb,
        "sys_ram_used_mb": ram_used_mb,
        "sys_ram_free_mb": ram_free_mb,
    }


def pct_stats(values):
    arr = [float(v) for v in values if v is not None]
    if not arr:
        return {"n": 0, "p50": None, "p90": None, "min": None, "max": None, "mean": None}
    a = np.asarray(arr, dtype=np.float64)
    return {
        "n": len(arr),
        "p50": round(float(np.percentile(a, 50)), 1),
        "p90": round(float(np.percentile(a, 90)), 1),
        "min": round(float(np.min(a)), 1),
        "max": round(float(np.max(a)), 1),
        "mean": round(float(np.mean(a)), 1),
    }


def load_wav_16k(path):
    """Lê um WAV de teste e converte para mono 16 kHz float32 (exatamente o formato que `Mic` entrega ao `CallManager`)."""
    a, sr = voice.read_wav(path)
    a = np.asarray(a, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if sr != 16000 and a.size > 1:
        n16 = int(round(a.size * 16000 / sr))
        a = np.interp(np.linspace(0, a.size - 1, n16, dtype=np.float32),
                      np.arange(a.size, dtype=np.float32), a).astype(np.float32)
    # Remove silêncio final já embutido no WAV para medir `last_speech_at` com precisão no fim real da voz
    abs_a = np.abs(a)
    nz = np.where(abs_a > 0.008)[0]
    if nz.size:
        end = min(a.size, int(nz[-1]) + int(0.04 * 16000))
        start = max(0, int(nz[0]) - int(0.06 * 16000))
        a = a[start:end]
    return a


class ZeroGainWASAPISpeaker:
    """Abre o `loopback.speaker` WASAPI real (medindo latência real do driver de áudio do Windows), mas envia zeros ao
    hardware para não tocar 40 respostas altas na caixa de som do estudante. Permite `fast_drain` após o 1º quadro."""

    def __init__(self, fast_after_first_s=None):
        self._real = loopback.speaker(call.PLAY_SR, 1, buffer_ms=80)
        self._fast_after = fast_after_first_s
        self._started = None

    def __enter__(self):
        self._real.__enter__()
        self._started = None
        return self

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)

    def play(self, data):
        a = np.asarray(data, dtype=np.float32)
        if self._started is None:
            self._started = time.monotonic()
        if self._fast_after is not None and (time.monotonic() - self._started) >= self._fast_after:
            # Depois que o 1º trecho já tocou pelo WASAPI real, drena o restante rápido quando pedido (só em ablações curtas)
            return
        self._real.play(np.zeros_like(a))

    def flush(self):
        if hasattr(self._real, "flush"):
            self._real.flush()


class FeedMic:
    """Microfone contínuo simulado em tempo real (quadros exatos de 32 ms / 512 amostras em 16 kHz)."""

    def __init__(self):
        self._cb = None
        self._running = False
        self._preroll = np.zeros(0, dtype=np.float32)
        self._q = queue.Queue()
        self._thread = None

    def start_continuous(self, on_frame, mic_id="", open_mic=None):
        self._cb = on_frame
        self._running = True
        self._preroll = np.zeros(int(16000 * 0.32), dtype=np.float32)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Bench feed mic")
        self._thread.start()

    def _loop(self):
        next_t = time.monotonic()
        silence = np.zeros(512, dtype=np.float32)
        while self._running:
            try:
                frame = self._q.get_nowait()
            except queue.Empty:
                frame = silence
            self._preroll = np.concatenate((self._preroll, frame))[-5120:]
            lvl = float(np.sqrt(np.mean(frame * frame)))
            if self._cb:
                self._cb(frame, lvl)
            next_t += 0.032
            rem = next_t - time.monotonic()
            if rem > 0:
                time.sleep(rem)
            elif rem < -0.2:
                next_t = time.monotonic()

    def preroll_audio(self):
        return self._preroll.copy()

    def feed_audio(self, audio_16k):
        a = np.asarray(audio_16k, dtype=np.float32).reshape(-1)
        pad = (-a.size) % 512
        if pad:
            a = np.concatenate((a, np.zeros(pad, dtype=np.float32)))
        for i in range(0, a.size, 512):
            self._q.put(a[i:i + 512])
        return a.size / 16000.0

    def pending_seconds(self):
        return self._q.qsize() * 0.032

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


COLD = {}


def setup_temp_vault_and_services():
    """Prepara cofre temporário de estudo no `LUMEN_DATA` e garante Voice Studio + Ollama quentes sem subir duplicata."""
    vault = BENCH_TMP / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "Memoria_e_Sono.md").write_text(
        "# Memória e sono\n\nO sono profundo (ondas lentas NREM) consolida a memória declarativa transferindo traços do "
        "hipocampo para o neocórtex. Já a memória de trabalho mantém poucos itens ativos por segundos no córtex pré-frontal.",
        encoding="utf-8",
    )
    (vault / "Biologia_Celular.md").write_text(
        "# Fotossíntese e respiração celular\n\nNos cloroplastos, a fase clara produz ATP e NADPH e o ciclo de Calvin fixa CO2. "
        "Nas mitocôndrias, glicólise, ciclo de Krebs e cadeia respiratória regeneram ATP.\n\n"
        "# Ciclo cardíaco\n\nNa sístole ventricular os ventrículos ejetam sangue; na diástole relaxam e enchem.",
        encoding="utf-8",
    )
    (vault / "Premiere_e_Fisica.md").write_text(
        "# Keyframes no Premiere\n\nKeyframes marcam valores no painel Effect Controls; Ease In e Ease Out suavizam a velocidade.\n\n"
        "# Leis de Newton\n\n1ª lei: inércia. 2ª lei: F = m·a. 3ª lei: ação e reação.",
        encoding="utf-8",
    )
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    cfg = store.load_config()
    cfg["obsidian_vault"] = str(vault)
    store.save_config(cfg)
    settings.save({
        "connectors": {"obsidian": True},
        "voice": {
            "engine": "voicestudio",
            "fallback": "off",
            "voice_id": "1faf41ee",
            "language": "pt",
            "call_quality": "balanced",
            "call_silence": "normal",
            "call_early": True,
            "call_earcon": True,
            "call_captions": True,
            "call_length": "short",
            "call_effort": "auto",
            "call_asr": "auto",
        },
    })
    index.sync("obsidian")

    h_state, _ = voicestudio.health()
    started_by_bench = False
    COLD["voicestudio_was"] = h_state
    t0 = time.monotonic()
    if h_state == "closed":
        voicestudio.BACKEND.ensure()
        started_by_bench = True
    COLD["voicestudio_backend_s"] = round(time.monotonic() - t0, 2)

    # Aquece Voice Studio, Ollama (qwen3.5:4b em 32k) e Parakeet CPU int8 antes de iniciar as contagens quentes.
    # Cada etapa guarda o seu tempo FRIO (1ª vez neste processo; o Ollama estava sem modelo carregado, se `ollama ps` vazio).
    s_voice = settings.load()["voice"]
    t0 = time.monotonic()
    for _ in listen._prepare(s_voice, lambda: None):
        pass
    COLD["voicestudio_model_s"] = round(time.monotonic() - t0, 2)
    t0 = time.monotonic()
    providers.warm_local(keep_alive="30m")
    COLD["llm_load_s"] = round(time.monotonic() - t0, 2)
    t0 = time.monotonic()
    call._load_call_asr("parakeet")
    COLD["parakeet_load_s"] = round(time.monotonic() - t0, 2)
    t0 = time.monotonic()
    call.load_vad()
    COLD["vad_load_s"] = round(time.monotonic() - t0, 3)
    dummy = np.zeros(16000, dtype=np.float32)
    dummy[1000:6000] = 0.05 * np.sin(2 * np.pi * 220 * np.arange(5000, dtype=np.float32) / 16000.0)
    t0 = time.monotonic()
    call.transcribe_call_audio(dummy, "parakeet")
    COLD["parakeet_first_run_ms"] = round((time.monotonic() - t0) * 1000, 1)
    # Um pedido curto de aquecimento ao Voice Studio para garantir modelo na GPU
    w = listen.who("call", s_voice, start=False)
    t0 = time.monotonic()
    listen.synth_sentence("Pronto.", w, {**s_voice, "cache_mb": 0}, 12, 1, lambda: None)
    COLD["tts_first_sentence_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return started_by_bench


# --- 1. Comparação de ASR (Parakeet CPU int8 × Whisper turbo GPU × Whisper small) ------------------------------------

def bench_asr():
    print("[1/5] Medindo transcrição (Parakeet CPU int8 × Whisper turbo GPU × Whisper small)...", flush=True)
    loaded_samples = [(slug, ref, load_wav_16k(SAMPLES_DIR / f"{slug}.wav")) for slug, ref in SAMPLES]
    out = {}

    # A. Parakeet TDT 0.6b v3 ONNX int8 na CPU (20 falas = 10 amostras × 2)
    p_times, p_wers, p_5s = [], [], []
    for _round in range(2):
        for slug, ref, audio in loaded_samples:
            txt, ms, _ = call.transcribe_call_audio(audio, "parakeet")
            p_times.append(ms)
            if slug == "02_memoria":
                p_5s.append(ms)
            rw, hw = voice.words(ref), voice.words(txt)
            p_wers.append(voice._wer(rw, hw))
    out["parakeet_cpu_int8"] = {
        **pct_stats(p_times),
        "sample_5s4_ms": pct_stats(p_5s)["p50"],
        "wer": round(float(np.mean(p_wers)), 4),
        "mem": mem_snapshot(),
    }

    # Mede também se a legenda parcial em paralelo atrasa a transcrição final no Parakeet
    cont_times = []
    for slug, _ref, audio in loaded_samples:
        tail = audio[:int(16000 * 3.0)]
        t_part = threading.Thread(target=lambda: call.transcribe_call_audio(tail, "parakeet"), daemon=True)
        t_part.start()
        time.sleep(0.08)
        _, ms, _ = call.transcribe_call_audio(audio, "parakeet")
        t_part.join()
        cont_times.append(ms)
    out["parakeet_with_inflight_partial"] = pct_stats(cont_times)

    # B. Whisper small (CPU int8 e GPU float16) + Whisper large-v3-turbo (GPU float16)
    from faster_whisper import WhisperModel

    for label, model_name, device, ctype in [
        ("whisper_small_cpu_int8", "small", "cpu", "int8"),
        ("whisper_small_gpu_fp16", "small", "cuda", "float16"),
        ("whisper_turbo_gpu_fp16", "large-v3-turbo", "cuda", "float16"),
    ]:
        if not transcribe.downloaded(model_name):
            out[label] = {"skipped": "modelo não baixado"}
            continue
        if device == "cuda":
            free_gb = transcribe.gpu_free_gb() or 0.0
            need_gb = 2.2 if "turbo" in model_name else 0.9
            if free_gb < need_gb:
                out[label] = {"skipped": f"VRAM livre insuficiente ({free_gb:.2f} GB < {need_gb} GB)"}
                continue
        wm = WhisperModel(model_name, device=device, compute_type=ctype,
                          cpu_threads=transcribe.cpu_threads(), local_files_only=True)
        try:
            # Aquecimento
            list(wm.transcribe(loaded_samples[0][2], language="pt", beam_size=1, vad_filter=False,
                               condition_on_previous_text=False)[0])
            mem_loaded = mem_snapshot()
            w_times, w_wers, w_5s = [], [], []
            for _round in range(2):
                for slug, ref, audio in loaded_samples:
                    t0 = time.perf_counter()
                    segs, _ = wm.transcribe(audio, language="pt", beam_size=1, vad_filter=False,
                                            condition_on_previous_text=False)
                    hyp = " ".join(s.text.strip() for s in segs if s.text.strip())
                    ms = (time.perf_counter() - t0) * 1000.0
                    w_times.append(ms)
                    if slug == "02_memoria":
                        w_5s.append(ms)
                    w_wers.append(voice._wer(voice.words(ref), voice.words(hyp)))
            out[label] = {
                **pct_stats(w_times),
                "sample_5s4_ms": pct_stats(w_5s)["p50"],
                "wer": round(float(np.mean(w_wers)), 4),
                "mem_loaded": mem_loaded,
            }
        finally:
            del wm
            gc.collect()

    print("  ASR:", json.dumps({k: {"p50": v.get("p50"), "p90": v.get("p90"), "wer": v.get("wer")} for k, v in out.items()}, ensure_ascii=False), flush=True)
    return out


# --- 2. Tocar no Python (`soundcard` WASAPI) × Tocar no navegador (HTTP NDJSON base64 + decode WAV) -------------------

def bench_playback():
    print("[2/5] Medindo reprodução: Python WASAPI × navegador (HTTP loopback base64 + WAV)...", flush=True)
    s_voice = settings.load()["voice"]
    w = listen.who("call", s_voice, start=False)
    wav_bytes, secs, _ = listen.synth_sentence("O sono profundo consolida a memória no córtex.", w,
                                               {**s_voice, "cache_mb": 0}, 12, 1, lambda: None)

    # A. Python WASAPI: converter WAV -> float32 24 kHz + abrir/enviar 1º bloco de 20 ms ao WASAPI + latência de parada
    py_start_ms, py_stop_ms = [], []
    for _ in range(20):
        t0 = time.perf_counter()
        samples = call.wav_to_float24k(wav_bytes)
        with ZeroGainWASAPISpeaker() as sp:
            sp.play(samples[:call.PLAY_CHUNK])
            py_start_ms.append((time.perf_counter() - t0) * 1000.0)
            # Mede a interrupção com descida suave de 50 ms + flush WASAPI
            t_cut = time.perf_counter()
            rem = samples[call.PLAY_CHUNK:call.PLAY_CHUNK + call.FADE_SAMPLES]
            env = np.linspace(1.0, 0.0, rem.size, dtype=np.float32)
            sp.play(rem * env)
            sp.flush()
            py_stop_ms.append((time.perf_counter() - t_cut) * 1000.0)

    # B. Caminho navegador (como `/api/study/voice/say`): codificar base64 + NDJSON por HTTP loopback + ler + decodificar WAV
    payload_holder = [wav_bytes]

    class _SayHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            line = json.dumps({"type": "audio", "audio": base64.b64encode(payload_holder[0]).decode("ascii")}) + "\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SayHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/say"
    web_start_ms = []
    try:
        # Mede a entrega HTTP NDJSON base64 + parse JSON + decodificação WAV PCM + abertura do dispositivo de saída
        for _ in range(20):
            t0 = time.perf_counter()
            with urllib.request.urlopen(url, timeout=5) as r:
                raw_line = r.readline()
            ev = json.loads(raw_line)
            decoded_wav = base64.b64decode(ev["audio"])
            samples = call.wav_to_float24k(decoded_wav)
            with ZeroGainWASAPISpeaker() as sp:
                sp.play(samples[:call.PLAY_CHUNK])
                web_start_ms.append((time.perf_counter() - t0) * 1000.0)
    finally:
        httpd.shutdown()
        httpd.server_close()

    res = {
        "python_wasapi": {
            "first_audio_ms": pct_stats(py_start_ms),
            "interrupt_fade_flush_ms": pct_stats(py_stop_ms),
            "echo_reference": "exata no mesmo processo (quadros de 20 ms -> EchoGuard)",
            "works_minimized": True,
        },
        "browser_http_base64": {
            "first_audio_ms": pct_stats(web_start_ms),
            "extra_payload_pct": round(len(base64.b64encode(wav_bytes)) / max(1, len(wav_bytes)) * 100 - 100, 1),
            "echo_reference": "indisponível no Python sem loopback extra",
            "works_minimized": "sujeito a throttling de aba oculta / WebAudio suspenso",
        },
    }
    print("  Playback:", json.dumps({
        "python_p50_ms": res["python_wasapi"]["first_audio_ms"]["p50"],
        "browser_p50_ms": res["browser_http_base64"]["first_audio_ms"]["p50"],
        "interrupt_p50_ms": res["python_wasapi"]["interrupt_fade_flush_ms"]["p50"],
    }), flush=True)
    return res


# --- 3. Eco e interrupção pela voz (4.4: fone × caixa sem filtro × barreira × pyaec + barreira) ----------------------

def bench_echo():
    print("[3/5] Medindo cancelamento de eco e falsos disparos em 20 turnos...", flush=True)
    vad = call.load_vad()
    # Fala do Lúmen (voz do Jhonny em 01_sono) voltando pela caixa de som (acoplamento de 0,28) vs estudante falando por cima (02_memoria)
    tts_ref_16k = load_wav_16k(SAMPLES_DIR / "01_sono.wav")
    user_barge_16k = load_wav_16k(SAMPLES_DIR / "02_memoria.wav")
    rng = np.random.default_rng(42)

    def eval_mode(mode_name):
        false_triggers = 0
        true_barge = 0
        for trial in range(20):
            vad.reset()
            eg = call.EchoGuard()
            if mode_name == "barrier_only":
                eg.aec = None
            coupling = 0.22 + 0.08 * (trial % 3)  # acoplamentos acústicos variados de mesa (22% a 38%)
            # 1) Só eco da caixa de som + ruído ambiente leve (~2,5 s = 78 quadros)
            n_frames = min(78, tts_ref_16k.size // 512)
            barge_streak = 0
            triggered = False
            for i in range(n_frames):
                ref = tts_ref_16k[i * 512:(i + 1) * 512]
                # Alimenta o alto-falante em 24 kHz como na chamada real
                ref24 = np.interp(np.linspace(0, 511, 768, dtype=np.float32), np.arange(512, dtype=np.float32), ref).astype(np.float32)
                eg.push_speaker_24k(ref24)
                mic_echo = ref * (coupling if mode_name != "headphones" else 0.002) + rng.normal(0.0, 0.0015, 512).astype(np.float32)
                if mode_name == "raw_vad":
                    prob = vad.prob(mic_echo)
                    hit = prob >= 0.5 and float(np.sqrt(np.mean(mic_echo * mic_echo))) >= 0.006
                    need = 3
                else:
                    hp = (mode_name == "headphones")
                    clean, _, _, above = eg.process(mic_echo, headphones=hp)
                    prob = vad.prob(clean)
                    hit = above and prob >= (0.55 if hp else 0.65)
                    need = 3 if hp else 5
                barge_streak = barge_streak + 1 if hit else 0
                if barge_streak >= need:
                    triggered = True
                    break
            if triggered:
                false_triggers += 1

            # 2) Estudante fala de verdade por cima da caixa de som (amplitude mais forte que o eco)
            vad.reset()
            barge_streak = 0
            detected = False
            n_b = min(50, user_barge_16k.size // 512, tts_ref_16k.size // 512)
            for i in range(n_b):
                ref = tts_ref_16k[i * 512:(i + 1) * 512] * 0.6
                ref24 = np.interp(np.linspace(0, 511, 768, dtype=np.float32), np.arange(512, dtype=np.float32), ref).astype(np.float32)
                eg.push_speaker_24k(ref24)
                user_f = user_barge_16k[i * 512:(i + 1) * 512] * 1.25
                mic_mix = user_f + ref * (coupling if mode_name != "headphones" else 0.002)
                if mode_name == "raw_vad":
                    prob = vad.prob(mic_mix)
                    hit = prob >= 0.5
                    need = 3
                else:
                    hp = (mode_name == "headphones")
                    clean, _, _, above = eg.process(mic_mix, headphones=hp)
                    prob = vad.prob(clean)
                    hit = above and prob >= (0.55 if hp else 0.65)
                    need = 3 if hp else 5
                barge_streak = barge_streak + 1 if hit else 0
                if barge_streak >= need:
                    detected = True
                    break
            if detected:
                true_barge += 1
        return {"trials": 20, "false_triggers": false_triggers, "true_barge_in": true_barge}

    out = {
        "headphones": eval_mode("headphones"),
        "speaker_raw_vad": eval_mode("raw_vad"),
        "speaker_barrier_only": eval_mode("barrier_only"),
        "speaker_pyaec_plus_barrier": eval_mode("pyaec_plus_barrier"),
    }
    print("  Echo:", json.dumps(out), flush=True)
    return out


# --- Auxiliar para rodar turnos reais fim a fim no `CallManager` -----------------------------------------------------

def run_call_turns(turn_slugs, voice_overrides=None, first_steps_override=None, fast_drain_s=0.35):
    """Roda uma lista de falas WAV num `CallManager` real (Ollama + Voice Studio + Parakeet + Silero VAD + WASAPI zero-gain)."""
    mic = FeedMic()
    timings = []
    errors = []

    cm = call.CallManager(
        mic=mic,
        speaker_factory=lambda: ZeroGainWASAPISpeaker(fast_after_first_s=fast_drain_s),
        persist_settings=False,
    )
    q = cm.subscribe()
    stop_reader = threading.Event()

    def reader():
        while not stop_reader.is_set():
            try:
                ev = q.get(timeout=0.2)
                if ev.get("type") == "timing":
                    timings.append(ev)
                elif ev.get("type") == "error":
                    errors.append(ev)
            except queue.Empty:
                pass

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    try:
        cm.start(temporary=True)
        t_wait = time.monotonic()
        while cm.state == "preparing" and time.monotonic() - t_wait < 90:
            time.sleep(0.05)
        if voice_overrides:
            cm.update_settings(voice_overrides, persist=False)
        if first_steps_override is not None:
            cm._s["_first_steps"] = int(first_steps_override)

        for slug in turn_slugs:
            prev_n = len(timings)
            audio = load_wav_16k(SAMPLES_DIR / f"{slug}.wav")
            dur_s = mic.feed_audio(audio)
            # Espera o áudio terminar de entrar + o turno completar e voltar para `listening`
            deadline = time.monotonic() + dur_s + 60.0
            while time.monotonic() < deadline:
                if len(timings) > prev_n and cm.state == "listening" and mic.pending_seconds() == 0:
                    break
                time.sleep(0.05)
            time.sleep(0.15)
    finally:
        cm.stop()
        stop_reader.set()
        cm.unsubscribe(q)
        rt.join(timeout=1.0)
    return timings, errors


# --- 4. Ablações: silêncio (450/700/1100 ms), resposta antecipada (ON/OFF) e passos do 1º pedaço (8/12/16) -----------

def bench_ablation():
    print("[4/5] Medindo ablações (silêncio 450/700/1100 ms, resposta antecipada e passos 8/12/16)...", flush=True)
    slugs_6 = ["01_sono", "02_memoria", "01_sono", "02_memoria", "01_sono", "02_memoria"]
    out = {"silence_and_early": {}, "first_chunk_steps": {}, "pause_false_cutoffs": {}}

    # A. Silêncio × Resposta antecipada (em 12 passos equilibrado)
    configs = [
        ("fast_450_early_on", {"call_silence": "fast", "call_early": True, "call_quality": "balanced"}),
        ("fast_450_early_off", {"call_silence": "fast", "call_early": False, "call_quality": "balanced"}),
        ("normal_700_early_on", {"call_silence": "normal", "call_early": True, "call_quality": "balanced"}),
        ("normal_700_early_off", {"call_silence": "normal", "call_early": False, "call_quality": "balanced"}),
        ("patient_1100_early_on", {"call_silence": "patient", "call_early": True, "call_quality": "balanced"}),
    ]
    for name, cfg in configs:
        call._FILLER_CACHE.clear()
        ts, errs = run_call_turns(slugs_6, voice_overrides=cfg, fast_drain_s=0.25)
        out["silence_and_early"][name] = {
            "turns": len(ts),
            "errors": len(errs),
            "eos_ms": pct_stats([t["eos_ms"] for t in ts]),
            "earcon_ms": pct_stats([t.get("earcon_ms") for t in ts]),
            "asr_ms": pct_stats([t["asr_ms"] for t in ts]),
            "llm_first_ms": pct_stats([t["llm_first_ms"] for t in ts]),
            "llm_clause_ms": pct_stats([t["llm_clause_ms"] for t in ts]),
            "tts_first_ms": pct_stats([t["tts_first_ms"] for t in ts]),
            "play_first_ms": pct_stats([t.get("play_first_ms") for t in ts]),
            "after_eos_ms": pct_stats([t["after_eos_ms"] for t in ts]),
            "total_ms": pct_stats([t["total_ms"] for t in ts]),
        }
        print(f"    {name}: total p50={out['silence_and_early'][name]['total_ms']['p50']} ms, p90={out['silence_and_early'][name]['total_ms']['p90']} ms", flush=True)

    #Checa cortes prematuros quando o estudante faz uma pausa respiratória no meio da frase (320 ms, 550 ms, 850 ms)
    vad = call.load_vad()
    part_a = load_wav_16k(SAMPLES_DIR / "01_sono.wav")[:int(16000 * 2.2)]
    part_b = load_wav_16k(SAMPLES_DIR / "02_memoria.wav")[:int(16000 * 2.0)]
    for preset, target_ms in call.SILENCE_MS.items():
        cuts = {}
        for pause_ms in (320, 550, 850):
            vad.reset()
            utt = np.concatenate((part_a, np.zeros(int(16000 * pause_ms / 1000.0), dtype=np.float32), part_b))
            speaking, sil, cut_early = False, 0, False
            for i in range(0, utt.size - 512, 512):
                fr = utt[i:i + 512]
                lvl = float(np.sqrt(np.mean(fr * fr)))
                is_sp = vad.prob(fr) >= 0.5 and lvl >= 0.006
                if is_sp:
                    speaking, sil = True, 0
                elif speaking:
                    sil += 1
                    if sil * 32.0 >= target_ms and i < part_a.size + int(16000 * pause_ms / 1000.0):
                        cut_early = True
                        break
            cuts[f"pause_{pause_ms}ms"] = cut_early
        out["pause_false_cutoffs"][preset] = cuts

    # B. Passos do 1º pedaço (`_first_steps`: 8, 12 e 16 com o resto em 16 passos, mais 12 uniforme)
    step_configs = [
        ("first8_rest16", {"call_silence": "normal", "call_early": True, "call_quality": "quality"}, 8),
        ("first12_rest16", {"call_silence": "normal", "call_early": True, "call_quality": "quality"}, 12),
        ("uniform_12", {"call_silence": "normal", "call_early": True, "call_quality": "balanced"}, None),
        ("uniform_16", {"call_silence": "normal", "call_early": True, "call_quality": "quality"}, None),
    ]
    for name, cfg, fsteps in step_configs:
        ts, errs = run_call_turns(slugs_6, voice_overrides=cfg, first_steps_override=fsteps, fast_drain_s=0.25)
        out["first_chunk_steps"][name] = {
            "turns": len(ts),
            "errors": len(errs),
            "tts_first_ms": pct_stats([t["tts_first_ms"] for t in ts]),
            "total_ms": pct_stats([t["total_ms"] for t in ts]),
        }
        print(f"    {name}: tts_first p50={out['first_chunk_steps'][name]['tts_first_ms']['p50']} ms | total p50={out['first_chunk_steps'][name]['total_ms']['p50']} ms", flush=True)

    return out


# --- 5. >= 20 turnos quentes + estabilidade de VRAM e RAM numa chamada contínua real de 10 minutos (600 s) -----------

def bench_soak_and_20_turns(duration_s=600.0, min_turns=22):
    print(f"[5/5] Rodando chamada contínua real de {int(duration_s)} s (10 min) com >= {min_turns} turnos quentes...", flush=True)
    mic = FeedMic()
    timings = []
    errors = []
    mem_trace = []

    # Na chamada de 10 minutos, toca a resposta inteira em tempo real no ZeroGainWASAPISpeaker (`fast_after_first_s=None`)
    cm = call.CallManager(
        mic=mic,
        speaker_factory=lambda: ZeroGainWASAPISpeaker(fast_after_first_s=None),
        persist_settings=False,
    )
    q = cm.subscribe()
    stop_reader = threading.Event()

    def reader():
        while not stop_reader.is_set():
            try:
                ev = q.get(timeout=0.2)
                if ev.get("type") == "timing":
                    timings.append(ev)
                elif ev.get("type") == "error":
                    errors.append(ev)
            except queue.Empty:
                pass

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()

    # Sequência de 24 turnos variados cobrindo conversa falada (>= 20 turnos diretos) + mapa mental, diagrama e erros
    turn_plan = (
        ["01_sono", "02_memoria"] * 10  # 20 turnos de conversa direta para estatística limpa de latência
        + ["03_mapa", "05_diagrama", "09_erros", "01_sono"]  # + 4 turnos com cartões visuais / mastery = 24 turnos!
    )

    try:
        cm.start(temporary=True)
        t_wait = time.monotonic()
        while cm.state == "preparing" and time.monotonic() - t_wait < 90:
            time.sleep(0.05)
        # Usa os padrões medidos da chamada (`call_autostop=0` para manter 10 min mesmo nos intervalos entre falas)
        cm.update_settings({"call_autostop": 0}, persist=False)

        t_start = time.monotonic()
        next_sample_at = 0.0
        turn_idx = 0
        spacing_s = max(18.0, (duration_s - 35.0) / len(turn_plan))

        while True:
            elapsed = time.monotonic() - t_start
            if elapsed >= next_sample_at:
                snap = {"elapsed_s": round(elapsed, 1), "turns_done": len(timings), "state": cm.state, **mem_snapshot()}
                mem_trace.append(snap)
                print(f"    [t={snap['elapsed_s']:5.1f}s] turnos={snap['turns_done']:2d} | VRAM={snap['vram_used_mb']} MB | RSS={snap['proc_rss_mb']} MB | RAM livre={snap['sys_ram_free_mb']} MB", flush=True)
                next_sample_at += 30.0

            if elapsed >= duration_s and len(timings) >= min_turns and cm.state == "listening":
                break

            if turn_idx < len(turn_plan) and elapsed >= turn_idx * spacing_s and cm.state == "listening" and mic.pending_seconds() == 0:
                slug = turn_plan[turn_idx]
                turn_idx += 1
                prev_n = len(timings)
                audio = load_wav_16k(SAMPLES_DIR / f"{slug}.wav")
                dur_s = mic.feed_audio(audio)
                deadline = time.monotonic() + dur_s + 75.0
                while time.monotonic() < deadline:
                    now_el = time.monotonic() - t_start
                    if now_el >= next_sample_at:
                        snap = {"elapsed_s": round(now_el, 1), "turns_done": len(timings), "state": cm.state, **mem_snapshot()}
                        mem_trace.append(snap)
                        print(f"    [t={snap['elapsed_s']:5.1f}s] turnos={snap['turns_done']:2d} | VRAM={snap['vram_used_mb']} MB | RSS={snap['proc_rss_mb']} MB | RAM livre={snap['sys_ram_free_mb']} MB", flush=True)
                        next_sample_at += 30.0
                    if len(timings) > prev_n and cm.state == "listening" and mic.pending_seconds() == 0:
                        break
                    time.sleep(0.1)
                if len(timings) > prev_n:
                    last = timings[-1]
                    print(f"      -> Turno {len(timings):2d} ({slug}): eos={last['eos_ms']} ms | earcon={last['earcon_ms']} ms | asr={last['asr_ms']} ms | llm={last['llm_clause_ms']} ms | tts={last['tts_first_ms']} ms | play={last['play_first_ms']} ms | TOTAL={last['total_ms']} ms", flush=True)
            else:
                time.sleep(0.25)

        # Amostra final exatamente no encerramento dos 600 s
        final_el = time.monotonic() - t_start
        mem_trace.append({"elapsed_s": round(final_el, 1), "turns_done": len(timings), "state": cm.state, **mem_snapshot()})
    finally:
        cm.stop()
        stop_reader.set()
        cm.unsubscribe(q)
        rt.join(timeout=1.0)

    chat_20 = timings[:20]
    stage_keys = ("eos_ms", "earcon_ms", "asr_ms", "llm_first_ms", "llm_clause_ms", "tts_first_ms", "play_first_ms", "after_eos_ms", "total_ms")
    summary_chat20 = {k: pct_stats([t.get(k) for t in chat_20]) for k in stage_keys}
    summary_all = {k: pct_stats([t.get(k) for t in timings]) for k in stage_keys}

    vrams = [m["vram_used_mb"] for m in mem_trace if m["vram_used_mb"] > 0]
    rss_vals = [m["proc_rss_mb"] for m in mem_trace if m["proc_rss_mb"] > 0]

    return {
        "duration_s": round(mem_trace[-1]["elapsed_s"], 1) if mem_trace else 0.0,
        "turns_completed": len(timings),
        "errors": errors,
        "settings_used": {k: settings.load()["voice"][k] for k in ("call_silence", "call_early", "call_quality", "call_asr", "call_length", "call_earcon")},
        "chat_20_turns": summary_chat20,
        "all_turns": summary_all,
        "raw_turns": timings,
        "memory_10min": {
            "samples": mem_trace,
            "vram_start_mb": vrams[0] if vrams else 0,
            "vram_end_mb": vrams[-1] if vrams else 0,
            "vram_peak_mb": max(vrams) if vrams else 0,
            "vram_delta_mb": (vrams[-1] - vrams[0]) if len(vrams) >= 2 else 0,
            "rss_start_mb": rss_vals[0] if rss_vals else 0.0,
            "rss_end_mb": rss_vals[-1] if rss_vals else 0.0,
            "rss_peak_mb": max(rss_vals) if rss_vals else 0.0,
            "rss_delta_mb": round(rss_vals[-1] - rss_vals[0], 1) if len(rss_vals) >= 2 else 0.0,
        },
    }


class _FT(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


def _ft(x):
    return (x.hi << 32) | x.lo


def _cpu_times():
    """(sistema_ocupado_100ns, sistema_total_100ns, processo_100ns) sem dependências extras."""
    k32 = ctypes.windll.kernel32
    idle, kern, user, c, e, pk, pu = _FT(), _FT(), _FT(), _FT(), _FT(), _FT(), _FT()
    k32.GetSystemTimes.argtypes = [ctypes.c_void_p] * 3
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.GetProcessTimes.argtypes = [ctypes.c_void_p] * 5
    k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    k32.GetProcessTimes(k32.GetCurrentProcess(), ctypes.byref(c), ctypes.byref(e), ctypes.byref(pk), ctypes.byref(pu))
    total = _ft(kern) + _ft(user)
    return total - _ft(idle), total, _ft(pk) + _ft(pu)


class Sampler(threading.Thread):
    """Amostra a cada `every` s: CPU do sistema, CPU deste processo (em núcleos), RSS, RAM livre e VRAM usada."""

    def __init__(self, every=1.0):
        super().__init__(daemon=True, name="Bench sampler")
        self.every, self.rows, self._stop_ev = every, [], threading.Event()
        self.t0 = time.monotonic()

    def run(self):
        busy0, tot0, proc0 = _cpu_times()
        w0 = time.monotonic()
        while not self._stop_ev.wait(self.every):
            busy1, tot1, proc1 = _cpu_times()
            w1 = time.monotonic()
            row = {"t": round(w1 - self.t0, 1),
                   "cpu_sys_pct": round(100.0 * (busy1 - busy0) / max(1, tot1 - tot0), 1),
                   "cpu_proc_cores": round((proc1 - proc0) / 1e7 / max(1e-6, w1 - w0), 2), **mem_snapshot()}
            self.rows.append(row)
            busy0, tot0, proc0, w0 = busy1, tot1, proc1, w1

    def stop(self):
        self._stop_ev.set()
        self.join(timeout=3)
        return self.rows

    def summary(self):
        def col(k):
            v = [r[k] for r in self.rows if r.get(k) is not None]
            return {"p50": round(float(np.percentile(v, 50)), 1), "max": round(float(max(v)), 1), "min": round(float(min(v)), 1)} if v else None
        out = {k: col(k) for k in ("cpu_sys_pct", "cpu_proc_cores", "proc_rss_mb", "vram_used_mb", "sys_ram_free_mb")}
        out["samples"] = len(self.rows)
        return out


# Fala do estudante (WAV sintéticos autorizados) por categoria: pergunta comum (só conversa) x exige busca/ferramenta
COMMON_TURNS = ["01_sono", "02_memoria"]
HEAVY_TURNS = ["03_mapa", "04_quiz", "05_diagrama", "09_erros"]


def run_turns_detailed(plan, overrides=None, fast_drain_s=0.25, label="", settle_s=0.3):
    """Roda `plan` (lista de slugs) num CallManager real e mede cada etapa a partir dos EVENTOS (serve para o código
    antigo e o novo): fim da fala, entendi, transcrição, 1ª palavra do modelo, 1ª frase falada (evento `sentence`), volta a ouvir."""
    mic, log, errors = FeedMic(), [], []
    cm = call.CallManager(mic=mic, speaker_factory=lambda: ZeroGainWASAPISpeaker(fast_after_first_s=fast_drain_s), persist_settings=False)
    q, stop_reader = cm.subscribe(), threading.Event()

    def reader():
        while not stop_reader.is_set():
            try:
                ev = q.get(timeout=0.1)
            except queue.Empty:
                continue
            t = time.monotonic()
            ty = ev.get("type")
            if ty in ("state", "sentence", "timing", "final", "error", "card", "interrupted", "token"):
                info = {k: ev.get(k) for k in ("state", "i", "seconds", "kind", "turn") if k in ev}
                if ty == "timing":
                    info.update({k: v for k, v in ev.items() if k not in ("type", "seq", "turn_id")})
                log.append((t, ty, info))
                if ty == "error":
                    errors.append(ev)

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    sampler = Sampler(1.0)
    turns = []
    ready_ms = None
    try:
        t_ready0 = time.monotonic()
        cm.start(temporary=True)
        while cm.state == "preparing" and time.monotonic() - t_ready0 < 120:
            time.sleep(0.02)
        ready_ms = round((time.monotonic() - t_ready0) * 1000.0, 1)
        if overrides:
            cm.update_settings(overrides, persist=False)
        sampler.start()
        for slug in plan:
            mark = len(log)
            audio = load_wav_16k(SAMPLES_DIR / f"{slug}.wav")
            t_feed = time.monotonic()
            dur_s = mic.feed_audio(audio)
            t_speech_end = t_feed + dur_s
            deadline = t_feed + dur_s + 90.0
            while time.monotonic() < deadline:
                got_timing = any(e[1] == "timing" for e in log[mark:])
                if got_timing and cm.state == "listening" and mic.pending_seconds() == 0:
                    break
                time.sleep(0.03)
            time.sleep(settle_s)
            ev = log[mark:]
            t_eos = next((e[0] for e in ev if e[1] == "state" and e[2].get("state") == "end_of_speech"), None)
            t_think = next((e[0] for e in ev if e[1] == "state" and e[2].get("state") == "thinking"), None)
            t_tok = next((e[0] for e in ev if e[1] == "token"), None)
            sent_ts = [e[0] for e in ev if e[1] == "sentence"]
            sent_secs = [e[2].get("seconds") or 0.0 for e in ev if e[1] == "sentence"]
            t_back = next((e[0] for e in reversed(ev) if e[1] == "state" and e[2].get("state") == "listening"), None)
            tm = next((e[2] for e in ev if e[1] == "timing"), {})

            def ms(a, b):
                return round((a - b) * 1000.0, 1) if (a is not None and b is not None) else None

            gaps = [ms(sent_ts[i + 1], sent_ts[i]) - round(sent_secs[i] * 1000.0, 1) for i in range(len(sent_ts) - 1)] if len(sent_ts) > 1 else []
            turns.append({"slug": slug, "speech_s": round(dur_s, 2), "eos_detect_ms": ms(t_eos, t_speech_end),
                          "asr_to_think_ms": ms(t_think, t_eos), "first_token_ms": ms(t_tok, t_eos),
                          "first_audio_from_eos_ms": ms(sent_ts[0] if sent_ts else None, t_eos),
                          "first_audio_from_speech_end_ms": ms(sent_ts[0] if sent_ts else None, t_speech_end),
                          "sentences": len(sent_ts), "back_to_listening_ms": ms(t_back, t_speech_end),
                          "gap_after_playback_ms": [round(g, 1) for g in gaps], "timing": tm})
            last = turns[-1]
            print(f"    {label} {slug}: eos+{last['eos_detect_ms']} ms | 1a palavra +{last['first_token_ms']} ms | "
                  f"1o audio +{last['first_audio_from_eos_ms']} ms (do fim da fala {last['first_audio_from_speech_end_ms']} ms) | "
                  f"{last['sentences']} frases", flush=True)
    finally:
        if sampler.is_alive():
            sampler.stop()
        cm.stop()
        stop_reader.set()
        cm.unsubscribe(q)
        rt.join(timeout=1.0)
    return {"ready_ms": ready_ms, "turns": turns, "errors": [{k: v for k, v in e.items() if k != "action"} for e in errors],
            "resources": sampler.summary()}


def summarize_turns(res):
    keys = ("eos_detect_ms", "asr_to_think_ms", "first_token_ms", "first_audio_from_eos_ms", "first_audio_from_speech_end_ms", "back_to_listening_ms")
    out = {k: pct_stats([t.get(k) for t in res["turns"]]) for k in keys}
    for k in ("earcon_ms", "asr_ms", "llm_first_ms", "llm_clause_ms", "tts_first_ms", "play_first_ms", "after_eos_ms", "total_ms",
              "search_ms", "understand_ms", "complete_ms"):
        out["timing." + k] = pct_stats([(t.get("timing") or {}).get(k) for t in res["turns"]])
    all_gaps = [g for t in res["turns"] for g in t["gap_after_playback_ms"]]
    out["inter_sentence_gap_ms"] = pct_stats(all_gaps)
    out["turns"], out["errors"], out["ready_ms"], out["resources"] = len(res["turns"]), len(res["errors"]), res["ready_ms"], res["resources"]
    return out


def bench_turns(n_common=16):
    """Linha de base por etapa: 1o turno (frio no processo) + perguntas comuns aquecidas + pedidos que exigem busca/ferramenta."""
    print(f"[turns] {n_common} perguntas comuns + {len(HEAVY_TURNS)} pedidos com cartao/ferramenta...", flush=True)
    common_plan = (COMMON_TURNS * (n_common // 2 + 1))[:n_common]
    common = run_turns_detailed(common_plan, label="comum")
    heavy = run_turns_detailed(HEAVY_TURNS, label="pesado")
    first = common["turns"][0] if common["turns"] else {}
    return {"cold_services": dict(COLD), "first_turn_in_process": first,
            "common_all": summarize_turns(common),
            "common_warm_excluding_first": summarize_turns({**common, "turns": common["turns"][1:]}),
            "heavy": summarize_turns(heavy), "raw_common": common["turns"], "raw_heavy": heavy["turns"]}


def bench_realtime(n_common=20, gap_s=4.0):
    """Chamada contínua em TEMPO REAL (a reprodução toca inteira, em ganho zero): >= 20 turnos comuns + 4 com cartão, uma
    pausa entre eles (~10 min no total). Mede lacunas entre frases, conclusão do turno e CPU/RAM/VRAM a cada segundo."""
    print(f"[realtime] {n_common} comuns + {len(HEAVY_TURNS)} com cartão, em tempo real...", flush=True)
    plan = (COMMON_TURNS * (n_common // 2 + 1))[:n_common] + HEAVY_TURNS
    res = run_turns_detailed(plan, fast_drain_s=None, label="rt", settle_s=gap_s)
    return {"summary": summarize_turns(res), "summary_common": summarize_turns({**res, "turns": res["turns"][:n_common]}),
            "summary_heavy": summarize_turns({**res, "turns": res["turns"][n_common:]}), "raw": res["turns"],
            "errors": res["errors"]}


# --- Sondas do caminho crítico: síntese (isolada x sob carga do modelo, passos, silêncio nas bordas) e fim de fala ---------

PROBE_FIRST = [
    "A consolidação da memória acontece no sono profundo,",
    "Quando você estuda, o hipocampo registra o conteúdo,",
    "A fotossíntese transforma luz em energia química,",
    "A sístole é o momento em que o coração se contrai,",
    "Os keyframes marcam valores no tempo,",
    "A segunda lei de Newton relaciona força e aceleração,",
]
PROBE_FULL = [
    "A consolidação da memória acontece principalmente durante o sono profundo, quando o hipocampo reativa as lembranças.",
    "Na fase clara da fotossíntese a planta produz ATP e NADPH, que depois alimentam o ciclo de Calvin.",
    "O ciclo cardíaco alterna a sístole, em que os ventrículos ejetam sangue, e a diástole, em que eles relaxam e enchem.",
]


def _edges_ms(wav_bytes, thresh=0.003):
    a = call.wav_to_float24k(wav_bytes)
    idx = np.flatnonzero(np.abs(a) > thresh)
    if idx.size == 0:
        return None
    return {"lead_ms": round(idx[0] / call.PLAY_SR * 1000, 1), "tail_ms": round((a.size - 1 - idx[-1]) / call.PLAY_SR * 1000, 1),
            "audio_s": round(a.size / call.PLAY_SR, 2)}


def _synth_once(text, steps, seed=1):
    s_voice = {**settings.load()["voice"], "cache_mb": 0}
    w = listen.who("call", s_voice, start=False)
    t0 = time.monotonic()
    data, secs, _ = listen.synth_sentence(text, w, s_voice, steps, seed, lambda: None)
    return (time.monotonic() - t0) * 1000.0, data


def _wer_of(text, wav_bytes):
    hyp, _, _ = call.transcribe_call_audio(call.load_wav_bytes_16k(wav_bytes) if hasattr(call, "load_wav_bytes_16k") else _wav16(wav_bytes), "parakeet")
    return voice._wer(voice.words(text), voice.words(hyp)), hyp


def _wav16(wav_bytes):
    a = call.wav_to_float24k(wav_bytes)
    n16 = int(round(a.size * 16000 / call.PLAY_SR))
    return np.interp(np.linspace(0, a.size - 1, n16, dtype=np.float32), np.arange(a.size, dtype=np.float32), a).astype(np.float32)


def bench_tts_probe(reps=4):
    """1. Latência do 1º trecho: isolada x com o modelo de texto gerando ao mesmo tempo (disputa pela mesma GPU).
    2. Passos 8/12/16: tempo, fator de tempo real e erro de palavras (Parakeet CPU) com o MESMO material.
    3. Silêncio no começo e no fim de cada trecho (decide se vale aparar). Guarda pares cegos para a escuta."""
    print("[tts] sondando a síntese (isolada, sob carga do modelo, passos, silêncio)...", flush=True)
    out = {"steps": {}, "contention": {}, "edges": {}}
    escuta = Path(os.environ.get("LUMEN_ESCUTA_DIR") or f"D:/Lumen/voz-conversa-20261108/escuta/{RUN_ID}")
    escuta.mkdir(parents=True, exist_ok=True)
    for steps in (8, 12, 16):
        times, rtf, wers, leads, tails = [], [], [], [], []
        for text in PROBE_FIRST + PROBE_FULL:
            for r in range(reps if text in PROBE_FIRST else 2):
                ms, data = _synth_once(text, steps)
                edges = _edges_ms(data)
                if r == 0:
                    w, _hyp = _wer_of(text, data)
                    wers.append(w)
                    if text == PROBE_FIRST[0] or text == PROBE_FULL[0]:
                        (escuta / f"{'curta' if text == PROBE_FIRST[0] else 'longa'}_{steps}p.wav").write_bytes(data)
                if edges:
                    times.append(ms)
                    rtf.append(ms / 1000.0 / max(edges["audio_s"], 0.1))
                    leads.append(edges["lead_ms"])
                    tails.append(edges["tail_ms"])
        out["steps"][str(steps)] = {"synth_ms": pct_stats(times), "rtf": pct_stats([x * 1000 for x in rtf]), "wer_pct": round(100 * float(np.mean(wers)), 2),
                                    "n_wer": len(wers)}
        out["edges"][str(steps)] = {"lead_ms": pct_stats(leads), "tail_ms": pct_stats(tails)}
        print(f"    {steps}p: síntese p50={out['steps'][str(steps)]['synth_ms']['p50']} ms | WER={out['steps'][str(steps)]['wer_pct']}% | "
              f"silêncio inicial p50={out['edges'][str(steps)]['lead_ms']['p50']} ms, final p50={out['edges'][str(steps)]['tail_ms']['p50']} ms", flush=True)

    # Disputa pela GPU: o mesmo 1º trecho (12 passos) com o modelo de texto escrevendo uma resposta longa ao mesmo tempo
    prov = providers.chain(settings.load(), True)[0][0]
    stop, tokens = threading.Event(), [0]

    def load():
        while not stop.is_set():
            try:
                for ev in prov.stream("Você é um professor.", [{"role": "user", "content": "Explique em detalhes, em 400 palavras, como funciona a memória humana."}],
                                      [], lambda: None, effort="medium", model=None, think=False, max_tokens=420):
                    if ev.get("type") == "text":
                        tokens[0] += 1
                    if stop.is_set():
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)

    alone = [_synth_once(t, 12)[0] for t in PROBE_FIRST for _ in range(2)]
    th = threading.Thread(target=load, daemon=True)
    th.start()
    time.sleep(1.5)   # o modelo já está decodificando
    loaded = [_synth_once(t, 12)[0] for t in PROBE_FIRST for _ in range(2)]
    stop.set()
    th.join(timeout=30)
    out["contention"] = {"first_clause_12p_alone_ms": pct_stats(alone), "first_clause_12p_with_llm_decoding_ms": pct_stats(loaded),
                         "llm_chunks_streamed_during": tokens[0]}
    print(f"    1º trecho (12p): sozinho p50={out['contention']['first_clause_12p_alone_ms']['p50']} ms | com o modelo escrevendo p50="
          f"{out['contention']['first_clause_12p_with_llm_decoding_ms']['p50']} ms", flush=True)
    out["blind_pairs_dir"] = str(escuta)
    return out


def _vad_tail_stats(wav, hysteresis):
    """Para cada fala sintética: onde o VAD acha que a voz acabou x onde ela acaba de verdade (energia). Positivo = o VAD
    segura a fala um pouco além (não corta o fim das palavras); negativo = cortou a cauda."""
    vad = call.load_vad()
    vad.reset()
    a = wav
    n = a.size // 512
    last_vad, last_energy = -1, -1
    for i in range(n):
        fr = a[i * 512:(i + 1) * 512]
        lv = float(np.sqrt(np.mean(fr * fr)))
        pr = vad.prob(fr)
        keep = (call.SPEECH_KEEP if hysteresis else call.SPEECH_ON)
        if pr >= (call.SPEECH_ON if last_vad < 0 else keep) and lv >= 0.004:
            last_vad = i
        if lv >= 0.008:
            last_energy = i
    return (last_vad - last_energy) * 32.0


def bench_endpoint_probe():
    """Fim de fala com o VAD Silero e o Parakeet REAIS sobre falas sintéticas: (1) cauda das palavras com e sem histerese;
    (2) pausa no meio da frase: a espera por frase inacabada evita o corte? (3) falsa espera em frases completas."""
    print("[endpoint] fim de fala: VAD e Parakeet reais...", flush=True)
    out = {"tail_ms_old_threshold": [], "tail_ms_hysteresis": [], "mid_pause": [], "complete_false_hold": []}
    waves = {slug: load_wav_16k(SAMPLES_DIR / f"{slug}.wav") for slug, _ in SAMPLES}
    # Cauda: usa o WAV bruto (com a descida natural da voz e 1 s de silêncio), sem o corte de silêncio de load_wav_16k
    raw = {}
    for slug, _ in SAMPLES:
        a, sr = voice.read_wav(SAMPLES_DIR / f"{slug}.wav")
        a = np.asarray(a, dtype=np.float32)
        a = a.mean(axis=1) if a.ndim > 1 else a
        if sr != 16000:
            a = np.interp(np.linspace(0, a.size - 1, int(round(a.size * 16000 / sr)), dtype=np.float32), np.arange(a.size, dtype=np.float32), a).astype(np.float32)
        raw[slug] = np.concatenate((a, np.zeros(16000, np.float32)))
    for slug, a in raw.items():
        out["tail_ms_old_threshold"].append(_vad_tail_stats(a, False))
        out["tail_ms_hysteresis"].append(_vad_tail_stats(a, True))
    out["tail_summary"] = {"old": pct_stats(out["tail_ms_old_threshold"]), "hysteresis": pct_stats(out["tail_ms_hysteresis"])}
    # pausa no meio: corta no ponto de menor energia entre 35% e 65% da fala (uma micro pausa entre palavras)
    for slug, a in waves.items():
        if a.size < 16000 * 2.0:
            continue
        lo, hi = int(a.size * 0.35), int(a.size * 0.65)
        win = 1600
        energy = [float(np.mean(np.abs(a[i:i + win]))) for i in range(lo, hi - win, 160)]
        cut = lo + int(np.argmin(energy)) * 160 + win // 2
        part_a = a[:cut]
        text, ms, eng = call.transcribe_call_audio(np.concatenate((part_a, np.zeros(int(16000 * 0.25), np.float32))), "parakeet")
        out["mid_pause"].append({"slug": slug, "cut_at_s": round(cut / 16000, 2), "heard": text, "looks_unfinished": call.looks_unfinished(text)})
    full = []
    for slug, a in waves.items():
        text, ms, eng = call.transcribe_call_audio(np.concatenate((a, np.zeros(int(16000 * 0.25), np.float32))), "parakeet")
        full.append({"slug": slug, "heard": text, "looks_unfinished": call.looks_unfinished(text)})
    out["complete_false_hold"] = full
    out["summary"] = {"mid_pause_cases": len(out["mid_pause"]), "mid_pause_hold_triggers": sum(1 for x in out["mid_pause"] if x["looks_unfinished"]),
                      "complete_cases": len(full), "complete_false_holds": sum(1 for x in full if x["looks_unfinished"])}
    print(f"    cauda p50: limiar antigo {out['tail_summary']['old']['p50']} ms x histerese {out['tail_summary']['hysteresis']['p50']} ms | "
          f"pausa no meio: espera ligou em {out['summary']['mid_pause_hold_triggers']}/{out['summary']['mid_pause_cases']} | "
          f"frases completas com espera falsa: {out['summary']['complete_false_holds']}/{out['summary']['complete_cases']}", flush=True)
    return out


class StampedSpeaker(ZeroGainWASAPISpeaker):
    """ZeroGain que anota quando entrou o último bloco e quando o buffer foi esvaziado (flush) na interrupção."""
    LAST_PLAY = [0.0]
    FLUSHES = []

    def play(self, data):
        super().play(data)
        StampedSpeaker.LAST_PLAY[0] = time.monotonic()

    def flush(self):
        StampedSpeaker.FLUSHES.append(time.monotonic())
        super().flush()


def bench_interrupts(trials=8):
    """Interrupção e retomada com o pipeline REAL (VAD, Parakeet, Ollama, Voice Studio): enquanto a resposta A toca, a fala B entra pelo
    microfone simulado. Mede: do início da fala B até a interrupção ser chamada, da interrupção até o último bloco de áudio, frases
    do turno A depois da interrupção (devem ser 0) e se a resposta B sai normalmente. Inclui também uma pausa longa no meio de uma frase."""
    print(f"[interrupts] {trials} interrupções por fala por cima + 2 pausas no meio da frase...", flush=True)
    mic, log = FeedMic(), []
    cm = call.CallManager(mic=mic, speaker_factory=lambda: StampedSpeaker(fast_after_first_s=None), persist_settings=False)
    q, stop_reader = cm.subscribe(), threading.Event()

    def reader():
        while not stop_reader.is_set():
            try:
                ev = q.get(timeout=0.05)
            except queue.Empty:
                continue
            log.append((time.monotonic(), ev))

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    res = {"barge": [], "pause": []}

    def onset_ms(slug):
        """Quando a voz começa de verdade na amostra (o WAV tem ruído/silêncio antes): 1º quadro de 32 ms com Silero >= 0,5."""
        a = load_wav_16k(SAMPLES_DIR / f"{slug}.wav")
        vad = call.load_vad()
        vad.reset()
        for i in range(0, a.size - 512, 512):
            if vad.prob(a[i:i + 512]) >= 0.5:
                return i / 16000.0 * 1000.0
        return 0.0
    onsets = {slug: onset_ms(slug) for slug in ("01_sono", "02_memoria")}
    try:
        cm.start(temporary=True)
        t0 = time.monotonic()
        while cm.state == "preparing" and time.monotonic() - t0 < 120:
            time.sleep(0.02)
        cm.update_settings({"call_autostop": 0, "call_headphones": True}, persist=False)   # sem eco: o microfone é simulado
        for i in range(trials):
            slug_a, slug_b = (("01_sono", "02_memoria") if i % 2 == 0 else ("02_memoria", "01_sono"))
            mark = len(log)
            mic.feed_audio(load_wav_16k(SAMPLES_DIR / f"{slug_a}.wav"))
            end = time.monotonic() + 40
            while time.monotonic() < end and not any(e[1].get("type") == "sentence" for e in log[mark:]):
                time.sleep(0.02)
            if not any(e[1].get("type") == "sentence" for e in log[mark:]):
                res["barge"].append({"trial": i, "error": "a resposta A não começou a falar"})
                continue
            time.sleep(1.0)                                     # a resposta A já está falando
            mark_b = len(log)
            turn_a = cm._turn.id if cm._turn else None
            StampedSpeaker.FLUSHES.clear()
            audio_b = load_wav_16k(SAMPLES_DIR / f"{slug_b}.wav")
            t_speech = time.monotonic()
            mic.feed_audio(audio_b)
            end = time.monotonic() + 8
            t_int = None
            while time.monotonic() < end:
                for t, e in log[mark_b:]:
                    if e.get("type") == "state" and e.get("state") == "user_speaking":
                        t_int = t
                        break
                if t_int:
                    break
                time.sleep(0.01)
            time.sleep(0.4)
            stale = [e for t, e in log[mark_b:] if e.get("type") in ("sentence", "token") and e.get("turn_id") == turn_a and t_int and t > t_int]
            last_play = StampedSpeaker.LAST_PLAY[0]
            flush_t = StampedSpeaker.FLUSHES[0] if StampedSpeaker.FLUSHES else None
            # espera a resposta B
            end = time.monotonic() + 60
            while time.monotonic() < end:
                if any(e.get("type") == "timing" for t, e in log[mark_b:]) and cm.state == "listening" and mic.pending_seconds() == 0:
                    break
                time.sleep(0.1)
            cid = cm.conversation_id
            msgs = chats_messages(cid)
            on = onsets[slug_b]
            res["barge"].append({"trial": i, "voice_onset_in_sample_ms": round(on, 1),
                                 "voice_to_interrupt_ms": round((t_int - t_speech) * 1000 - on, 1) if t_int else None,
                                 "voice_to_flush_ms": round((flush_t - t_speech) * 1000 - on, 1) if flush_t else None,
                                 "speech_to_interrupt_ms": round((t_int - t_speech) * 1000, 1) if t_int else None,
                                 "interrupt_to_last_audio_ms": round((last_play - t_int) * 1000, 1) if (t_int and last_play >= t_int) else 0.0,
                                 "interrupt_to_flush_ms": round((flush_t - t_int) * 1000, 1) if (t_int and flush_t) else None,
                                 "stale_events_from_turn_a": len(stale),
                                 "a_marked_interrupted": any((m.get("meta") or {}).get("interrupted") for m in msgs if m["role"] == "assistant")})
            print(f"    interrupção {i}: voz→interrupção {res['barge'][-1]['voice_to_interrupt_ms']} ms | voz→áudio parado (flush) {res['barge'][-1]['voice_to_flush_ms']} ms | "
                  f"eventos velhos {len(stale)}", flush=True)
            while not (cm.state == "listening" and mic.pending_seconds() == 0):
                time.sleep(0.1)
            time.sleep(1.0)
        # Pausa no meio da frase: "Qual é a diferença entre memória de trabalho" + 1,3 s + o resto
        a = load_wav_16k(SAMPLES_DIR / "02_memoria.wav")
        lo, hi, win = int(a.size * 0.35), int(a.size * 0.65), 1600
        energy = [float(np.mean(np.abs(a[i:i + win]))) for i in range(lo, hi - win, 160)]
        cut = lo + int(np.argmin(energy)) * 160 + win // 2
        users_before = len([m for m in chats_messages(cm.conversation_id) if m["role"] == "user"])
        for pause_s in (0.9, 1.3):
            mark = len(log)
            n_user = sum(1 for t, e in log if e.get("type") == "final")
            audio = np.concatenate((a[:cut], np.zeros(int(16000 * pause_s), np.float32), a[cut:]))
            mic.feed_audio(audio)
            end = time.monotonic() + 90
            while time.monotonic() < end:
                if sum(1 for t, e in log[mark:] if e.get("type") == "timing") >= 1 and cm.state == "listening" and mic.pending_seconds() == 0:
                    break
                time.sleep(0.1)
            finals = [e.get("text") for t, e in log[mark:] if e.get("type") == "final" and not e.get("fast")]
            retracts = sum(1 for t, e in log[mark:] if e.get("type") == "retract")
            users_now = [m["content"] for m in chats_messages(cm.conversation_id) if m["role"] == "user"]
            added = users_now[users_before:]
            users_before = len(users_now)
            res["pause"].append({"pause_s": pause_s, "final_events": len(finals), "retractions": retracts, "user_messages_added": added,
                                 "cut_in_two": len(added) > 1})
            print(f"    pausa de {pause_s} s no meio: {retracts} retirada(s); pergunta(s) no histórico: {added}", flush=True)
            time.sleep(1.0)
    finally:
        cm.stop()
        stop_reader.set()
        cm.unsubscribe(q)
        rt.join(timeout=1.0)
    b = [r for r in res["barge"] if "error" not in r]
    res["summary"] = {"trials": len(b), "voice_to_interrupt_ms": pct_stats([r["voice_to_interrupt_ms"] for r in b]),
                      "voice_to_flush_ms": pct_stats([r["voice_to_flush_ms"] for r in b]),
                      "speech_to_interrupt_ms": pct_stats([r["speech_to_interrupt_ms"] for r in b]),
                      "interrupt_to_last_audio_ms": pct_stats([r["interrupt_to_last_audio_ms"] for r in b]),
                      "interrupt_to_flush_ms": pct_stats([r["interrupt_to_flush_ms"] for r in b]),
                      "stale_events_total": sum(r["stale_events_from_turn_a"] for r in b),
                      "all_a_marked_interrupted": all(r["a_marked_interrupted"] for r in b),
                      "pause_user_messages_added": [len(r["user_messages_added"]) for r in res["pause"]], "pause_retractions": [r["retractions"] for r in res["pause"]]}
    return res


def chats_messages(cid):
    from lumen.study import chats
    try:
        return chats.get(cid)["messages"]
    except Exception:  # noqa: BLE001
        return []


def bench_stages_isolated():
    """Etapas 4 e 5 isoladas (não dependem do CallManager): intenção heurística e busca nas notas (índice do cofre temporário)."""
    from lumen.study import search
    out = {}
    qs = [t for _, t in SAMPLES[:3]]
    for name, fn in (("heuristic_ms", lambda q: search.heuristic(q)),
                     ("search_ms", lambda q: search.search(q, project=None, understanding=search.heuristic(q), limit=8))):
        vals = []
        for _ in range(5):
            for q in qs:
                t0 = time.monotonic()
                fn(q)
                vals.append((time.monotonic() - t0) * 1000.0)
        out[name] = pct_stats(vals)
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    def _flush(rep):
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        merged = dict(rep)
        if OUT_JSON.exists() and cmd != "all":
            prev = json.loads(OUT_JSON.read_text("utf-8"))
            prev.update(rep)
            merged = prev
        OUT_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    started_vs = setup_temp_vault_and_services() if cmd != "endpoint" else False
    try:
        report = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "machine_initial": mem_snapshot(),
                  "run_id": RUN_ID, "code_root": str(ROOT)}
        if cmd in ("after", "tts", "probe"):
            report["cold_services"] = dict(COLD)
            report["tts_probe"] = bench_tts_probe()
            _flush(report)
        if cmd in ("after", "endpoint", "probe"):
            report["endpoint_probe"] = bench_endpoint_probe()
            _flush(report)
        if cmd in ("after", "afterturns"):
            report["stages_isolated"] = bench_stages_isolated()
            report["turns"] = bench_turns()
            _flush(report)
            report["realtime"] = bench_realtime()
            _flush(report)
        if cmd in ("interrupts",):
            report["cold_services"] = dict(COLD)
            report["interrupts"] = bench_interrupts()
            _flush(report)
        if cmd in ("realtime",):
            report["cold_services"] = dict(COLD)
            report["realtime"] = bench_realtime()
            _flush(report)
        if cmd in ("turns", "baseline"):
            report["cold_services"] = dict(COLD)
            report["stages_isolated"] = bench_stages_isolated()
            report["turns"] = bench_turns()
            _flush(report)
        if cmd in ("asr", "prelim", "all"):
            report["asr"] = bench_asr()
            _flush(report)
        if cmd in ("playback", "prelim", "all"):
            report["playback"] = bench_playback()
            _flush(report)
        if cmd in ("echo", "prelim", "all"):
            report["echo"] = bench_echo()
            _flush(report)
        if cmd in ("ablation", "prelim", "ablation_soak", "all"):
            report["ablation"] = bench_ablation()
            _flush(report)
        if cmd in ("soak", "ablation_soak", "all"):
            report["soak_10m"] = bench_soak_and_20_turns(duration_s=600.0, min_turns=22)
            _flush(report)

        print(f"\nResultado salvo em: {OUT_JSON}", flush=True)
    finally:
        db.close()
        if started_vs and os.environ.get("LUMEN_BENCH_KEEP_VS") != "1":
            voicestudio.BACKEND.stop()


if __name__ == "__main__":
    main()

