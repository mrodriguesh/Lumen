# Resultados do benchmark de transcrição

Gerado por `python -m bench.asr_bench report`. Critérios fixados antes em [CRITERIOS.md](CRITERIOS.md).

Hardware: Intel Core i5-11400F (6 núcleos/12 threads), 16 GB RAM, NVIDIA RTX 3060 12 GB. Python 3.14.8, faster-whisper 1.2.1, CTranslate2 4.8.2, onnx-asr 0.12.0.

## WER por conjunto (menor é melhor)

| Modelo | leitura | palestra | conversa | ruido | musica | aula_longa | sem_fala (palavras) |
|---|---|---|---|---|---|---|---|
| whisper-small | 6.5% | 13.2% | 32.9% | 9.4% | 7.0% | 14.6% | 0 |
| whisper-medium | 4.6% | 12.4% | 25.6% | 5.1% | 3.7% | 13.0% | 0 |
| whisper-large-v3-turbo | 3.0% | 11.7% | 25.5% | 4.6% | 3.4% | 12.8% | 0 |
| whisper-large-v3 | 3.3% | 12.0% | 23.0% | 3.9% | 2.9% | 11.8% | 0 |
| whisper-small-cpu | 6.3% | 13.7% | 34.1% | 8.4% | 6.6% | 18.3% | 0 |
| whisper-large-v3-turbo-cpu | 3.1% | 12.5% | 25.0% | 4.3% | 3.2% | 12.8% | 0 |
| parakeet-tdt-0.6b-v3 | 4.2% | 10.9% | 25.8% | 6.1% | 3.9% | 14.3% | 0 |
| canary-1b-v2 | 3.9% | 13.5% | 28.8% | 6.7% | 4.4% | 18.2% | 0 |

## CER e erros por tipo (todos os conjuntos de fala)

| Modelo | CER | Substituições | Omissões | Inserções | Palavras da referência |
|---|---|---|---|---|---|
| whisper-small | 5.6% | 461 | 189 | 110 | 6133 |
| whisper-medium | 4.8% | 321 | 186 | 74 | 6133 |
| whisper-large-v3-turbo | 4.3% | 304 | 172 | 59 | 6133 |
| whisper-large-v3 | 4.3% | 280 | 176 | 52 | 6133 |
| whisper-small-cpu | 6.0% | 454 | 210 | 120 | 6133 |
| whisper-large-v3-turbo-cpu | 4.5% | 289 | 190 | 57 | 6133 |
| parakeet-tdt-0.6b-v3 | 4.9% | 323 | 198 | 58 | 6133 |
| canary-1b-v2 | 5.2% | 408 | 174 | 79 | 6133 |

## Nomes próprios, números, aula longa e recursos

| Modelo | Números certos | Nomes próprios certos | Aula longa: trechos perdidos (<50%) | Omissões aula longa | Palavras inventadas em silêncio/música | Velocidade (× tempo real) | RAM pico | VRAM pico | Tamanho | Licença |
|---|---|---|---|---|---|---|---|---|---|---|
| whisper-small | 94.1% de 17 | 73.9% de 115 | 0 de 40 | 3.4% | 0 | 29.7× (CUDA) | 1.0 GB | 1.0 GB | 0,48 GB | MIT |
| whisper-medium | 94.1% de 17 | 77.4% de 115 | 0 de 40 | 3.8% | 17 | 18.6× (CUDA) | 1.7 GB | 2.9 GB | 1,5 GB | MIT |
| whisper-large-v3-turbo | 94.1% de 17 | 79.1% de 115 | 0 de 40 | 4.0% | 0 | 23.5× (CUDA) | 1.8 GB | 2.4 GB | 1,6 GB | MIT |
| whisper-large-v3 | 94.1% de 17 | 79.1% de 115 | 0 de 40 | 4.1% | 0 | 11.9× (CUDA) | 3.3 GB | 4.9 GB | 3,1 GB | MIT |
| whisper-small-cpu | 94.1% de 17 | 74.8% de 115 | 1 de 40 | 6.1% | 0 | 4.6× (CPU) | 1.0 GB | — | 0,48 GB | MIT |
| whisper-large-v3-turbo-cpu | 94.1% de 17 | 79.1% de 115 | 0 de 40 | 4.7% | 0 | 1.6× (CPU) | 2.0 GB | — | 1,6 GB | MIT |
| parakeet-tdt-0.6b-v3 | 100.0% de 17 | 73.0% de 115 | 0 de 40 | 4.4% | 0 | 19.2× (CPU) | 1.4 GB | — | 0,67 GB (int8) | CC-BY-4.0 |
| canary-1b-v2 | 94.1% de 17 | 75.7% de 115 | 0 de 40 | 4.3% | 1 | 7.6× (CPU) | 1.8 GB | — | 1,0 GB (int8) | CC-BY-4.0 |

