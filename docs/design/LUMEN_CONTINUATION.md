# Lúmen Glass 2026 — como continuar

Leia nesta ordem: este arquivo → `LUMEN_IMPLEMENTATION_STATUS.md` → `LUMEN_REFERENCE_MANIFEST.md` (não é preciso reabrir as 38 imagens: estão catalogadas; as
folhas de leitura ficam em `D:\Lumen\glass-20261111\folhas\folha-01..19.png`).

## Estado em 14/11/2026 (5ª sessão — concluída; LEIA PRIMEIRO)

- **Última interface concluída:** menu de modo/esforço do Cérebro (R36). Na mesma sessão: Análise › Salvar (R02), Salvos (R08), Monitor (R25).
- **Último checkpoint:** tag `LUMEN_GLASS_2026_FASE11` (antes dela: `FASE10` = 4ª sessão; `FASE11_WIP` = meio da 5ª).
- **Testes de 14/11:** `glass_ui.py` 132/132 (Parte 5 nova); `test_glass` + tokens + temas + barra 103 ok; `study_ui.py` no Glass passou; Clássico: as mesmas
  2 telas com dado assíncrono de sempre (Diagnóstico e Proteção), nenhuma diferença nova; janela real do `Lumen.exe` (`scripts\nativo_s5.ps1`): Monitor com
  dados reais, Salvos vazio e menu de modo. Logs: `D:\Lumen\glass-20261114-s5\logs`. Não rodada: a unidade completa (26 min) — nenhum Python do app mudou.
- **O que falta:** só o que depende de função nova ou do usuário — R24 (sub-abas do Voice Studio), busca/filtros/ordenação dos Salvos (R08), filtros das
  Atividades (R23), e a validação do usuário (gosto, DPI 125/150%, vários monitores, uso real). Nenhuma referência está "não iniciada".
- Armadilha nova: na árvore de acessibilidade do WebView2, botão com `aria-expanded` (Monitor, menu de modo) não aceita `Invoke` — use
  `ExpandCollapsePattern`; aba (`role=tab`) usa `SelectionItemPattern` (ver `Press` em `nativo_s5.ps1`).

### Histórico da 5ª sessão (texto escrito no meio dela, quando o limite de uso a interrompeu)

- **4ª sessão (12/11 à tarde, também interrompida):** Atividades em linha do tempo (R23), Avaliação (R15), PDFs (R21) e Personalização (R26) em cartões,
  Catálogo (R11) e a bandeja da barra (R37) ficaram prontos e testados (`glass_ui.py` 120/120, Clássico com 0 diferenças fora das 2 assíncronas de sempre),
  mas sem documentação. Checkpoint: tag `LUMEN_GLASS_2026_FASE10`. O manifesto e o status **ainda não refletem** essas telas.
- **5ª sessão (14/11):** só `glass.css` e `tests/glass_ui.py` mudaram. Análise › coluna Salvar (R02: 30% de largura, destinos sem moldura dupla, ícone no botão),
  lista de Salvos (R08: faixas de vidro com ladrilho), Monitor (R25: cabeçalho à esquerda, ladrilho + filete + valor grande, painel rola em janela baixa) e
  menu de modo/esforço (R36: título à esquerda, cartão de descrição com ladrilho). Conferidos por captura em 1568×1003, 1100×760 e 820×700
  (`D:\Lumen\glass-20261114-s5\ui`). Checkpoint: tag `LUMEN_GLASS_2026_FASE11_WIP`.
- **(JÁ FEITO depois da retomada, ver acima)** Lista do que faltava naquele momento: 1) rodar `py -3.14 tests\glass_ui.py` — a **Parte 5 é nova e nunca rodou**; corrigir o que falhar;
  2) `test_glass` + tokens + temas + barra; 3) `LUMEN_TEST_UI_STYLE=glass py -3.14 tests\study_ui.py`; 4) `estilos_classico.py` (Clássico com 0 diferenças);
  5) janela real (`nativo_s4.ps1`); 6) atualizar manifesto, status, QA e `docs/DECISOES.md`; 7) tag `LUMEN_GLASS_2026_FASE11`.
- Capturas com dados de mentira para Salvos e Monitor: `py -3.14 D:\Lumen\glass-20261114-s5\scripts\shots.py <saida> --style glass sav-itens mon-dados`.
- Busca, filtros por tipo e ordenação dos Salvos (R08) e o subtítulo/ladrilho do cabeçalho do menu (R36) não foram desenhados: não existem no Lumen.

## Estado em 12/11/2026

- **Última interface concluída:** Configurações da IA (ladrilho por cartão e ícone por linha nas 15 seções; estado vazio ilustrado em Projetos). Referências: R11–R26.
- **Na mesma sessão:** resultado "Material processado" (R05), Ajustes da barra flutuante (R35), Capas do Notion (R27), Proteção do cérebro (R30), Diagnóstico (R33).
- **Último checkpoint:** tag `LUMEN_GLASS_2026_FASE9`.
- **Próxima tarefa:** Atividades em linha do tempo (R23), com registros de teste — ver "Prioridade do que falta" em `LUMEN_REDESIGN_MASTER_PLAN.md`.
- **Problemas pendentes conhecidos:** nenhum defeito aberto. Parciais: R02, R08, R11, R15, R21, R23, R24, R25, R26, R36; a barra (R37) não foi alterada.
  No Clássico, os Ajustes da barra em cima/embaixo cortam "Proteção do cérebro" e "Privacidade e dados" (defeito antigo; o Glass corrige, o Clássico ficou como estava).

