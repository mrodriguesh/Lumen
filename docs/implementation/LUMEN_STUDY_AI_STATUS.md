# Lúmen Study AI: estado da implementação

Atualizado em 09/11/2026 (Conversa rápida). O plano aprovado está em `%USERPROFILE%\.claude\plans\fluttering-petting-meadow.md`. Arquitetura em `LUMEN_ADVANCED_INTELLIGENCE.md`, decisões em `LUMEN_STUDY_AI_DECISIONS.md` e auditoria em `LUMEN_CLAUDE_OBSIDIAN_AUDIT.md`.

## Pedido novo (15/11): modos de resposta × níveis de esforço — corrigido e verificado com o Ollama real (dados isolados)

- **Causa medida:** (1) o Máximo entendia o pedido no modelo rápido (`qwen3.5:4b`), respondia no maior (`qwen3.5:9b`) e voltava ao rápido nos extras da
  explicação, no título e na memória: na RTX 3060 os dois não ficam juntos, então cada troca recarregava do HD (antes: 71,8 s de carga numa resposta com
  o 4b principal e 84,0 s com o `qwen3:8b`; depois: 57,5 s e 43,2 s, uma carga só); (2) com modo E esforço escolhidos à mão no modo Livre, o roteador
  ainda chamava o modelo (~2,6 s no 4b quente, ~30 s a frio) sem nada a decidir nem a buscar.
- **Correção (D180, só `lumen/study/agent.py`):** o modelo da resposta (`_answer_model`, a mesma regra de antes) é resolvido assim que o esforço se sabe
  (escolhido, ou "máximo" pedido com todas as letras) e fixa `provider.fast` para a resposta inteira; Livre + modo + esforço escolhidos usa só a
  heurística. Equilibrado e Profundo seguem com o papel "rápido" para entender (sem mudança). Nada de política, provedor, tela ou ajuste mudou.
- **Provas:** `tests/test_study_routing_matrix.py` (novo: 5 modos × 5 esforços × 5 catálogos de papéis × Livre/Notas = 250 respostas, mais Máximo
  pedido por extenso, troca manual registrada e relida, refazer, cancelar no meio do Máximo, tempo-limite e modelo ausente/sem raciocínio/sem
  ferramentas); falha 99 vezes contra o código antigo. 253 testes das suítes de Estudos OK; `tests/study_ui.py` 33 verificações OK.
  Sondas reais e roteador: `D:\Lumen\modo-esforco-20261115\logs` (relatório na resposta da tarefa).
- **Não verificado:** a janela nativa e o `Lumen.exe` oficial (o aberto guarda o código antigo: sair pelo menu e abrir de novo), as notas pessoais
  (as sondas usaram o modo Livre em dados isolados) e as capturas de tela citadas no pedido (não vieram anexadas).
- **Restauração:** `D:\Lumen\restauracao\modo-esforco-20261115\orig` (46 arquivos, `SHA256SUMS.txt`). **Não use** `git reset`, `clean`, `stash` nem `checkout`.

## Pedido novo (09/11, 4): retirada completa do Gemini — implementada e testada; o executável oficial NÃO foi trocado

- **Decisão:** o Gemini saiu do Lúmen (chat, mídia em nuvem, chave, aceites, rotas, telas e o conector Gemini Notebook). Fica só a IA local (Ollama);
  Claude e OpenAI seguem bloqueados. O Google Drive da Proteção foi preservado (rotas `/api/drive*`).
- **Migração:** `settings.migrate()` (por conteúdo, idempotente, uma cópia `.bak`), mais a remoção da entrada `google-api-key` do cofre.
- **Relatório:** `docs/implementation/LUMEN_REMOCAO_GEMINI_20261109.md`. **Restauração:** `D:\Lumen\restauracao\remover-gemini-20261109`
  (`verificar.py --origem|--restaurar`). **Não use** `git reset`, `clean`, `stash` nem `checkout --`: `lumen/study/` e quase toda `lumen/web/` não estão no git.
- O pedido anterior (Gemini gratuito com aceites, abaixo) está **superado** e fica como histórico.

## Pedido novo (09/11, 3): Gemini gratuito + bloqueio de serviços pagos — implementado e testado com mocks; integração real NÃO validada

- **Conclusão:** não existe Gemini gratuito **sem cotas**; o Gemini vem desativado e só abre com três aceites (cotas, uso de dados, plano do projeto). Local (Ollama) intacto. Claude, OpenAI, imagem/vídeo em nuvem
  e busca hospedada estão **bloqueados no backend** (`lumen/study/policy.py`), inclusive por configuração antiga/forjada, alternativo automático e identificador arbitrário.
- **Provas:** `tests/test_free_policy.py` (50), `tests/test_cloud_providers.py` (18), `tests/gemini_ui.py` (7 verificações, Chrome headless, dados isolados) e a suíte completa (ver o relatório). Os testes de bloqueio afirmam que nenhuma requisição saiu.
- **Falta (só você):** cadastrar uma chave NOVA (a colada no chat foi tratada como exposta e não foi usada), decidir se aceita as cotas e o uso de dados do plano gratuito, confirmar o plano em aistudio.google.com/projects e fazer o primeiro teste real; avaliar a tela no Lúmen em uso.
- **Relatório:** `docs/implementation/LUMEN_GEMINI_GRATUITO_20261109.md`. **Restauração:** `D:\Lumen\restauracao\gemini-gratis-20261109` (`verificar.py --origem|--restaurar`). **Não use** `git reset`, `clean`, `stash` nem `checkout`.

## Pedido novo (09/11, 2): corrigir o corte da Conversa rápida na barra compacta — corrigido, verificado e instalado (Lumen.exe oficial trocado e conferido); falta só o seu uso com mouse/teclado reais

- **Causa comprovada:** o `Lumen.exe` em uso (04/11, SHA-256 `1b560e6b…`) não conhece `widget:panel:chat`, então a janela ficou em 304 × 252 e a página desenhou 420 × 620 (`.notch` em (−116, −368) na barra real). A página supunha o tamanho da janela. Relatório: `LUMEN_CONVERSA_RAPIDA_CORRECAO_20261109.md` (D135–D140).
- **O que mudou:** a conversa abre no 304 × 252 (a barra não cresce), ocupa a janela inteira (`100vw × 100vh`), cabeçalho "Conversa" + ⋯ + ‹, Livre | Notas, lista que rola, campo que cresce até ~1/3 e rola; menu ⋯ (nova, temporária, Cérebro, Ampliar 360 × 540). `WidgetForm.PanelFor`, `ChatWide`.
- **Provas:** `tests/chat_compact.py` (falha com o código antigo, passa com o novo), `chat_ui.py`, `widget_ui.py`, `DesktopChecks.cs` (medidas) e sonda UIA na barra real isolada; ver o relatório para números e capturas.
- **Executável:** `Lumen.exe` oficial agora é o candidato testado (SHA-256 `EFA29C81…93EDE1`), trocado com `scripts\instalar.ps1` (sem kill; só com o Lumen ocioso) e conferido na janela oficial: 304 × 252, 17 elementos, 0 fora. Suíte completa 982 OK; nativo OK; `chat_compact.py` 11 cenários OK (e falha com o código antigo).
- **Restauração:** `D:\Lumen\restauracao\conversa-rapida-correcao-20261109` (34 arquivos, inclui o `Lumen.exe` anterior). **Não use** `git reset`, `clean`, `stash` nem `checkout`.

