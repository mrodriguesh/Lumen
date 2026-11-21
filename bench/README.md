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

## Modelos dos Estudos (Lúmen Study AI)

```
.venv\Scripts\python -m bench.study_models_bench prepare                  # casos de uma cópia do índice (só leitura)
.venv\Scripts\python -m bench.study_models_bench run qwen3.5:4b qwen3:8b  # think desligado e ligado
.venv\Scripts\python -m bench.study_models_bench judge                    # rubrica (juiz local, nunca o autor)
.venv\Scripts\python -m bench.study_models_bench duel                     # duelos às cegas, nas duas ordens
.venv\Scripts\python -m bench.study_models_bench duel "qwen3:8b" "gemma4:12b+think" --pair "qwen3.5:4b,qwen3.5:9b"
.venv\Scripts\python -m bench.study_models_bench sample                   # amostra cega para o estudante
.venv\Scripts\python -m bench.study_models_bench ctx qwen3.5:4b           # VRAM e velocidade por num_ctx
.venv\Scripts\python -m bench.study_models_bench report
```

Usa os prompts e esquemas do próprio app (`lumen/study`). Casos, respostas e a amostra cega ficam em `bench/.data`
(fora do Git); só os números vão para `results/study_models.json`. Resultado e escolha em
`docs/implementation/LUMEN_STUDY_AI_MODELS.md`.

### Recusas indevidas × utilidade (modelo sem filtragem editorial reduzida, 07/11/2026)

Pedidos legítimos em português (política, religião, linguagem informal, ficção sombria, saúde sexual, segurança da
informação, programação, limites legítimos, estudo com fontes, informação insuficiente), com **fontes sintéticas** (nenhuma
nota real) e dois Ollama separados: use sempre o segundo servidor, `ollama serve` com `OLLAMA_HOST=127.0.0.1:11435`
(o `bench.refusal_eval` recusa a porta 11434, que é a do Ollama do estudante).

```
.venv\Scripts\python -m bench.refusal_eval lock                                  # hash dos casos e dos critérios
.venv\Scripts\python -m bench.refusal_eval run qwen3.5:4b --tag base4b --split dev --cond both
.venv\Scripts\python -m bench.refusal_eval functional qwen3.5:4b --tag base4b     # ferramentas, JSON e roteador
.venv\Scripts\python -m bench.refusal_eval judge --tag base4b                     # dois juízes locais, nunca o próprio modelo
.venv\Scripts\python -m bench.refusal_eval report --tags base4b abl4b --split dev
.venv\Scripts\python -m bench.refusal_live --local MODELO --max MODELO            # fluxo real do Lúmen (agent.turn)
```

O conjunto `holdout` só roda com `--final` e cada execução entra no livro-razão (`ledger.log`); serve para a comparação
final, não para ajustar prompts. Saídas em `D:\Lumen\validacao-modelos-20261107` (fora do Git). A condição `bare` (sem
prompt) separa o que vem dos pesos do que vem das instruções do aplicativo. Resultados em
`docs/implementation/LUMEN_STUDY_AI_MODELO_LIVRE_20261107.md`.

### Perfil adulto: roteamento, escolha do modelo e fluxo real (08/11/2026)

Três instrumentos, todos com dados **sintéticos**, `LUMEN_DATA` temporário e o segundo Ollama (11435):

```
.venv\Scripts\python -m bench.adult_route_eval run --tag v5 --split dev --runs 2     # classificador real: falsos positivos e negativos
.venv\Scripts\python -m bench.adult_route_eval lock                                  # congela prompt, filtros e casos do conjunto final
.venv\Scripts\python -m bench.adult_route_eval run --tag v5 --split final            # só com o lock válido; entra no ledger
.venv\Scripts\python -m bench.adult_route_eval report --tag v5 --split final
.venv\Scripts\python -m bench.adult_model_eval run --model MODELO --tag T --split dev # entrega, sermão, honestidade, contexto, instrução
.venv\Scripts\python -m bench.adult_model_eval functional --model MODELO --tag T      # ferramentas, JSON e roteador
.venv\Scripts\python -m bench.adult_model_eval judge --tags T1,T2 --judges qwen3:8b
.venv\Scripts\python -m bench.adult_model_eval report --tags T1,T2 --split dev
.venv\Scripts\python -m bench.adult_live --adult MODELO                              # fluxo real (agent.turn) com o perfil ligado
```

`adult_route_eval` separa o falso negativo em "perdido pelo filtro de sinais" e "perdido pelo classificador". Os casos de
desenvolvimento servem para ajustar o prompt e os filtros; os do conjunto final só rodam depois do lock. Saídas em
`D:\Lumen\perfil-adulto-20261108` (fora do Git). Resultados em `docs/implementation/LUMEN_STUDY_AI_PERFIL_ADULTO_20261108.md`.

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

## Holograma 3D no chat (`holo_chat_check.py`)

Roda o fluxo inteiro do `/elegrama 3d` (`agent.turn` → fila → desenho no tamanho real → arquivos conferidos → conversa → reabertura) com dados
isolados. `py -3.14 bench/holo_chat_check.py SAIDA` usa respostas fixas (conteúdo conhecido, desenho real); `--ollama http://127.0.0.1:11435 --prompts
pedidos.json [--effort maximo]` usa um Ollama de verdade (use uma instância isolada, nunca a pessoal). Grava, por caso, o GIF, o PNG de reserva, uma
folha com início, terço, dois terços e fim da animação e `report.json` (tempos, pesos, quadros com movimento, mensagem).

## Conversa por voz (`call_bench.py`, `asr_first_utterance.py`)

Mede a chamada de ponta a ponta com o Ollama, o Voice Studio e o Parakeet reais, a saída WASAPI real **em ganho zero** e um microfone **simulado** com
falas sintéticas (`D:/Lumen/voz/amostras-chamada`): não grava o microfone de ninguém e não toca nas caixas. Cada execução usa um diretório **novo**
(`D:/Lumen/cache/lumen-call-bench-<LUMEN_BENCH_RUN>`) e só apaga o que ela mesma criou; o resultado vai para
`D:/Lumen/voz-conversa-20261108/bench/<LUMEN_BENCH_RUN>/call_bench.json` (`LUMEN_BENCH_OUT` muda). Cada processo sobe o Voice Studio a frio (~5 min); rode tudo o que precisar num só
comando e **não rode outra coisa pesada durante a medição**.

- `turns` / `baseline`: 16 perguntas comuns + 4 com cartão, por etapa (p50/p90), com o tempo frio de cada serviço.
- `realtime`: 20 comuns + 4 com cartão **em tempo real** (~10 min), com CPU, RAM e VRAM a cada segundo (`afterturns` = `turns` + `realtime`).
- `probe`: síntese isolada × com o modelo escrevendo, passos 8/12/16 com o erro de palavras, silêncio nas bordas, fim de fala com Silero e Parakeet reais; grava pares cegos em `D:/Lumen/voz-conversa-20261108/escuta/<execução>`.
- `endpoint`: só o fim de fala (CPU, sem Voice Studio). `LUMEN_BENCH_KEEP_VS=1` não desliga o backend que o bench subiu.
- `asr_first_utterance.py old|new`: custo da 1ª fala do Parakeet com e sem o aquecimento (um processo novo por modo).
