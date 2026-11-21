# Lúmen Glass 2026 — manifesto das referências

Fonte: `%USERPROFILE%\Downloads\Lumen Glass 2026` (38 PNG; a pasta não foi alterada). Todas as 38 imagens foram abertas e observadas em 11/11/2026
(folhas de leitura em `D:\Lumen\glass-20261111\folhas\`, índice em `indice.tsv`). Conferido de novo em 12/11/2026: as 9 pastas existem, com as mesmas 38 imagens
(nenhuma nova). `07-Integracoes` e `09-Componentes` estão **vazias**; a referência de Integrações/Voice Studio está em `05-Configuracoes-IA` (R24) e os
componentes compartilhados foram extraídos das próprias telas.

**Shell.** R01, R04, R06, R07 e R24 usam o shell Glass (barra lateral larga, Pomodoro em cartão). As demais usam o shell antigo (rail estreito, pílula do
Pomodoro, "folha"). Pela ordem de prioridade do pedido (sistema visual consolidado), vale o shell Glass com o **conteúdo** de cada referência.

Status: **I** implementado · **P** parcial · **H** herda o design system (não ajustada uma a uma) · **N** não iniciado.
Validação: **V** comparada com captura renderizada (Chrome sem GPU) · **Vn** também na janela real do `Lumen.exe` · **—** não comparada.

| # | Arquivo (pasta) | Interface real | Onde no código | Estado | Obrigatório na referência | Status | Val. |
|---|---|---|---|---|---|---|---|
| R01 | 01-Inicio/Painel Lúmen_ Jornada de Aprendizado | Início | `#view-home`, `glass.js` (hero, journey) | aula em andamento | hero "Comece uma nova aula", Sistema, Continue, Ações rápidas, jornada, Revisões, cometa | I | Vn |
| R02 | 02-Nova-Aula/Análise concluída | Nova aula › Análise | `#analysis`, `#review` | análise pronta | título central, cartões da análise, coluna "Salvar" | **I** (14/11: coluna "Salvar" com 30% da largura, destinos sem moldura dupla e ícone no botão; os cartões da análise já equivaliam) | V |
| R03 | 02-Nova-Aula/Interface Lúmen em modo escuro | Nova aula › Minha compreensão | `#understand` | vazio | etapas em linha, título central, papel largo, barra de ação | I | V |
| R04 | 02-Nova-Aula/Nova Aula em Fluxo | Nova aula › Fonte | `#compose`, `.g-src`, `.g-flow` | recuperação | fontes, estúdio, fluxo, coluna lateral | I (3 fontes reais; sem "Outro link") | Vn |
| R05 | 02-Nova-Aula/Materiais Processados | Nova aula › Salvar (resultado) | `#run`, `#result`, `glass.js` (`result`), `app.js` (`obsidianParts`, `visualFacts`) | concluído, falha num destino, um destino só, visualização que falhou | título com ladrilho, cartões Notion/Obsidian, visualização 3D, ações em duas fileiras | **I** (12/11; ordem do rodapé = ordem do DOM: Notion, compreensão, Obsidian) | V |
| R06 | 03-Biblioteca/Biblioteca em Neon Azul | Biblioteca | `#view-library`, `glass.js` (library) | lista | números, vistas, estrutura, lista | I (sem Tags, miniaturas e grade/lista: não existem) | Vn |
| R07 | 04-Cerebro/Central de Inteligência | Cérebro › Conversar | `study.js`, `.st-*` | vazio | abas, histórico, hero, composer, blocos | I (sem "Trabalhar com o seu conhecimento") | Vn |
| R08 | 04-Cerebro/Central de Salvos | Cérebro › Salvos | `#st-panel-saved` | lista | cabeçalho com ladrilho, busca, filtros, linhas | **I** (14/11: itens em faixas de vidro com ladrilho, "Abrir" em pílula e menu; sem busca, filtros por tipo e ordenação, que não existem) | V (com itens de mentira) · Vn (vazio) |
| R09 | 04-Cerebro/Fontes de conhecimento | Cérebro › Fontes | `#st-panel-sources` | conectado | cabeçalho, cartões Notion/Obsidian com fatos, busca por significado, pastas, internet | I | V |
| R10 | 04-Cerebro/Estudar e Revisar | Cérebro › Estudar | `study-learn.js`, `.st-lrn*` | início | cabeçalho, revisão de hoje, objetivos, recentes | I (cabeçalho e cartões) | V |
| R11 | 05/Catálogo de Skills | Config. IA › Catálogo | `study-settings.js` (catalog), `glass.js` (`aiCards`) | lista | cartões com ladrilho, skills | **I** (12/11, 4ª sessão: cada skill é uma linha com ladrilho, estado e "Testar", como na referência) | V |
| R12 | 05/Configurações da IA | Config. IA › Modelos | idem (models) | — | nav em pílula, cabeçalho, cartões com ladrilho, linhas com ícone e filete | **I** (12/11: ladrilho por cartão e ícone por linha) | V |
| R13 | 05/Conectores | Config. IA › Conectores | idem | — | idem | **I** (12/11) | V |
| R14 | 05/Desempenho | Config. IA › Desempenho | idem | — | idem + fontes indexadas | I | V |
| R15 | 05/Avaliação local | Config. IA › Avaliação | idem | vazio | contador, estado vazio, trilha Avaliar → Registrar → Comparar | **I** (12/11, 4ª sessão: contador, estado vazio e a trilha; `glass.js` `evaluation`) | V (vazio e com casos) |
| R16 | 05/Memória | Config. IA › Memória | idem | — | grupos com chaves | I (ícone por linha) | V |
| R17 | 05/Pesquisa | Config. IA › Pesquisa | idem | — | fontes com chaves | I (ícone por linha) | V |
| R18 | 05/privacidade da IA | Config. IA › Privacidade | idem | — | níveis, aplicativos | I | V |
| R19 | 05/Projetos | Config. IA › Projetos | idem | vazio | estado vazio ilustrado | **I** (12/11: ilustração em CSS; o texto é o de sempre; sem o cartão "Por que usar projetos?") | V |
| R20 | 05/Voz | Config. IA › Voz | idem (voice) | Voice Studio pronto | motor, qualidade, linhas com ícone | **I** (12/11) | V |
| R21 | 05/PDFs e imagens | Config. IA › PDFs | idem | — | 4 cartões (documentos, imagens, comandos, tipos) | **I** (12/11, 4ª sessão: quatro cartões de vidro com os mesmos controles e textos; `glass.js` `pdf`) | V |
| R22 | 05/Perfil Adulto | Config. IA › Perfil adulto | idem | desligado | ativação, estilo e geração | **I** (12/11) | V |
| R23 | 05/Histórico de Atividades | Config. IA › Atividades | idem | vazio | linha do tempo com filtros | **I** (12/11, 4ª sessão: linha do tempo por dia com os mesmos registros, em lotes de 30; sem os filtros da referência, que não existem; `glass.js` `activity`) | V (vazio e com registros de mentira) |
| R24 | 05/Voice Studio em vidro neon | Integrações (Voice Studio) | `#view-integrations`, `voice.js` | pronto | lista de integrações com estado, configurações gerais, painel | P (lista + gerais + painel; sem sub-abas Voz/Transcrição/Desempenho/Modelos, que não existem) | V |
| R25 | 05/Monitor Lúmen & Sistema | Monitor (flutuante) | `#sys-monitor-pop` | — | cartões CPU/RAM/GPU, motores | **I** (14/11, só CSS: cabeçalho à esquerda com o ladrilho do cometa, ladrilho + filete + valor grande por recurso, motores em grade; rola em janela baixa; o título "Motores ativos" e os valores são os do app) | Vn (dados reais do hardware) |
| R26 | 05/Personalização | Config. IA › Personalização | idem | — | 3 cartões (instruções, estilo, preferências) | **I** (12/11, 4ª sessão: três cartões de vidro com os mesmos campos; `glass.js` `personal`) | V |
| R27 | 06/Capas do Notion | Ajustes › Capas | `[data-cat=covers]`, `.g-cov-*` | sem página, com página, com prévia, sem Notion | cabeçalho, passos 1-2-3, cartão de escolha, "Como funciona", detalhes | **I** (12/11; a trilha espelha o estado real do fluxo) | Vn |
| R28 | 06/Captura | Ajustes › Captura | `[data-cat=capture]` | — | cabeçalho, 2 cartões | I | V |
| R29 | 06/IA Local | Ajustes › IA local | `[data-cat=ai]` | — | cartões de opção, modelos | I | V |
| R30 | 06/proteção do cérebro | Ajustes › Proteção | `protection.js` (intacto), `glass.css` | sem pasta, em andamento, em dia, falha | situação, atividade com selos, cópias em cartões | **I** (12/11, só CSS; "Recuperar minhas notas" fica na fileira de ações, não dentro do cartão da situação) | V (configurada, com estados de mentira) · Vn (sem pasta) |
| R31 | 06/Transcrição Local | Ajustes › Transcrição | `[data-cat=transcription]` | — | 3 cartões de opção com marcação | I | V |
| R32 | 06/Pomodoro | Ajustes › Pomodoro | `#set-pomo` | — | ciclos em cartões, durações, comportamento | I (sem "Seu ciclo de estudo", decorativo) | V |
| R33 | 06/Diagnóstico | Ajustes › Diagnóstico | `.diag-panel` | concluído com avisos | cabeçalho com ladrilho, situação com selo grande, um cartão por subsistema | **I** (12/11) | Vn |
| R34 | 06/Privacidade e dados | Ajustes › Privacidade | `[data-cat=privacy]` | — | grupos, limpar | I | V |
| R35 | 08/Ajustes em Vidro Escuro | Barra flutuante › Ajustes | `widget.css` (bloco Glass), `widget.html` (`data-ui`) | barra em cima/embaixo | grade 2 colunas de ladrilhos | **I** (12/11, só no Glass; encaixada na lateral a lista continua em uma coluna: não há largura) | V |
| R36 | 08/Interface em Vidro Líquido | Cérebro › menu de modo/esforço/modelo | `.st-menu` | — | blocos de escolha, trilho de esforço | **I** (14/11, só CSS: título à esquerda com o selo à direita, cartão de descrição com ladrilho e filete; sem o ladrilho e o subtítulo do cabeçalho, para o menu não crescer; o bloco "Modelo da resposta" não apareceu nas capturas e não foi comparado) | Vn |
| R37 | 08/Painel em Vidro Escuro | Barra flutuante | `widget.*` | parada, gravando | trilha, Pronto, Pomodoro, relógio, Assistir | **I** (12/11, 4ª sessão, só desenho no bloco Glass do `widget.css`: bandeja contínua, filete entre o estado e o Pomodoro, sair em círculo; nenhuma geometria mudou) | V |
| R38 | 08/Painel Pomodoro | Painel do Pomodoro (principal) | `.pomo-sheet` | pausado | anel grande, selo de estado, ação larga, linhas | I | V |

Defeitos das imagens corrigidos (não reproduzidos): botões do macOS junto com os do Windows; "Outro link"/"Link do YouTube" como fontes; chave "Áudio do sistema";
caixas de seleção de destino na Nova aula; Tags, miniaturas, porcentagens; "Trabalhar com o seu conhecimento"; sub-abas do Voice Studio; textos do tipo "Estudos 12";
logotipos de terceiros (Notion, Obsidian) desenhados como marca — o Lumen usa os próprios ícones.