## Pedido novo (09/11): Conversa rápida na barra flutuante — concluído tecnicamente; falta o seu uso com mouse/teclado reais e a avaliação visual

- **O que existe:** um painel de chat dentro da barra (ícone de balão entre Gravar e Ajustes, 420 × 620) com o MESMO agente, rotas e conversa do Cérebro: streaming, interromper, Livre/Notas de verdade (`skip_vault`, mesmas chaves do Cérebro), fontes reais com Abrir confirmado pelo servidor, copiar, nova conversa (e temporária), rascunho que sobrevive a trocar de painel/recolher/recarregar, "Abrir no Cérebro" na mesma conversa (sem reenviar), uma resposta por conversa em qualquer janela. Decisões D127–D134; relatório `LUMEN_CONVERSA_RAPIDA_20261109.md`; regras visuais na seção "Conversa rápida" de `docs/DESIGN.md`.
- **Provas de hoje (dados isolados):** `tests/chat_ui.py` **24 blocos OK** (servidor real, Ollama falso que transmite); `tests/test_quick_chat.py` **11 OK**; `widget_ui.py` OK; **nativo (WebView2 e janela reais, instância isolada) OK inteiro, incluindo 72 verificações novas** (cresce/recolhe sem salto nas quatro bordas, dentro da área útil, animação interrompida continua do tamanho atual, recolher durante a resposta não a cancela, Esc, mensagens ao `Lumen.exe` validadas); regressão do Cérebro `study_ui` (33), `call_ui` (10) e `estudar_ui` OK; **suíte completa 982 OK em 1208,8 s**. Evidências em `D:\Lumen\conversa-rapida-20261109\{logs,ui}`.
- **Herdado e corrigido só nos testes:** `widget_ui.py` e `DesktopChecks.cs` já falhavam antes da tarefa (7ª categoria de Ajustes; duplo sem `/api/protection`). Gravar deixou de ser o controle do meio da trilha (quatro controles; cinco com "Minha compreensão"): asserção atualizada.
- **Não verificado:** clique e digitação com mouse/teclado físicos, vários monitores com escalas diferentes (só a geometria, 800 casos), `ProcessFailed` real do WebView2, modelo real (Ollama falso), Notion e Obsidian reais, gravação real em paralelo, o `Lumen.exe` oficial (em uso, **não substituído**; candidato em `D:\Lumen\conversa-rapida-20261109\native\Lumen.Isolado.exe`) e o juízo estético. Sem voz/ditado, comandos `/`, anexos nem `/tela` na barra, de propósito.
- **Próxima ação exata:** (a troca do executável já foi feita, ver o pedido novo 09/11, 2) usar a conversa nas quatro bordas e avaliar o visual. Restauração: `D:\Lumen\restauracao\conversa-rapida-20261109\RESTAURAR.md` (241 arquivos). **Não use** `git reset`, `clean`, `stash` nem `checkout`.

## Pedido novo (08/11, 5): reorganização da aba Estudar — concluído tecnicamente; falta a sua avaliação visual no Lumen real

- **O que existe:** a aba Estudar tem três níveis, uma tela por vez: **Início → Objetivo → Atividade**. Quatro objetivos (Revisar, Praticar, Planejar, Visualizar) e as 12 funções, cada uma num único lugar a dois cliques do início; o seletor de nove opções, os quatro blocos empilhados e a lista corrida sumiram. As atividades são montadas uma vez e guardadas: rascunho, resultado, respostas do questionário, sessão de revisão e sessão do Treino falado sobrevivem a trocar de objetivo, de atividade e de aba. Erro ao lado do campo, "Tentar de novo", resultado lento vai por aviso com "Abrir", atalhos e microfone só na atividade visível, foco no título e de volta ao botão de origem. Decisões D121–D126; relatório `LUMEN_ESTUDAR_REORGANIZACAO_20261108.md`; regras visuais na seção "Estudar" de `docs/DESIGN.md`.
- **Medido (antes → depois, 1440×900, mesmos dados semeados):** aba vazia 1,28 → **0,63** tela; com dados 2,56 → **1,10** (520 px: 3,02 → 1,44); botões 42 → **14**; cards fixos 4 → **0**; campos visíveis no início 7 → **0**; rascunho sobrevive a trocar de aba: não → **sim**; contraste do texto do início ≥ 4,5 (mín. 5,68).
- **Provas desta tarefa (todas executadas agora, dados temporários):** `py -3.14 tests/estudar_ui.py` **16 blocos de verificação OK** no código final (`D:/Lumen/estudar-20261108/logs/estudar-ui-final.log`, capturas em `ui/depois-final/`); `py -3.14 tests/study_ui.py` **passou** no código final (`logs/study-ui-final-2.log`; uma rodada anterior, `logs/study-ui-final.log`, falhou no passo 11 "Pronúncias" por tempo de 8 s esperando o Voice Studio falso, sem relação com Estudar, e passou na repetição sem mudança de código); 141 testes direcionados OK (`test_ui_tokens`, `test_study_core/applied/explain/voice/catalog_eval`; saída só no terminal, sem log próprio, e os mesmos testes estão nas suítes completas abaixo); `node --check` OK. Suíte completa: ver a linha "Suíte completa" abaixo.
- **Suíte completa (`unittest discover -s tests -t .`):** **duas rodadas no código final, 971 testes cada, 970 OK e 1 falha diferente em cada uma, nenhuma ligada a Estudar** (`logs/suite-full-final.log`, 964 s; `logs/suite-full-final-2.log`, 1002 s). Rodada 1: `tests.test_protection.Protection.test_file_changes_during_copy_preserves_previous` (módulo de proteção herdado, não rastreado; falha 6 de 20 vezes **até isolado**: o teste só muta o arquivo se `background_yield` for chamado durante a cópia). Rodada 2: `tests.test_transcribe.SecondOpinion.test_flags_divergence_without_replacing_text` (passa 10 de 10 isolado; o teste não simula `gpu_free_gb` e devolve `False` quando a VRAM livre da RTX 3060, dividida com Ollama e Voice Studio, cai abaixo de 1,0 GB; hoje há 1,79 GB). Nenhum desses arquivos foi tocado por esta tarefa e o teste da rodada 1 passou na rodada 2 e vice-versa. **Não declaro a suíte "100% verde"**: os dois testes são intermitentes por ambiente/tempo e ficam como pendência fora do escopo.
- **Bugs achados e corrigidos:** rascunho, sessão e resultado perdidos ao clicar em Estudar (e `S.practicing` preso em `true`); revisão escondida capturando teclas; cenários e vozes do Treino falado buscados a cada render e ouvinte de `lumen-audio` acumulando; projeto do Plano de ação depois do botão; validação sem ligação com o campo; Plano de estudos e Plano de ação com o mesmo ícone; selo da aba dentro do nome da aba. Backend, rotas, contratos e dados **não mudaram** (conferido por hash contra a restauração, `logs/conferencia-restauracao-final.txt`: de código só `lumen/web/{study-learn.js, study.css, study.js, app.js}` e `tests/study_ui.py`, mais 5 documentos e 2 arquivos novos, `tests/estudar_ui.py` e o relatório; nenhum `.py` de `lumen/`).
- **Não verificado:** janela nativa WebView2 e executável oficial, microfone e voz reais (os testes usam Chrome headless, Ollama e Voice Studio falsos, microfone simulado), e o juízo estético (a largura de 880 px, o tom, o equilíbrio do início). Nada foi publicado nem commitado.
- **Próxima ação exata:** **Sair do Lúmen pelo menu e abrir de novo** (o aberto guarda o código antigo) e olhar: (1) o início com e sem revisão pendente, (2) criar um flashcard e voltar, (3) começar e abandonar uma revisão e voltar pelo início, (4) o Treino falado com a voz real. Restauração: `D:/Lumen/restauracao/estudar-20261108/RESTAURAR.md` (277 arquivos, conferida de novo em 09/11: 0 divergentes) e a implementação nova em `D:/Lumen/restauracao/estudar-20261108-implementacao-atual` e `...-final`. **Não use** `git reset`, `clean`, `stash` nem `checkout`.

