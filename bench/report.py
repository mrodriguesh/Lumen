"""Gera bench/RESULTADOS.md a partir de bench/results/*.json, aplicando os critérios de bench/CRITERIOS.md."""
import json
import re
from pathlib import Path

import numpy as np

from bench import metrics
from bench.asr_bench import DATA, MODELS, RES, ROOT

SETS = ["leitura", "palestra", "conversa", "ruido", "musica", "aula_longa"]
OPTIONAL = ["proprias"]  # aparece só se houver amostras próprias


def matched_ref_words(ref, hyp):
    """Alinhamento com retrocesso: para cada palavra da referência, se foi reconhecida exatamente."""
    n, m = len(ref), len(hyp)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        ri = ref[i - 1]
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j - 1] + (ri != hyp[j - 1]), d[i - 1, j] + 1, d[i, j - 1] + 1)
    ok, i, j = [False] * n, n, m
    while i > 0 and j > 0:
        if ref[i - 1] == hyp[j - 1] and d[i, j] == d[i - 1, j - 1]:
            ok[i - 1] = True
            i, j = i - 1, j - 1
        elif d[i, j] == d[i - 1, j - 1] + 1:
            i, j = i - 1, j - 1
        elif d[i, j] == d[i - 1, j] + 1:
            i -= 1
        else:
            j -= 1
    return ok


def long_checks(row, timeline):
    words = [metrics.normalize(t["ref"]) for t in timeline if t["kind"] == "fala"]
    ok = matched_ref_words([w for ws in words for w in ws], metrics.normalize(row["hyp"]))
    cover, k = [], 0
    for ws in words:
        cover.append(sum(ok[k:k + len(ws)]) / max(len(ws), 1))
        k += len(ws)
    gaps = [t for t in timeline if t["kind"] != "fala"]
    halluc = 0
    for s in row["segments"]:
        for g in gaps:
            overlap = min(s["end"], g["end"]) - max(s["start"], g["start"])
            if overlap > 0.5 * (s["end"] - s["start"]):
                halluc += len(metrics.normalize(s["text"]))
    return {"min_cover": min(cover), "lost": sum(c < 0.5 for c in cover), "halluc_words": halluc}


def entities(rows):
    """Nomes próprios (palavras com maiúscula fora do início da frase) e números da referência FLEURS."""
    hit_n = tot_n = hit_e = tot_e = 0
    for r in rows:
        hyp = " " + " ".join(metrics.normalize(r["hyp"])) + " "
        for num in re.findall(r"\d+(?:\.\d{3})*", r["ref"]):
            tot_n += 1
            hit_n += (" " + " ".join(metrics.normalize(num)) + " ") in hyp
        toks = r["ref"].split()
        for t in toks[1:]:
            w = re.sub(r"[^\w]", "", t)
            if w[:1].isupper() and not w.isupper():
                tot_e += 1
                hit_e += (" " + " ".join(metrics.normalize(w)) + " ") in hyp
    return hit_n / max(tot_n, 1), tot_n, hit_e / max(tot_e, 1), tot_e


def confidence(rows):
    """Critério 10: utterances com segmento de avg_logprob < -1 têm WER >= 2x?"""
    pool = [r for r in rows if r["set"] in ("palestra", "conversa") and r["segments"] and r["segments"][0].get("logprob") is not None]
    if not pool:
        return None
    flag = [r for r in pool if min(s["logprob"] for s in r["segments"]) < -1.0]
    rest = [r for r in pool if r not in flag]
    if not flag or not rest:
        return {"flagged": len(flag), "n": len(pool)}
    a, b = metrics.aggregate(flag)["WER"], metrics.aggregate(rest)["WER"]
    return {"flagged": len(flag), "n": len(pool), "wer_flagged": a, "wer_rest": b, "ratio": a / max(b, 1e-9)}


def agreement(rows_a, rows_b, limit=0.3):
    """Divergência entre dois modelos (mesma função do app) como sinal: trechos em que discordam erram mais?"""
    from lumen.transcribe import disagreement
    by_b = {r["id"]: r for r in rows_b}
    pool = [r for r in rows_a if r["set"] in ("palestra", "conversa") and r["id"] in by_b]
    flag, rest = [], []
    for r in pool:
        (flag if disagreement(r["hyp"], by_b[r["id"]]["hyp"]) > limit else rest).append(r)
    if not flag or not rest:
        return None
    a, b = metrics.aggregate(flag)["WER"], metrics.aggregate(rest)["WER"]
    return {"flagged": len(flag), "n": len(pool), "wer_flagged": a, "wer_rest": b, "ratio": a / b}