## Critérios

| Modelo | 1 leitura ≤10% | 2 palestra ≤20% | 3 aula longa | 4 sem texto inventado | 5 ≥5× nesta máquina | Aprovado |
|---|---|---|---|---|---|---|
| whisper-small | ✅ | ✅ | ✅ | ✅ | ✅ | **sim** |
| whisper-medium | ✅ | ✅ | ✅ | ❌ | ✅ | não |
| whisper-large-v3-turbo | ✅ | ✅ | ✅ | ✅ | ✅ | **sim** |
| whisper-large-v3 | ✅ | ✅ | ✅ | ✅ | ✅ | **sim** |
| whisper-small-cpu | ✅ | ✅ | ❌ | ✅ | ❌ | não |
| whisper-large-v3-turbo-cpu | ✅ | ✅ | ✅ | ✅ | ❌ | não |
| parakeet-tdt-0.6b-v3 | ✅ | ✅ | ✅ | ✅ | ✅ | **sim** |
| canary-1b-v2 | ✅ | ✅ | ✅ | ✅ | ✅ | **sim** |

Critério 5: o limite (≥ 5×) foi mantido. Modelos ONNX (Parakeet, Canary) rodaram na CPU porque o onnxruntime instalado não tem CUDA; contam se atingirem o limite mesmo assim.

## Escolha

Média de WER (palestra + aula longa) dos aprovados: whisper-large-v3 11.9%, whisper-large-v3-turbo 12.2%, parakeet-tdt-0.6b-v3 12.6%, whisper-small 13.9%, canary-1b-v2 15.8%.

**Vencedor (GPU): whisper-large-v3-turbo** (empate técnico com whisper-large-v3, parakeet-tdt-0.6b-v3; vence o mais rápido).

## Sinais de confiança (critério 10)