## Pedido novo (08/11, 4): conversa por voz natural, contínua e ligada ao Livre/Notas — concluído tecnicamente; falta a sua escuta e o microfone real

- **O que existe:** a chamada de voz agora (1) isola cada turno (`call.Turn`: um turno cancelado nunca revive, D107), (2) usa o **mesmo Livre/Notas, fontes e perfil do chat escrito**, com uma fotografia por turno, troca no meio da chamada,
  comandos de voz ("ativar modo livre", "usar minhas notas", "usar só o Obsidian") e antecipada/busca antecipada invalidadas (D108, D109), (3) espera uma vez por frase inacabada, tem histerese no VAD e aceita falar por cima também durante "pensando" (D110, D111),
  (4) guarda o que foi ouvido e, à parte, o que o modelo escreveu (D112), (5) aquece a voz na preparação e ao passar o mouse no botão (D113), (6) mostra estados e etapas reais, reabre o microfone que some e reconecta o fluxo sem duplicar (D114),
  (7) tem interface nova (D115), texto próprio para a fala (D116), tamanhos de pedaço que evitam voz parada (D119). Relatório: `LUMEN_VOZ_CONVERSA_NATURAL_20261108.md`; roteiro com microfone real: `LUMEN_VOZ_TESTE_FINAL_20261108.md`.
- **Provas de hoje:** `tests/test_call_natural.py` (**55 testes novos**, incluindo o do bug dos turnos antigos, reproduzido antes da correção); suíte completa **971 OK em 1024,1 s** (`D:/Lumen/voz-conversa-20261108/logs/suite-full-2.log`; a rodada anterior, 965 OK em 992,4 s, foi antes da mesclagem de pausa);
  `tests/study_ui.py` **passou: 33 verificações, sem erro de página, CSP ou HTTP 5xx** (`logs/study-ui-4.log`, repetida depois da última mudança de interface; uma rodada anterior falhou no passo 16, perfil adulto, sem relação com a voz, e passou na seguinte); `tests/call_ui.py` **10 verificações** (estados, Livre/Notas sincronizado, 4 larguras, movimento reduzido, teclado, pílula);
  medições reais em tempo real (24 turnos em ~10 min, **antes × depois**), sondas de síntese/fim de fala e **interrupções e pausas no pipeline real** (voz→áudio parado p50 137 ms, máx 157 ms; 0 eventos do turno velho; pausa de 0,9 e 1,3 s = 1 pergunta no histórico): ver o relatório.
- **Resultado honesto:** o **1º som com conteúdo não mudou** (p50 3,6 s, p90 4,1 s desde o fim da fala): o piso é a síntese do 1º trecho (~1,6 s sozinha; 3,4 s com o modelo decodificando ao mesmo tempo). Mudou o que estava errado: turnos antigos vazavam, a chamada ignorava Livre/Notas, falar durante "pensando" era ignorado,
  o microfone podia sumir sem aviso, a barra de preparo era fictícia. Uma regressão minha (voz parada entre o 1º e o 2º trecho; resposta 70% mais longa) foi medida e corrigida (D119).
- **Bugs achados e corrigidos:** além dos acima, o recorte do tópico do Feynman falhava com o ponto final do Parakeet (1 caractere deslocado), a reconexão da tela chamava uma função inexistente, `audio_q.put(None)` podia travar uma thread, e o `bench/call_bench.py` apagava um diretório fixo na partida (agora cada execução usa um diretório novo).
- **Não verificado:** conversa com a sua voz e microfone real, eco acústico das suas caixas (Realtek) com o microfone USB, naturalidade percebida (inclui 8 × 12 passos), janela nativa WebView2 e o executável oficial. Nada foi publicado nem commitado. A configuração pessoal (voz Jhonny, 12 passos, silêncio normal, caixas de som) **não foi alterada**.
- **Próxima ação exata:** **Sair do Lúmen pelo menu e abrir de novo** (o aberto guarda o código antigo) e seguir `LUMEN_VOZ_TESTE_FINAL_20261108.md` (~8 minutos, duas vezes: caixas e fones). Restauração: `D:/Lumen/restauracao/voz-conversa-20261108/RESTAURAR.md`.

## Pedido novo (08/11, 3): /elegrama 3d e /holograma 3d no chat — concluído tecnicamente

- **O que existe:** o comando gera, na própria conversa, a visualização 3D com aparência de holograma que as aulas já usam (`visual3d`, na CPU):
  GIF animado de 960×540 (48 quadros, 4 s) com PNG de reserva, explicação curta, download e, em conversa salva, as ações de salvar no
  Obsidian e no Notion. A IA só devolve dados validados (nunca código); a legenda diz que é esquema e se há fontes (D100–D106). Relatório:
  `LUMEN_STUDY_AI_ELEGRAMA_3D_20261108.md`.
- **Provas de hoje:** testes novos 39 (34 de `test_study_holo`, 3 de rótulos, 1 do perfil adulto, 1 do banco novo); suíte completa **916 OK em 1251,5 s (`D:/Lumen/elegrama-3d-20261108/logs/suite-full-2.log`; a primeira rodada, com 915, passou em 1259,9 s antes da correção do banco)**; `tests/study_ui.py`
  **passou: 33 verificações, nenhum erro de página, CSP ou HTTP 5xx, backend sem erro registrado (`D:/Lumen/elegrama-3d-20261108/logs/ui-6.log`)** com o cenário 17 (quatro larguras, movimento reduzido, downloads, salvar no Obsidian); fluxo real pelo `agent.turn` com modelo de
  verdade (instância isolada, 11435): 7 pedidos reais com o qwen3.5:9b, 7/7 com GIF de 48 quadros distintos e reabertura, 14–59 s por pedido (`amostras/reais-final`). GIF com 48 quadros distintos conferido (existir não prova animar).
- **Bugs achados e corrigidos:** vazamento de teste preexistente (25 falhas na baseline em outra ordem), comparação com rótulos no lado errado,
  caracteres sem glifo viravam quadrado, OSError virava "Erro inesperado", `previous_profile` esquecia o perfil depois de um arquivo gerado,
  escolha ruim de família/modelo (4B), e uma corrida no primeiro acesso a um banco novo dos Estudos (HTTP 500 em `/api/study/state`, `db.connect`). Detalhes na seção 7 do relatório.
