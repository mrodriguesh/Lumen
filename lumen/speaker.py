"""Consistência de locutor para o filtro de música (lumen/music.py): quem fala na aula, para não confundir com quem
canta ou faz rap na música ao fundo.

Só uma representação técnica da voz (embedding do ResNet34 do WeSpeaker), calculada e comparada dentro de UMA aula: não identifica
ninguém, não é comparada com outras aulas nem usada para nada fora do filtro. Fica só na memória durante o filtro;
o que vai para o cache da aula (music-<chave>.json) são as similaridades, nunca o embedding."""
import numpy as np

from . import audio

# ResNet34-LM do WeSpeaker (VoxCeleb, CC-BY-4.0): 26 MB em ONNX, entrada fbank 80 × T, saída 256. O CAM++ do
# WeSpeaker em ONNX foi testado e descartado: com as mesmas características, não separava 16 palestrantes (EER 27%,
# contra 0% deste; bench/music_bench.py).
MODEL = ("Wespeaker/wespeaker-voxceleb-resnet34-LM", "f0c48c298fd835726c27956a5d617bad7115627e", "voxceleb_resnet34_LM.onnx")
VERSION = 1
# Medido em 16 palestras do CORAA (janelas de 3 s, referência de 8 janelas): mesmo palestrante, mediana 0,76 (5%:
# 0,58); outro, mediana 0,26 (95%: 0,47). Sob música, na voz separada, o próprio professor cai para mediana 0,40
# (5%: 0,09) e cantores e rappers ficam em 0,14–0,18 (95%: 0,26–0,30): similaridade alta é prova de professor,
# similaridade baixa não prova nada sozinha.
CLUSTER_SIM = 0.35  # grupos de janelas acima disto (média) são o mesmo locutor. Entre janelas de 3 s do mesmo
                    # palestrante, 5% ficam abaixo de 0,14 (risos, plateia): um professor pode virar 2 grupos, o que
                    # não atrapalha; dois professores diferentes nunca viraram um (16 palestras, 8 pares)
ENROLL_MAX = 40     # janelas de referência por aula (espalhadas): o agrupamento cresce com n³
_banks = None


def _mel_banks(n_fft=512, bins=80, low=20.0):
    """Filtros mel do Kaldi (torchaudio.compliance.kaldi.get_mel_banks), com a coluna de Nyquist zerada."""
    mel = lambda f: 1127.0 * np.log(1.0 + f / 700.0)
    lo, hi = mel(low), mel(audio.SR / 2)
    delta = (hi - lo) / (bins + 1)
    m = mel(audio.SR / n_fft * np.arange(n_fft // 2))
    left = lo + np.arange(bins)[:, None] * delta
    up, down = (m - left) / delta, (left + 2 * delta - m) / delta
    return np.pad(np.maximum(0, np.minimum(up, down)), ((0, 0), (0, 1))).astype(np.float32)


def fbank(x):
    """fbank de 80 bandas como o Kaldi (25 ms, passo 10 ms, Hamming, pré-ênfase 0,97, sem dither), com a média de
    cada banda subtraída (CMN), como o WeSpeaker faz antes do modelo."""
    global _banks
    if _banks is None:
        _banks = _mel_banks()
    x = np.asarray(x, np.float32) * 32768
    if len(x) < 400:
        x = np.pad(x, (0, 400 - len(x)))
    f = np.lib.stride_tricks.sliding_window_view(x, 400)[::160].astype(np.float32)
    f = f - f.mean(1, keepdims=True)
    f = np.concatenate([f[:, :1] * 0.03, f[:, 1:] - 0.97 * f[:, :-1]], 1)
    f = f * np.hamming(400).astype(np.float32)
    p = np.abs(np.fft.rfft(f, 512)) ** 2
    e = np.log(np.maximum(p @ _banks.T, np.finfo(np.float32).eps)).astype(np.float32)
    return e - e.mean(0)


def embed(run, x):
    """Embedding (256, norma 1) de um trecho de voz mono 16 kHz; run(feats) roda o modelo (music._run: GPU ou CPU)."""
    v = run(fbank(x)[None])[0]
    return v / (np.linalg.norm(v) + 1e-9)


def cluster(embs, weights, threshold):
    """Agrupa embeddings por similaridade (cosseno, ligação média): [(centróide, peso)] do maior para o menor. Aulas
    com dois professores, entrevista ou pergunta de aluno dão mais de um grupo; nenhum é descartado aqui."""
    groups = [[i] for i in range(len(embs))]
    sim = embs @ embs.T
    while len(groups) > 1:
        best, pair = -2.0, None
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                s = sim[np.ix_(groups[a], groups[b])].mean()
                if s > best:
                    best, pair = s, (a, b)
        if best < threshold:
            break
        a, b = pair
        groups[a] += groups.pop(b)
    out = []
    for g in groups:
        c = embs[g].mean(0)
        out.append((c / (np.linalg.norm(c) + 1e-9), float(np.sum(np.asarray(weights)[g]))))
    return sorted(out, key=lambda t: -t[1])


def similarity(e, speakers):
    """Similaridade com o locutor da aula mais parecido (−1 a 1); None sem referência."""
    return max(float(e @ c) for c, _ in speakers) if speakers else None
