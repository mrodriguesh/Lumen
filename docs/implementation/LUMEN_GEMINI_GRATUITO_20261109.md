> **Histórico — superado em 09/11/2026.** O Gemini foi retirado do Lúmen no mesmo dia, por decisão do estudante (`LUMEN_REMOCAO_GEMINI_20261109.md`). Este relatório registra a integração gratuita que foi construída, testada com mocks e depois removida; os arquivos, rotas e testes citados abaixo (`policy.py` com os modelos do Gemini, `test_free_policy.py`, `test_cloud_providers.py`, `gemini_ui.py`) não existem mais.

# Gemini gratuito no Lúmen e bloqueio de serviços pagos (09/11/2026)

Executor: Claude Code (Sonnet 5.5). Escopo: chat de texto dos Estudos. Nada foi publicado, commitado ou enviado; nenhuma chamada real ao Gemini foi feita.

## 1. Conclusão curta

- **Não existe Gemini gratuito sem cotas.** A documentação oficial só descreve a camada gratuita *com* limites (por minuto, por dia, em tokens, por projeto) e diz que
  “limites especificados não são garantidos”. A exigência original (“gratuito **e** sem cotas”) não é atendida por nenhum modelo Gemini, e o Lúmen **não a flexibiliza em
  silêncio**: o Gemini vem **desativado** e só abre depois de o estudante aceitar por escrito (1) as cotas, (2) o uso de dados do plano gratuito e (3) confirmar o plano do projeto da chave.
- **Local (Ollama) segue funcionando, sem cota de API** — o limite é o hardware e a janela de contexto; isso nunca é descrito como “infinito”.
- **Claude, OpenAI, imagem/vídeo em nuvem e a busca hospedada do Gemini estão bloqueados no backend** (não só ocultos na tela).
- **Integração real com a conta Google NÃO validada**: não há chave nova cadastrada, o plano do projeto não foi comprovado e a exigência “sem cotas” continua sem solução. Só mocks e testes isolados.

## 2. Fontes oficiais e data

Consultadas em **09/11/2026**. Os endereços `ai.google.dev/gemini-api/...` respondem 301 e levam a `aistudio.google.com/docs/...` (mesmo conteúdo).

| Tema | Endereço pedido | Observação da leitura |
|---|---|---|
| Preços | <https://ai.google.dev/gemini-api/docs/pricing> | Página sem data. ~40 mil de 103 mil caracteres lidos na íntegra (modelos de texto novos, Gemini 4 Argon, Omni, Live, Google Search/Maps, caches); o resto veio de resumo automático e está marcado como “não verificado” abaixo. |
| Limites | <https://ai.google.dev/gemini-api/docs/rate-limits> | **Não publica números por modelo para a camada gratuita**: manda ver “no Google AI Studio” (`aistudio.google.com/rate-limit`). Limites por projeto; RPD zera à meia-noite do Pacífico; “prévias e experimentais têm limites mais restritos”. Não menciona `Retry-After`. |
| Faturamento | <https://ai.google.dev/gemini-api/docs/billing> | Camadas Free/Tier 1–3; mudar para pago = vincular conta de faturamento e pré-pagar US$ 5. **Nenhuma API documentada informa o plano de um projeto só com a chave** (só as páginas Projects/Billing do AI Studio). Teto de gasto por projeto é “experimental”, com ~10 min de atraso. Crédito pré-pago zerado → HTTP 402. |
| Modelos | <https://ai.google.dev/gemini-api/docs/models> | Sem data. Prévias “costumam ter faturamento habilitado e limites mais restritos”; `gemini-2.5-flash`/`2.5-pro` redirecionam em 01/12/2026. `models.list` **não traz campo de preço nem de gratuidade**. |
| Chaves | <https://ai.google.dev/gemini-api/docs/api-key> | Chave vai no cabeçalho `x-goog-api-key`. Chaves novas do AI Studio (desde 28/05/2026) são “auth keys”; a página **não cita prefixo** (`AIza…`/`AQ.…`): por isso o Lúmen **não valida por prefixo**. “Trate a chave como senha”. |
| Chamada de funções | <https://ai.google.dev/gemini-api/docs/function-calling> | A página agora documenta a Interactions API (`/v1beta/interactions`); `generateContent`/`streamGenerateContent` seguem suportados mas “legados”, sem data de desligamento (`api-reference/generate-content`, `llms.txt`). |
| Termos adicionais | <https://ai.google.dev/gemini-api/terms> | Vigência 23/03/2026. **Plano gratuito (“Unpaid Services”): o Google usa o conteúdo enviado e as respostas para melhorar produtos e “revisores humanos podem ler”; “não envie informações sensíveis, confidenciais ou pessoais”.** Em EEE/Suíça/Reino Unido valem os termos pagos. O Brasil está na lista de países. |

