# Conversa rápida: modelo Rápido como padrão, ajustes próprios e temporário discreto (09/11/2026)

Relatório de implementação e provas. Decisões D141–D147 em `docs/DECISOES.md`; design em `docs/DESIGN.md` (seção Conversa rápida); uso em `README.md`.
Executor: Claude Code (Sonnet 5.5). Nenhum commit, push, compra, publicação externa, serviço pago nem reinstalação do Gemini. Nenhum modelo foi baixado.

## 1. O que foi confirmado antes de editar

| Ponto levantado | Confirmado |
|---|---|
| `settings.fast_model()` resolve o modelo rápido | Sim: `models.fast` → `RECOMMENDED["fast"]` (vazio) → `local_model` (hoje `qwen3.5:4b`). |
| O agente liga o esforço `rapido` ao modelo rápido local | Sim: `agent._turn` (`model = settings.fast_model(s) if effort == "rapido"`). |
| A requisição da barra não enviava esforço | Sim: caía no automático, quase sempre Equilibrado → `local_model`, enquanto "entender a pergunta" usava `fast_model` (com `models.fast` ≠ `models.local` eram **dois modelos** carregados por pergunta). |
| Menu com nova conversa temporária; `#chat-temp` | Sim (chip em âmbar, só texto). |
| Ponteiro e rascunho no navegador | Sim, e **o ponteiro de conversa temporária ia para o `localStorage`** (corrigido). |
| Não duplicar agente nem histórico | Cumprido: mesma rota `/api/study/turn`, mesmo agente, mesmas conversas. |

## 2. Restauração

`D:\Lumen\restauracao\conversa-rapida-ajustes-20261109` — 1773 arquivos (lumen, tests, docs, launcher, bench, README, requirements, .bat; sem binários), `git status`/`diff`/`HEAD`, e o `settings.json` pessoal de antes. Integridade conferida (0 corrompidos). `py -3.14 -I verificar.py --origem` lista o que mudou; `--restaurar` copia de volta (não apaga arquivos novos). Nunca usar reset/clean/stash/checkout: boa parte de `lumen/study` e `lumen/web` não está no git.

## 3. Como o "Rápido" virou o padrão real (e só da barra)

- A tela manda `surface: "quick"` (e `skip_vault`, `temporary` só quando a pessoa escolheu no menu). **Não manda modelo, provedor, URL nem esforço.**
- `agent._turn` lê `settings.quick` **no começo de cada resposta**. Sem modelo escolhido → `effort = "rapido"` (sem raciocínio; 4 fontes; 2 rodadas de ferramentas: é a definição que o nível Rápido já tinha) e `settings.quick_resolve()` → `fast_model()` resolvido na hora.
- O modelo é **fixado** no provedor (`providers.Ollama.pin`, `providers.chain(s, model=)`): a resposta, entender a pergunta, título, memória, resumo e as demais etapas usam o mesmo modelo (`FakeOllama.requests` prova: um só modelo em todas as chamadas). O comportamento anterior era dois modelos quando `models.fast ≠ models.local`.
- `models.fast` global **nunca** é gravado pela barra; o chat principal (sem `surface`) segue como antes (teste: resposta em `qwen3:8b`, sem `meta.quick`).
- Esforço ≠ modelo: o `meta` da resposta traz `effort: "rapido"` **e** `model`; com modelo escolhido o esforço segue o automático (e o modelo vale em todos os níveis).
- "Tentar de novo" (`regenerate`) lê os ajustes **vigentes** na hora: mesma configuração, sem duplicar a pergunta.
- Perfil adulto: quando escolhido, mantém o modelo dedicado e nada passa pelo modelo da barra (teste). O modelo dedicado ao perfil não aparece na lista da barra nem pode ser escolhido nela.
- Nenhuma chamada externa: teste intercepta `urlopen` e exige só `127.0.0.1`.

**Modelo indisponível:** `settings.quick_resolve()`: pedido → rápido → principal, só entre os instalados. Se difere do pedido: evento `fallback` ("Usando X (“Y” não está instalado)…"), `meta.quick.fallback`, e a tela (Detalhes e Ajustes) diz qual respondeu; o ajuste **não** é reescrito. Nenhum instalado: `AppError` claro ("O modelo rápido “…” não está instalado e não há outro modelo local…") **depois** de confirmar a pergunta, com **Tentar de novo**. Nada é baixado.

