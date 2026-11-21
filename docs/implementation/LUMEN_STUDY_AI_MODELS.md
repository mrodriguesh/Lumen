# Lúmen Study AI: modelos medidos neste PC

Medido em 01/11/2026 (fase 2 do Study AI 2.0) com `bench/study_models_bench.py`. O PC tem uma RTX 3060 de 12 GB e 16 GB de RAM, com Ollama 0.40.13. Os modelos ficam num **disco rígido** (D:, Seagate de 1 TB).

As tarefas usam as notas reais, numa cópia do índice em modo só leitura (467 páginas do Notion e 67 notas do Obsidian), e os prompts e esquemas do próprio app:
- **resposta com citações:** 4 perguntas de cursos (gancho de vídeo, keyframes no Premiere, preço, persuasão), com 8 fontes reais cada;
- **roteador:** 12 pedidos com a intenção esperada;
- **JSON:** flashcards e mapa de conhecimento;
- **ferramentas:** 3 pedidos que exigem uma ferramenta certa.

Cada tarefa rodou com o raciocínio (`think`) desligado e ligado. Os números brutos estão em `bench/results/study_models.json`.

## Escolha por papel

| Papel | Modelo | Motivo |
|---|---|---|
| Responder (Automático) | **`qwen3.5:4b`** (era o `qwen3:8b`) | Nos duelos às cegas, vence o `qwen3:8b` por 6 × 0 e o `gemma4:12b` por 3 × 0 em vereditos consistentes. Contra o `qwen3.5:9b`, os juízes locais não decidem (1 × 1, com 13 inconsistentes). Com qualidade sem diferença medível, ganha por ser o mais rápido (81 tokens/s), o menor (4,2 GB), o mais rápido no JSON e o que mais cita as fontes. Já é o modelo de visão das aulas. A amostra cega fica para o estudante desempatar. |
| Rápido (entender o pedido, memória, título) | **o mesmo `qwen3.5:4b`** | Os modelos carregam do HD: a carga a frio levou de 10 s a 142 s, conforme o que estava no cache do Windows. Um modelo só evita trocar a cada pergunta. No roteador, acertou 10 de 12 em 2,2 s. |
| Embeddings | `qwen3-embedding:0.6b` (sem mudança, D5) | — |
| Visão (fase 4) | `qwen3.5:4b` | Já escolhido em `bench/vision_bench.py` para as aulas. |
| Profundo e Máximo (fase 3) | candidato: `qwen3.5:9b` com raciocínio ligado | Com raciocínio, os modelos Qwen acertam 3 de 3 nas ferramentas. Em troca, levam de 8 s a 28 s a mais até a primeira palavra. Falta medir na fase 3. |
| Reranker | adiado para a fase 3 | Só vale no nível Profundo. Medir exige marcar a relevância de cada trecho, o que fica para quando o nível existir. |

A troca é reversível em Estudos → Configurações → Modelos: o campo "Automático" mostra o modelo em uso, e a lista permite escolher outro. Se o modelo recomendado não estiver instalado, o Automático usa o modelo da IA local dos Ajustes.

## Resultados com o raciocínio desligado (o modo normal do chat)

| Modelo | VRAM em 16k | Carga a frio / com cache | 1º token | tokens/s | Resposta (mediana) | Citações válidas | Roteador | Flashcards / mapa | Ferramentas | Duelos (vitórias × derrotas consistentes) |
|---|---|---|---|---|---|---|---|---|---|---|
| **qwen3.5:4b** | 4,2 GB | 25–30 s / 2,9 s | 0,9 s | 81 | 17 s | 60/60 | 10/12 | 16 s / 13 s | 2/3 | **10 × 1** |
| qwen3.5:9b | 6,7 GB | 42–142 s / 3,6 s | 1,4 s | 52 | 22 s | 38/38 | 11/12 | 58 s / 12 s | 1/3 | 6 × 1 |
| gemma4:12b | 9,1 GB | 51–58 s / 6,0 s | 2,4 s | 60 | 18 s | 46/46 | 10/12 | 58 s / 10 s | 0/3 | 6 × 5 |
| qwen3:8b (padrão anterior) | 7,2 GB | 10–36 s / 2,8 s | 1,2 s | 55 | 14 s | 32/32 | 11/12 | 26 s / 27 s | 2/3 | 0 × 15 |
| granite4.2:8b (baixado nesta fase) | 7,7 GB | 101 s / — | 1,5 s | 52 | 42 s | 33/33 | 9/12 | 39 s / 23 s | 2/3 | não entrou |

Como ler a tabela:
- **VRAM:** é o `nvidia-smi` menos os 0,53 GB da área de trabalho (GB de 1024³ bytes, como o Ollama mostra). O `ollama ps` informa de menos para o `gemma4:12b` e para os `qwen3.5`.
- **Carga:** "a frio" é a leitura do HD, com o menor e o maior valor vistos (depende de quanto do arquivo já estava no cache do Windows); "com cache" é com o arquivo inteiro na memória.
- **Primeiro token e resposta:** mediana das 4 respostas, com o modelo já carregado na maioria delas.
- **Citações:** contadas como o app conta (`agent.validate`), depois da normalização descrita abaixo. Nenhum modelo inventou uma fonte.
- **Granite:** cita em formatos soltos (`(S1–S8)`, `(S1/S2 e S3)`), que só contam depois da normalização (D26). Ficou fora dos duelos como candidato por ser o mais lento (42 s por resposta, 101 s de carga a frio), acertar 9 de 12 no roteador e ocupar 7,7 GB.

### Com o raciocínio ligado