- whisper-small, `avg_logprob < -1`: marca 10 de 116 trechos; WER marcados 95.7% x não marcados 17.4% (razão 5.5×) → útil.
- whisper-medium, `avg_logprob < -1`: marca 2 de 116 trechos; WER marcados 80.0% x não marcados 16.2% (razão 4.9×) → útil.
- whisper-large-v3-turbo, `avg_logprob < -1`: marca 4 de 118 trechos; WER marcados 111.5% x não marcados 15.6% (razão 7.2×) → útil.
- whisper-small-cpu, `avg_logprob < -1`: marca 10 de 116 trechos; WER marcados 104.3% x não marcados 17.9% (razão 5.8×) → útil.
- whisper-large-v3-turbo-cpu, `avg_logprob < -1`: marca 3 de 118 trechos; WER marcados 90.0% x não marcados 16.4% (razão 5.5×) → útil.
- Divergência whisper-large-v3-turbo × parakeet-tdt-0.6b-v3 (> 0.2): marca 28 de 120 (23.3%); WER de whisper-large-v3-turbo nos marcados 60.3% x 11.2% (razão 5.4×) → útil.
- Divergência whisper-large-v3-turbo × parakeet-tdt-0.6b-v3 (> 0.3): marca 22 de 120 (18.3%); WER de whisper-large-v3-turbo nos marcados 73.6% x 12.1% (razão 6.1×) → útil.
- Divergência whisper-large-v3-turbo × parakeet-tdt-0.6b-v3 (> 0.4): marca 19 de 120 (15.8%); WER de whisper-large-v3-turbo nos marcados 77.5% x 12.6% (razão 6.2×) → útil.
- Divergência whisper-large-v3-turbo × whisper-small (> 0.2): marca 33 de 120 (27.5%); WER de whisper-large-v3-turbo nos marcados 44.8% x 12.4% (razão 3.6×) → útil.
- Divergência whisper-large-v3-turbo × whisper-small (> 0.3): marca 27 de 120 (22.5%); WER de whisper-large-v3-turbo nos marcados 56.9% x 12.8% (razão 4.5×) → útil.
- Divergência whisper-large-v3-turbo × whisper-small (> 0.4): marca 24 de 120 (20.0%); WER de whisper-large-v3-turbo nos marcados 63.1% x 12.6% (razão 5.0×) → útil.
- Divergência whisper-large-v3-turbo × whisper-large-v3 (> 0.2): marca 15 de 120 (12.5%); WER de whisper-large-v3-turbo nos marcados 70.2% x 14.3% (razão 4.9×) → útil.
- Divergência whisper-large-v3-turbo × whisper-large-v3 (> 0.3): marca 12 de 120 (10.0%); WER de whisper-large-v3-turbo nos marcados 75.3% x 14.8% (razão 5.1×) → útil.
- Divergência whisper-large-v3-turbo × whisper-large-v3 (> 0.4): marca 9 de 120 (7.5%); WER de whisper-large-v3-turbo nos marcados 91.9% x 14.9% (razão 6.2×) → útil.

## Aula efetivamente acelerada 2× (critérios 7 e 8)

| Modelo | Estratégia | WER | Omissões | Erro mediano do timestamp | p90 | Tempo |
|---|---|---|---|---|---|---|
| parakeet-tdt-0.6b-v3 | direto | 36.2% | 14.2% | 0.03 s | 0.07 s | 14 s |
| parakeet-tdt-0.6b-v3 | atempo_0.5 | 37.9% | 14.5% | 0.03 s | 0.12 s | 27 s |
| parakeet-tdt-0.6b-v3 | reamostragem_0.5 | 89.8% | 53.5% | 0.02 s | 0.02 s | 27 s |
| whisper-large-v3-turbo | direto | 17.9% | 6.5% | 0.19 s | 1.38 s | 13 s |
| whisper-large-v3-turbo | atempo_0.5 | 18.9% | 6.2% | 0.64 s | 4.01 s | 9 s |
| whisper-large-v3-turbo | reamostragem_0.5 | 47.4% | 20.0% | 1.58 s | 4.29 s | 8 s |
| whisper-large-v3 | direto | 17.6% | 9.1% | 0.19 s | 1.84 s | 27 s |
| whisper-large-v3 | atempo_0.5 | 17.4% | 5.0% | 0.25 s | 2.31 s | 21 s |
| whisper-large-v3 | reamostragem_0.5 | 45.8% | 19.0% | 0.53 s | 8.28 s | 19 s |
| whisper-small | direto | 27.1% | 4.5% | 0.49 s | 1.69 s | 9 s |
| whisper-small | atempo_0.5 | 30.9% | 11.2% | 0.39 s | 1.97 s | 9 s |
| whisper-small | reamostragem_0.5 | 85.8% | 58.3% | 1.91 s | 16.20 s | 24 s |

Normal (mesma aula, 1×): parakeet-tdt-0.6b-v3 14.3%, whisper-large-v3-turbo 12.8%, whisper-large-v3 11.8%, whisper-small 14.6%.

## Auditoria das opções do app (whisper-large-v3-turbo, GPU)

| Configuração | palestra | aula longa | erro mediano do timestamp (1×) | palavras em sem_fala |
|---|---|---|---|---|
| app_atual (auto idioma, cond_prev=True, VAD) | 11.7% | 11.5% | 0.50 s | 0 |
| pt, cond_prev=True, VAD | 11.7% | 11.5% | 0.50 s | 0 |
| pt, cond_prev=False, VAD | 11.7% | 12.8% | 0.51 s | 0 |
| pt, cond_prev=False, sem VAD | 11.6% | 12.1% | 0.73 s | 1 |
| pt, cond_prev=False, VAD, hotwords | 10.2% | 11.9% | 14.95 s | 0 |

