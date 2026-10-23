"""Filtro de música externa (lumen/music.py): dados, sonda fala × letra e transcrição antes/depois do filtro.

    python -m bench.music_bench fetch     # MUSDB18 trechos de 7 s (sigsep/Zenodo, 147 MB) em bench/.data/musdb7
    python -m bench.music_bench train     # treina a sonda fala × letra → lumen/music_probe.json
    python -m bench.music_bench run       # WER sem e com o filtro, por cenário e volume → bench/results/music.json
    python -m bench.music_bench perf      # tempo, CPU, RAM e disco numa aula de 10 min → bench/results/music_perf.json
    python -m bench.music_bench report    # bench/RESULTADOS_MUSICA.md

Fala: FLEURS/CORAA de bench/asr_bench (rode antes `asr_bench fetch` e `build`). Música: MUSDB18 (mistura, voz e
instrumental de cada faixa) e música sintética (piano, eletrônica). Treino e teste não compartilham faixas nem falas:
MUSDB train + falas A treinam a sonda; MUSDB test + falas B medem tudo. Nada disso vai para o Git.
"""
import json
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from bench import metrics

ROOT = Path(__file__).parent
DATA = ROOT / ".data"
MUSDB = DATA / "musdb7"
SR = 16000
MUSDB_URL = "https://zenodo.org/records/3270814/files/MUSDB18-7-STEMS.zip?download=1"


LESSONS = DATA / "lessons"  # “aulas”: falas seguidas do mesmo palestrante (CORAA, TEDx)
GTZAN = DATA / "gtzan"
GTZAN_URL = "https://huggingface.co/datasets/marsyas/gtzan/resolve/main/data/genres.tar.gz"
# clipes de 30 s guardados por gênero (o pacote tem 100 de cada; hip-hop e clássica inteiros: treino 0–49, teste 50–99)
GENRES = {"hiphop": 100, "classical": 100, "rock": 20, "pop": 20, "jazz": 20, "reggae": 20, "country": 20,
          "metal": 10, "blues": 10, "disco": 10}


def fetch():
    MUSDB.mkdir(parents=True, exist_ok=True)
    z = MUSDB / "MUSDB18-7-STEMS.zip"
    if not z.exists():
        urllib.request.urlretrieve(MUSDB_URL, z)
    with zipfile.ZipFile(z) as f:
        f.extractall(MUSDB)
    fetch_lessons()
    fetch_gtzan()


def fetch_lessons(per_talk=30):
    """CORAA v1.1, TEDx pt-BR: as 7 palestras do dev e 9 do test (o train só existe em .rar), 30 trechos seguidos de cada (≈ 3 min por
    palestrante), lidos por Range dos zips (só os trechos usados). Um palestrante por palestra."""
    import csv
    import io
    from bench.asr_bench import CORAA, HttpFile, _get, _load, _save_wav
    if (LESSONS / "lessons.json").exists():
        return
    LESSONS.mkdir(parents=True, exist_ok=True)
    out = []
    for split, n_talks in (("dev", 7), ("test", 9)):
        meta = list(csv.DictReader(io.StringIO(_get(CORAA + f"metadata_{split}_final.csv").decode("utf-8"))))
        talks = {}
        for m in meta:
            if m["dataset"] == "TEDx Talks" and m["variety"] == "pt_br" and len(m["text"].split()) >= 4:
                talks.setdefault(Path(m["file_path"]).stem.rsplit("-", 1)[0], []).append(m)
        picked = sorted(t for t, rows in talks.items() if len(rows) >= per_talk)[:n_talks]
        z = zipfile.ZipFile(io.BufferedReader(HttpFile(CORAA + f"{split}.zip"), buffer_size=1 << 20))
        names = {n.replace("\\", "/").split(f"{split}/", 1)[-1]: n for n in z.namelist()}
        for t in picked:
            rows = sorted(talks[t], key=lambda m: m["file_path"])[:per_talk]
            for m in rows:
                key = m["file_path"].replace("\\", "/").split(f"{split}/", 1)[-1]
                p = LESSONS / f"{Path(key).stem}.wav"
                if not p.exists():
                    _save_wav(p, _load(io.BytesIO(z.read(names[key]))))
                out.append({"talk": t, "split": split, "path": str(p), "ref": m["text"]})
            print("palestra", t, flush=True)
    (LESSONS / "lessons.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")


def fetch_gtzan():
    """GTZAN (Tzanetakis & Cook, 2002): lê o pacote de 1,2 GB em fluxo e guarda só os clipes de GENRES."""
    import tarfile
    if (GTZAN / "done").exists():
        return
    GTZAN.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(GTZAN_URL, timeout=120) as r, tarfile.open(fileobj=r, mode="r|gz") as tar:
        for m in tar:
            name = Path(m.name).name  # genres/hiphop/hiphop.00012.wav
            genre, _, idx = name.partition(".")
            if m.isfile() and genre in GENRES and idx[:5].isdigit() and int(idx[:5]) < GENRES[genre]:
                (GTZAN / name).write_bytes(tar.extractfile(m).read())
    (GTZAN / "done").write_text("ok")


CHOIR = DATA / "choir"
CHOIR_URL = "https://huggingface.co/datasets/Emulated-Inc/satb-choir-voice-f0/resolve/main/"


def fetch_choir():
    """Coral (Cantoría, Choral Singing Dataset; CC-BY-4.0): as 5 mixagens SATB do dev, lidas em fluxo dos tars do
    espelho no Hugging Face (o Zenodo recusou o acesso) e conferidas pelo SHA-256 de members.csv."""
    import csv
    import hashlib
    import io
    import tarfile
    if len(list(CHOIR.glob("*.wav"))) >= 5:
        return
    CHOIR.mkdir(parents=True, exist_ok=True)
    rows = csv.DictReader(io.StringIO(urllib.request.urlopen(CHOIR_URL + "members.csv", timeout=60).read().decode()))
    want = {r["file"]: r["sha256"] for r in rows if r["file"].startswith("dev/") and r["file"].endswith(".wav")}
    for part in ("members-001.tar", "members-000.tar"):
        with urllib.request.urlopen(CHOIR_URL + part, timeout=120) as r, tarfile.open(fileobj=r, mode="r|") as tar:
            for m in tar:
                name = m.name.replace("\\", "/").lstrip("./")
                if name in want:
                    data = tar.extractfile(m).read()
                    if hashlib.sha256(data).hexdigest() == want[name]:
                        (CHOIR / Path(name).name).write_bytes(data)
        if len(list(CHOIR.glob("*.wav"))) >= len(want):
            break


def gtzan(genre, part=None):
    """{nome: mono 16 kHz} de um gênero; part "train" = clipes 0–49, "test" = 50–99 (hip-hop e clássica)."""
    from lumen import audio
    out = {}
    for p in sorted(GTZAN.glob(f"{genre}.*.wav")):
        i = int(p.stem.split(".")[1])
        if part and (i < 50) != (part == "train"):
            continue
        try:
            out[p.stem] = audio.load(p)
        except Exception:  # noqa: BLE001 — o GTZAN tem um clipe corrompido (jazz.00054)
            pass
    return out


def _decode(path):
    """Cada faixa .stem.mp4 → [mistura, bateria, baixo, outros, voz] mono 16 kHz."""
    import av
    out = []
    with av.open(str(path)) as c:
        n = len(c.streams.audio)
    for k in range(n):
        with av.open(str(path)) as c:
            r = av.AudioResampler(format="flt", layout="mono", rate=SR)
            buf = []
            for f in c.decode(c.streams.audio[k]):
                buf += [o.to_ndarray().reshape(-1) for o in r.resample(f)]
            buf += [o.to_ndarray().reshape(-1) for o in r.resample(None)]
            out.append(np.concatenate(buf))
    m = min(len(v) for v in out)
    return np.stack([v[:m] for v in out])