Complementos: referência `generate-content` (thoughtSignature, finishReason, erros), `thought-signatures`, `api-errors`, `deprecations` e `available-regions` (todas em `aistudio.google.com/docs/...`).

**Limites da pesquisa:** nenhuma cota numérica da camada gratuita é publicada; nenhuma API oficial devolve o plano do projeto a partir da chave; parte da página de preços foi lida só por resumo. Claude/OpenAI: busca geral (fontes de terceiros conflitantes, nenhuma oficial) → classificados como **não comprovado gratuito** e, pela regra de lista de permissões, bloqueados.

## 3. Modelos e recursos pesquisados

| modelo / recurso | gratuito? | tem cota? | habilitado? | motivo |
|---|---|---|---|---|
| IA local (Ollama) | sim (roda no PC) | sem cota de API (limite = hardware e contexto) | **sim** | local, sem envio |
| `gemini-3.8-flash` (chat) | “Free of charge” na tabela (entrada e saída) | sim; números só na conta | **não por padrão**; só após os 3 aceites | gratuito **com** cotas ≠ exigência “sem cotas”; plano não comprovável pela chave |
| `gemini-3.6-flash` | idem | idem | idem | idem |
| `gemini-3.5-flash-lite` | idem | idem | idem | idem |
| `gemini-3.1-flash-lite` | idem | idem | idem | idem |
| `gemini-4-argon` | **não** (“not available on the Free tier”) | — | **não** | pago |
| `gemini-3.1-pro-preview` | não comprovado (só resumo diz “indisponível”) | — | **não** | gratuidade não comprovada |
| `gemini-3-flash-preview` | não comprovado (prévia; só resumo diz gratuito) | — | **não** | prévias costumam exigir cobrança/limites menores |
| Imagem (`gemini-nano-banana-2.1`, `…3.1-flash-image`, `…3.1-flash-lite-image`, `…3-pro-image`, `…2.5-flash-image`) | não (resumo: “Not available”; cobrado por imagem) | — | **não** | sem gratuidade comprovada |
| Vídeo (`gemini-omni-1.1-flash`, `…1.2-flash`) | **não** (“Not available”; rate-limits: Free “Not supported”) | — | **não** | pago |
| Busca hospedada (Grounding with Google Search) | **não** (Free: “Not available”; US$ 14 por mil após 5 mil/mês no pago) | — | **não** | cobrada à parte → `/web` usa a pesquisa guiada no Edge (local) |
| TTS / Live / transcrição do Gemini | a tabela mostra camada gratuita para alguns (leitura em resumo) | sim | **não** | enviaria áudio; as vozes locais ficam |
| Embeddings do Gemini | camada gratuita (resumo) | sim | **não** | as notas sairiam do PC para indexar |
| Armazenamento remoto (File Search, cache de contexto) | tabela traz preço de armazenamento | — | **não** | arquivos não são enviados para guarda |
| Claude (API Anthropic) | não comprovado (API cobrada por token) | — | **não** | bloqueado |
| OpenAI (API) | não comprovado (API cobrada por token) | — | **não** | bloqueado |
| Gemini Notebook (NotebookLM) | uso pelo site + Drive API | — | inalterado | não chama a API Gemini |

Os quatro modelos “habilitáveis” saem da tabela de preços lida na íntegra. A lista vive em **um só lugar**: `policy.GEMINI_FREE_CHAT` (revisão 09/11/2026; a página avisa reajustes em 01/12/2026 e 01/01/2027). Modelo desconhecido nunca é liberado.

## 4. Diagnóstico (antes)