“hotwords” usou 40 palavras raras da própria referência (melhor caso de vocabulário do curso).

## Modo Automático de velocidade (janelas de 120 s)

Fala normal: 1.78 a 2.88 palavras/s (16 janelas). Fala 2×: 2.89 a 5.43 (16 janelas). Limite 2.88: 32 de 32 janelas classificadas certo, mas com folga de só 0.01 palavras/s; por isso o Automático é tratado como sugestão.

## Caminho real do app (`python -m bench.app_check`, aula longa, opções finais)

| Caso | Modelo | Dispositivo | WER | Omissões | Inserções | Erro mediano do timestamp | Trechos marcados | Tempo |
|---|---|---|---|---|---|---|---|---|
| A: GPU 1x (equilibrado + segundo modelo) | large-v3-turbo | CUDA | 11.5% | 20 | 18 | 0.50 s | 14 de 88 | 24 s |
| B: automático no arquivo 2x (4.08 palavras/s) | large-v3-turbo | CUDA | 16.2% | 25 | 18 | 0.07 s | 45 de 115 | 21 s |
| C: automático no arquivo 1x (2.28 palavras/s) | large-v3-turbo | CUDA | 11.5% | 20 | 18 | 0.50 s | 14 de 88 | 20 s |
| 2x direto | large-v3-turbo | CUDA | 17.7% | 46 | 15 | 0.13 s | 35 de 96 | 17 s |
| 2x desacelerado | large-v3-turbo | CUDA | 16.2% | 25 | 18 | 0.07 s | 45 de 115 | 21 s |
| 2x direto | large-v3 | CUDA | 17.0% | 39 | 19 | 0.16 s | 32 de 94 | 37 s |
| 2x desacelerado | large-v3 | CUDA | 17.3% | 26 | 25 | 0.45 s | 59 de 114 | 52 s |
| 2x direto | small | CUDA | 26.4% | 52 | 31 | 0.22 s | 42 de 64 | 19 s |
| 2x desacelerado | small | CUDA | 27.0% | 42 | 29 | 0.10 s | 37 de 101 | 22 s |
| D: só CPU (equilibrado = Parakeet) | parakeet-tdt-0.6b-v3 | CPU | 14.3% | 31 | 19 | 0.03 s | 0 de 120 | 26 s |
| E: só CPU, arquivo 2x (large-v3-turbo, direto) | large-v3-turbo | CPU | 20.8% | 62 | 14 | 0.14 s | 0 de 80 | 79 s |
| E: só CPU, arquivo 2x (large-v3-turbo, desacelerado) | large-v3-turbo | CPU | 16.0% | 28 | 15 | 0.10 s | 0 de 92 | 121 s |

## 4× Ultra, auditoria do 2× e hardware (adendo 3; `python -m bench.ultra all`)

Aula longa (palestras reais do CORAA) em 1×, 2× e 4× (aceleração sintética com atempo). Preparação = fator do atempo antes do modelo (1,0 = direto; 0,25 em 4× = velocidade natural). Sem o segundo modelo. GPU% = uso médio da GPU durante a inferência (nvidia-smi a cada 250 ms); “usou GPU” só se o uso passou de 20%. É a placa inteira: outro programa pode causar um pico isolado (ex.: uma linha do Parakeet).

