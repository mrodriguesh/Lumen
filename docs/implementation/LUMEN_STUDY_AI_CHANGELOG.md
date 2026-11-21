# Lúmen Study AI: mudanças

## 15/11/2026 — Modos × esforço: sem troca de modelo no meio do Máximo e sem roteador quando não há o que decidir

- **D180:** `lumen/study/agent.py` resolve o modelo do nível antes de entender (esforço escolhido ou "máximo" por extenso) e o fixa nas etapas em JSON da
  resposta; no Livre com modo e esforço escolhidos, só a heurística. Medido: carga de modelo no Máximo 71,8 → 57,5 s (4b principal) e 84,0 → 43,2 s
  (`qwen3:8b`); Livre + escolhas manuais deixa de chamar o roteador (~2,6 s quente, ~30 s a frio).
- **Testes:** `tests/test_study_routing_matrix.py` (novo, 250 respostas na matriz e 5 casos de borda). Ver STATUS.

## 09/11/2026 — Estudar reorganizada: Início → Objetivo → Atividade, com rascunhos e sessões que não se perdem

- **Navegação (D121):** quatro objetivos (Revisar, Praticar, Planejar, Visualizar) e as 12 funções, cada uma num único lugar a dois cliques do início; início com "Próxima atividade" (revisão pendente com contagem e ação primária, ou uma linha calma), "Escolha um objetivo" e "Materiais recentes" (5, "Ver todos" na mesma tela). Saem o seletor de nove opções, os quatro blocos empilhados e a lista corrida de 30. Identificadores internos (`kind`), rotas, contratos e dados iguais.
- **Estado (D122):** atividades montadas uma vez e escondidas; `renderLearn` idempotente (só a revisão pendente e os materiais são buscados ao abrir a aba); rascunho, resultado, respostas do questionário, sessão de revisão e sessão do Treino falado sobrevivem à navegação; o início mostra "Rascunho" e "Em andamento"; cenários e vozes do Treino falado só na 1ª abertura.
- **Erros e resultados (D123):** validação ligada ao campo (`aria-invalid`, `aria-describedby`, `role=alert`, foco), falha de criação mantém o texto e oferece "Tentar de novo", cada criação tem número de tentativa (resultado antigo nunca é desenhado) e, se a pessoa já saiu da atividade, vem o aviso "Pronto" com "Abrir"; projeto do Plano de ação antes do botão.
- **Ciclo de vida (D124):** um ouvinte global de `lumen-audio` e de `lumen-pomodoro` (o foco continua registrado sem o plano aberto); Espaço/1–4 da revisão e a barra de espaço do microfone só com a atividade visível; a fala para ao sair do Treino falado.
- **Navegação e foco (D125):** "Voltar" diz para onde leva e volta de onde a atividade foi aberta; foco no título ao entrar e no botão de origem ao voltar; clicar de novo em "Estudar" volta ao início; Ctrl+K "Revisar flashcards" abre "Revisão de hoje"; selo da aba só visual com a contagem em `aria-description`; aviso curto "Resultado aberto: …" para leitor de tela.
- **CSS (D126):** bloco `.st-lrn*` escopado em `study.css`; removidas `.st-create`, `.st-kinds`, `.st-create-row`, `.st-review-card`, `.st-review-topics`, `.st-review-head` e o `!important` do Treino falado; ícone do Plano de ação diferente do Plano de estudos.
- **Arquivos:** `study-learn.js` (reescrito), `study.css`, `study.js`, `app.js`, `tests/estudar_ui.py` (novo), `tests/study_ui.py`, `docs/DESIGN.md`, D121–D126, STATUS, este CHANGELOG, `PROMPT_CONTINUAR.md` e `LUMEN_ESTUDAR_REORGANIZACAO_20261108.md`. Backend não mudou.
- **Testes:** `tests/estudar_ui.py` (16 blocos, comportamento e 1440/1100/760/520 px, contraste ≥ 4,5), passos de Estudar de `tests/study_ui.py`, 141 direcionados e suíte completa (ver STATUS). Capturas antes/depois em `D:/Lumen/estudar-20261108/ui/`.
- **Preservado:** configuração pessoal, banco pessoal (todos os testes usam dados temporários), voz, modelos, permissões, perfil adulto, alterações herdadas. Sem commit. Restauração: `D:/Lumen/restauracao/estudar-20261108` e suplementos `...-implementacao-atual` e `...-final`.

## 08/11/2026 — Conversa por voz natural: turno isolado, Livre/Notas de verdade, fim de fala com pausas, interface nova

- **Turno isolado (D107):** `call.Turn` com cancelamento próprio; `_emit`/`_set_state` descartam o turno cancelado; `turn_id` e `seq` em todo evento; `agent.PRE_CANCEL`; consumo da antecipada que acorda a cada 100 ms. Bug reproduzido antes: frases do turno antigo tocavam e apareciam no seguinte.
- **Livre/Notas (D108, D109):** `start`/`set_vault` e `action: "vault"` (`skip_vault`, `vault_sources`, `profile`), fotografia por turno, antecipada descartada se o modo mudou (texto reaproveitado), busca antecipada só com as mesmas fontes (`agent`), comandos de voz curtos e inteiros, Feynman e salvar respeitam o modo, `window.lumenStudy.vault` compartilhado com o chat.
- **Conversa natural (D110, D111, D116, D119, D120):** espera extra de até 0,9 s para frase inacabada e **mesclagem da retomada** (pausa longa no meio da frase vira uma pergunta só, `chats.drop_trailing_user`); histerese do VAD (0,5/0,35); falar por cima também durante "entendi/transcrevendo/pensando"; resposta longa só quando pedida; símbolos lidos como palavras; 1º trecho termina em vírgula; prompt "frases curtas (até uns 12 palavras)"; cronograma `CHUNK_CHARS` que evita voz parada.
- **Histórico e robustez (D112–D114):** a mensagem interrompida guarda o que foi ouvido e `meta.generated` guarda o resto (a conversa mostra "Ver o que a IA já tinha escrito"); microfone que some é reaberto (3 tentativas) ou a chamada termina com mensagem; "Ouvindo" só com áudio chegando; reenvio por `?since=seq`; erro de síntese ou de saída vira aviso; aquecimento da 1ª síntese e do Parakeet; "ainda preparando" após 6 s; novas etapas nos tempos (`agent_prep_ms`, `search_ms`, `gap_max_ms`, `complete_ms`, `ready_ms`…).
- **Interface (D115):** `study-call.js`/`study.css` refeitos (orbe único, estado em texto, Livre | Notas, mudo/interromper/encerrar, pílula), ícones `mic` e `mic-off`, botão de entrada novo, opção `call_first_quality` em Configurações → Voz (desligada por padrão), `docs/DESIGN.md`.
- **Não mudou (D117):** motor, voz, semente e passos de uso. Medido e descartado: aparar o silêncio das frases. Medido e deixado como opção: 8 passos só no 1º trecho.
- **Instrumentos:** `bench/call_bench.py` (diretório único por execução; comandos `turns`, `realtime`, `probe`, `endpoint`, `interrupts`, `afterturns`; amostrador de CPU/RAM/VRAM), `bench/asr_first_utterance.py`, `tests/call_ui.py`.
- **Testes:** `tests/test_call_natural.py` (55), ajustes em `tests/test_study_call.py` (o ASR falso agora pontua como o Parakeet real) e `tests/study_ui.py` (nomes novos da chamada); **suíte completa 971 OK em 1024,1 s**, UI 33 verificações, `call_ui` 10 verificações; interrupção medida no pipeline real: voz→áudio parado p50 137 ms. Medições antes/depois no relatório `LUMEN_VOZ_CONVERSA_NATURAL_20261108.md`; roteiro humano em `LUMEN_VOZ_TESTE_FINAL_20261108.md`.
- **Preservado:** configuração pessoal (nada escrito em `%LOCALAPPDATA%\Lumen`; conferido por data de modificação), voz, modelos, motor, permissões, perfil adulto, memória, notas. Sem commit. Restauração: `D:\Lumen\restauracao\voz-conversa-20261108`.

## 08/11/2026 — /elegrama 3d e /holograma 3d: a visualização 3D das aulas dentro do chat

- **Comando (D100):** `/elegrama 3d <assunto>` e `/holograma 3d <assunto>` (caixa e espaços livres; sem correspondência parcial); incompleto mostra
  um exemplo e não cria nada. Menu "/", autocomplete (Tab escreve `3d `) e `/ajuda`.
- **Dados e cena (D101, D103, D106):** a IA devolve só JSON (contrato do diagrama + `concept` + `sources`), validado por `diagram.build` e
  `visual3d.validate`; o ciclo vira um anel; o maior modelo local organiza os dados; fontes só se a IA as usou e existem; legenda sempre
  "esquemática" e "sem fontes das suas notas" quando for o caso; a conversa só entra se o pedido a cita.
- **Artefato (D102):** tipo `holo` (GIF ou PNG em `file`, PNG de reserva em `poster.png`, MIME e extensão certos, relido e conferido do disco
  antes de publicar); `visual3d.make` (trava de uma renderização por vez, rodapé próprio); rota `variant=poster`; salvar no Notion/Obsidian como
  imagem; falha de armazenamento com mensagem clara (também `/imagem` e `/pdf`).
- **Cartão (study.js/css, app.js):** imagem 16:9, legenda com as medidas reais, Pausar/Reproduzir, Ampliar (rolagem só no cartão), Baixar GIF e
  PNG, movimento reduzido mostra o PNG parado, alternativa estática sem botão de animação; `study_holo` não parece uma aula no status global.
- **Desenho (D104):** comparação com cada rótulo na coluna do seu lado; caracteres sem glifo viram o equivalente ou saem (sem quadrados).
  `RENDERER` continua `holo-3`; `visual_3d` das páginas não é tocado.
