# Fase 8 — implementação e evidências de 04–05/11/2026

## Estado

Implementação entregue no checkout. **Resultado reconciliado em 06/11:** `D:\Lumen\validacao-fase8-20261104\suite-final-2.log` terminou com 817 testes em 1183,345 s, OK. Resultado histórico conferido na fase 9, não executado novamente como prova atual. Interface anterior: 29 verificações. Não confundir a interface em navegador de teste com a janela nativa do executável. Nenhuma publicação real no Notion nesta sessão.

## Preservação

- Branch `estudos`, HEAD `88160399ce8858aa1dff3d976f0767e3f7595823`. Sem commit, reset, clean, stash ou checkout destrutivo.
- Antes da implementação: `D:\Lumen\restauracao\study-fase8-20261104`, 282 arquivos/44.340.851 bytes; ZIP SHA-256 `941989475e74b8c0836647a85e24e7c47191ea17e5359b5e8caf2de94324b98d`.
- Na retomada de 05/11: `D:\Lumen\restauracao\study-fase8-20261105`, 304 arquivos/44.607.581 bytes; ZIP SHA-256 `3a2ddccac23de24a27af59fe718b04869cabb3fc5cccd25d39079124f4fcbeb3`.
- Ambos incluem rastreados, não rastreados, manifestos, diff, estado do Git e conferência por leitura de cada entrada. Não incluem perfis pessoais ignorados, credenciais nem modelos.
- Houve alterações paralelas no visual, launcher, executável, modo livre e provedores de nuvem. Preservadas; o diff inteiro desses arquivos não é autoria desta fase. Esta sessão não recompilou o executável nem alterou C#.
- A migração de `image_dir` não foi repetida. Origem no C: preservada. Nenhuma instalação nova.

## Implementação

- `writes.py`: três opções de autonomia, áreas fixas da IA, revalidação de destino/permissão, criação exclusiva sem sobrescrita, confirmação por leitura no Notion, registro de criações e desfazer por identidade/conteúdo. Resultado parcial do Notion mantém id e estado `unconfirmed`, sem nova criação automática.
- `apps.py`: lista fixa de cinco aplicativos, editável por habilitação nas Configurações; comandos/argumentos da IA são recusados. Abertura automática depende de `privacy.open_windows`; clique explícito é distinto da abertura automática.
- `browser.py`: busca pública, resultados lidos do DOM da versão de leitura, escolha limitada de índices, páginas pelo transporte protegido, Edge visível com perfil próprio, miniatura, pausa/parada e limites por esforço. Conteúdo dos sites não executa scripts nem envia formulários.
- `agent.py`, `tools.py`, `registry.py`, `api.py`: `/nota`, `/pagina`, `/web`, `/abrir`, ferramentas e rotas. Pedido explícito concede criação só no destino escolhido; uma fonte lida não concede autonomia. Falha na criação não descarta a resposta do chat.
- `study.js`, `study.css`, `study-settings.js`: link e Desfazer persistentes ao reabrir a conversa, painel da pesquisa, opções de permissão e aplicativos.
- Salvar explicação ou mapa mental agora inclui o PNG do diagrama pela prévia existente, renderizado só na confirmação; usa o mesmo caminho de anexos e a mesma conferência de arquivo no Notion.
- `/tela` continua opt-in, com indicador existente; a captura não é persistida automaticamente. Nenhuma ativação de microfone real ou alteração no Voice Studio.

## Provas executadas

Comandos abaixo executados na raiz, com `TEMP`/`TMP=D:\Lumen\temp-fase8` e `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`. `tests/__init__.py` cria `LUMEN_DATA` temporário e neutraliza o Voice Studio pessoal. O teste visual substitui as funções de acesso às credenciais por respostas vazias para todos os provedores.