| Modelo | Tipo | Vel. | Preparação | WER | Omissões | Inserções | Trechos perdidos | Timestamp | Tempo | Núcleos CPU | GPU% | Usou GPU | VRAM pico | RAM pico |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| large-v3-turbo | float16 | 1× | 1.0 | 11.5% | 20 | 18 | 0 de 40 | 0.50 s | 18 s | 1.6 | 40% | sim | 2.4 GB | 1.8 GB |
| large-v3-turbo | float16 | 2× | 1.0 | 17.7% | 46 | 15 | 1 de 40 | 0.13 s | 10 s | 4.1 | 46% | sim | 2.4 GB | 1.8 GB |
| large-v3-turbo | float16 | 2× | 0.5 | 16.2% | 25 | 18 | 0 de 40 | 0.07 s | 20 s | 1.4 | 34% | sim | 4.5 GB | 1.8 GB |
| large-v3-turbo | float16 | 4× | 1.0 | 94.6% | 628 | 2 | 39 de 40 | 0.01 s | 8 s | 1.5 | 42% | sim | 2.4 GB | 1.8 GB |
| large-v3-turbo | float16 | 4× | 0.5 | 54.6% | 48 | 47 | 15 de 40 | 0.07 s | 11 s | 3.6 | 51% | sim | 2.5 GB | 1.8 GB |
| large-v3-turbo | float16 | 4× | 0.33 | 76.5% | 95 | 73 | 27 de 40 | 0.16 s | 19 s | 2.9 | 61% | sim | 2.6 GB | 1.8 GB |
| large-v3-turbo | float16 | 4× | 0.25 | 83.3% | 81 | 7 | 35 de 40 | 33.59 s | 29 s | 2.1 | 53% | sim | 2.5 GB | 1.8 GB |
| large-v3-turbo | float32 | 1× | 1.0 | 11.6% | 20 | 18 | 0 de 40 | 0.51 s | 27 s | 1.4 | 50% | sim | 4.2 GB | 3.5 GB |
| large-v3-turbo | float32 | 2× | 1.0 | 17.7% | 46 | 15 | 1 de 40 | 0.13 s | 21 s | 2.9 | 44% | sim | 4.3 GB | 3.4 GB |
| large-v3-turbo | float32 | 2× | 0.5 | 16.2% | 26 | 18 | 0 de 40 | 0.10 s | 25 s | 1.6 | 51% | sim | 4.3 GB | 3.5 GB |
| large-v3-turbo | float32 | 4× | 1.0 | 98.4% | 692 | 0 | 40 de 40 | — | 19 s | 1.8 | 42% | sim | 4.4 GB | 3.4 GB |
| large-v3-turbo | float32 | 4× | 0.5 | 57.6% | 85 | 34 | 19 de 40 | 0.25 s | 28 s | 2.4 | 53% | sim | 4.5 GB | 3.4 GB |
| large-v3-turbo | float32 | 4× | 0.33 | 65.1% | 214 | 14 | 24 de 40 | 1.93 s | 28 s | 2.1 | 57% | sim | 4.5 GB | 3.5 GB |
| large-v3-turbo | float32 | 4× | 0.25 | 64.3% | 197 | 10 | 28 de 40 | 0.82 s | 25 s | 1.3 | 52% | sim | 4.5 GB | 3.5 GB |
| large-v3 | float16 | 1× | 1.0 | 12.6% | 27 | 18 | 0 de 40 | 0.89 s | 35 s | 2.1 | 64% | sim | 4.4 GB | 3.3 GB |
| large-v3 | float16 | 2× | 1.0 | 17.0% | 39 | 19 | 0 de 40 | 0.16 s | 37 s | 3.7 | 57% | sim | 4.4 GB | 3.3 GB |
| large-v3 | float16 | 2× | 0.5 | 18.3% | 35 | 23 | 0 de 40 | 0.45 s | 55 s | 2.1 | 71% | sim | 5.5 GB | 3.3 GB |
| large-v3 | float16 | 4× | 1.0 | 80.4% | 110 | 30 | 35 de 40 | 4.49 s | 59 s | 2.7 | 76% | sim | 5.4 GB | 3.3 GB |
| large-v3 | float16 | 4× | 0.5 | 73.6% | 147 | 9 | 29 de 40 | 0.06 s | 44 s | 2.8 | 69% | sim | 5.5 GB | 3.3 GB |
| large-v3 | float16 | 4× | 0.33 | 62.1% | 66 | 30 | 21 de 40 | 0.08 s | 76 s | 2.6 | 77% | sim | 5.5 GB | 3.3 GB |
| large-v3 | float16 | 4× | 0.25 | 69.9% | 218 | 6 | 29 de 40 | 2.27 s | 59 s | 1.7 | 74% | sim | 5.5 GB | 3.3 GB |
| large-v3 | float32 | 1× | 1.0 | 12.1% | 21 | 20 | 0 de 40 | 0.87 s | 63 s | 1.9 | 65% | sim | 8.5 GB | 5.3 GB |
| large-v3 | float32 | 2× | 1.0 | 16.7% | 40 | 19 | 0 de 40 | 0.20 s | 53 s | 4.2 | 70% | sim | 8.7 GB | 6.4 GB |
| large-v3 | float32 | 2× | 0.5 | 21.3% | 38 | 31 | 1 de 40 | 0.06 s | 69 s | 1.5 | 76% | sim | 10.5 GB | 6.4 GB |
| large-v3 | float32 | 4× | 1.0 | 87.0% | 458 | 18 | 34 de 40 | 32.70 s | 28 s | 3.1 | 56% | sim | 8.6 GB | 6.4 GB |
| large-v3 | float32 | 4× | 0.5 | 55.7% | 62 | 23 | 22 de 40 | 0.06 s | 53 s | 3.8 | 68% | sim | 8.7 GB | 6.4 GB |
| large-v3 | float32 | 4× | 0.33 | 62.7% | 120 | 20 | 22 de 40 | 0.73 s | 90 s | 2.8 | 80% | sim | 10.5 GB | 6.4 GB |
| large-v3 | float32 | 4× | 0.25 | 67.8% | 216 | 7 | 28 de 40 | 0.79 s | 113 s | 2.0 | 84% | sim | 10.5 GB | 6.4 GB |
| small | float16 | 1× | 1.0 | 14.6% | 35 | 21 | 0 de 40 | 0.68 s | 13 s | 3.1 | 37% | sim | 0.9 GB | 0.8 GB |
| small | float16 | 2× | 1.0 | 26.4% | 52 | 31 | 2 de 40 | 0.22 s | 9 s | 5.2 | 47% | sim | 0.9 GB | 0.8 GB |
| small | float16 | 2× | 0.5 | 27.0% | 42 | 29 | 0 de 40 | 0.10 s | 11 s | 3.6 | 49% | sim | 0.9 GB | 0.8 GB |
| small | float16 | 4× | 1.0 | 100.0% | 705 | 0 | 40 de 40 | — | 21 s | 1.8 | 61% | sim | 1.0 GB | 0.8 GB |
| small | float16 | 4× | 0.5 | 84.5% | 219 | 17 | 37 de 40 | — | 20 s | 3.9 | 55% | sim | 1.1 GB | 0.8 GB |
| small | float16 | 4× | 0.33 | 88.8% | 333 | 4 | 39 de 40 | — | 29 s | 3.2 | 55% | sim | 1.1 GB | 0.8 GB |
| small | float16 | 4× | 0.25 | 98.2% | 547 | 0 | 40 de 40 | — | 30 s | 2.7 | 55% | sim | 1.1 GB | 0.8 GB |
| parakeet-tdt-0.6b-v3 | int8 (ONNX) | 1× | 1.0 | 14.3% | 31 | 19 | 0 de 40 | 0.03 s | 43 s | 10.8 | 2% | não | — | 1.0 GB |
| parakeet-tdt-0.6b-v3 | int8 (ONNX) | 2× | 1.0 | 36.2% | 100 | 14 | 7 de 40 | 0.03 s | 24 s | 10.6 | 2% | não | — | 1.0 GB |
| parakeet-tdt-0.6b-v3 | int8 (ONNX) | 2× | 0.5 | 37.9% | 102 | 14 | 11 de 40 | 0.03 s | 42 s | 11.0 | 2% | não | — | 1.0 GB |
| parakeet-tdt-0.6b-v3 | int8 (ONNX) | 4× | 1.0 | 99.7% | 634 | 0 | 40 de 40 | — | 15 s | 10.0 | 2% | não | — | 1.0 GB |
| parakeet-tdt-0.6b-v3 | int8 (ONNX) | 4× | 0.5 | 96.5% | 556 | 0 | 40 de 40 | — | 27 s | 10.6 | 3% | sim | 0.0 GB | 0.9 GB |
| parakeet-tdt-0.6b-v3 | int8 (ONNX) | 4× | 0.33 | 96.6% | 560 | 0 | 40 de 40 | — | 36 s | 10.7 | 2% | não | — | 1.0 GB |
| parakeet-tdt-0.6b-v3 | int8 (ONNX) | 4× | 0.25 | 98.2% | 588 | 0 | 40 de 40 | — | 42 s | 10.8 | 2% | não | — | 1.0 GB |

