# Prompt: Lúmen Study AI 2.0

> Para colar no Claude Code aberto na pasta do projeto (ou: "Leia e execute `docs/implementation/PROMPT_LUMEN_STUDY_AI_V2.md`").
> Modelo recomendado: **Claude Opus 5.5, esforço `xhigh`** em todas as fases (ajuste à mão: o padrão do Opus 5.5 é `medium`). Se o limite de uso apertar, use **Claude Sonnet 5.5** em `high`. Comece em **modo de plano**.

---

## Para quem é e por quê

O Lúmen é um app de desktop local (Python + WebView2, servido só em 127.0.0.1) que um estudante usa todos os dias: ele transcreve aulas e organiza os estudos no Notion e no Obsidian. A aba **Estudos** (Lúmen Study AI) já existe e funciona.

O estudante quer que ela seja a melhor assistente de estudos que o PC dele consegue rodar:

- que entenda o que ele pede sem configuração;
- que leia tudo o que ele tem: texto, PDF, imagem, áudio, vídeo, Notion, Obsidian, web e a própria tela;
- que **explique de um jeito que acelere o aprendizado**, com hologramas 3D, imagens, PDFs e vídeos;
- que aja por ele: crie páginas, abra aplicativos e navegue na web enquanto ele assiste;
- e que melhore com o uso.

O padrão continua sendo "tudo roda no seu PC". O Claude é opcional (decisão D1). Cada função nova precisa ajudar a aprender de verdade, não só impressionar. Se uma ideia não melhora o estudo, diga isso e proponha outra.

### Orçamento zero

O estudante não tem dinheiro para APIs ou serviços pagos.

- Tudo precisa funcionar bem só com modelos locais e gratuitos.
- O Claude dentro do app continua opcional e nunca é necessário para nenhuma função.
- Nada de serviço pago de imagem, vídeo ou voz.
- O que for baixado precisa ter licença que permita o uso pessoal sem custo.

### Autorização total para instalar (dada pelo usuário em 31/10/2026)

Você pode **baixar e instalar sem perguntar** tudo o que deixar a IA mais avançada e otimizada: modelos, pacotes Python, bibliotecas JavaScript, ferramentas e motores de imagem, vídeo, voz e 3D. Condições:

- **Grátis**, com licença que permita uso pessoal, e de fonte oficial (o site ou repositório do próprio projeto).
- **No D:**, porque o C: está quase cheio. Isso inclui os caches de `pip`, Hugging Face e os temporários dos downloads grandes.
- **Não quebre o que existe:**
  - não reinstale `onnxruntime` junto com o `onnxruntime-directml`;
  - ferramentas com dependências pesadas (como PyTorch) ficam num ambiente separado no D:, rodando como processo à parte, e não no `.venv` principal.
- **Registre cada instalação** em `LUMEN_STUDY_AI_DECISIONS.md` e `_CHANGELOG.md`: o quê, versão, tamanho, onde ficou, licença e por quê. Se for dependência do app, ela entra em `requirements.txt` com a licença no comentário.
- Desinstalar ou substituir algo que o app já usa, ou qualquer coisa que custe dinheiro, **continua exigindo perguntar**.

## O que entregar

1. Corrigir o bug do **Mapa de conhecimento**, que não é gerado. A causa já foi reproduzida (veja abaixo).
2. Escolher o **melhor modelo para este PC** por medição, e ajustar o Ollama para este hardware.
3. Um **sistema de contexto**: medidor de uso, compactação automática e manual (botão, atalho e `/compact`), `/clear` para limpar o chat e `/context` para ver o que ocupa o contexto.
4. **Comandos de barra** no chat (`/`), **skills** (as do sistema, as do cofre e as do usuário) e **integrações** ("plugins"), tudo num registro único.
5. **Níveis de esforço** e a **"Função inteligente"**: o usuário escreve o que quer e a IA escolhe o modo, o esforço e a skill.
6. Chat **multimodal**: anexos de qualquer tipo e leitura de imagens, inclusive as que estão no Notion e no Obsidian.
7. **Chat por voz**, nos dois sentidos.
8. **Geração de imagens** (diagramas precisos e ilustrações).
9. **Sistema avançado de explicação**, com **hologramas 3D interativos dentro do app**, como os das páginas de estudo.
10. **PDFs bonitos e tematizados pelo assunto**, com capa, imagens, hologramas, diagramas e as fontes citadas.
11. **Geração de vídeos** voltados ao aprendizado.
12. **Agente:** criar páginas no Notion e notas no Obsidian, abrir aplicativos, navegar na web numa janela que o usuário vê e ver a tela do usuário quando ele pedir.
13. Nas **Configurações**, um catálogo com todos os comandos, skills, plugins e permissões, e os modelos de cada papel, incluindo os de imagem, vídeo e 3D.
14. Uma IA que **aprende com o uso**, sem prometer o que não existe.
15. **Novas funções de estudo**, propostas e aprovadas pelo usuário.

---

## Fatos já verificados (31/10/2026)

Não refaça este levantamento. Só confira o que pode ter mudado.

### Hardware

| Item | Valor |
|---|---|
| GPU | NVIDIA RTX 3060 **12 GB** (driver 610.88). Com o `qwen3:8b` carregado em 32k de contexto, ~10 GB ficam ocupados. Tem codificador de vídeo NVENC |
| CPU | Intel i5-11400F, 6 núcleos / 12 threads |
| RAM | 15,8 GB |
| Disco C: | **28,7 GB livres (quase cheio).** Atenção: `DATA` (`%LOCALAPPDATA%\Lumen`) fica no C: |
| Disco D: | 844 GB livres. Os modelos do Ollama ficam em `D:\Ollama\models` (`OLLAMA_MODELS`) |

### Software e ajustes reais

- Ollama 0.40.13. Modelos instalados: `qwen3:8b`, `qwen3.5:9b`, `qwen3.5:4b` (é o de visão das aulas, escolhido em `bench/vision_bench.py`), `qwen3-vl:8b`, `qwen3-vl:8b-instruct`, `gemma4:12b` e `qwen3-embedding:0.6b`.
- `%LOCALAPPDATA%\Lumen\study\settings.json`: provedor `ollama`, sem alternativo, `local` e `fast` vazios. Na prática, **o chat e o modelo rápido usam o `qwen3:8b`**, o mais antigo dos instalados, que nunca foi comparado com os outros em tarefas de estudo.
- Python 3.14.8 no `.venv`. Dependências em `requirements.txt`: faster-whisper, onnx-asr (Parakeet), soundcard, pillow, anthropic 2.3.0, pypdf, onnxruntime-directml e **av 16.1.0**.
- **O PyAV instalado já codifica vídeo:** `libx264`, `h264_nvenc` (pela GPU), `libsvtav1`, `libvpx-vp9` e `aac`.