- **Perfil adulto (D105):** `previous_profile` pula arquivos gerados.
- **Banco dos Estudos (`db.connect`):** a preparação de cada conexão nova passa a ser uma por vez no processo; antes, no primeiro acesso a um banco ainda
  inexistente, várias threads recebiam `database is locked` ao trocar para WAL (115 erros em 150 bancos novos × 8 threads; 0 depois).
- **Testes:** `tests/test_study_holo.py` (34), `Labels` em `test_visual3d` (3), 1 em `test_study_adult`, `FirstConnection` em `test_study_core` (1); cenário 17 em `tests/study_ui.py`;
  `bench/holo_chat_check.py` (fluxo real, tamanho real). Corrigido o vazamento de `llm._chat` em `test_visual3d.Pages`. Suíte completa
  **916 OK em 1251,5 s (`D:/Lumen/elegrama-3d-20261108/logs/suite-full-2.log`; a primeira rodada, com 915, passou em 1259,9 s antes da correção do banco)**, UI **passou: 33 verificações, nenhum erro de página, CSP ou HTTP 5xx, backend sem erro registrado (`D:/Lumen/elegrama-3d-20261108/logs/ui-6.log`)**. Sem commit. Relatório: `LUMEN_STUDY_AI_ELEGRAMA_3D_20261108.md`.

## 08/11/2026 — Perfil adulto: modelo local dedicado, configuração própria e troca automática por contexto

- **Arquitetura (D92–D95, D97):** `lumen/study/adult.py` decide o perfil uma vez por resposta (manual → desligado → modo → automático →
  conservador). `providers.Ollama(adult=True)` leva o modelo e a temperatura do perfil a todas as etapas; `agent._turn` usa o modelo do
  perfil em todos os níveis de esforço, não troca ao refazer, e no perfil usa título neutro e não extrai memória sozinho.
- **Automático (D94):** filtro de sinais e de escrita criativa + classificador local (JSON `motivo`, `perfil`, `certeza`, temperatura 0) com
  as últimas mensagens e o perfil anterior; menor de idade ou idade incerta no pedido: sempre o principal; documento, página e ferramenta
  nunca decidem; classificador fora: mantém o perfil, ou o principal; principal externo + dúvida: pede a escolha manual.
- **Configuração e interface (D97):** seção `adult` validada e persistida; Configurações → Perfil adulto; chip "Modelo da resposta";
  `/perfil`; informações da resposta e catálogo mostram o perfil; `aplicar-perfil-adulto.ps1` liga ou desliga com backup.
- **Modelo (D96):** `qwen3.5-heretic:9b`. Triagem de Qwen3.5 Heretic 9B, Gemma 4 12B Heretic, Gemma 4 E4B Heretic e do principal.
- **Medição (D99):** roteamento 0/90 FP e 0/50 FN no final travado; modelo final 9/10 entregues, 3/6 explícitos (critério de 70% não atingido);
  fluxo real 25/25.
- **Bugs (D98):** o `qwen3-embedding` saía na lista de modelos de chat (correção anterior na rota errada); `PROFILE_LABEL` definido cedo
  demais na tela; radical `adult` no filtro. Detalhes na seção 8 do relatório.
- **Testes:** `tests/test_study_adult.py` (28), relacionados 76, UI passou (cenário novo, quatro larguras), real 25/25, **suíte completa 877 OK em 1021,96 s** (inclui o cache de falha do Ollama em `llm.models()`, +3 testes: com o Ollama parado a tela de Estudos levava ~14 s para abrir).
- **Preservado:** principal, Modo Livre e `/livre`, notas, permissões, memória (`SENSITIVE`), provedores externos, voz, visão, embeddings,
  launcher, seleção de modelos. Sem commit. Relatório: `LUMEN_STUDY_AI_PERFIL_ADULTO_20261108.md`.

## 07/11/2026 (concluído em 08/11) — Menos recusas indevidas: prompt sem fontes fantasmas, postura direta e modelos sem filtro avaliados

- **Diagnóstico medido:** o `SYSTEM` obrigava "Nas suas fontes… Próximos passos" e `[S#]` mesmo com `(nenhum documento encontrado)`. No conjunto reservado, 14 de 34 pedidos legítimos (4B) e 8 de 34 (9B) não eram entregues e 68 (4B) e 11 (9B) citações `[S#]` eram inventadas. Recusas literais de conteúdo só apareceram sem prompt (`qwen3.5:4b` recusou um monólogo de personagem racista numa peça e uma cena com palavrões).
- **Código (D87, D88):** `agent.py` ganha `SYSTEM_GENERAL` (sem notas) e a regra **Postura** nas duas variantes e na chamada de voz; `system_prompt(..., has_sources)`; `explain.task(notes=False)`; `providers.family()` reconhece a família sem o dono (`huihui_ai/…`, `hf.co/…`). Resultado no conjunto reservado: 0 de 34 (4B) e 1 de 34 (9B) não entregues, 0 citações inventadas, ferramentas 7/8, JSON e roteador mantidos, tempo igual.
- **Etapa A (D89):** instalados `huihui_ai/qwen3.5-abliterated:9b` e `:4B` e o Heretic (`qwen3.5-heretic:9b`, alias com `RENDERER/PARSER qwen3.5`), ~15 GB no D:. Nenhum adotado: os abliterados inventam onde deveriam admitir que não sabem (R3 reprovado, 2 de 3 casos contra 0 de 3); o Heretic empata com o modelo atual.
- **Etapa C não executada (D90).** Nenhum peso treinado, nenhum dado pessoal usado.
- **Instrumento (D91):** `bench/refusal_eval.py` (74 pedidos, fontes sintéticas, dois juízes, conjunto reservado travado) e `bench/refusal_live.py` (fluxo real do `agent.turn`); script `aplicar-modelo-estudos.ps1`. Dois defeitos do instrumento foram achados e corrigidos (caminho do produto ignorava `has_sources`; critério lexical estreito).
- **Testes:** 118 de linha de base; bateria relacionada 156; **suíte completa 845 OK em 907,3 s**; validação real 12/12. Uma suíte anterior, rodada com minhas medições na GPU, reprovou 2 testes de ambiente (VRAM/RAM) que passam isolados.
- **Preservado:** Modo Livre, `/livre`, `/notas`, permissões, memória (`SENSITIVE`), provedores externos, seleção de modelos, voz, visão, embeddings, launcher. Sem commit. Relatório: `LUMEN_STUDY_AI_MODELO_LIVRE_20261107.md`; restauração: `D:\Lumen\restauracao\modelos-20261107`.

## 07/11/2026 — Verificação técnica final e navegação na abertura

- Corrigida a volta involuntária para Início quando o usuário entrava em Cérebro antes de chegar o estado inicial. Reprodução controlada falhou antes da correção e passou na rodada final.
- Interface: 31 verificações aprovadas em 152,614 s, 1440/1100/760/520 px, foco, movimento reduzido, nenhum erro de página/CSP/HTTP 5xx; capturas inspecionadas. Backend sintético sem exceções no log. Integração/recursos/identidade: 20 testes OK em 3,971 s.
- Fechada a medição de vídeo anexado: clipe sintético de 6,393 s, transcrição e visão locais reais, um quadro e 207 caracteres; 89,516 s incluindo persistência/reabertura/exclusão. Configuração pessoal intacta, nenhum microfone, download ou publicação.
- Logs de 06/11 conferidos, sem repetir: suíte completa 841, direcionados 102 e regressões 32 aprovados. Desde a suíte, o único Python alterado foi a rota estática paralela de cursor, coberta pela interface atual; a lógica dos Estudos permaneceu igual.
- Fases 1–9 com implementação e prova técnica conciliadas. Janela nativa, voz com microfone real e publicação real permanecem verificações humanas/externas, sem alegação de conclusão. Launcher e executável não foram recompilados; sem commit ou limpeza ampla.

## 06/11/2026 — Fase 9 implementada; fechamento técnico em andamento

- Prática derivada das fontes, rubrica fixa, entrega por texto/anexo, feedback por critério, próximo passo e domínio atualizado. Histórico reabre, exporta e apaga com os anexos; falha na gravação não deixa uma tentativa parcial.
- Plano aplicado ao projeto, entregas e prazos, revisões em Estudar e associação ao Pomodoro. Concluir uma tarefa não é tratado como prova de aprendizagem.
- Catálogo a partir do registro único, skills próprias editáveis com proteção contra sobrescrita, ativação e teste no fluxo normal. Modelos/integrações e instalações reaproveitam configurações e relatórios existentes.
- Avaliações de respostas formam conjunto exportável e script local de regressão; contagens de trocas manuais ajustam o Automático nos limites de D84. Nenhum peso de IA é treinado.
- Corrigidas regressões de codificação de processos do Windows e de vetores durante alterações; isolamento do trabalhador de índice reforçado nos testes.
- Restaurado o indicador de foco por teclado removido por uma alteração visual paralela, preservando os efeitos novos. Cabeçalho de itens em janela estreita agora mantém “Salvar no Obsidian” legível; o teste visual verifica corte de texto, foco e movimento reduzido.
- Provas atuais: **841 testes na suíte completa aprovados**, 102 direcionados e 32 de regressão. Geração real com duas fontes em leitura, sem escrita externa; configuração pessoal intacta. A primeira suíte completa reprovou, foi corrigida e repetida. Interface final em andamento após alteração paralela de CSS e restauração do indicador de foco por teclado.
- Nenhuma dependência/modelo instalado, launcher não recompilado, executável pessoal preservado. Restaurações verificadas e resultados detalhados em `LUMEN_STUDY_AI_PHASE9_20261105.md`; checklist integrado em `LUMEN_STUDY_AI_FINAL_CHECKLIST_20261106.md`.

