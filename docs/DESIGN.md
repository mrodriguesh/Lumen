# Design do Lumen

Como a interface é feita e o que toda tela nova precisa seguir. Os tokens e os componentes estão em
`lumen/web/ui.css` (compartilhado pelas três janelas); o layout de cada tela, em `app.css` (janela principal e janela
flutuante da nota) e `widget.css` (barra flutuante). O mostruário vivo fica em `http://127.0.0.1:<porta>/design`.
A forma da janela principal tem dois **estilos** (Ajustes → Aparência → Estilo da interface): o **Clássico**, descrito aqui, e o **Lúmen Glass 2026**
(seção própria no fim deste arquivo; tudo dele em `glass.css`/`glass.js`, sem mudar o Clássico).

## Princípios

1. **Legibilidade antes de efeito; clareza antes de vidro.** Se um efeito atrapalha a leitura, ele sai.
2. **Uma ação principal por tela.** Ela é a única em `btn primary`; as outras são secundárias ou fantasmas.
3. **Estado nunca só por cor.** Sempre ícone + texto + cor (badge, pílula de status, chip).
4. **Menos ruído, mais hierarquia.** Informação secundária fica recolhida (`details.disclosure`), em dica ou na busca.
5. **Calmo quando parado.** Nada pisca ou pulsa sem motivo: só o que está acontecendo de verdade (gravando,
   processando) se move.
6. **O texto do estudante é dele.** A escrita do estudante é em serifa (`--serif`, `.writing`, `--paper`); a
   interface e a IA usam a Inter. A análise da IA fica numa superfície própria (`--ai-surface`).

## Camadas

```
fundo (--bg-base + halo azul suave)
  └ rail e barra superior: vidro simulado (--glass-subtle), sem blur
      └ área de trabalho: folha sólida (--bg-elevated, cantos de 28)
          └ cartões de conteúdo (--surface-1) → controles (--surface-2/3)
              └ flutuantes: popover, Pomodoro, resultados de busca, toast (--glass-floating)
                  └ modal e confirmação (--glass-modal + ::backdrop)  └ dica (tooltip)
```

**Vidro.** O WebView2 do Lumen roda sem GPU (`--disable-gpu`, ver `docs/DECISOES.md`), e o blur custa CPU. Regras:

- `backdrop-filter` só em `.glass-floating`, na busca (Ctrl+K) e, se preciso, em outro modal pequeno. Nunca em
  superfícies grandes, nunca animado.
- Rail, barra superior e barra flutuante usam vidro **simulado**: gradiente translúcido + luz na borda de cima
  (`--rim`/`--rim-strong`). A barra flutuante é uma janela opaca (região GDI), então nela não existe vidro real.
- Cartões com texto longo são sólidos.

## Tokens

| Grupo | Tokens | Uso |
|---|---|---|
| Fundo | `--bg-base`, `--bg-elevated`, `--surface-1/2/3`, `--surface-hover/active/sunken` | profundidade por níveis |
| Texto | `--text-primary`, `--text-secondary`, `--text-tertiary`, `--text-disabled`, `--text-inverse`, `--on-accent` | primário, descrição, metadados |
| Acento | `--accent`, `--accent-hover`, `--accent-strong`, `--accent-soft/softer`, `--accent-text`, `--accent-line`, `--accent-border`, `--accent-grad` | ação principal, item ativo, foco, progresso |
| Estados | `--success`, `--warning`, `--danger`, `--rec` (+ `-soft`, `-line`, `-text`) | sempre com ícone e texto |
| Obsidian | `--obsidian`, `--obsidian-soft`, `--obsidian-line` | só no ícone e na borda esquerda do destino Obsidian; nunca fundo de cartão |
| Borda | `--border-subtle/medium/strong`, `--border-focus` | 1 px; o ativo ganha contraste |
| Raio | `--r-xs 4`, `--r-sm 6`, `--r-md 10`, `--r-lg 14`, `--r-xl 20`, `--r-2xl 28`, `--r-pill` | interno = externo − espaço |
| Espaço | `--space-1…16` (4, 8, 12, 16, 20, 24, 32, 40, 48, 64) | só múltiplos de 4 |
| Sombra | `--shadow-1/2/3`, `--rim`, `--rim-strong` | escuras e suaves; a luz fica na borda |
| Vidro | `--glass-subtle/medium/floating/modal`, `--glass-line`, `--glass-blur` | ver “Vidro” |
| Movimento | `--dur-fast 120`, `--dur-normal 200`, `--dur-slow 320`, `--ease-standard/emphasized/exit` | sem ricochete |
| Camadas | `--z-sticky 10` … `--z-tooltip 70` | |

**Cores.** O primeiro bloco `:root` de `ui.css` é a única fonte dos valores de cor; o que é *derivado* (`--accent-grad`, `--glass-subtle/medium`, `--rim`,
`--shadow-1/2/3`, `--info`) é montado num segundo bloco `:root` a partir deles. Não há troca de cores em tempo de execução: o visual é o descrito aqui.

**Sem cor solta.** `app.css` e `widget.css` não têm `#hex`: toda cor vem de um token (`tests/test_ui_tokens.py` falha
se aparecer). Os textos passam de 4,5:1 sobre todas as superfícies, inclusive o terciário, e o anel de foco e os pontos
de status passam de 3:1 (o mesmo teste confere). Mudou um token? Rode o teste.

