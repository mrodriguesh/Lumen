# Filtro de música v2: aulas com professor (antes × depois)

Gerado por `python -m bench.music_bench run2 antes` (com a v1 congelada), `run2 depois` e `report2`. ASR: large-v3-turbo. Fala: 16 palestras do CORAA (TEDx; cada uma é um “professor”, ≈ 60 s por aula, metade sem música); música: MUSDB18 test, GTZAN 50–99 (hip-hop, clássica, outros gêneros). Nada disso foi usado no treino da sonda.

- **WER**: erros de palavra contra a transcrição humana. **Perdidas**: palavras da fala omitidas.
- **Letra livre**: palavras da letra que chegam à transcrição *sem* marca de “música ao fundo” (vão para a IA como fato). Letra marcada chega como “(?)”.
- **Fala marcada**: palavras da aula marcadas como dúvida (vão para a IA como “(?)”).

## Modo conservador

| Cenário | n | WER sem filtro | WER v1 | WER v2 | Perdidas sem → v1 → v2 | Letra livre sem → v1 → v2 | Fala marcada v1 → v2 | Removido v1 → v2 (s) |
|---|---|---|---|---|---|---|---|---|
| A professor sozinho | 6 | 14,9% | 14,9% | 14,9% | 38 → 38 → 38 | 0 → 0 → 0 | 0 → 0 | 0 → 0 |
| B professor + instrumental (+0 dB) | 6 | 26,0% | 25,2% | 23,4% | 93 → 83 → 74 | 0 → 0 → 0 | 78 → 6 | 0 → 0 |
| B professor + instrumental (+5 dB) | 6 | 52,8% | 40,1% | 29,6% | 381 → 153 → 101 | 0 → 0 → 0 | 45 → 40 | 0 → 0 |
| B professor + instrumental (+10 dB) | 6 | 60,1% | 49,1% | 45,3% | 481 → 256 → 132 | 0 → 0 → 0 | 8 → 84 | 0 → 0 |
| B2 instrumental a aula toda (+5 dB) | 6 | 88,0% | 45,2% | 43,7% | 632 → 257 → 231 | 0 → 0 → 0 | 139 → 208 | 0 → 0 |
| C professor + cantor (+0 dB) | 6 | 43,7% | 43,7% | 43,7% | 76 → 76 → 76 | 7 → 4 → 7 | 41 → 8 | 0 → 0 |
| C professor + cantor (+5 dB) | 6 | 64,9% | 64,9% | 64,9% | 336 → 336 → 336 | 0 → 0 → 0 | 57 → 29 | 0 → 0 |
| D professor + rap (+0 dB) | 6 | 18,3% | 18,3% | 18,3% | 43 → 43 → 43 | 0 → 0 → 0 | 67 → 68 | 0 → 0 |
| D professor + rap (+5 dB) | 6 | 38,5% | 36,1% | 36,0% | 61 → 62 → 59 | 37 → 18 → 2 | 76 → 143 | 0 → 0 |
| D2 rap a aula toda (+0 dB) | 6 | 28,9% | 28,9% | 28,9% | 91 → 91 → 91 | 0 → 0 → 0 | 5 → 141 | 0 → 0 |
| E dois professores (+5 dB) | 4 | 56,2% | 39,6% | 35,1% | 520 → 253 → 207 | 0 → 0 → 0 | 83 → 33 | 0 → 0 |
| F professor novo (sob instrumental) (+5 dB) | 4 | 57,8% | 49,7% | 46,4% | 318 → 243 → 219 | 0 → 0 → 0 | 33 → 57 | 0 → 0 |
| F professor novo (sob cantor) (+0 dB) | 4 | 58,8% | 58,8% | 58,8% | 231 → 231 → 231 | 0 → 0 → 0 | 24 → 20 | 0 → 0 |
| G professor + clássica (+0 dB) | 6 | 31,7% | 31,7% | 16,7% | 59 → 59 → 58 | 0 → 0 → 0 | 150 → 55 | 0 → 0 |
| G professor + clássica (+5 dB) | 6 | 35,5% | 35,5% | 27,0% | 161 → 161 → 139 | 0 → 0 → 0 | 134 → 44 | 0 → 0 |
| G professor + clássica (+10 dB) | 6 | 49,3% | 46,3% | 30,5% | 258 → 262 → 173 | 0 → 0 → 0 | 104 → 52 | 0 → 0 |
| H música entre as falas (cantor) (+0 dB) | 4 | 44,3% | 44,3% | 44,3% | 52 → 52 → 52 | 4 → 0 → 0 | 97 → 121 | 0 → 0 |
| H música entre as falas (rap) (+0 dB) | 4 | 18,7% | 19,6% | 18,7% | 38 → 42 → 38 | 0 → 0 → 0 | 159 → 239 | 0 → 0 |
| I podcast com trilha | 4 | 8,8% | 8,8% | 8,8% | 22 → 22 → 22 | 0 → 0 → 0 | 0 → 0 | 0 → 0 |
| J professor demonstra música | 4 | 12,1% | 12,1% | 12,1% | 23 → 23 → 23 | 0 → 0 → 0 | 20 → 20 | 0 → 0 |
| K coral sozinho | 4 | – | – | – | – → – → – | 35 → 0 → 0 | 0 → 0 | 0 → 0 |
| K professor + coral (+0 dB) | 4 | 19,4% | 19,4% | 19,4% | 56 → 56 → 56 | 1 → 1 → 1 | 83 → 43 | 0 → 0 |
| L voz cantada sem instrumentos | 4 | – | – | – | – → – → – | 106 → 90 → 90 | 0 → 0 | 0 → 0 |
| L professor + a cappella (+0 dB) | 4 | 35,4% | 35,4% | 35,4% | 26 → 26 → 26 | 0 → 0 → 0 | 9 → 5 | 0 → 0 |
| M instrumental sem voz | 3 | – | – | – | – → – → – | 0 → 0 → 0 | 0 → 0 | 0 → 0 |
| M clássica sem voz | 3 | – | – | – | – → – → – | 0 → 0 → 0 | 0 → 0 | 0 → 0 |
| N professor rápido (1,5×) (+5 dB) | 4 | 49,3% | 34,7% | 34,5% | 277 → 99 → 100 | 0 → 0 → 0 | 48 → 29 | 0 → 0 |
| O professor baixo (+5 dB) | 4 | 40,8% | 40,8% | 42,2% | 146 → 146 → 153 | 0 → 0 → 0 | 25 → 106 | 0 → 0 |
| P várias pessoas (+5 dB) | 4 | 45,7% | 44,1% | 45,2% | 131 → 108 → 105 | 0 → 0 → 0 | 5 → 0 | 0 → 0 |
| Q spoken word sobre a aula (+0 dB) | 4 | 40,3% | 40,3% | 40,3% | 40 → 40 → 40 | 48 → 42 → 43 | 28 → 20 | 0 → 0 |
| R gêneros (+5 dB) | 8 | 47,6% | 44,0% | 42,7% | 336 → 293 → 290 | 15 → 4 → 15 | 129 → 66 | 0 → 0 |