## Onde as coisas estão

- Código: `lumen/web/glass.css` (tudo sob `:root[data-ui="glass"]`), `lumen/web/glass.js` (`window.Glass`: hero, journey, system, source, library, aiSection, result, apply),
  ganchos `window.Glass?.…` em `app.js` e `study-settings.js`, peças `.g-only` em `index.html`, bloco Glass no fim dos Ajustes da barra em `widget.css`.
- O estilo chega no `<html data-ui>` de `/`, `/widget` e `/note` (`server._page_marks`); a barra e a nota acompanham a troca pela leitura de `/api/widget` (`ui`).
- Regras: `docs/DESIGN.md` ("Lúmen Glass 2026"), `LUMEN_DESIGN_SYSTEM.md`, decisões D161–D174 (`docs/DECISOES.md`).
- Evidências: `D:\Lumen\glass-20261110\` (1ª sessão), `D:\Lumen\glass-20261111\` (2ª) e `D:\Lumen\glass-20261111-s3\` (3ª: `ui`, `logs`, `scripts`).

## Checkpoints e restauração

| Nome | O quê | Onde |
|---|---|---|
| `PRE-LUMEN-GLASS-2026` | antes de qualquer Glass | tag git + `D:\Lumen\restauracao\glass-20261110` |
| `LUMEN_GLASS_2026_BASELINE` | Glass da 1ª sessão, antes do Super Redesign | tag git + `D:\Lumen\restauracao\glass-baseline-20261111` |
| `LUMEN_GLASS_2026_FASE7` | depois das telas de 11/11 | tag git |
| `LUMEN_GLASS_2026_FASE8` | resultado, barra, Capas, Proteção, Diagnóstico | tag git |
| `LUMEN_GLASS_2026_FASE9` | + Configurações da IA e documentação de 12/11 | tag git |

Voltar sem mexer em arquivo: Ajustes → Aparência → **Clássico** (a barra e a nota voltam junto). Um arquivo só: `git checkout <tag> -- caminho`. Todos os arquivos de
antes do Glass: `py -3.14 -I verificar.py --origem | --restaurar` na pasta da restauração (não apaga arquivos novos). Nunca `git reset --hard`/`clean`/`stash`
(há código fora do git). As tags são commits de snapshot feitos com índice temporário (`D:\Lumen\glass-20261111-s3\scripts\checkpoint.sh`): o branch `estudos` e as
alterações locais não foram tocados; nenhum commit no branch.

## Como trabalhar

1. Capturas (mundo simulado + servidor real isolado): `py -3.14 D:\Lumen\glass-20261111-s3\scripts\shots.py <saida> --style glass [--size LxA] <filtro>`.
   Cenários: `res-*` (resultado), `cov-*` (Capas), `prot-*` (Proteção com estados de mentira), `diag-pronto`, `ia-*`/`ia2-*` (Configurações da IA), `aj-*`, `cb-*`…
   Barra e nota: `shots_widget.py` (gera também a ampliação `@3x`). Janela real: `powershell -File scripts\nativo_s3.ps1` (dados isolados numa pasta nova).
2. Testes, sempre com `TEMP=TMP=D:\Lumen\t\tmp` (o C: tem pouco espaço) e `PYTHONIOENCODING=utf-8`:
   `.venv\Scripts\python -m unittest tests.test_glass tests.test_ui_tokens tests.test_widget`; `py -3.14 tests\glass_ui.py`;
   `LUMEN_TEST_UI_STYLE=glass py -3.14 tests\study_ui.py`; `scripts\estilos_classico.py` (o Clássico tem que dar 0 diferenças de estilo); se mexer em Python,
   `.venv\Scripts\python -m unittest discover -s tests -t .` (26 min).
3. Armadilhas: `:is()` com pseudo-elemento invalida a regra; regras tardias do `app.css` centralizam títulos (alinhar explicitamente); `wait_for_function` só com
   `() =>` (CSP); cabeçalho decorativo com o nome de um título quebra `get_by_role` (use `aria-hidden`); grade de duas colunas precisa do ponto de quebra de 900 px;
   nada que mova elemento sem desfazer no Clássico; **classe nova em elemento existente aparece na comparação do Clássico** (use `:has()` ou atributo);
   no Git Bash, heredoc com acento ou aspas quebra — escreva o script num arquivo; a árvore de acessibilidade do WebView2 só existe depois da primeira consulta
   (`FindAll` uma vez antes de procurar botões); na comparação do Clássico, o selo do Voice Studio e o resultado do Diagnóstico variam por serem dados assíncronos.

## Desfecho da sessão de 12/11

- Unidade completa 1084 ok; `test_glass` + tokens + temas + barra 100 ok; `glass_ui.py` 96/96; `study_ui.py` no Glass 33/33; Clássico: 0 diferenças de estilo em 97 230 elementos.
- Janela real: Ajustes, Capas, Diagnóstico e Proteção capturadas (`D:\Lumen\glass-20261111-s3\ui\nativo\`).
- Logs: `D:\Lumen\glass-20261111-s3\logs\`.