**Tipografia** (Inter, já no projeto): `.t-display` 30, `.t-h1` 24, `.t-h2` 18, `.t-h3` 15, corpo 14, `.t-sm` 13,
`.t-label` 12,5/500, `.t-caption` 12, `.eyebrow`/`.t-micro` 11 em maiúsculas. Números que mudam usam `tabular-nums`.
Todo tamanho de fonte vem de um `--fs-*`: além dos acima, a escala compacta da barra (`--fs-2xs` 9,5 · `--fs-tiny` 10 ·
`--fs-compact` 10,5 · `--fs-meta` 11,5), o campo (`--fs-input` 13,5), a escrita do estudante (`--fs-writing` 18,
`--fs-writing-sm` 16,5, `--fs-quote` 16) e os relógios (`--fs-clock` 44, `-sm` 40, `-xs` 34). Um `font-size: 13px`
solto em `app.css` ou `widget.css` faz o teste falhar.
Pesos: 600 para títulos, 500 para rótulos, 400 para o resto. Nada de negrito em tudo.

## Componentes (ui.css)

| Componente | Classes | Notas |
|---|---|---|
| Botão | `btn` (secundário), `btn primary`, `btn ghost`, `btn danger`, `btn danger primary`; tamanhos `sm`/`lg` | ícone + texto; altura 34 (28/42) |
| Botão de ícone | `icon-btn` (`sm`), `[aria-pressed=true]` para ativo | sempre com `aria-label` + `data-tip` |
| Campo | `label.field` + `input/select/textarea`, `.opt`, `.field-hint`, `.field-error`, `.input-row`, `.search-field` | estados hover, foco, `aria-invalid`, `disabled`; o erro fica logo abaixo do campo (`.field-error` com ícone, e o campo aponta para ele em `aria-describedby`) |
| Chave | `input.switch` (janela principal) e `button.switch[role=switch]` (barra) | |
| Segmentado | `.segmented` com `button[aria-pressed]`, `[role=tab][aria-selected]` ou `label > input[type=radio]`; `.wide` com `<small>` | a seleção é uma pílula clara |
| Linha de ajuste | `label.set-row` > `.set-text` (strong + small) + controle; `.set-list` agrupa várias com divisores, `.set-item` junta uma linha e o ajuste que depende dela | quebra em janela estreita; o ajuste dependente some (com o valor guardado) quando a linha está desligada |
| Prévia de capa | `.cover-box` > `.cover-area` > `figure.cover-preview` (`.cover-img` 12:5 com `img`, `.cover-emoji`, `.cover-cap`) + `.cover-state[data-tone]` + `.cover-actions` | sem prévia, o espaço é baixo (`data-empty`); gerando ou com o nome mudado, a imagem esmaece (`data-stale`); o estado diz o tipo da capa e o tempo medido |
| Seletor de página do Notion | `label.field` > `.search-field` > `input[role=combobox]` + `.cov-results` (`ul.pal-list.cov-list[role=listbox]` + `.cov-list-foot`: estado, Tentar de novo, Carregar mais) → `.cov-page` (ícone, título, `.badge`, onde está, Abrir no Notion, Trocar) | Capas do Notion: busca com espera de 300 ms e respostas velhas descartadas; link colado vai direto; setas, Enter, Esc e `aria-activedescendant`; a lista cresce dentro do cartão (sem flutuar) |
| Capa do Notion (diálogo) | `dialog.dlg.cov-dlg` (cabeçalho com fechar + `.dlg-body` que rola) recebe o mesmo `#cov-box` de Ajustes → Capas do Notion | aberto pelo `btn sm` **Capa** do cartão do Notion (Destinos do estudo); sem detalhes técnicos; fechar devolve o bloco a Ajustes e o foco ao botão |
| Abas de integração | `.integ-tabs[role=tablist]` > `button.integ-tab[role=tab]` (`.integ-tab-ico` + `.integ-tab-name` + `.integ-state[data-tone]`) | uma aba por integração com o estado resumido (ícone + texto); setas, Home e End; a seleção é borda e traço de acento |
| Cartão | `.card`, `.card-head` | sólido |
| Estado | `.badge[data-tone]` (ok, warn, error, busy, rec), `.status-pill[data-tone]`, `.chip-status[data-tone]`, `.spinner`, `.live-dot` | |
| Destino | `.dest-row` > `.dest-logo` + `.dest-main` (`.dest-top` nome + badge · `.dest-line2` destino + `btn sm` · `.dest-feats`) | Notion e Obsidian na Nova aula; estado de `notionState()`/`obsidianState()`, os mesmos de Integrações |
| Visualização 3D | `.v3d-set` (Destinos do material: texto + `.segmented wide` Animada/Estática/Desligada + `details.disclosure` técnico) e `figure.v3d-preview` no resultado (`picture` com o PNG em `prefers-reduced-motion` + `figcaption`) | a prévia é a mesma imagem que foi aos destinos; o estado diz o tipo (animação ou imagem estática) e onde ela entrou |
| Progresso | `.progress > span` (largura = progresso real) e `.progress.indeterminate` | sem percentual confiável, use o indeterminado |
| Carregando | `.skeleton` | em listas; nunca bloqueie a tela inteira |
| Vazio | `.empty` > `.empty-icon` + `strong` + `p` + ação | explica a área e a próxima ação |
| Diálogo | `dialog.dlg` > `.dlg-head` / `.dlg-body` / `.dlg-foot` | confirmação: `ui.confirm()` |
| Aviso | `ui.toast(msg, "success"\|"info"\|"warning"\|"error")` | 4 s, aviso 6 s, erro 9 s; um por vez |
| Dica | `[data-tip]` (vazio = usa o `aria-label`), `data-kbd`, `data-tip-pos` | `ui.js`; nunca `title` (some atrás das janelas sempre por cima) |
| Ícone | `<svg class="i"><use href="/icons.svg#nome"/></svg>` ou `ui.icon("nome")` | sprite próprio, grade 24, traço 1,75 |
| Pomodoro | `.pomo[data-state]` (ready, focus, paused, short, long, focusdone, breakdone) > `.pomo-ring` + `.pomo-name` + `.pomo-label`/`.pomo-short` + `.pomo-clock`; `.pomo-sheet` (painel); `.pomo-panel` (Ajustes) | estado sempre em palavras; o anel usa `--pomo-p`. Uma montagem com painel por janela; o relógio é um só por janela (`pomodoro.js`) e o estado vem do servidor |

