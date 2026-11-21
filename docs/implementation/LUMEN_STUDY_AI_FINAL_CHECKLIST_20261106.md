# Verificação integrada do escopo aprovado — atualizada em 07/11/2026

Estado: implementação das fases 1–9 presente e verificação técnica encerrada em ambiente isolado. Não equivale a validação humana, janela nativa ou publicação na conta real. A versão original do V2 é conciliada abaixo com o plano aprovado e D20–D86; critérios substituídos não são silenciosamente marcados como concluídos. Não há nova fase de implementação identificada; as pendências finais estão separadas abaixo.

| Requisito atual | Implementação e prova | Limite restante |
|---|---|---|
| Mapas e ausência de laços até o teto | `learn`, validação/repetição limitada; `test_study_core.Agent`; medições históricas em MODELS | Qualidade semântica do modelo continua variável |
| Modelos medidos e papéis definidos | MODELS, D21–D27, registro e configurações existentes; testes de provedores | APIs externas reais dependem de chave/escolha; não houve instalação nova nesta fase |
| Contexto real, compactação não destrutiva, `/clear`, `/context` | `context`, `chats`, `registry`; testes Core/Context/Claude e passos 7b/7c de study_ui | Atalhos da janela nativa ainda precisam de confirmação |
| Comandos/skills e permissões | Registro único, skills editáveis/ativáveis/revisões; testes Catalog/Context/Agent e passo 15 | Skills do cofre continuam somente leitura; sem execução de código |
| Quatro esforços e Automático | `agent.EFFORT`, `search.understand/adapt`; testes Effort/Router, medição histórica de roteamento | Contagens ajustam só escolhas implícitas; não alteram pesos |
| Anexos/imagens citáveis e origem preservada | `attachments`, `images`, testes da fase 4, prática com arquivo no passo 15; vídeo de controle com ASR/visão reais em 07/11 | Arquivos gerados por IA não viram evidência; clipe de controle não comprova todos os vídeos pessoais longos |
| Explicação avançada e diagrama | `explain`, `diagram`, testes e passos de interface da fase 5 | D41 substituiu holograma 3D girável por diagrama 2D interativo; pergunta rápida foi substituída no plano pelo ponto de partida a partir de notas e mastery |
| Voz, chamada, Treino falado e Feynman | Implementação/testes da fase 6; provas reais históricas em STATUS/MODELS | Microfone real, fone/caixa, interrupção e escuta cega do primeiro trecho dependem do usuário; não capturados automaticamente |
| Imagens/PDFs temáticos e renderizadores | `artifacts`, `pdf`, `cdp`, testes da fase 7 e passo 13; nove tipos, A4 claro/escuro, tema automático | D20 excluiu vídeo-aulas/clipes de difusão do escopo; recursos de vídeo de alterações paralelas não são nova fase nem prova de validação |
| Criar, prévia, link, desfazer, aplicativos e web | `writes`, `apps`, `browser`; testes da fase 8 e passo 14; pesquisa real histórica | D74–D79 limitam criações às áreas da IA e navegador à pesquisa guiada; não há controle livre nem “Assumir” formulários. Notion real de escrita requer destino escolhido e releitura |
| Prática e domínio | `applied.submit`, `learn`, `mastery`, `test_study_applied`; geração/correção real isolada e passo 15 | Correção da IA não prova domínio real; usuário pode revisar os critérios e a entrega |
| Plano aplicado, revisões e Pomodoro | `applied.action/due`, eventos existentes; testes de idempotência/persistência; plano real isolado | Timer armazena último evento; não conta retroativamente sessões não observadas |
| Catálogo final | `registry.catalog`, `study-settings`; testes Catalog e passo 15 | Modelo/VRAM/tamanho sem dado ficam desconhecidos; detalhes e ações são reutilizados nas seções de modelos/voz |
| Avaliação e dados visíveis/exportáveis/apagáveis | `evaluation`, CLI, `data`; testes Evaluation/Router; fonte de controle local | Juiz é o próprio modelo; triagem pode errar. Leitura real de Notion/Obsidian nesta fase não foi publicação |
| Persistência/reabertura | SQLite fechado/reaberto nos testes e benchmark; recarga da página no passo 15 | Executável oficial abriu isoladamente, mas CDP não ficou acessível; tentativa de abrir outra instância para checagem GUI foi bloqueada pela revisão automática |
| Suíte/interface/distribuição | Suíte completa 841/841 (06/11); interface final 31/31 e integração 20/20 (07/11); hashes estáveis, exe inalterado, nenhum C# alterado por esta fase | Validação nativa não concluída; não tratar o navegador como WebView2 oficial |
| Instalações e recuperação | Nenhuma instalação nesta fase; histórico em DECISIONS. Restaurações Nov5, Nov6 e `study-final-20261106` | Origem da migração de imagem no C: preservada; limpeza histórica bloqueada continua fora desta entrega |

