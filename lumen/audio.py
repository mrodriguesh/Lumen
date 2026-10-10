"""Preparação do áudio para transcrição: decodificação local e mudança de velocidade com preservação de tom."""
from fractions import Fraction

import av
import numpy as np
from faster_whisper import decode_audio

SR = 16000


def load(path):
    """Áudio do arquivo como float32 mono 16 kHz (decodificado localmente pelo FFmpeg do PyAV)."""
    return decode_audio(path if hasattr(path, "read") else str(path), sampling_rate=SR)


def tempo(samples, factor):
    """Muda a velocidade sem mudar o tom (filtro atempo do FFmpeg, WSOLA). factor 0.5 = metade da velocidade.

    Não usa reamostragem: reamostrar para desacelerar abaixa o tom e piora o reconhecimento.
    """
    if factor == 1:
        return samples
    graph = av.filter.Graph()
    src = graph.add_abuffer(format="flt", sample_rate=SR, layout="mono", time_base=Fraction(1, SR))
    node = src
    f = factor
    while f < 0.5 or f > 2:  # atempo aceita 0.5–2 por estágio; encadeia se preciso
        step = 0.5 if f < 0.5 else 2.0
        nxt = graph.add("atempo", str(step))
        node.link_to(nxt)
        node, f = nxt, f / step
    last = graph.add("atempo", str(f))
    node.link_to(last)
    sink = graph.add("abuffersink")
    last.link_to(sink)
    graph.configure()

    out = []

    def drain():
        while True:
            try:
                out.append(graph.pull().to_ndarray().reshape(-1))
            except (av.error.BlockingIOError, av.error.EOFError):
                return

    block = SR  # 1 s por quadro
    for i in range(0, len(samples), block):
        chunk = np.ascontiguousarray(samples[i:i + block], dtype=np.float32).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(chunk, format="flt", layout="mono")
        frame.sample_rate = SR
        frame.pts = i
        frame.time_base = Fraction(1, SR)
        graph.push(frame)
        drain()
    graph.push(None)
    drain()
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)
