# Lúmen Study AI: núcleo de inteligência

Registro técnico da aba **Estudos** e do núcleo que ela usa. A auditoria da IA do Obsidian está em `LUMEN_CLAUDE_OBSIDIAN_AUDIT.md`, as decisões em `LUMEN_STUDY_AI_DECISIONS.md` e o estado em `LUMEN_STUDY_AI_STATUS.md`.

## Visão geral

```
Tela (lumen/web/study*.js, study.css) ── /api/study/* (lumen/study/api.py, streaming NDJSON)
  └─ Orquestrador (agent.py): entender → recuperar → ferramentas → responder → validar citações → memória
       ├─ Provedores (providers.py): Ollama (padrão) · Claude (SDK oficial, opcional, guarda de envio externo)
       ├─ Busca (search.py): BM25 (FTS5) + cosseno (qwen3-embedding no Ollama) → RRF → mesmo assunto → links
       ├─ Índice (index.py) ← Conectores (sources/): Obsidian (disco) · Notion (API) · pastas autorizadas · web (SSRF)
       ├─ Ferramentas (tools.py): nível 1 automático · nível 2 só prepara (writes.py grava após o clique)
       ├─ Memória (memory.py) · Conversas e projetos (chats.py) · Modos de estudo (learn.py)
       └─ Dados (data.py) · Atividades (activity.py) · Ajustes (settings.py) — tudo em DATA/study (SQLite)
```

## Persistência

`%LOCALAPPDATA%\Lumen\study\study.db` é um SQLite com WAL e `secure_delete=ON`. As migrações usam `PRAGMA user_version`, em `db.MIGRATIONS`.

- **Índice:** `documents`, `chunks`, `chunks_fts` (FTS5 sem acentos, com uma coluna de radicais de 6 letras para flexões) e `vectors` (float32 normalizado; uma linha por trecho, memória e modelo).
- **Conversas e projetos:** `conversations`, `messages` (com `messages_fts`), `projects` e `project_documents`.
- **Memória:** `memories` (com `memories_fts` e vetores).
- **Estudo:** `flashcards` (estado SM-2) e `items` (resumos, questionários, planos, mapas e respostas salvas).
- **Controle:** `pending_actions` (gravações aguardando confirmação), `activity` (registro sem conteúdo) e `web_cache`.

Os ajustes ficam em `study\settings.json`. O único segredo, a chave da Anthropic, fica no keyring: serviço `Lumen`, conta `anthropic-api-key`.

## Conectores

- **Obsidian:** leitura direta do cofre configurado nos Ajustes.
  - Ficam de fora as pastas ocultas (`.obsidian`, `.trash`, `.claude`), os links e junctions, a cópia do Notion que a Proteção mantém no cofre (marcador `notion-mirror`), as notas com `lumen-protection-origin` e os templates.
  - Lê o texto inteiro, as tags (frontmatter e `#tag`), os `[[links]]`, os aliases e a autoria (`author`/`type`).
  - É incremental por mtime e tamanho.
  - Abre as notas por `obsidian://open`.
- **Notion:** API oficial com o token da integração interna que já existe.
  - Enumera as páginas com `POST /search` paginado, filtrando só páginas e ordenando por edição, e relê os blocos só das páginas cuja `last_edited_time` mudou.
  - O conversor próprio mantém a hierarquia: listas e toggles aninhados, tabelas, código, to-do, callouts e citações. As propriedades das linhas de bases viram metadados e tags.
  - Ficam de fora as páginas que a Proteção cria (`notion-mirror.json` e o bloco marcador), as filhas delas e as que estão na lixeira.
  - Usa o mesmo ritmo de 0,4 s entre pedidos que o backup.
  - Um documento só sai do índice depois de uma enumeração completa.
- **Pastas autorizadas:** Markdown, texto, HTML, CSV e PDF (`pypdf`).
  - Todo caminho é resolvido e precisa ficar dentro de uma pasta autorizada, sem seguir links.
  - O cofre e a própria pasta de dados do Lúmen não podem ser autorizados.
- **Web:** só `http`/`https`.
  - A resolução de DNS é feita aqui e são recusados IPs que não são públicos, inclusive o 127.0.0.1 do próprio Lúmen.
  - A conexão vai para o IP já conferido, contra DNS rebinding, e cada redirecionamento é validado de novo.
  - Teto de 2 MB, HTML convertido para texto e cache com validade.

## Busca (RAG)