**Ícones.** Só os do `icons.svg` (a lista aparece no `/design`). Para trocar o ícone de um botão (pausar ↔ retomar),
use `ui.setIcon(botão, "nome")`: mudar o `href` de um `<use>` já desenhado não redesenha no Chromium com o sprite
externo, e o ícone some. Para um novo, desenhe na mesma grade e no mesmo traço.
Nada de emoji ou glifo Unicode como ícone de interface; os emojis das páginas do Notion são dado do usuário e ficam.

## Navegação e layout

```
┌──────┬──────────────────────────────────────────────────────────────┐
│ ●●●  │ Área / etapa        [⌕ Buscar  Ctrl K]   [● status]  [Foco 18:42] │
│  ◉   ├──────────────────────────────────────────────────────────────┤
│Início│  ┌────────────────── área de trabalho (folha) ────────────────┐ │
│ Nova │  │  título da página + uma linha de contexto                  │ │
│Biblio│  │  conteúdo (máx. 1180 px)        [painel de contexto]       │ │
│Integr│  └────────────────────────────────────────────────────────────┘ │
│Ajust.│                                                                 │
└──────┴──────────────────────────────────────────────────────────────┘
```

- `showView(nome)` troca a área (`home | new | library | study | integrations | settings`) e atualiza o rail
  (`aria-current=page`) e a barra superior (`setWhere`). Ajustes por categoria: `goSettings(categoria)`. Integrações
  por aba: `goIntegrations("notion" | "obsidian" | "drive" | "voicestudio")`. A ordem da página é: destinos do material, as
  abas e o painel da aba escolhida (uma coluna de até 920 px, como os Ajustes). Trocar de aba só mostra ou oculta o
  painel: cada formulário existe uma vez, nada é salvo nem enviado, e o que está sendo digitado fica. A aba aberta
  fica no `localStorage` (`integTab`).
- A Nova aula tem etapas (`showStep`): `compose → understand → analysis (+ review) → run`, com o stepper
  `Fonte → Compreensão → Análise → Salvar`. `showStep` não troca de área sozinho: quem abre uma aula por ação do usuário
  chama `showView("new")` antes (evita tirar a pessoa da Biblioteca quando uma tarefa termina em segundo plano).
- **Painel de contexto** (à direita) só quando há contexto de verdade: Análise + Salvar. Abaixo de 1100 px ele desce.
- **Status global** (barra superior): Pronto, Configuração pendente, Gravando, Pausado, Processando · etapa · %, Erro.
  Clicar leva aonde está acontecendo.
- **Busca (Ctrl+K)**: telas, categorias de Ajustes, ações (gravar, pausar, destacar, painel do Obsidian, criar capa
  no Notion), aulas em andamento e salvas. Comando novo? Acrescente em `palCommands()` chamando uma função que já existe.

**Pontos de quebra.** 1180 (Início em 2 colunas), 1100 (painel de contexto e colunas da Nova aula descem), 900 (busca
só com o ícone, Ajustes com categorias em linha), 760 (rail sem rótulos, uma coluna), 640 (abas da fonte só com ícone).
A janela mínima é 520 × 560. Use `grid`/`flex` com `minmax(0, 1fr)`; nada de largura fixa em conteúdo.

**Barra flutuante.** Os tamanhos são contrato com `launcher/WidgetForm.cs` e com os testes: aberta 304 × 252, com a
nota 360 × 440, com a proteção 360 × 540, com a **Conversa rápida 304 × 252 (a mesma janela; ampliada sob pedido, 360 × 540)**,
alça 12 × 84 (84 × 12 em cima/embaixo),
cantos de 18 e fundo = `BackColor` (`--bg-base`, fixo no launcher: `NativeColors`). Mudou algum? Mude o C# e os testes (`DesktopChecks.cs`, `widget_ui.py`,
`chat_ui.py`, `chat_compact.py`) junto. A conversa é a exceção de método: o `.notch` dela ocupa **sempre** o que a janela entrega (100vw × 100vh),
sem tamanho próprio nem `screen.avail*`. A janela da nota tem a barra de 46 px (`NoteForm.Bar`). Controles da trilha, de cima para baixo (ou
da esquerda para a direita, em cima/embaixo): Lumen, **Gravar** (o maior), **Conversa rápida**, [Minha compreensão, só
quando há aula esperando], Ajustes. Com a compreensão são cinco controles e a trilha fica compacta (32 px, Gravar 38) para
não encostar na alça.

## Padrões de UX

- **Ações destrutivas** (descartar gravação, limpar dados, desconectar): `ui.confirm(texto, { danger: true })`, com o
  foco no Cancelar. Nada reversível pede confirmação.
- **Erros** dizem o que houve e o que fazer, com o botão da ação quando existe (Tentar novamente, Retomar, Escolher
  outro cofre). Códigos técnicos só no log.
- **Gravar ≠ parar ≠ descartar:** o principal é vermelho e vira quadrado ao gravar; pausar/retomar é secundário (âmbar
  quando pausado); descartar é `danger` com lixeira e confirmação. Cada controle tem rótulo visível.
- **Processamento** mostra as etapas reais da tarefa (`#stages`), a etapa que falhou e o progresso real, ou o
  indeterminado quando não há percentual; nunca um número inventado.
