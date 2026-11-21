# Lúmen Glass 2026 — QA visual

Método: captura da interface **renderizada** (Chrome headless sem GPU, como o WebView2 do Lumen; mundo simulado de `tests/ui_shots.py`, 1568 × 1003) posta ao lado
da referência. As referências têm tamanhos entre 1424 × 1105 e 1568 × 1003; a comparação é de estrutura, proporção, hierarquia e material, não de pixel.

- 11/11: capturas em `D:\Lumen\glass-20261111\ui\depois\` (e `antes\`), scripts em `D:\Lumen\glass-20261111\scripts\`.
- 12/11: capturas em `D:\Lumen\glass-20261111-s3\ui\` (`r05`, `r05-alto`, `r05-estreito`, `r05-classico`, `barra-antes`, `barra-glass`, `capas`, `prot-antes`, `prot`,
  `diag`, `ia-antes`, `ia`, `nativo`), scripts em `D:\Lumen\glass-20261111-s3\scripts\` (`shots.py`, `shots_widget.py`, `gen_visual.py`, `nativo_s3.ps1`).
- Janela real do `Lumen.exe`: 10/11 para Início, Biblioteca, Cérebro, Integrações e Ajustes; 12/11 para Ajustes, Capas, Diagnóstico e Proteção (`ui\nativo\`).

| Ref. | Tela | Igual à referência | Diferença aceita / pendente |
|---|---|---|---|
| R01 | Início | grade, hero, Sistema, Continue, Ações rápidas, jornada, Revisões, cometa, Pomodoro | sem miniaturas e selos de estado nas linhas (sem dado); "Salvas recentemente" a mais (função existente) |
| R03 | Minha compreensão | etapas em linha, título central 38, papel com borda de foco, barra de ação | etapas sem a cápsula de fundo; shell Glass em vez do rail estreito |
| R02 | Análise | etapas, título central, coluna "Salvar" com luz | cartões da análise com o desenho anterior |
| R04 | Nova aula | fontes, estúdio, recuperação âmbar, fluxo, coluna lateral, barra de ação | 3 fontes reais (sem "Outro link"); "Áudio do PC" é aviso, não chave |
| R05 | Material processado | as 4 etapas concluídas, ladrilho verde + "Material processado com sucesso" + subtítulo, "Seus materiais" com um cartão por destino (selo "Salvo", fatos com ícone, botão largo), "Visualização de conceitos" (imagem num poço escuro + fatos), ações em duas fileiras | rodapé na ordem Notion, compreensão, Obsidian (a do DOM, para o teclado); ícones próprios no lugar dos logotipos; com um destino só, o rodapé não repete o botão do cartão; a visualização das capturas é sintética (aula de teste "Fotossíntese", desenhada pelo próprio Lumen) |
| R06 | Biblioteca | números, vistas, estrutura, lista, ações | sem Tags, miniaturas, grade/lista |
| R07 | Cérebro | cabeçalho, abas, histórico, hero com horizonte, composer, blocos, Pomodoro compacto | sem "Trabalhar com o seu conhecimento"; sem subtítulo sob a pergunta |
| R09 | Fontes | cabeçalho com ladrilho, cartões com fatos, linhas | — |
| R10 | Estudar | cabeçalho com ladrilho, objetivos em cartões | "Revisão de hoje" como estava |
| R12, R13, R14, R16, R17, R18, R20, R22 | Config. IA (Modelos, Conectores, Desempenho, Memória, Pesquisa, Privacidade, Voz, Perfil adulto) | duas colunas, navegação em pílula, cabeçalho de seção, cartão com ladrilho + título + frase, linhas separadas por filete com ícone num ladrilho pequeno | os textos de ajuda são os do Lumen (mais longos que os das imagens); ícones escolhidos entre os do Lumen (sem termômetro, por exemplo) |
| R19 | Projetos | cartão com "Novo projeto", estado vazio ilustrado (pasta de vidro com segunda folha e luz) | o texto é o existente ("Nenhum projeto ainda…"), não a manchete da imagem; sem o cartão "Por que usar projetos?" |
| R11, R15, R21, R23, R26 | Catálogo, Avaliação, PDFs, Atividades, Personalização | cartão com ladrilho; linhas com ícone onde há linhas | Catálogo em lista; Avaliação sem contador/trilha; PDFs e Personalização num cartão só; Atividades sem linha do tempo (e só vista vazia) |
| R24 | Integrações | lista com estados, configurações gerais, painel da integração | preferências em lista (não em caixas de seleção); sem sub-abas do Voice Studio |
| R27 | Capas do Notion | cabeçalho com ladrilho, trilha 1-2-3 (o passo atual em pílula, os feitos com visto), cartão "Escolha uma página" com ladrilho, "Como funciona" em 3 passos com setas, "Gerador e detalhes técnicos" numa linha com seta | a trilha é visual (`aria-hidden`): o estado é anunciado pelo próprio fluxo; campo de busca com 40 px (50 na imagem) |
| R28, R31, R32, R29, R34 | Ajustes (Captura, Transcrição, Pomodoro, IA local, Privacidade) | cabeçalho com ladrilho, cartão por grupo, cartões de opção com marcação | sem ícone por opção; sem "Seu ciclo de estudo"/"Estado do sistema" |
| R30 | Proteção do cérebro | título solto no alto, situação num cartão com emblema grande (tom do estado), atividade em linhas com o estado em selo à direita, cópias em cartões lado a lado com a ação no rodapé | "Recuperar minhas notas" e "Fazer backup agora" numa fileira abaixo do cartão da situação (na imagem, um botão dentro dele); o texto do estado da etapa é o selo (a imagem tem descrição + selo); título sem ladrilho, como na imagem |
| R33 | Diagnóstico | cabeçalho com ladrilho, situação com selo grande + filete + título 28, botão largo + "Última conferência", um cartão por subsistema com ícone, título, selo "Pronto" e linhas nome / detalhe | com avisos o selo grande mostra "!" âmbar (a imagem só tem o estado 100%); nomes e detalhes são os do diagnóstico real da máquina |
| R35 | Barra › Ajustes | cabeçalho com seta, cartão "Assistir a tela junto", 8 categorias em ladrilhos de 2 colunas, nomes inteiros | só com a barra em cima/embaixo; na lateral continua a lista (largura); fonte de 10 px para caber "Proteção do cérebro" em 131 px |
| R37 | Barra flutuante | trilha de botões, "Pronto", Pomodoro, relógio, onda, "Assistir ativado", sair, aurora | não alterada: sem a bandeja contínua atrás dos botões e sem o filete vertical entre "Pronto" e o Pomodoro |
| R38 | Painel do Pomodoro | anel grande, selo de estado, sessão em pílula, ação larga, linhas em cápsula | — |
| R25 | Monitor | material flutuante, cartões | tamanhos e tipografia como estavam |
| R36 | Menu de modo/esforço | estrutura já igual; material e seleção | — |

## Defeitos achados pela comparação em 12/11 (corrigidos)

- Resultado sem visualização mostrava o texto "null" (defeito antigo, também no Clássico): `replaceChildren` recebia `null`.
- O texto do cabeçalho de Ajustes podia passar por baixo do Pomodoro (30 px): a reserva à direita era menor que o cartão.
- O foco do resultado ia para o rodapé e rolava a tela, escondendo o título: no Glass o foco fica na ação do primeiro destino e a tela no topo.
- Controle deslizante das Configurações da IA com 16 px de altura: área de arrastar com 24 px no Glass.
- `glass_ui.py`: a verificação "Continuar habilita depois de gravar" lia o botão no mesmo instante da resposta (falha intermitente): agora espera o estado.

## Comparação de 14/11 (5ª sessão; capturas em `D:\Lumen\glass-20261114-s5\ui`)

| Ref. | Antes | Depois | Sobra em relação à referência |
|---|---|---|---|
| R02 Análise | coluna "Salvar" com 340 px e um cartão dentro do outro: "Organizar depois" quebrava, a trilha do Notion e o selo do Obsidian eram cortados | coluna com 30% (399 px em 1568), destinos sem moldura dupla, nada cortado, ícone no botão de salvar | sem ícone no campo do link |
| R08 Salvos | linhas sem moldura, ladrilho de 36 px | faixas de vidro, ladrilho de 46 px, "Abrir" em pílula | busca, filtros por tipo e ordenação não existem |
| R25 Monitor | tudo centralizado, 380 px, textos pequenos | cabeçalho à esquerda com o ladrilho do cometa; ladrilho + filete + valor grande por recurso; 420 px; rola em janela baixa | título "Motores ativos" (o app não tem "e proteção"); temperatura junto do uso |
| R36 menu de modo | títulos em versalete centralizados, descrição centralizada | título à esquerda com selo à direita; descrição com ladrilho e filete | sem ladrilho/subtítulo no cabeçalho; as marcas do esforço ficam dentro do cartão |

Defeito achado pela comparação e corrigido: em janela baixa o Monitor espremia os cartões (com `overflow: hidden`) em vez de rolar.
Tamanhos vistos: 1568 × 1003, 1100 × 760 e 820 × 700 (folha em `ui\estreito\folha.png`).

## Limites desta validação

- A comparação é em Chrome sem GPU e, para quatro telas, na janela real; **não** houve conferência em escala 125/150% nem em vários monitores.
- Atividades com histórico, Avaliação com casos, Salvos com itens e a Análise foram vistos com dados de mentira (12 e 14/11), não com os dados do usuário.
- A Proteção configurada foi vista com estados de mentira (os formatos de `tests/protection_ui.py`), não com backups reais.
- Gosto e acabamento final são do usuário.