## 4. Ajustes desta conversa

- **Onde:** menu ⋯ → **Ajustes desta conversa** (painel interno no lugar da conversa; **Voltar** com ícone e texto, foco inicial, Esc volta). A janela não cresce (conferido na barra real). Só o corpo rola.
- **Conteúdo:** Modelo (*Rápido do Lumen · padrão* com o modelo resolvido; modelos locais instalados; "não instalado" se o escolhido saiu), Novas conversas (Normal | Temporária), Tamanho (o **mesmo** Compacto/Ampliado do menu: uma única função `setWide`, só da sessão), Restaurar. Linha "Responde com …" e aviso de quando vale.
- **Persistência/validação/migração:** `settings.json → quick {model, new_chat}`; `DEFAULTS` migra arquivos antigos; valor editado à mão e inválido volta ao padrão na leitura; `GET/POST /api/study/quick` (`{"reset": true}` restaura só essas chaves). `settings._check` recusa nome fora dos modelos de chat instalados, caminho, URL, provedor, embeddings, modelo do perfil adulto e Ollama fora do ar.
- **Não faz:** reenviar, interromper a resposta em andamento, apagar rascunho, mexer no Cérebro (`models.*`). Aplica do próximo envio, e a tela diz isso (com resposta em andamento: "continua como está").
- Leituras e gravações dos ajustes passam pela **mesma fila** na tela (corrigi uma corrida real: uma leitura começada antes de uma gravação podia terminar depois e devolver o valor antigo).

## 5. Temporário: o que é provado

Servidor (`tests/test_quick_settings.py`): não cria linha em `conversations`/`messages`/`messages_fts`/`memories`; **varredura de todos os arquivos de dados** (SQLite, WAL, índices) não encontra o texto temporário (com controle: o texto normal é encontrado, então a varredura enxerga); não lê memórias pessoais (`temporary_private`); registro de atividades sem o texto (corrigido: erro de ferramenta numa conversa `tmp-` registrava argumentos e mensagem); `quick.new_chat` aplicado pelo servidor só à barra, escolha explícita do menu vale mais, o Cérebro não segue; conversa existente nunca muda de tipo; tentar de novo/continuar mantêm o mesmo id e o caráter temporário; o Cérebro abre o mesmo id como temporário; Notas funciona na temporária; expira pela política existente (fechar o Lumen ou 24 h).

Navegador (`tests/quick_settings_ui.py`): o rascunho temporário, a mensagem e o id temporário **não aparecem** em `localStorage`/`sessionStorage`/cookies; ponteiro só para conversa normal (ponteiro temporário de versão anterior é apagado); rascunho **normal** e **temporário** são dois espaços, trocados ao mudar de conversa; recolher/reabrir e fechar os ajustes mantêm a conversa (em memória).

Visual: chip neutro de 20 px (relógio + "Temporária"), na linha de modo, sem pulso, sem âmbar, que não empurra Livre/Notas; texto de apoio no estado vazio; menu troca para "Nova conversa normal". Livre/Notas e Normal/Temporária não se misturam.

**Não se promete:** anonimato, eliminação forense ou proteção contra o sistema operacional. O Ollama mantém o modelo carregado por alguns minutos (nada do texto é guardado por ele no disco do Lumen). Se a barra recarregar a página, a conversa temporária continua existindo no servidor e no Cérebro, mas a barra deixa de apontar para ela (o ponteiro não é gravado de propósito).

## 6. O erro da captura ("Esta pergunta ficou sem resposta")

Investigado **sem ler o conteúdo** das conversas (só papéis, horários e metadados, em leitura): a conversa mais recente (19:17 UTC) termina numa mensagem do usuário de 2 caracteres sem resposta, e o registro de atividades tem um `envio-externo`/`google` no mesmo minuto: é uma pergunta de antes da retirada do Gemini que **não chegou a ter resposta**. Outras três conversas antigas (08 e 09/11) também terminam numa pergunta sem resposta. Causa: **falha antiga recuperável** (a pergunta foi confirmada e salva, a resposta não), não seleção de modelo, cancelamento nem perda de sincronização da barra. Reproduzido nos testes: bloco 19c de `chat_ui.py` (recarga no meio da resposta) e o novo bloco de falha/retry: a nota aparece, **Tentar de novo** reaproveita a pergunta, não duplica, mantém id/privacidade/modelo e mostra a falha real com mensagem compreensível quando ela existe. Não toquei nas conversas reais (não executei "Tentar de novo" nelas).