def tracks(split):
    """{nome: stems} de uma divisão do MUSDB (train/test), com cache em .npy."""
    cache = MUSDB / "npz"
    cache.mkdir(exist_ok=True)
    out = {}
    for p in sorted((MUSDB / split).glob("*.stem.mp4")):
        name = p.name[:-9]
        f = cache / f"{split}__{name}.npy"
        if not f.exists():
            np.save(f, _decode(p))
        out[name] = np.load(f)
    return out


def speech(part):
    """Falas com transcrição humana. A: treino da sonda. B: medições."""
    from lumen import audio
    man = json.loads((DATA / "manifest_full.json").read_text("utf-8"))
    by = lambda s: [i for i in man if i["set"] == s]
    items = (by("leitura")[40:60] + by("palestra")[40:50] + by("conversa")[40:50] if part == "A"
             else by("leitura")[60:80] + by("palestra")[50:60] + by("conversa")[50:60])
    return [{**i, "x": audio.load(i["path"])} for i in items]


def loop(m, n):
    return np.tile(m, -(-n // len(m)))[:n].astype(np.float32)


def level(x):
    """Potência dos trechos ativos (a fala tem pausas; a média de tudo subestimaria a fala)."""
    a = x[np.abs(x) > 0.02 * (np.abs(x).max() + 1e-9)]
    return float(np.mean(a ** 2)) if len(a) else 1e-12


def mix(s, m, off_db):
    """Fala + música com a música `off_db` dB acima (+) ou abaixo (−) da fala; pico limitado a 0,99."""
    y = s + m * np.sqrt(level(s) * 10 ** (off_db / 10) / level(m))
    return (y / max(1.0, np.abs(y).max() / 0.99)).astype(np.float32)


# ---------------------------------------------------------------- sonda fala × letra

def _clips(part, split):
    """Clipes da sonda com as saídas do YAMNet (mistura e voz separada), o ritmo da voz (music.rhythm) e o rótulo de
    cada quadro: 1 = fala da aula (com ou sem música), 0 = só música (inclusive letra, canto e rap), −1 = ambíguo
    (fica fora da conta). Música: MUSDB18 e, desde a v2, hip-hop e clássica do GTZAN (A: clipes 0–49, B: 50–99).
    Separar é o que demora: o resultado fica em cache em bench/.data."""
    from lumen import music
    cache = DATA / f"music_clips2_{part}.npz"
    keys = ("d_emb", "d_speech", "d_music", "v_emb", "v_speech", "rh", "label")
    if not cache.exists():
        rnd = np.random.default_rng(7 if part == "A" else 8)
        mus = list(tracks(split).items())
        hh, cl = list(gtzan("hiphop", split).values()), list(gtzan("classical", split).values())
        rows, kinds = [], []

        def add(x, label, kind):
            v = music.separate(x)
            d, dv = music.detect(x), music.detect(v)
            rows.append((d["emb"], d["speech"], d["music"], dv["emb"], dv["speech"],
                         music.rhythm(v, x, np.ones(len(d["speech"]), bool)), label))
            kinds.append(kind)
        for k, it in enumerate(speech(part)):
            s = it["x"]
            clean = music.detect(s)["speech"]
            label = np.where(clean > 0.5, 1, np.where(clean < 0.1, 0, -1))
            for kind, off in [("inst", int(rnd.choice([-10, -5, 0, 5, 10]))), ("vocal", int(rnd.choice([-10, -5, 0, 5, 10]))),
                              ("vocal", int(rnd.choice([0, 5, 10])))]:
                st = mus[int(rnd.integers(len(mus)))][1]
                add(mix(s, loop(st[0] - st[4] if kind == "inst" else st[0], len(s)), off), label, "fala+musdb")
            for kind, pool in (("fala+rap", hh), ("fala+clássica", cl)):
                m = pool[int(rnd.integers(len(pool)))]
                add(mix(s, loop(m[int(rnd.integers(0, len(m) // 2)):], len(s)), int(rnd.choice([-5, 0, 5, 10]))),
                    label, kind)
            print(f"fala {k + 1}/40", flush=True)
        for j, (name, st) in enumerate(mus):
            for m in ([st[0], st[4]] if j % 2 else [st[0]]):  # mistura (com letra) e, em metade, a voz sozinha
                x = loop(m, len(m))
                add(x, np.zeros(-(-len(x) // music.HOP), int), "musdb")
        for kind, pool in (("rap", hh), ("clássica", cl)):
            for m in pool:
                x = m[:20 * SR]
                add(x, np.zeros(-(-len(x) // music.HOP), int), kind)
        np.savez(cache, n=[len(r[6]) for r in rows], kind=kinds,
                 **{k: np.concatenate([r[i] for r in rows]).astype(np.float32) for i, k in enumerate(keys)})
    z = np.load(cache)
    cut = np.cumsum(z["n"])[:-1]
    cols = {k: np.split(z[k], cut) for k in keys}
    return [{"d": {"emb": cols["d_emb"][i], "speech": cols["d_speech"][i], "music": cols["d_music"][i]},
             "v": {"emb": cols["v_emb"][i], "speech": cols["v_speech"][i]}, "rh": cols["rh"][i],
             "label": cols["label"][i].astype(int), "kind": str(z["kind"][i])} for i in range(len(z["n"]))]


def _xy(clips, feats):
    X = np.concatenate([feats(c) for c in clips])
    y = np.concatenate([c["label"] for c in clips])
    return X[y >= 0].astype(np.float32), y[y >= 0].astype(np.float32)


def _fit(X, y, l2=1e-3, iters=800, lr=0.3):
    """Regressão logística (numpy) com classes balanceadas; pesos já desfazem a padronização."""
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = (X - mu) / sd
    w, b = np.zeros(Z.shape[1]), 0.0
    cw = np.where(y == 1, 0.5 / y.mean(), 0.5 / (1 - y.mean()))
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        r = (p - y) * cw
        w -= lr * (Z.T @ r / len(y) + l2 * w)
        b -= lr * r.mean()
    return w / sd, b - float(np.sum(w * mu / sd))


def _auc(p, y):
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def _decisions(clips, w, b, feats):
    """Com a regra do app (music.decide), por limiar de silêncio: quanto da fala some e quanto da música sozinha sai."""
    from lumen import music
    out = {}
    for t in (0.2, 0.3, 0.35, 0.4, 0.45, 0.5):
        lost = speech = gone = total = 0
        for c in clips:
            p = 1 / (1 + np.exp(-np.clip(feats(c) @ w + b, -30, 30)))
            _, region = music.regions(c["d"], music.MODES[music.MODE])
            m = music.decide(p, np.zeros(len(p)), region, dict(music.MODES["agressivo"], mute=t))  # só o silêncio
            if c["kind"].startswith("fala"):
                lost += int((m["mute"] & (c["label"] == 1)).sum())
                speech += int((c["label"] == 1).sum())
            else:
                gone += int(m["mute"].sum())
                total += len(m["mute"])
        out[f"{t:.2f}"] = {"fala_silenciada": lost / max(speech, 1), "musica_silenciada": gone / max(total, 1)}
    return out


def _rates(clips, feats, w, b, keep=0.6):
    """Com a média da decisão (±5 quadros) e o limiar keep: fração dos quadros de música sozinha que passariam por
    fala (letra sem marca) e da fala que fica “com certeza” (não é marcada)."""
    from lumen import music
    sig = lambda z: 1 / (1 + np.exp(-np.clip(z, -30, 30)))
    hi = lambda c: music._near(sig(feats(c) @ w + b), music.WINDOW, np.mean) >= keep
    out = {k: float(np.mean(np.concatenate([hi(c) for c in clips if c["kind"] == k]))) for k in ("musdb", "rap", "clássica")}
    out["fala"] = float(np.mean(np.concatenate([hi(c)[c["label"] == 1] for c in clips if c["kind"].startswith("fala")])))
    return out


def train():
    """Retreina a sonda (regressão logística sobre os embeddings congelados do YAMNet; nada do YAMNet é treinado).
    Compara, no mesmo teste (falas B, MUSDB test, GTZAN 50–99), a sonda da v1 com a nova; grava a nova.

    Testado em 20/10/2026 (docs/DECISOES.md): l2 = 0,03–0,3 e o MUSDB com peso 1 deram AUC até 0,935, mas
    calibração ruim (até 70% dos quadros de música cantada acima do limiar de fala: a letra passaria sem marca).
    Ficou l2 = 0,01, MUSDB com peso 2, e o viés ajustado NO TREINO para a música cantada passar em ≤ 3,5% dos quadros
    (a v1 passava 4,5% no teste)."""
    from lumen import music
    A, B = _clips("A", "train"), _clips("B", "test")
    old = json.loads((DATA / "music_probe_v1.json").read_text("utf-8"))  # cópia da sonda da v1 (antes de retreinar)
    feats = lambda c: music.features(c["v"], c["d"], c["rh"])
    data = A + [c for c in A if c["kind"] in ("musdb", "fala+musdb")]
    Xa, ya = _xy(data, feats)
    w, b = _fit(Xa, ya, l2=1e-2)
    shift = next(d for d in np.arange(0, -4.01, -0.25) if _rates(A, feats, w, b + d)["musdb"] <= 0.035)
    b += float(shift)
    res = {}
    for name, (ww, bb) in {"sonda da v1": (np.concatenate([old["w"], [0, 0]]), old["b"]), "sonda da v2": (w, b)}.items():
        Xb, yb = _xy(B, feats)
        r = {"auc": _auc(1 / (1 + np.exp(-np.clip(Xb @ ww + bb, -30, 30))), yb), "por_tipo": {}}
        for ks, km in (("fala+musdb", "musdb"), ("fala+rap", "rap"), ("fala+clássica", "clássica")):
            Xs, ys = _xy([c for c in B if c["kind"] in (ks, km)], feats)
            r["por_tipo"][ks] = _auc(1 / (1 + np.exp(-np.clip(Xs @ ww + bb, -30, 30))), ys)
        r["acima_do_limiar"] = _rates(B, feats, ww, bb)
        res[name] = r
        print(f"{name}: AUC {r['auc']:.3f} | " + " ".join(f"{k} {v:.3f}" for k, v in r["por_tipo"].items()) +
              " | acima de 0,6: " + " ".join(f"{k} {v:.1%}" for k, v in r["acima_do_limiar"].items()), flush=True)
    probe = {"features": "music.features: embeddings do YAMNet da voz separada + da mistura + ritmo (2)",
             "b": round(float(b), 6), "w": [round(float(v), 6) for v in w], "bias_shift": float(shift),
             "test": {k: {"auc": round(r["auc"], 4), "por_tipo": {t: round(a, 4) for t, a in r["por_tipo"].items()},
                          "acima_do_limiar": {t: round(a, 4) for t, a in r["acima_do_limiar"].items()}}
                      for k, r in res.items()},
             "data": "treino: MUSDB18-7 train (peso 2) + GTZAN hip-hop/clássica 0–49 + FLEURS/CORAA A; teste: MUSDB18-7 "
                     "test + GTZAN 50–99 + falas B (bench/music_bench.py)"}
    (ROOT.parent / "lumen" / "music_probe.json").write_text(json.dumps(probe, ensure_ascii=False), "utf-8")


# ---------------------------------------------------------------- transcrição sem × com o filtro

ASR = "large-v3-turbo"  # o modelo do modo Equilibrado com GPU (lumen/transcribe.py)
RAP = ("M.E.R.C. Music - Knockout",)  # o rap com voz audível nos trechos de teste do MUSDB (os do PR quase não têm voz)
ACOUSTIC = ("Cristina Vane - So Easy", "Lyndsey Ollard - Catching Up", "Speak Softly - Like Horses")
ELECTRONIC = ("Skelpolu - Resurrection", "Raft Monk - Tiring", "The Easton Ellises - Falcon 69")


CACHE = DATA / "music_cache"  # ASR e separação são determinísticos: o mesmo áudio não é processado de novo


def _digest(x):
    import hashlib
    return hashlib.sha256(np.ascontiguousarray(x, dtype=np.float32).tobytes()).hexdigest()[:20]


def asr(x):
    """Trechos como o app transcreve (mesmo modelo e opções de lumen/transcribe.py), com a confiança do ASR."""
    from lumen import transcribe
    f = CACHE / f"asr_{ASR}_{_digest(x)}.json"
    if f.exists():
        return json.loads(f.read_text("utf-8"))
    model = transcribe._model(ASR, "cuda" if transcribe.has_gpu() else "cpu")
    segs = [{"start": s.start, "end": s.end, "text": s.text.strip(), "lp": s.avg_logprob}
            for s, _ in transcribe._segments(model, x, lambda: None)]
    segs = [s for s in segs if s["text"]]
    CACHE.mkdir(exist_ok=True)
    f.write_text(json.dumps(segs, ensure_ascii=False), "utf-8")
    return segs


def _cached_separate():
    from lumen import music
    real = music.separate

    def separate(x, check=lambda: None):
        f = CACHE / f"sep_{music.SEPARATOR[2]}_{_digest(x)}.npy"
        if f.exists():
            return np.load(f)
        v = real(x, check)
        CACHE.mkdir(exist_ok=True)
        np.save(f, v)
        return v
    music.separate = separate


def _lyrics_words(voice):
    """A letra, aproximada: as palavras que o ASR ouve na voz da música sozinha. Na transcrição da aula, palavra
    dela que não está na fala de referência é letra infiltrada."""
    return set(metrics.normalize(" ".join(s["text"] for s in asr(voice))))


def _vocal_tracks(test):
    """Faixas com voz cantada forte no trecho (voz ≥ −4 dB em relação aos instrumentos), sem o rap."""
    out = []
    for name, st in test.items():
        voc, inst = st[4], st[0] - st[4]
        if name not in RAP and 10 * np.log10(level(voc) / level(inst)) >= -4 and np.mean(np.abs(voc) > 0.01) > 0.5:
            out.append(name)
    return out


def _synth(kind, n, rnd):
    """Música e ruídos sintéticos: piano, eletrônica, ventilador, teclado."""
    t = np.arange(n) / SR
    out = np.zeros(n, np.float32)
    if kind == "piano":
        notes = 261.63 * 2 ** (np.array([0, 2, 4, 5, 7, 9, 11, 12]) / 12)
        for k in range(0, n, SR // 2):
            for f in rnd.choice(notes, 2):
                seg = slice(k, min(n, k + SR * 2))
                tt = t[seg] - t[k]
                out[seg] += sum(np.sin(2 * np.pi * f * h * tt) / h ** 1.5 for h in (1, 2, 3, 4)) * np.exp(-2.5 * tt)
    elif kind == "electro":
        beat = int(SR * 0.5)
        for k in range(0, n, beat):
            seg = slice(k, min(n, k + beat))
            tt = t[seg] - t[k]
            out[seg] += np.sin(2 * np.pi * (40 + 80 * np.exp(-30 * tt)) * tt) * np.exp(-8 * tt)  # bumbo
            out[seg] += 0.3 * (2 * ((55 * 2 ** ((k // beat) % 4 / 12) * t[seg]) % 1) - 1)    # baixo serrote
            hat = slice(k + beat // 2, min(n, k + beat // 2 + 800))
            out[hat] += 0.2 * rnd.standard_normal(len(out[hat])) * np.exp(-np.arange(len(out[hat])) / 150)
    elif kind == "fan":
        out = np.cumsum(rnd.standard_normal(n)).astype(np.float32)
        out -= np.convolve(out, np.ones(800) / 800, "same")
        out += 0.3 * np.sin(2 * np.pi * 120 * t) * np.abs(out).mean()
    elif kind == "keyboard":
        for k in np.cumsum(rnd.integers(SR // 12, SR // 4, n // (SR // 12))):
            if k + 400 < n:
                out[k:k + 400] += rnd.standard_normal(400) * np.exp(-np.arange(400) / 60)
    return (out / (np.abs(out).max() + 1e-9)).astype(np.float32)


def _gate(n, rnd, on=(6, 10), off=(4, 8)):
    """Música começando e parando: 1 onde toca, com 50 ms de rampa."""
    g, i, playing = np.zeros(n, np.float32), 0, True
    while i < n:
        k = int(rnd.uniform(*(on if playing else off)) * SR)
        g[i:i + k] = playing
        i, playing = i + k, not playing
    r = np.ones(800, np.float32) / 800
    return np.convolve(g, r, "same")


def _join(items, pause=0.7):
    gap = np.zeros(int(pause * SR), np.float32)
    return np.concatenate([p for i in items for p in (i["x"], gap)]), " ".join(i["ref"] for i in items)


def _case(name, x, ref, lyrics=frozenset(), mode=None, **extra):
    from lumen import music
    before = asr(x)
    t = time.perf_counter()
    y, rep = music.clean(x, mode=mode or music.MODE)
    took = time.perf_counter() - t
    after = music.mark([dict(s) for s in asr(y)] if rep["filtered"] else [dict(s) for s in before], rep)
    refw = set(metrics.normalize(ref))
    out = {"case": name, **extra, "mode": mode or music.MODE, "dur": round(len(x) / SR, 1), "filter_s": round(took, 2),
           "rep": {k: v for k, v in rep.items() if not isinstance(v, list)}}
    for tag, segs in (("before", before), ("after", after)):
        text = " ".join(s["text"] for s in segs)
        words = metrics.normalize(text)
        lyr = lambda ws: sum(1 for w in ws if w in lyrics and w not in refw)
        free = [w for s in segs if not s.get("music") for w in metrics.normalize(s["text"])]
        flagged = [w for s in segs if s.get("music") for w in metrics.normalize(s["text"])]
        out[tag] = {"score": metrics.score(ref, text) if ref else None, "words": len(words),
                    "lyrics": lyr(words), "lyrics_free": lyr(free),  # letra que chega à IA sem marca
                    "ref_flagged": sum(1 for w in flagged if w in refw),  # fala da aula marcada como dúvida
                    "conf": round(float(np.mean([s["lp"] for s in segs])), 3) if segs else None,
                    "flagged": sum(1 for s in segs if s.get("music"))}
    return out


def run():
    from lumen import audio, music
    _cached_separate()  # o tempo do filtro por caso fica sem sentido; o desempenho é medido em perf()
    rnd = np.random.default_rng(11)
    sp = speech("B")
    test = tracks("test")
    vocal = _vocal_tracks(test)
    lyr = {}

    def lyrics(name):
        if name not in lyr:
            lyr[name] = _lyrics_words(test[name][4])
        return lyr[name]

    def track(name, kind):
        st = test[name]
        return st[0] - st[4] if kind == "inst" else st[0]

    res, t0 = [], time.time()

    def add(r):
        res.append(r)
        b, a = r["before"], r["after"]
        w = lambda s: f"{s['score']['S'] + s['score']['D'] + s['score']['I']}/{s['score']['N']}" if s["score"] else "-"
        print(f"[{time.time() - t0:5.0f}s] {r['case']:28} {str(r.get('off', '')):>4} erros {w(b):>7} → {w(a):>7} | "
              f"letra {b['lyrics']:3} → {a['lyrics']:3} | palavras {b['words']:3} → {a['words']:3} | "
              f"música {r['rep']['music_s']:5.1f}s removido {r['rep']['removed_s']:5.1f}s", flush=True)

    # 1. só fala (vozes femininas e masculinas, leitura, palestra e conversa espontânea com sotaques)
    for it in sp[:20]:
        add(_case("1 fala sozinha", it["x"], it["ref"], gender=it.get("gender"), set=it["set"]))
    # 2. só música: letra cantada e rap
    for name in vocal[:10] + list(RAP):
        x = loop(test[name][0], 20 * SR)
        add(_case("2 música sozinha" + (" (rap)" if name in RAP else ""), x, "", lyrics(name), track=name))
    # 3–6 e volumes: música −15 a +15 dB em relação à fala
    sub = sp[:10]
    for kind in ("inst", "vocal"):
        names = list(test) if kind == "inst" else vocal
        for off in (-15, -10, -5, 0, 5, 10, 15):
            for k, it in enumerate(sub):
                name = names[(k * 3 + off) % len(names)]
                x = mix(it["x"], loop(track(name, kind), len(it["x"])), off)
                add(_case(f"volume {kind}", x, it["ref"], lyrics(name) if kind == "vocal" else frozenset(),
                          off=off, track=name))
    for k, it in enumerate(sub):  # 6. professor + rap
        for off in (-5, 0, 5):
            name = RAP[0]
            add(_case("6 fala + rap", mix(it["x"], loop(track(name, "vocal"), len(it["x"])), off), it["ref"], lyrics(name),
                      off=off, track=name))
    # 7. música começando e parando várias vezes (com trechos só de música entre as falas)
    for k in range(3):
        s, ref = _join(sp[10 + 6 * k:16 + 6 * k], pause=4.0)
        name = vocal[k % len(vocal)]
        g = _gate(len(s), rnd)
        x = mix(s, loop(track(name, "vocal"), len(s)) * g, 0)
        d = music.detect(x)
        truth = g[::music.HOP][:len(d["music"])] > 0.5
        hit = float(np.mean((music._near(d["music"], 2, np.median) >= music.MODES[music.MODE]["music_on"])[:len(truth)] == truth))
        add(_case("7 música liga e desliga", x, ref, lyrics(name), track=name, tracking=round(hit, 3),
                  music_true_s=round(float(g.sum() / SR), 1)))
    # 8. silêncio
    for k in range(3):
        x = np.concatenate([np.zeros(10 * SR), rnd.standard_normal(10 * SR) * 10 ** (-70 / 20)]).astype(np.float32)
        add(_case("8 silêncio", x, ""))
    # 9. ruído ambiente: ventilador, teclado, pessoas conversando ao fundo
    babble = speech("A")
    for k, it in enumerate(sub):
        n = len(it["x"])
        for kind in ("fan", "keyboard", "babble"):
            if kind == "babble":
                noise = sum(loop(babble[(k * 3 + j) % len(babble)]["x"], n) for j in range(3))
            else:
                noise = _synth(kind, n, rnd)
            add(_case(f"9 ruído: {kind}", mix(it["x"], noise, -10), it["ref"], noise=kind))
    # 10. trilha do próprio vídeo: vinheta instrumental de abertura e trilha baixa embaixo da fala
    for k in range(3):
        s, ref = _join(sp[20 + 5 * k:25 + 5 * k])
        name = list(test)[(k * 7) % len(test)]
        bed = mix(s, loop(track(name, "inst"), len(s)), -18)
        intro = loop(track(name, "inst"), 6 * SR) * np.sqrt(level(s) / level(track(name, "inst")))
        add(_case("10 trilha do vídeo", np.concatenate([intro, bed]).astype(np.float32), ref, track=name))
    # 27. tentar quebrar: piano, eletrônica, violão, música que liga e desliga rápido
    for k, it in enumerate(sub[:6]):
        n = len(it["x"])
        for kind in ("piano", "electro"):
            for off in (0, 10):
                add(_case(f"27 {kind} sintético", mix(it["x"], _synth(kind, n, rnd), off), it["ref"], off=off))
        for names, label in ((ACOUSTIC, "violão/acústica"), (ELECTRONIC, "eletrônica real")):
            name = names[k % len(names)]
            add(_case(f"27 {label}", mix(it["x"], loop(track(name, "inst"), n), 0), it["ref"], off=0, track=name))
        name = vocal[k % len(vocal)]
        g = _gate(n, rnd, on=(1.5, 2.5), off=(1.5, 2.5))
        add(_case("27 música liga/desliga rápido", mix(it["x"], loop(track(name, "vocal"), n) * g, 0), it["ref"],
                  lyrics(name), off=0, track=name))
        fast = audio.tempo(it["x"], 2.0)  # aula gravada já acelerada (a sonda só viu fala em velocidade normal)
        add(_case("27 fala 2× + música", mix(fast, loop(track(name, "vocal"), len(fast)), 0), it["ref"], lyrics(name),
                  off=0, track=name))
    out = ROOT / "results" / "music.json"
    out.write_text(json.dumps({"asr": ASR, "separator": music.SEPARATOR[2], "detector": music.DETECTOR[2],
                               "mode": music.MODE, "cases": res}, ensure_ascii=False, indent=1), "utf-8")
    print("salvo em", out)


# ---------------------------------------------------------------- conjunto de validação v2 (aulas com professor)

def _talks():
    """{palestra: [falas na ordem]}: cada palestra é um “professor” (mesma voz do começo ao fim)."""
    out = {}
    for i in json.loads((LESSONS / "lessons.json").read_text("utf-8")):
        out.setdefault(i["talk"], []).append(i)
    return out


def _speech(items, seconds, pause=0.7):
    """Falas seguidas (com `pause` s entre elas) até `seconds`: (áudio, referência)."""
    from lumen import audio
    xs, refs, n = [], [], 0
    for i in items:
        x = audio.load(i["path"])
        xs += [x, np.zeros(int(pause * SR), np.float32)]
        refs.append(i["ref"])
        n += len(x) + int(pause * SR)
        if n >= seconds * SR:
            break
    return np.concatenate(xs), " ".join(refs)


def _bed(m, n, start=0.0, end=None):
    """Música (em loop) tocando de `start` a `end` segundos de um áudio de n amostras, com 50 ms de rampa."""
    g = np.zeros(n, np.float32)
    g[int(start * SR):n if end is None else int(end * SR)] = 1
    return loop(m, n) * np.convolve(g, np.ones(800, np.float32) / 800, "same")


def _f0(x):
    """Altura mediana da voz (Hz) por autocorrelação; só para rotular voz feminina/masculina no relatório."""
    f = np.lib.stride_tricks.sliding_window_view(x, 640)[::320]
    f = f[np.sqrt(np.mean(f ** 2, 1)) > 0.02]
    if not len(f):
        return None
    f = f - f.mean(1, keepdims=True)
    ac = np.fft.irfft(np.abs(np.fft.rfft(f, 1280)) ** 2)[:, :640]
    lo, hi = SR // 500, SR // 70
    lag = lo + ac[:, lo:hi].argmax(1)
    ok = ac[np.arange(len(f)), lag] > 0.5 * ac[:, 0]
    return float(np.median(SR / lag[ok])) if ok.any() else None


def suite():
    """Aulas de ≈ 60 s com um “professor” (palestra do CORAA) e a música por cima, para os cenários dos pedidos:
    [(cenário, áudio, referência, letra, extras)]. Determinístico; música só do MUSDB test e do GTZAN 50–99
    (o treino da sonda usa MUSDB train e GTZAN 0–49)."""
    from lumen import audio
    talks = list(_talks().values())
    test = tracks("test")
    names, vocal = list(test), _vocal_tracks(test)
    hh, cl = gtzan("hiphop", "test"), gtzan("classical", "test")
    hh_names, cl_names = list(hh), list(cl)
    lyr = {}

    def lyrics(key, voice):
        if key not in lyr:
            lyr[key] = _lyrics_words(voice)
        return lyr[key]

    inst = lambda k: test[names[(k * 7) % len(names)]][0] - test[names[(k * 7) % len(names)]][4]
    out = []

    def add(case, x, ref, lyr_words=frozenset(), **extra):
        out.append((case, (x / max(1.0, np.abs(x).max() / 0.99)).astype(np.float32), ref, lyr_words, extra))

    def lesson(k, seconds=60):
        return _speech(talks[k % len(talks)], seconds)

    def over(s, m, off, start, end=None):
        return s + _bed(m, len(s), start, end) * np.sqrt(level(s) * 10 ** (off / 10) / level(_bed(m, len(s), start, end)))

    for k in range(6):
        s, ref = lesson(k)
        add("A professor sozinho", s, ref)
    for off in (0, 5, 10):
        for k in range(6):
            s, ref = lesson(k)
            add("B professor + instrumental", over(s, inst(k), off, 30), ref, off=off)
    for k in range(6):
        s, ref = lesson(k + 6)
        add("B2 instrumental a aula toda", over(s, inst(k), 5, 0), ref, off=5)
    for off in (0, 5):
        for k in range(6):
            s, ref = lesson(k)
            name = vocal[k % len(vocal)]
            add("C professor + cantor", over(s, test[name][0], off, 30), ref, lyrics(name, test[name][4]), off=off,
                track=name, voz=("feminina" if (_f0(test[name][4]) or 0) > 165 else "masculina"))
    for off in (0, 5):
        for k in range(6):
            s, ref = lesson(k + 3)
            name = hh_names[k * 3]
            add("D professor + rap", over(s, hh[name], off, 30), ref, lyrics(name, hh[name]), off=off, track=name)
    for k in range(6):
        s, ref = lesson(k + 9)
        name = hh_names[k * 3 + 1]
        add("D2 rap a aula toda", over(s, hh[name], 0, 0), ref, lyrics(name, hh[name]), off=0, track=name)
    for k in range(4):  # dois professores alternando
        a, b = talks[k], talks[k + 8]
        parts, refs = [], []
        for j in range(4):
            for who in (a, b):
                x, r = _speech(who[j * 2:j * 2 + 2], 15)
                parts.append(x)
                refs.append(r)
        s, ref = np.concatenate(parts), " ".join(refs)
        add("E dois professores", over(s, inst(k), 5, len(s) / SR / 2), ref, off=5)
    for k in range(4):  # professor novo: aparece só depois, já com música
        a, ra = _speech(talks[k][:12], 30)
        b, rb = _speech(talks[k + 10][:12], 30)
        s = np.concatenate([a, b])
        add("F professor novo (sob instrumental)", over(s, inst(k), 5, len(a) / SR), ra + " " + rb, off=5)
        name = vocal[k % len(vocal)]
        add("F professor novo (sob cantor)", over(s, test[name][0], 0, len(a) / SR), ra + " " + rb,
            lyrics(name, test[name][4]), off=0, track=name)
    for off in (0, 5, 10):
        for k in range(6):
            s, ref = lesson(k + 2)
            name = cl_names[k * 4]
            add("G professor + clássica", over(s, cl[name], off, 30), ref, off=off, track=name)
    for k in range(4):  # música contínua; o professor pára 6 s entre as falas (música + silêncio de fala)
        s, ref = _speech(talks[k + 4][:10], 60, pause=6.0)
        name = vocal[(k + 3) % len(vocal)]
        add("H música entre as falas (cantor)", over(s, test[name][0], 0, 0), ref, lyrics(name, test[name][4]),
            off=0, track=name)
        name = hh_names[k * 3 + 2]
        add("H música entre as falas (rap)", over(s, hh[name], 0, 0), ref, lyrics(name, hh[name]), off=0, track=name)
    for k in range(4):  # podcast: vinheta, trilha baixa embaixo da fala, vinheta
        s, ref = lesson(k + 5, 45)
        m = inst(k + 1)
        bed = over(s, m, -15, 0)
        jingle = loop(m, 6 * SR) * np.sqrt(level(s) / level(m))
        add("I podcast com trilha", np.concatenate([jingle, bed, jingle]), ref)
    for k in range(4):  # o professor toca uma música para a turma e volta a explicar
        a, ra = _speech(talks[k + 1][:6], 25)
        b, rb = _speech(talks[k + 1][6:12], 20)
        name = vocal[(k + 5) % len(vocal)]
        song = loop(test[name][0], 15 * SR) * np.sqrt(level(a) / level(test[name][0]))
        add("J professor demonstra música", np.concatenate([a, song, b]), ra + " " + rb, lyrics(name, test[name][4]),
            track=name, song_words=len(lyrics(name, test[name][4])))
    choirs = {p.stem: audio.load(p)[10 * SR:40 * SR] for p in sorted(CHOIR.glob("*.wav"))}  # sem a entrada
    for k, (name, c) in enumerate(list(choirs.items())[:4]):
        add("K coral sozinho", loop(c, 20 * SR), "", lyrics(name, c), track=name)
        s, ref = lesson(k + 7)
        add("K professor + coral", over(s, c, 0, 30), ref, lyrics(name, c), off=0, track=name)
    for k in range(4):
        name = vocal[(k + 2) % len(vocal)]
        add("L voz cantada sem instrumentos", loop(test[name][4], 20 * SR), "", lyrics(name, test[name][4]), track=name)
        s, ref = lesson(k + 11)
        add("L professor + a cappella", over(s, test[name][4], 0, 30), ref, lyrics(name, test[name][4]), off=0,
            track=name)
    for k in range(3):
        add("M instrumental sem voz", loop(inst(k + 3), 20 * SR), "")
        add("M clássica sem voz", loop(cl[cl_names[k * 5 + 1]], 20 * SR), "", track=cl_names[k * 5 + 1])
    for k in range(4):
        s, ref = lesson(k + 12, 90)
        fast = audio.tempo(s, 1.5)
        add("N professor rápido (1,5×)", over(fast, inst(k), 5, 20), ref, off=5)
        s, ref = lesson(k + 13)
        add("O professor baixo", over(s, inst(k), 5, 30) * 0.05, ref, off=5)
    conv = [i for i in speech("A") + speech("B") if i["set"] == "conversa"]  # 20 falas de conversa
    for k in range(4):  # conversa gravada (NURC/SP2010/C-ORAL): várias pessoas
        s, ref = _join(conv[k * 5:k * 5 + 5])
        add("P várias pessoas", over(s, inst(k), 5, len(s) / SR / 2), ref, off=5)
    for k in range(4):  # spoken word: outra pessoa falando sobre uma batida, por cima da aula
        s, ref = lesson(k)
        other, ro = _speech(talks[k + 12][14:24], 30)
        track = loop(other, 30 * SR) + loop(inst(k + 2), 30 * SR) * np.sqrt(level(other) / level(inst(k + 2)))
        add("Q spoken word sobre a aula", over(s, track, 0, 30), ref, frozenset(metrics.normalize(ro)), off=0)
    for k, genre in enumerate(("rock", "pop", "jazz", "reggae", "country", "metal", "blues", "disco")):
        clips = gtzan(genre)
        name = sorted(clips)[-1]
        s, ref = lesson(k + 1)
        add("R gêneros", over(s, clips[name], 5, 30), ref, lyrics(name, clips[name]), off=5, track=name, genre=genre)
    return out


def run2(tag="depois", modes=("conservador", "balanceado", "agressivo"), only=None):
    """O conjunto v2 nos três modos → bench/results/music_v2_<tag>.json (tag “antes” = versão anterior do filtro).
    only: prefixo de cenário; roda só esses e troca só eles no arquivo existente."""
    from lumen import music
    _cached_separate()
    res, t0 = [], time.time()
    cases = [c for c in suite() if not only or c[0].startswith(only)]
    print(len(cases), "casos", flush=True)
    for mode in modes:
        for case, x, ref, lyr_words, extra in cases:
            r = _case(case, x, ref, lyr_words, mode=mode, **extra)
            res.append(r)
            b, a = r["before"], r["after"]
            e = lambda s: f"{s['score']['S'] + s['score']['D'] + s['score']['I']}/{s['score']['N']}" if s["score"] else "-"
            print(f"[{time.time() - t0:5.0f}s] {mode[:5]} {case[:34]:34} {str(r.get('off', '')):>3} erros {e(b):>7} → "
                  f"{e(a):>7} | letra livre {b['lyrics_free']:3} → {a['lyrics_free']:3} | fala marcada "
                  f"{a['ref_flagged']:3}", flush=True)
    out = ROOT / "results" / f"music_v2_{tag}.json"
    if only:
        res = [r for r in json.loads(out.read_text("utf-8"))["cases"] if not r["case"].startswith(only)] + res
    out.write_text(json.dumps({"asr": ASR, "version": music.VERSION, "cases": res}, ensure_ascii=False, indent=1), "utf-8")


NO_EXTERNAL = ("A ", "I ", "J ", "M ")  # cenários sem música externa por cima da fala (o filtro não devia mexer)


def report2():
    """bench/RESULTADOS_MUSICA_V2.md: o conjunto v2 (aulas com professor) na v1 (antes) e na v2 (depois), por modo."""
    load = lambda t: json.loads((ROOT / "results" / f"music_v2_{t}.json").read_text("utf-8"))["cases"]
    before, after = load("antes"), load("depois")
    pct = lambda v: f"{v:.1%}".replace(".", ",") if v is not None else "–"
    num = lambda v: f"{v:g}".replace(".", ",")

    def agg(rows, tag):
        sc = [r[tag]["score"] for r in rows if r[tag]["score"]]
        return metrics.aggregate(sc) if sc else None

    def cell(rows, tag, key):
        if key == "WER":
            a = agg(rows, tag)
            return pct(a and a["WER"])
        if key == "D":
            a = agg(rows, tag)
            return str(a["D"]) if a else "–"
        return str(sum(r[tag][key] for r in rows))
    out = ["# Filtro de música v2: aulas com professor (antes × depois)", "",
           "Gerado por `python -m bench.music_bench run2 antes` (com a v1 congelada), `run2 depois` e `report2`. ASR: "
           "large-v3-turbo. Fala: 16 palestras do CORAA (TEDx; cada uma é um “professor”, ≈ 60 s por aula, metade sem "
           "música); música: MUSDB18 test, GTZAN 50–99 (hip-hop, clássica, outros gêneros). Nada disso foi usado no "
           "treino da sonda.", "",
           "- **WER**: erros de palavra contra a transcrição humana. **Perdidas**: palavras da fala omitidas.",
           "- **Letra livre**: palavras da letra que chegam à transcrição *sem* marca de “música ao fundo” (vão para a "
           "IA como fato). Letra marcada chega como “(?)”.",
           "- **Fala marcada**: palavras da aula marcadas como dúvida (vão para a IA como “(?)”).", ""]
    for mode in ("conservador", "balanceado", "agressivo"):
        out += [f"## Modo {mode}", "", "| Cenário | n | WER sem filtro | WER v1 | WER v2 | Perdidas sem → v1 → v2 | "
                "Letra livre sem → v1 → v2 | Fala marcada v1 → v2 | Removido v1 → v2 (s) |", "|---|---|---|---|---|---|---|---|---|"]
        rb = [r for r in before if r["mode"] == mode]
        ra = [r for r in after if r["mode"] == mode]
        for name in dict.fromkeys(r["case"] for r in ra):
            for off in dict.fromkeys(r.get("off") for r in ra if r["case"] == name):
                b = [r for r in rb if r["case"] == name and r.get("off") == off]
                a = [r for r in ra if r["case"] == name and r.get("off") == off]
                if not b:
                    continue
                label = name + (f" ({off:+d} dB)" if off is not None else "")
                out.append(f"| {label} | {len(a)} | {cell(b, 'before', 'WER')} | {cell(b, 'after', 'WER')} | "
                           f"{cell(a, 'after', 'WER')} | {cell(b, 'before', 'D')} → {cell(b, 'after', 'D')} → "
                           f"{cell(a, 'after', 'D')} | {cell(b, 'before', 'lyrics_free')} → {cell(b, 'after', 'lyrics_free')} → "
                           f"{cell(a, 'after', 'lyrics_free')} | {cell(b, 'after', 'ref_flagged')} → {cell(a, 'after', 'ref_flagged')} | "
                           f"{num(round(sum(r['rep']['removed_s'] for r in b), 1))} → {num(round(sum(r['rep']['removed_s'] for r in a), 1))} |")
        out.append("")
    out += ["## Resumo por modo", "", "| Modo | Versão | WER (aulas com fala) | Perdidas | Letra livre | Fala marcada | "
            "Falsos positivos | Falsos negativos | Tempo do filtro (s) |", "|---|---|---|---|---|---|---|---|---|"]
    for mode in ("conservador", "balanceado", "agressivo"):
        for tag, rows in (("v1", before), ("v2", after)):
            rows = [r for r in rows if r["mode"] == mode]
            sp = [r for r in rows if r["after"]["score"]]
            a = metrics.aggregate([r["after"]["score"] for r in sp])
            # falso positivo: sem música externa por cima da fala, e o filtro mudou o texto ou tirou áudio
            fp = [r for r in rows if r["case"].startswith(NO_EXTERNAL) and (r["rep"]["removed_s"] > 0 or
                  (r["rep"]["filtered"] and r["after"]["words"] != r["before"]["words"]))]
            # falso negativo: havia música externa e o filtro não a detectou
            fn = [r for r in rows if not r["case"].startswith(NO_EXTERNAL) and not r["rep"]["music_detected"]]
            n_neg = sum(1 for r in rows if r["case"].startswith(NO_EXTERNAL))
            out.append(f"| {mode} | {tag} | {pct(a['WER'])} | {a['D']} | {sum(r['after']['lyrics_free'] for r in rows)} | "
                       f"{sum(r['after']['ref_flagged'] for r in rows)} | {len(fp)}/{n_neg} | {len(fn)}/{len(rows) - n_neg} | "
                       f"{num(round(sum(r['filter_s'] for r in rows)))} |")
        if mode == "conservador":
            rows = [r for r in before if r["mode"] == mode]
            sp = [r for r in rows if r["before"]["score"]]
            a = metrics.aggregate([r["before"]["score"] for r in sp])
            out.insert(len(out) - 2, f"| (sem filtro) | – | {pct(a['WER'])} | {a['D']} | "
                       f"{sum(r['before']['lyrics_free'] for r in rows)} | 0 | – | – | – |")
    (ROOT / "RESULTADOS_MUSICA_V2.md").write_text("\n".join(out) + "\n", "utf-8")
    print("\n".join(out))


def _vram_mb():
    import subprocess
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return float(out.split()[0])
    except Exception:  # noqa: BLE001 — sem NVIDIA: não mede
        return None


def perf(minutes=10, device="gpu"):
    """Uma aula de `minutes` min com música com voz o tempo todo (pior caso), na GPU ou forçando a CPU (rode cada um
    num processo: o pico de RAM é do processo): tempo, CPU, RAM, VRAM e disco → bench/results/music_perf_<device>.json.
    O áudio de saída fica em bench/.data para comparar CPU × GPU (perf_compare)."""
    import tempfile
    import threading
    import onnxruntime
    from bench.asr_bench import _peak_ram_mb, _save_wav
    from lumen import audio, music, speaker
    if device == "cpu":
        onnxruntime.get_available_providers = lambda: ["CPUExecutionProvider"]
    sp = speech("B")
    s = np.concatenate([i["x"] for i in sp] * 4)[:minutes * 60 * SR]
    name = _vocal_tracks(tracks("test"))[0]
    x = mix(s, loop(tracks("test")[name][0], len(s)), 0)
    vram0, vram = _vram_mb(), []
    done = threading.Event()

    def poll():
        while not done.wait(0.5):
            vram.append(_vram_mb() or 0)
    threading.Thread(target=poll, daemon=True).start()
    ram0 = _peak_ram_mb()
    cpu0, t0 = time.process_time(), time.perf_counter()
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "aula.wav"
        _save_wav(src, x)
        path, rep = music.prepare(src, Path(d))
        wall, cpu = time.perf_counter() - t0, time.process_time() - cpu0
        done.set()
        size = Path(path).stat().st_size if path != str(src) else 0
        y = audio.load(path)
        np.save(DATA / f"perf_{device}.npy", y)
        t1 = time.perf_counter()
        _, rep2 = music.prepare(src, Path(d))
        again = time.perf_counter() - t1
    models = sum(Path(music._file(m)).stat().st_size for m in (music.DETECTOR, music.SEPARATOR, speaker.MODEL))
    info = {"device": rep.get("device"), "audio_min": minutes, "wall_s": round(wall, 1), "rtf": round(minutes * 60 / wall, 1),
            "cpu_s": round(cpu, 1), "cpu_cores_avg": round(cpu / wall, 1), "threads": max(2, (os.cpu_count() or 4) // 2),
            "peak_ram_mb_before": round(ram0), "peak_ram_mb": round(_peak_ram_mb()),
            "vram_mb_peak_extra": round(max(vram) - vram0) if vram and vram0 is not None else None,
            "wav_mb": round(size / 1e6, 1), "models_mb": round(models / 1e6, 1), "cache_hit_s": round(again, 2),
            "cached": bool(rep2.get("cached")), "filter_s": rep.get("seconds"),
            "rep": {k: rep.get(k) for k in ("removed_s", "separated_s", "doubt_s", "speakers", "teacher_s", "error")}}
    (ROOT / "results" / f"music_perf_{device}.json").write_text(json.dumps(info, indent=1), "utf-8")
    print(info)


def perf_compare():
    """Diferença entre a saída da CPU e a da GPU (SNR, dB): a GPU não pode mudar o resultado."""
    a, b = np.load(DATA / "perf_cpu.npy"), np.load(DATA / "perf_gpu.npy")
    n = min(len(a), len(b))
    snr = 10 * np.log10(np.sum(a[:n] ** 2) / max(np.sum((a[:n] - b[:n]) ** 2), 1e-20))
    out = {"snr_db": round(float(snr), 1), "max_abs_diff": float(np.abs(a[:n] - b[:n]).max())}
    (ROOT / "results" / "music_perf_compare.json").write_text(json.dumps(out, indent=1), "utf-8")
    print(out)


def report():
    data = json.loads((ROOT / "results" / "music.json").read_text("utf-8"))
    cases = data["cases"]

    def agg(rows, tag):
        sc = [r[tag]["score"] for r in rows if r[tag]["score"]]
        return metrics.aggregate(sc) if sc else None

    def pct(x):
        return f"{x:.1%}".replace(".", ",") if x is not None else "–"

    def conf(rows, tag):
        v = [r[tag]["conf"] for r in rows if r[tag]["conf"] is not None]
        return f"{np.mean(v):.2f}".replace(".", ",") if v else "–"

    def line(label, rows):
        b, a = agg(rows, "before"), agg(rows, "after")
        lb, la = sum(r["before"]["lyrics"] for r in rows), sum(r["after"]["lyrics"] for r in rows)
        wb, wa = sum(r["before"]["words"] for r in rows), sum(r["after"]["words"] for r in rows)
        removed = sum(r["rep"]["removed_s"] for r in rows) / max(sum(r["dur"] for r in rows), 1e-9)
        flagged = sum(r["after"]["flagged"] for r in rows)
        return (f"| {label} | {len(rows)} | {pct(b and b['WER'])} | {pct(a and a['WER'])} | "
                f"{b['D'] if b else '–'} → {a['D'] if a else '–'} | {lb} → {la} | {wb} → {wa} | {conf(rows, 'before')} → "
                f"{conf(rows, 'after')} | {pct(removed)} | {flagged} |")
    head = ("| Cenário | n | WER sem filtro | WER com filtro | Palavras da fala perdidas | Letra infiltrada | "
            "Palavras na saída | Confiança do ASR | Áudio removido | Trechos marcados |\n|---|---|---|---|---|---|---|---|---|---|")
    out = ["# Filtro de música externa: transcrição sem × com o filtro", "",
           f"Gerado por `python -m bench.music_bench run` e `report`. ASR: {data['asr']} (como o app, GPU). "
           f"Detector: YAMNet. Separador: {data['separator']}. Modo: {data['mode']}. Fala: FLEURS/CORAA (falas B, "
           "nunca usadas no treino da sonda); música: MUSDB18 test (nunca usada no treino) e sintética.", "",
           "- **WER**: erros de palavra contra a transcrição humana (bench/metrics.py). Menor é melhor.",
           "- **Palavras da fala perdidas**: omissões (D) do alinhamento; mede fala apagada.",
           "- **Letra infiltrada**: palavras da letra da música (o que o ASR ouve na voz da música sozinha) que "
           "aparecem na transcrição e não estão na fala.",
           "- **Confiança do ASR**: média do log da probabilidade dos trechos (avg_logprob; mais perto de 0 = mais "
           "confiante).", "", "## Volume da música em relação à fala", ""]
    for kind, label in (("inst", "instrumental"), ("vocal", "com voz cantada")):
        out += [f"### Música {label}", "", head.replace("Cenário", "Música vs. fala")]
        for off in (-15, -10, -5, 0, 5, 10, 15):
            out.append(line(f"{off:+d} dB", [r for r in cases if r["case"] == f"volume {kind}" and r["off"] == off]))
        out.append("")
    out += ["## Cenários", "", head]
    for name in dict.fromkeys(r["case"] for r in cases if not r["case"].startswith("volume")):
        rows = [r for r in cases if r["case"] == name]
        extra = ""
        if rows[0].get("tracking") is not None:
            extra = f" (detector acompanhou {np.mean([r['tracking'] for r in rows]):.0%} dos quadros)"
        out.append(line(name + extra, rows))
    perfs = {d: json.loads((ROOT / "results" / f"music_perf_{d}.json").read_text("utf-8"))
             for d in ("gpu", "cpu") if (ROOT / "results" / f"music_perf_{d}.json").exists()}
    if perfs:
        n = lambda v: f"{v:g}".replace(".", ",")
        out += ["", "## Desempenho (pior caso: música com voz a aula toda, 10 min; `perf gpu`, `perf cpu`)", "",
                "| | Tempo | × tempo real | CPU (s) | Núcleos em média | RAM de pico (antes) | VRAM extra |",
                "|---|---|---|---|---|---|---|"]
        for d, p in perfs.items():
            out.append(f"| {p['device']} | {n(p['wall_s'])} s | {n(p['rtf'])} | {n(p['cpu_s'])} | {n(p['cpu_cores_avg'])} | "
                       f"{p['peak_ram_mb']} MB ({p['peak_ram_mb_before']} MB) | "
                       f"{'–' if not p.get('vram_mb_peak_extra') or d == 'cpu' else str(p['vram_mb_peak_extra']) + ' MB'} |")
        cmp_file = ROOT / "results" / "music_perf_compare.json"
        if cmp_file.exists():
            c = json.loads(cmp_file.read_text("utf-8"))
            out.append(f"\nSaída da GPU × da CPU: diferença máxima {c['max_abs_diff']:g} (a GPU não muda o resultado).")
        p = next(iter(perfs.values()))
        out += ["", f"- Modelos: {n(p['models_mb'])} MB. Mesmo áudio de novo: {n(p['cache_hit_s'])} s (cache).",
                "- i5-11400F (6 núcleos/12 threads) e RTX 3060 via DirectML (onnxruntime-directml).",
                "- Sem música, ou com a fala clara por cima dela: só o detector roda (≈ 750× o tempo real; 1 h ≈ 5 s)."]
    out += ["", "## Leitura", "",
            "- Fala sozinha, silêncio, ventilador, teclado, conversa ao fundo e música até 0 dB: transcrição idêntica "
            "à sem filtro (o filtro não troca o áudio).",
            "- Instrumental alto (+5 a +15 dB): o filtro recupera boa parte da fala que a música cobria.",
            "- Música com letra e rap: o filtro não piora, mas também não tira a letra que o ASR transcreve; esses "
            "trechos ficam marcados como “música ao fundo”. A proteção contra letra é não gravar o app de música "
            "(isolamento da fonte, medido à parte: o tom do “app de música” some da gravação e o da aula fica).",
            "- Sem recuperação possível (fala 2× sob música, voz cantada a +10 dB): o filtro não inventa texto; a "
            "transcrição fica como sem o filtro.",
            "- As versões anteriores pioravam e foram descartadas (docs/DECISOES.md): voz separada em todo trecho com "
            "música fazia o ASR transcrever a letra (música sozinha 0 → 18 e 14 → 48 palavras; cantada a +10 dB, "
            "28 → 133); silenciar onde a sonda via só música apagou fala sob piano e eletrônica (0/18 → 18/18 erros)."]
    (ROOT / "RESULTADOS_MUSICA.md").write_text("\n".join(out) + "\n", "utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    import tests  # noqa: F401  (isola LUMEN_DATA: este script nunca toca nos dados reais do app)
    sys.stdout.reconfigure(encoding="utf-8")  # o console do Windows (cp1252) não imprime “→”
    {"fetch": fetch, "train": train, "run": run, "run2": lambda: run2(*sys.argv[2:3]), "perf": lambda: perf(10, *sys.argv[2:3]),
     "perf_compare": perf_compare, "report": report, "report2": report2}[sys.argv[1]]()
