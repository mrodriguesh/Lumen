# Design do Lumen

Como a interface é feita e o que toda tela nova precisa seguir. Os tokens e os componentes estão em
`lumen/web/ui.css` (compartilhado pelas três janelas); o layout de cada tela, em `app.css` (janela principal e janela
flutuante da nota) e `widget.css` (barra flutuante). O mostruário vivo fica em `http://127.0.0.1:<porta>/design`.

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
| Campo | `label.field` + `input/select/textarea`, `.opt`, `.field-hint`, `.input-row`, `.search-field` | estados hover, foco, `aria-invalid`, `disabled` |
| Chave | `input.switch` (janela principal) e `button.switch[role=switch]` (barra) | |
| Segmentado | `.segmented` com `button[aria-pressed]`, `[role=tab][aria-selected]` ou `label > input[type=radio]`; `.wide` com `<small>` | a seleção é uma pílula clara |
| Linha de ajuste | `label.set-row` > `.set-text` (strong + small) + controle | quebra em janela estreita |
| Cartão | `.card`, `.card-head` | sólido |
| Estado | `.badge[data-tone]` (ok, warn, error, busy, rec), `.status-pill[data-tone]`, `.chip-status[data-tone]`, `.spinner`, `.live-dot` | |
| Destino | `.dest-row` > `.dest-logo` + `.dest-main` (`.dest-top` nome + badge · `.dest-line2` destino + `btn sm` · `.dest-feats`) | Notion e Obsidian na Nova aula; estado de `notionState()`/`obsidianState()`, os mesmos de Integrações |
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

- `showView(nome)` troca a área (`home | new | library | integrations | settings`) e atualiza o rail
  (`aria-current=page`) e a barra superior (`setWhere`). Ajustes por categoria: `goSettings(categoria)`.
- A Nova aula tem etapas (`showStep`): `compose → understand → analysis (+ review) → run`, com o stepper
  `Fonte → Compreensão → Análise → Salvar`. `showStep` não troca de área sozinho: quem abre uma aula por ação do usuário
  chama `showView("new")` antes (evita tirar a pessoa da Biblioteca quando uma tarefa termina em segundo plano).
- **Painel de contexto** (à direita) só quando há contexto de verdade: Análise + Salvar. Abaixo de 1100 px ele desce.
- **Status global** (barra superior): Pronto, Configuração pendente, Gravando, Pausado, Processando · etapa · %, Erro.
  Clicar leva aonde está acontecendo.
- **Busca (Ctrl+K)**: telas, categorias de Ajustes, ações (gravar, pausar, destacar, painel do Obsidian), aulas em
  andamento e salvas. Comando novo? Acrescente em `palCommands()` chamando uma função que já existe.

**Pontos de quebra.** 1180 (Início em 2 colunas), 1100 (painel de contexto e colunas da Nova aula descem), 900 (busca
só com o ícone, Ajustes com categorias em linha), 760 (rail sem rótulos, uma coluna), 640 (abas da fonte só com ícone).
A janela mínima é 520 × 560. Use `grid`/`flex` com `minmax(0, 1fr)`; nada de largura fixa em conteúdo.

**Barra flutuante.** Os tamanhos são contrato com `launcher/WidgetForm.cs` e com os testes: aberta 304 × 252, com a
nota 360 × 440, alça 12 × 84 (84 × 12 em cima/embaixo), cantos de 18 e fundo = `BackColor` (`--bg-base`). Mudou algum?
Mude o C# e os testes (`DesktopChecks.cs`, `widget_ui.py`) junto. A janela da nota tem a barra de 46 px
(`NoteForm.Bar`).

## Padrões de UX

- **Ações destrutivas** (descartar gravação, limpar dados, desconectar): `ui.confirm(texto, { danger: true })`, com o
  foco no Cancelar. Nada reversível pede confirmação.
- **Erros** dizem o que houve e o que fazer, com o botão da ação quando existe (Tentar novamente, Retomar, Escolher
  outro cofre). Códigos técnicos só no log.
- **Gravar ≠ parar ≠ descartar:** o principal é vermelho e vira quadrado ao gravar; pausar/retomar é secundário (âmbar
  quando pausado); descartar é `danger` com lixeira e confirmação. Cada controle tem rótulo visível.
- **Processamento** mostra as etapas reais da tarefa (`#stages`), a etapa que falhou e o progresso real, ou o
  indeterminado quando não há percentual; nunca um número inventado.
- **Textos:** português natural, rótulos curtos, “Ajustes” (não “Configurações”), “Integrações” para Notion e Obsidian.
  Explicação longa vai para dica, `details` ou a documentação.
- **Atalhos** aparecem na dica (`data-kbd`): Ctrl+K, Ctrl+Enter, Ctrl+Shift+D, Ctrl+Alt+P.

## Movimento

Hover e press em `--dur-fast`, entrada de painel e modal em `--dur-normal` com `--ease-emphasized`, troca de estado do
gravador em ~340 ms. Sem `cubic-bezier` de ricochete. Animações infinitas só para o que acontece de verdade (gravando,
processando, sincronizando); `prefers-reduced-motion` desliga todas (regra no fim de `ui.css`). Não anime blur, sombra
grande ou layout.

## Acessibilidade

- Foco visível em tudo (`:focus-visible`, anel `--border-focus`); alvo de clique ≥ 24 px (os botões têm 28–34).
- Botão só com ícone: `aria-label` + `data-tip`. Status com `role=status`/`aria-live`. Abas com `role=tab` e setas.
- Contraste garantido pelos tokens (teste). Texto sobre vidro só nos níveis com fundo quase opaco.

## Tela nova: checklist

1. Use os componentes de `ui.css`; se faltar um, crie no `ui.css` (com token) e mostre no `/design`.
2. Uma ação principal; o resto secundário ou fantasma. Estado com ícone + texto.
3. Vazio, carregando e erro desenhados (não só o caso feliz).
4. Funciona em 520 × 560 e em 1920 × 1040, e de 80% a 120% de zoom.
5. Acrescente o cenário em `tests/ui_shots.py` (`SCENARIOS`), rode e **olhe** as imagens em
   `tests/desktop-artifacts/ui/`: `py -3.14 tests\ui_shots.py <nome> --sizes --zoom`. Se a tela entra no fluxo de uma
   aula, acrescente a etapa ao percurso de ponta a ponta (`py -3.14 tests\ui_shots.py --walk`).
6. `.venv\Scripts\python -m unittest tests.test_ui_tokens` (contraste e cores soltas).