| Modelo | 1º token | Resposta | Roteador | Flashcards / mapa | Ferramentas |
|---|---|---|---|---|---|
| qwen3.5:4b | 28 s | 39 s | 11/12 (26 s) | 51 s / 56 s | 3/3 |
| qwen3.5:9b | 26 s | 41 s | 11/12 (41 s) | 267 s / 84 s | 3/3 |
| gemma4:12b | 20 s | 35 s | 10/12 (11 s) | 77 s / 65 s | 1/3 |
| qwen3:8b | 8 s | 26 s | 10/12 (9 s) | 50 s / 37 s | 3/3 |
| granite4.2:8b | 45 s | 102 s | 12/12 (30 s) | 102 s / 159 s | 3/3 |

O raciocínio melhora as ferramentas, mas custa de 8 s a 45 s antes da primeira palavra. A qualidade da explicação não sobe: o juiz deu nota menor ao `qwen3.5:4b` com raciocínio (4,45) do que sem (4,95). Por isso o chat normal fica sem raciocínio, e o raciocínio fica para o nível Profundo da fase 3.

**Níveis de raciocínio (lidos em `/api/show`):**
- os quatro modelos instalados antes desta fase só aceitam ligado ou desligado (`thinking.values = [false, true]`);
- o `granite4.2:8b` não declara níveis, e foi testado só com `true` e `false`.

Na prática, os níveis de esforço da fase 3 vão variar o modelo, o contexto e o número de fontes, não o grau de raciocínio.

## Como a qualidade foi julgada

- **Rubrica:**
  - **Como funcionou:** dois juízes locais (`gemma4:12b` e `qwen3.5:9b`), sem o Claude, porque ele custa dinheiro. Cada um deu notas de 1 a 5 em fidelidade, didática, português, estrutura e utilidade, e nunca julgou a si mesmo.
  - **Limite:** as notas ficaram quase todas entre 4,5 e 5, então a rubrica sozinha não separa bem. O `gemma4:12b` deu 5 a quase tudo.
  - **Resultado:** com o `qwen3.5:9b` como juiz, o `qwen3:8b` sem raciocínio teve a menor nota (4,40, com 3,75 em didática), e o `qwen3.5:4b`, a maior (4,95).
- **Duelos às cegas:**
  - **Como funcionou:** duas respostas lado a lado, sem nome, nas duas ordens, julgadas por modelos que não estão no duelo. Foram 111 julgamentos.
  - **Só vale o veredito consistente**, isto é, o mesmo vencedor nas duas ordens.
  - **Viés de posição:** três juízes escolhem pela posição, não pelo conteúdo. O `gemma4:12b` escolheu a resposta A em 24 de 24 duelos, o `qwen3:8b` escolheu B em 8 de 8 e o `granite4.2:8b`, B em 36 de 48. Os mais equilibrados foram o `qwen3.5:9b` (10 A e 14 B) e o `gemma4:12b` com raciocínio (5 A e 2 B).

| Duelo | Vereditos consistentes | Inconsistentes |
|---|---|---|
| qwen3.5:4b × qwen3:8b | **6 × 0** | 6 |
| qwen3.5:4b × gemma4:12b | **3 × 0** | 5 |
| qwen3.5:4b × qwen3.5:9b | 1 × 1 | 13 |
| qwen3.5:9b × qwen3:8b | 3 × 0 | 5 |
| qwen3.5:9b × gemma4:12b | 2 × 0 | 2 |
| gemma4:12b × qwen3:8b | 6 × 0 | 2 |

**O que dá para concluir:**
- O `qwen3:8b`, o padrão anterior, perde para todos e não venceu nenhum duelo de forma consistente.
- Os dois `qwen3.5` ficam acima do `gemma4:12b`.
- Entre o `qwen3.5:4b` e o `qwen3.5:9b`, os juízes locais não conseguem separar a qualidade.

- **Amostra para o estudante:** está em `bench/.data/study_models/amostra.md`, com 2 perguntas e as respostas do `qwen3:8b`, do `qwen3.5:4b` e do `qwen3.5:9b` sem nome. Os nomes estão em `amostra_gabarito.json`. É ela que desempata entre o `qwen3.5:4b` e o `qwen3.5:9b`: se a sua ordem discordar da escolha, vale a sua, e a troca é feita nas Configurações.

## Candidatos considerados

A pesquisa de 31/10, em fontes oficiais, considerou estes modelos além dos instalados:
- **Qwen3.6 e Qwen3.8:** só existem em 27B ou mais (18 a 23 GB) e não cabem nos 12 GB da placa.
- **`granite4.2:8b`:** foi baixado e medido nesta fase.
- **`glm-ocr`:** fica para a fase 4, de imagens, e só se a licença for confirmada.

## Risco conhecido

O `qwen3.5:4b` também lê as telas das aulas (`lumen/vision.py`), com 4 mil tokens de contexto. Se o estudante conversar nos Estudos enquanto uma aula é processada, o Ollama recarrega o modelo a cada troca de contexto. A recarga leva cerca de 3 s com o arquivo no cache. O fluxo das aulas não foi mudado nesta fase.

## VRAM por tamanho de contexto (`num_ctx`)

Valores do `nvidia-smi`, menos os 0,53 GB da área de trabalho. O texto de teste tem cerca de 3 mil tokens, e todos os modelos ficaram 100% na GPU em todos os tamanhos.

| Modelo | 4k | 8k | 16k | 32k | tokens/s |
|---|---|---|---|---|---|
| qwen3.5:4b | 3,7 GB | 3,9 GB | 4,2 GB | 4,7 GB | 81 |
| qwen3.5:9b | 6,2 GB | 6,5 GB | 6,7 GB | 7,1 GB | 53 |
| qwen3:8b | 5,3 GB | 6,0 GB | 7,2 GB | 9,3 GB | 54 |
| gemma4:12b | 8,5 GB | 8,9 GB | 9,1 GB | 9,0 GB | 54 |