## Modo balanceado

| Cenário | n | WER sem filtro | WER v1 | WER v2 | Perdidas sem → v1 → v2 | Letra livre sem → v1 → v2 | Fala marcada v1 → v2 | Removido v1 → v2 (s) |
|---|---|---|---|---|---|---|---|---|
| A professor sozinho | 6 | 14,9% | 14,9% | 14,9% | 38 → 38 → 38 | 0 → 0 → 0 | 0 → 0 | 0 → 0 |
| B professor + instrumental (+0 dB) | 6 | 26,0% | 24,0% | 23,4% | 93 → 74 → 74 | 0 → 0 → 0 | 39 → 2 | 0 → 0 |
| B professor + instrumental (+5 dB) | 6 | 52,8% | 31,2% | 30,9% | 381 → 110 → 98 | 0 → 0 → 0 | 52 → 11 | 0 → 0 |
| B professor + instrumental (+10 dB) | 6 | 60,1% | 58,5% | 44,8% | 481 → 106 → 135 | 0 → 0 → 0 | 24 → 29 | 0 → 0 |
| B2 instrumental a aula toda (+5 dB) | 6 | 88,0% | 39,9% | 41,3% | 632 → 210 → 208 | 0 → 0 → 0 | 97 → 82 | 0 → 0 |
| C professor + cantor (+0 dB) | 6 | 43,7% | 43,7% | 43,7% | 76 → 76 → 76 | 7 → 5 → 7 | 9 → 0 | 0 → 0 |
| C professor + cantor (+5 dB) | 6 | 64,9% | 64,9% | 64,9% | 336 → 336 → 336 | 0 → 0 → 0 | 4 → 0 | 0 → 0 |
| D professor + rap (+0 dB) | 6 | 18,3% | 18,3% | 18,3% | 43 → 43 → 43 | 0 → 0 → 0 | 38 → 46 | 0 → 0 |
| D professor + rap (+5 dB) | 6 | 38,5% | 38,9% | 38,5% | 61 → 60 → 63 | 37 → 30 → 16 | 49 → 114 | 0 → 0 |
| D2 rap a aula toda (+0 dB) | 6 | 28,9% | 28,9% | 28,9% | 91 → 91 → 91 | 0 → 0 → 0 | 5 → 98 | 0 → 0 |
| E dois professores (+5 dB) | 4 | 56,2% | 38,3% | 32,8% | 520 → 154 → 157 | 0 → 0 → 0 | 18 → 57 | 0 → 0 |
| F professor novo (sob instrumental) (+5 dB) | 4 | 57,8% | 41,5% | 56,1% | 318 → 187 → 157 | 0 → 0 → 0 | 0 → 74 | 0 → 0 |
| F professor novo (sob cantor) (+0 dB) | 4 | 58,8% | 58,8% | 58,8% | 231 → 231 → 231 | 0 → 0 → 0 | 4 → 9 | 0 → 0 |
| G professor + clássica (+0 dB) | 6 | 31,7% | 31,7% | 16,7% | 59 → 59 → 58 | 0 → 0 → 0 | 116 → 55 | 0 → 0 |
| G professor + clássica (+5 dB) | 6 | 35,5% | 30,2% | 26,3% | 161 → 180 → 135 | 0 → 0 → 0 | 55 → 35 | 0 → 0 |
| G professor + clássica (+10 dB) | 6 | 49,3% | 39,9% | 28,9% | 258 → 244 → 159 | 0 → 0 → 0 | 59 → 16 | 0 → 0 |
| H música entre as falas (cantor) (+0 dB) | 4 | 44,3% | 44,3% | 44,3% | 52 → 52 → 52 | 4 → 0 → 0 | 35 → 62 | 0 → 0 |
| H música entre as falas (rap) (+0 dB) | 4 | 18,7% | 30,1% | 18,7% | 38 → 43 → 38 | 0 → 0 → 0 | 79 → 201 | 0 → 0 |
| I podcast com trilha | 4 | 8,8% | 8,8% | 8,8% | 22 → 22 → 22 | 0 → 0 → 0 | 0 → 0 | 0 → 0 |
| J professor demonstra música | 4 | 12,1% | 12,1% | 12,1% | 23 → 23 → 23 | 0 → 0 → 0 | 20 → 20 | 0 → 0 |
| K coral sozinho | 4 | – | – | – | – → – → – | 35 → 0 → 0 | 0 → 0 | 0 → 0 |
| K professor + coral (+0 dB) | 4 | 19,4% | 19,4% | 19,4% | 56 → 56 → 56 | 1 → 1 → 1 | 83 → 34 | 0 → 0 |
| L voz cantada sem instrumentos | 4 | – | – | – | – → – → – | 106 → 90 → 90 | 0 → 0 | 0 → 0 |
| L professor + a cappella (+0 dB) | 4 | 35,4% | 35,4% | 35,4% | 26 → 26 → 26 | 0 → 0 → 0 | 9 → 4 | 0 → 0 |
| M instrumental sem voz | 3 | – | – | – | – → – → – | 0 → 0 → 0 | 0 → 0 | 0 → 0 |
| M clássica sem voz | 3 | – | – | – | – → – → – | 0 → 0 → 0 | 0 → 0 | 0 → 0 |
| N professor rápido (1,5×) (+5 dB) | 4 | 49,3% | 34,2% | 35,4% | 277 → 99 → 95 | 0 → 0 → 0 | 22 → 23 | 0 → 0 |
| O professor baixo (+5 dB) | 4 | 40,8% | 40,8% | 42,2% | 146 → 146 → 145 | 0 → 0 → 0 | 25 → 93 | 0 → 0 |
| P várias pessoas (+5 dB) | 4 | 45,7% | 45,5% | 45,5% | 131 → 105 → 106 | 0 → 0 → 0 | 5 → 0 | 0 → 0 |
| Q spoken word sobre a aula (+0 dB) | 4 | 40,3% | 40,3% | 40,3% | 40 → 40 → 40 | 48 → 47 → 47 | 13 → 7 | 0 → 0 |
| R gêneros (+5 dB) | 8 | 47,6% | 43,2% | 43,0% | 336 → 287 → 286 | 15 → 15 → 15 | 65 → 47 | 0 → 0 |