- **Textos:** português natural, rótulos curtos, “Ajustes” (não “Configurações”), “Integrações” para Notion, Obsidian, Google Drive e Voice Studio.
  Explicação longa vai para dica, `details` ou a documentação.
- **Atalhos** aparecem na dica (`data-kbd`): Ctrl+K, Ctrl+Enter, Ctrl+Shift+D, Ctrl+Alt+P.
- **Estado que não é verificável** (ex.: “Importação confirmada por você”) diz quem confirmou. “Conectado” só para o que
  o Lumen de fato autentica (Notion, Google Drive: “Drive conectado”). O Google Drive tem seis estados, cada um com título, explicação e a
  próxima ação: não configurado, falta entrar (cliente escolhido), aguardando a autorização no navegador, Drive
  conectado, acesso expirado ou revogado, e não foi possível entrar (com a mensagem).
- **Diálogo grande** (ex.: Organizar aula): cabeçalho, abas e rodapé fixos, só o corpo rola
  (`overscroll-behavior: contain`); a mesma altura nas abas, para nada pular. O rodapé tem uma linha de estado
  reservada acima dos botões: mudar de estado não move os botões. Quando o botão em foco some (a ação começou), o foco
  espera na linha de estado e volta para a ação principal ao terminar; ao fechar, volta para quem abriu o diálogo.
- **Aviso com diálogo aberto:** `ui.toast` coloca o aviso dentro do diálogo modal aberto (senão ele ficaria atrás do
  fundo escurecido e inerte).
- **Atualização periódica** (ex.: login do Google): só enquanto a tela está aberta; nunca abre ou fecha seções,
  apaga campos ou rouba o foco (`swap` só troca o que mudou).

## Movimento

Hover e press em `--dur-fast`, entrada de painel e modal em `--dur-normal` com `--ease-emphasized`, troca de estado do
gravador em ~340 ms. Sem `cubic-bezier` de ricochete. Animações infinitas só para o que acontece de verdade (gravando,
processando, sincronizando); `prefers-reduced-motion` desliga todas (regra no fim de `ui.css`). Não anime blur, sombra
grande ou layout. Os pulsos de chamar atenção (`fx-pulse`, ponto do monitor) param com a janela sem foco (`body.inactive`):
sem GPU, cada quadro custa CPU (D188).

## Acessibilidade

- Foco visível em tudo (`:focus-visible`, anel `--border-focus`); alvo de clique ≥ 24 px (os botões têm 28–34).
- Botão só com ícone: `aria-label` + `data-tip`. Status com `role=status`/`aria-live`. Abas com `role=tab` e setas.
- Contraste garantido pelos tokens (teste). Texto sobre vidro só nos níveis com fundo quase opaco.

## Conversa por voz (Estudos → botão de onda)

`lumen/web/study-call.js` + bloco `.st-call*` de `study.css`. Um orbe com o avatar da voz, o estado em texto grande (derivado do que o
servidor informa, nunca de suposição), uma dica de uma linha, o controle **Livre | Notas** (o mesmo estado do chat escrito) e, embaixo, três
ações grandes: mudo, interromper, encerrar. Voz, legendas e minimizar ficam no cabeçalho, discretos. Regras:

- **Calmo parado:** só o orbe, o estado e as legendas se mexem, e só com `transform`/`opacity` (a janela roda sem GPU). O nível do orbe vem do
  nível real (microfone ou voz) em ~16 Hz; `prefers-reduced-motion` zera animação e nível.
