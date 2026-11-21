# Conversa rápida: correção do corte na barra compacta (09/11/2026)

Escrito para: quem mantém o Lumen e precisa saber a causa, o que mudou, como foi provado e o que ainda depende do uso real.

## 1. Causa comprovada

O que a captura mostrava (campo de mensagem saindo pela lateral, cabeçalho e Livre/Notas sumidos) foi reproduzido na **barra real** (Lumen.exe + WebView2), em instância isolada, por automação de interface (UIA, sem mexer no mouse do usuário):

| | Executável antigo em uso + páginas atuais | Candidato anterior (420 × 620) |
|---|---|---|
| Janela ao abrir a conversa | **304 × 252** (não cresce) | 420 × 620 |
| `.notch` (moldura da página) | **420 × 620 em (−116, −368)** | 420 × 620 em (0, 0) |
| Cabeçalho, "Nova conversa", "Recolher", Livre/Notas, lista | y = −357 … −283: **fora da janela** | dentro |
| Campo de mensagem | x = −89 … 197: **ultrapassa a lateral** | dentro |

Cadeia de causas:

1. **O executável aberto não é o testado.** `D:\Aplicativos\lumen 2026\Lumen.exe` (PID 29332, iniciado 02:29) tem SHA-256 `1B560E6B…83A2F`: é o build de 04/11 e **não contém** as mensagens `widget:panel:chat`, `chat:open` nem `desktop:chat`. O candidato da 1ª versão (`348B8AFC…`) existia só em `D:\Lumen\conversa-rapida-20261109\native\` e nunca foi instalado.
2. **As páginas vêm do disco.** O servidor (`pythonw -m lumen`) serve `lumen/web` a cada requisição (cache por mtime), então o executável antigo já mostrava a página nova: janela 304 × 252 + página de 420 × 620.
3. **A página supunha o tamanho da janela.** `body[data-panel=chat] .notch` tinha `width: var(--chat-w)` / `height: var(--chat-h)` (de `min(420, screen.availWidth)`), ancorado à direita com `margin-left: calc(100vw − 420px)` (negativo numa janela de 304). Qualquer janela diferente do esperado cortava o painel.
4. **O teste anterior não podia ver isso.** `chat_ui.py` abria o navegador já em 420 × 620 (a janela que o executável novo daria) e o teste nativo só rodava o executável novo.

A hipótese "é só CSS" estava **errada** como causa única: com o executável certo a 1ª versão aparecia inteira (420 × 620); o defeito era o contrato janela ↔ página.

## 2. O que mudou

- **Compacta por padrão.** A conversa abre na MESMA janela de 304 × 252 (`WidgetForm.ChatPanel = MainPanel`): a barra não cresce. "Ampliar a conversa" (menu ⋯) pede 360 × 540 (`ChatWide`, `widget:panel:chat-wide`), só nesta sessão.
- **A página segue a janela.** `.notch` da conversa = `100vw × 100vh`; saíram `--chat-w/--chat-h`, `screen.avail*` e a margem negativa. O painel é flex coluna com `min-width/min-height: 0`; a lista de mensagens recebe o que sobra e rola; o campo cresce em linhas inteiras até ~1/3 do painel e rola por dentro; ajustes de largura com `@container` (264 px do painel).
- **Interface em uma coluna, poucos controles.** "Conversa" · relógio da gravação (se houver) · ⋯ · ‹ na primeira linha; Livre | Notas (com *Temporária* e o escopo) na segunda; lista; campo com "Pergunte…". Nova conversa, temporária, Continuar no Cérebro e Ampliar ficam no menu ⋯, que nunca passa do painel. Sem ícone no estado vazio, sem deslocamentos negativos, textos secundários subidos para `--fs-caption`/`--fs-micro` (nada abaixo de 11 px nos controles de uso).
- **Achado só na barra real:** na barra deitada a dica longa do campo ("Pergunte ou consulte suas notas…") quebrava de linha no WebView2 e deixava uma barra de rolagem no campo vazio — o Chrome headless não mostrava. Agora a dica longa só entra se cabe numa linha (medida com a fonte real do campo, `chat.js: hintFits`), e `chat_compact.py` e `DesktopChecks.cs` falham se um campo vazio rolar.
- **Corrigidos de passagem:** erro de rede mostrava "Failed to fetch" cru (agora "Sem conexão com o Lumen. Tente novamente."); a dica do escopo usa `data-tip` (nunca `title`); altura do campo vazio não infla mais com o placeholder quebrado.
- **Preservado:** conversa e identificador, histórico e temporárias, Livre/Notas (`skip_vault`), streaming, interromper, erro/recuperação, copiar, fontes, mesma conversa no Cérebro, validação de `chat:open`, Markdown seguro, rascunho, gravação, ajustes, Pomodoro, "Assistir a tela junto". Backend (`agent.py`, `api.py`, rotas) **não** mudou.

### Arquivos alterados

`lumen/web/chat.css`, `chat.js`, `widget.css`, `widget.js`, `widget.html`; `launcher/WidgetForm.cs` (`ChatPanel`, `ChatWide`, `PanelFor`); testes: `tests/chat_compact.py` (**novo**), `tests/chat_harness.py` (**novo**), `chat_ui.py`, `DesktopChecks.cs`; docs: `DESIGN.md`, `DECISOES.md`, `LUMEN_STUDY_AI_DECISIONS.md` (D135–D140), `LUMEN_STUDY_AI_STATUS.md`, `LUMEN_CONVERSA_RAPIDA_20261109.md` (aviso no topo), `README.md`, este relatório.

## 3. Medidas (pixels físicos × unidades do Windows × pixels CSS)

Janela real, 96 dpi (escala 1,0: pixel físico = unidade lógica = pixel CSS; o teste confere `innerWidth × escala = largura do WebView2`, sem aplicar a escala duas vezes). Extraído de `logs/native-final3.log`:

| Estado | Bounds / ClientSize | WebView2 | `innerWidth × innerHeight` | `.notch` | cabeçalho | lista | campo |
|---|---|---|---|---|---|---|---|
| Compacta, esquerda | 304 × 252 | 304 × 252 | 304 × 252 | 0,0 → 304,252 | y 9–37 | y 79–195 | y ≈ 203–243 |
| Ampliada, esquerda | 360 × 540 | 360 × 540 | 360 × 540 | 0,0 → 360,540 | y 9–37 | y 79–483 | y 491–531 |

Na barra real (UIA, instância isolada): compacta 304 × 252 com **17 elementos, 0 fora da janela**; menu aberto 22 elementos, 0 fora; ampliada 360 × 540, 0 fora; reduzida, de volta a 304 × 252, 0 fora (`ui\uia-candidato-novo\`).

## 4. Verificação

| O quê | Resultado |
|---|---|
| Regressão `tests/chat_compact.py` contra o código **antigo** (janela que ignora o pedido, como o executável aberto) | **FALHOU**, como deve: `.notch 0,−368 420×620 não coincide com a janela 304×252`, `#chat-title`, `#chat-collapse`, `#chat-mode` fora/sem clique, `#chat-input` 2/5 pontos sem clique (`logs\chat-compact-ANTES.log`) |
| `tests/chat_compact.py` com o código novo | **OK, 11 cenários**; também com `CHAT_LEGACY=1` (janela que ignora o pedido de tamanho): OK |
| `tests/chat_ui.py` (servidor real, Ollama falso que transmite) | **OK, 24 blocos** |
| `tests/widget_ui.py` | **OK** |
| `unittest tests.test_quick_chat tests.test_ui_tokens tests.test_widget` | **29 testes OK** |
| Nativo `Lumen.Check.exe` (WebView2 e janela reais, dados em D:) | **OK inteiro, exit 0, em 3 execuções finais** (`logs\native-final*.log`): 100 verificações da conversa (compacta sem crescer, ampliar/reduzir sem salto, essenciais amostrados durante a animação, quatro bordas, área útil, interrupção da animação, streaming, rascunho, Esc, `chat:open`), 800 + 140 casos de geometria e as demais regressões. Streaming (resposta simulada de 150 pedaços): 281–286 quadros, maior intervalo 17 / 16,9 / 66,5 ms (a última com a máquina ocupada), 0 tarefas longas |
| Barra real isolada por UIA (compacta, digitando, menu, ampliar, reduzir) | OK nos 4 estados (acima) |
| Suíte completa `unittest discover -s tests -t .` | **982 testes OK em 1046 s** (`logs\suite-full.log`) |