1. **Entender:** a heurística é instantânea. Na conversa, a IA devolve em JSON a intenção, o tópico, os termos, as expansões (sinônimos PT/EN e conceitos vizinhos) e a pergunta reescrita pelo histórico.
2. **Lexical:** FTS5 com BM25, com pesos 6 para o título, 3 para os cabeçalhos e 1 para o texto e os radicais.
3. **Semântica:** cosseno sobre `qwen3-embedding:0.6b` (configurável), com a instrução de pergunta que o modelo pede.
4. **Fusão:** RRF com k = 60. Entram no máximo 3 trechos por documento. Conteúdo idêntico vira um resultado só ("também em"), e vetores médios ≥ 0,92 são marcados como "mesmo assunto". As conexões vêm por link e backlink.
5. **Motivo e relevância reais:** a tela mostra as palavras casadas, a semelhança numérica e a relevância relativa à melhor resposta da busca.
6. **Contexto:** os trechos entram numerados `[S#]`, dentro de `<material>` e marcados como dados, até o limite de caracteres configurado.

## Orquestrador e ferramentas

- A recuperação roda sempre. O laço de ferramentas é extra e tem limites: até 6 passos, 12 chamadas e 3 páginas da web por resposta, 180 s, e a mesma chamada repetida é recusada.
- As ferramentas são as mesmas para qualquer provedor:

  | Ferramenta | Nível |
  |---|---|
  | `search_knowledge`, `read_document`, `follow_links`, `list_sources` | 1 |
  | `read_local_file`, `fetch_url`, `open_document` | 1 |
  | `prepare_note` | 2: só prepara a prévia |

  Nenhuma ferramenta edita, move ou apaga originais.
- **Claude:** usa streaming, chamadas de ferramenta com `eager_input_streaming` (entradas validadas no Lúmen), `cache_control` no prompt de sistema, busca web do servidor (`web_search_20260209`/`20250305`) quando a internet está ligada, `fallbacks: "default"` nos modelos que aceitam e tratamento de `pause_turn`/`refusal`. Nunca envia `temperature`.
- **Quando usar ferramentas:** a regra 9 do prompt diz para buscar de novo antes de responder "não encontrei" e para ler, seguir links ou abrir uma fonte quando o estudante pedir (D27).
- **Validação:** as variações de citação (`[S1, S2]`, `(S3)`, `<S2>`) viram `[S#]` (D26). Toda citação `[S#]` inexistente é removida, e a resposta diz quantas foram removidas.
- **Modelo local:** o "Automático" é o `qwen3.5:4b`, para responder e para entender o pedido (D23). Todas as chamadas usam 16k de contexto (D24). A medição está em `LUMEN_STUDY_AI_MODELS.md`.
- **Eventos reais na tela:** entendendo, buscando, lendo X, internet, escrevendo e usando IA alternativa.

## Contexto, compactação e comandos

- **O que vai para o modelo** (`context.window`): o prompt do sistema, o resumo das mensagens antigas e as fixadas antigas. Depois, como texto, as mensagens que não foram resumidas e a pergunta com o material.
- **Medidor:** é o uso medido na última resposta (`prompt_eval_count` no Ollama, `usage` no Claude) sobre a janela usada. Fica na caixa de mensagem, e clicar abre o `/context`, com as partes aproximadas (D30).
- **Compactação:**
  - **Quando:** sozinha, quando o pedido estimado passa de 90% do espaço de entrada; também por `/compact [foco]`, pelo botão do `/context` e por Ctrl+Shift+K.
  - **Como:** o resumo é um JSON com tetos, e as duas últimas trocas e as mensagens fixadas ("Mais opções → Fixar no contexto") vão sempre inteiras.
  - **Não apaga nada:** as mensagens ficam no banco e na tela, com uma linha marcando até onde a IA recebe o resumo (D28).
- **Janela:** 32k nos modelos `qwen3.5` e 16k nos outros. É a mesma em todas as chamadas, para o Ollama não recarregar o modelo (D24).
- **Menu `/`** (`registry.menu`):
  - **Comandos:** `/ajuda`, `/clear` (conversa nova no mesmo projeto e modo, com "Desfazer" no aviso), `/compact [foco]`, `/context`, `/modo`, `/buscar`, `/temp`, `/memoria` e `/exportar`.
  - **Skills do sistema**, que são os modos: `/explicar`, `/resumir`, `/comparar`, `/encontrar`, `/flashcards`, `/quiz`, `/mapa`, `/plano` e `/lacunas`.
  - **Skills do cofre e do usuário:** cada uma vira um comando, como `/buscar-cerebro sono` (D29).
  - **Teclado:** setas, Enter ou Tab para escolher e Esc para fechar.