- **Próxima ação exata:** o usuário **Sair pelo menu e abrir o Lúmen de novo**, digitar `/elegrama 3d do sistema solar` e conferir na janela de
  verdade. Não verificado: WebView2 oficial, Notion real, publicação real. Restauração: `D:\Lumen\restauracao\elegrama-3d-20261108`.

## Pedido novo (08/11, 2): perfil adulto com modelo dedicado e troca automática — concluído tecnicamente

- **O que existe:** um perfil de IA local separado (modelo, instruções de estilo e temperatura próprios, ligado em Configurações →
  Perfil adulto) e a troca automática por contexto, decidida uma vez por resposta, no computador, antes de qualquer chamada que possa
  sair dele (`lumen/study/adult.py`, `agent._turn`; D92–D99). Escolha manual vence o automático (chip "Modelo da resposta" ou
  `/perfil`); desligado, só o principal responde. Voz e texto usam a mesma decisão. O principal não foi alterado.
- **Modelo:** `qwen3.5-heretic:9b` (Qwen3.5-9B Ultra Uncensored Heretic, Q4_K_M, Apache-2.0). No conjunto final: 9/10 pedidos
  adultos e de palavrão entregues, 3/6 explícitos, 1 recusa real; ferramentas 6/8, JSON 100%, roteador 12/12, sem invenção. Não
  atingiu o critério de 70% de explícito (3/6). Gemma 4 12B Heretic (ferramentas 1/8) e Gemma 4 E4B Heretic (2/6 explícitos)
  não foram adotados.
- **Roteamento (classificador real, conjunto final travado):** 0/90 falsos positivos e 0/50 falsos negativos; mediana 676 ms.
- **Provas de hoje:** testes novos 28 OK; relacionados 76 OK; `tests/study_ui.py` passou com o cenário novo; fluxo real pelo `agent.turn`
  25/25 (a 1ª rodada deu 19/23 por defeitos do instrumento, corrigidos); suíte completa **877 OK em 1021,96 s** (`D:/Lumen/perfil-adulto-20261108/logs/suite-full-2.log`; inclui o cache de falha do Ollama).
- **Correção junto:** o `qwen3-embedding` aparecia na lista de modelos de chat (a correção de 08/11 estava na rota errada); agora em
  `providers.status`, com teste de interface.
- **Próxima ação exata:** o usuário **Sair pelo menu e abrir o Lúmen de novo**, ligar o perfil em Configurações → Perfil adulto (ou
  rodar `aplicar-perfil-adulto.ps1 -Model "qwen3.5-heretic:9b"` com o Lúmen fechado) e testar. Não verificado: janela nativa/WebView2,
  microfone real, publicação real; o Heretic 9B ainda suaviza ou recusa parte dos pedidos explícitos. Relatório:
  `LUMEN_STUDY_AI_PERFIL_ADULTO_20261108.md`; restauração: `D:\Lumen\restauracao\perfil-adulto-20261108`.

## Pedido novo (08/11): IA local com menos recusas indevidas — concluído tecnicamente

- **Resultado:** o problema era do **aplicativo** (o prompt forçava "Nas suas fontes… nenhum documento encontrado" e `[S#]` mesmo sem notas, e o modelo não entregava a cena/diálogo/script pedido). Corrigido em `agent.py` (D87), `explain.py` e `providers.py` (D88). Conjunto reservado: pedidos legítimos não entregues 41% → 0% (4B) e 24% → 3% (9B); citações inventadas 68/11 → 0; ferramentas, JSON, roteador, português e tempo mantidos.
- **Modelos:** abliterados da huihui (9B e 4B) e Heretic foram pesquisados, instalados e medidos; **não adotados** (abliterados reprovam em honestidade; Heretic empata). Seleção de modelos inalterada. Sem treinamento (D89, D90).
- **Provas de hoje:** suíte completa **845 OK**; validação real pelo `agent.turn` **12/12**; relatório e números em `LUMEN_STUDY_AI_MODELO_LIVRE_20261107.md`; restauração em `D:\Lumen\restauracao\modelos-20261107`.
- **Próxima ação exata:** o usuário **Sair pelo menu e abrir o Lúmen de novo** (o aberto carrega o código antigo) e testa um pedido de cena e uma pergunta geral. Não verificado: executável oficial/WebView2, voz com microfone real, publicação real. Sem commit.

## Retomada atual — implementação e verificação técnica encerradas (07/11)

- **Implementado:** prática com rubrica/entregas/mastery; plano aplicado com revisões e Pomodoro; catálogo/skills; avaliação local e ajuste do Automático por contagens. Sem dependências novas, mudança de modelos pessoais ou build de C#.
- **Executado em 07/11:** interface final com 31 verificações em 152,614 s, quatro larguras, foco/movimento reduzido, zero erros de página/CSP/HTTP 5xx; 20 testes de integração em 3,971 s; vídeo de controle com transcrição/visão reais, persistência/reabertura/exclusão em 89,516 s. Capturas inspecionadas e hashes da interface estáveis. Nenhum teste segue em execução.
- **Resultados de 06/11 conferidos na retomada:** 841 testes da suíte completa, 102 direcionados, 32 de regressão e geração local real a partir de duas fontes em leitura. Avaliação CLI real funcionou e indicou um caso a revisar. Provas em `D:/Lumen/validacao-fase9-20261105` e no relatório da fase 9.
- **Suíte completa encerrada:** `suite-final2.log` / `suite2-result.json`: 841 testes em 1187,788 s, zero erros/falhas. Nenhum processo sobrevivente. Os hashes apontaram somente alteração paralela de `lumen/web/ui.css`; a interface final valida esse arquivo depois da correção do foco por teclado. A primeira suíte reprovada permanece documentada.
- **Corrigido no fechamento:** o carregamento inicial podia voltar para Início após entrar em Cérebro. Reprodução negativa em `ui-navigation-before3.log`, correção em `app.js` e prova positiva na rodada final. Foco por teclado e botão de salvar em 520 px também corrigidos. O `OperationalError` pontual da rodada anterior não reapareceu; a rodada final captura exceções da fixture, reprova 5xx e terminou com `backend.log` vazio. Não foi inventada uma causa para esse evento anterior.
- **Próxima ação exata:** usuário sair pelo menu e reabrir normalmente; seguir os quatro passos humanos/externos do checklist final. Não há nova fase nem requisito de implementação adicional identificado no escopo conciliado. Reabrir trabalho técnico se esses testes revelarem falha. Não repetir a suíte de 841 testes sem mudança relevante ou nova falha.
- **Mudanças desde a suíte:** fontes Python iguais, exceto inclusão paralela da rota estática `/cursor.js` em `server.py`; demais diferenças são HTML/CSS/JS e teste visual. Preservar o visual paralelo. Restauração antes da correção de navegação: `study-final-navigation-20261106`, app.js e study_ui.py, ZIP/manifesto conferidos.
- **Nativa e humano:** executável oficial abriu em perfis isolados, mas não expôs CDP; interface/reabertura nativa não comprovadas. A tentativa adicional de abertura GUI foi bloqueada pela revisão automática (`blocked by policy`), sem contorno. Voz real e publicação real no Notion permanecem dependências humanas/externas.
- **Histórico apenas conferido:** fase 8 terminou com 817 testes OK / 1183,345 s e 29 verificações visuais. Resultado anterior, não execução desta fase.
- **Restauração mais recente do checkout:** `D:/Lumen/restauracao/study-final-20261106`, 342 arquivos / 49.185.894 bytes; manifesto e ZIP conferidos. SHA-256 `5625cfef7352f83ec47f3d7530588d24f6c848e1c136be5295bb65973582781f`. Suplemento antes de corrigir foco: `study-final-ui-20261106`, ui.css e study_ui.py, íntegro. Preservadas as restaurações de 05/11 e 06/11 e todo trabalho paralelo.
- **Referências:** `LUMEN_STUDY_AI_PHASE9_20261105.md`, decisões D80–D86 e `LUMEN_STUDY_AI_FINAL_CHECKLIST_20261106.md`. Sem commit, push, limpeza ampla ou alteração de memórias globais. O plano externo foi lido em 06/11; em 07/11 seu caminho já não existia, portanto a retomada usou a conciliação registrada e os requisitos/decisões do projeto.

