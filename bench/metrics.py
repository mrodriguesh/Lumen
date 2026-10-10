"""WER/CER com contagem de substituições, omissões e inserções, e normalização para pt-BR.

A normalização é a mesma para referência e hipótese: minúsculas, sem pontuação, números por extenso
(“1990” e “mil novecentos e noventa” contam igual) e sem pausas preenchidas (“ahn”, “hum”).
"""
import re
import unicodedata

_UNITS = "zero um dois três quatro cinco seis sete oito nove dez onze doze treze quatorze quinze dezesseis dezessete dezoito dezenove".split()
_TENS = {2: "vinte", 3: "trinta", 4: "quarenta", 5: "cinquenta", 6: "sessenta", 7: "setenta", 8: "oitenta", 9: "noventa"}
_HUNDREDS = {1: "cento", 2: "duzentos", 3: "trezentos", 4: "quatrocentos", 5: "quinhentos", 6: "seiscentos",
             7: "setecentos", 8: "oitocentos", 9: "novecentos"}
FILLERS = {"ahn", "ah", "hum", "hm", "hmm", "uh", "eh", "éh", "ã", "hã", "ahm", "uhm", "mhm", "aham"}


def _below_1000(n):
    if n < 20:
        return _UNITS[n]
    if n < 100:
        t, u = divmod(n, 10)
        return _TENS[t] + (" e " + _UNITS[u] if u else "")
    if n == 100:
        return "cem"
    h, r = divmod(n, 100)
    return _HUNDREDS[h] + (" e " + _below_1000(r) if r else "")


def number_words(n):
    """Inteiro 0..999.999.999 por extenso em pt-BR."""
    if n < 1000:
        return _below_1000(n)
    if n < 1_000_000:
        k, r = divmod(n, 1000)
        head = "mil" if k == 1 else _below_1000(k) + " mil"
    else:
        m, r = divmod(n, 1_000_000)
        head = ("um milhão" if m == 1 else _below_1000(m) + " milhões")
        if r >= 1000:
            return head + " " + number_words(r)
    if not r:
        return head
    return head + (" e " if r < 100 or r % 100 == 0 else " ") + _below_1000(r) if r < 1000 else head + " " + number_words(r)


def normalize(text):
    t = unicodedata.normalize("NFC", text or "").lower()
    t = re.sub(r"(\d)[.](\d{3})\b", r"\1\2", t)          # 1.000 → 1000
    t = re.sub(r"(\d+)\s*%", r"\1 por cento", t)
    t = re.sub(r"(\d+)[ºª°]", r"\1", t)
    t = re.sub(r"\d+", lambda m: number_words(int(m.group())) if len(m.group()) <= 9 else m.group(), t)
    t = re.sub(r"[^\w\s]|_", " ", t)                     # pontuação, hífens, aspas
    return [w for w in t.split() if w not in FILLERS]


def align(ref, hyp):
    """Distância de edição com contagem (S, D, I). D = palavra da referência omitida; I = palavra inventada."""
    n, m = len(ref), len(hyp)
    prev = [(j, 0, 0, j) for j in range(m + 1)]  # (custo, S, D, I)
    for i in range(1, n + 1):
        cur = [(i, 0, i, 0)] + [None] * m
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur[j] = prev[j - 1]
                continue
            s, d, ins = prev[j - 1], prev[j], cur[j - 1]
            best = min((s[0], 0), (d[0], 1), (ins[0], 2))[1]
            if best == 0:
                cur[j] = (s[0] + 1, s[1] + 1, s[2], s[3])
            elif best == 1:
                cur[j] = (d[0] + 1, d[1], d[2] + 1, d[3])
            else:
                cur[j] = (ins[0] + 1, ins[1], ins[2], ins[3] + 1)
        prev = cur
    _, s, d, i = prev[m]
    return {"S": s, "D": d, "I": i, "N": n}


def score(ref_text, hyp_text):
    r, h = normalize(ref_text), normalize(hyp_text)
    w = align(r, h)
    c = align(list(" ".join(r)), list(" ".join(h)))
    return {**w, "Nc": c["N"], "Ec": c["S"] + c["D"] + c["I"]}


def aggregate(scores):
    tot = {k: sum(s[k] for s in scores) for k in ("S", "D", "I", "N", "Nc", "Ec")}
    tot["WER"] = (tot["S"] + tot["D"] + tot["I"]) / max(tot["N"], 1)
    tot["CER"] = tot["Ec"] / max(tot["Nc"], 1)
    return tot