Os prompts reais dos Estudos usam até 5,5 mil tokens e dão de 3,0 a 3,7 caracteres por token.

## Ajuste do Ollama

| Ajuste | Decisão | Motivo |
|---|---|---|
| `num_ctx` | **Um valor por modelo em todas as chamadas dos Estudos**: 16k na fase 2; desde a fase 3 (D24), 32k na família `qwen3.5` e 16k nos outros; o dobro só para um pedido que não cabe (`providers.num_ctx`) | O padrão anterior era 32k fixo. O Ollama recarrega o modelo quando o `num_ctx` muda entre pedidos, então o roteador e o chat precisam do mesmo valor. Com o `qwen3:8b`, 32k custava 2,1 GB a mais sem uso. |
| Flash attention | Sem mudança | O 0.40.13 já liga sozinho (`flash_attn = auto` e "Flash Attention enabled" no `server.log`). |
| Cache do contexto quantizado (`OLLAMA_KV_CACHE_TYPE=q8_0`) | **Não adotado** | No `qwen3.5:4b`, o cache inteiro em 16k mede cerca de 0,5 GB (de 16k para 32k só cresce 0,5 GB), então a economia seria de 0,25 GB. A variável vale para todos os modelos, inclusive os das aulas, e há relatos de perda de qualidade no Gemma 4. Como não foi adotado, a qualidade com `q8_0` não foi medida. |
| `OLLAMA_MAX_LOADED_MODELS` | **Sem mudança** (não foi para 1) | Cada pergunta usa o modelo de embeddings e o de chat. Com 1, o Ollama trocaria os dois a cada pergunta, lendo do HD. Juntos, ocupam menos de 6 GB. Isto foi deduzido, não medido. |
| `keep_alive` | Sem mudança (10 min no chat) | Depois de descarregado, o modelo volta em cerca de 3 s enquanto o arquivo está no cache do Windows. Segurar a VRAM por mais tempo atrapalharia o gerador de imagens e as aulas. |

Nenhuma variável de ambiente do Ollama foi alterada, então não é preciso reiniciar o Ollama.

## Outras conclusões da medição

- **Citações fora do padrão:** os modelos locais escrevem `[S1, S2]`, `(S3)`, `<S2>`, `(S1–S8)` e `(S1/S2)`. O app só reconhecia `[S1]`, e essas citações sumiam da tela. Na verificação de ponta a ponta com o `qwen3.5:4b`, a mesma pergunta citou 1 de 8 fontes antes da correção e 4 depois (a busca pode variar entre as duas rodadas). Agora `agent.validate` normaliza tudo antes de conferir, e intervalos viram cada fonte, conferida uma a uma (D26).
- **Ferramentas:**
  - **Sem a regra:** com o prompt antigo, o `qwen3.5:4b` fez 0 de 3 no teste rápido. No pedido com a busca vazia, ele e o `qwen3:8b`, com e sem raciocínio, responderam "não encontrei" sem buscar, e o `qwen3:8b` ainda citou `[S0]` e `[S1]`, que não existiam. Esses testes rodaram antes da regra e não estão no JSON.
  - **Com a regra 9 (D27):** os pedidos explícitos ("leia a fonte S2 inteira", "quais notas estão ligadas à S1") funcionam sem raciocínio no `qwen3.5:4b`, no `qwen3:8b` e no `granite4.2:8b`.
  - **O que a regra não resolve:** **buscar de novo quando o material vem vazio só acontece com o raciocínio ligado.** Sem raciocínio, nenhum dos 5 modelos buscou. Isso fica para a fase 3.
- **Issue #19350 do Ollama** (com `think` desligado e um esquema JSON, o `qwen3.5:9b` não para de gerar): **não reproduzido** no 0.40.13. Foram 12 pedidos do roteador, 2 JSON de estudo, 32 notas de juiz e 24 duelos, e todos terminaram com `stop` e JSON válido.
- **Roteador sem IA (a heurística):** acerta 7 de 12. Ela classifica "roteiro de vídeo" como plano de estudos, porque "roteiro" está entre as palavras de plano, e "roteiro" aparece em 69 trechos das suas notas. Também não reconhece "me testa". Isso fica para o modo Automático da fase 3.

## Voz (fase 6, 02/11/2026)

Medido na RTX 3060 com o Voice Studio 0.5.7 (OmniVoice) e a voz do Jhonny (perfil `1faf41ee`, referência de 59,2 s). Script: `bench/voicestudio_bench.py`. As medidas do Chatterbox são de 01/11 (`bench/voice_bench.py`, D44).

| Medida | Voice Studio (Jhonny) | Chatterbox pt-br |
|---|---|---|
| Geração por segundo de fala (roteiro de 106 palavras) | **0,42** com `pt` (16,7 s para 40,1 s de fala); 0,40 sem idioma | 1,1 |
| Geração por minuto de áudio | **25 s** (sem conferência); **33,6 s** no resumo real de uma aula, com a conferência do Whisper (D45) | cerca de 66 s, sem conferência |
| Erro de palavras (Whisper large-v3-turbo do Lúmen) | **0%** com `pt` (106 de 106); 1,9% sem idioma | 10,4% (111 palavras ouvidas para 106) |
| Até o primeiro som no chat (modelo quente) | `/ws/tts` frase a frase 2,68 s; texto inteiro 2,67 s; HTTP frase a frase 2,75 s | — |
| Até o primeiro som numa resposta real do `qwen3.5:4b` | 11,4 s com a 1ª frase de ≈ 220 caracteres; **2,4 s a 2,7 s** com o 1º pedaço cortado em 90 (`listen.FIRST_CHARS`); a resposta inteira (27,5 s de fala) fica pronta em 10 s a 11 s, sem pausa | — |
| VRAM | modelo carregado 2,7 GB; geração cerca de 2,2 GB a mais no pico | 3,6 GB |
| Carga a frio | cerca de 9 s (a 1ª frase levou 11,4 s; as seguintes, 2,0 s) | 88 s |