## Provas novas de 07/11

- `ui-final-20261107.log` / `ui-final-20261107-result.json`: 31 verificações OK / 152,614 s; quatro larguras, foco visível, movimento reduzido, sem erros de página/CSP/HTTP 5xx. `backend.log` vazio, hashes sem alterações, capturas relevantes inspecionadas. A falha de navegação foi reproduzida antes da correção em `ui-navigation-before3.log`.
- `integration-final-20261107.log`: 20 testes OK / 3,971 s, widget/servidor, tokens visuais e identidade. Sintaxe de app.js aprovada.
- `video-real-20261107/report.json`: clipe sintético de 6,393 s, transcrição/visão reais em 89,516 s, 1 quadro e 207 caracteres, fonte citável, persistência/reabertura/exclusão. Configuração pessoal intacta, sem mic ou mídia pessoal.
- Nenhuma execução desta retomada continua ativa. A rota estática `/cursor.js` adicionada paralelamente foi a única diferença Python desde a suíte de 841; nenhuma lógica dos Estudos mudou. Interface final cobre os recursos atuais.

## Provas de 06/11 conferidas nesta retomada

- `suite-final2.log` / `suite2-result.json`: 841 testes OK / 1187,788 s (1192,178 s com descoberta).
- `focused-final2.log`: 102 testes OK, 72,480 s.
- `regressions.log`: 32 testes OK, 15,832 s.
- `ui-20261106.log`: 30 verificações OK, quatro larguras, zero erros de página/CSP; anterior aos últimos ajustes.
- `real/report.json`: duas fontes reais lidas, 13 GETs do Notion, geração de prática/correção/plano e reabertura do banco. Tempos e limites no relatório da fase 9. Configuração pessoal não mudou.
- `suite-final.log`: 839 testes, 9 falhas e 60 erros; causas corrigidas, não contar como aprovação.
- `native/report.json`, `native2/report.json`: tentativas negativas de CDP no executável oficial. As duas instâncias próprias foram encerradas; o Lúmen pessoal permaneceu ativo. Tentativa posterior de abertura via ferramenta foi bloqueada com “blocked by policy”; nenhum contorno.

## Prova histórica apenas conferida

- Fase 8: `D:\Lumen\validacao-fase8-20261104\suite-final-2.log`, 817 testes OK, 1183,345 s. Interface anterior: 29 verificações. Não executados de novo como se fossem prova desta sessão.
- Medições de voz/modelos/PDFs das fases anteriores continuam identificadas pelas datas nos relatórios. Não foram repetidas nem convertidas em validação nativa.

## Verificações humanas e externas

1. Sair do Lúmen pelo menu e reabrir normalmente para carregar o Python e os recursos atuais. Não é necessário rebuild do launcher para a fase 9.
2. Em Cérebro → Estudar, abrir uma prática e plano, conferir anexo/correção, fechar e reabrir a janela, conferir persistência; testar teclado e os atalhos de contexto.
3. Na chamada por voz, testar falar/parar/interromper com seu microfone, usando fone e depois caixa; conferir saída de áudio e a escuta cega sem alterar a escolha automaticamente.
4. Quando escolher publicar um item real no Notion, usar o destino já escolhido/prévia, confirmar o arquivo/bloco persistido e só então testar desfazer se não houver edições posteriores.

Nenhum desses itens está concluído sem prova do usuário/acesso correspondente. Falta técnica conhecida em código ou suíte continua sendo trabalho do agente, não deve ser transferida para esta lista.