## Pronto e testado

| Parte | Prova |
|---|---|
| Aba Estudos no menu lateral e nos destinos do Ctrl+K; cabeçalho numa linha, com o estado real da IA e das fontes num painel sob pedido | `tests/study_ui.py` (passo 1) |
| Redesenho minimalista: histórico e fontes recolhíveis (por cima em janela estreita, Esc fecha), resposta sem caixa, ações agrupadas em "Mais opções", informações da resposta | `tests/study_ui.py` (passos 4 e 9) |
| Conectores Obsidian (disco), Notion (API), pastas autorizadas e web (SSRF) | `test_study_index`, `test_study_core.Security` |
| Índice incremental com FTS5 e vetores, e trabalhador em segundo plano | `test_study_index` |
| Busca híbrida com motivo e relevância reais, mesmo conteúdo e conexões | `test_lexical_semantic_and_hybrid`, `study_ui` (passo 3) |
| Conversa com streaming, citações conferidas e painel de fontes | `test_answer_streams_*`, `study_ui` (passo 4) |
| Claude pelo SDK oficial, com guarda de envio externo, ferramentas, cache e registro sem conteúdo | `test_study_core.Claude` (SDK real contra servidor SSE falso) |
| Ferramentas com níveis de permissão, limites e injeção de prompt | `test_tools_*`, `test_permissions_limit_tools` |
| Conversas: histórico, busca, fixar, arquivar, exportar, apagar uma, várias ou todas; conversa temporária | `Conversations.*`, `test_temporary_*`, `study_ui` (passo 5) |
| Projetos com escopo de memória e de fontes | `test_projects_scope_memory_and_sources` |
| Memória: categorias, consolidação, sugestões, seleção automática, importação do Claude Code, limpar | `Memory.*`, `study_ui` (passo 8) |
| Estudar: flashcards SM-2, questionário, plano, mapa e lacunas | `test_learn_*`, `study_ui` (passo 7) |
| Gravação com prévia no Obsidian e no Notion | `Writes.*`, `study_ui` (passo 6) |
| Configurações da IA (10 seções) e Seus dados no Lúmen | `study_ui` (passos 8 e 9), `test_data_*` |
| Modelo Automático medido neste PC (`qwen3.5:4b`), um contexto por modelo (32k no `qwen3.5`, D24), citações em qualquer formato e regra de ferramentas | `test_study_core.Agent`, `study_ui` (passo 8), `LUMEN_STUDY_AI_MODELS.md` |
| Medidor de contexto com o uso medido, compactação não destrutiva (automática, `/compact`, botão e Ctrl+Shift+K), mensagens fixadas, menu `/` com as skills do cofre e `/clear` com Desfazer | `test_study_core.Context`, `Claude.test_compacted_claude_conversation_sends_summary_and_text_only`, `study_ui` (passo 7b) |
| Níveis de esforço (Rápido, Equilibrado, Profundo, Máximo com revisão) e Função inteligente (regras, depois o modelo rápido; chip "Automático · modo · esforço" com o motivo; `/esforco`; trocas registradas) | `test_study_core.Effort`, `ROUTER_RULES`, `study_ui` (passo 7c), `bench/study_models_bench.py router` |
| Larguras de 1100, 760 e 520 px (mínimo da janela), nas 4 abas e com os painéis abertos, sem erro de CSP | `study_ui` (passo 9) |
| Conversa por voz em tempo real nos Estudos: orbe animado por estado, legenda ao vivo, cartões reais do chat, interrupção, eco cancelado (`pyaec` + barreira), 18 ajustes validados e pílula flutuante em 1440, 1100, 760 e 520 px | `test_study_call` (10), `study_ui` (passo 12), `bench/call_bench.py` |

## Verificado com dados reais (só leitura, banco temporário)

- **Cofre real:** 67 notas indexadas em 0,2 s, sem erros. A cópia do Notion (487 notas), a `.claude` e os modelos ficaram de fora, e o cofre não foi alterado.
- **Embeddings reais:** `qwen3-embedding:0.6b` foi baixado (com autorização). As buscas no cofre real trouxeram notas pertinentes pela busca híbrida.
- **Resposta real com o `qwen3:8b`:** 7 citações, todas válidas, nenhuma inventada. Levou cerca de 2 minutos.
- **Notion real:** conexão confirmada; 477 páginas depois de tirar o espelho do Obsidian, o que bate com as 479 da captura do backup. Três páginas reais foram lidas e convertidas. O teste foi só de leitura e leve, para não pesar no limite que o backup usa.

## Depende de configuração externa

- **Claude real:** precisa da chave de API do usuário, do envio externo ligado e da escolha do modelo pela lista da conta. O código está testado contra um servidor falso; ainda não falou com a Anthropic de verdade.
- **Primeira sincronização completa do Notion pelo app:** feita pelo usuário. Em 31/10, o índice real tinha 467 páginas do Notion e 67 notas do Obsidian, com 2.095 trechos com vetor (conferido só lendo o banco).
- **Gravação real no cofre e no Notion:** só pela tela, com a confirmação do usuário.
- **Lúmen aberto:** o backend novo só carrega depois de Sair pelo menu e abrir de novo. A janela nativa (WebView2) não foi testada nesta sessão.

## Pendências conhecidas

Detalhadas em `DECISIONS.md` → Pendente:
- reordenar com a IA ("rerank");
- seleção automática de provedor por tarefa;
- plugin Local REST API do Obsidian.

## Study AI 2.0 — implementação pronta, validação humana/externa pendente

Pedido em `PROMPT_LUMEN_STUDY_AI_V2.md`. O plano aprovado (31/10) está em `%USERPROFILE%\.claude\plans\fluttering-petting-meadow.md`, e as escolhas do usuário estão em D20 a D22.

