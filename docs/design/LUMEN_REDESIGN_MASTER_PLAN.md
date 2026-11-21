# Lúmen Glass 2026 — plano mestre do redesign

Objetivo: levar todas as telas do Lumen às referências aprovadas (`%USERPROFILE%\Downloads\Lumen Glass 2026`), como **estilo reversível** (Ajustes → Aparência →
Estilo da interface), sem mudar o que o Lumen faz. Arquitetura e decisões: `docs/DECISOES.md` D161–D170; regras: `docs/DESIGN.md`.

## Fases

| Fase | O quê | Situação |
|---|---|---|
| 1 Auditoria | stack (Python + HTML/CSS/JS + WebView2 sem GPU), redesign anterior, testes | feita (10 e 11/11) |
| 2 Referências | 38 imagens lidas; manifesto | feita — `LUMEN_REFERENCE_MANIFEST.md` (reconferida em 12/11: mesmas 38) |
| 3 Design system | tokens, materiais, componentes compartilhados | feita — `LUMEN_DESIGN_SYSTEM.md` |
| 4 Liquid Glass | materiais em camadas sem GPU; blur só em flutuantes | feita |
| 5 Navegação | barra de título do Windows, barra lateral, Pomodoro em cartão | feita |
| 6 Telas principais | Início, Nova aula (4 etapas + resultado), Biblioteca, Cérebro (4 abas), Integrações | feita; parciais: R02 (cartões da análise), R08 (lista de Salvos), R24 (sub-abas inexistentes) |
| 7 Configurações | Ajustes (10 categorias) e Configurações da IA (15 seções) | feita em 12/11: Capas, Proteção, Diagnóstico e o componente de cartão/linha das Configurações da IA; parciais: R11, R15, R21, R23, R26 |
| 8 Flutuantes | painel do Pomodoro, Monitor, menus do composer, Ajustes da barra | feita; a barra em si (R37) já era equivalente e não foi alterada |
| 9 Animações | revisão `review-animations` e `animation-performance` | feita (10/11); em 12/11 só a chegada do resultado (cascata curta, uma vez por aula) e o toque dos ladrilhos da barra |
| 10 Comparação e testes | capturas × referências, suítes | feita para o que está "V"/"Vn" no manifesto |

## Situação em 14/11/2026

Os itens 1 a 5 da lista abaixo foram feitos (4ª sessão: R23, R15, R21, R26, R11, R37; 5ª: R02, R08, R25, e também R36). Restam o 6 (R24, só se virar função),
os filtros/busca que seriam função nova (R08, R23) e o 7 (validação do usuário). A lista fica como registro da ordem seguida.

## Prioridade do que falta

1. **R23 Atividades** em linha do tempo: precisa de registros de teste (a tela só foi vista vazia) e de mexer na tabela de `study-settings.js`.
2. **R15 Avaliação**: contador em destaque, estado vazio com ladrilho e a trilha Avaliar → Registrar → Comparar.
3. **R21 PDFs** e **R26 Personalização** em cartões separados (hoje um cartão por seção); **R11 Catálogo** em colunas.
4. **R02** cartões da análise; **R08** lista de Salvos (com itens); **R25** Monitor (tamanhos e tipografia).
5. **R37** barra: bandeja contínua atrás dos botões e filete entre "Pronto" e o Pomodoro (só no Glass, sem mudar tamanhos — contrato com `launcher/WidgetForm.cs`).
6. **R24** sub-abas do Voice Studio só se virarem função de verdade (hoje são seções).
7. Validação do usuário: gosto, DPI 125/150%, vários monitores, uso real com gravação, backup e Voice Studio.

## Regras que valem para o que falta

- Tudo em `glass.css` sob `:root[data-ui="glass"]` (a barra: bloco Glass do `widget.css`); peça nova só do Glass leva `.g-only`; nada de classe nova em elemento que já existia.
- Nenhuma função, rota ou dado inventado: se a referência mostra algo que o Lumen não tem, registrar no manifesto e não desenhar.
- Cada tela: referência → captura → comparação → `glass_ui.py` → `estilos_classico.py` (Clássico com 0 diferenças de estilo) → checkpoint.