| Comando | Resultado observado |
|---|---|
| `.venv\Scripts\python.exe -m unittest tests.test_study_core.Writes tests.test_study_pdf -v` | 17 testes, 135,417 s, aprovados; transição viável da fase 7. |
| `.venv\Scripts\python.exe -m unittest tests.test_study_core tests.test_study_agent tests.test_study_pdf tests.test_cdp -v` | 69 testes, 232,327 s, aprovados na primeira implementação da fase 8. |
| `.venv\Scripts\python.exe -m unittest tests.test_study_agent tests.test_widget -v` | 23 testes, 48,095 s, aprovados após corrigir a fixture do widget. |
| `py -3.14 tests/study_ui.py` | **29 verificações aprovadas novamente em `ui-final.log`**, em 1440, 1100, 760 e 520 px. Inclui fase 7, novo passo 14 e o checkout com provedores paralelos. Sem erro de página, CSP ou `OperationalError` nessa rodada. |
| `.venv\Scripts\python.exe -m unittest discover -s tests -t . -v` | Primeira rodada: 788 testes em 1.251,759 s, um erro na fixture de `test_closed_widget_connection_does_not_raise`; corrigido inicializando `close_connection`, campo normal do handler HTTP. Rodada final em execução. |

Falhas intermediárias transparentes: o primeiro teste visual esperava “Voltar aos estudos”, alterado pelo trabalho paralelo para “Voltar ao Cérebro”; o primeiro teste novo de diagrama usou um nome de função incorreto, corrigido para `diagram.from_mind`. A rodada isolada desse diagrama passou em 34,035 s. Houve um `OperationalError` transitório no estado inicial durante `ui-2`, sem reprovação dos fluxos; já havia registro histórico desse comportamento. Não foi atribuída causa sem rastreamento.