**Ollama e voz juntos (a fala do chat):** com o `qwen3.5:4b` carregado em 32k e o OmniVoice falando, o pico do PC inteiro foi de 11,25 GB de 12 (havia 4,0 GB em uso antes: o OmniVoice carregado e os programas abertos). **Cabem**, com pouca folga; por isso os áudios longos chamam `llm.release_vram()` antes (pico de 11,19 GB no resumo real, com o Whisper `small` da conferência).

**Custo fixo de 5 s do log:** não aparece pela API. Com o modelo quente, 3,55 s de fala saem em 2,05 s, e o log mostra o recorte do melhor trecho de 15 s da referência a cada pedido sem o Whisper do Voice Studio. Uma versão curta da voz não mudaria o tempo, então não há o que sugerir ao estudante.

**Idioma:** `"Portuguese (Brazil)"` não é reconhecido pelo OmniVoice (o log avisa e o modelo fica sem idioma); `"pt"` é o código aceito.

**Resumo real** (aula de curso "Fluxo de Criação de Motion Graphics com Ferramentas Open Source e IA", banco temporário, original só lido): 6 capítulos (resumo e 5 tópicos), 2 min 17 s de áudio gerados em 76,5 s com a conferência ligada; a estimativa antes de começar foi de 94 s. Arquivos para ouvir em `D:\Lumen\voz\amostras-vs\real-resumo-aula.m4a` e `real-resposta.m4a`.

## Voz, parte 2: passos, 1º som e a máquina (02/11/2026)

Medido na RTX 3060 com o Voice Studio 0.5.7 aberto (o backend do app), a voz do Jhonny, modelo quente, `language: "pt"`, semente 1. Script: `bench/voicestudio_bench.py passos` (resultado em `D:\Lumen\voz\amostras-vs\bruto\passos.json`).

| Passos (`num_step`) | Geração por segundo de fala (roteiro de 106 palavras) | Erro de palavras | 1º som, frase de chat de ≈ 100 caracteres (PCM, mediana de 3) |
|---|---|---|---|
| 8 | 0,27 (10,9 s para 40,2 s) | 0,9% (1 palavra) | 1,92 s |
| 12 | 0,33 (13,2 s) | 0% | 2,17 s |
| 16 (o padrão do `/v1/audio/speech` e do `/ws/tts`) | 0,39 (15,8 s) | 0% | 2,69 s |
| 24 | 0,53 (21,1 s) | 0% | 3,62 s |
| 32 | 0,68 (27,2 s) | 1,9% | 4,64 s |

- **`/ws/tts`** (16 passos fixos): 2,79 s com uma conexão por frase e 2,73 s com a resposta inteira numa conexão. O HTTP em PCM com 16 passos (2,69 s) já empata ou ganha e aceita passos e semente: a fala do chat passou para ele (D56).
- **1º som × tamanho do 1º pedaço:** 39 caracteres 1,19 s (8 passos), 1,51 s (12), 1,91 s (16); 60 caracteres 1,37 s, 1,77 s, 2,18 s; 88 caracteres 1,65 s, 1,99 s, 2,34 s. Há um custo fixo de ≈ 1 s por pedido. Com o 1º pedaço cortado na vírgula perto de 50 caracteres, o chat fica em ≈ 1,5 s com 12 passos e ≈ 1,2 s com 8 (meta de 1,5 s, se a escuta aprovar).
- **VRAM:** a geração soma ≈ 0,1 GB ao modelo em qualquer número de passos. Menos passos não economizam placa, só tempo.
- **RAM:** com o app aberto, o Electron ocupa 728 MB de memória privada em 6 processos (297 MB em uso). O backend sozinho (sem janela) dispensa isso. No momento da leitura havia de 2,4 GB a 3,1 GB de RAM livres (de 15,8).
- **`torch.compile`:** não medido. O app força `TORCHDYNAMO_DISABLE=1` no Windows, e o ambiente dele não tem o `triton`; medir exigiria instalar. Fica como está (D59).
- **Escuta cega dos passos:** `D:\Lumen\voz\amostras-passos\X.wav`, `Y.wav` e `Z.wav` (8, 12 e 16 passos, letras sorteadas; a chave em `chave.json`). Os padrões (chat 12, áudios longos 16) ficam até o estudante escolher.
- **Teste real a frio (02/11, o Voice Studio fechado pelo estudante; script no terminal com `LUMEN_DATA` temporário, pelo `listen.live` do Lúmen, 12 passos, cache desligado):**