## 7. Arquivos alterados

Código: `lumen/study/settings.py`, `providers.py`, `agent.py`, `tools.py`, `api.py`; `lumen/web/chat.js`, `chat.css`, `widget.html`.
Testes (novos): `tests/test_quick_settings.py` (29), `tests/quick_settings_ui.py` (14 blocos). Ajustados: `tests/test_study_core.py` (chave `quick` em `resolved`; limpeza das conversas temporárias entre testes, que vazavam e quebravam `listing`), `tests/chat_ui.py` (mensagem de erro mais clara), `tests/chat_compact.py` (menu de 5 ações).
Docs: `README.md`, `docs/DESIGN.md`, `docs/DECISOES.md`, este relatório.
Não alterados: `launcher/*` (C#), `Lumen.exe`, models.* , dados pessoais.

## 8. Testes e evidências

Pastas isoladas no D: (TEMP/TMP e dados): `D:\Lumen\conversa-rapida-ajustes-20261109\{logs,ui,scripts,data-*}`. Dados do usuário nunca foram escritos por teste.

### 8.1 Teste isolado (Ollama falso, dados temporários)

| Execução | Resultado |
|---|---|
| `.venv\Scripts\python.exe -m unittest discover -s tests -t . -p "test_*.py"` (TEMP curto no D:, sem nada em paralelo) | **1002 testes OK** (25 min). |
| `tests.test_quick_settings` (novo) | **29 OK**: padrão Rápido em todas as etapas (um só modelo), chat principal e `models.fast` intactos, escolha local validada/persistida/recusas (caminho, URL, provedor, embeddings, perfil adulto), pedido não escolhe modelo, ajuste no meio da resposta não a altera, tentar de novo, modelo ausente (recuperação e erro), sem chamada externa (só 127.0.0.1), perfil adulto, restaurar só o `quick`, migração, temporário (banco, memórias, atividades, varredura de todos os arquivos, id e privacidade mantidos, Cérebro, Notas, expiração). |
| `py -3.14 tests/quick_settings_ui.py` (novo, Chrome headless + servidor real) | **14 blocos OK**: ajustes, escolha e persistência, ajuste no meio da resposta, temporário e navegador sem conteúdo temporário, rascunhos separados, Nova conversa normal/temporária, recolher/reabrir, Cérebro, modelo ausente, restaurar, servidor recusando modelo que saiu, servidor anterior sem a rota, teclado/Esc/foco/movimento reduzido, quatro bordas + ampliada, capturas. |
| `py -3.14 tests/chat_ui.py` | 24 blocos OK (uma mensagem de erro mais clara atualizada). |
| `py -3.14 tests/chat_compact.py` | 11 cenários OK (menu de 5 ações). |
| `py -3.14 tests/widget_ui.py`, `test_ui_tokens` | OK. |

Observação sobre a primeira rodada completa: ela falhou em 22 testes (`test_visual3d`, `test_widget`, `test_vision`, `test_estudos`, `test_study_attachments`) porque TEMP apontava para um caminho longo (`D:\Lumen\conversa-rapida-ajustes-20261109\tmp`) e a suíte rodava junto com outras verificações. Rodados sozinhos, com TEMP curto (`D:\Lumen\t`), todos passam; a suíte inteira passou (1002). Não é regressão desta tarefa.

### 8.2 Execução local real (modelo de verdade, dados isolados em D:)

`scripts/real_quick.py` (saída em `logs/pergunta-real.log`, na pasta de evidências do D:): uma pergunta genérica, pelo caminho da barra (`surface: "quick"`, temporária, Livre), contra o Ollama real: `provider ollama`, **`model qwen3.5:4b`**, `effort rapido`, `quick {source: fast, requested: qwen3.5:4b, fallback: false}`, 4,5 s; **0 linhas** em conversas/mensagens/memórias; só `qwen3.5:4b` ficou carregado no Ollama. Sem conteúdo pessoal.

### 8.3 Barra real (`Lumen.Isolado.exe` = mesmo SHA do oficial, WebView2 real, instância isolada, por UI Automation, sem tocar no mouse)

`D:\Lumen\conversa-rapida-ajustes-20261109\scripts\uia_ajustes.ps1`, nas **quatro bordas** (direita, esquerda, em cima, embaixo): abrir a Conversa rápida, menu, **Ajustes desta conversa** (a janela **permanece 304 × 252**), escolher *Temporária* em Novas conversas, Voltar (chip aparece), enviar uma pergunta real ao modelo local numa conversa temporária, menu na temporária, Restaurar, Voltar. Menu de 5 ações sem item fora da janela nas quatro bordas (depois do ajuste de 26 px em cima/embaixo). Achados só vistos no WebView2 e **corrigidos**: dica do botão Voltar cobrindo o título; dica longa do campo voltando ao fechar os ajustes; menu em cima/embaixo cortando a 5ª ação. Uma execução em "embaixo" encerrou a barra no meio (a janela encolheu para 84 × 12; coerente com "perder o foco recolhe"); não se repetiu em duas rodadas seguintes.
Com a máquina ociosa: `Lumen.Check.exe` (WebView2 real, 100 verificações da Conversa rápida, todo o `DesktopChecks.cs`) **OK**. A primeira execução falhou no "Teste 7" de *Minha compreensão* quando a suíte unitária rodava em paralelo; sem carga, passou.

### 8.4 Aplicativo oficial aberto

O `Lumen.exe` oficial (PID 19508, aberto às 18:17) **não foi tocado nem reiniciado**. Ele serve as páginas novas do disco, mas o servidor Python dele é o **código antigo** até ser reaberto: sem `/api/study/quick`, a tela de ajustes mostra "Não consegui ler os ajustes agora… reabra o Lumen" e a barra segue funcionando (o servidor antigo ignora `surface`). Depois de reabrir, tudo vale.

### 8.5 Capturas (inspecionadas visualmente: cortes, alinhamento, proporção)

- `ui\ajustes\10-conversa-normal.png`, `12-conversa-temporaria.png`, `13-ajustes.png` / `14-ajustes-rolado.png`, `11-menu-aberto-compacto.png` (Chrome, 304 × 252 @2x); também `00`–`06` (menu, temporária vazia/com resposta, modelo ausente, restaurados).
- `ui\barra-real\{right,left,top,bottom}-{1..9}-*.png` (WebView2 real, instância isolada).

## 9. Restauração

`D:\Lumen\restauracao\conversa-rapida-ajustes-20261109`: `py -3.14 -I verificar.py --origem` mostra o que mudou desde o ponto de partida; `--restaurar` copia de volta (inclui o `settings.json` pessoal em `dados\`, copie à mão se quiser desfazer a seção `quick`). Os ajustes `quick` só existem no `settings.json` se a pessoa os mudar; "Restaurar ajustes deste chat" os devolve ao padrão sem apagar nada.

## 10. Limitações restantes

- Reabrir o Lumen é necessário para o servidor novo (ver 8.4). Não troquei o executável nem encerrei processos pessoais.
- "Rápido" = o nível Rápido já existente (4 fontes, 2 rodadas de ferramentas, sem raciocínio). Se quiser o modelo rápido **com** o esforço automático, é a escolha *outro modelo* (esforço automático) ou mudar `models.fast`; não alterei a definição do nível.
- Com o perfil adulto ligado em modo automático, o classificador dele usa `fast_model` (não o modelo escolhido na barra): numa pergunta com sinal adulto isso pode carregar dois modelos. Fora do perfil adulto (desligado por padrão), um só.
- Se a barra recarregar a página, a conversa temporária deixa de aparecer nela (continua no Cérebro até o Lumen fechar). O ponteiro temporário não é gravado, de propósito.
- Trocar de conversa na barra abandona a temporária anterior na barra (ela segue na lista do Cérebro até expirar); o rascunho temporário só vive na memória da página.
- O tamanho Compacto/Ampliado continua só da sessão (decisão anterior mantida); "Restaurar" o devolve a Compacto.
- Só o usuário valida: usar com mouse e teclado reais nas quatro bordas, vários monitores/DPI reais, a aparência, e se quer a conversa temporária como padrão (hoje "Normal").