| Fase | Conteúdo | Estado |
|---|---|---|
| 1 | Mapa de conhecimento (tetos, repetições, nova tentativa) e auxiliar CDP (capa, mapa mental, gráficos) | **Pronta** (31/10): testes, reprodução real em 23,5 s e os 3 testes do Edge passam. Em 01/11 o Edge parou de abrir pelo terminal de administrador e foi corrigido (`--do-not-de-elevate`, D19) |
| 2 | Modelos medidos neste PC e ajuste do Ollama | **Pronta** (01/11): `LUMEN_STUDY_AI_MODELS.md`. O Automático usa o `qwen3.5:4b` (D23), com um contexto só por modelo (D24; 16k na fase 2, 32k no `qwen3.5` desde a fase 3), citações normalizadas (D26) e regra de ferramentas (D27). O Ollama ficou sem mudança (D25) |
| 3 | Contexto e compactação, registro único, menu `/`, skills, esforço e Automático | **Pronta** (01/11): medidor, compactação não destrutiva, `/clear`, `/context`, registro e menu `/` (D28 a D30, D24 revista); quatro níveis de esforço (D31) e Função inteligente (D32). Medido: roteador 12/12 e 14/14; uma resposta real por nível, de 19 s (Equilibrado) a 139 s (Máximo, com a carga do 9b) |
| 4 | Anexos, imagens do cofre e do Notion, `/tela` | **Pronta** (01/11): anexos de qualquer tipo com o tipo conferido pelos bytes (D33 a D35), imagens das notas como texto pesquisável (D37), `/tela` só na memória (D36), visão com 32k nos Estudos (D38); `glm-ocr` com licença confirmada e não instalado (D39). Medido: print em 4,0 s, PDF de 20 páginas em 0,4 s, PDF escaneado de 2 páginas em 32,3 s, imagens de nota em 3,5 s cada, resposta com o anexo citado em 12,3 s |
| 5 | Explicação avançada, diagrama interativo, mapas mentais no chat e modelo do estudante | **Pronta** (01/11): explicação em camadas por esforço, com diagrama e checagem a partir do Equilibrado, flashcards no Profundo e resumo e revisão no Máximo (D40); diagrama 2D interativo com a spec do holograma (D41); modelo do estudante em `mastery` (D42); `/mapa-mental` (D43). Medido no cofre real: Rápido 21 s, Equilibrado 28 s, Profundo 35 s, Máximo 126 s (com a carga do 9b); os extras levam de 8 a 10 s (33 s no Máximo); mapa mental em 12 s e PNG em 2,2 s |
| 6 | Voz, revisão em áudio, "ver na aula", Treino falado, Feynman e **conversa por voz em tempo real** | **Pronta no código, testada e medida** (02/11, partes 1, 2 e 3); **aguarda a escuta cega do 1º pedaço da chamada e os testes rápidos na janela real do estudante**. O motor é o **Voice Studio** dele, com a voz do Jhonny (D46 a D48, D60). Parte 1: voz no chat, resumo e revisão em áudio, player com capítulos, Feynman, tour narrado e "ver na aula" (D49 a D52). Parte 2: backend sem janela, modelos e motores no Lúmen, qualidade por uso, painel da máquina, pronúncias, vozes por descrição, **Treino falado** e revisão a duas vozes (D53 a D59). **Parte 3:** chamada de voz em tempo real (`call.py`, `study-call.js`, D61 a D65), com orbe, legenda e cartões ao vivo, Parakeet CPU int8 (270,7 ms), resposta antecipada (−725,5 ms), som de "entendi" (42,3 ms), saída WASAPI no Python (11,3 ms; parar em 53,9 ms), `pyaec` + barreira (0/20 disparos falsos) e 24 turnos reais em 10 min sem crescer VRAM nem RAM |
| 7 | PDFs tematizados e `/imagem` (com `image_dir` no D:) | **Pronta no código, testada e medida (04/11)**; aguarda verificação na janela nativa e envio real confirmado pelo usuário. D66–D73. Migração conferida, comandos, nove tipos de PDF, prévia de arquivos e testes novos. Evidências e limites em `LUMEN_STUDY_AI_PHASE7_20261104.md`. |
| 8 | Agente: criar/desfazer, aplicativos e pesquisa guiada | **Implementada e verificada tecnicamente.** Resultado histórico reconciliado em 06/11: 817 testes OK e 29 verificações de interface. Notion real de escrita e janela nativa continuam sem comprovação. Ver relatório da fase 8. |
| 9 | Prática com correção, Plano de ação, catálogo e avaliação | **Implementada e verificada tecnicamente em ambiente isolado (07/11).** 841 testes completos em 06/11; interface final 31/31 e integração 20/20 em 07/11; geração local real e persistência. Validação nativa/humana e publicação externa continuam pendentes. Ver relatório e checklist final. |

**Fase 6, feita em 02/11** (pedido em `PROMPT_LUMEN_VOZ_VOICE_STUDIO.md`; D45 a D52)

- **Motor:** o Voice Studio do estudante (`lumen/voicestudio.py`), só por HTTP e WebSocket no loopback; voz padrão o perfil `1faf41ee` (Jhonny); reserva Chatterbox pt-br, sempre avisando qual voz fala. Nenhuma rota de escrita do Voice Studio é chamada (o falso dos testes registra tudo).
- **Onde está:** `lumen/study/listen.py` (quem fala, a fala do chat, apertar para falar, os áudios longos pela fila e as rotas `/api/study/voice/*`), `lumen/web/voice.js` (WebAudio, barra de fala, player, Integrações → Voice Studio), `study-settings.js` (Configurações → Voz), `study-learn.js` (revisão em áudio e Feynman), `study-diagram.js` (tour narrado), `explain.feynman`.
- **Prova:** `tests/test_study_voice.py` (18) e o passo 10 de `tests/study_ui.py`, sem erro de CSP: Integrações → Voice Studio em 1440, 1100, 760 e 520 px; Configurações → Voz em 1440, 760 e 520; o player em 1440 e 520; a barra de fala, o tour narrado, o apertar para falar e o Feynman em 1440. A barra de espaço, o botão de áudio da Biblioteca e o "Ver na aula" não entraram no passo (o "Ver na aula" tem teste unitário). Real, com banco temporário: uma resposta do `qwen3.5:4b` lida pelo Jhonny e o resumo em áudio de uma aula de curso (6 capítulos, 2 min 17 s em 76,5 s, com a conferência ligada). Medidas em `LUMEN_STUDY_AI_MODELS.md` → Voz.

**Fase 6, parte 2, feita em 02/11** (pedido em `PROMPT_LUMEN_VOICE_STUDIO_V2.md`; D53 a D59)

- **Onde está:** `lumen/voicestudio.py` (o backend sem janela `BACKEND`, `health()`, as escritas só por `write()`, catálogo de modelos e motores, pronúncias, vozes por descrição), `lumen/study/listen.py` (pré-aquecer, passos por uso, cache de frases, ritmo de 2 frases à frente, VRAM, revisão a duas vozes, `warm`), `lumen/study/voice_admin.py` (modelos, mover a pasta, "Esta máquina", pronúncias, vozes por descrição), `lumen/study/practice.py` (Treino falado), `lumen/web/voice.js` (Integrações → Voice Studio), `study-settings.js` (Configurações → Voz), `study-learn.js` (Treino falado), `study.js` (pré-aquecer ao abrir e na resposta).
- **Prova:** `tests/test_study_voice.py` (50 testes, 18 da parte 1), com o backend falso rodando como processo de verdade (sem janela, pipe, subida lenta com o vigia de uso parado ligado, falha, porta de outro programa, trava, uso parado com e sem o app, app abrindo, versão nova com arquivos de verdade); a conferência independente (subagente Sonnet) achou 9 problemas médios ou graves, todos corrigidos e testados (CHANGELOG); o passo 11 de `tests/study_ui.py` (Treino falado, Modelos de voz, Esta máquina, Criar voz para personagem e Pronúncias em 1440, 1100, 760 e 520 px), que prova que só os dois cliques do teste escreveram no Voice Studio. Medidas reais (só fala, no app aberto): `LUMEN_STUDY_AI_MODELS.md` → Voz, parte 2.
- **Real, com o Voice Studio fechado pelo estudante** (script no terminal, `LUMEN_DATA` temporário, pelo `listen.live`): o backend subiu sem nenhuma janela visível, falou 4 frases e desligou em 0,8 s fechando o pipe, sem `python.exe` restante. **1º som a frio: 74,1 s (arquivos frios) e 40,9 s (2ª subida)**, quase tudo na carga do modelo dentro do Voice Studio; a meta de 25 s não foi atingida (MODELS → Voz, parte 2). O `offload-after-generation` não liberou VRAM na rota de fala.
- **Não verificado nesta sessão:** abrir o app do Voice Studio com o backend do Lúmen rodando e fechar o Lúmen com o app aberto (o estudante tinha fechado o app; o Lúmen não o abre sem ele pedir), o Lúmen do estudante (o aberto ainda roda o código antigo), o microfone real no Treino falado e a janela nativa (WebView2). A dublagem (item opcional) não foi feita.