## Função inteligente e níveis de esforço

- **Automático** (`search.understand`, D32):
  - **Regras baratas primeiro:** palavras explícitas como "flashcards", "me testa", "cronograma" ou "detalhado" decidem a intenção, o esforço e o nível.
  - **Depois, o modelo rápido:** devolve a intenção, o esforço, o nível, os termos, a pergunta reescrita e um motivo curto.
  - **Se a IA falha:** valem as regras, com esforço Equilibrado.
  - **Skills do cofre e do usuário:** no automático, sobem para Profundo, porque têm várias etapas e o modelo local só usa as ferramentas com raciocínio.
- **Chip na caixa de mensagem:** mostra a escolha (ex.: "Automático · Explicar · Equilibrado"), com o motivo na dica. Clicar troca o modo e o esforço, e `/modo` e `/esforco` fazem o mesmo. Cada troca de uma escolha automática vai para o registro de atividades (`troca-automatico`).
- **Níveis** (`agent.EFFORT`, D31):

  | Nível | Modelo (Ollama) | Raciocínio | Fontes | Rodadas de ferramentas | Tempo-limite | Claude |
  |---|---|---|---|---|---|---|
  | Rápido | o modelo rápido | não | 4 | 1 | 2 min | `low` |
  | Equilibrado | o de responder | não | o ajuste (8) | até 5 | 3 min | `medium` |
  | Profundo | o de responder | sim | 12 | até 7 | 7 min | `high` |
  | Máximo | o modelo do esforço Máximo (Automático: `qwen3.5:9b`) | sim, e revisa o rascunho | 16 | até 7 | 15 min | `xhigh` |

  O texto das fontes por resposta também cresce com o nível: metade no Rápido, 1,5 vez no Profundo e 2 vezes no Máximo.

## Memória

- **Cinco categorias:** perfil, longo prazo, episódica (vence em 90 dias), projeto (nunca entra em outro projeto) e procedimental.
- **Campos:** origem, confiança, uso (relevância), datas e retenção.
- **Seleção automática:**
  - fica ativa só a memória com confiança ≥ 0,85 em que o estudante declarou algo sobre si;
  - uma episódica só fica ativa com pedido explícito ("lembre", "anote");
  - o resto, a partir de 0,6, vira sugestão para aprovar;
  - conteúdo sensível nunca é guardado.

  Isso foi ajustado depois do teste real, em que uma pergunta impessoal gerava 3 memórias.
- **Consolidação:** uma memória parecida com outra existente, por radicais ≥ 0,6 ou vetor ≥ 0,9, atualiza a existente em vez de duplicar.
- **Feedback e correções:** 👍/👎 e a correção viram sugestão procedimental. "Analisar minhas preferências" propõe um perfil a partir das avaliações; nada é salvo sem aprovação.
- **Sem treinamento do modelo:** a memória entra como contexto, e a tela diz isso.
- **Importação:** a memória do Claude Code em `C04 Claude Obsidian/04 Memory` entra com prévia e seleção. Também há exportar e importar em JSON.

## Conversas e projetos

- **Conversas:** histórico com busca de texto, fixar, arquivar, renomear (o título sugerido pela IA nunca troca o do usuário), mover para um projeto, apagar uma, várias ou todas (com confirmação digitada), filtro por data e projeto, e exportação em Markdown ou JSON.
- **Conversa temporária:** fica só na memória do processo. Não grava em disco, não cria memórias, não lê memórias no modo privacidade máxima e some ao fechar o app ou após 24 h. Desligar "Guardar conversas no histórico" torna toda conversa nova temporária.
- **Projetos:** cada um tem nome, descrição, objetivos, instruções, fontes permitidas (inclusive envio externo), memórias próprias e documentos fixados, que pesam mais na busca.

## Permissões, atividades e dados

- **Nível 1 (leitura):** automático nas fontes autorizadas.
- **Nível 2 (criar nota ou página):** sempre com prévia e confirmação, ou desligado.
- **Níveis 3 e 4:** não existem como ferramenta da IA. Limpezas de dados do Lúmen pedem confirmação proporcional ao risco, até "digite APAGAR TUDO".
- **Atividades:** a ação, a ferramenta, o alvo (título ou caminho), o resultado, a permissão e o provedor. Nunca o conteúdo.
- **Seus dados no Lúmen:**
  - inventário por categoria, arquivos e tamanhos, onde está o segredo e quais provedores receberam dados;
  - exportação completa sem segredos;
  - exclusão por categoria em transação, que inclui o FTS e os vetores, seguida de `wal_checkpoint(TRUNCATE)`;
  - apagar o índice nunca toca nos originais.