- **Estado nunca só por cor:** texto ("Ouvindo", "Você está falando", "Consultando suas notas", "Preparando a resposta", "Falando", "Microfone
  silenciado", "Reconectando", erro) + cor do orbe + ícone/botão. "Ouvindo" só depois de o microfone entregar áudio; a barra de preparo é
  indeterminada e só mostra número se o Voice Studio o informou.
- **Teclado:** Esc encerra, Espaço interrompe (ou segura, no modo apertar para falar), M alterna o mudo; Livre/Notas é um `radiogroup` com setas.
- **Microfone aberto** sempre visível (ponto vermelho); some no mudo. Pílula flutuante ao minimizar, com estado, tempo e Livre/Notas.
- Verificação: `py -3.14 tests/call_ui.py` (estados, Livre/Notas, 1440/1100/760/520 px, movimento reduzido, teclado, pílula; capturas em
  `D:/Lumen/voz-conversa-20261108/ui/`).

## Cápsula de gravação (barra flutuante → botão vermelho)

Estado da barra que já existe (nenhuma janela, captura ou rota novas): `lumen/web/widget.html` + `widget.css` + `widget.js`. O Gravar/Encerrar (`#action`) vive num grupo `.rec-group`
do MESMO tamanho dele, então **parado a barra é exatamente a de antes** (Gravar 40 × 40 no mesmo lugar). Gravando, o servidor manda `recording.active` e a página liga
`body[data-rec=on]`: uma pílula (`.rec-pill`) cresce atrás do grupo e o botão de Pausa (`#pause`, o mesmo de antes, tirado do painel) **sai de trás do vermelho** para o espaço
livre da barra: abaixo dele na barra lateral, à direita dele em cima/embaixo. Conversa, Minha compreensão e Ajustes dão a vez deslizando pela propriedade `translate` (a grade da
barra e a janela não mudam; o Gravar/Encerrar não se mexe: o alvo de encerrar nunca vai parar embaixo do ponteiro). Parar desfaz o caminho de volta.

- **Estados:** parado (sem pausa: `visibility: hidden`, fora do foco e da árvore de acessibilidade) → *iniciando* (anel girando no Gravar, rótulo “Iniciando gravação…”, painel “Iniciando…”;
  a cápsula só abre depois da confirmação do servidor) → gravando (Gravar vira quadrado; Pausa ⏸) → pausado (Pausa vira ▶ “Retomar gravação”, pílula e botão âmbar, painel “Pausada”: o
  estado não depende só da cor) → *encerrando* (anel no Encerrar; a cápsula só recolhe após a confirmação). Falha: a mensagem real aparece no painel e a cápsula volta a mostrar o que o
  servidor está fazendo (uma falha ao encerrar não esconde uma gravação que continua).
- **Medidas** (px lógicos, 304 × 252): barra lateral sem nota: Gravar 40, Pausa 30, folga 4; Conversa/Ajustes descem 30/26 px (a barra tem 250: Ajustes termina em 244). Com Minha compreensão:
  Gravar 38, Pausa 28, pílula mais justa (2 px), os três de baixo descem 28/24/20 px. Barra deitada: Conversa e Ajustes (e Nota) vão 34 px (32 com nota) para a direita; tudo dentro da
  barra, sem tocar a alça. Variáveis em `.rail` (`--cap-*`): nada de `scale` global, fonte menor nem `overflow` que esconda botão.
- **Movimento:** transições de 200–320 ms nos tokens existentes (`--dur-normal`, `--dur-slow`, `--ease-emphasized`), só `translate`, `scale` e `opacity` nos botões; a pílula é o único
  elemento cujo tamanho muda (um elemento solto e pequeno). Sem ricochete, sem brilho extra, sem pulso parado: o anel só gira com um comando pendente. A animação roda quando o ESTADO
  muda, nunca a cada leitura do servidor, e uma página recarregada já gravando aparece pronta (`data-capsule=init`, sem entrada falsa). **Movimento reduzido:** a Pausa aparece no lugar
  com um esmaecer de 120 ms, os vizinhos vão direto ao lugar final e a pílula não cresce animada.
- **Cliques e foco:** a pílula e o anel têm `pointer-events: none`; a Pausa só é focável/clicável quando visível; ordem do teclado: Gravar/Encerrar → Pausa → Conversa; se a Pausa sai de
  cena com o foco, ele vai para o Gravar. Comandos pendentes usam `aria-disabled` (o foco do teclado não se perde). Estado anunciado discretamente num `role=status` (“Gravação iniciada.”,
  “pausada.”, “retomada.”, “encerrada.”) só quando muda. Rótulos: “Iniciar gravação”, “Encerrar gravação”, “Pausar gravação”, “Retomar gravação”; dica curta com `Ctrl+Alt+P`, aberta para o
  lado de dentro na barra deitada.
- **Robustez:** o estado vem do servidor; o clique age pelo que a pessoa VIU (estado diferente na leitura → mostra o real e não age: nunca encerra uma gravação que ela não viu gravando); um
  segundo clique nos 700 ms depois de iniciar é ignorado; leitura pedida antes de um comando que já terminou é descartada; sem conexão a cápsula fica esmaecida (estado possivelmente velho)
  e volta ao real quando a conexão volta. Sem polling nem timer permanente novos.
- Verificação: `py -3.14 tests/capsule_ui.py` (16 blocos: estados, comandos, falhas, outra janela, painéis, cinco posições × com/sem nota, quadros exatos da transição, escalas, teclado,
  movimento reduzido, recarga/reconexão, resposta atrasada), `tests/widget_ui.py`, o bloco “Cápsula de gravação” de `tests/DesktopChecks.cs` (WebView2 real, 52 verificações).

## Conversa rápida (barra flutuante → ícone de balão)

`lumen/web/chat.js` + `chat.css` + `md.js` (Markdown seguro, o mesmo do Cérebro). Um painel **próprio** para perguntar e consultar
sem abrir a janela principal; não é o Cérebro espremido. **Cabe no bolinho:** abre na janela compacta de sempre (304 × 252; o painel útil
tem ~230 × 235 px ao lado da trilha), a barra não cresce. Uma coluna, de cima para baixo: cabeçalho (**Conversa** · relógio da gravação, só
quando há · **⋯** mais opções · **‹** recolher), **Livre | Notas** (com *Temporária* e o escopo ao lado, não no cabeçalho), a conversa que
rola por dentro (recebe o espaço que sobra) e o campo de mensagem (uma linha, cresce em linhas inteiras até ~1/3 do painel e depois rola
por dentro; placeholder curto "Pergunte…" no compacto). O menu **⋯** reúne Nova conversa, Nova conversa temporária, Continuar no Cérebro
(a mesma conversa), **Ampliar a conversa** (360 × 540; escolha da sessão, o padrão é sempre o compacto) e **Ajustes desta conversa**. Regras:

- **Ajustes desta conversa:** painel interno que SUBSTITUI a conversa (não é modal nem outra janela; a janela não cresce): **Voltar** (ícone + texto, sempre à vista, foco inicial) e um corpo que rola
  por dentro com três grupos de rádios (setas movem e escolhem): Modelo (*Rápido do Lumen · padrão* com o modelo resolvido sob ele; modelos locais instalados; uma linha "Responde com …" acima da lista),
  Novas conversas (Normal | Temporária) e Tamanho (Compacto | Ampliado), mais **Restaurar ajustes deste chat**. Mostra o que foi salvo e quando vale ("a partir da próxima resposta"; com resposta em andamento,
  "continua como está"). Esc: menu → ajustes → recolher. Sem controles de temperatura, tokens, prompt ou voz.
- **Temporária:** chip neutro de 20 px (relógio 11 px + "Temporária", `--surface-2`, `--border-medium`; nada de âmbar, pulso ou banner) na linha de modo, à direita de Livre/Notas, que encolhe com reticências e
  nunca empurra os controles. O texto de apoio do estado vazio diz o que é provado ("fica fora do histórico e não cria memórias"). O menu troca "Nova conversa" por "Nova conversa normal" quando o contexto é temporário.
  Livre/Notas (fontes) e Normal/Temporária (histórico e memória) são dimensões diferentes e não se misturam na interface.
- **Barra em cima/embaixo:** com 5 ações o menu usa itens de 26 px (148 px disponíveis) para todas ficarem à vista sem rolar; nas demais bordas e ampliada os itens seguem com 32/40 px.

- **A janela manda:** nenhuma largura/altura de janela mora no CSS da conversa (`widget.css`: `body[data-panel=chat] .notch` = `100vw × 100vh`; nada de
  `screen.availWidth`, `100vh` em conteúdo, margem negativa para ancorar à direita nem `transform: scale`). Ajustes por largura usam `@container`
  (a largura do painel, ≥ 264 px = barra deitada ou ampliada). O que não cabe quebra (`overflow-wrap`), encolhe com reticências ou rola dentro do
  próprio bloco (código, tabela); o menu nunca é mais largo nem mais alto que o painel (rola por dentro).
- **Princípios da Apple traduzidos** (HIG: Layout, Materials, Motion, Accessibility): hierarquia por tipografia e espaço, não por caixas; uma só
  coluna alinhada à esquerda; controles agrupados por função (identificação/ações · modo · leitura · escrita); divulgação progressiva (o secundário
  vai para o menu, fontes e detalhes só abrem sob pedido); superfície de leitura tranquila e opaca (`--bg-elevated`/`--surface-*`), sem blur nem vidro
  porque a janela roda sem GPU; movimento só para explicar mudança de estado, com `prefers-reduced-motion` desligando tudo. Tamanhos de espaço
  (`--space-*`), raios (`--r-*`) e fonte (Inter, `--fs-*`) são os do Lumen; as medidas da janela são decisão do projeto, não da Apple.

- **Calmo:** sem vidro, blur, sombra animada nem animação contínua parado. Só se mexe o que está acontecendo (ponto da etapa, ponto de
  gravação, ponto no ícone); `prefers-reduced-motion` desliga tudo. A resposta em escrita é redesenhada no máximo ~11 vezes por
  segundo, e nada é desenhado com a barra recolhida.
- **Estados reais:** a etapa vem do servidor ("Buscando no Notion e no Obsidian…"); fontes são as da resposta, citadas primeiro e
  marcadas "citada"/"consultada"; **Abrir** confirma pelo que o servidor devolveu ("Nota aberta no Obsidian."); conhecimento geral
  nunca é atribuído às notas (rótulo "Conhecimento geral").
- **Resposta sem cartão:** o texto fica solto na coluna; a pergunta é um balão discreto. Ações (Copiar, Fontes · n / Detalhes,
  resultado completo no Cérebro) ficam sob a resposta e só a lista de fontes/detalhes abre sob pedido.
- **Parcial nunca é concluída:** resposta interrompida ou cortada fica com borda tracejada âmbar e o aviso "não foi concluída",
  fora do histórico, com **Tentar de novo** (reaproveita a pergunta; nunca a duplica).
- **Rolagem:** só acompanha a resposta quem está a ~56 px do fim; quem subiu para ler não é puxado e ganha o botão ↓.
- **Teclado:** Enter envia, Shift+Enter quebra a linha, o Enter que confirma uma composição (IME) não envia; Esc fecha o menu e, depois,
  recolhe a barra (nunca encerra o Lumen, nem interrompe gravação ou resposta); Livre | Notas é um `radiogroup` com setas.
- **Comandos "/" não saem como texto:** o envio externo e o custo têm confirmação só no Cérebro; a barra manda para lá.
- Verificação: `py -3.14 tests/chat_compact.py` (geometria no 304 × 252: limites, recortes, clique, quatro bordas, ampliar em passos, DPI do
  navegador, janela menor), `tests/chat_ui.py` (servidor real, Ollama falso que transmite, 24 blocos), `tests/quick_settings_ui.py` (ajustes e temporário, 14 blocos, com capturas) e `tests/test_quick_settings.py` (servidor: modelo, ajustes, privacidade), `tests/widget_ui.py` (trilha), o bloco
  "Conversa rápida" de `tests/DesktopChecks.cs` (janela e WebView2 reais, com medidas) e `tests/test_ui_tokens.py` (inclui `chat.css`).

## Estudar (Cérebro → aba Estudar)

`lumen/web/study-learn.js` + bloco `.st-lrn*` de `study.css` (escopado: nada de `.card`, `.btn`, campos ou `.segmented` globais mudou). A aba tem
**três níveis, uma tela por vez**: Início → Objetivo (Revisar, Praticar, Planejar, Visualizar) → Atividade (as 12 funções). Cada função tem
um único lugar e fica a dois cliques do início. Regras:

- **Início:** título + uma linha; "Próxima atividade" (revisão pendente com contagem e uma ação primária, ou uma linha calma quando não há);
  "Escolha um objetivo" (quatro botões, nada de seletor de nove opções); "Materiais recentes" (cinco linhas compactas, "Ver todos" na mesma
  tela). Nenhum campo e nenhum card fixo.
- **Atividade:** voltar (diz para onde), título, uma linha, campos essenciais com **rótulo visível** (o placeholder é só exemplo), "Mais opções"
  recolhido, **uma** ação primária, ajuda ("Como funciona") recolhida. Resultado abre na própria atividade; "Criados antes" lista só os do tipo.
- **Estado:** cada atividade é montada uma vez e escondida (`hidden`), não destruída: rascunho, resultado, sessão de revisão e Treino falado
  sobrevivem a trocar de objetivo, de atividade e de aba. O início sinaliza "Rascunho" e "Em andamento".
- **Erro:** a mensagem fica ao lado do campo (`field-error`, `aria-invalid`, `aria-describedby`, `role=alert`) e o foco vai para ele; falha de
  criação mantém o texto e oferece "Tentar de novo".
- **Foco e teclado:** o título da tela recebe o foco ao entrar; "Voltar" devolve o foco ao botão que abriu. Clicar de novo na aba Estudar
  volta ao início. Atalhos (Espaço/1–4 na revisão, barra de espaço do microfone) só valem com a atividade visível. Sem `role=tab/radiogroup`
  só por aparência: objetivos e funções são botões.
- **Visual:** hierarquia por tipografia e espaço; uma superfície destacada só para a próxima atividade; sem cor por função, sem brilho, sem
  blur, sem animação (nada a desligar em `prefers-reduced-motion`).
- Verificação: `py -3.14 tests/estudar_ui.py` (comportamento, 1440/1100/760/520 px, capturas em `D:/Lumen/estudar-20261108/ui/`).

## Lúmen Glass 2026 (Ajustes → Aparência → Estilo da interface)

Catálogo dos componentes, manifesto das 38 referências, status e continuação: `docs/design/` (comece por `LUMEN_CONTINUATION.md`).

Um segundo **estilo** da janela principal, ao lado do Clássico (o de sempre, que continua o padrão). O estilo troca
disposição, geometria, vidro e movimento. Decisões D161–D170 em `docs/DECISOES.md`.

**Como funciona.** `config.json → ui_style` (`classic` | `glass`; ausente = `classic`). O servidor marca `<html data-ui="…">`
antes do primeiro quadro (`server._page_marks`). `glass.css` entra por último e **toda** regra dele fica sob `:root[data-ui="glass"]`; no Clássico ele não muda
nada (teste + comparação de estilos calculados). Peças só do Glass: `.g-only` no HTML (ocultas no Clássico por `app.css`); texto só do Clássico: `.c-only`.
`glass.js` faz o que o CSS não faz: troca sem recarregar, move (nunca recria) elementos para as colunas do Início, a faixa do Pomodoro e o corpo da Biblioteca,
e devolve tudo ao lugar ao voltar ao Clássico; preenche as peças do Glass com os dados e funções do `app.js` (ganchos `window.Glass?.…`).

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ◗ Lúmen                                         [● status]   —  ▢  ✕ (Windows) │  barra de título (44 px, arrasta)
├────────────┬─────────────────────────────────────────────────────────────────┤
│  [logo]    │  Título da página                         ┌ Pomodoro · Foco ┐   │
│ ⌂ Início   │  subtítulo                                 │ ◔ 18:42 / 25:00 ‖ ■ ⌄│  faixa do Pomodoro: rola com a página
│ ⊕ Nova aula│ ┌───────────── cartões de vidro ─────────────┐┌── lateral ──┐      │
│ ▥ Biblioteca│ │                                            ││             │     │
│ ◎ Cérebro  │ └────────────────────────────────────────────┘└─────────────┘      │
│ ⏚ Integr.  │                                                                   │
│ ⚙ Ajustes  │                                                                   │
└────────────┴─────────────────────────────────────────────────────────────────┘
```

**Materiais (sem GPU).** Cartão = preenchimento translúcido derivado dos tokens (`--g-fill`, `color-mix`) + reflexo especular (`--g-specular`) + borda óptica
(`.card::before` com máscara, `--g-edge`) + sombra de contato (`--g-shadow`). Barra lateral = material estrutural, mais denso (`--g-fill-structural`).
Selecionado = vidro mais claro com filete forte (`--g-fill-raised`, `--g-hi-strong`) ou o azul translúcido (fonte, abas, conversa ativa).
`backdrop-filter` **só** em flutuantes pequenos (`.glass-floating`, aviso, dica, menus, painel do Pomodoro, diálogo); nunca em cartão, barra lateral, área de
trabalho ou elemento sticky. Leitura longa (respostas do Cérebro, compreensão, análise, listas) fica em superfície quase opaca.

**Paleta.** `--bg-base #0b0d12`, `--text-primary #f1f2f6`, `--text-secondary #a8aebb`, `--accent #4c69ee` (o #5571EF da direção visual,
2% mais escuro para o texto branco passar 4,5:1), `--accent-strong #7488f5`. Nenhuma cor solta fora do bloco da paleta.