- `providers.py` não tinha política: `get()`, `chain()`, `Anthropic.*`, `CloudProvider.*`, `generate_image`, `generate_video` e `models_for` eram chamáveis; a UI só **escondia** Claude/OpenAI.
- Ajuste antigo/forjado (`provider=openai`, `image_provider=google`, `video_provider=google`, `fallback=anthropic`) reativava serviços pagos; o personal tinha `image_google=gemini-2.5-flash-image` salvo.
- O chat do Gemini mandava `googleSearch` (cobrado, sem camada gratuita) quando o usuário pedia `/web`.
- Bugs do adaptador: `thoughtSignature` descartado (a doc exige devolvê-lo em chamadas de função do Gemini 3/4, senão 4xx); `id` das chamadas ignorado; `required: []` e `parameters: {properties: {}}` enviados; 402 sugeria “confira faturamento”; 429 sem `Retry-After`; timeout = “não foi possível conectar”; erro no meio do streaming; `finishReason` (SAFETY, MALFORMED_FUNCTION_CALL…) ignorado.
- Falha no meio do streaming com alternativo configurado: o texto parcial ficava na tela e o alternativo escrevia por cima (agora há `replace` antes de repetir).

## 5. O que foi feito

**Política única — `lumen/study/policy.py` (novo).** Lista de permissões: `ollama` e `google` (só chat). `authorize(s, provider, model, feature, has_key)` levanta `Blocked(code, mensagem)` **antes de qualquer requisição** para: provedor pago/desconhecido, recurso não‑chat (imagem, vídeo, `web_search`, TTS, ASR, embeddings, storage), modelo fora de `GEMINI_FREE_CHAT`, e para o Gemini sem **chave, envio externo, cotas aceitas, uso de dados aceito, plano confirmado (por época da chave) ou com trava de plano pago**. `normalize(s)` neutraliza escolhas antigas. `gemini_view()` devolve o estado e o rótulo verdadeiros para a tela.

**Pontos que chamam a política (os únicos caminhos externos):** `CloudProvider._guard` (stream, JSON, fallback, compactação, memórias, atividades, título, entendimento — todos usam `provider.stream/json`), `Anthropic._guard/models`, `models_for`, `generate_image`, `generate_video`, `artifacts.image_blob` (capas, `/imagem`, PDF), `chain()`/`get()` (alternativo nunca paga), `settings.load()` (normaliza na leitura), `settings.save()` (enums fechados; a seção `gemini` não é gravável por PATCH), `api._key` (Claude/OpenAI não recebem chave nova; remover é sempre permitido).

**Aceites do plano gratuito (`settings.gemini`).** `accept_quotas`, `accept_data_use`, `confirmed_epoch` (vale só para a chave atual: trocar/remover a chave sobe `key_epoch` e exige confirmar de novo), `locked_*` (um HTTP 402 prova projeto pago → trava até chave nova). Rota própria `POST /api/study/gemini`. O Lúmen **não gera “para ver se cobra”**: a verificação do plano é a confirmação do estudante em `aistudio.google.com/projects` (coluna Billing Tier).

**Migração conservadora (`settings.migrate`, uma vez por execução, em `/api/study/state`).** Grava no `settings.json` o que a política neutralizou, registra em Atividades (`migracao-politica`) e, antes de qualquer gravação, guarda `settings.json.antes-gemini-gratis-20261109.bak` ao lado do arquivo. Não apaga histórico, memórias, conversas nem chaves do cofre (as chaves antigas continuam lá; “Remover” funciona).

**Erros e cotas.** 400 chave/ferramenta/parâmetros/modelo; 400 `FAILED_PRECONDITION` (plano gratuito indisponível na região) sem sugerir faturamento; 402 → trava e diz que não sugere pagar; 403 acesso negado; 404 modelo inexistente/descontinuado; 429 `RateLimited` (lê `Retry-After`/`retryDelay`, distingue cota diária); 5xx/503 indisponível; 504/timeout “demorou demais”; queda no meio do streaming; cancelamento. **Uma única nova tentativa**, só antes de qualquer trecho da resposta (nada duplicado), só para 429 com espera ≤ 20 s e não diária, e para 503 (2 s); a espera é cancelável a cada 0,25 s. Nenhuma mensagem sugere ativar pagamento, trocar de projeto ou girar chaves.

