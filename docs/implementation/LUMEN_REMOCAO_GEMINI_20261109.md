# Retirada completa do Gemini do Lúmen (09/11/2026)

Executor: Claude Code (Sonnet 5.5). Pedido: tirar o Gemini do Lúmen e seguir só com IA local (Ollama), sem cobrança por chamada de API.
Nada foi publicado, commitado ou enviado; nenhuma chamada ao Gemini foi feita (nem para testar a remoção). O Lúmen aberto pelo usuário
**não foi reiniciado nem substituído** (ver seção 10).

## 1. Conclusão curta

- O Gemini **não existe mais** como função do Lúmen: sem adaptador, modelos, catálogo, chamadas HTTP, streaming, chave, consentimentos,
  verificação de plano, mídia, alternativo automático, rotas nem telas. Não sobrou implementação dormente que uma configuração antiga
  possa reativar: `google` e `gemini` viraram IDs **recusados** (`removed_provider`) pela política.
- O conector **Gemini Notebook** (`lumen/notebook.py`, 699 linhas, e as 20 rotas `/api/notebook/*`) também saiu. O que o Google Drive da
  **Proteção** usava ficou: `lumen/gdrive.py` perdeu só o envio de Docs, e a aba de Integrações virou “Google Drive”.
- Claude (Anthropic) e OpenAI continuam **bloqueados**. Nenhuma outra API externa entrou no lugar.
- A chave do Gemini foi **apagada do cofre do Windows** (só ela). Apagar a cópia local **não revoga** a chave na sua conta Google.
- A IA local (Ollama) segue respondendo; sem modelo instalado, a tela diz como escolher ou baixar um pelo fluxo que já existia.

## 2. Restauração (antes de qualquer edição)

