# Lúmen Glass 2026 — status da implementação

Atualizado em 12/11/2026. Status por referência: `LUMEN_REFERENCE_MANIFEST.md`. Nenhum commit no branch `estudos`; checkpoints são tags de snapshot + cópias em `D:\Lumen\restauracao`.

## Concluído

| Sessão | Entrega |
|---|---|
| 10/11 | Estilo reversível `ui_style` (classic \| glass), `glass.css`/`glass.js`, shell (barra de título do Windows, barra lateral, Pomodoro em cartão), Início, Nova aula › Fonte, Biblioteca, Cérebro › Conversar, Integrações em duas colunas, testes `test_glass.py`/`glass_ui.py`, prova do Clássico idêntico, validação na janela real do `Lumen.exe` |
| 11/11 | Leitura das 38 referências e manifesto; componentes compartilhados (cabeçalho de seção com ladrilho, grupo, linha, cartão de opção, varredura de luz); **Ajustes** com cabeçalho de seção e um cartão por grupo; **Configurações da IA** em duas colunas; Cérebro › **Salvos/Fontes/Estudar**; **Minha compreensão** e **Análise**; **Integrações** (R24); **painel do Pomodoro**, **Monitor** e **menus do composer** |
| 12/11 | **Resultado "Material processado"** (R05) em cartões por destino; **barra flutuante › Ajustes** em ladrilhos (R35) com a barra e a nota acompanhando o estilo; **Capas do Notion** (R27) com a trilha de 3 passos; **Proteção do cérebro** (R30); **Diagnóstico** (R33); **Configurações da IA** com ladrilho por cartão e ícone por linha nas 15 seções (R11–R26) e estado vazio ilustrado em Projetos (R19) |

## Última interface concluída

Menu de modo/esforço do Cérebro (R36), em 14/11. Antes dele, na mesma sessão: Análise › Salvar (R02) → Salvos (R08) → Monitor (R25).
Na 4ª sessão (12/11 à tarde): Atividades (R23) → Avaliação (R15) → PDFs (R21) e Personalização (R26) → Catálogo (R11) → bandeja da barra (R37).
Na 3ª (12/11): Configurações da IA (componente compartilhado `aiCards`); antes: Diagnóstico → Proteção → Capas → barra › Ajustes → resultado.

## Arquivos alterados em 12/11

| Arquivo | O quê |
|---|---|
| `lumen/server.py` | `_page_marks` também em `/widget` e `/note`; `/api/widget` devolve `ui` (o estilo) |
| `lumen/web/app.js` | resultado: `obsidianParts`, `visualFacts` (os mesmos textos, compartilhados com o Glass), `data-tier` nos botões, gancho `Glass.result`; **correção**: resultado sem visualização mostrava o texto "null" (também no Clássico) |
| `lumen/web/glass.js` | `result` (cartões do resultado), `settingsArrange` (`[data-g-group]`, `[data-g-free]`, ladrilho do Diagnóstico), `aiCards` (ícones dos cartões e linhas das Configurações da IA) |
| `lumen/web/glass.css` | blocos "Salvar › resultado", "Capas do Notion", "Proteção do cérebro", "Diagnóstico do sistema", cartões/linhas das Configurações da IA, estado vazio ilustrado, pontos de quebra de 900 px |
| `lumen/web/index.html` | `#g-run-sub`; Capas: trilha `.g-cov-steps`, cabeçalho `.g-cov-head`, cartão `.g-cov-how`, `data-g-group`/`data-g-free` |
| `lumen/web/widget.html`, `note.html`, `widget.js`, `note.js`, `widget.css` | `data-ui` no `<html>`, troca ao vivo pela leitura de `/api/widget`, bloco Glass dos Ajustes da barra |
| `tests/glass_ui.py`, `tests/test_glass.py` | resultado, Capas, Diagnóstico, barra e nota, disposição das telas novas em 7 tamanhos |
| `docs/design/*` | este conjunto |

Nada em C#, dados, credenciais ou integrações. `protection.js` e `study-settings.js` não mudaram em 12/11.

## Componentes compartilhados (onde reutilizar)

- Cabeçalho de seção com ladrilho: `.g-sec-head` + `.g-sec-ico` (Ajustes, Diagnóstico) e `.st-section-head` (Cérebro).
- Grupo em cartão: `.g-group`; começa em `h3.eyebrow` ou `[data-g-group]`; `[data-g-free]` fica solto entre cartões (`settingsArrange`).
- Ladrilho de ícone: `.g-tile-ico` (46 px), `.g-card-ico` (cartão das Configurações da IA), `.g-row-ico` (linha), `.protection-emblem`/`.run-ico` (62 px, com tom).
- Painel interno (um degrau acima do cartão): `.g-dest`, `.g-vis`. Lista de fatos: `.g-facts`. Trilha de passos: `.g-cov-steps`.
- Linha com filete (Configurações da IA) × linha em cápsula (Ajustes): `.st-set-card .set-row` × `.g-group .set-row`.

