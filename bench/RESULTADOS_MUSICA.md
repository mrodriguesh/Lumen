# Filtro de música externa: transcrição sem × com o filtro

Gerado por `python -m bench.music_bench run` e `report`. ASR: large-v3-turbo (como o app, GPU). Detector: YAMNet. Separador: UVR_MDXNET_3_9662.onnx. Modo: balanceado. Fala: FLEURS/CORAA (falas B, nunca usadas no treino da sonda); música: MUSDB18 test (nunca usada no treino) e sintética.

- **WER**: erros de palavra contra a transcrição humana (bench/metrics.py). Menor é melhor.
- **Palavras da fala perdidas**: omissões (D) do alinhamento; mede fala apagada.
- **Letra infiltrada**: palavras da letra da música (o que o ASR ouve na voz da música sozinha) que aparecem na transcrição e não estão na fala.
- **Confiança do ASR**: média do log da probabilidade dos trechos (avg_logprob; mais perto de 0 = mais confiante).

## Volume da música em relação à fala

### Música instrumental

| Música vs. fala | n | WER sem filtro | WER com filtro | Palavras da fala perdidas | Letra infiltrada | Palavras na saída | Confiança do ASR | Áudio removido | Trechos marcados |
|---|---|---|---|---|---|---|---|---|---|
| -15 dB | 10 | 5,5% | 5,5% | 3 → 3 | 0 → 0 | 233 → 233 | -0,13 → -0,13 | 0,0% | 0 |
| -10 dB | 10 | 5,1% | 5,1% | 1 → 1 | 0 → 0 | 235 → 235 | -0,14 → -0,14 | 0,0% | 0 |
| -5 dB | 10 | 6,8% | 6,8% | 1 → 1 | 0 → 0 | 235 → 235 | -0,18 → -0,18 | 0,0% | 0 |
| +0 dB | 10 | 12,3% | 12,3% | 11 → 11 | 0 → 0 | 226 → 226 | -0,25 → -0,25 | 0,0% | 2 |
| +5 dB | 10 | 75,7% | 51,5% | 85 → 52 | 0 → 0 | 195 → 190 | -0,48 → -0,45 | 0,0% | 1 |
| +10 dB | 10 | 69,4% | 53,2% | 137 → 30 | 0 → 0 | 99 → 220 | -0,52 → -0,56 | 0,0% | 2 |
| +15 dB | 10 | 100,0% | 86,4% | 235 → 68 | 0 → 0 | 0 → 193 | – → -1,05 | 0,0% | 1 |

### Música com voz cantada

| Música vs. fala | n | WER sem filtro | WER com filtro | Palavras da fala perdidas | Letra infiltrada | Palavras na saída | Confiança do ASR | Áudio removido | Trechos marcados |
|---|---|---|---|---|---|---|---|---|---|
| -15 dB | 10 | 5,5% | 5,5% | 2 → 2 | 0 → 0 | 234 → 234 | -0,14 → -0,14 | 0,0% | 0 |
| -10 dB | 10 | 6,0% | 6,0% | 1 → 1 | 0 → 0 | 235 → 235 | -0,14 → -0,14 | 0,0% | 0 |
| -5 dB | 10 | 14,5% | 14,5% | 6 → 6 | 0 → 0 | 232 → 232 | -0,31 → -0,31 | 0,0% | 0 |
| +0 dB | 10 | 35,7% | 35,7% | 19 → 19 | 0 → 0 | 229 → 229 | -0,42 → -0,42 | 0,0% | 1 |
| +5 dB | 10 | 74,9% | 74,9% | 117 → 117 | 3 → 3 | 130 → 130 | -0,57 → -0,57 | 0,0% | 1 |
| +10 dB | 10 | 99,1% | 99,1% | 182 → 182 | 28 → 28 | 54 → 54 | -0,96 → -0,96 | 0,0% | 8 |
| +15 dB | 10 | 104,3% | 104,3% | 201 → 201 | 31 → 31 | 44 → 44 | -0,66 → -0,66 | 0,0% | 5 |

## Cenários