## Modo agressivo

| Cenário | n | WER sem filtro | WER v1 | WER v2 | Perdidas sem → v1 → v2 | Letra livre sem → v1 → v2 | Fala marcada v1 → v2 | Removido v1 → v2 (s) |
|---|---|---|---|---|---|---|---|---|
| A professor sozinho | 6 | 14,9% | 14,8% | 14,9% | 38 → 37 → 38 | 0 → 0 → 0 | 0 → 0 | 6,7 → 0 |
| B professor + instrumental (+0 dB) | 6 | 26,0% | 23,8% | 22,6% | 93 → 74 → 70 | 0 → 0 → 0 | 40 → 20 | 13,4 → 3,4 |
| B professor + instrumental (+5 dB) | 6 | 52,8% | 31,8% | 27,0% | 381 → 117 → 68 | 0 → 0 → 0 | 45 → 41 | 13 → 4,3 |
| B professor + instrumental (+10 dB) | 6 | 60,1% | 58,2% | 44,2% | 481 → 98 → 137 | 0 → 0 → 0 | 27 → 85 | 9,6 → 8,6 |
| B2 instrumental a aula toda (+5 dB) | 6 | 88,0% | 38,6% | 25,1% | 632 → 200 → 90 | 0 → 0 → 0 | 102 → 127 | 24 → 24 |
| C professor + cantor (+0 dB) | 6 | 43,7% | 42,1% | 43,7% | 76 → 78 → 76 | 7 → 4 → 0 | 9 → 154 | 6,7 → 0 |
| C professor + cantor (+5 dB) | 6 | 64,9% | 64,9% | 64,9% | 336 → 336 → 341 | 0 → 0 → 0 | 4 → 163 | 6,7 → 31,7 |
| D professor + rap (+0 dB) | 6 | 18,3% | 18,3% | 18,4% | 43 → 43 → 42 | 0 → 0 → 0 | 38 → 58 | 0 → 0 |
| D professor + rap (+5 dB) | 6 | 38,5% | 36,9% | 36,4% | 61 → 64 → 177 | 37 → 18 → 0 | 35 → 78 | 3,8 → 35,6 |
| D2 rap a aula toda (+0 dB) | 6 | 28,9% | 28,9% | 28,7% | 91 → 91 → 51 | 0 → 0 → 2 | 5 → 111 | 0 → 0 |
| E dois professores (+5 dB) | 4 | 56,2% | 33,3% | 49,5% | 520 → 173 → 134 | 0 → 0 → 0 | 5 → 119 | 6,7 → 0 |
| F professor novo (sob instrumental) (+5 dB) | 4 | 57,8% | 41,4% | 41,7% | 318 → 179 → 167 | 0 → 0 → 0 | 7 → 124 | 43,2 → 36 |
| F professor novo (sob cantor) (+0 dB) | 4 | 58,8% | 58,8% | 58,6% | 231 → 231 → 234 | 0 → 0 → 0 | 4 → 74 | 6,7 → 21,1 |
| G professor + clássica (+0 dB) | 6 | 31,7% | 18,6% | 18,8% | 59 → 65 → 92 | 0 → 0 → 0 | 100 → 14 | 14,4 → 9,1 |
| G professor + clássica (+5 dB) | 6 | 35,5% | 30,1% | 22,0% | 161 → 179 → 126 | 0 → 0 → 0 | 55 → 26 | 10,1 → 17,3 |
| G professor + clássica (+10 dB) | 6 | 49,3% | 40,2% | 30,5% | 258 → 251 → 177 | 0 → 0 → 0 | 51 → 25 | 22,1 → 26,4 |
| H música entre as falas (cantor) (+0 dB) | 4 | 44,3% | 44,3% | 42,1% | 52 → 52 → 54 | 4 → 0 → 0 | 35 → 57 | 0 → 8,2 |
| H música entre as falas (rap) (+0 dB) | 4 | 18,7% | 31,3% | 19,6% | 38 → 45 → 36 | 0 → 0 → 0 | 77 → 180 | 7,2 → 59,6 |
| I podcast com trilha | 4 | 8,8% | 9,0% | 8,8% | 22 → 21 → 22 | 0 → 0 → 0 | 0 → 0 | 33,6 → 30,3 |
| J professor demonstra música | 4 | 12,1% | 12,1% | 14,0% | 23 → 23 → 33 | 0 → 0 → 0 | 20 → 9 | 6,7 → 21,6 |
| K coral sozinho | 4 | – | – | – | – → – → – | 35 → 27 → 0 | 0 → 0 | 35 → 0 |
| K professor + coral (+0 dB) | 4 | 19,4% | 23,6% | 19,4% | 56 → 81 → 56 | 1 → 1 → 1 | 62 → 38 | 11,5 → 0 |
| L voz cantada sem instrumentos | 4 | – | – | – | – → – → – | 106 → 90 → 90 | 0 → 0 | 17,8 → 0 |
| L professor + a cappella (+0 dB) | 4 | 35,4% | 35,4% | 35,4% | 26 → 26 → 26 | 0 → 0 → 0 | 9 → 18 | 0 → 0 |
| M instrumental sem voz | 3 | – | – | – | – → – → – | 0 → 0 → 0 | 0 → 0 | 60 → 0 |
| M clássica sem voz | 3 | – | – | – | – → – → – | 0 → 0 → 0 | 0 → 0 | 56 → 0 |
| N professor rápido (1,5×) (+5 dB) | 4 | 49,3% | 34,2% | 32,6% | 277 → 99 → 89 | 0 → 0 → 0 | 22 → 25 | 0 → 0 |
| O professor baixo (+5 dB) | 4 | 40,8% | 41,6% | 50,4% | 146 → 135 → 248 | 0 → 0 → 0 | 25 → 34 | 7,2 → 31,7 |
| P várias pessoas (+5 dB) | 4 | 45,7% | 45,5% | 38,7% | 131 → 105 → 91 | 0 → 0 → 0 | 5 → 17 | 0 → 0 |
| Q spoken word sobre a aula (+0 dB) | 4 | 40,3% | 46,7% | 40,3% | 40 → 52 → 40 | 48 → 70 → 18 | 13 → 132 | 6,7 → 0 |
| R gêneros (+5 dB) | 8 | 47,6% | 42,8% | 43,4% | 336 → 280 → 263 | 15 → 15 → 15 | 79 → 83 | 9,6 → 20,6 |

## Resumo por modo

| Modo | Versão | WER (aulas com fala) | Perdidas | Letra livre | Fala marcada | Falsos positivos | Falsos negativos | Tempo do filtro (s) |
|---|---|---|---|---|---|---|---|---|
| (sem filtro) | – | 42,2% | 4926 | 253 | 0 | – | – | – |
| conservador | v1 | 37,1% | 3511 | 159 | 1647 | 0/20 | 6/132 | 272 |
| conservador | v2 | 34,3% | 3113 | 158 | 1637 | 0/20 | 4/132 | 64 |
| balanceado | v1 | 36,3% | 3098 | 188 | 925 | 0/20 | 6/132 | 21 |
| balanceado | v2 | 34,5% | 2948 | 176 | 1119 | 0/20 | 4/132 | 63 |
| agressivo | v1 | 35,7% | 3135 | 225 | 874 | 12/20 | 6/132 | 19 |
| agressivo | v2 | 34,1% | 2978 | 126 | 1812 | 6/20 | 4/132 | 66 |