**Fase 6, parte 3, feita em 02/11** (pedido em `PROMPT_ARGON_CHAMADA_DE_VOZ.md`; D61 a D65)

- **Onde está:** `lumen/study/call.py` (máquina de estados, VAD Silero ONNX, resposta antecipada com `_commit_gate`, transcrição na memória, saída pelo Python, `EchoGuard` com `pyaec` + barreira, comandos rápidos sem IA, quiz/revisão/Feynman/domínio/prévia por voz e rotas `/api/study/call*`), `lumen/loopback.py` (`speaker()` com `flush()` e `CoInitializeEx` por thread), `lumen/study/settings.py` (18 chaves `call_*`), `lumen/study/agent.py` (`CALL_SYSTEM` e omissão seletiva de esquemas JSON na chamada), `lumen/web/study-call.js` e `study.css` (orbe, legenda, cartões, controles, ponto vermelho `"Microfone aberto"` e pílula flutuante), `lumen/web/study-settings.js` (seção `"Conversa por voz"`), `lumen/web/study.js` e `app.js` (botão ao lado da caixa e destino no Ctrl+K).
- **Prova:** `tests/test_study_call.py` (10 testes unitários), `tests/test_ui_tokens.py` (6), passo 12 de `tests/study_ui.py` (27 verificações totais nas 4 larguras — 1440, 1100, 760 e 520 px — e `prefers-reduced-motion`, sem erro de CSP nem escrita indevida no Voice Studio), suíte inteira (`750` testes) e conferência independente por subagente com contexto novo (2 achados — trava `_ASR_LOCK` no pré-aquecimento e reconexão automática do stream de eventos — corrigidos).
- **Real, com `LUMEN_DATA` temporário, Ollama e Voice Studio do estudante** (`bench/call_bench.py`, `D:\Lumen\voz\amostras-chamada\call_bench.json`; tabelas completas em `LUMEN_STUDY_AI_MODELS.md` → Conversa por voz): som de "entendi" em **42,3 ms** (meta ≤ 300 ms); Parakeet CPU int8 em **270,7 ms** (p90 342,9 ms, 2,65% de erro, +0 MB de VRAM); saída WASAPI no Python em **11,3 ms** e interrupção em **53,9 ms** (meta ≤ 150 ms); eco com `pyaec` + barreira em **0/20 disparos falsos** e **20/20 interrupções reais**; resposta antecipada economizando **725,5 ms** na mediana em 700 ms; 1º som da resposta em **3,41 s** (conversa curta) a **3,73 s** (mediana de 20 turnos) com 12 passos — ou **3,13 s** (p90 3,27 s) com 8 passos no 1º pedaço — devido ao piso físico de síntese do OmniVoice na RTX 3060 compartilhada com o `qwen3.5:4b`; chamada contínua de **10 minutos (24 turnos, 0 erros)** com VRAM em −200 MB e RSS em +2,5 MB.
- **Não verificado nesta sessão:** o microfone real do estudante (não gravado sem pedido; testado com falas WAV reais do Voice Studio) e a janela nativa WebView2 do Lúmen aberto (que guarda o código antigo até Sair pelo menu e abrir de novo).

**Próximo passo**

1. **Implementação e verificação técnica fechadas:** suíte, interface final, medição e checklist conciliados. Executar somente os testes humanos/externos listados abaixo; não repetir etapas já comprovadas sem mudança ou falha.
2. **Não iniciar nova fase.** A implementação aprovada está presente. Reconciliar as evidências e separar testes humanos/externos no checklist final; não reimplementar prática, catálogo ou Treino falado.
3. **Janela nativa pendente:** após o usuário sair normalmente e reabrir, verificar `/imagem paisagem`, `/pdf revisao`, **Gerar PDF**, reabertura da conversa e `/nota`, `/pagina`, `/web`, `/abrir`. O Lúmen ativo não foi encerrado nem recompilado por esta fase. A prova da fase 7 nesta sessão é isolada; 764/28 continuam sendo números históricos.
4. Notion: criação/desfazer e arquivos comprovados com serviço falso; nenhuma publicação na conta real. Em envio real escolhido pelo usuário, usar prévia e reler blocos/arquivo persistidos.
5. Fase 6 mantém os testes humanos de microfone, interrupção por fala, fone/caixa, mapa mental e abrir/fechar Voice Studio. Escuta cega não revelada; oito passos não ativados. Não bloqueiam a fase 9.
6. `image_dir` já aponta para `D:/Lumen/imagem`; origem no C: preservada. Não repetir a migração. Preservar mudanças paralelas de visual, launcher, executável, modo livre e provedores. Restaurações verificadas da fase 8 em `D:/Lumen/restauracao/study-fase8-20261104` e `study-fase8-20261105`.
7. Limpeza histórica da fase 7 continua bloqueada por revisão automática; lista em `D:/Lumen/validacao-fase7-20261104/limpeza-pendente.json`. Não confundir com temporários desta fase nem apagar a origem das imagens.