## Interface (aba Estudos)

Redesenho minimalista de 31/10/2026: a conversa é o centro, e o resto fica recolhido até ser pedido. Nenhuma função saiu; algumas mudaram de lugar.

| Parte | Onde fica |
|---|---|
| Cabeçalho | Uma linha: "Estudos", o subtítulo, as abas (Conversar · Estudar · Salvos · Fontes), um único indicador de estado e a engrenagem. |
| Estado da IA, do Notion e do Obsidian | Painel do indicador (`.st-status-pop`), com o modelo em uso. Cada linha leva aos Modelos ou às Fontes. O ponto mostra o pior estado; "não conectado" não conta como problema. |
| Histórico | Coluna recolhível pelo ícone da barra da conversa. A escolha fica em `localStorage` (`lumen.studySide`). Abaixo de 900 px, abre por cima e fecha com Esc ou com um clique fora. |
| Conversas | Lista de uma linha (título e hora). Renomear, fixar, mover, arquivar, exportar e apagar ficam no "⋯" (que aparece ao passar o mouse) ou no clique direito. |
| Fontes | Fechadas por padrão. Abrem pela citação [n], pelas referências abaixo da resposta ("+N" para as demais) ou pelo botão "Fontes N" da barra. A partir de 1180 px, viram painel por cima. Mostram as fontes da resposta clicada, não só da última. |
| Ações da resposta | À vista: Copiar (com retorno "Copiado"), Gerar de novo, Salvar e Mais opções. Em "Mais opções": Aprofundar, Boa resposta, Resposta ruim (corrigir) e Informações da resposta. |
| Informações da resposta | Provedor, modelo, citadas de consultadas, referências removidas, memórias, consultas extras e material cortado (`answerInfo`). Saíram de baixo de cada resposta. |
| Campo de mensagem | Fixo embaixo e centralizado (768 px). O placeholder é "Pergunte qualquer coisa…". O modo fica dentro do campo, e o botão de enviar acende com texto e vira "parar" durante a geração. Enter envia; Shift+Enter quebra a linha (dica no botão). |
| Conversa temporária | Ícone de relógio na barra da conversa. Ligada, mostra "Temporária" e o aviso no estado vazio. |

Notas de implementação:
- **Mensagem da IA:** a classe é `.st-msg.bot`. O nome `.ai` já é o cartão da leitura da IA em `app.css`, e reaproveitá-lo trazia borda e fundo.
- **Classes renomeadas:** pelo mesmo motivo, `.empty` (estado vazio global) e `.st-project` (lista de Projetos) viraram `.is-empty` e `.st-proj-filter`.
- **Listas em grid:** usam `grid-template-columns: minmax(0, 1fr)`. Sem isso, um título longo alarga a coluna além da lateral.
- **Painéis por cima:** precisam de `align-self: stretch`. O `start` da coluna também vale para caixa fixa e a encolheria até o conteúdo.

## Testes

- `tests/test_study_index.py` (8 testes): trechos, exclusões do cofre, incremental, falha que não apaga, busca lexical, semântica e híbrida, mesmo conteúdo, Notion paginado (mais de 100 páginas e mais de 100 blocos) com hierarquia e exclusão do espelho, conversor, ajustes.
- `tests/test_study_core.py` (17 testes):
  - **orquestrador:** streaming, citações validadas, título e memória;
  - **conversas:** temporária, ferramentas, injeção de prompt, confirmação de gravação, permissões e limites;
  - **estudo:** flashcards e SM-2, conversas, projetos e escopo;
  - **memória:** consolidar, editar, apagar, limpar, seleção automática e importação do Claude Code;
  - **gravação:** Obsidian com nome único e área protegida, Notion com página-mãe única;
  - **segurança:** SSRF, caminhos e banco por perfil;
  - **dados:** inventário, exportar e apagar;
  - **Claude:** guarda de envio externo, SDK real contra servidor SSE falso, laço de ferramentas, cache do prompt, sem `temperature`, registro sem conteúdo.
- `tests/study_ui.py` (Playwright): 11 grupos de verificação na janela com backend real isolado. Cobre o estado sob pedido, as fontes fechadas até o clique, Copiar com retorno, "Mais opções" e "Informações da resposta", e o histórico e as fontes por cima a 760 e 520 px.
- Servidores falsos: `tests/fake_ollama.py`, Claude SSE em `test_study_core.FakeAnthropic` e `tests/fake_notion.py`, que agora pagina os blocos filhos sem mudar o comportamento antigo.