### Código que já existe

**Estudos** (`lumen/study/`, ~3.900 linhas Python, e `lumen/web/study*.js|css`):

- `providers.py`: o Ollama sempre recebe `think: false` e `num_ctx` fixo em 32768. O parâmetro `effort` só chega ao Claude, que é chamado pelo SDK oficial com fallback no servidor.
- `agent.py`: tem o laço de ferramentas, e `search.understand()` já detecta a intenção (find, explain, summary, compare, chat, flashcards, quiz, plan, map, gaps). **É o ponto de partida natural da Função inteligente.**
- `tools.py`: ferramentas com níveis de permissão: buscar, ler, links, listar, ler arquivo, ler URL, abrir e preparar gravação.
- `writes.py`: gravação no Obsidian e no Notion com prévia.
- `search.py` e `index.py`: FTS5, vetores numpy e fusão RRF. O ajuste `rerank` existe, mas a busca não o usa.
- `memory.py`: memória com categorias, consolidação, sugestões e retorno (`memory.feedback`).
- `learn.py`: flashcards SM-2, questionário, plano, mapa e lacunas.
- `chats.py`: histórico, projetos e conversa temporária.
- `sources/`: Obsidian (disco), Notion (API), pastas autorizadas (só `.md .markdown .txt .csv .html .htm .pdf`) e web.
- Ajustes de permissão em `settings.py`:
  - `privacy.organize`: `ask` (sempre com prévia) ou `off`;
  - `privacy.open_windows`: se a IA pode abrir páginas e notas sozinha;
  - `privacy.external`: envio externo.

**Resto do app (reaproveite):**

- `lumen/jobs.py`: fila de trabalhos pesados (`busy`, `start`, `cancel`).
- `lumen/eta.py`: estimativa de tempo.
- `lumen/vision.py`: visão local e **captura da tela pelo GDI do Windows**, com detecção de tela nova.
- `lumen/transcribe.py`: fala para texto.
- `lumen/charts.py`: desenho com Pillow.
- `llm.release_vram()`: tira os modelos de texto da GPU.
- **`lumen/visual3d.py` (1.118 linhas): os hologramas 3D das páginas de estudo.**
  - Monta uma cena tridimensional com cara de holograma a partir do material da aula.
  - Entrega ao Notion e ao Obsidian como GIF animado (com PNG de reserva).
  - Fluxo: spec → validate → cena com primitivas 3D → quadros → GIF/PNG conferidos → cache em `DATA/visuals`.
  - Desenho em NumPy + Pillow, na CPU: perspectiva com câmera orbitando, faces translúcidas, brilho e "famílias temáticas".
  - **Nada da aula ou da IA vira código:** a spec só traz rótulos e índices, e o desenho é sempre o mesmo.
  - Histórico e cuidados em `docs/CONTINUIDADE-3D.md`. Teste: `tests.test_visual3d`.
- **`lumen/imagegen.py`: geração de imagem local que já existe e está instalada**, hoje só para as capas.
  - Usa stable-diffusion.cpp (Vulkan) com o Z-Image-Turbo Q4 (Apache 2.0), escolhido numa comparação com o FLUX.2 [klein] 4B (`docs/DECISOES.md`).
  - Leva ≈ 33 s por capa 1536×640 na 3060.
  - Os arquivos (6,4 GB) estão em `%LOCALAPPDATA%\Lumen\imagem`, **no C:**, porque `image_dir` não está definido na configuração.
- `DECOR_SYSTEM` em `llm.py` e `lumen/cover.py`: o tema por assunto que as páginas do Notion já usam. A IA escolhe emoji, motivos, paleta e cor de destaque a partir do título.
- **A renderização pelo Edge está quebrada.** `cover.py`, `mindmap.py` e `charts.py` transformam HTML em PNG com `msedge --headless --screenshot`, que parou de gravar arquivos no Edge 155. Por isso 3 testes falham desde 20/10. O Edge headless com CDP (`--remote-debugging-port`) continua funcionando.
- Atalhos que já existem: **Ctrl+K** abre a paleta de comandos do app (`app.js:3075`). Ctrl+Enter é usado no editor de entendimento.

### Skills que já existem no cofre do usuário

O cofre (`D:\downloads\cerebro\Cerebro Oficial`) tem skills do Claude Code em `.claude/skills/*/SKILL.md`. Elas têm frontmatter com `name`, `description` e `argument-hint`, e usam `$ARGUMENTS` no corpo.

- São 9 skills: `analisar-lacunas`, `analisar-livro`, `buscar-cerebro`, `criar-briefing`, `detectar-duplicacao`, `processar-inbox`, `revisao-semanal`, `revisar-projeto` e `sugerir-links`.
- Há também 3 agentes em `.claude/agents/`: `archive-curator`, `knowledge-librarian` e `research-assistant`.
- Algumas skills gravam notas (por exemplo, `revisao-semanal`) ou citam ferramentas e agentes do Claude Code.
- O `CLAUDE.md` do cofre define as regras de saída da IA. Por exemplo, as notas geradas vão para `C04 Claude Obsidian/01 Outputs` com `author: lumen-ai` (D7).

### Lacunas confirmadas

- O chat não aceita anexos e não tem comandos de barra, medidor de contexto nem compactação.
- Os Estudos não leem imagens. No Notion, a imagem vira só "[Imagem: legenda]" (`sources/notion.py:90`). No Obsidian, `![[...]]` é ignorado.
- Não há voz, geração de vídeo, geração de PDF nem níveis de esforço para a IA local.
- A geração de imagem e os hologramas existem, mas fora dos Estudos e sem interação: o holograma é só GIF ou PNG.
- A pesquisa na web só funciona com o Claude (D10), porque o modo local não tem motor de busca.
- A IA não cria páginas sozinha: tudo passa por prévia (D11).

### Leia antes de mexer

- `docs/implementation/LUMEN_STUDY_AI_STATUS.md`
- `docs/implementation/LUMEN_STUDY_AI_DECISIONS.md` (D1 a D17 continuam valendo, salvo onde este documento muda)
- `docs/implementation/LUMEN_ADVANCED_INTELLIGENCE.md`
- `docs/DESIGN.md`, `docs/DECISOES.md` e `docs/CONTINUIDADE-3D.md`
- A skill `claude-api`, antes de tocar no código do Claude.

---

## 1. Bug: o Mapa de conhecimento não é gerado (causa reproduzida)

Reproduzido em 31/10 numa cópia do banco (via `LUMEN_DATA`), com `qwen3:8b`, assunto "Psicologia" e 8 fontes:

- `learn.generate("map")` chama `providers.Ollama.json()` e falha com **"A IA devolveu uma resposta fora do formato."** depois de 162 s.
- Saída crua: `done_reason=length` e `eval_count=6000`, que é o teto `max_tokens=6000` de `learn.py:88`. No primeiro conceito, o modelo entrou em laço: `"sources": ["S1","S5","S6","S1","S5","S6", …]` até o teto, e o JSON chegou cortado.
- **Causa raiz:** `learn.schema()` não limita o tamanho dos arrays (não há `maxItems`), e a decodificação guiada por gramática deixa o modelo repetir o enum de fontes sem fim. O banco real não tem nenhum item `kind=map`, enquanto flashcards, questionário e plano foram salvos.

**Corrija na raiz, em `learn.schema()`.** A correção vale para todos os modos, não só para o mapa:

- limite o tamanho de todo array;
- remova repetições no pós-processamento;
- quando a resposta parar no teto, tente de novo com uma instrução mais enxuta e, se falhar outra vez, mostre um erro que diga o que aconteceu.

Confirme com um teste real se o Ollama 0.40 leva `maxItems` e `uniqueItems` para a gramática. `providers.strict()` manda o mesmo esquema para o Claude: confira na skill `claude-api` o que a saída estruturada aceita.

**A mesma lição vale para todo esquema novo deste trabalho** (holograma, roteiro de vídeo, PDF, roteador): todo array com teto.

**Prova:**

- um teste com o Ollama falso (`tests/fake_ollama.py`) que devolve a resposta em laço;
- a reprodução real acima passa a gerar o mapa, de preferência em menos de 60 s.

## 2. O melhor modelo para este PC, medido

**Objetivo:** escolher, por medição neste PC, o melhor modelo para cada papel (principal, rápido/roteador, visão, embeddings e reranker) e ajustar o Ollama para este hardware.

**Candidatos.** Os instalados mais o estado da arte de **outubro de 2026** para 12 GB de VRAM: modelos abertos com bom português, chamada de ferramentas, JSON confiável e visão. Pesquise na web, porque o que você sabe pode estar desatualizado. Baixe os que valerem o teste (autorização total), sempre para o D:.

**Banco de provas.** Crie `bench/study_models_bench.py` no padrão de `bench/vision_bench.py`, com tarefas reais do cofre (só leitura, banco temporário). Meça:

- velocidade e tempo até o primeiro token;
- VRAM;
- JSON válido e citações válidas;
- chamadas de ferramenta corretas;
- qualidade das explicações em português, com rubrica escrita. O juiz é o maior modelo local que couber. Separe uma amostra pequena para o usuário conferir. Não use o Claude como juiz, porque custa dinheiro.

Rode cada tarefa com `think` ligado e desligado.

**Ajuste do Ollama:**

- flash attention;
- cache KV quantizado (confira se a qualidade se mantém);
- `num_ctx` por modelo e por tarefa, no lugar dos 32k fixos;
- um modelo carregado por vez, porque a RAM é de 16 GB;
- `keep_alive`.

Você pode definir as variáveis de usuário do Ollama (`setx`) e reiniciar o Ollama, mas só quando nenhuma aula estiver sendo processada (`jobs.busy()`). Informe o que mudou.

**Resultado:** uma tabela e uma recomendação por papel, gravadas em `docs/implementation/`. **Troque os padrões quando a medição mostrar ganho claro.** Informe no relatório e deixe a troca reversível nas Configurações.

## 3. Sistema de contexto e comandos de barra

**Objetivo:** o estudante sempre sabe quanto do contexto está em uso, nunca perde uma conversa longa por estourar a janela do modelo e controla o contexto como no Claude Code.

### Medidor

- A janela de contexto real depende do modelo: o `num_ctx` escolhido na seção 2 no Ollama, ou o contexto do modelo do Claude.
- Mostre o uso medido, não estimado: `prompt_eval_count` no Ollama e `usage` (ou `count_tokens`) no Claude.
- Na caixa de mensagem, um medidor discreto (ex.: "12 mil / 32 mil"). Ao clicar, ele abre o detalhamento do `/context`.

### Compactação automática