**Tipografia.** Segoe UI Variable (Text no corpo, Display nos títulos), Inter de reserva. Saudação 38, títulos de página 32, título de cartão 19, corpo 15,
auxiliar 12,5–14. Tudo por `--fs-*`/`--g-fs-*` (teste).

**Geometria.** Cartão 20, controle 12, botão 12 (sm 10, lg 14), pílulas só onde é pílula. Barra lateral 176 px (84 px só com ícones abaixo de 1100 px).
Pomodoro 400 × 84 (330 abaixo de 1340; 210 × 62 abaixo de 900; acima do conteúdo abaixo de 640).

**Movimento.** As variáveis de sempre com curvas fortes (`--ease-standard/emphasized/exit = cubic-bezier(.23,1,.32,1)`; `--g-ease-move` para o que gira na
tela). Pressão `scale(.95–.98)` em 120 ms; diálogo 220 ms do centro; painel do Pomodoro 200 ms do canto do cartão; aviso com `@starting-style`. Troca de
tela instantânea. Nada infinito sem motivo (o botão de gravar só se move gravando). Reduzir movimento: sem deslocamento, fades curtos nos flutuantes.

**Janela.** No Glass os controles são os do Windows (`.g-winctl`, `data-g-window`, as mesmas mensagens `window:*`), visíveis só na moldura própria do
`Lumen.exe`; o de maximizar vira restaurar. Os botões coloridos do Mac ficam só no Clássico. Sem menu de Snap Layouts no hover (limite de botão em HTML).