## 05/11/2026 — Fase 8: agente, criações e pesquisa guiada

- Três opções de autonomia; criação só nas áreas da IA quando pedida, link e Desfazer persistentes no histórico. Notion relê texto/arquivos; criação parcial fica a conferir e não é repetida. Desfazer recusa alterações posteriores e preserva anexos no cofre.
- `open_app` com cinco aplicativos, lista permitida nas Configurações, respeito à abertura de janelas e nenhum argumento de terminal produzido pelo modelo.
- `/web`: Edge visível, perfil temporário no D:, busca pública, lista pelo DOM e leitura protegida, fontes citáveis, miniatura, Pausar/Retomar e Parar. Sem scripts de sites, formulários, login ou cliques livres. D10/D11 atualizadas; D74–D79 registram o comportamento.
- `/nota`, `/pagina`, `/abrir` e ferramentas ligadas aos fluxos existentes. `/tela` mantém a ativação explícita e não persiste a captura. Falha na criação externa preserva a resposta no chat.
- Prévia de mapas e explicações inclui a imagem do diagrama; usa renderizador e anexos existentes, somente após confirmar.
- Testes novos em `test_study_agent`, passo 14 em `study_ui` e medição real reproduzível em `bench/study_agent_bench.py`. Fixture antiga do widget atualizada para inicializar `close_connection`; nomes de botões e isolamento das credenciais no teste visual acompanham alterações paralelas.
- Pesquisa real com `qwen3.5:4b`, Python.org e Edge 156.0.4314.58: 113,59 s; referência, criação local e desfazer conferidos. Isso prova o fluxo, não a correção semântica integral do texto do modelo. Notion apenas falso; janela nativa pessoal pendente.
- **Instalações: nenhuma.** Restaurações completas e verificadas em 04 e 05/11. Nenhuma mudança no launcher/executável por esta fase, nenhuma parada/reinício de Ollama ou Voice Studio, nenhuma migração de imagem repetida.
- Resultados, falhas intermediárias e continuidade: `LUMEN_STUDY_AI_PHASE8_20261105.md`. Resultado reconciliado em 06/11: suíte final anterior de 817 testes aprovada; não é execução desta fase 9.
- Integração com o trabalho paralelo de provedores: `_google_schema` preserva nomes de propriedades e limpa `required` inexistentes; mensagens anteriores usam `model` no Gemini; erros de `streamGenerateContent` distinguem parâmetros e modelo incompatível. A expectativa antiga que recusava `openai` foi trocada por um provedor realmente inválido. Os 27 testes focados existentes passaram; nenhum envio real à nuvem foi feito. Contrato conferido na [referência oficial do Gemini](https://ai.google.dev/api/generate-content?hl=en).

## 04/11/2026 — Fase 7: imagens e PDFs (testada e medida)

- `/imagem` nos Estudos, em quatro proporções, pela fila existente, com liberação da VRAM do Ollama e cancelamento do processo de difusão da própria tarefa. Resultado persistido na conversa, identificado como gerado por IA e impedido de virar fonte, inclusive na reimportação de PNG com procedência.
- `/pdf` em nove tipos: revisão de uma página, apostila com sumário, Cornell, exercícios, flashcards frente/verso, plano, simulado, mapa mental e explicação. A4 claro por padrão; opção escura e capa ilustrada opcional nas configurações. `Gerar PDF` reaproveita a explicação existente.
- Novo `lumen/study/pdf.py` usa o mesmo `cdp.pdf` e os renderizadores existentes. Texto escapado, dados limitados, JPEG comprimido, referências verificadas por id e conhecimento geral identificado. A medição real identificou que a busca podia selecionar apenas seções de estrutura da nota; PDFs agora leem o documento encontrado pela ferramenta `read_document` antes de escrever.
- `lumen/study/artifacts.py` reutiliza anexos, conversas, fila e prévia. Obsidian preserva autoria e fontes; Notion relê o bloco persistido e compara os bytes antes de confirmar o envio. Testes usam o Notion falso e cofre isolado.
- Corrigido `image_dir` descartado por `store.DEFAULTS`. Migração para `D:\Lumen\imagem` com 24 arquivos/6.786.395.497 bytes conferidos por SHA-256; configuração alterada após saída normal confirmada pelo usuário. Origem preservada.
- CDP aguarda o arquivo `DevToolsActivePort` quando o Edge ainda o está criando com acesso exclusivo e encerra apenas os processos do perfil temporário da própria chamada se o fechamento normal não terminar.
- Direção do produto esclarecida: base local de um segundo cérebro, também para tecnologias futuras. Registrada no README e em D66; nenhuma função das fases 8 ou 9 foi adicionada.
- Restauração validada fora do projeto: 258 arquivos, ZIP + manifesto + hashes. Fontes herdadas, novos arquivos e executável inicial incluídos. Outra sessão alterou o launcher/visual e executável durante o trabalho; essas alterações foram preservadas e não são atribuídas à fase 7.
- **Instalações: nenhuma.** Validação usa `pypdf` do ambiente existente, Edge/CDP e `pypdfium2` 5.14.0 já instalado no Python 3.14. O gerador local existente produziu uma imagem real em 148,27 s.
- **Provas finais:** suíte completa com 764 testes passando; 15 testes novos exercitados em rodadas focadas e nove testes de fontes/índice na conferência final. Interface com 28 verificações passando nas quatro larguras. PDF real: 83,79 s, uma página, seis blocos atribuídos à nota; imagem real: 148,27 s. Gráfico estático pelo renderer existente e até duas imagens das fontes também conferidos.
- Comandos, resultados, medições, capturas e pendências: `LUMEN_STUDY_AI_PHASE7_20261104.md`.


## 02/11/2026 — Study AI 2.0, fase 6, parte 3: conversa por voz em tempo real

**Novo**
- **Conversa por voz em tempo real nos Estudos** (`lumen/study/call.py`, `lumen/web/study-call.js`, `lumen/web/study.css`, D61 a D65): botão `"Conversa por voz"` ao lado da caixa de mensagem e destino no Ctrl+K. Abre a visão de chamada dentro dos Estudos com o avatar da voz ativa num orbe animado (Ouvindo, Entendi, Pensando, Falando e `"Preparando a voz…"` a frio, D54), usando apenas tokens de `DESIGN.md` e desligando qualquer movimento em `prefers-reduced-motion: reduce`.
- **Legenda ao vivo, cartões e pílula flutuante:** fala parcial em cinza e final em cor normal; resposta do Lúmen sincronizada com a frase que está tocando destacada; interrupção cortando exatamente até onde tocou com selo `"interrompida"`; cartões reais do chat (mapa mental, diagrama, quiz, flashcards, plano, `/tela`, Feynman e prévia de gravação) dentro da legenda com fala curta; controles de Mudo, Falar agora, Voz, Legendas, Minimizar (vira pílula flutuante entre as abas do app) e Encerrar (`Esc`), com ponto vermelho `"Microfone aberto"` (some no mudo) e cronômetro/estado em `aria-live`. Ao encerrar, a conversa volta inteira ao chat (em conversa temporária, nada é salvo no banco).
- **Configurações → Voz → "Conversa por voz"** (`lumen/study/settings.py`, `lumen/web/study-settings.js`): 18 ajustes planos validados (`call_mode`, `call_silence`, `call_barge_in`, `call_headphones`, `call_early`, `call_mic`, `call_voice`, `call_speed`, `call_quality`, `call_length`, `call_effort`, `call_earcon`, `call_filler`, `call_asr`, `call_captions`, `call_autostop`, `call_save`, `call_timings`), com padrões vindos da medição.
- **Caminho da fala em tempo real e privacidade:** microfone contínuo (`listen.Mic.start_continuous`, quadros de 32 ms em 16 kHz e anel de 320 ms), VAD Silero ONNX na CPU, resposta antecipada aos 250 ms com portão `_commit_gate` (descarta sem rastro se o estudante voltar a falar), transcrição na memória com Parakeet ONNX int8 na CPU por padrão no Automático, saída de áudio pelo Python (`loopback.speaker`, WASAPI `float32` 24 kHz com descida suave de 50 ms + `flush`), cancelamento de eco duplo com `pyaec` (SpeexDSP) + barreira calibrada de energia (`EchoGuard`), comandos rápidos sem IA ("para", "repete", "mais devagar", "mais rápido", "fala mais baixo", "encerra a chamada", "fala com a voz da demo") e os 10 pedidos por voz (mapa mental, diagrama, flashcards, quiz falado com `"não sei"` nunca contado como acerto no `mastery`, plano, `"o que eu errei"`, Feynman, `/tela`, revisão do dia e salvar sempre com prévia). Nenhum áudio da chamada vai para o disco, e `activity.log` guarda só tempos numéricos.
- **Rotas, testes e benchmark:** `GET /api/study/call`, `GET /api/study/call/events` e `POST /api/study/call`; `tests/test_study_call.py` (10 testes cobrindo toda a máquina de estados, resposta antecipada cancelada, interrupção, eco, comandos rápidos, intenções, conversa temporária e privacidade), passo 12 de `tests/study_ui.py` (em 1440, 1100, 760 e 520 px) e `bench/call_bench.py` (com amostras em `D:\Lumen\voz\amostras-chamada` e escuta cega em `escuta-cega\`).

**Instalado**
- `pyaec` 1.0.1 (`82,8 KB`, roda oficial `cp314-win_amd64` do PyPI em `.venv` e `requirements.txt`, licenças MIT / SpeexDSP BSD-3-Clause), para cancelamento de eco acústico na chamada com caixa de som (D64).

**Medido**
- `D:\Lumen\voz\amostras-chamada\call_bench.json` (`LUMEN_STUDY_AI_MODELS.md` → Conversa por voz): Parakeet CPU int8 em 270,7 ms (p90 342,9 ms, 2,65% de erro, +0 MB de VRAM); saída WASAPI no Python em 11,3 ms e interrupção em 53,9 ms; 0/20 disparos falsos de eco e 20/20 interrupções reais com `pyaec` + barreira; som de "entendi" em 42,3 ms; resposta antecipada economizando 725,5 ms na mediana em 700 ms; 1º som da resposta em 3,41 s a 3,73 s com 12 passos (ou 3,13 s com 8 passos no 1º pedaço); 10 minutos contínuos (24 turnos, 0 erros) com VRAM variando −200 MB e RSS +2,5 MB.

**Corrigido**
- `lumen/loopback.py`: inicialização COM por thread (`CoInitializeEx` após `import soundcard`) em `microphones()`, `microphone()` e `speaker()`, evitando erro `0x800401f0` / `0x100000001` do WASAPI em threads secundárias.
- `lumen/voicestudio.py`: `errors="replace"` na leitura de `tasklist` em `app_open()`, evitando falha de decodificação em Windows pt-BR sob UTF-8.
- `lumen/study/listen.py` e `study-settings.js`: chave compatível na listagem de microfones e sincronização imediata dos ajustes `call_*` com chamada ativa.
- Achados da conferência independente (subagente): trava `_ASR_LOCK` aplicada também no pré-aquecimento `_warm_asr_safe` (`call.py`) e reconexão automática com recuo curto em `connectStream` (`study-call.js`).

## 02/11/2026 — Study AI 2.0, fase 6: escolhas do estudante

**Mudado**
- Escuta cega da fase 6: o estudante escolheu o Voice Studio com idioma `pt` (Y). A reserva `voice.fallback` agora é `off` por padrão (D60).
- Fala do chat: o padrão passou de 12 para 16 passos (escuta cega: Y), cerca de 0,4 s a mais até o 1º som (D56). Muda em Configurações → Voz; quem já salvou outro valor mantém o dele.
- Chatterbox removido do PC (ambiente, finetune, cache e Python 3.11 dele): 12,8 GB livres no D:. O código do motor continua e a tela já trata "não instalado".
- Modelos do Voice Studio copiados para o D: (`D:\Lumen\voicestudio\models`): 149 arquivos, 23,1 GB, cada um conferido por hash, em 374 s. A pasta antiga (`%LOCALAPPDATA%\OmniVoice\hf_cache`) continua intacta até o estudante escolher a pasta nova no app do Voice Studio e apertar "Apagar a cópia antiga no C:" no Lúmen.
- Cópia antiga apagada (`%LOCALAPPDATA%\OmniVoice\hf_cache`): o C: foi de 20 para 31,9 GB livres. O botão recusou a 1ª vez porque o Voice Studio gravou 3 logs do downloader (`xet\logs`) na pasta antiga depois da cópia; `safe_to_delete` agora só confere os arquivos de `models--*`, com teste. O Lúmen aberto tinha o código antigo, então o mesmo passo (mesmas checagens) rodou por script, com a confirmação do estudante.

## 02/11/2026 — Study AI 2.0, fase 6, parte 2: Voice Studio sem janela, modelos no Lúmen, voz mais rápida e Treino falado

**Novo**
- A voz funciona com o Voice Studio fechado: o Lúmen sobe o backend dele sem janela na primeira fala, mostra "Preparando a voz… 40%" na barra de fala e o desliga depois de 15 min parado (não com o app aberto). Abrir o app depois usa a mesma voz, sem conflito de porta (D53 a D55).
- Integrações → Voice Studio: estado novo ("Pronto (rodando em segundo plano)", "Pronto (o app está aberto)", "Preparando a voz…", "Desligado, liga sozinho quando precisar"), "Deixar a voz pronta ao abrir o Lúmen", "Abrir o app" como ação secundária.
- Modelos de voz no Lúmen: os pacotes Rápido, Equilibrado, Qualidade, Máximo e Automático (o que já está instalado e quanto falta baixar), todos os modelos com tamanho e licença ("uso pessoal" nos CC-BY-NC), baixar com progresso e Cancelar, remover, motores de voz e de transcrição (os indisponíveis com o motivo e "Instalar"), a transcrição do próprio Lúmen e a pasta dos modelos, com "Mover para o D:" (copiar e conferir, escolher a pasta no app, apagar a cópia antiga) e "Limpar temporários". Tudo só pelo clique, com "Isto muda também no Voice Studio" (D57).
- Qualidade por uso: "Fala do chat" e "Áudios longos", de Rápido (8 passos) a Máximo (32), sem mexer no nível do Voice Studio (D56).
- Painel "Esta máquina": placa por quem (Ollama, voz, Lúmen), RAM, C: e D:, o estado da voz e os últimos tempos, com o que fazer quando falta memória (D59).
- Pronúncias (Configurações → Voz): o dicionário do Voice Studio, aplicado também na fala do Lúmen, com testar, importar, exportar e "Sugerir das minhas notas" (D58).
- Criar voz para personagem por descrição, com o nome marcado "(Lúmen)" (D58).
- Treino falado (Estudar): venda, negociação e entrevista em inglês, em turnos de voz, com a rubrica no fim indo para o modelo do estudante (D58).
- Revisão a duas vozes: o narrador pergunta, a voz padrão responde (D58).
- Cache de frases: "Ouvir" de novo sai na hora; no máximo 2 frases prontas à frente; com pouca VRAM, a voz pede ao Ollama para soltar a placa na hora de falar (D59).

**Mudado**
- A fala do chat sai pelo `/v1/audio/speech` em PCM com os passos do uso (antes, `/ws/tts` com 16 passos fixos). O 1º pedaço é cortado na vírgula perto de 50 caracteres: com 12 passos, ≈ 1,5 s até o 1º som (antes 2,4 a 2,7 s).
- Os testes nunca sobem, abrem nem chamam o Voice Studio real (`tests/__init__.py` aponta os caminhos dele para uma pasta vazia).

**Medido**
- Passos 8, 12, 16, 24 e 32: geração por segundo de fala de 0,27 a 0,68, erro de palavras de 0% a 1,9%, 1º som de 1,92 s a 4,64 s (`LUMEN_STUDY_AI_MODELS.md` → Voz, parte 2).
- A frio, com o Voice Studio fechado: o Lúmen subiu o backend sem nenhuma janela, falou e desligou em 0,8 s, sem processo restante. 1º som em 74,1 s (arquivos frios) e 40,9 s (2ª subida), quase tudo na carga do modelo; a meta de 25 s não foi atingida. O `offload-after-generation` não libera VRAM na rota de fala do Lúmen.

**Corrigido nos testes de tela**
- O diálogo "Criar voz para personagem" escondia o 1º botão (o rodapé de 460 px não quebrava linha): diálogos de formulário ficam mais largos e o rodapé quebra.
- Um "null" aparecia embaixo dos modelos e no painel da máquina; o ícone da transcrição era um ponto (agora uma onda).
- Em 520 px, cada linha das Configurações ficava com 220 px de altura (o `flex-basis` virava altura na coluna). Vale para todas as seções das Configurações, não só a Voz.
- Clicar na seção das Configurações que já está aberta desenhava o painel de novo e trocava os campos enquanto se digitava (no teste, o termo da pronúncia sumia): agora a seção aberta não é redesenhada.

**Corrigido depois da conferência independente** (um subagente com contexto novo leu a fase contra o prompt):
- O vigia de uso parado podia desligar o backend no meio de uma subida a frio (o relógio de uso começava em zero): subir e carregar o modelo agora contam como "em uso".
- "Apagar a cópia antiga" podia, depois de reiniciar o Lúmen, apontar para a pasta de trabalho: agora só apaga com a cópia conferida gravada, numa pasta com `models--*`, com cada arquivo presente na nova; a confirmação mostra o caminho, e o botão aparece de novo depois que o Voice Studio passa a usar o D:.
- O cache de frases tocava o áudio antigo depois de uma pronúncia nova ou de trocar o motor: a chave usa o texto já trocado e o motor ativo. Conversas temporárias e o Treino falado não entram no cache, "Limpar frases guardadas" e Seus dados apagam o cache, e o cache em 0 não lê o que havia.
- Outro programa na porta do Voice Studio virava "recusou o pedido": agora a tela diz que a porta está ocupada, e a reserva fala avisando.
- "Ligar a voz agora" ligava só com "ligar sozinho" ativo; criar uma voz por descrição agora espera o modelo carregar de verdade.
- O estado em Integrações era reescrito a cada 2 s numa região que o leitor de tela anuncia: só muda quando o texto muda. O seletor de pacote tem uma parada de Tab (as setas trocam).
- Treino falado: uma falha da IA não gasta a vez do estudante (a fala volta para a caixa), e a nota geral é a média dos critérios.
- Um modelo que não carrega no prazo não aparece mais como "pronto"; o 1º pedaço da fala usa a vírgula mais perto de 50 caracteres; testes mais fortes (ritmo de 1, 2 e 3 frases à frente, versão do app com arquivos de verdade, subida lenta com o vigia ligado) e nenhum teste lê a RAM, a placa ou o Ollama de verdade.

## 02/11/2026 — Study AI 2.0, fase 6: as vozes do Voice Studio, a fala no chat e os áudios com capítulos

**Novo**
- **Voice Studio como motor de voz** (`lumen/voicestudio.py`, D46 e D47): o Lúmen lista as vozes clonadas e criadas do estudante e fala com a do Jhonny por padrão. Só HTTP e WebSocket no loopback; nenhuma rota que muda algo no Voice Studio. Com ele fechado, a reserva (Chatterbox pt-br) entra avisando qual voz está falando.
- **Integrações → Voice Studio** (`lumen/web/voice.js`): estado real (Conectado, Fechado com o botão Abrir, Carregando o modelo com a barra), versão, GPU e motor; a galeria com avatar (iniciais sobre o gradiente do acento, com um anel que segue a amplitude real do som), "Clonada" ou "Criada", o idioma, ouvir a referência, Testar, Usar como padrão e Editar (abre o Voice Studio). Não há Excluir.
- **Estudos → Configurações → Voz**: motor e reserva, a voz padrão, uma voz por uso (conversa, resumo, revisão e a do Treino falado, já usada no "Ouvir o retorno" do Feynman; o Treino falado em si é pendência), velocidade com prévia ao soltar, idioma, semente, estilo (as tags do motor), leitura automática, o que ler, enviar sozinho, conferir os áudios longos, o resumo no fim de cada aula e "Testar a voz" com texto editável.
- **Voz no chat** (`lumen/study/listen.py`, D48 e D50):
  - "Ouvir" em cada resposta: sem Markdown, código nem `[S#]`, frase a frase pelo `/ws/tts`, com a frase que está tocando destacada na resposta;
  - a barra de fala sobre a caixa de mensagem: avatar, nome, estado (`aria-live`), onda ao vivo, "frase X de N", pausar, pular e parar (Esc);
  - "Apertar para falar" (o botão ou a barra de espaço segurada fora da caixa de texto): o Python grava, transcreve em português e o texto entra na caixa; "Enviar sozinho" opcional;
  - a fala para quando o estudante começa a falar ou manda outra mensagem.
- **Resumo em áudio da aula e revisão em áudio** (D49): pela fila de tarefas, com o tempo previsto, o progresso por frase e o Cancelar no status do topo. O resumo lê o que a aula já tem (resumo e tópicos); a revisão faz pergunta, pausa e resposta. Cada frase é conferida pelo Whisper (D45). O arquivo é um `.m4a` com o volume igualado em `D:\Lumen\estudos\audio`, com os capítulos num `.json` ao lado.
- **Player com capítulos** (`voice.js`): play e pausa, posição, velocidade de 0,75 a 2×, capítulos clicáveis (o servidor entrega o arquivo com `Range`), posição salva, Baixar, Mostrar na pasta e Apagar. Na Biblioteca e no fim de uma aula: "Resumo em áudio" (ouvir ou gerar).
- **O resto da fase 6** (D52): o áudio da revisão vai para a nota do Obsidian pela prévia (o `.m4a` copiado para a pasta de anexos do cofre só depois de confirmar); "Ver na aula (mm:ss)" nos capítulos do resumo; Feynman em Estudar ("Explique com as suas palavras", por texto ou voz, com o certo, o que faltou e o que está errado, e a origem `feynman` no modelo do estudante); "Tour narrado" no diagrama, com a parte falada acendendo junto.
- **Rotas:** `/api/study/voice/state`, `voices`, `sample`, `image`, `test`, `say`, `listen`, `make`, `audios`, `file` e `audio`; `/api/voicestudio/open`; `/api/study/feynman`.
- **Testes:** `tests/test_study_voice.py` (18, com o Voice Studio falso de `tests/fake_voicestudio.py`, que registra tudo e prova que nenhuma rota de escrita é chamada) e o passo 10 de `tests/study_ui.py`.
- **Medidas:** `bench/voicestudio_bench.py` e `LUMEN_STUDY_AI_MODELS.md` → Voz.

**Corrigido**
- No Windows, a porta fechada do loopback chega como tempo esgotado na conexão; o cliente do Voice Studio passou a tratar isso como "fechado", e a reserva entra.
- As abas de Integrações viraram uma grade de 4 colunas (2 em janela estreita), sem a quarta aba sozinha numa linha.
- A 1ª frase de uma resposta real era longa demais (11,4 s até o primeiro som): o 1º pedaço da fala é cortado em 90 caracteres (2,4 s a 2,7 s).
- Achados da revisão final (subagente):
  - o resumo no fim da aula nunca disparava (a chave está no resultado, não no spec) e, quando disparasse, apagaria o resultado da aula antes de a tela vê-lo: agora entra na fila 6 s depois e não refaz um áudio que já existe;
  - na reserva, cada consulta fechava o Chatterbox (que leva 88 s para carregar): ele só fecha quando o Voice Studio responde;
  - o "apertar para falar" detectava o idioma sozinho: agora é português fixo, e o Ollama é liberado se a placa encher;
  - a barra de fala ficava escondida quando a fala começava fora do chat (Feynman, Estudar): agora flutua embaixo;
  - "Testar" não avisava quando a reserva falava; o aviso de voz sumida se acumulava; um fechamento do WebSocket virava "erro inesperado"; o Whisper do Voice Studio podia ser descarregado mesmo se o estudante o tinha carregado; o prazo de geração passou a ser o do próprio Voice Studio;
  - na conversa por voz (pergunta pelo microfone), a resposta é lida em voz alta mesmo com a leitura automática desligada; com o Voice Studio fechado e sem reserva, a tela oferece "Abrir o Voice Studio".
- No PC do estudante, "apertar para falar" dava "O microfone não abriu": o microfone USB mono informa o formato como PCM simples e o gravador do soundcard só aceita o "extensible" (falha num assert). O microfone agora abre com o mesmo gravador de formato fixo do filtro de música (`loopback.microphone`, o Windows converte), e a falha vai para o log com o motivo. Conferido nos dois microfones do PC.

**Removido**
- Kokoro (o ambiente e o modelo): não foi usado, porque a fala ao vivo do Voice Studio começa em 2,7 s.

## 01/11/2026 — Study AI 2.0, fase 5: explicação por nível, diagrama interativo, mapa mental e modelo do estudante

**Novo**
- **Explicação por nível de esforço** (`lumen/study/explain.py`, D40): o texto em camadas parte do que o estudante já sabe; abaixo dele vêm os extras do nível:
  - **Rápido:** só o texto (intuição e mecanismo);
  - **Equilibrado:** diagrama e uma pergunta de checagem;
  - **Profundo:** também flashcards no baralho de revisão espaçada;
  - **Máximo:** também o resumo de 3 linhas e a próxima revisão marcada.
  - Botões abaixo de cada explicação: "Mais simples", "Mais fundo", "Outro exemplo" e "De outro jeito". A checagem é corrigida pela IA; se errar, a IA explica de outro jeito a partir do que ele respondeu.
- **Diagrama interativo** (`lumen/study/diagram.py` e `lumen/web/study-diagram.js`, D41): SVG 2D na paleta do holograma, em oito famílias (processo, linha do tempo, ciclo, estrutura, comparação, sistema, conceitos e mapa mental).
  - "Passo a passo" acende as partes em ordem; com movimento reduzido, avança um passo por clique.
  - Clicar numa parte, ou Enter e Espaço nela, mostra a explicação dela, com "Explicar esta parte". As setas andam entre as partes.
  - "Partes em lista" traz tudo em texto, e "Baixar PNG" gera a imagem.
  - Em 520 px vira uma coluna; largo, o mapa mental põe os ramos dos dois lados do centro.
- **`/mapa-mental <assunto>`** (D43): o mapa mental no chat, salvo em Estudar. Exporta em PNG (pelo `mindmap.py`, o desenho das aulas) e vai para o Obsidian ou o Notion com prévia.
- **Modelo do estudante** (`lumen/study/mastery.py`, D42): acertos e erros por assunto nos flashcards, nos questionários e nas checagens.
  - Ajusta o ponto de partida da explicação.
  - Em Estudar, "Assuntos para revisar" lista os de revisão vencida e os de dificuldade.
  - Em Seus dados, a categoria "O que o Lúmen sabe que você domina" é visível, exportável e apagável.
- **Rotas:** `POST /api/study/check` (corrige a checagem) e `POST /api/study/diagram` (PNG ou GIF da spec, conferida de novo no servidor). `GET /api/study/due` passou a trazer os assuntos para revisar.
- **Banco, migração 4:** tabela `mastery`.
- **Testes:** `tests/test_study_explain.py` e o passo 7e de `tests/study_ui.py`, em 520 px.

**Alterado**
- **Roteador:** "mapa mental" vira o modo `mindmap`, e não mais o mapa de conhecimento. O modelo também pode escolher `mindmap`.
- **`learn`:** `add_cards` e `grade` saíram de `generate` e `answer` para serem usados pela explicação. `review` e `answer` gravam no modelo do estudante.
- **`agent.system_prompt`** recebe o esforço e o assunto; o modo "explain" usa `explain.task`.
- **`visual3d.render`** recebe a origem do texto ("da aula" por padrão; "das suas notas" no diagrama dos Estudos). As aulas não mudam.
- **Correção de respostas abertas** (`learn.grade`, usada no questionário e na checagem): o retorno só cita como acerto o que está escrito na resposta. Na medição, ele elogiava uma ideia que a resposta não tinha; depois da mudança, 3 de 3 respostas erradas tiveram retorno fiel.

**Corrigido durante a medição real:**
- **Diagrama com uma parte só:** o `qwen3.5:4b` às vezes mandava um processo de 1 parte, recusado pela validação, e o Equilibrado ficava sem diagrama (saiu em 1 de 3 tentativas). O esquema ganhou `minItems: 3`, o prompt pede "de 3 a 8 partes" e a numeração do rótulo ("1. Desenho") sai, porque o desenho já numera. Depois disso, saiu em 6 de 6.

**Corrigido depois da conferência independente** (um subagente com contexto novo leu a fase contra os critérios):
- **Conversa temporária:** não grava mais baralho, revisão marcada nem acertos e erros. Com a privacidade ligada, o modelo do estudante também não entra no prompt (D13).
- **"Difícil" no flashcard** deixou de contar como acerto, como diz a D42.
- **Resposta da IA fora do esquema** (cartão com número no lugar de texto, fonte em lista, `children` que não é lista): o que dá para aproveitar vira texto, o resto sai, e a explicação não cai mais com "Erro inesperado".
- **Texto "null"** sob a explicação de uma parte, no mapa mental aberto em Estudar.
- **Botão do "Passo a passo"** seguia dizendo "Pausar" depois de clicar numa parte; agora diz "Continuar".
- **Botões da explicação** devolvem o rascunho que estava na caixa e não deixam o modo Explicar ligado se o envio não sair.
- **Apagar um projeto** apaga o domínio registrado nele.
- **Assuntos parecidos:** o casamento ficou mais estrito (um assunto de uma palavra não casa com qualquer pergunta que a contenha), e o mesmo assunto com outras palavras soma na mesma linha.
- **Testes novos:** temporária sem gravação, saída fora do esquema, "Difícil", projeto apagado, assuntos parecidos e numeração no rótulo (15 testes no arquivo). A conversa temporária criada num teste é tirada no fim dele: antes, ela vazava para `test_study_core` quando os dois arquivos rodavam nessa ordem.

**Nada instalado.**

**Medido com dados reais** (banco temporário; cofre só leitura, com 67 notas e 668 trechos indexados em 12 s; Ollama real). O assunto foi "o fluxo de criação de motion graphics com ferramentas open source", coberto por duas notas de curso. A primeira rodada foi antes da correção do diagrama; a segunda, depois.

| Nível | Tempo total | Extras | O que veio | Fontes citadas |
|---|---|---|---|---|
| Rápido | 41,5 s / 21,1 s (a 1ª com os modelos frios) | — | só o texto | 2 / 2 |
| Equilibrado | 30,8 s / 27,6 s | 4,6 s / 8,0 s | checagem; diagrama só na 2ª (processo, 4 partes) | 2 / 0 |
| Profundo | 36,6 s / 35,0 s | 11,3 s / 9,8 s | diagrama (5 partes), checagem, 4 / 3 flashcards no baralho | 2 / 0 |
| Máximo (`qwen3.5:9b`) | 130,1 s / 126,0 s | 34,7 s / 33,4 s (o 4b volta à placa) | diagrama, checagem, 3 flashcards, resumo de 3 linhas, revisão marcada | 2 / 3 |

- **Camadas:** seguidas em cada nível. O Profundo trouxe exemplo, contraexemplo, erros comuns e onde se aplica.
- **Checagem:** a pergunta pede o porquê (por exemplo, "Por que o Cloud Code é essencial neste fluxo?"). A correção leva de 1,2 a 2,3 s.
- **Ponto de partida:** depois de uma checagem errada e uma certa, mudou de "ainda não praticou" para "está aprendendo (1 acerto e 1 erro)".
- **`/mapa-mental`:** 13,4 s / 12,0 s, com 18 e 15 partes. O PNG pelo Edge leva 2,3 s / 2,2 s (1,6 MB / 1,4 MB).
- **Imagens do diagrama:** o PNG da cena do holograma sai em 1,2 s (193 KB), e o GIF em 5,7 s (2,4 MB).

## 01/11/2026 — Study AI 2.0, fase 4: anexos, imagens das notas e `/tela`

**Novo**
- **Anexos no chat** (`lumen/study/attachments.py`, D33 a D35): botão `+` na caixa de mensagem, arrastar para a conversa ou colar um print com Ctrl+V; também `/anexar`.
  - O tipo vem dos bytes iniciais, nunca da extensão, com teto por tipo. Texto, código, md, csv e html; PDF (páginas escaneadas pela visão); docx, pptx, xlsx, odt e epub; png, jpg, webp e bmp; áudio e vídeo (transcritos, com `[mm:ss]`; no vídeo, os quadros-chave também pela visão).
  - Cada anexo aparece como ficha acima do campo, com o andamento real ("Transcrevendo… 40%", "Esperando a aula em processamento terminar…") e miniatura nas imagens. O envio espera a leitura terminar. Sem texto, a pergunta padrão é "O que este anexo traz de importante para eu estudar?".
  - Na conversa, o anexo é a fonte S1 (S2…) em todas as respostas dela, embrulhado como dado. As fichas ficam acima da pergunta; no clique, "Adicionar ao índice".
  - Os arquivos ficam em `D:\Lumen\estudos\anexos\` e somem com a conversa.
- **Imagens das notas** (`lumen/study/images.py`, D37): `![[x.png]]` e `![](x.png)` no cofre e as imagens enviadas ao Notion (baixadas na sincronização) viram texto pesquisável no lugar onde aparecem, lido pela visão local depois de cada sincronização (30 por rodada). Miniaturas nas fontes. Ajustes: "Ler as imagens das notas" (Busca) e "Imagens das notas lidas por sincronização" (Desempenho).
- **`/tela [pergunta]`** (D36): a IA vê a janela que você usava antes do Lúmen. Nada é guardado; um aviso mostra o nome da janela, e a pergunta ganha a ficha "Tela vista nesta pergunta".
- **Rotas:** `POST /api/study/attachments` (corpo binário), `GET /api/study/attachments`, `POST /api/study/attachment` (tirar, adicionar ao índice) e `GET /api/study/image` (miniaturas).
- **Banco, migração 3:** tabelas `attachments` e `images`.
- **Testes:** `tests/test_study_attachments.py` e o passo 7d de `tests/study_ui.py`.

**Alterado**
- **Visão nos Estudos com 32k** (D38): `vision.read` ganhou `num_ctx`; as aulas continuam com 4k.
- **`vision.Screen.previous()` e `vision.window_jpeg()`**, para o `/tela`.
- **`web._get`** aceita outro teto de tamanho (as imagens do Notion vão até 25 MB).
- **Apagar conversa** apaga os anexos; **"Documentos indexados"** em Seus dados apaga também as cópias das imagens das notas, e a pasta de mídia aparece no inventário.
- **Fontes de anexo e de tela** não mostram "Abrir original".
- **`PROMPT_CONTINUAR.md`:** regras do Edge como administrador, do Ollama do estudante e do `study_ui`.

**Corrigido depois da conferência independente** (um subagente com contexto novo leu a fase contra os critérios):
- **Quadros de vídeo** também vão para a visão com 32k (`vision.extract` ganhou `num_ctx`). Antes, um vídeo anexado recarregava o modelo do chat (D38).
- **Imagem achada pelo nome no cofre** passa pelas mesmas guardas do caminho direto (`vault.inside`, pastas da Proteção de fora). Um link simbólico para fora do cofre não é mais lido.
- **Leitura interrompida** por fechar o Lúmen vira erro com aviso no início seguinte ("Anexe o arquivo de novo"), em vez de ficar em "Lendo…" e a IA nunca ver o anexo.
- **Imagem com pixels demais** (acima de cerca de 40 milhões) é recusada antes de decodificar; o anexo de imagem passou a abrir pelo Pillow, que confere isso, e sempre fecha o arquivo.
- **Um XML de documento** acima de 60 MB é recusado.
- **`</documento>` dentro de uma nota ou anexo** não fecha mais o envelope de dado (`tools.wrap`): vale para todas as fontes.
- **Arquivo vazio** e `Content-Length` negativo são recusados; **fotos HEIC e AVIF** são recusadas com o motivo, em vez de irem para a transcrição como vídeo.
- **PDF lido em parte** (mais de 300 páginas, ou mais de 20 escaneadas) diz isso na ficha.
- **Anexo guardado no índice** não mostra "Abrir original".
- **Testes novos:** vídeo, texto, HTML e CSV, HEIC, arquivo vazio, imagem com pixels demais, zip que se expande demais, PDF lido em parte, leitura interrompida e link simbólico no cofre (19 testes no arquivo); no `study_ui`, arrastar e soltar.

**Nada instalado.** O `glm-ocr` teve a licença confirmada (MIT e Apache-2.0) e não foi adotado (D39).

**Medido com dados reais** (banco temporário, cofre e PDFs só leitura, Ollama real, `qwen3.5:4b`):

| O quê | Tempo | Resultado |
|---|---|---|
| Visão com 4k logo depois do chat em 32k | 11,9 s | recarregou o modelo |
| Chat em 32k logo depois da visão com 4k | 7,8 s | recarregou de novo |
| Visão com 32k (duas vezes) | 4,5 s e 3,7 s | sem recarga; 4,22 GB de VRAM contra 3,14 GB |
| Print de aula (tela do PhotoCraft) anexado | 4,0 s | título, descrição e o texto da janela "Novo documento" |
| PDF de 20 páginas (roteiro de VSL) | 0,4 s | 10.850 caracteres, nenhuma página escaneada |
| PDF escaneado de 2 páginas | 32,3 s | 5.531 caracteres lidos pela visão (conteúdo não exibido: documento pessoal) |
| Imagens de uma nota de aula do cofre | 14,2 s | 4 imagens, 3,5 s cada; a descrição entrou no texto da seção |
| Cópia da janela para o `/tela` | 0,53 s | 1280×720, só na memória |
| Resposta sobre o PDF anexado ("Resuma os passos do roteiro de VSL") | 12,3 s (1º texto em 3,6 s) | Equilibrado; o anexo foi a fonte S1, citada |
| Resposta sobre as telas da nota | 11,0 s (1º texto em 4,0 s) | trouxe textos que só existem nas imagens (endereços do GitHub, o pedido escrito na tela), mas sem marcar a citação |

- **Limite visto:** no Equilibrado (sem raciocínio), o `qwen3.5:4b` usou o texto das imagens e não escreveu o `[S1]`. É o mesmo comportamento de D27 e D31; o rodapé avisa "nenhuma citada".

## 01/11/2026 — Study AI 2.0, fase 3 (itens 4 e 5): níveis de esforço e Função inteligente

**Novo**
- **Quatro níveis de esforço** (`agent.EFFORT`, D31): Rápido, Equilibrado, Profundo e Máximo. Cada um define o modelo, o raciocínio (`think`), o número de fontes, quanto material entra, as rodadas de ferramentas e o tempo-limite. No Claude, define o `effort`.
  - **Máximo:** usa o modelo do esforço Máximo (Automático: `qwen3.5:9b`) e revisa o próprio rascunho antes de responder ("Revisando o rascunho…"). A revisão só vale se terminar inteira; senão fica o rascunho.
  - **Com raciocínio:** a tela mostra "Pensando…", sem despejar o raciocínio na resposta.
- **Função inteligente** (D32):
  - `search.understand()` agora também escolhe o esforço e diz o motivo;
  - regras novas para conversa ("oi", "me lembra o que eu disse"), cartões, "me testa", "em que ordem devo estudar", "o que ficou faltando" e "onde eu anotei";
  - "em detalhes" ou "aprofunde" pedem Profundo; "máximo de cuidado" pede Máximo;
  - uma skill do cofre ou do usuário, no automático, roda em Profundo.
- **Chip na caixa de mensagem:** "Automático · Explicar · Equilibrado", com o motivo na dica. Um clique abre o modo e o esforço para trocar.
- **Comando `/esforco`** (`rapido`, `equilibrado`, `profundo`, `maximo` ou `automatico`). Trocar pelo chip, por `/modo` ou por `/esforco` vale para os próximos pedidos e fica no registro de atividades como `troca-automatico`.
- **Configurações:** "Modelo do esforço Máximo".
- **"Informações" da resposta:** linha "Esforço".
- **Bench:** `bench/study_models_bench.py router` mede o roteador em 12 pedidos de ajuste e 14 novos.

**Alterado**
- **Rodapé da resposta:** quando nenhuma fonte foi citada, diz "8 fontes consultadas, nenhuma citada", com a dica de que o texto veio do conhecimento geral da IA.
- **Prompt do roteador:** explica cada intenção e prefere responder a montar um plano quando a pessoa só quer entender algo.
- **Regra de conversa por último:** "perfeito, agora faça flashcards" é pedido de flashcards. O modelo não escolhe o Máximo sozinho.
- **Última etapa sem ferramentas** no modelo local: o Rápido não fica mais sem resposta quando o modelo pede uma segunda busca.
- **Modelo local sem raciocínio ou sem ferramentas:** o erro do Ollama agora traz o motivo (`llm._stream`), e o pedido é refeito sem `think` ou sem ferramentas. Antes, a nova tentativa sem ferramentas nunca disparava.
- **Claude:** no Opus 4.6 e no Sonnet 4.6, o Máximo vai como `effort: max` (não têm `xhigh`).
- **Regenerar** repete o esforço da resposta que sai.
- **Trocas registradas:** só o que mudou em relação ao que o Automático decidiu; o chip não mostra mais um esforço escolhido à mão como se fosse automático.

**Medido com dados reais** (cópia do índice, a mesma pergunta nos quatro níveis):

| Nível | Tempo total | 1º texto | Modelo | Fontes | Citadas |
|---|---|---|---|---|---|
| Rápido | 20,8 s | 3,5 s | qwen3.5:4b | 4 | 0 |
| Equilibrado | 19,2 s | 3,7 s | qwen3.5:4b | 8 | 0 |
| Profundo | 26,2 s | 8,8 s | qwen3.5:4b | 14 (buscou de novo) | 3 |
| Máximo | 138,8 s | 58,1 s (carga do 9b) | qwen3.5:9b | 16 | 6, com revisão |

- **Rápido e Equilibrado:** as notas quase não falam de keyframes, e os dois responderam do conhecimento geral. Numa segunda rodada, o Rápido citou 2 fontes e o Equilibrado 0; a conferência não removeu nenhuma citação.
- **Roteador:** só as regras acertaram 12/12 e 12/14; regras mais `qwen3.5:4b` acertaram 12/12 e 14/14, com mediana de 2,5 s.

**Instalações:** nenhuma.

## 01/11/2026 — Study AI 2.0, fase 3 (itens 1 a 3): contexto, compactação e menu "/"

**Novo**
- **Medidor de contexto na caixa de mensagem** (ex.: "11 mil / 32 mil"):
  - mostra o uso medido na última resposta: `prompt_eval_count` do Ollama e `usage` do Claude (D30);
  - muda de cor a partir de 80%;
  - clicar abre o `/context`, com as partes aproximadas (instruções, memórias, resumo, histórico, fontes, pergunta e ferramentas).
- **Compactação não destrutiva** (`lumen/study/context.py`, D28):
  - **O que faz:** resume as mensagens antigas num JSON com tetos (D18), com o que o estudante disse de si, decisões, definições, perguntas em aberto e as fontes citadas pelo título. O resumo vai para a IA no lugar das mensagens resumidas.
  - **Quando:** sozinha, quando o pedido estimado passa de 90% do espaço de entrada; também por `/compact [foco]`, pelo botão do `/context` e por Ctrl+Shift+K.
  - **O que nunca entra no resumo:** as duas últimas trocas e as mensagens fixadas ("Mais opções → Fixar no contexto").
  - **Nada é apagado:** uma linha na conversa marca até onde a IA recebe o resumo.
- **Menu "/"** acima do campo, filtrável e navegável pelo teclado:
  - **Comandos:** `/ajuda`, `/clear`, `/compact [foco]`, `/context`, `/modo`, `/buscar`, `/temp`, `/memoria` e `/exportar`.
  - **Skills do sistema:** `/explicar`, `/resumir`, `/comparar`, `/encontrar`, `/flashcards`, `/quiz`, `/mapa`, `/plano` e `/lacunas`.
  - **Skills do cofre e do usuário:** cada uma vira um comando.
- **`/clear`:** começa uma conversa nova, com o mesmo projeto e o mesmo modo, e mostra "Desfazer" no aviso. Uma temporária limpa assim some como toda temporária (ao fechar o Lúmen ou em 24 h); até lá, o Desfazer a reabre.
- **Regenerar:** refazer uma resposta repete a mesma skill e o mesmo modo.
- **Mensagem fixada e desafixada depois de compactar:** continua indo inteira até a próxima compactação e então entra no resumo.
- **Registro único** (`lumen/study/registry.py`, D29): comandos, skills, ferramentas com o nível de permissão, integrações e modelos por papel, pela rota `GET /api/study/registry`.
- **Skills do cofre:** as 9 de `<cofre>/.claude/skills` aparecem no menu, lidas só para leitura. Rodar uma põe o corpo dela no prompt daquele pedido, com o mapa das ferramentas do Claude Code para as do Lúmen.
- **Banco:** a migração 2 acrescentou `conversations.summary`, `conversations.summary_upto` e `messages.pinned`.
- **Rotas:**
  - `GET /api/study/context`;
  - `GET /api/study/registry`;
  - em `POST /api/study/conversations`, as ações `compact` e `pin_message`.
- **Interface geral:** `ui.toast` aceita um botão de ação.

**Alterado**
- **Histórico:** o corte de 8 mil caracteres do histórico saiu. No lugar dele vale o resumo, e nada mais some da conversa sem aviso.
- **Janela de contexto por modelo (D24 revista):** 32k na família `qwen3.5` (o Automático) e 16k nos outros. Com 16k, uma conversa real compactava a cada turno a partir do 4º.

**Medido com dados reais** (cópia do índice, `qwen3.5:4b`, conversa de 5 turnos sobre o Premiere):
- **Estimativa:** o uso medido ficou entre 5,2 mil e 11,3 mil tokens, e a estimativa de 3 caracteres por token ficou de 14% a 23% acima do medido.
- **Com 16k:**
  - a compactação disparou no 4º turno (6,3 s) e de novo no 5º (10 s);
  - o resumo guardou "prova prática na sexta-feira";
  - a resposta do 5º turno, sem as mensagens do 1º, ainda trouxe a data e a matéria.
- **Com 32k:** nenhuma compactação nos 5 turnos, com 11,3 mil de 32 mil (34%). O modelo de chat (4,2 GB) e o de embeddings ficaram juntos na GPU.

**Testes**
- **`test_study_core.Context`, 8 testes:**
  - uso medido;
  - compactação que não apaga e não resume as fixadas (a desafixada entra no resumo seguinte);
  - compactação automática, e o aviso quando ela falha;
  - conversa curta;
  - conversa temporária;
  - skills do cofre e do usuário no menu e em uso (regenerar mantém a skill; skill inexistente não salva nada);
  - catálogo.
- **`test_study_core.Claude`:** depois de compactar, o pedido ao Claude leva o resumo no sistema e só texto nas mensagens.
- **`study_ui`, passo 7b:**
  - medidor e menu `/` pelo teclado, com a skill do cofre de teste;
  - `/compact` com a marca na conversa e `/context`;
  - fixar, Ctrl+Shift+K e `/clear` com Desfazer.

## 01/11/2026 — Study AI 2.0, fase 2: modelos medidos neste PC

O resultado completo está em `LUMEN_STUDY_AI_MODELS.md`.

**Alterado**
- **Modelo dos Estudos:** o campo vazio passou a ser "Automático", que hoje é o **`qwen3.5:4b`**, para responder e como modelo rápido (D23). Antes valia o `qwen3:8b` dos Ajustes.
  - Nos duelos às cegas, o `qwen3.5:4b` venceu o `qwen3:8b` por 18 × 6.
  - É 47% mais rápido (81 contra 55 tokens/s) e ocupa 3 GB a menos.
  - A tela mostra "Automático (qwen3.5:4b)", e a lista permite voltar a outro modelo.
- **Contexto:** todas as chamadas dos Estudos ao Ollama usam 16k, no lugar dos 32k fixos (D24).
- **Citações:** `[S1, S2]`, `(S3)`, `<S2>` e `【S1】` viram `[S#]` antes da conferência (D26). Antes essas citações sumiam da tela.
- **Prompt do chat:** a regra 9 diz quando usar as ferramentas. Sem ela, nenhum modelo local chamava ferramentas (D27).

**Corrigido**
- **Capa, mapa mental, gráficos e PDF pelo Edge:** voltaram a falhar em 01/11 sem nenhuma mudança no código.
  - **Causa:** o terminal que roda os testes é administrador. Nesse caso o Edge se reabre fora do modo administrador, e essa reabertura passou a travar antes de abrir o DevTools.
  - **Correção:** `lumen/cdp.py` passa `--do-not-de-elevate`. Os 30 testes de CDP, gráficos e mapa mental passam em 15,8 s.
  - A explicação de D19 foi corrigida.

**Novo**
- `bench/study_models_bench.py`: banco de provas dos Estudos.
  - **Medidas:** resposta com citações, roteador, JSON, ferramentas, juiz por rubrica, duelos às cegas e VRAM por tamanho de contexto.
  - **Uso:** instruções em `bench/README.md`.
- `docs/implementation/LUMEN_STUDY_AI_MODELS.md`: tabela e escolha por papel.
- **Testes** em `test_study_core`:
  - um único `num_ctx` em todas as chamadas;
  - o modelo Automático, com recaída no dos Ajustes;
  - a normalização das citações;
  - a regra de ferramentas.
- **Interface:** `study_ui` ganhou a conferência do Automático em Configurações → Modelos.

**Instalado**
- `granite4.2:8b` (IBM):
  - **versão:** 8,8 B de parâmetros, Q4_K_M;
  - **tamanho:** 5,3 GB;
  - **licença:** Apache-2.0;
  - **onde:** `D:\Ollama\models`;
  - **para quê:** candidato a modelo de chat, com ferramentas e raciocínio.
  - **Resultado:** não foi adotado. É o mais lento (42 s por resposta, 101 s de carga a frio), acerta 9 de 12 no roteador e ocupa 7,7 GB. Pode ser removido com `ollama rm granite4.2:8b` se o espaço fizer falta.

**Ollama**
- Nenhuma variável de ambiente foi alterada, e não é preciso reiniciar (D25).

## 31/10/2026 — Study AI 2.0, fase 1: mapa de conhecimento e auxiliar CDP

O plano por fases está em `%USERPROFILE%\.claude\plans\fluttering-petting-meadow.md`; as escolhas do usuário estão em D20 e D21.

**Corrigido**
- **Mapa de conhecimento:** voltou a ser gerado (D18).
  - **Antes:** com 8 fontes, falhava depois de 162 s, com o JSON cortado.
  - **Agora:** numa cópia do banco real (`qwen3:8b`, "Psicologia", 8 fontes), sai em **23,5 s**, numa chamada, com 14 conceitos, 8 documentos e 57 ligações.
  - **Teto nos esquemas:** todo array de `learn.schema()` (flashcards, questionário, plano, mapa e lacunas) e dos esquemas de memória, preferências e "entender" ganhou `maxItems`. Repetições saem em `_dedupe`.
  - **Resposta cortada:** vira `providers.Truncated` nos dois provedores e ganha uma tentativa enxuta.
- **Capa, mapa mental e gráficos das páginas:** voltaram a ser desenhados pelo novo `lumen/cdp.py` (D19). Estavam quebrados desde 20/10 com o Edge 155. Os 3 testes que falhavam (`test_charts` ×2 e `test_mindmap`) passam.

**Novo**
- `lumen/cdp.py`: `png(html, largura, altura, escala)` e `pdf(html)`, este com texto selecionável, links, marcação e marcadores, já pronto para os PDFs da fase 7.
- Testes:
  - `tests/test_cdp.py`;
  - em `test_study_core`: laço até o teto, nova tentativa enxuta, erro depois de dois cortes e tetos na saída estruturada do Claude;
  - `tests/fake_ollama.py` ganhou `json_raw` (respostas cruas com `done_reason`).

**Instalado**
- `websocket-client` **1.9.2**:
  - **o quê e para quê:** cliente do DevTools Protocol do `cdp.py`;
  - **licença:** Apache-2.0;
  - **tamanho:** 929 KB;
  - **onde:** `.venv`, registrado em `requirements.txt`;
  - **cache do pip:** em `D:\Lumen\cache\pip`.

## 31/10/2026 — redesenho minimalista da aba Estudos

Só a interface mudou: nenhuma rota, regra ou dado do backend. Detalhe de onde ficou cada coisa em `LUMEN_ADVANCED_INTELLIGENCE.md` → Interface.

**Diagnóstico da versão anterior**
- O cabeçalho tinha quatro linhas: rótulo, título, subtítulo e três pílulas de estado coloridas.
- As abas ficavam numa caixa.
- A coluna "Fontes utilizadas" era permanente, inclusive vazia.
- Cada resposta vinha numa caixa com borda, que era o cartão `.ai` de `app.css` aplicado por engano, e tinha uma linha técnica ("IA local · qwen3:8b · sem citações").
- Havia seis botões debaixo de cada resposta.
- O campo de mensagem tinha um ícone de busca e um texto de dica em volta.
- No histórico, cada conversa ocupava um cartão com data e número de mensagens.

**Removido da vista (a função continua)**
- **Linha técnica da resposta:** foi para "Mais opções → Informações da resposta".
- **Pílulas de estado:** viraram um indicador único, com painel ao clicar.
- **Coluna de fontes:** virou painel sob pedido, e nenhum espaço fica reservado.
- **Dica de teclado:** foi para a dica do botão Enviar.
- **Número de mensagens no histórico:** saiu.

**Agrupado**
- Aprofundar, 👍 e 👎 (com correção) e as informações da resposta ficam em "Mais opções".
- Renomear, fixar, mover, arquivar, exportar e apagar ficam no menu de contexto da conversa, pelo "⋯" ao passar o mouse ou pelo clique direito.

**Reorganizado**
- **Cabeçalho:** cabe numa linha.
- **Barra da conversa:** traz histórico, título, conversa temporária e Fontes.
- **Estado vazio:** a pergunta, o campo e as sugestões ficam centralizados.
- **Fontes citadas:** aparecem abaixo de cada resposta, com nome e origem.
- **Campo de mensagem:** ganhou um botão de enviar que acende com texto e vira "parar" durante a geração.

**Novo**
- **Painéis recolhíveis:** histórico e fontes ficam ao lado em telas largas e abrem por cima em janelas estreitas. Fecham com Esc ou com um clique fora.
- **Informações da resposta.**
- **Retorno ao copiar:** o ícone vira ✓ e o rótulo, "Copiado".
- **Animações curtas:** entrada das mensagens, painéis e menus, e um texto "Escrevendo…" com brilho. Todas são desligadas por `prefers-reduced-motion`.
- **Retomar:** só aparece quando o histórico está fechado.

**Fora da aba**
- `app.css`: o item ativo do menu lateral perdeu o brilho e a luz de borda, mas a marca azul ficou.
- `docs/DESIGN.md`: `study` entrou na lista de `showView`.

**Testes**
- `tests/study_ui.py` foi atualizado para o novo desenho, e as imagens novas estão em `tests/desktop-artifacts/study-ai-redesign-20261031`.
- A aba "Pesquisar e conversar" agora se chama **Conversar**. O modo "Só buscar" continua no seletor do campo.

## 31/10/2026 — primeira versão

**Novo**
- **Aba Estudos (Lumen Study AI):**
  - pesquisa e conversa com streaming e citações `[S#]` conferidas;
  - painel de fontes com o trecho usado e o link para o original;
  - histórico de conversas completo e conversa temporária;
  - projetos;
  - Estudar: flashcards com revisão espaçada, questionário com correção, plano, mapa de conhecimento e lacunas;
  - Salvos;
  - Fontes de conhecimento (Notion, Obsidian, pastas e internet);
  - Configurações da IA em 10 seções.
- **Backend:** pacote `lumen/study/` com 14 módulos, mais 4 conectores e 34 rotas `/api/study/*`, entre elas a de streaming NDJSON.
- **Memória:** 5 categorias, sugestões para aprovar, consolidação, importação da memória do Claude Code, exportar e limpar.
- **Gravação com prévia:** nota no Obsidian (`01 Outputs`, modelo Output IA) e página no Notion (dentro de "Lúmen Study AI").
- **Seus dados no Lúmen:** inventário, exportação, exclusão por categoria e retenção.
- **Testes:**
  - `tests/test_study_index.py`, `tests/test_study_core.py` e `tests/study_ui.py`;
  - `tests/fake_ollama.py`;
  - `tests/fake_notion.py`, que agora pagina os blocos filhos sem mudar o comportamento antigo.

**Alterado**
- `lumen/server.py`: rotas de estudo, arquivos estáticos novos e `Handler._stream`, que responde em NDJSON e cancela quando a conexão fecha.
- `lumen/web/index.html` e `lumen/web/app.js`:
  - botão "Estudos" no menu lateral e a nova tela;
  - destinos no Ctrl+K;
  - texto de privacidade dos Ajustes, que agora menciona o Claude opcional.
- `requirements.txt`: `anthropic==2.3.0` e `pypdf==6.21.4`.

**Corrigido durante a verificação real**
- **Notion:** a checagem do marcador da Proteção quebrava com blocos reais, porque ícones emoji têm `type` de texto. Agora só os blocos do nível de cima são lidos.
- **Memória automática:** estava ansiosa demais (D12).