Critério 12 (4×: WER ≤ 2 × WER em 1× e ≤ 30%, sem trecho perdido, timestamp ≤ 1 s, sem texto inventado):
0 combinações aprovadas. Melhor 4× na tabela: large-v3-turbo float16 preparação 0.5 (54.6%). **Nenhuma aprovada → 4× Ultra é oferecido como experimental.**

### 4×: Rubber Band (FFmpeg do sistema) e condition_on_previous_text=False

| Modelo | Preparação | Método | WER | Omissões | Inserções | Timestamp |
|---|---|---|---|---|---|---|
| large-v3-turbo | 0.5 | rubberband | 64.3% | 65 | 30 | 0.34 s |
| large-v3-turbo | 0.5 | atempo, cond_prev=False | 53.2% | 92 | 32 | 0.07 s |
| large-v3-turbo | 0.33 | rubberband | 80.1% | 119 | 105 | 2.20 s |
| large-v3-turbo | 0.33 | atempo, cond_prev=False | 56.6% | 116 | 20 | 0.36 s |
| large-v3-turbo | 0.25 | rubberband | 64.4% | 143 | 23 | 3.25 s |
| large-v3-turbo | 0.25 | atempo, cond_prev=False | 66.8% | 208 | 10 | 0.84 s |
| large-v3 | 0.5 | rubberband | 72.3% | 196 | 19 | 0.14 s |
| large-v3 | 0.5 | atempo, cond_prev=False | 59.6% | 156 | 11 | 0.33 s |
| large-v3 | 0.33 | rubberband | 71.5% | 239 | 19 | 0.41 s |
| large-v3 | 0.33 | atempo, cond_prev=False | 56.9% | 87 | 27 | 0.16 s |
| large-v3 | 0.25 | rubberband | 80.9% | 351 | 8 | — |
| large-v3 | 0.25 | atempo, cond_prev=False | 65.0% | 200 | 14 | 0.62 s |