**Testes.** `.venv\Scripts\python -m unittest tests.test_glass` (preferência, marcação, escopo de cada regra, cores, fontes, movimento, blur, contraste da paleta);
`py -3.14 tests\glass_ui.py [--shots]` (troca sem recarregar, persistência, volta ao Clássico com a mesma ordem, funções no Glass e disposição de 520 × 560 a
1920 × 1080); `LUMEN_TEST_UI_STYLE=glass py -3.14 tests\study_ui.py` (o Cérebro inteiro no Glass). Mudou algo no Clássico? Rode também a comparação de estilos
calculados (relatório da tarefa).

## Alinhamento do texto (14/11/2026)

**Regra.** Texto **curto e independente** fica no centro; texto **ancorado** fica no início. "Independente" é o que não está preso a um ícone ou ladrilho à
esquerda, a um controle à direita, à borda de uma lista ou a uma coluna de leitura: mensagem de um cartão sem ilustração (aula gravando, pausada ou em
processamento no Início), estado vazio, nota de rodapé de cartão, mensagem de diálogo, rótulo acima de um controle centralizado.

**Como.** Dois tokens no `:root` do `ui.css`: `--ta-short` (para `text-align`) e `--jc-short` (para a linha flex que acompanha esse texto: selo, botões).
A regra central fica logo abaixo das utilidades de texto do `ui.css` (`.t-center, .card-note, .st-empty-small, .protection-footnote, .g-ev-note, .pomo-msg,
.prefs-label`), com `text-wrap: balance` para dividir as linhas por igual. Peça nova: use a classe `.t-center` ou acrescente o seletor a essa lista — não
escreva `text-align: center` solto. O bloco "CENTRALIZAÇÃO ELEGANTE" do `app.css` (cabeçalhos de página, diálogos e painéis do Clássico) usa o mesmo token.
Trocar `--ta-short` para `start` devolve tudo isso ao início de uma vez.