A rodada `suite-final.log` encontrou também 11 regressões do trabalho paralelo de provedores/configurações. Causas corrigidas em `providers.py`: conversão do esquema Gemini descartava nomes de parâmetros, histórico usava `assistant` onde o Gemini espera `model`, e o tratamento de erro não reconhecia `streamGenerateContent`/modelo incompatível. A fixture de configurações ainda esperava rejeição de `openai`, agora válido; passou a testar `inexistente`. `.venv\Scripts\python.exe -m unittest tests.test_study_index.Settings tests.test_cloud_providers -v`: **27 testes, 0,233 s, aprovados**, log `parallel-regressions-ok.log`. Nova suíte completa em `suite-final-2.log`. Isso é validação com transporte falso, sem chaves ou chamadas reais a Google/OpenAI. Contrato: [referência oficial Gemini](https://ai.google.dev/api/generate-content?hl=en).

Evidências: `D:\Lumen\validacao-fase8-20261104`. Logs `baseline.log`, `focused.log`, `agent-final.log`, `suite-1.log`, `suite-final.log`, `ui-2.log`, `ui-final.log`; capturas em `ui` e `ui-final`. Foram inspecionadas visualmente a criação em 1440 px, pesquisa em 520 px, permissões em 520 px e leitura real do Edge. Alguns sites trazem menus/aviso de ausência de JavaScript no texto extraído; a versão de leitura não reproduz o layout original.

### Serviço falso e geração local de arquivos

Notion falso com leitura real dos blocos dentro do servidor de teste: criação, texto, arquivos, ida à lixeira, recusa de desfazer após edição e criação parcial. Cofre temporário: arquivo Markdown e PNG reais, leitura do conteúdo, SHA-256, recusa de sobrescrita, preservação de edição e movimentação da criação intacta para `.trash`. Anexos são preservados ao desfazer. Isso não comprova publicação na conta real do Notion.

### Navegador de teste

Edge real/CDP contra um servidor HTTP de teste: busca RSS, leitura de uma página no Rápido, pausa/retomada, interrupção, ausência de POST e execução de scripts/subrecursos da página, cache persistente vazio. O acesso loopback é liberado apenas por patch no teste; testes separados comprovam o bloqueio normal de loopback, rede privada, metadados e `file://`. O fluxo visual usa Chrome headless com backend real, Ollama falso, voz simulada e Edge headless para a pesquisa simulada.

### Pesquisa e IA locais reais

Comando: `.venv\Scripts\python.exe bench/study_agent_bench.py D:\Lumen\validacao-fase8-20261104`.

Ollama existente, `qwen3.5:4b`, esforço Rápido, consulta pública `Python programming language`, Edge **visível** `156.0.4314.58`, janela CDP em estado `normal`. Perfil em D: confirmado e removido ao terminar. Busca real retornou Python.org; página oficial lida, referência `[S1]` produzida, nota real criada em cofre temporário e relida, desfazer confirmado. **113,59 s** até a resposta; **113,61 s** com criação e desfazer. `real.json`, `edge-real.jpg`, `nota-real.md` guardam a prova. Nenhum token do Notion, publicação externa ou chamada ao Voice Studio.

Essa prova confirma o encadeamento e a correspondência da referência com a URL lida, **não a correção semântica integral da resposta**. O 4b acrescentou uma paráfrase inadequada do Zen of Python; a avaliação de qualidade permanece distinta dos testes de transporte e permissões. Tentativas de consulta anteriores também trouxeram resultados irrelevantes, e um endereço da OpenAI retornou HTTP 403. Não foram tratados como pesquisas bem-sucedidas.

## Limites e próxima ação

- A janela nativa do Lúmen pessoal não foi usada como ambiente de teste. Na retomada, havia `Lumen.exe --background` ativo; não foi encerrado. Após saída normal e reabertura pelo usuário, verificar `/imagem paisagem`, `/pdf revisao`, **Gerar PDF**, reabertura da conversa e os novos comandos da fase 8.
- Não houve publicação no Notion real. Se o usuário escolher fazê-la, usar a prévia e conferir página, blocos e bytes persistidos antes de declarar sucesso.
- Pesquisa é leitura guiada, sem login, cliques livres, formulários ou controles de outros aplicativos. RSS público pode mudar; sites podem impedir a leitura. Parar aguarda a fronteira de uma chamada bloqueante em andamento.
- Desfazer no Notion é conservador, mas não há transação atômica entre a leitura e o envio à lixeira; edição simultânea é um limite conhecido. No cofre, não são apagados anexos potencialmente usados em outras notas.
- Verificações humanas de voz da fase 6 continuam pendentes; escuta cega não revelada, oito passos não ativados. Ollama e Voice Studio pessoais não foram parados/reiniciados.
- Fase 9 não iniciada. Primeiro fechar `suite-final-2.log` (a interface `ui-final.log` já passou), corrigir qualquer reprovação e atualizar STATUS com os resultados finais. Depois, seguir a seção da fase 9 do plano, começando pela prática com rubrica ligada a `mastery`, sem ampliar o escopo.

## Continuidade

Novos arquivos desta fase: `lumen/study/apps.py`, `lumen/study/browser.py`, `tests/test_study_agent.py`, `bench/study_agent_bench.py` e este relatório. Alterações pontuais em `cdp`, `study/{writes,settings,tools,agent,registry,api,sources/web}`, `web/{study.js,study.css,study-settings.js}`, `tests/study_ui.py`, fixture em `tests/test_widget.py` e documentos de implementação. Arquivos compartilhados têm também mudanças paralelas.

Na integração final, correções pontuais também em `lumen/study/providers.py` e na fixture `tests/test_study_index.py`; preservado o restante da implementação paralela de nuvem.

Processos de teste são próprios: servidores falsos, Edge/Chrome de perfis temporários e Python das suítes. Nenhum servidor Ollama novo foi iniciado pela fase 8. Na conclusão, conferir os processos restantes e registrar o `git status` final na pasta de evidências; não encerrar processos pessoais nem restaurar o ZIP por cima deste checkout.