### Automático com 4× (palavras/s em janelas de 120 s; critério 13)

- 1x: 1.48 a 2.90
- 2x: 3.00 a 5.52
- 4x: 0.06 a 8.56
- 4x_depois_0.5: 2.25 a 4.96
- 2x_depois_0.5: 1.51 a 2.84

Em 4× o modelo muitas vezes quase não reconhece nada (taxa perto de 0), e depois de desacelerar 0,5× as faixas de 2× e 4× se sobrepõem. **O Automático não identifica 4× com segurança**: sugere 2× quando a fala é rápida, marca como incerto quando quase nada é reconhecido e pede a confirmação do usuário.

### Responsividade (critério 15; 120 s de aula na CPU)

| Modelo | Núcleos lógicos reservados | Prioridade baixa | Tempo | API p95 | Outro programa fica |
|---|---|---|---|---|---|
| large-v3-turbo | 0 | não | 60.3 s | 12 ms | 1.82× mais lento |
| large-v3-turbo | 2 | sim | 63.6 s | 12 ms | 1.77× mais lento |
| large-v3-turbo | 6 | sim | 65.6 s | 4 ms | 1.36× mais lento |
| large-v3-turbo | 8 | não | 67.7 s | 3 ms | 1.23× mais lento |
| parakeet-tdt-0.6b-v3 | 0 | não | 18.7 s | 144 ms | 2.91× mais lento |
| parakeet-tdt-0.6b-v3 | 0 | sim | 17.2 s | 119 ms | 2.84× mais lento |
| parakeet-tdt-0.6b-v3 | 2 | não | 13.7 s | 287 ms | 2.56× mais lento |
| parakeet-tdt-0.6b-v3 | 2 | sim | 14.3 s | 84 ms | 2.77× mais lento |
| parakeet-tdt-0.6b-v3 | 4 | não | 12.2 s | 189 ms | 2.03× mais lento |
| parakeet-tdt-0.6b-v3 | 4 | sim | 12.4 s | 79 ms | 2.15× mais lento |
| parakeet-tdt-0.6b-v3 | 6 | não | 11.1 s | 55 ms | 1.73× mais lento |
| parakeet-tdt-0.6b-v3 | 6 | sim | 10.8 s | 59 ms | 1.81× mais lento |
| parakeet-tdt-0.6b-v3 | 8 | não | 9.5 s | 34 ms | 1.44× mais lento |
| parakeet-tdt-0.6b-v3 | 8 | sim | 9.6 s | 60 ms | 1.57× mais lento |