| | 1ª subida (arquivos frios) | 2ª subida (com `OMNIVOICE_OFFLOAD_AFTER_GENERATION=1`) |
|---|---|---|
| Backend respondendo (`Loading API routes`) | 16,3 s | 6,6 s |
| Modelo carregado (do início) | ≈ 73 s | ≈ 40 s |
| **1º som** | **74,1 s** | **40,9 s** |
| Janelas visíveis na árvore do backend (conferido a cada 0,3 s) | nenhuma | nenhuma |
| VRAM depois da fala | 3,1 GB no PC (≈ 2,3 GB do modelo) | 3,1 GB: o `offload` não liberou nada na rota de fala do Lúmen |
| Frase seguinte (12 passos) | 1,73 s | 1,83 s |
| RAM do backend | 2,7 GB | 2,7 GB |
| Desligar (fechar o pipe) | 0,8 s, o processo saiu, 0 `python.exe` do Voice Studio restantes | igual |

  **A meta de 25 s não foi atingida.** Quase todo o tempo é a carga do modelo dentro do Voice Studio (32 s a 55 s), com 2,5 GB a 3 GB de RAM livres no PC: os arquivos do modelo não ficam no cache do disco. Os "≈ 9 s de carga" da fase 6 foram medidos com os arquivos já na memória. O que o Lúmen já faz para esconder isso: pré-aquecer ao abrir os Estudos com a leitura automática ligada e quando uma resposta começa a chegar (D54); "Deixar a voz pronta ao abrir o Lúmen" carrega na abertura. O `offload-after-generation` fica desligado (sem efeito medido na rota de fala). Pendentes: abrir o app com o backend do Lúmen rodando e fechar o Lúmen com o app aberto (o estudante decide quando abrir o app).

## Conversa por voz (fase 6, parte 3 — 02/11/2026)

Medido neste PC (i5-11400F, 15,8 GB de RAM, RTX 3060 de 12 GB) com `LUMEN_DATA` temporário no D:, o Ollama do estudante (`qwen3.5:4b` em 32k, sem raciocínio) e o backend já aberto do Voice Studio 0.5.7 (OmniVoice, voz do Jhonny `1faf41ee`, `language: "pt"`), usando saída WASAPI real em ganho zero para não tocar áudio nas caixas de som durante o teste. Script: `bench/call_bench.py`; dados completos em `D:\Lumen\voz\amostras-chamada\call_bench.json`.

### 1. Atraso fim a fim em 20 turnos quentes (do último som da fala ao 1º som da resposta)

Configuração padrão medida (`call_silence: "normal"` = 700 ms, `call_early: true` aos 250 ms, `call_quality: "balanced"` = 12 passos, `call_asr: "auto"` → Parakeet CPU int8, `call_length: "short"`):

| Etapa | Mediana (p50) | 90º percentil (p90) | Mínimo | Máximo | Observação |
|---|---|---|---|---|---|
| Fim da fala (`eos_ms`, silêncio até fechar o turno) | 704,0 ms | 704,2 ms | 703,6 ms | 704,3 ms | Com `call_early` ligado, a transcrição já começa aos 256 ms de silêncio |
| Som de "entendi" (`earcon_ms`, após o fim da fala) | **42,3 ms** | **45,5 ms** | 20,7 ms | 46,1 ms | **Meta ≤ 300 ms atingida com folga** (em paralelo à transcrição) |
| Transcrição (`asr_ms`, Parakeet TDT 0.6b v3 ONNX int8 na CPU) | **307,4 ms** | **354,6 ms** | 249,5 ms | 376,6 ms | **Meta < 400 ms atingida**, sem ocupar VRAM |
| 1º token do `qwen3.5:4b` (`llm_first_ms`) | 770,4 ms | 919,4 ms | 343,9 ms | 980,8 ms | Cresce levemente ao longo de 20 turnos pelo histórico da conversa (587 ms com histórico curto) |
| 1ª oração pronta para falar (`llm_clause_ms`) | 911,1 ms | 1.039,2 ms | 527,7 ms | 1.168,0 ms | Corta na 1ª pontuação após 20 caracteres ou conector natural |
| 1º áudio do Voice Studio (`tts_first_ms`, 12 passos) | 2.255,7 ms | 2.376,4 ms | 1.856,7 ms | 2.425,8 ms | OmniVoice dividindo a RTX 3060 com o final do streaming do `qwen3.5:4b` |
| Abertura e 1º quadro WASAPI no Python (`play_first_ms`) | **14,8 ms** | **16,6 ms** | 7,6 ms | 17,6 ms | `loopback.speaker` direto em `float32` 24 kHz |
| Espera após o fim da fala (`after_eos_ms`) | 3.021,4 ms | 3.251,8 ms | 2.474,2 ms | 3.438,8 ms | O que o estudante espera depois dos 700 ms de silêncio |
| **Total (último som do estudante → 1º som da resposta)** | **3.725,6 ms** (3.412,9 ms em conversa curta) | **3.955,4 ms** (3.519,8 ms em conversa curta) | **3.178,2 ms** | 4.142,8 ms | Com 8 passos no 1º pedaço cai para **3.129,8 ms** (p50) e **3.268,0 ms** (p90) |

**Por que a meta de ≤ 2,0 s (p50) / ≤ 3,0 s (p90) não cabe sem degradar a voz neste hardware:**
- Só o OmniVoice sozinho, com a placa ociosa, já leva **1,51 s** (12 passos) a **1,91 s** (16 passos) para um trecho curto de 39 caracteres (seção Voz, parte 2); durante a chamada, enquanto o `qwen3.5:4b` termina de escrever a 2ª frase na mesma RTX 3060, o 1º trecho em 12 passos leva **2,12 s a 2,26 s** (e **1,93 s** com 8 passos).
- Somando o piso anterior à síntese — 256 ms de silêncio antes do disparo antecipado + 307 ms de transcrição na CPU + 720 a 911 ms até a 1ª oração do `qwen3.5:4b` + 15 ms de saída WASAPI (= **1,30 s a 1,49 s**) — o piso físico real com o `qwen3.5:4b` + OmniVoice Jhonny nesta máquina é **3,41 s a 3,73 s** em 12 passos (ou **3,13 s** de mediana e **3,27 s** de p90 com 8 passos no 1º pedaço, aguardando escuta cega do estudante).
- Para esconder a espera sem trocar a voz clonada: o som de "entendi" responde em **42 ms** após o fim da fala, a legenda parcial/final e os tokens aparecem na tela durante o pensamento, e o ajuste opcional **"Preencher a espera"** (`call_filler`) toca uma frase curta guardada na memória aos 1,9 s quando o turno demora mais.