**Protocolo.** `thoughtSignature` e `id` das chamadas voltam na mesma parte; papéis `user`/`model`; respostas de ferramenta com erro vão como `{"error": …}`; `parameters` omitido sem propriedades; `required` só com propriedades existentes (nomes iguais a palavras‑chave, como `type`/`items`, passam intactos); `type: ["string","null"]` → `nullable`; `finishReason` SAFETY → recusa, `MALFORMED_FUNCTION_CALL`/`MISSING_THOUGHT_SIGNATURE` → erro claro; `promptFeedback.blockReason` → erro claro. Nenhuma ferramenta hospedada é enviada (`googleSearch`, URL, código, Maps, File Search, cache).

**Interface (Configurações → Modelos; barra flutuante intocada).** Provedor principal/alternativo só com “IA local — sem cota de API” e “Google Gemini — <estado>”; cartão “Google Gemini — só texto, plano gratuito com cotas” com chave, modelos liberados, modelos pagos **explicados**, três aceites, links para o plano e as cotas da conta, e o estado real (“Indisponível pela exigência de uso sem cotas”, “Plano gratuito não confirmado”, “Gemini — gratuito com cotas (plano confirmado por você)”). Sem “ilimitado”, “custo zero” ou “funcionando”. Cartões de imagem e vídeo em nuvem removidos; `/video` saiu do menu; `/imagem` e a capa do PDF só usam o gerador local; `/web` sempre usa a pesquisa guiada no Edge.

## 6. Testes executados (todos com mocks e dados isolados em D:)