def vram(r):
    return "—" if r["vram_peak_gb"] is None or not r["gpu_used"] else f"{r['vram_peak_gb']:.1f} GB"


def sec(x):
    return "—" if x is None else f"{x:.2f} s"


def pct(x):
    return "—" if x is None else f"{100 * x:.1f}%"


def main():
    timeline = json.loads((DATA / "aula_longa.json").read_text("utf-8"))
    results = {}
    for name in MODELS:
        p = RES / f"{name}.json"
        if p.exists():
            results[name] = json.loads(p.read_text("utf-8"))
    L = ["# Resultados do benchmark de transcrição", "",
         "Gerado por `python -m bench.asr_bench report`. Critérios fixados antes em [CRITERIOS.md](CRITERIOS.md).", ""]
    info0 = next(iter(results.values()))["info"]
    L += [f"Hardware: Intel Core i5-11400F (6 núcleos/12 threads), 16 GB RAM, NVIDIA RTX 3060 12 GB. "
          f"Python {info0['versions']['python']}, faster-whisper {info0['versions']['faster_whisper']}, "
          f"CTranslate2 {info0['versions']['ctranslate2']}, onnx-asr {info0['versions']['onnx_asr']}.", ""]

    cols = SETS + [s for s in OPTIONAL if any(x["set"] == s for r in results.values() for x in r["rows"])]
    L += ["## WER por conjunto (menor é melhor)", "",
          "| Modelo | " + " | ".join(cols) + " | sem_fala (palavras) |", "|---" * (len(cols) + 2) + "|"]
    summary = {}
    for name, r in results.items():
        rows = r["rows"]
        agg = {s: metrics.aggregate([x for x in rows if x["set"] == s]) for s in cols}
        quiet = next(x for x in rows if x["set"] == "sem_fala")
        lc = long_checks(next(x for x in rows if x["set"] == "aula_longa"), timeline)
        summary[name] = {"agg": agg, "quiet": len(metrics.normalize(quiet["hyp"])), "long": lc, "info": r["info"],
                         "ent": entities([x for x in rows if x["set"] == "leitura"]), "conf": confidence(rows)}
        L.append(f"| {name} | " + " | ".join(pct(agg[s]["WER"]) for s in cols) + f" | {summary[name]['quiet']} |")

    L += ["", "## CER e erros por tipo (todos os conjuntos de fala)", "",
          "| Modelo | CER | Substituições | Omissões | Inserções | Palavras da referência |", "|---|---|---|---|---|---|"]
    for name, sm in summary.items():
        tot = metrics.aggregate([x for x in results[name]["rows"] if x["set"] in SETS])
        L.append(f"| {name} | {pct(tot['CER'])} | {tot['S']} | {tot['D']} | {tot['I']} | {tot['N']} |")

    L += ["", "## Nomes próprios, números, aula longa e recursos", "",
          "| Modelo | Números certos | Nomes próprios certos | Aula longa: trechos perdidos (<50%) | Omissões aula longa | Palavras inventadas em silêncio/música | Velocidade (× tempo real) | RAM pico | VRAM pico | Tamanho | Licença |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, sm in summary.items():
        i, lc, al = sm["info"], sm["long"], sm["agg"]["aula_longa"]
        num, nn, ent, ne = sm["ent"]
        L.append(f"| {name} | {pct(num)} de {nn} | {pct(ent)} de {ne} | {lc['lost']} de 40 | {pct(al['D'] / al['N'])} | "
                 f"{lc['halluc_words']} | {i['rtf']:.1f}× ({i['device'].upper()}) | {i['peak_ram_mb'] / 1000:.1f} GB | " +
                 ('—' if not i['peak_vram_mb'] or i['device'] == 'cpu' else f"{i['peak_vram_mb'] / 1000:.1f} GB") + f" | {i['size']} | {i['license']} |")

    L += ["", "## Critérios", "", "| Modelo | 1 leitura ≤10% | 2 palestra ≤20% | 3 aula longa | 4 sem texto inventado | 5 ≥5× nesta máquina | Aprovado |",
          "|---|---|---|---|---|---|---|"]
    passed = {}
    for name, sm in summary.items():
        a, lc, i = sm["agg"], sm["long"], sm["info"]
        c = [a["leitura"]["WER"] <= .10, a["palestra"]["WER"] <= .20,
             a["aula_longa"]["WER"] <= .25 and a["aula_longa"]["D"] / a["aula_longa"]["N"] <= .08 and lc["lost"] == 0,
             sm["quiet"] == 0 and lc["halluc_words"] < 3,
             i["rtf"] >= 5]  # medido nesta máquina; modelos ONNX rodam na CPU (onnxruntime sem CUDA) e ainda assim contam
        passed[name] = all(c)
        L.append(f"| {name} | " + " | ".join("✅" if x else "❌" for x in c) + f" | {'**sim**' if all(c) else 'não'} |")

    L.append("\nCritério 5: o limite (≥ 5×) foi mantido. Modelos ONNX (Parakeet, Canary) rodaram na CPU porque o "
             "onnxruntime instalado não tem CUDA; contam se atingirem o limite mesmo assim.")
    ok = {n: summary[n] for n, v in passed.items() if v}
    L += ["", "## Escolha", ""]
    if ok:
        score = {n: (s["agg"]["palestra"]["WER"] + s["agg"]["aula_longa"]["WER"]) / 2 for n, s in ok.items()}
        best = min(score.values())
        tied = [n for n in score if score[n] - best < 0.01]
        win = max(tied, key=lambda n: ok[n]["info"]["rtf"])
        L.append("Média de WER (palestra + aula longa) dos aprovados: " +
                 ", ".join(f"{n} {pct(v)}" for n, v in sorted(score.items(), key=lambda kv: kv[1])) + ".")
        L.append(f"\n**Vencedor (GPU): {win}**" + (f" (empate técnico com {', '.join(t for t in tied if t != win)}; vence o mais rápido)" if len(tied) > 1 else "") + ".")
    else:
        L.append("**Nenhum modelo passou em todos os critérios.** O app não deve anunciar a transcrição como precisa.")

    L += ["", "## Sinais de confiança (critério 10)", ""]
    for name, sm in summary.items():
        c = sm["conf"]
        if c and "ratio" in c:
            L.append(f"- {name}, `avg_logprob < -1`: marca {c['flagged']} de {c['n']} trechos; WER marcados {pct(c['wer_flagged'])} "
                     f"x não marcados {pct(c['wer_rest'])} (razão {c['ratio']:.1f}×) → {'útil' if c['ratio'] >= 2 else 'NÃO útil'}.")
    for a, b in (("whisper-large-v3-turbo", "parakeet-tdt-0.6b-v3"), ("whisper-large-v3-turbo", "whisper-small"),
                 ("whisper-large-v3-turbo", "whisper-large-v3")):
        if a in results and b in results:
            for limit in (0.2, 0.3, 0.4):
                g = agreement(results[a]["rows"], results[b]["rows"], limit)
                if g:
                    L.append(f"- Divergência {a} × {b} (> {limit:.1f}): marca {g['flagged']} de {g['n']} "
                             f"({pct(g['flagged'] / g['n'])}); WER de {a} nos marcados {pct(g['wer_flagged'])} x "
                             f"{pct(g['wer_rest'])} (razão {g['ratio']:.1f}×) → {'útil' if g['ratio'] >= 2 else 'NÃO útil'}.")

    spd = sorted(RES.glob("speed_*.json"))
    if spd:
        L += ["", "## Aula efetivamente acelerada 2× (critérios 7 e 8)", "",
              "| Modelo | Estratégia | WER | Omissões | Erro mediano do timestamp | p90 | Tempo |", "|---|---|---|---|---|---|---|"]
        for p in spd:
            name = p.stem[6:]
            for v, d in json.loads(p.read_text("utf-8")).items():
                a = metrics.aggregate([d])
                L.append(f"| {name} | {v} | {pct(a['WER'])} | {pct(a['D'] / a['N'])} | " +
                         sec(d['ts']['median_s']) + " | " + sec(d['ts']['p90_s']) + f" | {d['secs']:.0f} s |")
        L.append("\nNormal (mesma aula, 1×): " + ", ".join(
            f"{p.stem[6:]} {pct(summary[p.stem[6:]]['agg']['aula_longa']['WER'])}" for p in spd if p.stem[6:] in summary) + ".")

    var = RES / "variants.json"
    if var.exists():
        L += ["", "## Auditoria das opções do app (whisper-large-v3-turbo, GPU)", "",
              "| Configuração | palestra | aula longa | erro mediano do timestamp (1×) | palavras em sem_fala |",
              "|---|---|---|---|---|"]
        for name, d in json.loads(var.read_text("utf-8")).items():
            L.append(f"| {name} | {pct(d['palestra']['WER'])} | {pct(d['aula_longa']['WER'])} | {sec(d['ts']['median_s'])} | {d['sem_fala_words']} |")
        L.append("\n“hotwords” usou 40 palavras raras da própria referência (melhor caso de vocabulário do curso).")
    rate = RES / "rate.json"
    if rate.exists():
        r = json.loads(rate.read_text("utf-8"))
        n, f = r["normal"], r["2x"]
        lim = r["limite"]
        ok = sum(v < lim for v in n.values()) + sum(v >= lim for v in f.values()) if lim else 0
        L += ["", "## Modo Automático de velocidade (janelas de 120 s)", "",
              f"Fala normal: {min(n.values()):.2f} a {max(n.values()):.2f} palavras/s ({len(n)} janelas). "
              f"Fala 2×: {min(f.values()):.2f} a {max(f.values()):.2f} ({len(f)} janelas). "
              + (f"Limite {lim:.2f}: {ok} de {len(n) + len(f)} janelas classificadas certo, mas com folga de só "
                 f"{min(f.values()) - max(n.values()):.2f} palavras/s; por isso o Automático é tratado como sugestão."
                 if lim else "As faixas se sobrepõem: o Automático não é confiável.")]
    chk = RES / "app_check.json"
    if chk.exists():
        L += ["", "## Caminho real do app (`python -m bench.app_check`, aula longa, opções finais)", "",
              "| Caso | Modelo | Dispositivo | WER | Omissões | Inserções | Erro mediano do timestamp | Trechos marcados | Tempo |",
              "|---|---|---|---|---|---|---|---|---|"]
        for c in json.loads(chk.read_text("utf-8")):
            L.append(f"| {c['caso']}{' (' + str(c['detectado_wps']) + ' palavras/s)' if 'detectado_wps' in c else ''} | "
                     f"{c['modelo']} | {c['dispositivo'].upper()} | {pct(c['WER'])} | {c['omissoes']} | {c['insercoes']} | "
                     f"{sec(c['timestamp']['median_s'])} | {c['marcados']} de {c['trechos']} | {c['segundos']:.0f} s |")
    ul = RES / "ultra.jsonl"
    if ul.exists():
        rows = [json.loads(x) for x in ul.read_text("utf-8").splitlines() if x.strip()]
        L += ["", "## 4× Ultra, auditoria do 2× e hardware (adendo 3; `python -m bench.ultra all`)", "",
              "Aula longa (palestras reais do CORAA) em 1×, 2× e 4× (aceleração sintética com atempo). Preparação = fator "
              "do atempo antes do modelo (1,0 = direto; 0,25 em 4× = velocidade natural). Sem o segundo modelo. "
              "GPU% = uso médio da GPU durante a inferência (nvidia-smi a cada 250 ms); “usou GPU” só se o uso passou de 20%. "
              "É a placa inteira: outro programa pode causar um pico isolado (ex.: uma linha do Parakeet).", "",
              "| Modelo | Tipo | Vel. | Preparação | WER | Omissões | Inserções | Trechos perdidos | Timestamp | Tempo | Núcleos CPU | GPU% | Usou GPU | VRAM pico | RAM pico |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['model']} | {r['compute']} | {r['speed']}× | {r['prep']} | {pct(r['WER'])} | {r['D']} | {r['I']} | "
                     f"{r['lost']} de 40 | {sec(r['ts']['median_s'])} | {r['secs']:.0f} s | {r['cpu_cores_avg']:.1f} | "
                     f"{r['gpu_util_avg']:.0f}% | {'sim' if r['gpu_used'] else 'não'} | "
                     f"{vram(r)} | "
                     f"{r['ram_peak_gb']:.1f} GB |")
        one = {(r["model"], r["compute"]): r["WER"] for r in rows if r["speed"] == 1}
        L += ["", "Critério 12 (4×: WER ≤ 2 × WER em 1× e ≤ 30%, sem trecho perdido, timestamp ≤ 1 s, sem texto inventado):"]
        best4 = min((r for r in rows if r["speed"] == 4), key=lambda r: r["WER"])
        passed4 = [r for r in rows if r["speed"] == 4 and r["WER"] <= min(0.30, 2 * one.get((r["model"], r["compute"]), 1))
                   and r["lost"] == 0 and (r["ts"]["median_s"] or 99) <= 1 and r["halluc"] == 0]
        L.append(f"{len(passed4)} combinações aprovadas. Melhor 4× na tabela: {best4['model']} {best4['compute']} preparação "
                 f"{best4['prep']} ({pct(best4['WER'])}). **Nenhuma aprovada → 4× Ultra é oferecido como experimental.**"
                 if not passed4 else f"Aprovadas: {', '.join(r['model'] + ' ' + str(r['prep']) for r in passed4)}.")
    ex = RES / "extra4x.json"
    if ex.exists():
        L += ["", "### 4×: Rubber Band (FFmpeg do sistema) e condition_on_previous_text=False", "",
              "| Modelo | Preparação | Método | WER | Omissões | Inserções | Timestamp |", "|---|---|---|---|---|---|---|"]
        for r in json.loads(ex.read_text("utf-8")):
            L.append(f"| {r['model']} | {r['prep']} | {r['method']} | {pct(r['WER'])} | {r['D']} | {r['I']} | {sec(r['ts']['median_s'])} |")
    r4 = RES / "rate4.json"
    if r4.exists():
        d = json.loads(r4.read_text("utf-8"))
        rng = {k: (min(x for x in v.values() if x is not None), max(x for x in v.values() if x is not None)) for k, v in d.items()}
        L += ["", "### Automático com 4× (palavras/s em janelas de 120 s; critério 13)", ""]
        L += [f"- {k}: {a_:.2f} a {b_:.2f}" for k, (a_, b_) in rng.items()]
        L.append("\nEm 4× o modelo muitas vezes quase não reconhece nada (taxa perto de 0), e depois de desacelerar 0,5× "
                 "as faixas de 2× e 4× se sobrepõem. **O Automático não identifica 4× com segurança**: sugere 2× quando a "
                 "fala é rápida, marca como incerto quando quase nada é reconhecido e pede a confirmação do usuário.")
    rs = RES / "responsive.json"
    if rs.exists():
        L += ["", "### Responsividade (critério 15; 120 s de aula na CPU)", "",
              "| Modelo | Núcleos lógicos reservados | Prioridade baixa | Tempo | API p95 | Outro programa fica |", "|---|---|---|---|---|---|"]
        for r in sorted(json.loads(rs.read_text("utf-8")), key=lambda r: (r["model"], r["reserve"], r["low_priority"])):
            L.append(f"| {r['model']} | {r['reserve']} | {'sim' if r['low_priority'] else 'não'} | {r['secs_120s_audio']:.1f} s | "
                     f"{r['api_p95_ms']:.0f} ms | {r['probe_slowdown']:.2f}× mais lento |")
    bt = RES / "batched.json"
    if bt.exists():
        L += ["", "### Inferência em lotes (BatchedInferencePipeline, turbo na GPU)", "",
              "| Velocidade | Lote | WER | Tempo | GPU% | Timestamp |", "|---|---|---|---|---|---|"]
        for r in json.loads(bt.read_text("utf-8")):
            L.append(f"| {r['speed']}× | {r['batch'] or 'sequencial (app)'} | {pct(r['WER'])} | {r['secs']:.1f} s | {r['gpu_util_avg']:.0f}% | {sec(r['ts']['median_s'])} |")
        L.append("\nLotes: 2× mais rápido, mas WER pior e timestamps grosseiros (segmentos longos) → **não adotado** (critério 14).")

    L += ["", "Variação entre execuções: com o fallback de temperatura do Whisper, a mesma configuração pode mudar de uma "
          "rodada para outra (ex.: large-v3 2× desacelerado deu 26,7% numa execução e 17,3% na seguinte). Diferenças "
          "menores que ~1 ponto não devem ser lidas como vitória."]
    L += ["", "## Configuração", "",
          "A tabela principal usou `condition_on_previous_text=False` em todos os Whisper. Pela auditoria acima, o app "
          "mantém `True` (aula longa do turbo: 11,5% em vez de 12,8%). Na GPU, o app também roda o whisper-small como "
          "segundo modelo, só para marcar trechos divergentes (limite 0,2, conforme o adendo dos critérios).", ""]
    for name, sm in summary.items():
        i = sm["info"]
        L.append(f"- **{name}**: `{i['model_id']}` em {i['device']}; {i['options']}; carga {i['load_s']:.0f} s.")
    (ROOT / "RESULTADOS.md").write_text("\n".join(L) + "\n", "utf-8")
    print("bench/RESULTADOS.md atualizado")