### 2. Transcrição na chamada (`N = 20` falas reais, direto da memória)

| Motor | Mediana (p50) | p90 | Fala de 5,4 s | Erro de palavras (WER) | VRAM total no PC | Escolha |
|---|---|---|---|---|---|---|
| **Parakeet TDT 0.6b v3 ONNX int8 (CPU, 4 threads)** | **270,7 ms** | **342,9 ms** | **352,2 ms** | **2,65%** | **7.990 MB (+0 MB)** | **Padrão do Automático** com Ollama + OmniVoice carregados |
| Parakeet com legenda parcial a cada 650 ms concorrendo | 386,5 ms | 427,4 ms | — | 2,65% | 7.990 MB | Desligada no modo mãos livres (+115,8 ms no final pela disputa da trava ONNX; 4.3.3) |
| Whisper `large-v3-turbo` (`cuda`, `float16`) | 290,9 ms | 304,3 ms | 300,6 ms | 2,85% | 10.254 MB (+2.264 MB; restam só 1.862 MB livres) | Só entra no Automático se houver ≥ 4,5 GB livres (ex.: modelo de texto na nuvem) |
| Whisper `small` (`cuda`, `float16`) | 141,3 ms | 166,9 ms | 152,7 ms | 7,51% | 8.761 MB (+771 MB) | Quase 3× mais erro que o Parakeet |
| Whisper `small` (`cpu`, `int8`) | 1.576,6 ms | 1.837,6 ms | 1.745,3 ms | 7,51% | 7.990 MB (+0 MB) | Reserva apenas se o Parakeet não estiver baixado |

### 3. Fim da fala (450 / 700 / 1100 ms) × Resposta antecipada (ligada / desligada)

| Configuração (12 passos, 6 turnos cada) | `eos_ms` (p50) | `after_eos_ms` (p50) | `total_ms` (p50) | `total_ms` (p90) | Corta pausa respiratória de 320 ms? | Corta pausa de 550 ms? | Corta pausa de 850 ms? |
|---|---|---|---|---|---|---|---|
| Rápido (450 ms) + antecipada ligada | 480,0 ms | 3.456,1 ms | 3.936,0 ms | 4.369,3 ms | Não | **Sim** | Sim |
| Rápido (450 ms) + antecipada desligada | 480,0 ms | 3.396,9 ms | 3.877,1 ms | 4.134,9 ms | Não | **Sim** | Sim |
| **Normal (700 ms) + antecipada ligada (padrão)** | **704,1 ms** | **2.840,4 ms** | **3.544,3 ms** | **3.765,7 ms** | **Não** | **Não** | Sim |
| Normal (700 ms) + antecipada desligada | 704,0 ms | 3.565,5 ms | 4.269,8 ms | 4.441,8 ms | Não | Não | Sim |
| Paciente (1100 ms) + antecipada ligada | 1.120,0 ms | 2.317,4 ms | 3.437,6 ms | 3.797,3 ms | Não | Não | **Não** |

- Em 700 ms, a resposta antecipada aos 250 ms economiza **725,5 ms na mediana** (3.544,3 ms contra 4.269,8 ms) e **676,1 ms no p90**, porque a transcrição (≈ 316 ms) já termina e o `qwen3.5:4b` já começa a gerar ~130 ms antes do fim oficial do silêncio, sem cortar pausas naturais de 550 ms no meio da frase. Em 450 ms, além de cortar pausas de 550 ms, os 194 ms entre 256 ms e 450 ms não bastam para terminar a transcrição antes do fim da fala.

### 4. Passos do 1º pedaço (8 / 12 / 16 passos)

| Estratégia | 1º áudio `tts_first_ms` (p50) | 1º áudio `tts_first_ms` (p90) | `total_ms` (p50) | `total_ms` (p90) |
|---|---|---|---|---|
| 1º pedaço em 8 passos + resto em 16 (`first8_rest16`) | **1.929,0 ms** | **2.049,6 ms** | **3.129,8 ms** | **3.268,0 ms** |
| 1º pedaço em 12 passos + resto em 16 (`first12_rest16`) | 2.226,2 ms | 2.420,6 ms | 3.517,8 ms | 3.709,9 ms |
| **12 passos uniforme (`balanced`, padrão atual da chamada)** | **2.120,6 ms** | **2.241,1 ms** | **3.412,9 ms** | **3.519,8 ms** |
| 16 passos uniforme (`quality`, padrão do chat escrito) | 2.620,2 ms | 2.861,4 ms | 3.870,9 ms | 4.196,7 ms |

- Amostras cegas geradas em `D:\Lumen\voz\amostras-chamada\escuta-cega\amostra_A.wav`, `amostra_B.wav` e `amostra_C.wav` (8, 12 e 16 passos no 1º pedaço seguido de 16 passos no restante, letras sorteadas em `chave.json`). O padrão da chamada fica em **Equilibrado (12 passos uniformes)** até o estudante ouvir e decidir se aprova 8 passos no 1º pedaço (−283 ms contra 12 passos e −741 ms contra 16 passos).

### 5. Onde tocar o áudio (Python WASAPI × navegador HTTP base64 + WebAudio, `N = 20`) e eco (`N = 20`)

