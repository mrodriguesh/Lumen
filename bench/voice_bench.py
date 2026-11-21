"""Fase 6: escolha da voz da revisão em áudio. Gera o mesmo roteiro de revisão em cada motor de fala local e mede
carga, tempo de geração, duração do áudio, velocidade (geração ÷ duração) e VRAM de pico.

Roda com o Python do ambiente de cada motor (D:\\Lumen\\voz\\<motor>), não com o .venv do Lúmen:
    D:\\Lumen\\voz\\kokoro\\Scripts\\python bench/voice_bench.py kokoro
    D:\\Lumen\\voz\\chatterbox\\Scripts\\python bench/voice_bench.py chatterbox
    D:\\Lumen\\voz\\voxcpm\\Scripts\\python bench/voice_bench.py voxcpm
e a voz do Windows (base de comparação) com o .venv: .venv\\Scripts\\python bench/voice_bench.py sapi
Depois, `.venv\\Scripts\\python bench/voice_bench.py cegas` sorteia as letras (A, B, C, D) das amostras cegas.

Saída em D:\\Lumen\\voz\\amostras: bruto\\<motor>.wav, bruto\\<motor>.json e, no fim, A.wav… com a chave em chave.json.
Os modelos baixam para HF_HOME (D:\\Lumen\\voz\\hf). Nenhuma voz é clonada: cada motor usa a voz padrão dele ou uma
voz criada por descrição de texto (VoxCPM2)."""
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

OUT = Path(r"D:\Lumen\voz\amostras")
RAW = OUT / "bruto"
os.environ.setdefault("HF_HOME", r"D:\Lumen\voz\hf")
os.environ.setdefault("TORCH_HOME", r"D:\Lumen\voz\torch")

# Roteiro de revisão (prática de lembrar): pergunta, pausa para pensar, resposta. Tema dos cursos do estudante, com os
# termos em inglês que aparecem no Premiere.
SCRIPT = [
    "Revisão rápida: animação com keyframes no Premiere.",
    "Primeira pergunta. Onde você cria o primeiro keyframe de posição de um clipe?",
    3.0,
    "Resposta: no painel Effect Controls. Você clica no cronômetro ao lado de Position, e o Premiere marca o ponto de partida.",
    1.0,
    "Segunda pergunta. Depois do primeiro keyframe, o que falta para o elemento se mover?",
    3.0,
    "Resposta: mover a agulha da linha do tempo e mudar o valor da posição. O Premiere cria o segundo keyframe sozinho e calcula o caminho entre os dois.",
    1.0,
    "Dica final: para o movimento começar e terminar suave, clique com o botão direito no keyframe e escolha Ease In ou Ease Out.",
]
# VoxCPM2: voz criada por descrição (prefixo entre parênteses), sem clonar ninguém
DESIGN = "(A calm, clear adult female teacher, Brazilian Portuguese, warm and friendly, moderate pace)"


class Peak:
    """VRAM usada no PC inteiro (nvidia-smi), amostrada a cada 0,2 s: pega também o que não passa pelo PyTorch."""

    def __init__(self):
        self.base, self.peak, self.stop = self.read(), 0, threading.Event()
        threading.Thread(target=self.loop, daemon=True).start()

    @staticmethod
    def read():
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout
            return int(out.split()[0])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return 0

    def loop(self):
        while not self.stop.is_set():
            self.peak = max(self.peak, self.read())
            time.sleep(0.2)

    def done(self):
        self.stop.set()
        return round(max(self.peak - self.base, 0) / 1024, 2)


def kokoro():
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="p", repo_id="hexgrad/Kokoro-82M")

    def say(text):
        return np.concatenate([np.asarray(audio, np.float32) for _, _, audio in pipe(text, voice="pf_dora")])
    return 24000, say, "pf_dora"


def chatterbox():
    """Finetune brasileiro (ResembleAI/Chatterbox-Multilingual-pt-br), carregado como o app carrega
    (lumen/voice_worker.py: o chatterbox-tts 0.1.7 do PyPI não carrega o finetune sozinho)."""
    import torch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lumen.voice_worker import load
    model = load()

    def say(text, **options):  # options: temperature, cfg_weight, exaggeration… (padrões do generate da 0.1.7)
        with torch.inference_mode():
            return model.generate(text, language_id="pt", **options).squeeze().float().cpu().numpy()
    return model.sr, say, "voz padrão + finetune pt-br"