- `tests/test_free_policy.py` (novo, **50 testes**): catálogo (livres × pagos × desconhecidos); configuração antiga não reativa nada; migração com cópia e idempotente; PATCH não grava aceites; chamadas diretas a Claude/OpenAI/imagem/vídeo/capas com ajustes **forjados** — afirmam que `urlopen`, `_request_json`, `_request_stream` e o SDK da Anthropic **nunca foram chamados**; modelo arbitrário/`../` recusado; `web=True` bloqueado; portão do Gemini item a item (chave ausente, envio externo, cotas, dados, plano, trava 402, época da chave); alternativo nunca paga e obedece ao mesmo portão; erros 400/402/403/404/429/500/503/504/timeout; 429 com `Retry-After`, diária, longa, sem espera (no máx. 1 nova tentativa); cancelamento durante a espera; queda e erro SSE no meio do streaming; cancelamento fecha a resposta; assinatura de raciocínio, ids, papéis e múltiplas etapas; JSON estruturado; esquemas; **nenhum segredo** em erros, status, ajustes, Atividades, URL ou corpo; ponta a ponta pelo agente (mesma rota da barra e do Cérebro): sem aceites a resposta é local e nada sai; com aceites o Gemini recebe só `generateContent` sem ferramentas hospedadas; `/web` vai ao Edge; falha no meio do streaming com alternativo local troca o texto sem duplicar.
- `tests/test_cloud_providers.py` (reescrito, 18 testes) e `tests/test_study_core.py` (classe `Claude` reescrita: Claude **bloqueado** mesmo com chave, servidor falso no ar e arquivo forjado; zero requisições).
- `tests/gemini_ui.py` (novo): backend real isolado + Chrome headless, **7 verificações OK**: estados verdadeiros na tela, modelos pagos explicados, aceites liberando, chave nova exigindo confirmar de novo, PATCH recusado, `/video` fora do menu, nenhum vazamento da chave. Capturas em `D:\Lumen\gemini-gratis-20261109\ui\`.
- **Suíte completa (`unittest discover`, 1025 testes, dados em D:)** — resultado honesto:
  - 2ª rodada, ociosa: **1025 testes OK** (1436 s). Log: `D:\Lumen\gemini-gratis-20261109\logs\pos-mudanca-full-2.log`.
  - 1ª rodada (`pos-mudanca-full.log`): 16 falhas + 5 erros, **todos** em `test_vision.Lifecycle` (2), `test_visual3d.Pages` (15), `test_widget.Widget` (3) e um *tearDown* de `test_study_attachments`
    (“o índice anterior precisa parar”) — testes de threads/tempo que rodaram enquanto eu usava a máquina para outras tarefas. **Não reproduziram**: os mesmos módulos, isolados na árvore modificada,
    deram 114/114 OK (`modificado-falhas-isolado.log`); depois dos meus testes, 163/163 OK (`ordem-minhas-primeiro.log`); e a 2ª rodada completa passou. Tratei como intermitência de ambiente, não como regressão.
  - Linha de base limpa (cópia da restauração em `D:\Lumen\gemini-gratis-20261109\baseline-tree`, sem `bench\`, `.exe` e binários): 979 testes, 7 erros só da cópia incompleta (`test_bench_metrics`, restic em
    `test_protection*`, registro do Windows em `test_widget`) — nenhum em provedores, política, Estudos ou interface. Log: `baseline-limpo-full.log`.
  - `tests/study_ui.py` (regressão geral da aba Estudos, Chrome headless, 33 blocos de verificação): **passou** (`passed: true`; nenhum erro de página, bloqueio de CSP ou resposta 5xx). Capturas em `D:\Lumen\gemini-gratis-20261109\ui-study`, log `logs\study-ui.log`.

## 7. Limitações e o que só você valida

1. **Exigência “sem cotas” sem solução** — ativar o Gemini gratuito exige aceitar as cotas oficiais. Decisão sua.
2. **O plano do projeto não é comprovável pela chave**: a confirmação é sua (AI Studio → Projects). Se a chave for de um projeto com faturamento, o Lúmen não tem como saber até receber um 402.
3. **Privacidade do plano gratuito**: o conteúdo enviado pode ser usado pelo Google e lido por revisores. Não envie nada sensível; projetos com notas pessoais devem manter “permitir envio externo” desligado.
4. **Nenhuma chamada real ao Gemini foi feita**: protocolo, thought signatures, esquemas e erros seguem a documentação e os mocks; o comportamento real da API (inclusive o legado `generateContent` e um `FAILED_PRECONDITION` regional) só se confirma com a sua chave nova, depois dos aceites.
5. As cotas numéricas não são publicadas e a conta só as mostra no AI Studio: o Lúmen não as conhece nem as inventa.
6. **Capacidades por modelo não verificadas**: ferramentas, JSON estruturado e streaming de cada um dos 4 modelos ficam nas páginas por modelo, que não foram lidas (a página-índice só tem o Gemini 4 Argon detalhado). O Lúmen usa funções (`functionDeclarations`) e `responseMimeType: application/json` com o esquema no prompt (não `responseJsonSchema`); se um modelo recusar, o 400 vira “o Gemini recusou a definição de uma ferramenta / os parâmetros da conversa” e o alternativo local (se escolhido) responde. A limitação não pode ser anunciada antes da chamada porque a API de listagem não informa isso.
7. `generateContent` é legado segundo a documentação; a migração para a Interactions API fica para quando houver validação real.
8. Os endereços de preço mudam (01/12/2026 e 01/01/2027): revisar `policy.GEMINI_FREE_CHAT` e `REVIEWED` nessas datas.
9. Não validado no app oficial em uso: o `Lumen.exe` em execução não foi tocado nem reiniciado; a interface foi vista no backend isolado com Chrome headless, não na janela nativa.

## 8. Credencial

A chave colada no chat durante a tarefa **não foi usada, testada, gravada nem copiada para nenhum arquivo ou relatório**. Como foi digitada em texto puro, trate-a como exposta: **revogue-a** em aistudio.google.com/apikey e cadastre uma nova só pela tela Configurações → Modelos (Gerenciador de Credenciais do Windows). Os testes usam chaves de mentira.

## 9. Restauração

- Cópia íntegra: `D:\Lumen\restauracao\gemini-gratis-20261109` (194 arquivos do projeto + `settings.json` pessoal; `MANIFEST.json`/`.sha256`; `git\` com HEAD/status/não rastreados). Independe do app e do git.
- `py -3.14 -I verificar.py` (confere), `--origem` (o que mudou), `--restaurar` (volta tudo; `--sem-pessoal` mantém o `settings.json` atual). Feche o Lúmen antes.
- Arquivos novos desta tarefa (não são apagados pelo `--restaurar`): `lumen/study/policy.py`, `tests/test_free_policy.py`, `tests/gemini_ui.py`, este relatório. Para remover, apague-os.
- A migração guarda também `settings.json.antes-gemini-gratis-20261109.bak` ao lado do `settings.json` (a 1ª gravação depois da mudança).
- **Não** use `git reset`, `clean`, `stash` nem `checkout`: `lumen/study/` e boa parte de `lumen/web/` não estão no git.