- Começa perto do limite (por volta de 80%; ajuste medindo).
- Resume as mensagens mais antigas e mantém as recentes intactas.
- O resumo preserva o que importa para estudar: o que o estudante disse sobre si, decisões, definições já explicadas, as fontes citadas (ligadas aos documentos, não só aos números S#) e as perguntas em aberto.
- Mensagens fixadas nunca entram no resumo.
- **Não é destrutiva:** as mensagens originais continuam no banco e no histórico. A compactação muda só o que vai para o modelo.

### Compactação manual

- Pelo botão no medidor, por um atalho de teclado e por `/compact [foco]`.
- O foco é opcional (ex.: `/compact mantenha só a parte de farmacologia`).
- Sugestão de atalho: Ctrl+Shift+K, porque Ctrl+K já é a paleta. Confirme que o WebView2 não o reserva.

### No caminho do Claude

Fable 5.1, Opus 5.5 e Sonnet 5.5 vinculam os blocos de raciocínio ao histórico ("preserved thinking"). **Editar turnos antigos pode dar erro 400**, e contas criadas a partir de 31/08/2026 já recebem esse erro. Leia na skill `claude-api` a parte de preserved thinking e de compactação antes de implementar. Escolha um mecanismo que sirva aos dois provedores e explique a escolha em `DECISIONS.md`.

### Comandos de barra

- Digitar `/` no início da mensagem abre um menu filtrável, navegável por teclado, com a descrição e os argumentos de cada comando.
- **Mínimo:**
  - `/clear`: começa uma conversa nova e vazia, com o mesmo projeto e o mesmo modo. A conversa anterior continua no histórico (ou some, se era temporária). Como nada é apagado, não precisa de confirmação; ofereça "Desfazer" num aviso.
  - `/compact [foco]`;
  - `/context`: mostra o que ocupa o contexto (instruções do sistema, memórias, fontes, anexos, histórico e resumo);
  - `/esforco` e `/modo`;
  - `/explicar [assunto]` e `/holograma [assunto]`;
  - `/voz` e `/tela`;
  - `/imagem`, `/pdf [tipo] [assunto]` e `/video`;
  - `/web [tarefa]` e `/abrir [aplicativo]`;
  - `/pagina` (criar no Notion ou no Obsidian);
  - `/flashcards`, `/quiz`, `/mapa`, `/plano` e `/lacunas`;
  - `/buscar` e `/memoria`;
  - `/temp` (conversa temporária);
  - `/exportar`;
  - `/ajuda`.
- Cada skill também vira um comando (ex.: `/buscar-cerebro sono e memória`).
- **Um registro único** (comandos, skills, integrações, permissões e modelos por papel) alimenta o menu `/`, a Função inteligente e o catálogo das Configurações. Nada de listas duplicadas.

## 4. Skills e integrações ("plugins")

### Skills

São pacotes de instruções que a IA segue para uma tarefa. Três origens:

- **Do sistema:** as funções do Lúmen (explicar, resumir, comparar, flashcards etc.).
- **Do cofre:** as skills do Claude Code em `<cofre>/.claude/skills/*/SKILL.md`. São lidas do disco, só leitura, no mesmo formato (frontmatter e `$ARGUMENTS`).
- **Do usuário:** skills criadas e editadas nas Configurações, no mesmo formato, numa pasta do Lúmen.

Regras:

- As skills do cofre foram escritas para o Claude Code. Ao rodar uma, diga ao modelo quais ferramentas do Lúmen correspondem às que ela cita.
- Se a skill delega a um agente (ex.: `knowledge-librarian`), rode a instrução no próprio laço de ferramentas.
- Gravações feitas por skills seguem o ajuste de autonomia da seção 12.
- Skills de várias etapas tendem a precisar de esforço "Profundo": o roteador deve saber disso.

### Integrações

O que aparece como "plugins" são as integrações que já existem ou que este trabalho cria:

- Ollama e Claude;
- Notion, Obsidian, pastas e web;
- navegador do agente e aplicativos;
- visão da tela;
- fala para texto e texto para fala;
- motor de imagem, motor de vídeo e motor 3D.

Cada uma mostra estado, versão, o que acessa e um botão para ligar ou desligar. **Não crie um carregador de plugins de código de terceiros**: rodar código de fora é risco de segurança, e o usuário não pediu isso.

## 5. Níveis de esforço e "Função inteligente"

Quatro níveis, que o usuário pode escolher ou deixar no automático. Os números são o ponto de partida: ajuste com os dados da seção 2.

| Nível | IA local | Claude (se permitido) | Busca e raciocínio |
|---|---|---|---|
| Rápido | modelo rápido, `think` desligado, contexto curto | `effort: low` | poucas fontes, no máximo 1 rodada de ferramentas |
| Equilibrado | modelo principal, `think` desligado | `effort: medium` | ~8 fontes, poucas rodadas |
| Profundo | principal com `think` ligado | `effort: high` | mais fontes, rerank, conferência das citações |
| Máximo | o maior modelo que couber (ou o Claude, se o projeto permitir) | `effort: xhigh` ou `max` | planejar, pesquisar, rascunhar, criticar o próprio rascunho e responder |

O nível vale para tudo, não só para o chat:

- a profundidade da explicação (seção 9);
- o número de passos e o tempo do agente na web (seção 12);
- a quantidade de ilustrações num PDF ou vídeo.

Detalhes:

- Confira em cada modelo como o Ollama aceita `think`. Mostre o estágio "pensando…" sem despejar o raciocínio na resposta.
- Para o Claude, veja na skill `claude-api` as regras de cada modelo: Fable 5.1 e Opus 5.5 sempre pensam, o Opus 5.5 usa `medium` como padrão de esforço, e `temperature` deixa de ser aceita na versão de API de 2026-10-21.

### Função inteligente

- Estenda `search.understand()`, não crie um classificador paralelo. Ela escolhe o modo, o esforço, a skill e o que mais o pedido precisa: web, visão, tela, imagem, holograma, PDF, vídeo, voz, página ou aplicativo.
- Primeiro vêm regras baratas; só depois o modelo rápido decide. Ela precisa ser rápida e, se falhar, cai em "Equilibrado".
- Um chip "Automático" na caixa de mensagem mostra a escolha e o motivo (ex.: "Explicar · Profundo · com holograma"). O usuário troca com um clique.
- As trocas manuais ficam registradas e ajustam o roteador com o tempo (seção 14).
- **Prova:** um teste com pedidos variados e o resultado esperado de cada um, e mais um passo em `tests/study_ui.py`.

## 6. Chat multimodal: anexos de qualquer tipo e leitura de imagens

- O usuário anexa arrastando, colando (inclusive print com Ctrl+V) ou pelo botão de clipe.
- Tipos aceitos e como ler cada um:
  - texto e código, md, csv, html: leitura direta;
  - PDF: texto pelo `pypdf`; se for escaneado, as páginas vão para o modelo de visão;
  - docx, pptx, xlsx, odt e epub: são zip com XML, então leia com a biblioteca padrão ou com uma biblioteca melhor, se compensar;
  - imagens: vão para o modelo de visão;
  - áudio e vídeo: transcritos pelo pipeline que já existe. No vídeo, os quadros-chave também vão para a visão, como as aulas já fazem.
- Cada anexo vira fonte citável na conversa. "Adicionar ao índice" guarda o anexo para as próximas conversas.
- **Segurança:**
  - limite de tamanho por tipo e conferência do tipo real do arquivo (não confie na extensão);
  - nada é executado;
  - os arquivos são limpos ao apagar a conversa;
  - o conteúdo do anexo é **dado, não instrução**: embrulhe-o como `tools.wrap` já faz.
- As imagens vão para a visão local. Para o Claude, só se o envio externo for permitido.
- Anexos grandes não ficam no C:.

**Imagens do Notion e do Obsidian:**

- **Obsidian:** resolva `![[x.png]]` e `![](...)` dentro do cofre.
- **Notion:** as URLs de arquivo expiram em cerca de 1 h, então baixe a imagem durante a sincronização e guarde em cache pelo hash.
- A visão gera descrição e texto lido da imagem (OCR). O resultado vira um trecho de imagem ligado ao documento e à seção onde ela aparece.
- Tudo roda em segundo plano, incremental, cedendo a vez às aulas (`performance.yield_to_lessons`). Ponha um ajuste para ligar e desligar, e um limite por sincronização.
- A resposta pode mostrar a miniatura nas fontes. As cópias da Proteção continuam fora do índice (D14).

## 7. Chat por voz

- **Entrada:** apertar para falar, e um modo de conversa com detecção de voz.
- **Microfone:** decida e explique entre:
  - `getUserMedia` no WebView2: exige tratar `PermissionRequested` em `launcher/Lumen.cs`;
  - gravar pelo Python com `soundcard`, que já é dependência.
- **Reconhecimento de fala:** reaproveite faster-whisper e Parakeet, em português.
- **Fala:** um único motor para o chat, para a narração dos vídeos (seção 11) e para o tour dos hologramas (seção 9).
  - O `speechSynthesis` do navegador não grava em arquivo, então não serve para os vídeos.
  - Compare a SAPI do Windows (`System.Speech`, nativa e que grava WAV) com os melhores TTS neurais locais e gratuitos em português de outubro de 2026.
  - Escolha pela qualidade medida, instale e informe.
- A fala para quando o usuário começa a falar. Markdown e marcadores de citação não são lidos em voz alta.

## 8. Gerar imagens

1. **Diagramas precisos** (fluxogramas, mapas, linhas do tempo, esquemas com texto): a IA gera SVG ou Mermaid, porque modelos de difusão erram texto. Reaproveite o que o app já desenha.
2. **Ilustrações** (conceitos, mnemônicos visuais, capas): **reaproveite `imagegen.py`**, que já está instalado e medido. Leve-o para os Estudos (chat, `/imagem`, PDF e vídeo), com outras proporções além da de capa.
   - Descarregue o LLM antes de gerar (`llm.release_vram()`) e use a fila de `jobs.py`.
   - Troque de modelo só se um teste lado a lado mostrar ganho claro. Vale medir o build CUDA do stable-diffusion.cpp, que pode ser mais rápido que o Vulkan.
   - Mova os 6,4 GB de `image_dir` para o D:: copie, confira os arquivos, aponte `image_dir` para a nova pasta e só então apague a cópia do C:. Faça isso com o Lúmen fechado (peça ao usuário para sair pelo menu), para o app aberto não regravar a configuração antiga.
3. Uma imagem gerada é **ilustração, não fonte**: marque "gerada por IA, pode conter erros" e nunca a use como evidência numa resposta.
4. As imagens ficam na conversa e podem ir para o Notion ou o Obsidian (seção 12).

## 9. Sistema avançado de explicação e hologramas 3D no app

**Objetivo:** quando o estudante pede para entender algo, ele recebe a explicação que mais acelera o aprendizado dele, e não um texto longo. A explicação junta várias formas de ver o mesmo assunto, confere se ele entendeu e se adapta ao que ele já sabe.

### A explicação

Siga o que a ciência da aprendizagem mostra que funciona:

- usar mais de uma forma de representar o mesmo conteúdo;
- exemplos resolvidos passo a passo;
- explicar o porquê, não só o quê;
- prática de lembrar;
- feedback imediato.

Ela tem estas partes, conforme o nível de esforço:

1. **Ponto de partida:** o que o estudante já sabe, tirado do modelo do estudante (seção 14) e das notas dele. Se faltar algo, uma pergunta rápida.
2. **Pré-requisitos que faltam,** com link para as notas que os cobrem.
3. **Camadas:**
   - intuição, com uma analogia;
   - o mecanismo passo a passo;
   - a versão precisa (definição, fórmula);
   - exemplos e contraexemplos;
   - os erros comuns;
   - onde se aplica.
4. **Representações:** texto, diagrama (seção 8), **holograma 3D interativo** e, quando ajudar, ilustração ou imagem das notas.
5. **Checagem:** perguntas curtas no meio. Se o estudante errar, a IA explica de outro jeito em vez de repetir.
6. **Fechamento:** resumo de três linhas, flashcards criados no baralho SM-2 que já existe, e a próxima revisão marcada.
7. **Botões:** "mais simples", "mais fundo", "outro exemplo", "explicar de outro jeito", "tour narrado", "gerar PDF" e "gerar vídeo".

**Por nível:**

| Nível | O que entra |
|---|---|
| Rápido | intuição e mecanismo, em texto |
| Equilibrado | mais diagrama e uma pergunta |
| Profundo | mais holograma, perguntas, erros comuns e flashcards |
| Máximo | tudo, com o tour narrado do holograma |

A explicação usa as notas como base e cita as fontes, como as outras respostas.

### Hologramas 3D dentro do app

Hoje `visual3d.py` gera o holograma como GIF ou PNG para o Notion e o Obsidian. Agora ele também vive **dentro do app**, interativo:

- girar com o mouse, aproximar e afastar;
- clicar numa parte para ver a explicação dela;
- um **tour** que passa pelas partes em ordem, sincronizado com a narração (seção 7);
- animação de processos (o passo 1 acende, depois o 2…).

**Requisitos:**

- **Mesma identidade visual** do holograma atual: aparência, famílias temáticas e paleta.
- **A IA continua produzindo só dados, nunca código.** A spec JSON, validada no Python (reaproveite a validação de `visual3d.py`), escolhe um modelo de cena e traz rótulos, partes, relações e passos. O desenho é sempre o do app. Todo array tem teto (seção 1).
- **Uma spec, vários destinos:** a mesma cena vira o holograma interativo no app e o GIF/PNG do `visual3d.py` para o Notion, o Obsidian, o PDF (seção 10) e os quadros do vídeo (seção 11).
- **Motor no navegador:** escolha e explique entre portar a projeção atual para Canvas/WebGL ou usar uma biblioteca 3D (como three.js). Arquivos locais, sem CDN, respeitando a CSP do app.
- Sem WebGL, cai no PNG.
- Acessível: dá para usar pelo teclado, e há uma lista das partes e relações como alternativa em texto, como o mapa já faz em "Conexões em lista". Respeita a preferência de movimento reduzido.
- Funciona em 520 px de largura.

**Modelos de cena.** Veja no cofre quais assuntos o estudante estuda (Psicologia aparece, por exemplo) e priorize os modelos que servem a eles. Exemplos:

- processo e ciclo;
- estrutura com partes separáveis (vista explodida);
- hierarquia;
- comparação lado a lado;
- linha do tempo;
- rede de conceitos;
- molécula (átomos e ligações);
- órbitas e forças.

Quando o assunto pedir um objeto real (o cérebro, uma célula), você pode baixar modelos 3D abertos (glTF) de licença livre, guardados no D:, com a fonte registrada.

**Prova:**

- testes da spec (validação, tetos e rótulos) e de que o mesmo spec gera o interativo e o GIF;
- um passo em `study_ui` que gira, clica numa parte e roda o tour;
- uma explicação real, a partir do cofre, em cada nível.

## 10. PDFs bonitos e tematizados pelo assunto

**Objetivo:** com um pedido ("faz uma apostila de farmacologia", `/pdf ciclo de Krebs`), o estudante recebe um PDF que dá vontade de estudar. Ele é bonito, tem a identidade visual do assunto, traz imagens que explicam e o conteúdo vem das notas dele, com as fontes.

### Tipos de documento

Pensados para estudar, não só para ler:

- apostila ou resumo do assunto, com sumário;
- folha de revisão de uma página;
- anotações no método Cornell (perguntas na margem, notas no centro e resumo no fim);
- lista de exercícios com o gabarito no fim, longe das questões;
- flashcards para imprimir e recortar, com frente e verso alinhados;
- plano de estudos e simulado;
- mapa de conhecimento ou mapa mental em página inteira;
- a explicação avançada da seção 9, impressa.

### Tema pelo assunto

- Reaproveite o que as páginas do Notion já usam: `DECOR_SYSTEM` escolhe emoji, motivos, paleta e cor de destaque pelo título, e `imagegen.py` desenha a capa ilustrada. Assim o PDF tem a mesma identidade das páginas do mesmo assunto.
- O tema define a capa, a paleta, a cor de cada seção, os ícones e as caixas de destaque (definição, exemplo, atenção, "lembre-se").
- Use fontes livres que já estão no projeto (`lumen/web/fonts`) ou no Windows.

### Imagens

- Diagramas da seção 8, que são exatos e podem ter texto.
- **Hologramas 3D da seção 9**, em PNG.
- Ilustrações geradas, marcadas como geradas por IA.
- Imagens do cofre e do Notion (seção 6), com a fonte.
- Gráficos.

Comprima as imagens para o PDF não ficar enorme.

### Conteúdo

Sai das notas e das fontes, como as respostas do chat, com as citações conferidas. No fim vem uma seção "Fontes", com link para cada nota do Obsidian e página do Notion. O que vier do conhecimento geral fica marcado, como já é feito em Estudar.

### Como gerar

- Escreva HTML e CSS de impressão (`@page`, quebras de página, cabeçalho e rodapé com número de página). Converta em PDF pelo Edge headless via **CDP `Page.printToPDF`**: o Edge já vem no Windows e o CDP funciona.
- Não use a opção `--print-to-pdf` da linha de comando sem testar, porque o `--screenshot` do mesmo Edge quebrou.
- Peça texto selecionável e links clicáveis. Se o Edge instalado aceitar, peça também PDF com marcação (`generateTaggedPDF`) e marcadores (`generateDocumentOutline`).

### Um auxiliar só

Crie um auxiliar de renderização por CDP (HTML para PDF e HTML para PNG) e use-o também em `cover.py`, `mindmap.py` e `charts.py`. Isso conserta a capa, o mapa mental e os gráficos, que estão quebrados desde o Edge 155, e os 3 testes que falham. O mesmo auxiliar pode desenhar os quadros dos vídeos (seção 11).

### Regras

- **Fundo claro por padrão,** que economiza tinta ao imprimir, com uma opção escura para ler na tela. É uma exceção consciente a D9: o PDF é um documento, não a interface do app. Registre isso em `DECISIONS.md`.
- Papel A4 por padrão.
- Cada ilustração leva cerca de 30 s. Use a fila de `jobs.py`, mostre o progresso com `eta.py` e permita cancelar. Limite o número de ilustrações por documento e reaproveite as já geradas.
- O PDF nunca fica no C:. Salve numa pasta configurável no D: ou nos anexos do cofre.
- **Confira o resultado com os próprios olhos:** renderize as páginas em PNG pelo CDP e olhe cada uma, procurando texto cortado, página vazia, imagem quebrada ou contraste ruim.

### Prova

- Um teste que gera um PDF de cada tipo com o Ollama falso e confere o número de páginas, o texto extraível (`pypdf`) e os links.
- Um PDF real, gerado a partir do cofre e conferido página por página.

## 11. Gerar vídeos para aprender

Vídeo só ajuda a aprender quando segue o que a pesquisa mostra funcionar (princípios de Mayer):

- narração com imagem, em vez de texto lido na tela;
- vídeos curtos e divididos em partes;
- destaque do que importa;
- exemplos resolvidos passo a passo;
- perguntas no meio do vídeo (prática de lembrar).

Use isso como critério de projeto. Em ordem de valor e custo:

1. **Vídeo-aula montada, o principal.**
   - A IA escreve o roteiro em cenas (narração, visual e duração) a partir das notas e das fontes.
   - Cada cena vira um quadro: slide, diagrama (seção 8), **holograma girando (seção 9)**, ilustração ou imagem do cofre. O auxiliar CDP da seção 10 desenha os slides a partir de HTML, com o mesmo tema do PDF.
   - A narração usa o motor de fala da seção 7, e o PyAV monta o MP4 (`h264_nvenc` na GPU, ou `libx264`).
   - Legenda (WebVTT) e capítulos saem do próprio roteiro.
2. **Revisão com a própria aula.** Monte vídeos curtos com os trechos da gravação original em que cada conceito aparece, usando os tempos que o resumo da aula já guarda, quando o arquivo original ainda existir.
3. **Vídeo interativo.** O player do app pausa em pontos marcados, faz uma pergunta e só continua depois da resposta. As perguntas ficam num arquivo ao lado do vídeo, não gravadas dentro dele. As respostas alimentam o modelo do estudante (seção 14).
4. **Revisão espaçada em vídeo:** um vídeo curto do dia com os cartões que vencem e as lacunas.
5. **Clipes gerados por difusão:** clipes curtos que ilustram processos (divisão celular, uma cena histórica).
   - Pesquise o estado da arte gratuito de outubro de 2026 que rode em 12 GB, meça o tempo por clipe e instale o melhor num ambiente separado no D:.
   - Use a GPU com exclusividade: descarregue o LLM, use a fila de `jobs.py` e não rode durante o processamento de aulas.
   - Marque como ilustração gerada, que pode conter erros.

Regras:

- Vídeos e modelos **nunca ficam no C:**.
- Mostre o progresso e a estimativa de tempo com `eta.py`, e permita cancelar.

## 12. Agente: páginas, aplicativos, web e tela

**Objetivo:** a IA faz coisas pelo estudante, e ele vê tudo o que ela faz e pode parar a qualquer momento. Tudo segue o nível de esforço (seção 5) e fica no registro de atividades.

### Criar páginas no Notion e notas no Obsidian

- Ferramentas para **criar** páginas e notas completas: com título, tema (seção 10), imagens, hologramas em GIF/PNG, diagramas, fontes e propriedades. Siga o `CLAUDE.md` do cofre e D7.
- Um ajuste novo de autonomia em `privacy.organize`, que hoje tem `ask` e `off`. Ele passa a ter três opções:
  - **sempre com prévia**;
  - **criar sem perguntar nas áreas da IA**: `C04 Claude Obsidian/01 Outputs` e a página dos Estudos no Notion. Esse é o novo padrão sugerido. Fora delas, a IA pede confirmação;
  - **nunca**.
- **Só criar.** Editar, mover ou apagar o que o estudante escreveu continua fora (D11). Atualize D11 em `DECISIONS.md` para registrar a nova regra.
- Cada criação mostra um link e um "Desfazer": no Obsidian, move a nota para a lixeira do cofre; no Notion, arquiva a página.

### Abrir aplicativos

- Uma ferramenta `open_app` com **lista permitida**, editável nas Configurações. Por padrão: Obsidian, Notion, Edge, a pasta do cofre no Explorer e a Calculadora.
- Abrir notas e páginas específicas também vale.
- Nunca comando de terminal livre nem argumentos montados pela IA.
- Segue o ajuste `privacy.open_windows`.

### Navegar na web com o estudante vendo

É como o modo de navegador do Claude ou o Project Astra. Isso também resolve D10: a pesquisa na web passa a funcionar no modo local, por um buscador gratuito aberto na janela.

- **Janela visível.** Uma janela do Edge comandada por CDP ou pelo Playwright (`channel="msedge"`, que usa o Edge instalado). Ela usa um **perfil próprio no D:**, separado do perfil pessoal do estudante.
- **Painel no chat:** mostra cada passo ("Abrindo…", "Clicando em…", "Lendo…") e uma miniatura ao vivo, com os botões **Pausar**, **Assumir** (o estudante controla e a IA espera) e **Parar**.
- **Como a IA enxerga a página:**
  - primeiro a árvore de acessibilidade ou o DOM resumido em texto, que é rápido e funciona com modelos de 8B;
  - captura da página com a visão local só quando o texto não bastar.
- **Limites por nível de esforço:** número de passos e tempo. Peça só tarefas que um modelo local faça bem: buscar, abrir, ler, comparar, coletar fontes. Seja honesto sobre o que fica difícil.
- **Segurança:**
  - antes de enviar formulário, fazer login, comprar, publicar, mandar mensagem, baixar ou subir arquivo, a IA pede confirmação;
  - a IA **nunca digita senhas**: o estudante digita na janela;
  - o conteúdo das páginas é **dado, não instrução** (injeção de prompt);
  - endereços da rede local ficam bloqueados (as regras de SSRF de `sources/web.py`);
  - tudo vai para o registro de atividades.
- **Resultado:** o que a IA encontrar vira fonte citável, e pode ir para o índice e para páginas novas.

### Ver a tela junto

Também como o Project Astra:

- `/tela`, ou um botão no modo de voz, deixa a IA ver a tela e responder sobre ela. Por exemplo: "o que é esse gráfico?" ou "me explica esse slide".
- Reaproveite a captura e a detecção de tela nova de `vision.py`.
- Só funciona com o estudante ativando, sempre com um indicador visível.
- Nada é guardado, a menos que ele peça.

### O que fica de fora

Controlar o mouse e o teclado de outros aplicativos fica fora: um modelo local erra muito nisso, e o risco é alto. Se o estudante quiser no futuro, registre como ideia.

**Prova:**

- testes com páginas falsas servidas localmente e o Edge headless por CDP: buscar, abrir, ler, a confirmação antes de enviar e o bloqueio de rede local;
- testes de criação no Obsidian (cofre temporário) e no Notion (`tests/fake_notion.py`), com desfazer.

## 13. Configurações: catálogo de tudo

Uma seção nova nas Configurações dos Estudos, alimentada pelo registro único da seção 3:

- **Comandos:** cada comando de barra, com argumentos, descrição e atalho de teclado.
- **Skills:** do sistema, do cofre e do usuário, com origem, descrição, comando, botão para ligar ou desligar e "Testar". As do usuário podem ser criadas e editadas ali.
- **Plugins (integrações):** estado, versão, o que cada uma acessa (privacidade) e botão para ligar ou desligar.
- **Permissões do agente:**
  - autonomia de escrita;
  - lista de aplicativos permitidos;
  - navegador (perfil, passos máximos, sites bloqueados);
  - visão da tela.
- **Modelos por papel:** chat principal, rápido/roteador, visão, embeddings, reranker, fala para texto, texto para fala, **imagem**, **vídeo** e **3D**. Para cada um:
  - o modelo em uso, se está instalado, tamanho, VRAM e onde fica no disco;
  - os resultados medidos na seção 2;
  - os botões trocar, baixar e testar.
- **PDF:** os tipos de documento, o tema (automático pelo assunto ou fixo), claro ou escuro, o tamanho do papel e a pasta onde os PDFs são salvos.
- **Instalados por este trabalho:** a lista do que foi baixado, com tamanho, licença e onde está.

Siga o visual atual: escuro, tokens de `ui.css`, prefixo `st-` e o minimalismo de D16. As informações técnicas ficam recolhidas até o usuário pedir.

## 14. Aprender com o uso (sem prometer o que não existe)

Seja honesto com o usuário: **os pesos do modelo não mudam**. Ajuste fino (LoRA) não compensa no uso diário com uma 3060: registre como ideia futura. "Ficar mais inteligente" aqui quer dizer:

- tudo o que entra (anexos, conversas, imagens, páginas da web, aulas processadas) é indexado e pode ser citado;
- um **modelo do estudante**: o domínio de cada conceito vem dos flashcards, das respostas do questionário, das checagens das explicações e dos vídeos interativos, e das perguntas repetidas. Ele serve para ajustar o nível e sugerir revisão;
- correções e 👍/👎 viram memórias de prioridade alta;
- o roteador aprende com as trocas manuais;
- um **conjunto de avaliação local** cresce com as respostas marcadas como boas ou ruins e serve de teste de regressão quando o modelo ou o prompt mudar.

Tudo fica local, visível e apagável em "Seus dados no Lúmen".

## 15. Novas funções de estudo

Proponha uma lista curta e construa só as que o usuário aprovar. Ideias:

- tutor socrático (a IA pergunta em vez de entregar a resposta);
- técnica Feynman (o estudante explica e a IA avalia);
- exercícios com correção passo a passo;
- simulado cronometrado;
- flashcards com imagem (oclusão de partes da imagem) e com holograma;
- resumo em áudio;
- glossário e linha do tempo do curso;
- mapa de conhecimento do cofre inteiro, em 3D;
- ligação com o Pomodoro e os tempos que o app já registra.

---

## Princípios de arquitetura

- **Local primeiro.** Envio externo só com a guarda que já existe (D1).
- **Segurança:**
  - conteúdo de nota, anexo, imagem, página da web ou tela é dado, nunca instrução;
  - a IA cria, mas não edita, move nem apaga originais (D11 atualizada);
  - a IA nunca gera código que o app executa: holograma, PDF e vídeo são sempre dados validados desenhados por código fixo.
- **Reaproveite antes de criar.** Sem LangChain, LlamaIndex ou banco vetorial (D6). Use a biblioteca padrão e o que já está instalado quando servirem. Quando uma ferramenta de fora for claramente melhor, instale-a (autorização total) e registre o motivo.
- **Uma GPU de 12 GB e 16 GB de RAM:** um trabalho pesado por vez (LLM grande, imagem, vídeo, aula), pela fila de `jobs.py`. As aulas têm prioridade.
- **Interface:** tokens escuros de `ui.css`, prefixo `st-` (as classes globais `.ai` e `.empty` colidem), acessível e funcionando até 520 px de largura.
- **Simplicidade:** não acrescente funções, refatorações ou abstrações além do que a tarefa pede. Faça a coisa mais simples que funcione bem, sem deixar nada pela metade. Valide só nas fronteiras (entrada do usuário, arquivos, web, APIs externas).

## Regras deste ambiente (aprendidas na prática)

- **Nos seus testes, sem automação de mouse ou teclado.** Teste a interface com Edge headless + CDP (`tests/study_ui.py`). O `--screenshot` do Edge não desenha alguns gráficos; use o CDP. Isso vale para você durante o desenvolvimento: o navegador do agente (seção 12) usa CDP, não o mouse do Windows.
- **Rode a suíte com `-t .`** (ex.: `.venv\Scripts\python -m unittest discover -s tests -t .`). A configuração real já foi sobrescrita uma vez. Nunca aponte teste para o `%LOCALAPPDATA%\Lumen` real: use `LUMEN_DATA` temporário.
- No teste de interface, o boot zera `store.get_token` e `settings.api_key`, porque o keyring do Windows é compartilhado.
- **O C: está quase cheio.** Nada grande vai para lá, nem caches. Limpe `%TEMP%\lumen-*` depois de testar.
- **Não reinstale `onnxruntime`** junto com o `onnxruntime-directml`.
- **O Lúmen aberto em segundo plano guarda o código antigo.** Peça ao usuário para sair pelo menu e abrir de novo; nunca mate o processo. Ao renderizar a instância oficial, bloqueie `/api/bye`.
- Edite arquivos com a ferramenta Edit. Heredoc estraga barras invertidas.
- **Instalações:** autorização total, nas condições do topo deste documento.
- Commit só quando o usuário pedir. O branch atual é `estudos`.

## Como trabalhar

- **Comece em modo de plano.** Leia os documentos, rode a suíte para ter a linha de base e mostre um plano por fases com o que pretende instalar (com o tamanho). Depois da aprovação, trabalhe com autonomia: as instalações não precisam de nova pergunta.
- **Ordem sugerida:** é a ordem das dependências, e você pode ajustá-la explicando o motivo.
  1. bug do mapa;
  2. modelos;
  3. contexto, comandos e registro;
  4. skills e integrações;
  5. esforço e roteador;
  6. anexos e imagens;
  7. voz;
  8. imagem;
  9. explicação avançada e hologramas no app;
  10. PDFs, junto com o auxiliar CDP que conserta capa, mapa mental e gráficos;
  11. vídeo;
  12. agente (páginas, aplicativos, web e tela);
  13. catálogo nas Configurações, preenchido conforme cada parte fica pronta;
  14. aprendizado;
  15. novas funções.
- **Economize o limite de uso do usuário.** O plano dele é limitado.
  - Use subagentes só quando o trabalho paralelo compensar: pesquisa de modelos de texto, imagem, vídeo, fala e 3D. Para pesquisa e leitura, rode-os num modelo mais barato (Sonnet ou Haiku).
  - Ao fim de cada fase importante, peça a um subagente com contexto novo para conferir o resultado contra este documento.
  - Não releia arquivos à toa e não rode a suíte inteira a cada edição pequena: rode os testes da parte mexida e a suíte inteira no fim da fase.
  - Divida o trabalho em sessões. Uma ou duas fases por sessão, com o `STATUS` como ponto de retomada.
- **Em cada fase:** implemente, teste (unitário e `study_ui`), meça com dados reais em modo só leitura e atualize `LUMEN_STUDY_AI_STATUS.md`, `_DECISIONS.md` e `_CHANGELOG.md`. Termine o `STATUS` com o próximo passo, para que outra sessão continue dali.
- **Registre o que aprender** sobre este projeto na memória do Claude Code deste projeto: uma lição por arquivo, com o porquê. Atualize em vez de duplicar.
- **Pergunte só o que bloqueia:**
  - quais funções novas construir (seção 15);
  - desinstalar ou substituir algo que o app já usa;
  - qualquer coisa que custe dinheiro.

  Para o resto, quando tiver informação suficiente, aja. Ao pesar uma escolha, traga uma recomendação, não uma lista de todas as opções.
- **Quando o usuário só descreve um problema ou faz uma pergunta,** a entrega é a sua avaliação: não aplique a correção até ele pedir.

## Como relatar

- Comece pelo resultado: o que funciona agora e o que o usuário precisa fazer, se houver algo.
- Antes de afirmar que algo está pronto, confira cada afirmação contra um resultado de ferramenta desta sessão. Se um teste falhar, diga isso e mostre a saída. Se pulou um passo, diga que pulou.
- Escreva em português, com frases completas e sem abreviações inventadas durante o trabalho. Quem lê não viu as chamadas de ferramenta.
- Mostre os números medidos: tempos, VRAM, taxa de acerto e o tamanho de cada coisa instalada.

## Pronto quando

- [ ] O mapa de conhecimento é gerado com o modelo local real, e nenhum modo entra em laço até o teto.
- [ ] Há uma tabela de modelos medida neste PC, e os padrões foram trocados onde a medição mostrou ganho.
- [ ] O medidor de contexto mostra o uso real. A compactação automática e a manual (botão, atalho e `/compact`) funcionam com Ollama e Claude sem perder nada do histórico. `/clear` e `/context` funcionam.
- [ ] O menu `/` lista todos os comandos e skills, e as skills do cofre rodam respeitando a autonomia de escrita.
- [ ] Os quatro níveis de esforço funcionam no chat, nas explicações e no agente, e o modo Automático escolhe bem nos testes.
- [ ] O chat aceita os tipos de arquivo listados e lê imagens. As imagens do cofre e do Notion entram no índice e aparecem nas respostas com a fonte.
- [ ] A voz funciona nos dois sentidos, em português.
- [ ] A explicação avançada funciona nos quatro níveis, com checagem e flashcards. O holograma 3D é interativo no app (girar, aproximar, clicar numa parte e tour narrado), e a mesma cena sai em GIF/PNG para o Notion, o Obsidian, o PDF e o vídeo.
- [ ] O app gera diagramas e ilustrações, e gera vídeo-aulas narradas com legenda e perguntas interativas. Os clipes por difusão funcionam.
- [ ] O app gera PDFs tematizados pelo assunto, nos tipos listados, com capa, imagens, hologramas, sumário e fontes, conferidos página por página.
- [ ] A capa, o mapa mental e os gráficos voltaram a ser desenhados pelo auxiliar CDP, e os 3 testes que falhavam passam.
- [ ] A IA cria páginas no Notion e notas no Obsidian conforme a autonomia escolhida, com link e desfazer. Ela abre os aplicativos da lista. Navega na web numa janela visível, com Pausar, Assumir e Parar e confirmação antes de enviar qualquer coisa. E vê a tela quando o estudante ativa.
- [ ] As Configurações mostram todos os comandos, skills, plugins, permissões e modelos por papel, inclusive os de imagem, vídeo e 3D, e a lista do que foi instalado.
- [ ] O modelo do estudante e o conjunto de avaliação local existem, e o usuário vê e apaga esses dados.
- [ ] A suíte inteira passa e `study_ui` cobre os fluxos novos em 1100, 760 e 520 px.
- [ ] Cada instalação está registrada (o quê, versão, tamanho, onde e licença).
- [ ] A documentação está atualizada e o usuário sabe que precisa sair e reabrir o Lúmen.