def voxcpm():
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)

    import torch
    ref, sr = RAW / "voxcpm-voz-criada.wav", model.tts_model.sample_rate

    def say(text):
        """A voz é criada uma vez pela descrição, numa frase de abertura; as outras frases usam esse trecho sintético
        como referência (sem ele, cada frase sairia com uma voz um pouco diferente). A 2.0.3 não aceita `seed`."""
        torch.manual_seed(42)
        if not ref.exists():
            save(ref, model.generate(text=f"{DESIGN}Olá! Vamos revisar juntos o que você estudou hoje.",
                                     cfg_value=2.0, inference_timesteps=10), sr)
        return np.asarray(model.generate(text=text, reference_wav_path=str(ref), cfg_value=2.0, inference_timesteps=10), np.float32)
    return sr, say, "voz criada por descrição"


def sapi():
    """Base de comparação: a voz pt-BR do Windows (Microsoft Maria), pelo System.Speech."""
    def say(text):
        tmp = RAW / "sapi-tmp.wav"
        cmd = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
               "$s.SelectVoice('Microsoft Maria Desktop'); "
               f"$s.SetOutputToWaveFile('{tmp}'); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()")
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], input=text, text=True, encoding="utf-8",
                       check=True, capture_output=True)
        with wave.open(str(tmp)) as w:
            data = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
            rate = w.getframerate()
        tmp.unlink()
        say.rate = rate
        return data
    say("teste")
    return say.rate, say, "Microsoft Maria"


def save(path, audio, sr):
    """WAV de 16 bits com o volume igualado (RMS em -20 dBFS, pico até 0,98): na escuta cega, ninguém ganha por volume."""
    audio = np.asarray(audio, np.float32)
    rms = float(np.sqrt(np.mean(audio ** 2))) or 1.0
    audio = audio * (0.1 / rms)
    audio = audio * min(1.0, 0.98 / max(float(np.abs(audio).max()), 1e-9))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes((audio * 32767).astype(np.int16).tobytes())


def run(engine):
    RAW.mkdir(parents=True, exist_ok=True)
    peak = Peak()
    t = time.perf_counter()
    sr, say, voice = globals()[engine]()
    load = time.perf_counter() - t
    say(SCRIPT[0][:20])  # aquece (a primeira chamada compila e aloca)
    parts, gen, spoken = [], 0.0, 0
    for item in SCRIPT:
        if isinstance(item, float):  # pausa para pensar antes da resposta
            parts.append(np.zeros(int(sr * item), np.float32))
            continue
        t = time.perf_counter()
        said = np.asarray(say(item), np.float32).ravel()
        gen += time.perf_counter() - t
        spoken += len(said)
        parts += [said, np.zeros(int(sr * 0.35), np.float32)]  # respiro entre frases
    audio = np.concatenate(parts)
    speech = spoken / sr
    save(RAW / f"{engine}.wav", audio, sr)
    out = {"motor": engine, "voz": voice, "taxa_hz": int(sr), "carga_s": round(load, 1), "geracao_s": round(gen, 1),
           "fala_s": round(speech, 1), "audio_s": round(len(audio) / sr, 1), "geracao_por_s_de_fala": round(gen / speech, 2),
           "vram_gb": peak.done()}
    (RAW / f"{engine}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(out, ensure_ascii=False))


def blind():
    """Sorteia as letras das amostras cegas. A chave fica em chave.json, para abrir só depois da escolha."""
    engines = sorted(p.stem for p in RAW.glob("*.json"))  # um motor medido = um .json
    order = engines[:]
    for i in range(len(order) - 1, 0, -1):  # Fisher–Yates com secrets: sorteio de verdade
        j = secrets.randbelow(i + 1)
        order[i], order[j] = order[j], order[i]
    key = {}
    for letter, engine in zip("ABCDEF", order):
        shutil.copy(RAW / f"{engine}.wav", OUT / f"{letter}.wav")
        key[letter] = engine
    (OUT / "chave.json").write_text(json.dumps(key, ensure_ascii=False), "utf-8")
    print(f"{len(key)} amostras: {', '.join(f'{k}.wav' for k in key)}")


if __name__ == "__main__":
    blind() if sys.argv[1] == "cegas" else run(sys.argv[1])