**Ficam no início, de propósito** (o inventário completo, com o motivo de cada um, está em `docs/design/LUMEN_ALINHAMENTO_INVENTARIO_GLASS.tsv` e `…_CLASSICO.tsv`):

| O quê | Por quê |
|---|---|
| Campos, áreas de escrita, transcrição, código | o cursor e o texto digitado no centro atrapalham a edição |
| Parágrafos com mais de 3 linhas, listas, tabelas, pares termo–valor | leitura em coluna precisa de uma borda fixa |
| Linhas com ícone ou ladrilho à esquerda (cabeçalhos de seção do Glass, itens de lista, cartões de recurso do Monitor) | o texto forma um par com o ícone; centralizar separa os dois |
| Rótulo à esquerda com controle à direita (linhas de ajuste), rótulo e dica de campo | acompanham a borda do controle |
| Títulos de página, seção e grupo do Glass | seguem a borda esquerda do conteúdo que nomeiam (referências R01–R38); no Clássico os cabeçalhos de página são centralizados |
| Linhas de abrir/fechar (`summary`), navegação, paleta de comandos | a seta e o rótulo dependem da borda esquerda |
| Selos, botões e linhas do tamanho do próprio texto | não há folga para alinhar |
| ~~O convite "Comece uma nova aula" do Glass com a ilustração ao lado~~ | deixou de ser exceção em 15/11/2026, a pedido do usuário: texto e botões centralizam na coluna ao lado da ilustração |
| Notas dos Ajustes da barra (`.prefs-note`) | são estados de várias linhas (`pre-line`) num painel de 266 px |
| Menu da bandeja e aviso do Windows (launcher) | são desenhados pelo Windows; o launcher não desenha texto próprio |

**Cuidados.** Coluna flex centralizada encolhe filhos sem largura própria: a barra de progresso do cartão do Início leva `align-self: stretch`.
Números que mudam (tempo de gravação, Pomodoro) mantêm `tabular-nums`. Nada de `!important` nem de estilo em linha (a CSP barra).

**Como conferir.** `py -3.14 tests\glass_ui.py` (Parte 6: mede o centro de cada texto nos dois estilos, título enorme/sem quebra/não latino/emoji, um caractere,
o token e as exceções) e `tests.test_ui_tokens.Alignment`. Inventário de todas as telas: `D:\Lumen\centralizar-20261114\scripts\inventario.py` + `agregar.py`
(`comparar.py` mostra, contêiner a contêiner, o que mudou entre dois inventários).

## Tela nova: checklist

1. Use os componentes de `ui.css`; se faltar um, crie no `ui.css` (com token) e mostre no `/design`.
2. Uma ação principal; o resto secundário ou fantasma. Estado com ícone + texto.
3. Vazio, carregando e erro desenhados (não só o caso feliz).
4. Funciona em 520 × 560 e em 1920 × 1040, e de 80% a 120% de zoom.
5. Acrescente o cenário em `tests/ui_shots.py` (`SCENARIOS`), rode e **olhe** as imagens em
   `tests/desktop-artifacts/ui/`: `py -3.14 tests\ui_shots.py <nome> --sizes --zoom`. Se a tela entra no fluxo de uma
   aula, acrescente a etapa ao percurso de ponta a ponta (`py -3.14 tests\ui_shots.py --walk`).
6. `.venv\Scripts\python -m unittest tests.test_ui_tokens` (contraste e cores soltas).