## Parcial / pendente

Em 14/11 nenhuma referência está parcial por falta de desenho. O que resta depende de função nova ou do usuário: sub-abas do Voice Studio (R24), busca, filtros e
ordenação dos Salvos (R08), filtros das Atividades (R23) e a validação do usuário. Ver "Prioridade do que falta" em `LUMEN_REDESIGN_MASTER_PLAN.md`.

## Testes (12/11, com `TEMP=TMP=D:\Lumen\t\tmp`)

| Teste | Resultado |
|---|---|
| Suíte de unidade completa (`unittest discover`, depois da mudança no servidor) | 1084 ok (26 min) |
| `unittest tests.test_glass tests.test_ui_tokens tests.test_themes tests.test_widget` (no fim) | 100 ok |
| `py -3.14 tests\glass_ui.py --shots` | 96/96 (resultado, Capas, Diagnóstico, barra e nota; 7 tamanhos; redimensionamento contínuo) |
| `LUMEN_TEST_UI_STYLE=glass py -3.14 tests\study_ui.py` | 33/33 (`"passed": true`), repetida depois do último ajuste do `aiCards` (`logs\study_ui-glass-2.txt`) |
| `py -3.14 tests\widget_ui.py` (barra flutuante, Clássico) | OK (alças, painéis em cima/embaixo, gravação/parada, ajustes) |
| `py -3.14 tests\protection_ui.py` (Proteção, Clássico) | `"passed": true`, 49 verificações |
| Clássico idêntico (`D:\Lumen\glass-20261111-s3\scripts\estilos_classico.py`) | 97 230 elementos × 39 propriedades em 51 telas/estados (agora com o resultado, as Configurações da IA e as Capas com prévia): 0 diferenças de estilo. Variam só dados assíncronos: o ícone do selo do Voice Studio (`#vs-badge`) e o resultado do Diagnóstico, que é calculado em cada árvore de código |
| Janela real do `Lumen.exe` (`scripts\nativo_s3.ps1`, dados isolados, sem credenciais) | Ajustes, Capas, Diagnóstico e Proteção capturadas com `PrintWindow` em 1568 × 1003 |

Não executado em 12/11: medição de desempenho (quadros ao rolar), escala 125/150% e vários monitores; as suítes da barra e da Proteção rodam no Clássico
(no Glass, a barra é coberta pela Parte 4 do `glass_ui.py` e a Proteção só por captura).

## 4ª e 5ª sessões (12/11 à tarde e 14/11)

Arquivos: `lumen/web/glass.css`, `glass.js`, `study-settings.js`, `widget.css`, `icons.svg` (ícones `thumb` e `bars`), `tests/glass_ui.py`, `tests/test_glass.py` na 4ª;
só `lumen/web/glass.css` e `tests/glass_ui.py` (Parte 5) na 5ª. Tags: `LUMEN_GLASS_2026_FASE10` e `LUMEN_GLASS_2026_FASE11`.

| Teste (14/11, com `TEMP=TMP=D:\Lumen\t\tmp`) | Resultado |
|---|---|
| `.venv\Scripts\python -m unittest tests.test_glass tests.test_ui_tokens tests.test_themes tests.test_widget` | 103 ok |
| `py -3.14 tests\glass_ui.py` | 132 verificações ok, 0 falhas (Parte 5: Análise, Salvos, Monitor e menu de modo, nos dois estilos) |
| `LUMEN_TEST_UI_STYLE=glass py -3.14 tests\study_ui.py` | `"passed": true` |
| Clássico idêntico (`estilos_classico.py`) | 57 telas/estados, 112 902 elementos: só as 2 telas de sempre variam (Diagnóstico e Proteção, dados assíncronos); nenhuma diferença nova |
| Janela real do `Lumen.exe` (`D:\Lumen\glass-20261114-s5\scripts\nativo_s5.ps1`, dados isolados, sem credenciais) | Monitor (dados reais do hardware), Salvos vazio e menu de modo capturados em 1568 × 1003 |

Não executado em 14/11: unidade completa (nenhum Python do app mudou), desempenho, escala 125/150%, vários monitores; a Análise e os Salvos com itens só foram vistos
no mundo simulado (a janela real isolada não tem aulas nem itens salvos).
