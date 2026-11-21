# Estudar: reorganização da aba (08/11/2026)

Aba **Estudar** do Cérebro (Estudos). Escopo: navegação interna, apresentação, formulários, estados e testes. Algoritmos de revisão, avaliação e geração, rotas, contratos, dados e identificadores internos **não mudaram**.
Decisões: D121 a D126 em `LUMEN_STUDY_AI_DECISIONS.md`. Regras visuais: seção "Estudar" de `docs/DESIGN.md`.

## 1. O que mudou, em uma frase

De um formulário único com um seletor de nove opções, quatro blocos empilhados e uma lista corrida, para **três níveis, uma tela por vez**: **Início → Objetivo → Atividade**, com cada uma das 12 funções num único lugar, a dois cliques do início, e com rascunhos, resultados e sessões que **não se perdem** ao navegar.

## 2. Diagnóstico (antes), com medidas

Medido na interface antiga restaurada, com os mesmos dados semeados (`tests/estudar_ui.py`, modo `before`; dados temporários, nunca o banco pessoal). Capturas em `D:\Lumen\estudar-20261108\ui\antes\`.

| Medida | Antes | Depois |
|---|---|---|
| Altura da aba, vazia (1440×900) | 1,28 tela | **0,63** |
| Altura com dados (1440×900) | 2,56 telas | **1,10** |
| Altura com dados (520 px) | 3,02 telas | **1,44** |
| Botões visíveis (vazia → com dados) | 14 → 42 | **4 → 14** |
| Campos visíveis no início | 7 (de 6 formulários ao mesmo tempo) | **0** |
| Cards fixos | 4 | **0** |
| Rascunho sobrevive a trocar de aba | **não** | sim |
| `S.practicing` depois de trocar de aba no meio do treino | preso em `true` (sem sessão) | consistente com a sessão |
| `GET /api/study/practice` ao abrir a aba | a cada abertura | só na 1ª abertura do Treino falado |

Problemas confirmados (todos reproduzidos):

1. O seletor de nove tipos era uma lista longa quebrando linha, ocupando o topo e competindo com o resto.
2. Criar, revisar, praticar e planejar tinham o mesmo peso visual; a revisão pendente ficava num card igual aos outros e o "Começar revisão" aparecia depois do formulário.
3. Quatro formulários e blocos ao mesmo tempo (Criar, Revisão de hoje, Explique com suas palavras, Treino falado) e uma lista de até 30 itens corrida.
4. Texto explicativo permanente em cada bloco; cards grandes com borda repetida.
5. **Cada clique em "Estudar" reconstruía a aba**: perdia o rascunho do Feynman, a conversa do Treino falado (sem avisar) e o resultado aberto.
6. Validação só por aviso solto no topo; o campo de projeto do Plano de ação aparecia **depois** do botão Criar.
7. A revisão capturava o teclado (Espaço, 1 a 4) mesmo escondida; cenários e vozes do Treino falado eram buscados a cada render; cada material de áudio aberto acrescentava um ouvinte global de `lumen-audio`.
8. Plano de estudos e Plano de ação tinham o mesmo ícone.

## 3. A organização nova

```
Estudar (início)
├─ Próxima atividade  ........ revisão pendente (contagem + "Começar revisão") ou uma linha calma
│                              + "Em andamento" (revisão ou Treino falado) + assuntos que vale rever
├─ Escolha um objetivo
│   ├─ Revisar     → Revisão de hoje · Flashcards · Revisão em áudio
│   ├─ Praticar    → Questionário · Prática com correção · Explique com suas palavras · Treino falado
│   ├─ Planejar    → Plano de estudos · Plano de ação · O que falta estudar
│   └─ Visualizar  → Mapa mental · Mapa de conhecimento
└─ Materiais recentes ........ 5 linhas compactas; "Ver todos" na própria tela (até 30)
```

Cada **atividade**: voltar (diz para onde), título, uma linha, campos essenciais com rótulo visível, "Mais opções" recolhido, **uma** ação principal, "Como funciona" recolhido. O resultado abre na própria atividade; "Criados antes" lista só os do tipo.

## 4. Mapa de funções: antes → depois

Nenhuma função saiu nem foi escondida em "Outros". O identificador interno (`kind`) é o mesmo de sempre.

| Função | Antes | Depois (início → …) | `kind` / contrato |
|---|---|---|---|
| Revisão de hoje | card fixo no alto, com "Começar revisão" | **Próxima atividade** no início; ou Revisar → Revisão de hoje | `/api/study/due`, `/review` (SM-2) |
| Revisões dos planos | botões dentro do card | Revisar → Revisão de hoje (lista) e atalho no início | `/due` → `plans` |
| Assuntos para revisar (modelo do estudante) | chips no card | início (até 4) e Revisão de hoje | `/due` → `topics` |
| Flashcards | 1º dos nove tipos do seletor | Revisar → Flashcards | `flashcards` |
| Revisão em áudio | seletor | Revisar → Revisão em áudio | `audio` |
| Questionário | seletor | Praticar → Questionário | `quiz` · `/api/study/quiz` |
| Prática com correção | seletor | Praticar → Prática com correção | `exercise` · `/api/study/applied` |
| Explique com suas palavras | card próprio | Praticar → Explique com suas palavras | `/api/study/feynman` |
| Treino falado | card próprio | Praticar → Treino falado | `/api/study/practice` |
| Plano de estudos | seletor | Planejar → Plano de estudos | `plan` |
| Plano de ação | seletor (+ projeto depois do botão) | Planejar → Plano de ação (projeto **antes** do botão) | `action` · Pomodoro |
| O que falta estudar | seletor | Planejar → O que falta estudar | `gaps` |
| Mapa mental | seletor | Visualizar → Mapa mental | `mindmap` |
| Mapa de conhecimento | seletor | Visualizar → Mapa de conhecimento | `map` |
| Materiais criados | lista corrida de 30 | Materiais recentes (5) e "Criados antes" por tipo | `/api/study/items`, `/item` |
| Abrir material vindo do chat ou de Salvos | `openItem` | `openItem` (mesmo contrato), abre na atividade do tipo | — |
| Ctrl+K "Revisar flashcards" | abria a aba | abre direto "Revisão de hoje" | `learnGo("today")` |

Distinções pedidas: **Plano de estudos × Plano de ação** (ícones diferentes; a descrição diz "etapas, pré-requisitos e revisões" × "entregas e prazos no seu projeto") e **Mapa mental × Mapa de conhecimento** ("tópicos e ramos" × "conceitos e como se ligam nas suas notas"); **Questionário × Prática com correção × Explique com suas palavras × Treino falado** têm cada um a sua frase de uma linha e o seu campo.

## 5. Estado, ciclo de vida e teclado

- Cada atividade é montada **uma vez** e fica escondida (`hidden`), não destruída; `renderLearn` é idempotente e só rebusca a revisão pendente e a lista de materiais (D122).
- Rascunho (assunto, explicação, resposta), respostas e correção do questionário, resultado aberto, sessão de revisão e sessão do Treino falado sobrevivem a trocar de objetivo, de atividade e de aba. O início mostra "Rascunho" ou "Em andamento"; o que já foi enviado não conta como rascunho.
- Um ouvinte global de `lumen-audio` e de `lumen-pomodoro` (o foco continua sendo registrado mesmo sem o plano aberto). O atalho da revisão e o microfone por barra de espaço só atuam com a atividade visível; ao sair do Treino falado a fala para.
- Resultado de uma criação lenta nunca é desenhado na atividade errada: vem o aviso "Pronto: …" com "Abrir".
- Foco: título ao entrar; botão de origem ao voltar; clicar de novo em "Estudar" volta ao início.

## 6. Bugs corrigidos (além da reorganização)

1. Rascunho, sessão e resultado perdidos ao clicar em "Estudar" (D122).
2. `S.practicing` preso em `true` sem sessão (bloqueava o microfone do Feynman).
3. Revisão escondida capturando teclas.
4. Cenários e vozes do Treino falado buscados a cada render; ouvinte de `lumen-audio` acumulando.
5. Projeto do Plano de ação depois do botão; validação sem ligação com o campo; aviso sem `role=alert`.
6. Plano de estudos e Plano de ação com o mesmo ícone.
7. Texto de ajuda do Feynman e do Treino usando só placeholder/`aria-label` (agora rótulo visível ligado por `for`/`id`).
8. O selo da aba ("18") entrava no nome da aba ("Estudar 18") e nada avisava que um resultado tinha aberto: agora o nome é "Estudar", a contagem é descrição e há um aviso curto "Resultado aberto: …" (D125).

## 7. Arquivos alterados nesta tarefa

| Arquivo | O que mudou |
|---|---|
| `lumen/web/study-learn.js` | reescrito: casca (início, objetivo, atividade), 12 atividades, estado, foco, erros por campo, ciclo de vida. Os renderizadores de resultado (`deck`, `quiz`, `plan`, `gaps`, mapa, `exercise`, `actionPlan`, `listenView`) são os de antes, com o mesmo contrato. |
| `lumen/web/study.css` | bloco `.st-lrn*` novo; removidas as regras que só o Estudar antigo usava; `!important` do Treino falado trocado por especificidade. |
| `lumen/web/study.js` | clicar na aba já aberta volta ao início; selo da aba só visual, contagem como `aria-description`. |
| `lumen/web/app.js` | Ctrl+K "Revisar flashcards" abre "Revisão de hoje". |
| `tests/estudar_ui.py` (novo) | cenário "depois" com 16 blocos de verificação e capturas; modo `before` (usado uma vez no diagnóstico). |
| `tests/study_ui.py` | os passos de Estudar usam a navegação nova (`learn_go`); nada exige todos os formulários ao mesmo tempo. |
| `docs/DESIGN.md`, `LUMEN_STUDY_AI_DECISIONS.md` (D121–D126), `LUMEN_STUDY_AI_STATUS.md`, `LUMEN_STUDY_AI_CHANGELOG.md`, este relatório | documentação. |

Backend, rotas e dados: **nenhuma alteração**.

## 8. Testes executados agora

Todos nesta sessão, em dados temporários (`LUMEN_DATA` em pasta temporária), nunca no banco pessoal. Logs em `D:\Lumen\estudar-20261108\logs\`.

| O quê | Resultado |
|---|---|
| `node --check` em `study-learn.js`, `study.js`, `app.js` | OK |
| `tests.test_ui_tokens`, `test_study_core`, `test_study_applied`, `test_study_explain`, `test_study_voice`, `test_study_catalog_eval` | **141 testes, OK** (141,8 s; saída só no terminal, sem log próprio; os mesmos testes estão nas suítes completas abaixo) |
| `py -3.14 tests/estudar_ui.py` (novo, 16 blocos de verificação), no código final | **passou** (`logs/estudar-ui-final.log`; capturas em `ui/depois-final/`; execuções anteriores: `estudar-ui-1/2/3.log`) |
| `py -3.14 tests/study_ui.py` (passos de Estudar atualizados), no código final | **passou** (`logs/study-ui-final-2.log`, 131 s). Uma rodada (`logs/study-ui-final.log`) falhou no passo 11 "Pronúncias" (espera de 8 s pelo Voice Studio falso, fora de Estudar) e passou na repetição sem mudança de código; `study-ui-1.log` e `study-ui-2.log` (código quase final) também passaram |
| Suíte completa `unittest discover -s tests -t .`, rodada 1 (`logs/suite-full-final.log`, 964 s) | 971 testes, **970 OK e 1 falha**: `tests.test_protection.Protection.test_file_changes_during_copy_preserves_previous` (módulo herdado; **falha 6 de 20 vezes até isolado**) |
| Suíte completa, rodada 2 (`logs/suite-full-final-2.log`, 1002 s) | 971 testes, **970 OK e 1 falha diferente**: `tests.test_transcribe.SecondOpinion.test_flags_divergence_without_replacing_text` (passa 10 de 10 isolado; depende da VRAM livre real da GPU, 1,79 GB hoje contra o mínimo de 1,0 GB) |

**Leitura honesta da suíte:** nenhuma das duas falhas toca Estudar (nenhum `.py` de `lumen/` foi alterado nesta tarefa, conferido por hash), cada uma passou na outra rodada e as duas dependem de tempo ou de ambiente. Mesmo assim **não declaro a suíte completa "verde"**: são dois testes intermitentes de módulos herdados (proteção e transcrição) que ficam como pendência fora do escopo, sem alteração minha.

O que `tests/estudar_ui.py` comprova (comportamento, não estrutura de HTML): as 12 funções abrem a dois cliques com uma atividade visível por vez e só os campos essenciais; os nove tipos de criação enviam os mesmos campos de antes (`kind`, `topic`, `level`, `application`, `project_id`); validação no campo sem requisição; falha de criação preserva o texto e permite tentar de novo; criação lenta vai para o aviso "Abrir"; rascunhos sobrevivem à navegação; Feynman por texto e voz; questionário mantém resposta e correção; revisão com teclado e progresso; Treino falado com sessão, rascunho, avaliação e `S.practicing`; plano de ação registra o foco do Pomodoro; material recente abre na atividade do tipo; teclado, foco visível, movimento reduzido; 1100/760/520 px sem rolagem horizontal; contraste do texto do início ≥ 4,5.

## 9. Capturas

`D:\Lumen\estudar-20261108\ui\`: `antes\` (interface antiga restaurada), `depois-1\`, `depois-2\`, `depois-3\` e `depois-final\` (execuções; a última é a do código final) e `comparativo\` (antes | depois, gerado de `depois-final`, mesmo tamanho de janela e mesmos dados semeados: vazio, com dados, página inteira, 760, 520, resultado aberto, erro de validação, treino em andamento). Também há uma captura por objetivo, por família de formulário, revisão em andamento, rascunho no início, foco visível e 1100/760/520 px. As capturas originais não foram sobrescritas.

## 10. Janela headless × WebView2

Tudo acima rodou em **Chrome headless** (Playwright), sem GPU, com Ollama e Voice Studio **falsos** e microfone simulado. **Não** foi exercitada a janela nativa WebView2, o executável oficial nem o microfone/voz reais. O código novo só aparece no Lumen aberto depois de **Sair pelo menu e abrir de novo**.

## 11. O que só a sua avaliação visual decide

Não declaro aprovação de design. Conferi com capturas e métricas que: o seletor de nove opções não domina mais, formulários que não se relacionam não aparecem juntos, a revisão tem destaque proporcional, o início não é uma pilha longa, nenhuma função ficou escondida e o caminho de volta é evidente. **Você** decide se o equilíbrio, o tamanho da coluna (880 px) e o tom estão certos. Sugestão de olhar: (1) início com e sem revisão pendente, (2) criar um flashcard e voltar, (3) começar e abandonar uma revisão, (4) Treino falado com a voz real.

## 12. Limitações

- A coluna do Estudar tem largura máxima de 880 px (leitura confortável); em janela larga sobra espaço à direita, de propósito.
- A atividade "Revisão de hoje" abre a sessão no próprio lugar; a sessão de revisão continua sendo única (uma por vez).
- "Rascunho" considera só os campos de texto; arquivos anexados à entrega da Prática ficam no resultado, não no rascunho.
- O teste de criação dos tipos `quiz`, `plan`, `map` e `gaps` usa a resposta semeada no lugar do modelo (o Ollama falso não os gera); o pedido enviado é conferido do mesmo jeito. Os demais passam pelo fluxo real da fixture.
- O limite do servidor (4 criações a cada 10 s) obriga o teste a espaçar as chamadas.

## 13. Reversão

1. Pontos de restauração: `D:\Lumen\restauracao\estudar-20261108\RESTAURAR.md` (copie `arquivos\<caminho>` de volta; `manifesto.json` tem o SHA-256 de cada arquivo; 277 arquivos, 0 divergentes). **Não use** `git reset`, `clean`, `stash` nem `checkout`. `lumen/study` não está no git: só essa cópia (e a de `voz-conversa-20261108`) o preserva.
2. Voltar só a interface do Estudar: restaurar `lumen/web/study-learn.js`, `study.css`, `study.js` e `app.js` da cópia. Backend e dados não precisam voltar (não mudaram).
3. Configuração pessoal: não foi alterada (cópia de `settings.json` na mesma pasta, só por precaução).
4. Evidências: `D:\Lumen\estudar-20261108\` (pode apagar se quiser espaço; as capturas "antes" só existem lá).