**Pendências da fase 6** (não bloqueiam):
- **Atraso físico de síntese na chamada (parte 3):** com `qwen3.5:4b` e OmniVoice dividindo a RTX 3060, o 1º som fica em 3,41 s a 3,73 s em 12 passos (3,13 s com 8 passos no 1º pedaço, à espera da escuta cega); o som de `"entendi"` sai em 42,3 ms e `"Preencher a espera"` (`call_filler`) cobre turnos mais longos aos 1,9 s.
- **Legenda parcial periódica em mãos livres (parte 3):** desligada porque disputava a trava do Parakeet ONNX na CPU e somava +115,8 ms na transcrição final (D62); o texto transcrito entra logo ao fechar o silêncio (ou já pronto pela resposta antecipada).
- **Treino falado:** feito na parte 2 (D58); testado com a IA e o microfone simulados.
- **Efeitos de voz e dublagem:** o `/v1/audio/speech` não aceita preset de efeito (não implementado); a dublagem era opcional e ficou de fora.
- **Fechar o Lúmen com o app do Voice Studio conectado ao backend dele:** o app mostra que o backend parou e pede reinício (comportamento do app, D53).
- **Instalar um motor pelo Lúmen:** começa a instalação no Voice Studio, mas o progresso só aparece no app.
- **`VoiceStudio.exe` na bandeja:** se o app ficar na bandeja depois de fechado, conta como aberto, e o desligamento por uso parado espera (a conferir no teste a frio).
- **Áudio no Notion:** o roteiro vai como texto; enviar o `.m4a` (upload de arquivo e bloco de áudio) ficou para depois, sempre pela prévia (D11).
- **"Ver na aula" nas fontes do chat:** só nos capítulos do resumo em áudio, que têm o tempo real do tópico. Nas fontes do chat dependeria de ligar cada nota do cofre à aula de origem.
- **Arquivo do PC no "ver na aula":** o player do Windows não aceita começar num tempo; a tela diz para onde pular.
- **Microfone real:** o "apertar para falar" foi testado com o microfone simulado (testar com o real gravaria o microfone do estudante sem ele pedir). A transcrição é a das aulas, já testada.
- **Janela nativa (WebView2):** a voz foi testada no Chrome sem janela. O Lúmen aberto guarda o código antigo: é preciso Sair pelo menu e abrir de novo.
- **A fala ao vivo não leva semente** (o `/ws/tts` não aceita): a voz pode variar um pouco entre frases; nos áudios longos a semente vale.
- **Ollama e voz juntos** cabem com pouca folga (pico de 11,25 GB de 12, com os programas abertos); se a placa encher, a fala do chat pode falhar enquanto o modelo de resposta estiver carregado.

**Pendências da fase 5** (não bloqueiam):
- **Citações:** na segunda rodada real, o Equilibrado e o Profundo usaram as notas sem escrever `[S#]`. Na primeira, os quatro níveis citaram. É o limite do 4b sem raciocínio (D27, D31), e o rodapé avisa "nenhuma citada".
- **O 4b nem sempre segue o "não escreva":** ainda fecha o Equilibrado com "Próximos passos" e, no Profundo, às vezes desenha um "diagrama" em texto, além do diagrama de verdade.
- **Extras no Máximo:** levam cerca de 33 s, porque o 4b volta à memória da placa depois do 9b.
- **3D girável na família "estrutura":** fora, como decidido em D41.
- **Imagem do mapa mental dentro da nota ou da página:** resolvida na fase 8 (D79); PNG renderizado na confirmação e conferido no destino falso. Janela nativa/envio real continuam pendentes.
- **A checagem não guarda a resposta dada:** reabrir a conversa mostra a pergunta de novo, sem a resposta.
- **Mapa mental ao reabrir a conversa:** volta como texto, com o link para Estudar, onde abre o diagrama. O diagrama da explicação volta junto, porque fica na meta da resposta.
- **"Pergunta rápida" quando falta o ponto de partida** (V2, 9.1): não foi feita. O ponto de partida vem só do modelo do estudante e das notas.
- **Janela nativa (WebView2):** o diagrama, a checagem e o mapa mental foram testados no Chrome sem janela.

**Pendências da fase 4** (não bloqueiam):
- **Janela nativa (WebView2):** colar um print com Ctrl+V, arrastar um arquivo e o `/tela` com o Lúmen na frente foram testados no Chrome sem janela e com a captura simulada. A captura real da janela de trás foi medida pelo terminal (0,53 s), mas não de dentro do Lúmen aberto.
- **Vídeo anexado:** medido em 07/11 com clipe de controle sintético de 6,393 s, `large-v3-turbo` e `qwen3.5:4b` reais. Texto falado e um quadro legíveis; persistência, reabertura e exclusão aprovadas. Resultado em `video-real-20261107/report.json`. Não é validação de vídeo pessoal longo.
- **Imagens das notas no cofre real:** a leitura foi medida numa nota (4 imagens); a primeira sincronização do cofre inteiro com as imagens ligadas ainda não rodou no app aberto (só 5 notas embutem imagens hoje).
- **Citação das imagens:** no Equilibrado, o modelo usou o texto das imagens sem escrever `[S1]` (D27, D31).
- **`pptx`:** os slides seguem o número do arquivo, que quase sempre é a ordem da apresentação (a ordem exata está em `presentation.xml`).
- **Apagar durante a leitura de um áudio ou vídeo:** o Windows não deixa apagar o arquivo aberto pela transcrição; a pasta sai no próximo início do Lúmen (`attachments.sweep`).
- **Imagens das notas que saem do índice:** a cópia em `MEDIA/imagens` e a linha da fila ficam até "Documentos indexados" ser apagado em Seus dados.
- **`/tela` não espera a aula** em processamento: é um pedido do estudante e leva cerca de 4 s na placa.

**Pendências da fase 3** (não bloqueiam):
- **Ctrl+Shift+K:** testado no Chromium sem janela, mas não na janela nativa (WebView2).
- **Skills do usuário:** criação, edição, ativação e teste pelas Configurações concluídos na fase 9. A autonomia segue D74: sem pedido explícito de criação, a ferramenta prepara uma prévia.
- **Rápido e Equilibrado sem raciocínio:** quando as notas não cobrem o assunto, respondem do conhecimento geral sem buscar de novo (D27, D31). O rodapé avisa "nenhuma citada".
- **O roteador ainda não decide** visão, tela, imagem, PDF, voz, página ou aplicativo: cada um entra junto com a sua função (D32). Na fase 4, anexo e `/tela` são escolhas explícitas do estudante e não passam pelo roteador.
- **Reranker:** fica para o conjunto de avaliação (fase 9).

**Suíte inteira (02/11, fim da fase 6, parte 2):** 740 testes, todos passando (14 min), com `-t .`; o `config.json` real não mudou. `tests/study_ui.py` passa inteiro, com o passo 11. Numa das rodadas do `study_ui`, `/api/study/state` deu um `OperationalError` do SQLite uma vez (o servidor seguiu e a rodada seguinte não repetiu); a rota não usa nada da voz, e o mais provável é disputa com a 1ª sincronização do índice. Se voltar, olhar `index.start()` e `attachments.sweep()` em `api.state`. Na parte 1: 708 testes. `tests/study_ui.py` passa inteiro, com o passo 10 (voz). Na fase 5: 690 testes, 12 min. `tests/study_ui.py` também passa inteiro, com o passo 7e (diagrama, checagem e mapa mental em 520 px). Rodar `test_study_explain` antes de `test_study_core` já deixou uma conversa temporária vazar entre os dois; hoje a base dos testes da fase 5 a tira. Na fase 3, `test_protection.Protection.test_file_changes_during_copy_preserves_previous` falhou uma vez com a máquina carregada e passou 5 de 5 sozinho; nas rodadas das fases 4 e 5, passou. Se voltar a falhar, olhe a ordem entre o hash e a cópia em `protection.py` (`background_yield` roda nas duas).

**Atenção nos scripts:**
- com `LUMEN_DATA`, os dados ficam em `<LUMEN_DATA>\Lumen\`, e a mídia dos Estudos em `<LUMEN_DATA>\Lumen\study\media` (sem ele, em `D:\Lumen\estudos`);
- `tests/study_ui.py` roda com `py -3.14`; o servidor dele importa `tests`, que troca o `LUMEN_DATA` por outra pasta temporária;
- o terminal do Claude Code é administrador: todo Edge aberto pelo Python precisa de `--do-not-de-elevate` (D19).
