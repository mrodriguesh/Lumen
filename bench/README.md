# Benchmark de transcrição local (pt-BR)

Compara modelos de reconhecimento de fala **locais e gratuitos** no mesmo áudio, com as mesmas opções, e aplica
critérios fixados antes dos resultados ([CRITERIOS.md](CRITERIOS.md)). O resultado atual está em
[RESULTADOS.md](RESULTADOS.md).

## Repetir

```
.venv\Scripts\python -m pip install -r requirements-bench.txt     # onnx-asr (MIT), só para Parakeet/Canary
.venv\Scripts\python -m bench.asr_bench fetch                     # ~80 MB em bench/.data (fora do Git)
.venv\Scripts\python -m bench.asr_bench build
.venv\Scripts\python -m bench.asr_bench run whisper-large-v3-turbo # um modelo por vez (ver MODELS em asr_bench.py)
.venv\Scripts\python -m bench.asr_bench speed whisper-large-v3-turbo
.venv\Scripts\python -m bench.asr_bench variants
.venv\Scripts\python -m bench.asr_bench report
```

Os modelos são baixados para o cache do Hugging Face (`%USERPROFILE%\.cache\huggingface`), não para o projeto.
Tamanhos: small 0,48 GB, medium 1,5 GB, large-v3-turbo 1,6 GB, large-v3 3,1 GB, Parakeet int8 0,67 GB,
Canary int8 1,0 GB. Para liberar espaço depois, apague as pastas `models--*` que não usar.

## Leitura da tela (Assistir a tela junto)

```
.venv\Scripts\python -m bench.vision_bench make              # desenha as 18 telas de teste (Edge headless)
.venv\Scripts\python -m bench.vision_bench run qwen3.5:4b    # um modelo do Ollama; largura opcional (padrão 1280)
.venv\Scripts\python -m bench.vision_bench report
```

Usa exatamente o pedido e o filtro do app (`lumen/vision.py`). Métricas: palavras do gabarito encontradas no texto
lido, decisão de guardar ou descartar, textos que não podiam aparecer (recomendações, notificação, anúncio) e tempo.

## Filtro de música externa

```
.venv\Scripts\python -m bench.music_bench fetch       # MUSDB18 (147 MB), palestras do CORAA, GTZAN (só os clipes usados), coral
.venv\Scripts\python -m bench.music_bench train       # sonda fala × letra → lumen/music_probe.json
.venv\Scripts\python -m bench.music_bench run         # conjunto da v1: transcrição sem × com o filtro
.venv\Scripts\python -m bench.music_bench run2 antes  # conjunto v2 (aulas com professor), 3 modos; “antes” com a v1 congelada
.venv\Scripts\python -m bench.music_bench run2 depois
.venv\Scripts\python -m bench.music_bench perf gpu    # pior caso de 10 min; rode “perf cpu” em outro processo
.venv\Scripts\python -m bench.music_bench perf_compare
.venv\Scripts\python -m bench.music_bench report      # bench/RESULTADOS_MUSICA.md
.venv\Scripts\python -m bench.music_bench report2     # bench/RESULTADOS_MUSICA_V2.md
```

Precisa das falas do `asr_bench` (`fetch` e `build`). Mede WER, palavras da fala perdidas, letra infiltrada e a
confiança do ASR em cada cenário (fala sozinha, música sozinha, rap, música −15 a +15 dB, música que liga e
desliga, silêncio, ruídos, trilha do próprio vídeo, piano, eletrônica, violão, fala 2×), sempre com falas e
faixas que a sonda nunca viu. ASR e separação ficam em cache em `bench/.data/music_cache`. O conjunto v2 monta
aulas de ≈ 60 s com o mesmo palestrante (CORAA TEDx) e a música por cima (MUSDB18, GTZAN, coral): professor
sozinho, + instrumental, + cantor, + rap, dois professores, professor novo, + clássica, música entre as falas,
podcast, professor tocando música, coral, a cappella, fala rápida e baixa, várias pessoas, spoken word, 8 gêneros.

## Dados

- **GTZAN** (Tzanetakis & Cook, 2002; uso em pesquisa): 30 s por clipe, 10 gêneros; guardados 330 clipes (hip-hop e
  clássica inteiros: 0–49 treinam a sonda, 50–99 medem). Tem repetições e distorções conhecidas.
- **Cantoría** (Universitat Pompeu Fabra, CC-BY-4.0): 5 mixagens de coral SATB, do espelho no Hugging Face
  (Emulated-Inc/satb-choir-voice-f0), conferidas pelo SHA-256.

- **FLEURS pt-BR** (Google, CC-BY 4.0), split *dev*: fala lida por várias pessoas, com transcrição humana.
- **CORAA v1.1** (NILC/USP, CC BY-NC-ND 4.0: só uso não comercial, sem redistribuir alterado), split *dev*: palestras TEDx
  e conversas espontâneas com sotaques de Recife, São Paulo e Minas, com transcrição humana. O script lê só os
  trechos escolhidos do zip remoto (requisições HTTP Range).
- Condições derivadas (ruído, música, aula longa, aula 2×, sem fala) são montadas por `build` a partir dessas
  falas reais. Ruído, música e aceleração são **sintéticos**.

- **MUSDB18** (sigsep, trechos de 7 s do Zenodo, CC BY 4.0 nesse registro; só uso local): mistura, voz e
  instrumental de 150 músicas. *train* treina a sonda do filtro de música; *test* mede.

A seleção é fixa (semente 7). Nenhum áudio vai para o Git.

## Usar suas próprias aulas (recomendado)

O áudio mais parecido com o seu uso é o seu. Sem publicar nada:

1. Coloque o áudio em `bench/.data/proprias/` (`.wav`, `.mp3` ou `.m4a`), por exemplo 3 a 5 minutos de uma aula.
2. Ao lado, crie um `.txt` com o mesmo nome e a transcrição **revisada por você**, palavra por palavra.
3. Rode `build`, `run <modelo>` e `report`. Aparece a coluna `proprias`.

`bench/.data` está no `.gitignore`.

## Como as métricas são calculadas

`bench/metrics.py`: referência e hipótese passam pela mesma normalização (minúsculas, sem pontuação, números por
extenso, sem "ahn/hum"). Depois é feito um alinhamento por distância de edição, que conta substituições (S),
omissões (D) e inserções (I). WER = (S + D + I) / palavras da referência. O CER é igual, por caractere.
WER baixo não garante que cada palavra está certa; por isso o app mantém a revisão manual.