| Saída de áudio | 1º som (p50 / p90) | Parar com descida suave de 50 ms + `flush` (p50 / p90) | Referência para cancelar eco | Janela minimizada |
|---|---|---|---|---|
| **Python (`loopback.speaker`, WASAPI `float32`)** | **11,3 ms / 13,7 ms** | **53,9 ms / 54,3 ms** (meta ≤ 150 ms) | **Exata no mesmo processo (quadros de 20 ms)** | **Continua normal** |
| Navegador (NDJSON base64 + decode WAV) | 24,3 ms / 36,9 ms (+33,3% de tráfego) | Depende da aba ativa | Indisponível no Python sem loopback extra | Sujeito a suspensão de WebAudio |

| Cenário acústico (20 rodadas com acoplamento de 22% a 38% da voz do Jhonny + fala real por cima) | Disparos falsos pelo próprio eco | Interrupções reais detectadas |
|---|---|---|
| Fone de ouvido (`call_headphones: true`) | **0 / 20** | **20 / 20** |
| Caixa de som sem proteção (só VAD puro) | **20 / 20** (autointerrupção em 100% dos turnos) | 20 / 20 |
| Caixa de som só com barreira calibrada de energia | **0 / 20** | **20 / 20** |
| **Caixa de som com `pyaec` (SpeexDSP) + barreira calibrada (adotado)** | **0 / 20** | **20 / 20** |

### 6. Estabilidade de VRAM e RAM numa chamada contínua real de 10 minutos (600,2 s, 24 turnos)

Incluiu 20 turnos de conversa direta mais mapa mental (14,7 s com geração do JSON do diagrama), explicação com diagrama (4,7 s) e consulta ao modelo de domínio (`mastery`, 2,7 s), com zero erros:

| Instante | Turnos concluídos | VRAM usada no PC | Memória RSS do processo Python | RAM livre no Windows |
|---|---|---|---|---|
| 0,0 s (início quente) | 0 | 8.153 MB | 1.115,6 MB | 1.036,9 MB |
| 150,0 s (2 min 30 s) | 6 | 7.968 MB | 1.104,5 MB | 1.693,6 MB |
| 300,1 s (5 min) | 12 | 7.970 MB | 1.106,9 MB | 1.407,9 MB |
| 450,0 s (7 min 30 s) | 18 | 7.972 MB | 1.105,7 MB | 1.404,9 MB |
| 600,2 s (10 min, fim) | 24 | **7.953 MB (−200 MB)** | **1.118,1 MB (+2,5 MB)** | 931,5 MB |

Nenhum crescimento contínuo de VRAM (pico 8.153 MB, variação de −200 MB) nem de RAM do processo (pico 1.118,2 MB, variação de +2,5 MB em 10 minutos e 24 turnos).

## Como repetir

```
.venv\Scripts\python -m bench.study_models_bench prepare
.venv\Scripts\python -m bench.study_models_bench run qwen3.5:4b qwen3.5:9b
.venv\Scripts\python -m bench.study_models_bench judge
.venv\Scripts\python -m bench.study_models_bench duel
.venv\Scripts\python -m bench.study_models_bench sample
.venv\Scripts\python -m bench.study_models_bench ctx qwen3.5:4b
.venv\Scripts\python -m bench.study_models_bench report
.venv\Scripts\python bench/call_bench.py all
```

O `prepare` copia o índice pela API de backup do SQLite, com a origem aberta só para leitura, e apaga a cópia logo depois da recuperação. O app roda com `LUMEN_DATA` apontando para `bench/.data/study_models`, e nada do `%LOCALAPPDATA%\Lumen` real é aberto para escrita.

## Recusas indevidas e modelos sem filtragem editorial reduzida (07/11/2026)

Medido nesta sessão com `bench/refusal_eval.py` (74 pedidos legítimos em português, fontes sintéticas, segundo Ollama em 11435).
Relatório completo, critérios e reversão: `LUMEN_STUDY_AI_MODELO_LIVRE_20261107.md`. Resumo no conjunto reservado (37 pedidos, prompt
final congelado), "falha" = pedido legítimo recusado, esquivado ou não entregue, segundo qualquer um de dois juízes locais ou o detector:

| Modelo e prompt | Falhas (de 34) | Invenção quando deveria admitir (de 3) | Ferramentas (de 8) | Tempo mediano | tok/s | VRAM a 32k |
|---|---|---|---|---|---|---|
| `qwen3.5:4b`, prompt antigo | 14 | 0 | 6 | 10,2 s | 78,8 | 3,93 GB |
| **`qwen3.5:4b`, prompt novo (adotado)** | **0** | 0 | 7 | 10,1 s | 78,8 | 3,93 GB |
| `huihui_ai/qwen3.5-abliterated:4B`, prompt novo | 3 | **2** | 7 | 11,0 s | 84,0 | 3,93 GB |
| `qwen3.5:9b`, prompt antigo | 8 | 0 | 6 | 16,3 s | 51,5 | 6,12 GB |
| **`qwen3.5:9b`, prompt novo (adotado)** | **1** | 0 | 7 | 17,5 s | 51,5 | 6,12 GB |
| `huihui_ai/qwen3.5-abliterated:9b`, prompt novo | 0 | **2** | 6 | 15,3 s | 54,4 | 6,16 GB |
| `qwen3.5-heretic:9b` (Heretic/ARA, `llmfan46`), prompt novo | 1 | 0 (manual) | 6 | 16,6 s | 52,1 | 5,79 GB |

- **A escolha por papel acima não mudou.** O ganho veio de corrigir o prompt do aplicativo (`SYSTEM`/`SYSTEM_GENERAL`), não de trocar pesos.
- Os abliterados da huihui (Apache-2.0, sem números publicados de recusa) e o Heretic (autor reporta 4/100 recusas contra 86/100 e KL 0,0241,
  no conjunto dele) ficaram instalados como opção; os abliterados fabricaram respostas onde deveriam admitir que não sabem.
