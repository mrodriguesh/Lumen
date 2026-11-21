# Prompt de continuação: Lúmen Study AI 2.0

> **Pedido novo concluído em 09/11/2026 (reorganização da aba Estudar):** não retomar fases antigas nem refazer a aba. A navegação é **Início → Objetivo → Atividade**
> (Revisar, Praticar, Planejar, Visualizar; 12 funções), atividades montadas uma vez e guardadas, rascunhos e sessões preservados (`lumen/web/study-learn.js`,
> bloco `.st-lrn*` de `study.css`, ganchos em `study.js` e `app.js`; D121–D126; seção "Estudar" de `docs/DESIGN.md`). Leia `LUMEN_ESTUDAR_REORGANIZACAO_20261108.md`
> e o topo do STATUS. Backend, rotas, contratos e dados não mudaram. Provas: `py -3.14 tests/estudar_ui.py` (16 blocos), `py -3.14 tests/study_ui.py`, suíte completa
> (resultado no STATUS). Falta o usuário **Sair pelo menu e reabrir o Lúmen** e avaliar o visual na janela de verdade (WebView2); a estética **não** foi aprovada por ele.
> Restauração: `D:\Lumen\restauracao\estudar-20261108` (+ suplementos `-implementacao-atual` e `-final`); evidências em `D:\Lumen\estudar-20261108\`. Sem commit.
> Falha intermitente conhecida e **fora do escopo** (módulo de proteção herdado): `tests.test_protection.Protection.test_file_changes_during_copy_preserves_previous`
> falha ~30% das vezes até isolada (depende de `background_yield` ser chamado durante a cópia). Não é regressão de Estudar; não foi alterada.

> **Pedido novo concluído em 08/11/2026 (conversa por voz natural):** não retomar fases antigas. Turnos isolados, Livre/Notas na chamada, fim de fala com pausas e interface nova
> (`lumen/study/call.py`, `study-call.js`, D107–D120). Leia `LUMEN_VOZ_CONVERSA_NATURAL_20261108.md` e `LUMEN_VOZ_TESTE_FINAL_20261108.md`. Falta a escuta e o microfone reais.
> Restauração: `D:\Lumen\restauracao\voz-conversa-20261108`. Sem commit.

> **Pedido novo concluído em 08/11/2026 (/elegrama 3d e /holograma 3d no chat):** não retomar fases antigas. A visualização 3D das aulas
> agora também sai na conversa (`lumen/study/holo.py`, artefato `holo`, D100–D106). Leia `LUMEN_STUDY_AI_ELEGRAMA_3D_20261108.md`. Falta o usuário
> Sair pelo menu e reabrir o Lúmen e conferir na janela de verdade (WebView2), e o Notion real. Restauração:
> `D:\Lumen\restauracao\elegrama-3d-20261108`. Processos ativos: nenhum (a instância isolada do Ollama na 11435 foi encerrada). Sem commit.

> **Pedido novo concluído em 08/11/2026 (perfil adulto):** não retomar fases antigas. Há um perfil de IA local separado (modelo
> `qwen3.5-heretic:9b`, configuração própria, troca automática por contexto e escolha manual), decidido em `lumen/study/adult.py`.
> Leia `LUMEN_STUDY_AI_PERFIL_ADULTO_20261108.md` e D92–D99. Falta o usuário Sair pelo menu e reabrir o Lúmen, ligar o perfil em
> Configurações → Perfil adulto (ou `aplicar-perfil-adulto.ps1`) e verificar à mão: janela nativa, microfone real e publicação real.
> Restauração: `D:\Lumen\restauracao\perfil-adulto-20261108`. Sem commit.

> **Pedido novo concluído em 08/11/2026 (modelo local com menos recusas indevidas):** não retomar fases antigas. Leia `LUMEN_STUDY_AI_MODELO_LIVRE_20261107.md` e D87–D91. A causa era o prompt do aplicativo (`SYSTEM` forçando fontes mesmo sem notas), corrigido com `SYSTEM_GENERAL`, a regra Postura e `has_sources`; modelos abliterados e Heretic foram medidos e **não adotados**; nenhum treinamento. Provas: suíte completa 845 OK, validação real 12/12, conjunto reservado travado por hash (`ledger.log` tem 7 execuções: não rodar de novo para ajustar prompts). Restauração: `D:\Lumen\restauracao\modelos-20261107`. Próxima ação: o usuário sair pelo menu e reabrir o Lúmen. Não repetir as medições sem mudança de modelo ou de prompt; sem commit nem push.

> **Retomada atual — 07/11/2026:** fases 1–9 implementadas; verificação técnica encerrada no ambiente isolado. Não iniciar fase nova nem refazer prática, Plano de ação, catálogo ou Treino falado. A entrega ainda depende das verificações humanas/externas do checklist final.
>
> **Provas novas de 07/11:** `D:/Lumen/validacao-fase9-20261105/ui-final-20261107.log` e resultado de mesmo prefixo: 31 verificações OK / 152,614 s, quatro larguras, foco, movimento reduzido, sem erros de página/CSP/HTTP 5xx; capturas inspecionadas e nenhum hash alterado durante a rodada. `integration-final-20261107.log`: 20 testes OK / 3,971 s. `video-real-20261107/report.json`: vídeo de controle de 6,393 s com transcrição/visão reais, persistência, reabertura e exclusão em 89,516 s. Nenhum processo de teste segue ativo.
>
> **Logs anteriores conferidos:** suíte completa de 06/11, 841 testes / 1187,788 s (`suite-final2.log`), 102 direcionados e 32 de regressão; fase 8, 817 testes históricos. Não dizer que foram executados novamente em 07/11. Desde a suíte completa, o único Python alterado foi a rota estática paralela `/cursor.js`; demais mudanças foram recursos da interface, agora validados.
>
> **Correção final:** a inicialização em `app.js` preserva a tela escolhida em vez de forçar Início. Teste de navegação reproduziu o defeito antes da correção e passou depois. O evento isolado de `OperationalError` de 06/11 não reapareceu; diagnóstico restrito à fixture e falha automática em 5xx foram acrescentados. Não inventar causa para o evento anterior.
>
> **Próxima ação exata:** usuário Sair pelo menu e reabrir normalmente; conferir persistência e atalhos no WebView2, voz/microfone/escuta cega e publicação real no destino escolhido. Instruções em `LUMEN_STUDY_AI_FINAL_CHECKLIST_20261106.md`. Não repetir abertura nativa bloqueada pela revisão automática (`blocked by policy`). Não repetir suítes sem mudança relevante ou nova falha.
>
> **Preservação:** checkout `estudos`, HEAD `88160399ce8858aa1dff3d976f0767e3f7595823`, trabalho rastreado e novo sem commit. Restauração completa `D:/Lumen/restauracao/study-final-20261106` (342 arquivos) e suplementos de foco, layout, diagnóstico e navegação, todos verificados. `study-final-navigation-20261106` contém app.js/teste antes da correção. Preservar visual, launcher, executável e provedores herdados/paralelos; não restaurar por cima.
>
> **Referências atuais:** topo do STATUS, relatório da fase 9, checklist final e D80–D86. Plano externo lido em 06/11, mas seu arquivo não existia no caminho original em 07/11; requisitos já conciliados permanecem documentados. Sem commit, push, limpeza ampla, instalação, troca de modelos pessoais ou atualização de memória global nesta conclusão.
>
> **Preferência do agente:** GPT-6 Astra, xhigh, selecionado na interface; não declarar troca nem mudar modelos do aplicativo.

**Direção do produto:** o Lúmen é a base do segundo cérebro do usuário e de tecnologias futuras; aprendizado é um de seus usos. Preserve fontes, autoria, contexto e permissão de escrita. Não ampliar a fase atual para construir integrações futuras sem pedido.

**Concorrência em 04/11:** o usuário confirmou outra sessão alterando o visual, launcher e executável. Preservar essas alterações e separar sua autoria. O backup de início da fase 7 está fora do projeto em `D:\Lumen\restauracao\study-fase7-20261104`. Não restaurar por cima do trabalho mais recente.

**Referências da fase 7 (verificações humanas pendentes):** `lumen/study/artifacts.py`, `lumen/study/pdf.py`, `tests/test_study_pdf.py`, passo 13 de `tests/study_ui.py`. Os PDFs leem as notas encontradas pela ferramenta `read_document`; a busca podia trazer só seções de estrutura. Revisão usa até 6 blocos e ajuste limitado a 90% para caber em uma página, sem esconder conteúdo; se ainda não couber, informa erro. PDFs de estudo permanecem limitados a 30 páginas. Não repetir a migração de `image_dir`, reinstalar motores ou revelar a chave da escuta cega.


---

Você está continuando a implementação do Lúmen Study AI 2.0, a aba Estudos do app Lúmen. O estudante usa o app todos os dias, e cada sessão deve deixá-lo um passo mais perto de pronto, sem quebrar o que já funciona.

## 1. Situe-se, sem refazer o que já foi feito

Leia, nesta ordem:

1. `docs/implementation/LUMEN_STUDY_AI_STATUS.md`, seção **Study AI 2.0**. Ela diz qual fase é a próxima e qual é o próximo passo.
2. `docs/implementation/LUMEN_STUDY_AI_DECISIONS.md`. **As decisões mais recentes (D20 em diante) valem mais que o pedido original.** Por exemplo: diagrama interativo 2D no lugar de holograma 3D, revisão em áudio no lugar de vídeo, e web por pesquisa guiada no Edge.
3. O plano aprovado, em `%USERPROFILE%\.claude\plans\fluttering-petting-meadow.md`.
4. O prompt da fase atual, pela tabela abaixo. Se houver um prompt próprio da fase, **ele vale mais que o V2** naquilo que trata; o V2 continua valendo para o resto.
5. Só se houver dúvida, o `LUMEN_STUDY_AI_CHANGELOG.md`.

| Fase | Prompt |
|---|---|
| 6: voz, resumo e revisão em áudio, "ver na aula", Treino falado e Feynman | `PROMPT_LUMEN_VOZ_VOICE_STUDIO.md`, com as decisões D46 a D52. O motor é o **Voice Studio** do estudante, com a voz clonada do Jhonny (perfil `1faf41ee`) como padrão. O Chatterbox (D44) é a reserva |
| 6, parte 2: Voice Studio sem janela, modelos no Lúmen, otimização e funções extras | `PROMPT_LUMEN_VOICE_STUDIO_V2.md`, com as decisões D53 a D60. Pronta no código em 02/11, com escutas cegas feitas e modelos movidos para o D:; falta só o teste do estudante abrindo/fechando o app na janela real (STATUS → Próximo passo). **Vem antes da fase 7** |
| 6, parte 3: conversa por voz em tempo real (chamada, como o modo de voz do ChatGPT) | `PROMPT_ARGON_CHAMADA_DE_VOZ.md`, com as decisões D61 a D65. Pronta no código, testada e medida em 02/11 (24 turnos contínuos em 10 min); aguarda a escuta cega do 1º pedaço (`D:\Lumen\voz\amostras-chamada\escuta-cega`) e o teste de 2 min no microfone real. **Vem antes da fase 7**, a pedido do estudante (02/11) |
| 7 a 9 | A seção da fase em `PROMPT_LUMEN_STUDY_AI_V2.md` |

Quando uma fase ganhar um prompt próprio, acrescente uma linha nesta tabela.

**Antes da fase nova, feche o que depende do estudante.** Veja no `STATUS` se alguma fase anterior espera uma escolha dele, como a escuta cega da fase 6 (amostras em `D:\Lumen\voz\amostras-vs`, com a chave em `chave.json`, que só deve ser aberta depois que ele escolher). Se ele já respondeu nesta conversa, aplique a escolha, registre e só então siga. Se ainda não respondeu, pergunte uma vez, curto, e trabalhe na fase seguinte enquanto ele não responde.

As pendências que não bloqueiam (por exemplo, o Treino falado da fase 6) entram quando a fase atual terminar com folga, ou quando o estudante pedir.

Confira com `git status` e com os testes da última fase pronta se o estado do repositório bate com o `STATUS`. Se algo não bater (uma fase marcada como pronta com teste falhando, ou arquivos pela metade), conserte isso primeiro e registre o que aconteceu.

## 2. Trabalhe na próxima fase até ela ficar pronta

- Continue para a próxima pendência aprovada executável; não encerre automaticamente ao terminar uma fase.
- Siga os critérios de pronto do prompt da fase (o próprio, se houver, ou o V2), com as mudanças das decisões D20 em diante.
- **Fase grande:** divida pelas etapas do prompt da fase. Cada etapa termina testada antes da próxima, e o `STATUS` diz em qual etapa a sessão parou.
- **Prove o que fizer:**
  - testes unitários da parte mexida;
  - um passo em `tests/study_ui.py` para o que aparece na tela;
  - medição com dados reais em modo só leitura, com banco temporário via `LUMEN_DATA`.
- No fim da fase:
  - rode a suíte inteira com `-t .`;
  - peça a um subagente com contexto novo, num modelo mais barato, para conferir o resultado contra os critérios da fase.
- **Instalar:** você tem autorização para instalar sem perguntar, desde que seja grátis, de fonte oficial, no D:, sem quebrar o que existe e registrado. As condições completas estão no topo do prompt V2.
- **Pergunte só o que bloqueia:** escolhas que só o estudante pode fazer, desinstalar ou substituir algo que o app usa, e qualquer coisa que custe dinheiro. Para o resto, quando tiver informação suficiente, aja.

## 3. Deixe a próxima sessão pronta para continuar

Antes de terminar a sessão, mesmo que a fase tenha ficado pela metade:

- Atualize no `STATUS` a tabela de fases e o **Próximo passo**. Ele deve ser concreto o bastante para outra sessão começar sem reler tudo: arquivo, função, o que falta e como provar.
- Registre em `DECISIONS` as decisões novas (com o motivo) e em `CHANGELOG` o que mudou, incluindo cada instalação com versão, tamanho, local e licença.
- Registre as lições e o estado de continuidade nos documentos do projeto. Não atualize memórias globais sem pedido explícito do usuário.
- Identifique processos e temporários desta execução. Preserve evidências e arquivos herdados; não faça limpeza ampla nem remova conteúdo pessoal.
- Commit só se o estudante pedir.

## 4. Estágio final

Quando todas as fases do `STATUS` estiverem prontas:

1. Rode a suíte inteira e `tests/study_ui.py` em 1100, 760 e 520 px.
2. Percorra o checklist "Pronto quando" do prompt V2 e dos prompts próprios das fases, ajustado pelas decisões D20 em diante. Para cada item, aponte a prova: teste, medição ou captura. O que não tiver prova fica marcado como não verificado.
3. Faça uma verificação real de ponta a ponta com o cofre e o Notion do estudante, em modo só leitura, com os modelos padrão.
4. Atualize `STATUS` e `DECISIONS` para o estado final, e a memória do projeto.
5. Entregue um relatório final ao estudante.
6. Peça a ele para **sair do Lúmen pelo menu e abrir de novo**, porque o app aberto guarda o código antigo. Depois disso, ele mesmo testa na janela real.

## Regras que sempre valem

- **Nunca toque no `%LOCALAPPDATA%\Lumen` real em teste.** A configuração real já foi sobrescrita uma vez.
- **Não mate o Lúmen aberto.** Ao renderizar a instância oficial, bloqueie `/api/bye`.
- **Sem automação de mouse ou teclado** nos seus testes: use Edge headless com CDP (`lumen/cdp.py`). O terminal é administrador, então todo Edge aberto pelo Python precisa de `--do-not-de-elevate` (D19).
- **Não pare nem reinicie o Ollama do estudante.** O Lúmen aberto responde 403 sem o token da janela, então não dá para saber de fora se há aula sendo processada. Para testar ajustes do Ollama, use um segundo `ollama serve` na porta 11435.
- **`tests/study_ui.py` roda com `py -3.14`** (é ele que tem o Playwright). O servidor do teste importa `tests`, que troca o `LUMEN_DATA` por outra pasta temporária: peça os caminhos ao próprio servidor.
- **O C: está quase cheio:** nada grande vai para lá, nem caches.
- **Não reinstale `onnxruntime`** junto com o `onnxruntime-directml`.
- **Orçamento zero:** nada pago, e o Claude dentro do app nunca é necessário para nenhuma função.
- **O Voice Studio é do estudante** (`http://127.0.0.1:3900`, dados em `%APPDATA%\OmniVoice`). O Lúmen fala com ele só por HTTP, e quem chama é o backend, nunca o navegador. Não escreva no banco dele, não apague, edite nem trave vozes, não desligue a marca d'água e não feche, reinicie ou descarregue o modelo enquanto ele usa o app. Nos testes, use o Voice Studio falso dos testes.
- **A placa (RTX 3060, 12 GB) é dividida** entre o Ollama e o motor de voz: uma voz carregada por vez, e `llm.release_vram()` antes de gerar áudio longo.

## Como relatar no fim de cada sessão

- **Comece pelo resultado:** que fase avançou, o que funciona agora e o que o estudante precisa fazer, se houver algo.
- **Mostre as provas:** testes com o número que passou e o que falhou (com a saída), medições reais e tamanhos instalados.
- **Só afirme o que conferiu nesta sessão.** O que ficou sem verificar, diga que ficou.
- **Termine com o próximo passo,** o mesmo que ficou no `STATUS`.
- Escreva em português, com frases completas e sem abreviações inventadas durante o trabalho. Quem lê não viu as chamadas de ferramenta.
