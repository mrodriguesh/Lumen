# Lúmen Glass 2026 — design system

Tudo vive em `lumen/web/glass.css` (regras só sob `:root[data-ui="glass"]`) e `lumen/web/glass.js`. O Clássico não usa nada daqui. Regras gerais e testes: `docs/DESIGN.md`
("Lúmen Glass 2026"). Este arquivo é o catálogo dos componentes compartilhados; as telas só os posicionam.

## Tokens

| Grupo | Tokens |
|---|---|
| Paleta (só sobre o tema padrão) | `--bg-base #0b0d12`, `--bg-elevated #111318`, `--surface-1/2/3`, `--text-primary #f1f2f6`, `--text-secondary #a8aebb`, `--accent #4c69ee` (o #5571EF, ajustado para 4,5:1), `--accent-strong #7488f5` |
| Materiais | `--g-fill` (Glass Panel), `--g-fill-raised` (Glass Elevated/Interactive), `--g-fill-structural` (Glass Shell: barra lateral, navegação de ajustes), `--g-fill-floating` (Glass Floating), `--g-specular` (reflexo), `--g-edge` (borda óptica), `--g-sweep` (varredura de luz azul no canto, para cabeçalhos e flutuantes), `--g-hi`/`--g-hi-strong` (filete interno), `--g-shadow`/`--g-shadow-float` |
| Linhas | `--g-line-soft`, `--g-line`, `--g-line-strong` |
| Estados | `--g-hover`, `--g-press`, `--g-sel`, `--g-accent-glow` |
| Tipografia | Segoe UI Variable (Display nos títulos); `--g-fs-greet 38`, `--fs-display 32`, `--g-fs-sec 28`, `--fs-h2 19`, `--fs-body 15`, `--fs-sm 14`, `--fs-label 13.5` |
| Geometria | `--g-r-card 20`, `--g-r-ctl 12`, ladrilho 58 (46 em janela estreita), `--g-rail-w 176`, `--g-pomo-w/h` |
| Movimento | `--ease-*` = `cubic-bezier(.23,1,.32,1)`, `--g-ease-move`, `--dur-fast 120`, `--dur-normal 200`, `--g-dur-press 120` |
| Ícones em CSS | `--g-ico-brain`, `--g-ico-check` (data URI; o resto vem do sprite `icons.svg`) |

## Materiais (nomes do pedido → implementação)

| Material | Onde | Como |
|---|---|---|
| Glass Shell | barra lateral, navegação de Ajustes, histórico do Cérebro | `--g-fill-structural` + filete, sem blur |
| Glass Panel | `.card`, `.g-group`, `.st-set-card` | `--g-specular` + `--g-fill` + `::before` com `--g-edge` (máscara) + `--g-shadow` |
| Glass Elevated | ladrilhos, botões, `.g-stat`, `.g-tile` | `--g-fill-raised` + `--g-hi(-strong)` |
| Glass Interactive | botões, campos, cartões de opção, abas | transições de cor 120 ms, pressão `scale(.95–.98)`, selecionado em azul translúcido |
| Glass Floating | menus, painel do Pomodoro, Monitor, diálogo, aviso, dica | `--g-fill-floating` + `--g-sweep` + `backdrop-filter` (só aqui) |
| Glass Subtle | linhas internas (`.set-row`), fatos, avisos | `color-mix(bg-base 30–34%)` + `--g-line-soft` |

## Componentes

| Componente | Marcação | Notas |
|---|---|---|
| Cabeçalho de seção | `header.g-sec-head` > `span.g-sec-ico` + `h2` + `p.g-sec-sub` (Ajustes e Config. IA, criado por `glass.js`); `.st-section-head`, `.st-lrn-head` (Cérebro, ladrilho por CSS) | título 28, subtítulo 15; reserva o espaço do Pomodoro à direita |
| Grupo | `div.card.g-group` (Ajustes: `glass.js` embrulha o `h3.eyebrow` e o que vem depois; desfaz no Clássico); `.st-set-card` | o `h3` vira título do cartão |
| Linha de ajuste | `.set-row` dentro de grupo | cápsula sutil, título 15/600, descrição 13,5 |
| Cartão de opção | `.segmented.wide > label` em painel de ajustes; `.pomo-presets > button` | marcador redondo no canto; escolhido = borda azul + anel + check |
| Navegação de ajustes | `.settings-nav` | painel estrutural, item ativo em vidro claro; vira faixa abaixo de 900 px |
| Lista de integrações | `#integ-tabs` (≥ 1180 px) | cartão único com título, linhas com estado em pílula |
| Fonte da aula | `.g-src-opt[aria-pressed]` | aciona as abas reais |
| Número | `.g-stat` | filtra ao clicar |
| Árvore | `.g-tree-row`, `details.g-tree-group` | Biblioteca |
| Passos | `.g-steps`, `.g-flow-steps`, `.stepper` | sem pulso |
| Pomodoro | `.g-pomo-lane .pomo` (cartão) e `.pomo-sheet` (painel) | `--g-ring` define o anel |
| Controles de janela | `.g-winctl .g-win[data-g-window]` | só na moldura do `Lumen.exe` |

## Regras

1. Cor só por token; nenhuma cor fora do bloco da paleta (`tests/test_glass.py`).
2. `backdrop-filter` só em flutuantes pequenos; nunca em cartão, barra lateral, área de trabalho ou elemento sticky.
3. Nada infinito sem motivo; reduzir movimento mantém só fades curtos nos flutuantes.
4. Peça nova só do Glass: `.g-only` no HTML ou criada por `glass.js`; mover elemento existente exige desfazer no Clássico (e teste da ordem).
5. Nenhuma função inventada para imitar a referência.

## Componentes acrescentados em 12/11/2026

| Componente | Classe | Onde | Regra |
|---|---|---|---|
| Painel interno | `.g-dest`, `.g-vis` | resultado da aula | um degrau acima do cartão: preenchimento elevado, filete claro no alto, sombra de contato curta; nunca um painel interno dentro de outro |
| Lista de fatos | `.g-facts` | resultado | ícone 20 px + texto 16/22; linha de aviso em âmbar (`data-warn`) |
| Ladrilho de ícone | `.g-tile-ico` (46), `.g-card-ico` (46, cartão), `.g-row-ico` (40, linha), `.g-dest-logo` (40) | Capas, Configurações da IA, resultado | borda `--g-line-strong`, preenchimento elevado, ícone na cor de destaque; sempre decorativo (`aria-hidden`) |
| Ladrilho com tom | `.run-ico`, `.protection-emblem`, `.diag-hero-info::before` (62–66) | resultado, Proteção, Diagnóstico | verde = concluído, âmbar = atenção, vermelho = falha; o tom vem do estado real (`data-tone`) |
| Trilha de passos | `.g-cov-steps` | Capas | passo atual em pílula com borda de destaque; feitos com visto verde; espelha o estado por CSS, sem JavaScript |
| Linha com filete | `.st-set-card .set-row` | Configurações da IA | sem cápsula; filete `--g-line-soft`; com ícone, recuo de 56 px (linha sem ícone continua alinhada) |
| Linha em tabela | `.protection-step`, `.diag-item-row` | Proteção, Diagnóstico | nome em negrito numa coluna de até 270 px, detalhe ao lado, estado em selo à direita |
| Ações em duas fileiras | `#run-actions [data-tier]` | resultado | destinos em cima (iguais, largos), o resto embaixo; a quebra é um pseudo-elemento |
| Ladrilho de categoria (barra) | `.prefs-menu button` no Glass | barra › Ajustes | 23 px de altura, 10 px, nome inteiro; toque com `scale(.97)` em 120 ms |
| Estado vazio ilustrado | `.st-set-card > .empty` | Projetos | o ícone vira uma pasta de vidro com uma segunda folha girada 6° e luz por baixo; o texto não muda |

Movimento novo: a chegada do resultado (uma vez por aula) entra em cascata curta — opacidade + 8 px, 280 ms, 50 ms entre seções, `--ease-out`, só com
`prefers-reduced-motion: no-preference` e sem bloquear o clique. Nada mais ganhou animação: as telas de Ajustes são vistas muitas vezes e trocam na hora.