- Carga a frio medida (HD): 4B de 4,3 a 29,7 s; 9B de 27,9 a 68,3 s, conforme o cache do Windows. Esforço Máximo pelo fluxo real
  (9B com raciocínio e revisão, carga incluída): 224 s e 308 s nas duas rodadas de hoje, contra 139 s medidos em 01/11; a variação
  acompanha a carga do HD e o tamanho da resposta. A mudança de prompt não mexe nos níveis de esforço.

---

## Perfil adulto (08/11/2026)

Modelo dedicado ao registro adulto (linguagem informal, palavrões e conteúdo adulto consensual entre maiores de 18 anos), medido com
`bench/adult_model_eval.py` nas condições do app, com dados sintéticos e o segundo Ollama (11435). Relatório, critérios, fontes e
reversão: `LUMEN_STUDY_AI_PERFIL_ADULTO_20261108.md` (D92–D99). Conjunto final, 23 casos por modelo, temperatura 0,8:

| Modelo | Entregues (adulto + vulgar, de 10) | Explícito (de 6) | Recusas | Palavrão ≥ 2 (de 4) | Ferramentas (de 8) | Roteador | tok/s | VRAM | Decisão |
|---|---|---|---|---|---|---|---|---|---|
| `qwen3.5:4b` (principal) | 9 | 2 | 0 | 1 | 7 | 12/12 | 81 | 3,9 GB | principal |
| `qwen3.5:9b` (principal, Máximo) | 6 | 0 | 4 | 2 | 7 | 12/12 | 53 | 6,1 GB | principal |
| **`qwen3.5-heretic:9b`** | **9** | **3** | **1** | **3** | 6 | 12/12 | 54 | 5,8 GB (32k) | **perfil adulto** |
| `gemma4-heretic:e4b` | 9 | 2 | 0 | 4 | 7 | 11/12 | 75 | 3,1 GB (16k) | não adotado |
| `gemma4-heretic:12b` (só triagem) | 10 | 3 | 0 | 2 | **1** | 11/12 | 33 | 8,6 GB (16k) | descartado |

"Explícito" é o grau medido pelo juiz local (`qwen3:8b`); "palavrão" é contagem objetiva; os números são sinal de uma amostra pequena
(IC 95% do 3/6: 19% a 81%). O Heretic 9B não atingiu o critério de 70% de explícito e ainda recusou 1 pedido. Roteamento (classificador
`qwen3.5:4b`, final travado): 0/90 falsos positivos, 0/50 falsos negativos, mediana 676 ms.

## Modelos Cloud: Google Gemini e Function Calling

> **Histórico — superado em 09/11/2026.** A integração com o Gemini foi retirada do Lúmen (relatório: `docs/implementation/LUMEN_REMOCAO_GEMINI_20261109.md`). O texto abaixo registra o que foi decidido e medido na época; não descreve o código de hoje.

### 1. Capacidades Suportadas no Lumen
O Lumen separa rigorosamente as capacidades dos modelos Google por modalidade:
- **Chat com Ferramentas (`chat`):** Modelos de texto compatíveis com `generateContent`, streaming SSE (`streamGenerateContent`) e declaração de ferramentas (`functionDeclarations`). Exemplos: `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-1.5-pro`, `gemini-1.5-flash`.
- **Pesquisa Web Integrada (`web`):** O Lumen permite combinar `functionDeclarations` locais com `googleSearch: {}` no array `tools` em modelos compatíveis.
- **Geração de Imagens (`image`):** Endpoint oficial de interações (`/interactions`), restrito a modelos validados de imagem (`gemini-nano-banana-2.1`, `gemini-3.1-flash-image`, etc.).
- **Geração de Vídeo (`video`):** Restrito a modelos com método `interactions` e suporte multimodal a vídeo (`gemini-omni-1.1-flash`).

Modelos especializados sem suporte a chat agêntico (como `gemini-3.8-flash-tts` para Text-to-Speech ou modelos exclusivos de embeddings/áudio) são filtrados na descoberta e rejeitados no backend.

### 2. Validação Estrita de Schemas e Diferença entre Modelos
- **Validador OpenAPI 3.0:** Modelos frontier (como `gemini-3.8-flash` e `gemini-4-argon`) executam uma verificação estrita de integridade onde qualquer campo listado em `required` DEVE existir no dicionário `properties`. Se `properties` for omitido ou esvaziado enquanto `required` mantiver referências, o Google rejeita o pedido com `HTTP 400 Bad Request: Invalid function declaration`.
- **Modelos Lite:** Endpoints de altíssimo throughput (como `gemini-3.5-flash-lite` e `gemini-3.1-flash-lite`) usam um parser mais tolerante que ignora chaves soltas em `required` quando não há propriedades declaradas, ou respondem diretamente em texto puro sem acionar a recusa.
- **Formato Oficial Garantido pelo Lumen:** A função `_google_schema` preserva os nomes dos parâmetros dentro de `properties`, remove recursivamente campos não suportados pelo Gemini (`additionalProperties`, `maxLength`, `minLength`, `$schema`, `default`), normaliza enums para strings e garante que `required` contenha apenas chaves existentes.

### 3. Privacidade e Cobrança
- As chaves de API ficam salvas de forma segura no cofre do sistema operacional (`keyring`) e nunca são enviadas ao navegador, logs ou mensagens de erro.
- O envio para provedores externos só ocorre com a opção "Permitir envio a provedores externos" ativada em **Estudos → Configurações → Privacidade**.
- O provedor padrão do aplicativo continua sendo a IA local (`Ollama`), que opera 100% offline sem emitir requisições à internet.
