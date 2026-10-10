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

## Dados

- **FLEURS pt-BR** (Google, CC-BY 4.0), split *dev*: fala lida por várias pessoas, com transcrição humana.
- **CORAA v1.1** (NILC/USP, CC BY-NC-ND 4.0: só uso não comercial, sem redistribuir alterado), split *dev*: palestras TEDx
  e conversas espontâneas com sotaques de Recife, São Paulo e Minas, com transcrição humana. O script lê só os
  trechos escolhidos do zip remoto (requisições HTTP Range).
- Condições derivadas (ruído, música, aula longa, aula 2×, sem fala) são montadas por `build` a partir dessas
  falas reais. Ruído, música e aceleração são **sintéticos**.

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