`D:\Lumen\restauracao\remover-gemini-20261109`: 220 arquivos do projeto (`lumen\` inclusive `lumen\web\`, `launcher\*.cs`, `tests\`, `docs\`,
`README.md`, `requirements.txt`; arquivos **não rastreados** incluídos) mais o `settings.json` pessoal. `MANIFEST.json`/`MANIFEST.sha256` (SHA-256),
`git\` (HEAD, status, não rastreados) e `RESTAURAR.md`. Conferida: 221 arquivos íntegros, 0 diferenças na hora da cópia.

```
py -3.14 -I verificar.py            # a cópia está íntegra?
py -3.14 -I verificar.py --origem   # o que mudou no projeto desde a cópia
py -3.14 -I verificar.py --restaurar [--sem-pessoal]   # volta tudo (feche o Lumen antes)
```

`lumen\study\`, `lumen\gdrive.py`, `lumen\notebook.py` e quase toda `lumen\web\` **não estão no git**: não use `git reset/clean/stash/checkout --`.
A cópia não tem chave nem token (o cofre do Windows não foi copiado): a chave do Gemini apagada **não volta** por restauração; seria preciso
gerar outra no Google, o que esta tarefa não pede.

## 3. O que foi removido

| Onde | O que saiu |
|---|---|
| `lumen/study/providers.py` | classes `Google`/`CloudProvider`, cliente HTTP e streaming (`_request_json`, `_request_stream`, repetições, cotas), tradução de histórico/ferramentas/esquemas, `models_for`, `generate_image`, `generate_video`, listas de modelos. `OpenAI` virou stub que só levanta `Blocked`. |
| `lumen/study/policy.py` | `GEMINI_*`, aceites, plano, época da chave, travas de faturamento, fontes e links do Gemini. Ficam `LOCAL`, `PROVIDERS=("ollama",)`, `BLOCKED_PROVIDERS`, `REMOVED_PROVIDERS`, `FEATURES`, `Blocked`, `authorize`, `normalize`. |
| `lumen/study/settings.py` | seção `gemini`, `models.google`, `models.image_google`, `privacy.external`, `gemini_consent`, `lock_gemini`, época da chave, `KEY_ACCOUNTS["google"]`. |
| `lumen/study/api.py` | rotas `POST /api/study/key` e `POST /api/study/gemini`; `GET /api/study/models` lista só modelos locais. |
| `lumen/study/{artifacts,registry,agent}.py` | ramo de imagem em nuvem, `video()` (agora só avisa que o Lúmen não gera vídeo), a entrada “Google Gemini” do catálogo, o “Chat principal” em nuvem. |
| `lumen/study/*` (9 chamadas) | o parâmetro de “projeto permite provedor externo” de `providers.chain` e o interruptor “Provedor externo (Gemini)” dos Projetos (`SOURCE_KEYS` sem `external`). |
| `lumen/notebook.py` | o módulo inteiro (vínculos, exportação, versões, pedidos de estudo, importação, envio de Docs). |
| `lumen/gdrive.py` | `FOLDER` “Lumen - Gemini Notebook”, `DOC`, `_media`, `_mime`, `_multipart`, `get`, `folder`, `create`, `update`; o campo `folder` de `status()`. |
| `lumen/server.py` | 20 rotas `/api/notebook/*`, `_nb`, `_nb_import`, `_nb_audio`; `notebook` e `course_notebooks` da Biblioteca. |
| `lumen/web/*` | cartão e seletores do Gemini em Estudos → Modelos, chave, aceites, links de cotas e plano; o diálogo “Estudar no Gemini Notebook”, seus botões (Análise, Resultado, Biblioteca, “Caderno do curso”, Ctrl+K), cartão de cadernos de Integrações, estilos `.nb-*`; interruptor de envio externo de Privacidade. |
| `tests/` | `test_free_policy.py`, `test_cloud_providers.py`, `gemini_ui.py`, `test_notebook.py` (a parte do Drive foi portada, seção 8). |

## 4. O que foi preservado

IA local/Ollama (chat, rápida, Livre/Notas, histórico, temporárias, fontes e citações, memória, streaming, cancelamento, ferramentas,
flashcards/questionários/planos); embeddings, transcrição, voz e visão locais; imagens e visualizações locais; Notion e Obsidian;
pesquisa guiada no Edge (`/web`); gravação e captura; Proteção e restauração; **autenticação e backup no Google Drive**
(`gdrive.py` + `protection_drive.py`); conversas e materiais já gerados (inclusive os feitos pelo Gemini: a origem continua registrada em
`meta.provider`, só não há mais como chamá-lo). Parâmetros de geração e modelos locais **não** foram alterados. A conversa rápida (barra) não
foi tocada.

## 5. Migração

`settings.migrate()` é guiada pelo **conteúdo** do `settings.json` (não por uma marca): só age se o arquivo ainda guarda `gemini`,
`models.google`, `models.image_google`, `privacy.external` ou um provedor/imagem/vídeo que não existe mais. Então: principal Gemini → `ollama`,
alternativo → `none`, imagem → `local`, vídeo → `none`, campos exclusivos deixam de ser gravados, o **resto é preservado** (inclusive o modelo
local já escolhido; nenhum nome é inventado: vazio continua “Automático”). Guarda **uma** cópia do original
(`settings.json.antes-remocao-gemini-20261109.bak`, nunca sobrescrita), registra `migracao-gemini` no histórico de atividades e depois apaga a
chave do cofre. Rodar de novo não faz nada (nem outra cópia, nem perde preferências novas). Corre ao abrir o servidor (`server.serve`) e na
primeira leitura do estado; um erro nela nunca impede o app de abrir. Mesmo antes de rodar, `settings.load()` já devolve o provedor local.

**Conferida numa cópia do seu `settings.json` real** (dados temporários em D:, cofre em memória; o arquivo real não foi tocado e continua com o hash de antes):
`models.provider: google → ollama`, `models.google` e `models.image_google` removidos, `privacy.external` removido; nenhuma seção nova ou perdida;
cópia `.bak` idêntica ao original; segunda execução sem efeito e sem outra cópia; `models.local` continua vazio (Automático). Log:
`D:\Lumen\remover-gemini-20261109\logs\migracao-copia-real.log`. **A migração do arquivo real acontece quando você reabrir o Lumen.**

## 6. Credencial

Confirmado no cofre real antes de apagar: serviço `Lumen`, conta `google-api-key` (`store.APP` e `settings.KEY_ACCOUNTS`). Apaguei **só** essa
entrada (sem lê-la ou imprimi-la); o `keyring` do Windows apagou junto o registro legado `target=Lumen` da mesma conta. Conferido depois com
`cmdkey /list`: restaram `google-drive@Lumen`, `notion@Lumen` e os quatro `protection-*@Lumen`. Nada de OAuth/token do Drive, do Notion ou da
Proteção foi tocado, nem variável global. O código faz o mesmo (`forget_legacy_gemini_key`) na migração, sem ler o valor. **A chave continua
válida na sua conta Google até você revogá-la em aistudio.google.com/apikey**; a que foi colada no chat de uma tarefa anterior também deve ser revogada.

## 7. Rotas e interface

- Respondem **404** (testado por HTTP real): `POST /api/study/key`, `POST /api/study/gemini` e as 20 de `/api/notebook/*`.
- O Drive da Proteção passou para `GET /api/drive`, `POST /api/drive/client|login|logout` (antes `/api/notebook/drive/*`); `protection.js`
  chama `/api/drive/login`.
- Integrações: Notion, Obsidian, **Google Drive**, Voice Studio. Estudos → Configurações → Modelos mostra o provedor fixo “IA local (Ollama)”,
  os modelos instalados e, se faltar modelo, “escolha ou baixe um em Ajustes → IA local (Ollama); o Lúmen não baixa modelos sozinho”.
- Sem espaços vazios ou separadores órfãos (capturas em `D:\Lumen\remover-gemini-20261109\ui`), sem erro de console e sem requisição fora do 127.0.0.1.

## 8. Testes realizados

Tudo com mocks, cofre em memória e dados temporários em `D:\Lumen\remover-gemini-20261109`; **nenhuma chamada ao Gemini** e nenhuma requisição fora do
127.0.0.1 nos caminhos testados (os testes de bloqueio contam `urlopen` e consultas de DNS).

**A. Testes automatizados (unittest, `.venv\Scripts\python.exe`)**

- **Suíte completa:** `Ran 971 tests in 1030 s — OK` (`logs\full-1.log`). Antes da tarefa eram 1025: saíram 98 testes do recurso eliminado
  (`test_notebook` 30, `test_free_policy` 50, `test_cloud_providers` 18) e entraram 44 (`test_gemini_removed` 34 e `test_gdrive` 10 na hora da rodada).
  Depois de ajustes finais (um rótulo do catálogo e +1 teste de `test_gdrive`), reexecutei os módulos afetados: **162 testes OK**
  (`test_gemini_removed`, `test_gdrive` com 11, `test_study_catalog_eval`, `test_study_core`, `test_study_index`, `test_diagnostics`, `test_protection`,
  `test_protection_overview`). `compileall` de `lumen` e `tests` e `node --check` de todos os `lumen/web/*.js`: sem erro.
- **Os 11 casos pedidos** (`tests/test_gemini_removed.py`): 1 ajuste antigo migra (modelo local e preferências ficam); 2 reexecutar não muda nada, não faz 2ª
  cópia e mantém preferências novas; 3 payload com `google`/`gemini`/variações é recusado, campos antigos são ignorados e não gravados; 4 nenhuma tentativa
  HTTP externa nesses caminhos; 5 as 22 rotas retiradas respondem 404 por HTTP real e não executam nada; 6 a interface não oferece o Gemini (varredura
  de `lumen/web` + Chrome); 7 a IA local continua respondendo (Ollama falso: um turno com ajustes antigos e um com `provider: google` forjado no pedido;
  `/web` vai à pesquisa guiada); 8 a credencial do Gemini sai de um cofre simulado (só a entrada exata; sem ler o valor; idempotente; tolera cofre
  indisponível); 9 as do Drive, do Notion, da Proteção, de outro aplicativo e uma de nome parecido ficam intactas; 10 a Proteção continua usando
  `gdrive` (`test_gdrive`: login PKCE, `state` errado, token renovado uma vez, 403/429 com `Retry-After`, 5xx só no idempotente, criação sem resposta
  nunca repetida, `protection.js` só chama rotas que existem); 11 conversas e artefatos antigos (com `meta.provider="google"`) continuam legíveis, e
  `DATA/notebook*` fica idêntico depois da migração. Mais: sem Ollama o erro é explicado e nada mais é tentado; com Ollama sem modelo de chat o status
  diz “não está instalado”; e a varredura mostra que nenhum `.py` de `lumen/` tem endpoint ou protocolo do Gemini.
- O `tests/__init__.py` agora instala um **cofre em memória** (`tests.VAULT`): nenhum teste lê, grava ou apaga credencial do Windows.

**B. Chrome headless (Playwright) com backend isolado e Ollama falso**

- `tests/local_ai_ui.py`: **7/7** (migração ao abrir o servidor; Modelos, Privacidade e Projetos sem Gemini; conversa respondida pelo Ollama; Integrações com
  Google Drive; Início, Nova aula, Biblioteca, Ctrl+K e catálogo; 404 das rotas antigas), sem erro de página/console, sem requisição fora do 127.0.0.1.
  Capturas em `D:\Lumen\remover-gemini-20261109\ui`.
- `tests/study_ui.py` (regressão geral de Estudos): **passou**. `tests/chat_compact.py` (11 cenários) e `tests/chat_ui.py` (24 blocos): **passaram**, ou
  seja, a conversa rápida não mudou. `tests/protection_ui.py`: **passou**.
- `tests/ui_shots.py` (capturas com API simulada): **não é uma prova útil hoje**, e a causa é anterior à tarefa. Todas as 163 capturas acusam o mesmo
  erro, `Cannot read properties of undefined (reading 'operation')`, porque o script não simula `/api/protection` (o painel da Proteção veio depois dele), e
  `--walk` para no 1º clique (`#go` “not stable”). Reproduzi **o mesmo resultado na árvore original** (cópia do estado de antes em
  `D:\Lumen\remover-gemini-20261109\tmp\arvore-original`, mesmo script, mesmos erros). Atualizei as partes do script que eram do Notebook (cartão do Drive,
  rotas simuladas e passos), e as 9 capturas `drive-card*` rodaram só com esse erro antigo. Não consertei o script: é outro assunto.

**C. Conversa local real mínima**

Ollama real, `qwen3.5:4b`, dados temporários em D:, rede externa bloqueada, ajustes começando como os do Lúmen anterior (Gemini como principal): a migração
levou a `ollama`, o turno respondeu `OK` em 27 s, provedor `ollama`, **0 requisições externas**, 0 erros. Depois descarreguei o modelo (`ollama stop`).
Log: `logs\conversa-local-real.log`. Não toquei na sua sessão pessoal.

**Não foi feito:** nada contra o Gemini (nem para “provar” a remoção); nenhuma validação no executável oficial.

## 9. Buscas finais e classificação do que restou

Busca por `gemini`, `generativelanguage`, `google-api-key`, `notebooklm`, `/api/notebook`, símbolos e rotas removidos, em `lumen/`, `launcher/`, `tests/`,
`bench/`, `scratch/`, docs e README:

| Categoria | Onde | O que é |
|---|---|---|
| **Ausência de integração ativa** | `lumen/` inteiro | **Zero** ocorrência de endpoint/protocolo (`generativelanguage`, `generateContent`, `thoughtSignature`, `x-goog-api-key`, `functionDeclarations`, `googleSearch`) e de rotas/símbolos removidos (`/api/notebook`, `/api/study/key`, `/api/study/gemini`, `CloudProvider`, `models_for`, `gemini_consent`, `openNotebook`…). Testado por `Sources` em `test_gemini_removed.py`. |
| Rejeição e migração (intencional) | `policy.py` (`REMOVED_PROVIDERS`), `providers.py` (comentário), `settings.py` (`obsolete`, `migrate`, `forget_legacy_gemini_key`, `LEGACY_GEMINI_ACCOUNT="google-api-key"`), `api.py`/`server.py` (`migrate_legacy`) | só nomes de campos e IDs para migrar, recusar e apagar a entrada do cofre |
| Dados antigos preservados | `store.py` (a “Limpar” apaga `DATA/notebook/`), texto de “Limpar dados” no `index.html`, rótulos de procedência em `study.js` (“Gemini (Google)”) e `study-settings.js` (“Quem recebeu informações”) | descrevem conversas, envios e arquivos que já existem; não são controles |
| Integração independente do Google Drive | `gdrive.py`, `protection_drive.py`, `protection.py`, `protection.js`, `diagnostics.py`, `/api/drive*`, aba “Google Drive” | backup da Proteção (a nota em `gdrive.py` só registra o que saiu) |
| Testes de rejeição/migração | `tests/test_gemini_removed.py`, `tests/local_ai_ui.py`, `tests/test_gdrive.py`, 1 linha em `test_study_catalog_eval.py` | provam a ausência e a recusa |
| Documentação histórica (marcada como tal) | `LUMEN_GEMINI_GRATUITO_20261109.md`, `LUMEN_STUDY_AI_MODELS.md` (seção Cloud), seções antigas de `docs/DECISOES.md`, `LUMEN_STUDY_AI_*`, `PROMPT_ARGON_CHAMADA_DE_VOZ.md`, `CONTINUIDADE-*` | registro do que foi decidido/medido na época |
| Fora do Lúmen | `scratch/*`, `tests/verify_monitor_ui.py` (`%USERPROFILE%\.gemini\antigravity\…`, `scratch/test_clean_schema.py`) | rascunhos e o caminho de outra ferramenta (Antigravity), sem relação com a integração |
| **Pendente** | nenhum no código | — |

Documentação ativa (`README.md`, `docs/DESIGN.md`, `docs/implementation/LUMEN_STUDY_AI_STATUS.md`) não ensina mais a configurar o Gemini.

## 10. Executável e versão realmente aberta

- **O que está aberto:** `Lumen.exe` (PID 17732, iniciado hoje às 14:08, `--background`) com seus dois `pythonw -m lumen` (14:08). É o código **de antes**: ele ainda
  tem a tela do Gemini na memória e **não foi reiniciado nem fechado** por mim (não interrompo gravações nem processos pessoais).
- **Precisa recompilar?** **Não.** O `Lumen.exe` (98.304 bytes, 03:41, SHA-256 `efa29c81f2c8a85c…`) é só o lançador em C#: ele executa
  `.venv\Scripts\pythonw.exe -m lumen` na pasta do projeto, e a interface (`lumen/web`) é servida dessa mesma pasta. Nenhum arquivo de `launcher/` foi
  alterado por esta tarefa, e o executável não foi sobrescrito. A versão nova passa a valer na **próxima vez que você fechar e abrir o Lumen**.
- **Validação do candidato:** o ponto de entrada (`import lumen.__main__`) importa; o servidor sobe e migra (Chrome headless, `tests/local_ai_ui.py`); uma
  conversa real saiu pelo Ollama. Isso valida o **código novo em backend isolado**, **não** o executável oficial em uso: a primeira abertura do app real ainda é
  uma verificação sua.

## 11. Limitações e verificações pendentes

1. **Falta reabrir o Lumen.** Até lá o aplicativo em uso segue com o código antigo; a migração do `settings.json` real e a conferência visual no app real só
   acontecem depois. A chave já foi apagada do cofre; o app antigo, sem chave, cai para a IA local.
2. **Revogue a chave na Google.** Apagar do cofre não a invalida. Ela existe na conta (aistudio.google.com/apikey); a que foi colada num chat anterior também.
3. **Pasta e documentos no Google** (“Lumen - Gemini Notebook” no seu Drive e os cadernos) não foram mexidos, de propósito. Apague-os pelo Drive se quiser.
4. **Dados antigos no PC:** `%LOCALAPPDATA%\Lumen\notebook\` e `notebook.json` ficam, sem código que os leia. “Limpar dados” apaga a pasta, e `notebook.json`
   (como o catálogo) continua; apague à mão se não quiser.
5. **Sem modelo local instalado**, a IA não responde e a tela diz isso; o Lúmen não baixa modelos sozinho (nenhum foi baixado por esta tarefa).
6. **`tests/ui_shots.py`** continua com falhas antigas (ver 8.B); `--walk` e as 163 capturas não servem de regressão até o script ser atualizado para a Proteção.
7. **Vídeo:** não há geração local; `/video` digitado à mão responde “O Lúmen não gera vídeo”.
8. **Claude/OpenAI** seguem bloqueados no backend (classes de status que só levantam `Blocked`); não foram reativados nem trocados.
9. Os relatórios e seções antigas sobre o Gemini ficaram como **histórico** (marcados), não foram reescritos.

## 12. Reversão

Tudo volta com `verificar.py --restaurar` (seção 2). Arquivos **novos** criados pela tarefa (não apagados pelo `--restaurar`):
`tests/test_gemini_removed.py`, `tests/test_gdrive.py`, `tests/local_ai_ui.py` e este relatório. Arquivos **apagados** pela tarefa e que a
restauração devolve: `lumen/notebook.py`, `tests/test_notebook.py`, `tests/test_free_policy.py`, `tests/test_cloud_providers.py`,
`tests/gemini_ui.py`. Para reativar a chave do Gemini seria preciso uma chave nova (a antiga foi apagada do cofre).