`chat_compact.py` cobre, no viewport 304 × 252 (com a tela de 1920 × 1080, que era o caso do corte): estado vazio em esquerda/direita/em cima/embaixo/livre (E/D), conversa real em Notas com código, tabela, URL longa e fontes, campo de 14 linhas, menu aberto nas 4 bordas (todas as ações com clique de teste; o 1º Esc só fecha o menu), resposta em andamento e erro, 24 aberturas/recolhimentos (com cliques rápidos), ampliar/reduzir com a janela crescendo em 8 passos nas 4 bordas (essenciais conferidos em cada passo), pedido de ampliar com a janela que não cresce, áreas úteis reduzidas (360 × 480, 360 × 400, 330 × 360) e maiores (420 × 620, 800 × 700), escalas 100/125/150/200 % do navegador, movimento reduzido. Em cada cenário: `.notch` = janela; cada essencial existe, está visível, dentro do recorte de TODOS os ancestrais (não só `scrollWidth`) e recebe clique (5 pontos de `elementFromPoint` + clique de teste do Playwright); nada passa da largura do painel (código e tabela rolam no próprio bloco); lista com altura mínima; campo ≤ ~1/3 do painel.

## 5. Capturas (inspecionadas; a aprovação estética é sua)

- Antes (barra real, executável antigo): `D:\Lumen\conversa-rapida-correcao-20261109\ui\uia-antes\right-2-conversa.png`; antes no navegador no mesmo tamanho: `ui\antes-chrome\`.
- Depois, barra real (WebView2, software): `ui\uia-candidato-novo\right-2-conversa.png` (vazio), `right-3-digitando.png` (3 linhas), `right-4-menu.png`, `right-5-ampliada.png`, `right-6-reduzida.png`.
- Depois, navegador (2×): `ui\depois-chrome\depois-01-vazio-{left,right,top,bottom}.png`, `02-conversa-esquerda`, `03-conversa-direita`, `04-notas-com-fontes`, `05-campo-varias-linhas`, `06-menu`, `07-respondendo`, `08-erro`, `09-ampliada`.
- Nativo: `ui\nativo-final3\chat-compacta-{left,right,top}.png`, `chat-ampliada-{left,top}.png`, `chat-respondendo.png`.
- **Janela oficial instalada** (a do uso real, dados pessoais intactos, só abrir e recolher o painel): `ui\oficial\oficial-conversa.png`.
- Quatro bordas na barra real isolada, nos estados compacta/digitando/menu/ampliada/reduzida: `ui\uia-final\{left,right,top,bottom}-*.png`.

Observação honesta: a janela compacta dá ~116 px de leitura (≈ 5 linhas) ao lado da trilha, e ~56–80 px nas barras deitadas; é o preço do tamanho do bolinho. Para ler mais, **Ampliar** (360 × 540) ou **Continuar no Cérebro**.

## 6. Executável

- **Instalado e validado.** O `Lumen.exe` oficial em `D:\Aplicativos\lumen 2026\Lumen.exe` agora é o candidato testado: SHA-256 `EFA29C81F2C8A85C4A329FE92D09517CA0E9B8116F94025D1F9E338CE193EDE1` (o anterior, `1B560E6B…83A2F`, está na restauração). A troca ocorreu às 03:56 com `scripts\instalar.ps1 -Executar`, só depois de conferir que não havia gravação, tarefa nem conversa respondendo (Pomodoro pausado, guardado em `pomodoro.json`) e que o usuário estava sem entrada há mais de uma hora; o Lumen foi fechado pelo próprio botão "Sair do Lumen" (nunca por kill) e reaberto em segundo plano (`--background`, como a barra já estava: a janela principal abre pela bandeja). Foi reaberto uma segunda vez para carregar as páginas finais (`-Reiniciar`).
- **Conferido na janela oficial** (`scripts\uia_oficial.ps1`, `logs\uia-oficial-final.log`): processo `Lumen.exe` do caminho oficial com o SHA-256 acima; a barra volta ao lugar de antes; a conversa abre em **304 × 252** no lugar da barra, **17 elementos, 0 fora da janela**, com "Mais opções" (versão nova) e o campo numa linha só; recolhe de volta à alça 84 × 12. Não digitei nem criei conversa nessa instância.
- Identidade do que foi testado: `D:\Lumen\conversa-rapida-correcao-20261109\IDENTIDADE.json` (SHA-256 do executável, do verificador nativo e de 24 fontes); `py -3.14 -I scripts\identity.py --verify` confere que nada mudou desde os testes. O candidato foi compilado dos fontes de `launcher\` com as opções de `launcher\build.ps1`.
- Para repetir ou reverter a troca: `instalar.ps1` simula sem `-Executar`; a restauração tem o executável anterior.

## 7. Reversão

`py -3.14 -I D:\Lumen\restauracao\conversa-rapida-correcao-20261109\verificar.py --restaurar` devolve os 34 arquivos (inclui o `Lumen.exe` oficial anterior) ao estado de antes desta correção; confira antes com `--origem`. Arquivos novos (não apagados pelo `--restaurar`): `tests\chat_compact.py`, `tests\chat_harness.py` e este relatório. A restauração anterior à 1ª versão continua em `D:\Lumen\restauracao\conversa-rapida-20261109`. Sem `git reset/clean/stash/checkout`; nada foi commitado.

## 8. Limitações

- **Não provado:** teclado e mouse físicos digitando no campo da barra real (a automação preencheu o campo por UIA; o foco por clique real e a digitação física não foram feitos para não roubar o foco de quem usa o PC), vários monitores com escalas diferentes e DPI 125/150/200 % **na janela nativa** (a geometria foi provada em 800 casos e o navegador em 4 escalas, mas o monitor desta máquina é 96 dpi), `ProcessFailed` real do WebView2, modelo, Notion e Obsidian reais (Ollama falso, cofre de teste), o juízo estético.
- "Ampliar" só funciona com o `Lumen.exe` novo (já instalado); com um antigo a conversa continua inteira, compacta, e o item do menu não amplia.
- Reabri o Lumen oficial duas vezes nesta tarefa (troca e recarga das páginas), com o usuário ausente e o app ocioso; o que estava aberto na barra (rascunho em sessionStorage) não foi preservado, como em qualquer reinício.
- O streaming no WebView2 real foi medido com resposta simulada (150 pedaços); não é garantia de 60 FPS.