| Cenário | n | WER sem filtro | WER com filtro | Palavras da fala perdidas | Letra infiltrada | Palavras na saída | Confiança do ASR | Áudio removido | Trechos marcados |
|---|---|---|---|---|---|---|---|---|---|
| 1 fala sozinha | 20 | 2,2% | 2,2% | 1 → 1 | 0 → 0 | 489 → 489 | -0,09 → -0,09 | 0,0% | 0 |
| 2 música sozinha | 10 | – | – | – → – | 52 → 52 | 65 → 65 | -0,39 → -0,39 | 0,0% | 5 |
| 2 música sozinha (rap) | 1 | – | – | – → – | 4 → 4 | 4 → 4 | -1,54 → -1,54 | 0,0% | 0 |
| 6 fala + rap | 30 | 83,3% | 83,3% | 16 → 16 | 285 → 285 | 918 → 918 | -0,57 → -0,57 | 0,0% | 2 |
| 7 música liga e desliga (detector acompanhou 93% dos quadros) | 3 | 43,6% | 43,6% | 76 → 76 | 0 → 0 | 332 → 332 | -0,54 → -0,54 | 0,0% | 3 |
| 8 silêncio | 3 | – | – | – → – | 0 → 0 | 0 → 0 | – → – | 0,0% | 0 |
| 9 ruído: fan | 10 | 3,8% | 3,8% | 2 → 2 | 0 → 0 | 234 → 234 | -0,10 → -0,10 | 0,0% | 0 |
| 9 ruído: keyboard | 10 | 3,4% | 3,4% | 1 → 1 | 0 → 0 | 235 → 235 | -0,10 → -0,10 | 0,0% | 0 |
| 9 ruído: babble | 10 | 11,5% | 11,5% | 2 → 2 | 0 → 0 | 241 → 241 | -0,20 → -0,20 | 0,0% | 0 |
| 10 trilha do vídeo | 3 | 20,7% | 20,7% | 38 → 38 | 0 → 0 | 234 → 234 | -0,18 → -0,18 | 0,0% | 0 |
| 27 piano sintético | 12 | 57,9% | 57,9% | 158 → 158 | 0 → 0 | 135 → 135 | -0,23 → -0,23 | 0,0% | 7 |
| 27 electro sintético | 12 | 27,1% | 27,1% | 47 → 47 | 0 → 0 | 247 → 247 | -0,29 → -0,29 | 0,0% | 7 |
| 27 violão/acústica | 6 | 13,7% | 13,7% | 2 → 2 | 0 → 0 | 146 → 146 | -0,20 → -0,20 | 0,0% | 0 |
| 27 eletrônica real | 6 | 17,8% | 17,8% | 4 → 4 | 0 → 0 | 145 → 145 | -0,33 → -0,33 | 0,0% | 0 |
| 27 música liga/desliga rápido | 6 | 16,4% | 16,4% | 7 → 7 | 1 → 1 | 140 → 140 | -0,26 → -0,26 | 0,0% | 0 |
| 27 fala 2× + música | 6 | 97,3% | 97,3% | 18 → 18 | 10 → 10 | 162 → 162 | -0,75 → -0,75 | 0,0% | 0 |

## Desempenho (pior caso: música com voz a aula toda, 10 min; `perf gpu`, `perf cpu`)

| | Tempo | × tempo real | CPU (s) | Núcleos em média | RAM de pico (antes) | VRAM extra |
|---|---|---|---|---|---|---|
| GPU | 28,3 s | 21,2 | 40,6 | 1,4 | 805 MB (447 MB) | 556 MB |
| CPU | 163,2 s | 3,7 | 911,9 | 5,6 | 1054 MB (447 MB) | – |

Saída da GPU × da CPU: diferença máxima 0 (a GPU não muda o resultado).

- Modelos: 72,3 MB. Mesmo áudio de novo: 0,15 s (cache).
- i5-11400F (6 núcleos/12 threads) e RTX 3060 via DirectML (onnxruntime-directml).
- Sem música, ou com a fala clara por cima dela: só o detector roda (≈ 750× o tempo real; 1 h ≈ 5 s).

## Leitura

- Fala sozinha, silêncio, ventilador, teclado, conversa ao fundo e música até 0 dB: transcrição idêntica à sem filtro (o filtro não troca o áudio).
- Instrumental alto (+5 a +15 dB): o filtro recupera boa parte da fala que a música cobria.
- Música com letra e rap: o filtro não piora, mas também não tira a letra que o ASR transcreve; esses trechos ficam marcados como “música ao fundo”. A proteção contra letra é não gravar o app de música (isolamento da fonte, medido à parte: o tom do “app de música” some da gravação e o da aula fica).
- Sem recuperação possível (fala 2× sob música, voz cantada a +10 dB): o filtro não inventa texto; a transcrição fica como sem o filtro.
- As versões anteriores pioravam e foram descartadas (docs/DECISOES.md): voz separada em todo trecho com música fazia o ASR transcrever a letra (música sozinha 0 → 18 e 14 → 48 palavras; cantada a +10 dB, 28 → 133); silenciar onde a sonda via só música apagou fala sob piano e eletrônica (0/18 → 18/18 erros).