### Inferência em lotes (BatchedInferencePipeline, turbo na GPU)

| Velocidade | Lote | WER | Tempo | GPU% | Timestamp |
|---|---|---|---|---|---|
| 1× | sequencial (app) | 11.5% | 10.0 s | 63% | 0.50 s |
| 1× | 8 | 13.2% | 4.9 s | 67% | 16.84 s |
| 1× | 16 | 13.0% | 4.5 s | 64% | 16.84 s |
| 2× | sequencial (app) | 16.2% | 10.1 s | 62% | 0.07 s |
| 2× | 8 | 17.0% | 4.6 s | 73% | 9.32 s |
| 2× | 16 | 16.9% | 4.5 s | 64% | 9.32 s |

Lotes: 2× mais rápido, mas WER pior e timestamps grosseiros (segmentos longos) → **não adotado** (critério 14).

Variação entre execuções: com o fallback de temperatura do Whisper, a mesma configuração pode mudar de uma rodada para outra (ex.: large-v3 2× desacelerado deu 26,7% numa execução e 17,3% na seguinte). Diferenças menores que ~1 ponto não devem ser lidas como vitória.

## Configuração

A tabela principal usou `condition_on_previous_text=False` em todos os Whisper. Pela auditoria acima, o app mantém `True` (aula longa do turbo: 11,5% em vez de 12,8%). Na GPU, o app também roda o whisper-small como segundo modelo, só para marcar trechos divergentes (limite 0,2, conforme o adendo dos critérios).

- **whisper-small**: `small` em cuda; language=pt, beam_size=5, vad_filter=True, condition_on_previous_text=False; carga 2 s.
- **whisper-medium**: `medium` em cuda; language=pt, beam_size=5, vad_filter=True, condition_on_previous_text=False; carga 23 s.
- **whisper-large-v3-turbo**: `large-v3-turbo` em cuda; language=pt, beam_size=5, vad_filter=True, condition_on_previous_text=False; carga 4 s.
- **whisper-large-v3**: `large-v3` em cuda; language=pt, beam_size=5, vad_filter=True, condition_on_previous_text=False; carga 45 s.
- **whisper-small-cpu**: `small` em cpu; language=pt, beam_size=5, vad_filter=True, condition_on_previous_text=False; carga 3 s.
- **whisper-large-v3-turbo-cpu**: `large-v3-turbo` em cpu; language=pt, beam_size=5, vad_filter=True, condition_on_previous_text=False; carga 5 s.
- **parakeet-tdt-0.6b-v3**: `nemo-parakeet-tdt-0.6b-v3` em cpu; language=pt, int8, Silero VAD no áudio longo; carga 20 s.
- **canary-1b-v2**: `nemo-canary-1b-v2` em cpu; language=pt, int8, Silero VAD no áudio longo; carga 20 s.
