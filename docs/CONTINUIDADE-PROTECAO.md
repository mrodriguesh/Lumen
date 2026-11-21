# Ajuste de 31/10/2026 — Google Drive visível no backup automático

Só tela ([protection.js](../lumen/web/protection.js)); o backend não precisou mudar.

- **Problema:** no backup automático, “Guardando alterações” listava só os trabalhadores com atividade naquele instante. O Drive, esperando o snapshot, não aparecia.
- **Agora** a lista traz sempre as seis etapas, em backup pedido ou automático. O Drive diz, conforme o estado real: “Desativado nas configurações (não consome cota)” (ícone de pausa), “Aguardando a conclusão da leitura das notas…” e “Na fila para sincronizar…” (relógio), “Enviando para o Google Drive…” com a barra de bytes, ou “Sincronizado na nuvem” (confirmação). “Sincronizado” só aparece quando o destino está com a cópia mais recente confirmada (`places.drive.state == ok`), mesmo que uma leitura esteja em andamento; só esperar não vira sucesso. Falha e conexão perdida aparecem como tal. Os outros destinos seguem a mesma regra (“Em dia”, “Na fila para atualizar…”).
- **Backend, conferido:** `loop("drive")` já publica a atividade `copying` ao iniciar o ciclo e `protection_drive` publica `uploading`/`checking` com bytes; com o Drive desligado o ciclo nem começa. Não mudei a cadência de 10 s: acordar todos os trabalhadores a cada snapshot faria o Obsidian e o Notion lerem de novo sem necessidade. Teste novo: o ciclo do Drive reporta atividade ligado e nada desligado.
- **Prova:** bloco 8b de `tests/protection_ui.py` (as cinco fases, com imagens em `tests\desktop-artifacts\protection-drive-activity-20261031`) e `unittest` de `test_protection*`. Janela nativa não testada; a tela vale sem reabrir o Lúmen.

# Ajuste de 31/10/2026 — seções inferiores em cards

Só tela ([protection.js](../lumen/web/protection.js), [protection.css](../lumen/web/protection.css)); nenhum arquivo do backend mudou.

- As três sanfonas finais viraram cards, criados por `card()`: ícone temático (`download` com tom de destaque, `key` âmbar, `gear` neutro), título, selo e uma linha explicando para que serve, tudo visível antes de abrir. A seta do navegador foi trocada por um chevron que gira 180° ao abrir (sem animação com “reduzir movimento”). O conteúdo fica em `card.body`.
- Nomes novos: “Recuperar minhas notas” (Restauração), “Segurança e chave mestra” (Criptografia), “Detalhes técnicos e pasta” (Ajustes). “O que precisa de atenção”, “Ver detalhes” e as demais sanfonas não mudaram.
- Botões: principais “Ver minhas cópias salvas”, “Guardar minha chave de recuperação” e, quando aparecem, “Recuperar a cópia escolhida” e “Recuperar do Drive”. Os outros (“Usar uma chave que já tenho”, “Procurar minhas cópias no Drive”, “Abrir pasta das cópias”, “Trocar a pasta das cópias”, “Conectar Google Drive”, “Abrir uma cópia de outro lugar”, “Recuperar no Notion”) são com borda fina. Ações e `loadVersions` não mudaram.
- Prova: `tests/protection_ui.py` (bloco 7c, navegador isolado, janela e widget) confere ícone, selo, microcópia, seta girando e qual botão é principal; imagens em `tests\desktop-artifacts\protection-cards-20261031` (`cards-closed.png`, `cards-open.png`). `unittest` de `test_protection` e `test_protection_overview` passou. A bateria completa da etapa anterior (Drive opcional): 602 testes, só as 3 falhas conhecidas do Edge.
- Limite: janela nativa não testada; a tela nova aparece sem reabrir o Lúmen.

# Ajuste de 31/10/2026 — Google Drive opcional e status do Drive em toda resposta

Registro mais recente. Vale sobre as seções abaixo no que tocar o Drive.

## O que mudou

- **Status do Drive perdido.** `POST /api/protection` devolvia `view()` sem a chave `drive`, e `v.drive?.connected` ficava indefinido depois de qualquer ação. `view()` agora inclui `drive` (de `gdrive.status()`, chamado uma vez e reaproveitado em `places()`); a rota GET deixou de montar o próprio dicionário.
- **Drive opcional.** Novo campo `drive_enabled` em `configuration()`, salvo em `config.json`, com a ação `drive-enable` (`enabled` explícito, não “alternar”). Desligar não desconecta a conta, não apaga nada do Drive e não altera o backup automático.
  - **Padrão e migração:** sem escolha salva, começa desligado, **exceto** onde já existe cópia confirmada no Drive (`state.drive.confirmed`): ali começa ligado, para a atualização não parar um envio que já funcionava. A escolha salva sempre vale mais. Uma vez que qualquer `configure()` roda, o valor derivado fica gravado.
  - `loop("drive")` não roda sem pedido manual quando desligado; `drive_cycle()` sai sem erro e confere a opção entre uma versão e outra (nunca no meio de um envio).
  - Pedido manual de backup com o Drive desligado termina `completed`: o passo do Drive fecha como `done`, sem erro e sem envio. A tela esconde esse passo.
  - `places()`: novo código `disabled` (“Desativado por você”), que não vira atenção nem pendência e mantém o que o Drive já guarda (`held`, agora com `objects`, a contagem de objetos do catálogo confirmado). O cabeçalho “Suas cópias estão em dia” trata `disabled` como resolvido, e a frase de cobertura não afirma backup no Drive enquanto ele está desligado.
- **Tela** ([protection.js](../lumen/web/protection.js)): botão “Desativar backup no Drive” / “Ativar backup no Google Drive” (`aria-pressed`) com aviso de cota limitada; a linha do Drive mostra “N objetos confirmados” por origem, a data da última confirmação e “Abrir pasta no Drive” (antes “Ver cópias”). Backend antigo, sem `drive_enabled`, é tratado como ligado.
- **Card “Para que serve cada cópia”:** três itens (neste computador, Google Drive, espelhamento Notion ↔ Obsidian), só texto fixo, sem estado. Usa `--surface-1`/`--surface-2`; empilha no widget.

## Provas

- `unittest` de `test_protection`, `test_protection_overview`, `test_protection_progress`, `test_protection_attention` e `test_protection_hierarchy`; os testes novos cobrem `drive` na `view()`, padrão e migração, `disabled`, `drive_cycle` desligado/ligado e pedido manual concluído. Testes antigos que dependiam do Drive ligado passaram a pedir `drive_enabled=True`.
- Ação `drive-enable` chamada em `_protection_action` com dados isolados: ligar/desligar/ligar e uma ação seguinte (`pause`) sempre devolvem `drive`.
- `tests/protection_ui.py` (navegador, dados isolados): novo bloco 7b (card, objetos só no Drive, desligar sem alarme, passo oculto, religar) e card no widget. Imagens: `tests\desktop-artifacts\protection-drive-20261031` (`drive-disabled*.png`, `widget-types.png`).
- `pytest` não está instalado neste `.venv`; a suíte do projeto é `unittest`.

## Limites

- O backend só carrega ao abrir: no Lúmen aberto, o JS novo funciona com o backend antigo (Drive tratado como ligado, sem o botão ter efeito até reabrir). Para valer, Sair pelo menu e reabrir quando nenhum backup estiver rodando.
- Não foi verificado envio real ao Drive com o botão; as provas usam recibos e simulações. Janela nativa não testada.
- Ponto de restauração dos arquivos antes da mudança, com SHA-256, na pasta de rascunho da sessão (`restore-drive`).

# Ajuste de 31/10/2026 — seção “O que precisa de atenção”

Registro vigente desta seção. As seções abaixo são históricas; seus testes não foram reexecutados aqui, salvo quando citado.

## Antes

Imagens: `D:\Aplicativos\Lumen-protecao-atencao-20261031\antes-*.png`, de cópias do estado pessoal num servidor isolado. Problemas encontrados:

- Cada aviso repetia três rótulos: “O que aconteceu”, “O que já está guardado” e “O que fazer”.
- O título da seção era sempre amarelo, mesmo quando nada exigia ação.
- “Tentar novamente” aparecia como saída geral, inclusive para limitações permanentes do Notion. “Conferir pendências das notas” não tinha finalidade clara.
- As 8 versões preservadas apareciam com a mesma cara de um problema atual.
- A frase “Não há perda do texto da nota” afirmava mais do que os dados comprovam.
- `issuesLoaded` carregava os avisos das notas uma única vez. Uma pendência nova não aparecia, uma resolvida não saía, e não havia proteção contra resposta antiga.
- `replaceChildren` recriava a lista, fechando detalhes e tirando o foco.
- Avisos de destino com conflito ou nota incompleta duplicavam os avisos por nota.

## O que mudou

- **Backend** (`lumen/protection.py`): cada aviso de `attention_details()` traz:
  - `cause`, para agrupar;
  - `tone`: `review` para conteúdo a conferir, `info` sem ação;
  - título curto (`headline`), uma frase (`summary`) e `details`;
  - `action`: `notion-page`, `locate`, `notion-area` ou `connect-notion`.

  Avisos idênticos (mesma página e mesma causa) aparecem uma vez. O campo `kind` foi mantido, porque `bench/protection_reconcile_metadata.py` o lê; o script não foi executado. `view()` ganhou `attention_key`, que muda quando uma pendência do Notion, uma diferença, uma estrutura ou uma nota Obsidian → Notion aparece ou é resolvida.
- **Tela** (`protection.js`/`.css`; janela e widget):
  - introdução curta: “Nenhuma ação necessária.”, “Nada impede as cópias…” ou “Comece pelo primeiro aviso…”;
  - contagem só de pendências reais e distintas: “· 1 precisa de ação · 2 para conferir”;
  - avisos em ordem, todos com ícone e texto: **Precisa de ação** (amarelo), **Para conferir** (azul) e **Aguardando** (neutro);
  - cada aviso tem título curto, nome real da nota ou do destino, uma frase, no máximo uma ação e “Ver detalhes” recolhido;
  - a mesma causa em várias notas vira um único aviso com a lista e uma ação por nota; acima de 4 notas, a lista fica recolhida;
  - versões preservadas ficam num bloco discreto (“8 versões antigas preservadas · nenhuma ação necessária”), fora da contagem, com “Localizar” por nota;
  - “Refazer backup completo” só aparece para falha de destino, de leitura ou do pedido, e “Ver detalhes” explica que o backup inteiro é refeito. Com o automático pausado, alterações não copiadas oferecem “Fazer backup agora”; com o automático ligado, ficam como “Aguardando”, sem botão. As duas ações reutilizam o botão principal e sua proteção contra pedidos duplicados.
- **Atualização**:
  - os avisos das notas recarregam quando `attention_key` muda e sempre que a seção é aberta;
  - um número de série descarta respostas antigas;
  - a falha da consulta mantém o último conteúdo, com “Mostrando a consulta de …”, e tenta de novo;
  - os elementos são reaproveitados por chave, então “Ver detalhes” aberto, foco e rolagem são preservados;
  - um backend ainda não reiniciado (formato antigo) é mostrado aviso a aviso, sem agrupar errado.

## Provas desta rodada

Evidências: `D:\Aplicativos\Lumen-protecao-atencao-20261031`. Imagens do navegador: `tests\desktop-artifacts\protection-attention-20261031`.

- **Backend**: `tests.test_protection_attention` e `tests.test_protection_overview`, com 21 testes aprovados. Dois são novos ou ampliados:
  - limitações permanentes dizem que repetir o backup não ajuda e não falam em “perda”; nenhuma duplicata;
  - tons e ações de diferença e versão preservada; a chave muda quando a pendência surge e volta ao valor anterior quando ela é resolvida.
- **Bateria completa** (`suite-completa.txt`): **598 testes** em 677,7 s, com 595 aprovados e as 3 falhas conhecidas do Edge `--screenshot` (`test_charts` ×2 e `test_mindmap`), sem relação com a proteção. As datas de modificação da configuração pessoal ficaram iguais.
- **Navegador** (`tests/protection_ui.py`, Chrome headless, backend isolado, aprovado com o código final: **42 verificações** nomeadas em `interface-navegador.json` e 38 imagens). Verificações novas:
  - nenhuma pendência;
  - pendência surgindo e sendo resolvida;
  - três páginas com a mesma causa em um aviso, com contagem 4 em vez de 6, sem somar versões preservadas;
  - ação abrindo a página certa;
  - conflito com “Localizar nota”, sem sobrescrever;
  - detalhes abertos, foco e rolagem mantidos após atualização;
  - resposta antiga descartada;
  - reabrir mostra o momento atual;
  - falha da consulta com conteúdo preservado e recuperação;
  - falha só do Drive: “A cópia neste computador foi confirmada. Falta terminar o envio ao Drive.”;
  - “Refazer backup completo” com três cliques gera um único pedido;
  - ações de abrir continuam ativas durante o backup;
  - pausado oferece ação, ligado mostra “Aguardando”;
  - seis notas com títulos longos, em 1120 px e 760 px;
  - Tab, Shift+Tab, Enter e Espaço, com foco visível;
  - widget com os mesmos avisos e contagem.

  As imagens foram observadas, o que levou a três correções: linhas da lista altas demais; frase do grupo depois da lista; título espremido no widget, onde o link agora vai abaixo.
- **Dados pessoais, servidor isolado sobre cópias** (`depois-*.png`, `depois.json`): “2 para conferir”. Os avisos são o ícone de bloco de destaque em **Template - Ficha de Lead | Barbearia** e o bloco não disponibilizado em **Personalidade**, ambos reconfirmados no estado atual, mais 8 versões preservadas à parte. Em `destinos-dos-avisos.json`, com navegador e Explorador interceptados, os 10 destinos (2 páginas no Notion e 8 notas preservadas) conferem. Configurações pessoais com hash inalterado.
- **Instância oficial** (só leitura, POST bloqueado exceto a consulta `attention`, sinal de fechamento bloqueado; `oficial*.png`, `oficial.json`): JS e CSS servidos idênticos aos arquivos. O backend em memória é o anterior, iniciado às 13:53. A seção usa o layout novo com os textos antigos (por exemplo, “Não há perda do texto da nota”) até o Lúmen ser reaberto.

## Limitações e pendências

- **Reabrir o Lúmen.** O backend (`protection.py`) mudou, então é preciso sair pelo menu e abrir de novo. Recarregar só a janela não traz os textos novos dos avisos. Na conferência, o backup automático estava **ligado** e trabalhando; nada foi interrompido. O launcher não mudou e não foi recompilado.
- **Janela nativa.** Não foi testada nesta sessão: não há ferramenta de controle da tela disponível. A validação foi em navegador.
- **Ponto de restauração:** `D:\Aplicativos\Lumen-restauracao-protecao-atencao-20261031-135957\restauracao.zip`, com 84 arquivos, `sha256.json` e releitura conferida. Não contém chaves.

---

# Ajuste de 31/10/2026 — remoção de “O que guardar”

- Removido do DOM o painel “O que guardar” no componente compartilhado pela janela principal e pelo widget. Saíram a lista de páginas, o campo de link, os botões de seleção, a consulta de títulos e a atualização dessa lista. Removidos os estilos exclusivos. “Recuperar minhas notas” continua antes de “Segurança e recuperação”, agora sem depender do painel removido.
- Cofre e raízes continuam vindo de `protection.configuration()`: a configuração persistida de proteção prevalece sobre os padrões de `store.load_config()`. O motor e as rotas do backend foram preservados. Não foram gravados caminhos ou IDs pessoais no código. Se faltar o cofre, ou não houver raízes e a descoberta estiver desativada, o estado principal pede a conferência das origens; o painel não reaparece.
- Perfil oficial consultado somente para leitura: `Lumen.exe` em `D:\Aplicativos\lumen 2026`, iniciado às 13:18, perfil `%LOCALAPPDATA%\Lumen`; gravação inativa, tarefa ociosa e nenhuma atividade de proteção. Cofre `D:\downloads\cerebro\Cerebro Oficial`, pasta `D:\Cerebro backup\Lumen - Protecao do cerebro`, duas raízes e automático pausado. Os hashes de `config.json` e `protection/config.json` ficaram idênticos antes/depois. Nenhum backup pessoal foi solicitado nesta rodada.
- A leitura atual mostrou os quatro destinos atualizados, com duas partes do Notion ainda a conferir e o último pedido parcial. Isso é o estado informado pelos recibos do backend, não uma conclusão derivada da retirada do painel. O aviso histórico de reabertura para carregar `places` já foi resolvido: a instância atual fornece esse campo.
- **Testes desta rodada:** `node --check lumen/web/protection.js`; 56 testes aprovados de `tests.test_protection`, `tests.test_protection_overview` e `tests.test_protection_progress` (96,616 s); `python tests/protection_ui.py` aprovado, com 32 verificações nomeadas. O novo teste de motor captura uma nota Obsidian real em pasta temporária e verifica que a captura do Notion recebe exatamente as raízes persistidas mesmo com padrões gerais diferentes; configuração inalterada. As chamadas Notion desse teste são simuladas, sem API externa.
- **Interface em Chrome headless:** ausência dos controles removidos na janela/widget, recuperação na ordem correta, confirmação por destino, pedido único, estados parciais/falhos, pausa, resposta antiga, teclado, foco/rolagem e versão de recuperação escolhida preservados durante polling. Caminhos longos, janela menor, zoom de navegador 125%/150% e widget nas quatro bordas. As consultas de títulos e alterações de raízes não são mais enviadas. Não há campo de digitação nessa área após a remoção; a verificação de estabilidade agora usa o seletor de versão da recuperação.
- **Servidor oficial em navegador, somente leitura:** imagens observadas de painel completo, detalhes e recuperação no widget; sem corte horizontal ou lacuna deixada pelo painel. Recuperação acessível e caminhos reais conferidos. JS/CSS recebidos idênticos aos arquivos locais por SHA-256. Todos os métodos de API diferentes de GET/HEAD foram bloqueados nessa inspeção; um pedido automático de prévia de organização foi bloqueado, sem alteração de dados.
- **Limite nativo:** Computer Use localizou a janela Lumen, mas a captura retornou imagem de outro aplicativo; nova seleção/ativação falhou com `failed to activate captured window`. Nenhum clique nativo foi usado, nenhum diálogo foi exercitado e a instância pessoal não foi encerrada. O launcher/backend não mudaram, portanto não há recompilação necessária. `Lumen.exe` mantém SHA-256 `1a6b0c6353defba22a0c1bc7c91368c37b438a50fbd61e95adaa8a1f42f53e4d`. A janela Windows já aberta pode conservar o JS anterior: para carregar esta alteração, sair normalmente pelo menu do Lúmen e abrir o executável oficial. Essa recarga nativa não foi comprovada nesta sessão.
- **Ponto anterior à alteração:** `D:\Aplicativos\Lumen-restauracao-sem-o-que-guardar-20261031-134622\restauracao.zip`, 190 arquivos rastreados/novos, manifesto `sha256.json`, conteúdo integral relido e verificado; sem chaves exportadas.
- **Evidências:** `D:\Aplicativos\Lumen-protecao-sem-o-que-guardar-20261031-134622`: `antes.json`, `verificacao-oficial.json`, `oficial-painel-completo.png`, `oficial-recuperacao.png`, `oficial-widget-recuperacao.png`, `interface.txt`, `motor.txt`, pasta `interface` com estados controlados e `alteracoes.diff`. Testes e navegadores auxiliares encerrados ao terminar. Esta alteração não revalidou a API real do Notion/Drive nem repetiu a recuperação pessoal; seus testes anteriores permanecem históricos.

---

# Entrega de 31/10/2026 — visão principal por destino

Registro vigente. As seções abaixo são históricas; suas contagens e testes **não** foram reexecutados nesta rodada, salvo quando citado aqui.

## Estado pessoal consultado em 31/10 (somente leitura)

- Instância oficial `Lumen.exe --background` aberta desde 31/10 12:07, perfil `%LOCALAPPDATA%\Lumen`, sem gravação, sem tarefa e sem atividade de proteção. Automático **pausado**. Último pedido manual: 30/10, terminou `partial`.
- Obsidian: versão de 29/10 17:03 guardada no computador e no Drive; a última leitura (30/10 22:29) não encontrou mudanças.
- Notion: a versão de 30/10 13:12 está no computador e no Drive. Uma leitura mais nova, de 30/10 22:43, virou versão no repositório interno, mas **não foi copiada** para o computador, o Drive nem o espelho Notion → Obsidian. Ela tem 19 páginas alteradas em relação à versão espelhada.
- As duas limitações da captura continuam na leitura mais nova: **Template - Ficha de Lead | Barbearia**, ícone de um bloco de destaque (`/blocks/1/callout/icon`) que veio como símbolo, sem endereço de arquivo; e **Personalidade**, bloco 61 retornado como `unsupported`.
- Obsidian → Notion: confirmado na versão mais nova do Obsidian, com 136 notas. A área **Backup do Obsidian** não está na lixeira e tem 18 páginas no primeiro nível. Hoje ela aparece no nível principal do workspace, não dentro da página escolhida. O Lúmen a encontra pelo identificador gravado. Não foi movida nem alterada nesta rodada, e o registro não mostra quem a moveu.
- A tela anterior dizia “Obsidian guardado · falta a outra origem”, o que é falso. Ela só olhava a versão mais nova de cada origem e ignorava a versão anterior do Notion já guardada.

## O que mudou

- **Backend** (`lumen/protection.py`): `places()` deriva um código por destino só de recibos persistidos e da atividade em memória. Os códigos são `ok`, `checking`, `copying`, `queued`, `first`, `behind`, `attention`, `unavailable`, `unknown` e `setup`. Cada destino informa, em `held`, a versão de cada origem que ele de fato confirmou. `sources` informa leitura, versão mais nova, pendências e falhas por origem. A falha de uma tentativa grava `failed` sem apagar `confirmed`. O campo `saved` agora considera versões anteriores confirmadas. `view()` continua somente leitura: o teste compara os hashes de `state.json` e `config.json`. Pendências trazem “o que já está guardado”. O ícone de bloco é reconhecido em qualquer nível do JSON da página; antes, só o ícone da página era. Notas Obsidian → Notion incompletas também entram na lista.
- **Tela** (`protection.js`/`.css`; mesmo componente na janela e no widget):
  - mensagem geral com três linhas: situação, o que está guardado por origem e o que fazer;
  - **Fazer backup agora** e **Recuperar minhas notas**;
  - **Backup automático: ligado/pausado**, separado, com explicação;
  - grupos **Backups para recuperar suas notas** e **Notas para consultar no outro aplicativo**, cada um com uma frase sobre a diferença;
  - um sinal por destino, sempre com ícone e texto;
  - linhas por origem, por exemplo “Notion: versão de … · falta copiar a de …”;
  - ação por destino e motivo visível quando ela está indisponível;
  - pedido manual mostrado como seis etapas persistidas: pedido recebido → leituras → destinos;
  - progresso indeterminado, salvo para o **arquivo atual**;
  - pendências com “O que aconteceu / O que já está guardado / O que fazer”;
  - oito versões preservadas agrupadas num item informativo, com a lista recolhida;
  - avisos curtos somem após 10 s.
- **Backend anterior ainda carregado**: a tela mostra “Reabra o Lúmen para ver cada cópia” e nenhum destino aparece como confirmado. Isso cobre a janela que lê o JS novo do disco antes do reinício.
- O launcher não mudou e não precisa ser recompilado. SHA-256 do `Lumen.exe` continua `1a6b0c6353defba22a0c1bc7c91368c37b438a50fbd61e95adaa8a1f42f53e4d`.

## Provas desta rodada

Evidências: `D:\Aplicativos\Lumen-protecao-validacao-20261031`. Imagens do navegador: `tests\desktop-artifacts\protection-overview-20261031`.

- **Automatizado, dados isolados**: `tests/test_protection_overview.py`, com 12 testes novos. Cobrem:
  - configuração incompleta e primeira cópia;
  - limitação de captura sem virar falha;
  - leitura nova não copiada;
  - só uma origem guardada;
  - falha do Drive preservando a confirmação local e a cópia anterior;
  - destinos indisponíveis;
  - trabalho paralelo, pedido em fila e conflito;
  - leitura não salva, páginas trocadas e envio interrompido;
  - `view()` sem escrita;
  - falha gravada pelo laço;
  - recibos reais do Restic: disco desconectado e sem espaço;
  - volta completa com Restic real das **duas origens** pelo destino local e pelo Drive (objetos em memória, download real com conferência de tamanho e SHA-256), com objeto corrompido recusado.

  Resultado:
  - `protecao-final.txt`: **74 testes** de proteção aprovados, em 96,8 s. Inclui os 12 novos e os de motor, andamento, pendências e hierarquia.
  - `suite-completa.txt`: bateria completa com **595 testes** em 641,9 s. Foram 592 aprovados e 3 falhas, que são as conhecidas do Edge `--screenshot` (`test_charts` ×2 e `test_mindmap`), sem relação com a proteção. Essa bateria começou antes do teste de volta completa, que foi rodado à parte e está nos 74.
  - As datas de modificação da configuração pessoal (`config.json`, `protection/config.json` e `state.json`) ficaram iguais antes e depois.
- **Navegador (Chrome headless, backend isolado)**: `tests/protection_ui.py`, com 29 verificações nomeadas em `interface-navegador.json` e 27 imagens. Cobrem:
  - carregamento e configuração incompleta;
  - um único pedido com três cliques rápidos;
  - pedido aceito diferente de iniciado;
  - etapas reais;
  - bytes apenas do arquivo atual;
  - texto digitado, foco, rolagem e seção aberta preservados durante o polling;
  - fechar e reabrir a área;
  - falha temporária da tela;
  - pausa e retomada com pedido manual;
  - falha só do Drive;
  - detalhes legíveis sem IDs;
  - conclusão completa e sem alterações;
  - limitações da captura;
  - estado igual ao pessoal;
  - uma origem só;
  - destino indisponível;
  - falha do pedido;
  - as quatro ações enviando o destino certo;
  - trabalho paralelo;
  - resposta antiga ignorada;
  - seletor cancelado;
  - backend anterior;
  - Tab, Shift+Tab, Enter e Espaço com foco visível;
  - 760×600, títulos e caminhos longos;
  - zoom de 125% e 150% no navegador (não é a escala do Windows);
  - widget com os mesmos textos da janela, nas quatro bordas em 320×400;
  - movimento reduzido.
- **Contraste** dos sinais sobre `#08090c` e `#181b21`: entre 5,3:1 (etapa aguardando) e 17,6:1.
- **Dados pessoais reais, em servidor isolado sobre cópias** de `config.json`, `state.json`, `drive-queue.json` e manifesto (`pessoal-copia*.png`, `pessoal-copia.json`):
  - a tela mostrou “Há backups, mas falta atualizar”;
  - computador, Drive e Notion → Obsidian aparecem como *Cópia/Versão anterior disponível; atualização pendente*;
  - Obsidian → Notion aparece como *Notas atualizadas*;
  - as pendências trazem os títulos reais.

  Os cliques reais em **Abrir pasta** e **Ver notas** abriram `D:\Cerebro backup\Lumen - Protecao do cerebro` e `...\Lumen - Backup do Notion\Particular`, confirmados pelas janelas do Explorador e fechados depois. Os arquivos pessoais ficaram com o mesmo hash.
- **Destinos das ações com dados reais** (`destinos-das-acoes.json`), com navegador interceptado:
  - **Ver cópias** leva à pasta registrada do Drive. Uma leitura GET real confirmou o nome “Lumen - Protecao do cerebro”, que é pasta, não está na lixeira e está marcada para este conjunto.
  - **Ver notas** (Obsidian → Notion) leva à área gravada **Backup do Obsidian**.
- **Hierarquia Notion → Obsidian nos arquivos** (`hierarquia-atual.json`, somente leitura, contra a captura que o espelho reflete):
  - 479 páginas, todas com bytes iguais ao gerado;
  - oito níveis e as seis páginas de topo;
  - todo filho dentro da pasta do pai, inclusive bases e fontes de dados;
  - 907 links locais válidos e 520 anexos com hash correto;
  - nenhum identificador duplicado em 479 notas;
  - 17 títulos repetidos, cada um com caminho próprio;
  - oito versões preservadas presentes e nenhuma divergência aberta.

  Renomeações, mudanças de pai e ciclos repetidos **não** foram induzidos no perfil pessoal. Eles continuam cobertos pelos testes isolados de hierarquia, que rodaram na bateria completa.
- **Instância oficial**: `protection.js` e `protection.css` servidos são idênticos aos arquivos. O backend carregado às 12:07 ainda não tem `places`, então a tela oficial mostra “Reabra o Lúmen para ver cada cópia” e nenhum sinal verde (`oficial-antes-de-reabrir*.png`). Na conferência, todo método diferente de GET e o sinal de fechamento foram bloqueados.

## Não feito ou pendente

- **Reabrir o Lúmen pessoal.** O app só encerra de forma normal pelo próprio menu, e não há controle da tela nesta sessão. Encerrar o processo seria forçado. Ação do usuário: **Ajustes → Geral → Sair**, depois abrir o Lúmen. Os módulos novos carregam ao iniciar.
- **Guardar a leitura mais nova do Notion.** Clicar em **Fazer backup agora**, o que mantém o automático pausado. Nenhum backup pessoal foi disparado nesta rodada.
- **Duas limitações do Notion.** Conferir no Notion, se necessário, o ícone do bloco em “Template - Ficha de Lead | Barbearia” e a parte não suportada de “Personalidade”. Repetir o upload ao Drive não resolve isso.
- **Janela nativa.** Não houve clique ou diálogo nativo: não há ferramenta de controle da tela nesta sessão, e a automação de mouse e teclado é bloqueada. Toda a interação foi em navegador.
- **Ponto de restauração** desta rodada: `D:\Aplicativos\Lumen-restauracao-protecao-visao-20261031-123333\restauracao.zip`, com 83 arquivos rastreados alterados e novos, `sha256.json` e releitura conferida. Não contém chaves.

---

# Ajuste de 30/10/2026 — detalhes legíveis

- Removida a exposição do estado interno em JSON na área antes chamada “Detalhes técnicos”. A seção agora é “Detalhes da proteção”, com rótulos e valores legíveis: pasta das cópias, cofre, resultado do último pedido e últimas confirmações local/Drive. Caminhos continuam selecionáveis e quebram linha no widget.
- Mensagens traduzidas para o usuário, sem IDs internos, hashes ou blocos de código. Os elementos permanecem estáveis durante as atualizações para preservar foco e seção aberta.
- Alteração apenas em `lumen/web/protection.js`, `lumen/web/protection.css`, verificações de `tests/protection_ui.py` e este registro. Backend e launcher não precisaram de recompilação/reinicialização para servir os novos recursos; uma janela que já carregou o JS anterior precisa ser recarregada ou reaberta.
- Conferência contra o servidor oficial, em navegador real, na janela principal e no widget: dados pessoais corretos, ausência de `pre`/`code`, sem rolagem horizontal, foco/seção preservados após nova consulta, JS/CSS servidos idênticos aos arquivos locais. Configurações geral e de proteção com hashes inalterados. O controle nativo novamente retornou imagem que não corresponde à área do Lúmen; recarga do WebView2 aberto não foi comprovada.
- Evidências: `D:\Aplicativos\Lumen-protecao-validacao-20261030\detalhes-legiveis\principal.png`, `widget.png`, `verificacao.json` e `interface.txt`. `node --check lumen/web/protection.js` e `python tests/protection_ui.py` aprovados nesta rodada; o teste existente recebeu verificações da apresentação legível, inclusive resultado parcial e widget.
- Ponto anterior a este ajuste: `D:\Aplicativos\Lumen-restauracao-detalhes-20261030-184520\restauracao.zip`, 189 arquivos, manifesto SHA-256 e conteúdo relido/verificado. Nenhuma chave exportada incluída.

---

# Entrega de 30/10/2026 — interface, pendências e conferência real

Este é o registro vigente. As seções abaixo da divisória são históricas; suas contagens não são resultados desta alteração.

## Estado entregue

- `Lumen.exe` oficial reaberto após o usuário confirmar saída normal. Processo 6256 nesta verificação, com backend Python 19228/16044, perfil `%USERPROFILE%\AppData\Local\Lumen`. PIDs são temporários. A instância anterior era de 30/10 e já havia executado a hierarquia: a instrução histórica de reabertura de 29/10 estava desatualizada.
- Launcher não foi alterado nesta rodada e não precisou de recompilação. SHA-256 oficial permanece `1a6b0c6353defba22a0c1bc7c91368c37b438a50fbd61e95adaa8a1f42f53e4d`. O executável anterior está incluído no novo ponto de restauração.
- Backend novo confirmado pela API (`saved`, `local_available`, `attention`, localização das versões) e JS/CSS servidos comparados por SHA-256 aos arquivos entregues. O perfil pessoal foi exercitado em navegador real, incluindo detalhes, recuperação, widget e abertura das pastas corretas. O Windows exibiu as janelas do Explorador **Particular** e **Lumen - Protecao do cerebro** após os comandos.
- Configuração geral e de proteção idênticas às anteriores, por hash. Cofre, pasta local, seleção de páginas, conexões, chave e pausa preservados. Automático **pausado**; nenhum backup pessoal novo foi disparado nesta rodada. O último pedido pessoal continua historicamente `partial`; não foi convertido artificialmente em sucesso.
- Há versões das duas origens confirmadas no destino local e no Drive, mas a captura do Notion mantém duas limitações. A tela informa isso sem confundir conexão, cópia recuperável e representação navegável.

## Tela e correções

- Hierarquia visual refeita: título legível, estado principal, ações de backup e recuperação, automático secundário; backups separados das cópias navegáveis. Removida uma camada de cartão/borda e aumentadas letras e áreas dos botões. Não foram criadas abas ou gráficos decorativos.
- `Abrir pasta`, `Ver cópias` e `Ver notas` usam os destinos registrados e validados. Notion → Obsidian abre diretamente `Particular`. Caminhos arbitrários e áreas com identidade diferente são recusados.
- Pendências abertas sob demanda, com títulos e próxima ação. Diferenças de hash não são atribuídas automaticamente ao usuário e não há orientação para desfazer edições. Notas preservadas podem ser localizadas.
- Estado parcial distingue versões guardadas de cobertura incompleta. Falha do pedido atual tem precedência sobre confirmações antigas. Atividade em paralelo continua visível mesmo quando existem recibos anteriores. Bytes de um arquivo nunca são tratados como porcentagem global nem como número de arquivos.
- Corrigido aviso persistente de “a cópia continua” depois da conclusão. Pausa e andamento são separados. Cliques duplicados, respostas atrasadas, campos, foco e seções abertas continuam protegidos pelo mecanismo existente.
- Recuperação abre uma seção simples; seletores vazios só aparecem depois de carregar versões. A lista normal agora usa o repositório da **pasta escolhida**, quando disponível. Se usar as capturas internas do Lúmen como alternativa, a origem é explicitamente identificada. Quatro versões reais foram listadas na interface pessoal.
- Corrigida a retomada quando uma atualização já escreveu exatamente os novos bytes, mas foi interrompida antes do recibo. Só igualdade exata com a representação gerada permite reconciliar automaticamente; outras diferenças continuam preservadas.

## Oito diferenças e duas pendências

As oito notas antigas tinham conteúdo idêntico à captura após comparar apenas a data gerada no cabeçalho e as quebras de linha CRLF/LF. Seus bytes também coincidiam com a cópia anterior à reorganização de 29/10. Não foram encontradas nos manifestos históricos como edições do usuário, nem foi comprovada a interrupção exata que causou a divergência de registro. Portanto, a atribuição anterior de “sua edição” não era sustentada.

Foi feita uma reconciliação explícita, com controlador exclusivo, automático pausado e ZIP do espelho verificado antes da alteração. Os **oito arquivos originais foram preservados byte a byte** em:

`D:\downloads\cerebro\Cerebro Oficial\Lumen - Backup do Notion\Versões preservadas`

As representações atuais foram geradas nos caminhos de página/subpágina corretos. A lista de títulos, hashes, caminhos antigos e preservados está em `reconciliacao-pessoal.json`; o marcador persistente guarda `preserved_copies`. Essa operação excepcional não virou política automática de resolução de conflitos. Os scripts `bench/protection_reconcile_metadata.py` e `bench/protection_repair_personal_20261030.py` documentam as verificações; **não executar novamente o script pessoal indiscriminadamente**.

As duas limitações que continuam reais:

1. **Template - Ficha de Lead | Barbearia**: o campo `/blocks/1/callout/icon` retornou um objeto externo com endereço `✦`, sem URL de arquivo. É um ícone do bloco de destaque, não evidência de perda do texto. A validação de endereço recusa o download. A tela ainda pode descrevê-lo genericamente como arquivo da página; esta investigação registra a causa precisa. Conferir o ícone no Notion se ele for necessário.
2. **Personalidade**: o Notion retornou um bloco do tipo `unsupported`. O conteúdo que a API disponibilizou está nos dados originais, mas esse bloco não tem representação legível completa. Abrir/exportar essa parte no Notion se for necessária offline. Repetir upload ao Drive não resolve uma limitação da captura.

Não houve modificação de páginas pessoais no Notion, novas permissões, descarte de versões ou limpeza de histórico para ocultar pendências.

## Hierarquia conferida nos arquivos

- **479 páginas organizadas**, em vez das 471 anteriores, com até **oito níveis**. Títulos reais preservados, incluindo `Caixa  de entrada` e `Produção de counteúdo`.
- Comparação entre pais/filhos da captura, caminhos esperados, marcador e bytes produzidos: nenhuma nota ausente ou divergente entre as representações atuais.
- **907 links locais conferidos**, sem destino quebrado após a reconciliação. A inspeção inicial havia encontrado 24 links antigos quebrados nas notas retidas no formato plano.
- **1.957 comparações de hash/representação**, com leitura de notas profundas e decodificação de quatro imagens reais do espelho. JSON original e anexos mantidos.
- Três ciclos após a correção: `[487, 487, 487]` arquivos Markdown, sendo 479 notas organizadas e oito versões preservadas. Não houve crescimento por duplicação. Áreas geradas continuam excluídas da captura do Obsidian.
- Sem lacunas de ancestralidade na captura atual. Isso não comprova acesso a todo o workspace ou reprodução completa da barra lateral. Os testes isolados continuam cobrindo ancestrais ausentes, blocos expansíveis, bases/fontes, mudanças de pai/título, colisões de nomes, migração e edições reais.

## Testes executados nesta alteração

Evidências: `D:\Aplicativos\Lumen-protecao-validacao-20261030`.

- `motor-final.txt`: **60 testes** aprovados, 48,800 s, de proteção, andamento, hierarquia e explicações. Após os últimos ajustes de recuperação/reconciliação, `ajustes-final.txt`: **32 testes** aprovados, 2,240 s. Os grupos se sobrepõem; não somar como testes distintos. A primeira rodada registrou uma falha de classificação CRLF/LF, corrigida e retestada.
- `regressoes.txt`: **216 testes** aprovados, 119,065 s: Notion, Obsidian, Drive/Notebook, widget, Pomodoro, gravação, compreensão, fluxo, capturas, identidade visual e recuperação de visualizações 3D. Houve aviso de socket não fechado ao encerrar a bateria; nenhuma falha de teste. Isso não certifica todos os fluxos reais do aplicativo. A gravação automatizada usou **sinal sintético de 220 Hz**, não microfone real.
- `interface-estendida.txt`: navegador real com backend isolado e estados controlados. Carregamento, configuração, aceite sem conclusão, bytes, indeterminado, trabalhos paralelos, conclusão, ausência de mudanças, falha, parcial, cliques rápidos, reabertura, respostas fora de ordem, falha de atualização, pausa, cancelamento, digitação/foco, recuperação, widget e teclas Tab/Shift+Tab/Espaço/Enter.
- Imagens em `tests/desktop-artifacts/protection-visual-20261030`, incluindo `parallel.png`, `unchanged.png`, `failed.png`, `scale-1.25.png`, `scale-1.5.png`, janela menor, títulos longos e widget nas quatro bordas. 125%/150% são **zoom de navegador**, não mudança da escala global do Windows. Movimento reduzido respeitado. Imagens foram abertas e inspecionadas; depois corrigido o aviso contraditório que apareceu na primeira revisão.
- `recuperacao-real.json`: novos downloads reais dos objetos já existentes no Drive, montagem com `docs/recuperar-drive.py` em processo `-I`, Restic `--no-cache check --read-data`, listagem e restauração das duas origens em pastas novas. Obsidian: quatro arquivos, uma nota e duas imagens; Notion: sete arquivos, três notas e uma imagem. Mesmos conteúdos recuperados do destino local; hashes e imagens conferidos. Chave separada; chave errada recusada. **Nenhuma origem ou cache foi consultado para preencher arquivos ausentes**.
- `notion-readback-real.json`: três páginas do espelho isolado relidas pela API, árvore persistida comparada ao registro e três anexos baixados/conferidos. Reutilizados IDs anteriores; nenhuma nova página/upload nesta prova. Testes de repetição/retomada/desconexão/espaço/permissão, importação incorreta, catálogos e limpeza foram automatizados com dados isolados; não alegar falhas de disco ou diálogos nativos induzidos no perfil pessoal.
- Perfil oficial: interface e widget renderizados contra o servidor oficial, versões reais carregadas e pastas abertas no Explorador. Recursos servidos e preservação de configurações em `entrega.json`.

## Restauração e limites da entrega

- Ponto novo: `D:\Aplicativos\Lumen-restauracao-protecao-visual-20261030-134332\restauracao.zip`, **185 arquivos** rastreados/novos, manifesto `sha256.json`, inventário e diff Git; todas as entradas relidas e conferidas.
- Mesmo ponto: `copia-notion-antes-reconciliacao.zip`, **1.479 arquivos** do espelho antes da correção, conferidos por releitura contra `copia-notion-sha256.json`. Nenhuma chave exportada nos pacotes. O ponto de 29/10 solicitado foi preservado.
- Hashes de `config.json` e `protection/config.json` permaneceram iguais. Somente a área gerada do espelho e seus registros foram reconciliados. O cofre pessoal fora dela, conexões, chave e versões não foram alterados.
- O controle nativo deixou de retornar erro de pipe. Antes da reabertura, falhava com `failed to activate captured window`; depois, a tela inicial oficial pôde ser observada, mas cliques/teclas não produziram navegação confirmada. **A área de proteção foi testada em navegador, não por cliques comprovados no WebView2. Seletores nativos de exportar/importar/cancelar permanecem não exercitados nesta rodada.** Não foi usado encerramento forçado da instância pessoal.
- Instâncias, navegadores e controladores auxiliares encerrados. Na conferência final só permaneceu o `Lumen.exe` pessoal e seus processos Python, sem Restic auxiliar em execução. O controlador pessoal foi reiniciado pela abertura oficial, mantendo a pausa.
- Imagens da instância entregue: `oficial-principal.png`, `oficial-notas.png`, `oficial-pendencias.png`, `oficial-recuperacao.png`, `oficial-widget.png`. A imagem de pendências mostra o início da seção; os detalhes completos estão em `detalhes-finais.json`.

Uso: **Fazer backup agora** mantém o automático pausado. **Recuperar minhas notas → Ver minhas cópias salvas** permite escolher origem/data e cria uma pasta nova. `Ver notas` abre `D:\downloads\cerebro\Cerebro Oficial\Lumen - Backup do Notion\Particular`. A ação pessoal restante é conferir/exportar, se necessário, as duas partes limitadas pelo Notion. Quando o controle nativo estiver funcional, exercitar os seletores reais em perfil isolado, sem substituir configurações ou chave pessoal.

---

# Registro histórico — estrutura do Notion no Obsidian

Atualização de 29/10/2026, 23h: a cópia navegável agora segue as páginas e subpáginas capturadas do Notion. Os registros anteriores foram preservados abaixo.

## Entrega desta alteração

- Destino pessoal: `D:\downloads\cerebro\Cerebro Oficial\Lumen - Backup do Notion\Particular`. As seis páginas principais foram confirmadas: Caixa de entrada, Pessoal, Instruções, Produção de counteúdo, Estudos e Trabalho - anotações. Os nomes são os títulos existentes no Notion; não foram renomeadas páginas de origem.
- Cada página tem uma nota com seu título; a pasta de mesmo nome contém as subpáginas. Exemplo: `Particular/Pessoal.md` e `Particular/Pessoal/Sub página.md`. Bases, fontes de dados e páginas dentro de blocos expansíveis usam os vínculos conhecidos da captura. Links entre notas e anexos foram ajustados aos novos caminhos.
- A organização é refeita em cada execução do espelho existente. Renomeações e mudanças de página usam as identidades persistentes do Notion; nomes iguais recebem um sufixo estável somente quando necessário. Arquivos antigos só são retirados após conferir a nova cópia, quando continuam idênticos ao conteúdo gerado pelo aplicativo. Arquivos desconhecidos e edições são preservados.
- Os arquivos estruturados ficam em `Dados originais`; os recursos baixados ficam em `Anexos`. Capturas originais, formato dos snapshots, criptografia, Drive, chave e política de versões não foram alterados. Nenhuma página foi criada ou modificada no Notion nesta alteração.
- A leitura de metadados também verifica mudanças de pai/título mesmo sem mudança de horário, e usa o pai da leitura final estável. Assim, uma mudança de lugar pode gerar a nova representação e versão correspondente.

## Aplicação pessoal e configuração

- A migração real usou o snapshot Notion `f799fa2f0351899fcde3b71a8f14902e78034c840e55cecf062c58186c81c58b`. Foram organizadas **471 páginas**, mantendo **oito notas alteradas** nos caminhos anteriores, sem sobrescrever as edições. A captura contém 479 páginas, sem lacunas de ancestralidade nessa estrutura. O estado permanece `conflict`, com duas pendências anteriores na origem; isso NÃO comprova proteção completa do workspace ou conclusão de todos os destinos.
- O controlador pessoal foi parado pela API existente, após conferir gravação inativa, processamento ocioso, revisão inativa e pedido anterior terminado. A migração adquiriu o bloqueio exclusivo do controlador, restaurou e conferiu o snapshot, atualizou somente a área identificada do espelho e terminou esse controlador. Não há controlador auxiliar de migração deixado em execução.
- Configuração geral e de proteção ficaram com hashes idênticos. Cofre, pasta local `D:\Cerebro backup\Lumen - Protecao do cerebro`, páginas escolhidas, chave e **automático pausado** preservados.
- **Reabertura pessoal ainda pendente**: o `Lumen.exe` aberto foi iniciado antes da mudança e mantém o módulo Python anterior em memória. Foi solicitado ao usuário sair normalmente por Ajustes → Geral → Sair. O controle do Windows foi novamente consultado e continua desconectado (`Computer Use native pipe is unavailable`, erro 2). Não houve encerramento forçado. Antes do próximo backup, sair e reabrir o Lúmen para carregar o módulo final. O launcher não mudou e não precisa ser recompilado: o executável oficial lê os módulos desta pasta ao iniciar. SHA-256 do executável preservado: `1a6b0c6353defba22a0c1bc7c91368c37b438a50fbd61e95adaa8a1f42f53e4d`.

## Verificações e restauração

- Ponto anterior às alterações: `D:\Aplicativos\Lumen-restauracao-hierarquia-notion-20261029-233144\restauracao.zip`, **188 arquivos**, 14.264.547 bytes; conteúdo rastreado e novo incluído, hashes conferidos por releitura do ZIP, com manifesto e registros Git. Não foi executada operação Git destrutiva.
- Antes da migração pessoal, a área inteira do espelho foi preservada em `copia-notion-antes.zip` nesse mesmo ponto: **1.479 arquivos**, 278.477.105 bytes, todos conferidos pelo manifesto `copia-notion-antes-sha256.json`. Não contém a chave exportada.
- **52 testes** de motor, acompanhamento e hierarquia aprovados, 47,451 s. Após a correção final sobre o pai durante leitura concorrente, os **10 testes de hierarquia** passaram em 1,204 s, incluindo exclusão da árvore gerada na recaptura do Obsidian para impedir ciclos. Esse grupo se sobrepõe aos 52; não somar como testes distintos. **60 regressões de Notion/Obsidian** aprovadas, 15,080 s.
- Cenários: páginas/subpáginas, links relativos, anexos, bytes originais, três ciclos sem duplicação, migração plana, edição preservada, renomeação/mudança de pai, nomes repetidos/ilegais, ancestrais ausentes, ciclos inválidos, páginas em blocos expansíveis, bases/fontes, interrupção antes dos recibos e captura corrompida. Mudança de pai com horário igual e mudança durante a leitura têm testes próprios.
- Prova isolada com o controlador e Restic reais: snapshot existente restaurado e espelhado três vezes; contagens **[8, 8, 8]**, sete arquivos conferidos, captura original intacta. O teste seleciona uma subárvore cujo ancestral não está na captura: a parte conhecida permanece navegável sob `Estrutura a conferir`, com pendência explícita; não é inferida uma árvore completa.
- Evidências em `D:\Aplicativos\Lumen-protecao-validacao-20261028\hierarquia-notion`: `evidencias-isoladas.json`, `evidencias-pessoais.json`, `motor-final.txt`, `estrutura-final.txt` e `entrega.json`. Testes de hierarquia em `tests/test_protection_hierarchy.py`.
- `Particular` é o agrupamento solicitado para as páginas acessíveis capturadas. A API pública não revela integralmente as seções privadas/compartilhadas da barra lateral nem comprova acesso ao workspace inteiro. Na captura pessoal atual, as seis páginas de topo correspondem às mostradas pelo usuário. Se faltar um ancestral, preservar a árvore conhecida em `Estrutura a conferir` e sinalizar o acesso pendente.

Próximo passo exato: após a saída normal do usuário, confirmar que a instância pessoal terminou, reabrir o `Lumen.exe` oficial, conferir configuração/pausa e executar o próximo espelho com o módulo final. Não repetir migração por código antigo nem ativar o automático sem decisão do usuário. As oito edições continuam preservadas; conferir os caminhos em `conflicts` antes de resolver qualquer uma.

---

# Registro anterior — interface e andamento

Atualização entregue em 29/10/2026. Esta seção é o estado mais recente; os registros anteriores abaixo foram preservados.

## Entrega e configuração preservada

- `Lumen.exe` oficial atualizado e reaberto após o usuário sair normalmente. SHA-256: `1a6b0c6353defba22a0c1bc7c91368c37b438a50fbd61e95adaa8a1f42f53e4d`.
- Pasta pessoal reconfirmada e preservada: `D:\Cerebro backup\Lumen - Protecao do cerebro`. Cofre inteiro: `D:\downloads\cerebro\Cerebro Oficial`.
- Os hashes de `config.json` e `protection/config.json` pessoais ficaram idênticos antes/depois. Duas páginas escolhidas, chave existente, conta Drive e **backup automático pausado** preservados. Os títulos reais das duas páginas foram consultados e resolvidos com sucesso.
- A instância oficial executa o novo backend e serve os arquivos finais da interface; caminho do processo, hash do executável, novos campos da API e hashes dos recursos servidos foram conferidos. A interface dessa mesma instância foi exercitada em navegador real. Não confundir isso com interação direta no WebView2 nativo.
- A proteção pessoal ainda apresenta pendências. Os testes isolados não demonstram que todas as notas pessoais estejam protegidas.

## Interface e comportamento

- Estado principal em linguagem simples; quatro destinos compactos; recuperação em destaque. Páginas, segurança e informações técnicas recolhidas por padrão. IDs e dados técnicos ficam na seção própria. Páginas selecionadas aparecem pelos títulos e aceitam novos links.
- `Fazer backup agora` cria um pedido identificado, persistido no estado existente, sem ligar o automático. Cliques repetidos reutilizam o pedido ativo. Cada origem é lida de novo; os destinos acompanham as versões escolhidas nessa leitura. Alterações automáticas posteriores não prolongam esse pedido indefinidamente.
- Pedido recebido mostra preparação, nunca conclusão. A conclusão exige os seis trabalhos correspondentes: duas origens, destino local, Drive e dois espelhos. Falha parcial preserva as confirmações dos outros destinos. Reabrir a área recupera o andamento.
- Atividade em memória mostra tarefas paralelas e etapas reais. Volume conhecido é do **arquivo atual**, sem representar o backup inteiro. Sem total confiável, o indicador é indeterminado. Sem tempo restante inventado. Consultas sem mudanças não geram avisos de sucesso.
- Ações seguras continuam acessíveis; bloqueio de novo pedido e troca de destino durante o trabalho. Campos digitados, seções abertas e foco são preservados. Movimento reduzido é respeitado. Avisos de acessibilidade acompanham mudanças de etapa, sem anunciar cada byte.
- Respostas antigas de atualização não sobrescrevem um pedido novo. Falha na atualização da tela é distinguida de falha do backup. Cancelamento de seletor retorna `cancelled` e não mostra sucesso.
- Foi corrigido um problema encontrado na prova real: depois de copiar uma versão criptografada, a lista local de recibos precisava ser atualizada antes de montar `Atual`. A pasta legível agora é conferida contra a versão solicitada; o estado registra quais versões foram materializadas antes de mostrar “Em dia”.
- O widget usa 360×540 somente nesta categoria, com tamanho limitado à área disponível. Gravação e nota mantêm os tamanhos anteriores. Os controles próprios da proteção não são sobrescritos pelo bloqueio geral das outras configurações.

## Provas desta melhoria

- Ponto de restauração anterior às mudanças: `D:\Aplicativos\Lumen-restauracao-interface-protecao-20261029-172133\restauracao.zip`, **1.026 arquivos**, 135.221.829 bytes; todas as entradas relidas e comparadas ao `sha256.json`. Chaves exportadas excluídas. A versão anterior do executável está também em `Lumen-antes-interface.exe` nessa pasta, hash `7c31cad739e36aa464508a3eba11ccdc0a181bc103e45b7b153158b7b3791d38`.
- **43 testes** do motor e acompanhamento aprovados. Depois da última alteração no horário de confirmação local, os **14 testes afetados** passaram novamente. Regressões direcionadas: **29 testes** de widget/servidor/ciclo de vida/Drive e **35 testes** de Notion/acompanhamento/limpeza aprovados. Esses grupos se sobrepõem: não somar as contagens como testes distintos.
- Interface real em navegador, com cenários controlados: configuração incompleta, configuração existente, aceite sem conclusão, progresso conhecido/desconhecido, resultado parcial, falha de atualização, resposta atrasada, reabertura, cliques rápidos, pausa, cancelamento, campos/foco, janela menor e widget. Os últimos testes também mantêm os comandos desativados até a primeira leitura da configuração.
- Imagens em `tests/desktop-artifacts/protection-simple`: `incomplete.png`, `ready.png`, `working-overview.png`, `partial.png`, `complete.png`, `small.png`, `long-title.png`, `widget.png`, `widget-working.png`, `widget-clamped.png`. Nenhuma rolagem horizontal nos tamanhos testados, inclusive widget limitado a 320×400 nas quatro bordas.
- Geometria nativa C#: **640 casos do widget**, incluindo o novo tamanho, e **140 da nota flutuante**, de 100% a 300% de escala. São verificações das funções nativas de tamanho/posição, sem cliques no aplicativo pessoal.
- Fluxo real usando o servidor de uma instância Windows isolada: requisição recebida como `running`, fechamento/reabertura da área, mesmo ID em nova tentativa concorrente, seis etapas concluídas, arquivo legível comparado por SHA-256 e catálogo baixado do Drive conferido. Pausa e configuração permaneceram idênticas. Após a correção, a repetição reutilizou as mesmas versões de origem.
- Segundo fluxo com PNG de teste de aproximadamente 4,3 MB: **45,894 s**, 25 amostras de atividade, seis com volume conhecido. Foram observados **4.194.304 de 4.324.105 bytes do arquivo de transferência**, sem tratar isso como porcentagem global. Ambas as cópias e os espelhos terminaram confirmados; automático continuou pausado.
- Registros: `D:\Aplicativos\Lumen-protecao-validacao-20261028\interface-protecao\evidencias.json`, `interface-protecao-volume\evidencias.json`, `interface-protecao\testes.json` e `interface-protecao\entrega.json`. Este último contém os hashes finais e a preservação das configurações. `interface-protecao\oficial.png` mostra a nova interface servida pelo executável oficial, com a configuração pessoal real e sem ativar backup pessoal.
- Instância isolada e controlador encerrados. Tarefas temporárias removidas. Apenas o aplicativo pessoal permanece aberto.

## Limitação e uso

O controle direto do Windows continua indisponível: `Computer Use native pipe is unavailable` (erro 2). A validação visual e os cliques desta melhoria foram feitos em navegador real; a distribuição Windows, seu backend, recursos servidos e geometria foram verificados. Fica pendente observar e clicar diretamente na janela nativa quando a conexão da ferramenta voltar.

Para uma cópia agora, use **Fazer backup agora**. Isso mantém a pausa do automático. Para ligar as próximas cópias, use **Backup automático: pausado**. **Recuperar minhas notas** abre as cópias salvas. Em **O que guardar**, confira páginas e adicione links. Em **Opções de segurança**, guarde a chave de recuperação separadamente.

As ferramentas de prova usam os IDs e caminhos de teste existentes. `bench/protection_progress_live.py` guarda um checkpoint e não repete um fluxo já comprovado; `LUMEN_PROGRESS_CASE=volume` seleciona o ensaio com PNG. Não executar scripts reais indiscriminadamente, nem substituir o destino pessoal por um destino de teste.

---

## Registro da entrega anterior

# Proteção do cérebro — estado da entrega

Atualizado em 29/10/2026, 16h55 (America/Sao_Paulo). Implementação entregue no executável oficial. A validação dos diálogos nativos permanece limitada pela indisponibilidade do controle do Windows. Os registros históricos abaixo descrevem etapas anteriores.

## Executável e perfil pessoal

- Oficial: `D:\Aplicativos\lumen 2026\Lumen.exe`.
- SHA-256: `7c31cad739e36aa464508a3eba11ccdc0a181bc103e45b7b153158b7b3791d38`, igual ao candidato `Lumen.Final.exe`.
- O usuário encerrou a instância pessoal antes da troca. O oficial foi reaberto sem encerramento forçado, com o perfil `%LOCALAPPDATA%\Lumen`. Caminho do processo, hash, API e recursos das configurações principal/widget foram conferidos. PIDs são temporários.
- O hash de `config.json` ficou idêntico antes/depois. Cofre inteiro `D:\downloads\cerebro\Cerebro Oficial`, estudos `B02 Estudos` e destinos preservados. Proteção pessoal desativada, pasta local vazia e configuração pessoal de proteção ainda inexistente. Os dados pessoais NÃO foram declarados protegidos.
- Instâncias isoladas pausadas, controlador parado e processos encerrados. Tarefas temporárias removidas. Candidato e executável de verificação permanecem como artefatos locais.

## Restauração verificada

Mais recente: `D:\Aplicativos\Lumen-restauracao-protecao-20261029-164642-entrega\restauracao.zip`, 785 arquivos, 15.612.785 bytes; todas as entradas relidas e comparadas ao `sha256.json`. Chaves exportadas excluídas e mantidas separadas. Ambientes, caches, modelos baixados, temporários e restaurações antigas excluídos.

Executável anterior também em `Lumen-anterior.exe` nessa pasta, SHA-256 `ee1ce4baef3422e654eac26d26fa770cf5285b1a267f0b2a996f421d89cf0592`. O ponto de 11h39 foi novamente verificado e não continha chave exportada. HEAD continua `8816039`, com alterações herdadas e novas preservadas, sem reset/clean/stash/checkout destrutivo.

## Correções concluídas

- Notion consulta a cada 30–60 segundos após a leitura anterior, com espera compartilhada e Retry-After integral. Duração da captura, volume e indisponibilidade da API podem aumentar o atraso.
- Captura continua durante aulas, com I/O limitado e Restic em prioridade reduzida. Entregas aguardam no máximo 30 s antes de iniciar; isso não promete conclusão em 30 s.
- Horários locais não são renovados sem entrega/verificação. Drive revalida catálogos e objetos periodicamente. Captura, snapshot e recibos dos destinos têm campos separados.
- Espelho Obsidian usa snapshot estável, sem bloquear a captura durante esperas de rede. Alterações com mesmo tamanho/data são detectadas por hash.
- Inicialização reconcilia snapshots órfãos, ordenando corretamente os fusos, e remove somente locks Restic obsoletos, incluindo o destino local identificado. Falhas temporárias permitem nova tentativa. Segundo controlador no mesmo perfil é recusado.
- Recuperação Drive dispensa o repositório original. Chave importada é validada antes de substituir a vigente; chave temporária de recuperação é isolada por perfil.
- Seletores usam diálogos nativos com proprietário Tk oculto, como os seletores existentes; falhas retornam erro explícito. A tentativa anterior de proprietário extra visível não faz parte da versão final.
- Todas as versões são mantidas, sem exclusão automática. Espaço e pendências aparecem na interface. Limpar histórico preserva proteção, repositórios, filas, catálogos e chaves.

## Testes e evidências

Base: `D:\Aplicativos\Lumen-protecao-validacao-20261028`. Todos os testes destrutivos usam dados identificados nessa área.

- `motor-final.txt`: **30 testes aprovados em 46,036 s**, depois de corrigir duas falhas encontradas pelos novos testes: ordenação por fuso de snapshot órfão e leitura do lock do segundo controlador.
- `regressoes-final.txt`: **195 testes aprovados em 195,906 s**. Inclui 25 testes anteriores do motor e 170 de Notion, Drive/Notebook, Obsidian, widget, fluxo, revisão e Pomodoro. Não somar 195 + 30 como testes distintos. Mudanças posteriores de recuperação/inicialização foram cobertas pelos 30 finais e por 5 testes adicionais de servidor/ciclo de vida.
- Navegador real isolado: principal, widget, erro de raízes, foco por Tab e largura 760×600 aprovados. Imagens em `tests/desktop-artifacts/protection`; isso não equivale a testar diálogos nativos.
- Handlers reais com seleção simulada: troca de destino preservando o anterior, persistência e exportação/importação de chave. `native_dialog_selection_tested: false`.
- Notion após inatividade: intervalos medidos de 61,303 s, 62,252 s e 61,382 s entre leituras, incluindo sua duração, sem snapshots adicionais para conteúdo idêntico. Configuração em 60 s.
- Edição Notion: snapshot em 43,401 s, local 47,280 s, Drive 74,487 s; cópia no Obsidian observada até 76,491 s. Três páginas de teste.
- Primeiro ciclo Obsidian oculto: snapshot 8,104 s, local 30,808 s, Drive 52,883 s; todos os destinos e espelho observados até 72,502 s.
- **Candidato final**, com janelas invisíveis verificadas pela API Windows: snapshot 3,851 s, local 10,245 s, Drive 42,815 s, espelho Notion 74,342 s. Leitura posterior no serviço e download do anexo confirmaram o SHA-256. Mesmos bytes do executável oficial entregue.
- Interrupção forçada somente da instância isolada, após snapshot e antes da entrega Drive: o mesmo snapshot foi retomado e confirmado localmente/no Drive, com espelho atualizado.
- Drive real: falha injetada depois de o serviço receber 1.000 bytes; retomada pelo mesmo ID, sem duplicação, e download com hash confirmado. Não foi interrompida a conexão pessoal.
- Recuperação local e dos downloads Drive de ambas as origens: **3 arquivos Obsidian e 7 Notion**, hashes conferidos, Markdown lido e PNGs decodificados. Utilitário independente em outro processo, chave do arquivo exportado, Restic `--no-cache`, sem completar arquivos pela origem ou pelo catálogo da instalação.
- Gravação controlada: `gravacao-controlada/evidencias.json`, áudio sintético, WAV de 34 s em 34,099 s, atraso máximo de 0,000677 s; snapshot chegou ao destino durante a gravação. Não testa dispositivo real nem horas de aula. O primeiro ensaio tinha cronômetro iniciado antes da preparação; o ensaio corrigido está registrado.
- `evidencias.json` preserva as provas anteriores: exclusão de nota de teste, recuperação da versão anterior, reconstrução de três páginas em nova área Notion e contagens estáveis `[3, 3, 3]`.

Evidência principal, horários, IDs, caminhos recuperados e hashes da implementação: `evidencias-retomada.json`.

## Limitação da validação nativa

O controle Windows continua indisponível: `Computer Use native pipe is unavailable` (erro 2), em ambas as interfaces, inclusive após reinicializar a sessão de controle. O usuário autorizou continuar e registrar a limitação.

Na etapa anterior foram observados/abertos a janela nativa, Ajustes e Proteção do cérebro; o seletor chegou a aparecer. **Não foram comprovados** seleção/cancelamento por teclado, Abrir pasta, exportação/importação pelos diálogos, recuperação por cliques e acesso nativo pelo widget. Não há evidência para atribuir a falha da ferramenta ao aplicativo.

Próximo passo exato: restabelecer Computer Use e exercitar esses controles com `LUMEN_DATA=D:\Aplicativos\Lumen-protecao-validacao-20261028\native`, usando `Lumen.Final.exe` e somente destino/chave de teste. O perfil está pausado. Não usar o perfil pessoal nem repetir indiscriminadamente `bench/protection_live.py --run`: os IDs já existem.

## Ativar e recuperar

No oficial: **Ajustes → Proteção do cérebro → Escolher pasta**. Conferir o cofre inteiro e as raízes autorizadas, conectar Drive se necessário, preparar/exportar a chave para lugar separado e clicar **Retomar** ou **Fazer backup agora**. Acompanhar cada destino; ativar não significa que a primeira captura terminou.

Recuperar pelo painel **Ver versões e recuperar**, sempre em pasta nova. Sem Lúmen, seguir `docs/RECUPERAR-PROTECAO.md` e `docs/recuperar-drive.py`, também disponíveis na pasta Drive. `Atual` é legível; `repository` guarda o histórico criptografado. A chave JSON fica separada; Restic usa o valor `password`.

Limites: Notion cobre raízes autorizadas e descoberta, sem promessa de todo o workspace. Canvas/Bases/configurações permanecem originais; não viram recursos equivalentes no Notion. Captura de anexo Notion: até 512 MB. Anexos do espelho acima de 5 MB ficam no backup e geram pendência no espelho. Sem aplicativo/computador ativo não há novas capturas. Carga e cobertura do cofre pessoal ainda não foram medidas. Todas as versões ocupam espaço, sem limpeza automática.

---

## Histórico preservado

# Proteção do cérebro — continuidade

Estado: implementação em andamento, iniciada em 28/10/2026. A pasta local definitiva será escolhida pelo usuário no aplicativo. Não está ativa por inferência.

## Preservação

- Projeto: `D:\Aplicativos\lumen 2026`.
- Cofre reconfirmado: `D:\downloads\cerebro\Cerebro Oficial`; estudos: `B02 Estudos`. Captura abrangerá o cofre inteiro.
- Git já tinha alterações em 40 arquivos e 14 arquivos novos. Nenhum reset, stash, clean ou checkout foi usado.
- Restauração: `D:\Aplicativos\Lumen-restauracao-protecao-20261028-130342\restauracao.zip`, 201 arquivos, 4.076.401 bytes; todos relidos e comparados ao `sha256.json`. Inclui fontes novas/alteradas, executáveis e estado persistente; exclusões de ambientes, caches, modelos, temporários e artefatos estão no LEIA-ME ao lado.
- Lúmen estava aberto, sem gravação e sem tarefa/revisão ativa na inspeção inicial. Revalidar antes do reinício.

## Decisão

Restic oficial 0.19.1 Windows amd64, instalação restrita a `launcher/tools`, ZIP validado pelo SHA256SUMS oficial e pelo digest da release GitHub. SHA256 do ZIP: `da948ad707ed690426473aaba2046cd61f8f90f6f0e7dab6be0d5796531de67d`. Origem e hash do executável em `launcher/tools/restic-origin.json`.

Capturas independentes e legíveis, manifestos por item e snapshots Restic. Repositórios de transporte recebem `restic copy` e verificação, nunca uma cópia concorrente sem coordenação. Drive recebe objetos binários imutáveis e um catálogo de conclusão por último. A senha fica no cofre Windows; exportação somente por ação explícita e para fora do backup.

Não há sincronização de edições para originais nem remoção automática de versões nesta primeira política conservadora. Todas as versões são mantidas; espaço e pendências ficam visíveis. Reavaliar retenção após medir o uso real; referências desejadas: 30 diários e 12 mensais, sem apagar versões fixadas ou a última recuperável.

## Fontes oficiais consultadas

- https://restic.readthedocs.io/en/stable/010_introduction.html
- https://restic.readthedocs.io/en/stable/020_installation.html
- https://restic.readthedocs.io/en/stable/045_working_with_repos.html
- https://developers.notion.com/reference/search-optimizations-and-limitations
- https://developers.notion.com/reference/file-object
- https://developers.notion.com/reference/request-limits
- https://developers.google.com/workspace/drive/api/guides/manage-uploads
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth

## Escopo dos arquivos

Novos módulos de captura/controlador, transporte binário Drive, captura/espelho Notion; integração em server, __main__, configurações atuais, widget, encerramento nativo. Reutilizar credenciais, publicações e proteção de endpoints existentes. Testes novos isolam dados e credenciais; regressões cobrem Notion, Obsidian, Notebook, configurações e interface.

## Retomada em 29/10/2026

O registro anterior parou antes das implementações e provas descritas abaixo. O código e `D:\Aplicativos\Lumen-protecao-validacao-20261028\evidencias.json` foram relidos. HEAD continua `8816039`; há alterações herdadas e arquivos novos, todos preservados.

Novo ponto de restauração: `D:\Aplicativos\Lumen-restauracao-protecao-20261029-retomada\restauracao.zip`, 441 arquivos, 19.467.552 bytes, cada entrada relida e conferida pelo SHA-256. Inclui projeto, estado pessoal persistente e validação, excluindo ambientes, caches/modelos, Git e temporários de aulas. Manifesto `sha256.json` e estado Git estão ao lado. Credenciais não foram exportadas.

Reconfirmado: Restic 0.19.1 e hash do executável `b0dd1fd21eea5d8fe1325f55f7118213c21f36de8a261e04c0624a5ab9fd7830`, igual ao registro de origem. Não foi baixado novamente.

Instância pessoal: `Lumen.exe`, perfil `%LOCALAPPDATA%\Lumen`, cofre pessoal e `B02 Estudos` preservados; estava sem gravação, tarefa ou revisão. Não tem configuração pessoal de proteção. Escolha de pasta continua pendente.

Instância de verificação: `Lumen.ProtectionCheck.exe`, perfil `D:\Aplicativos\Lumen-protecao-validacao-20261028\native\Lumen`, cofre isolado, widget inicialmente desligado. Estava ativa; somente seu controlador foi pausado/parado para retomar com estado consistente. PIDs são observações temporárias e não devem ser reutilizados.

### Evidências anteriores disponíveis

- Captura com 3 arquivos originais do Obsidian e 3 páginas Notion, 7 arquivos recuperados da captura Notion.
- Snapshots reais, novas versões, exclusão isolada, recuperação local, uploads binários no Drive e recuperação de ambas as origens após download.
- Recuperação em perfil vazio com senha fornecida em memória e sem consultar o cofre original de credenciais.
- Reconstrução de 3 páginas em nova área do Notion, com leitura dos blocos e anexos persistidos.
- Três ciclos com contagens `[3, 3, 3]`, sem ampliação por recaptura do espelho.
- Interface principal/widget testada em navegador isolado; imagens em `tests/desktop-artifacts/protection`.
- Tempos do pequeno conjunto anterior: snapshot local 4,627 s; captura/snapshot Notion 7,028 s; envios ao Drive 30,32 s e 20,353 s. Não representam a cobertura do cofre pessoal.

### Pendências confirmadas da retomada

- Reduzir espera adaptativa do Notion (chegava a 900 s) e impedir suspensão total durante gravações/processamento.
- Corrigir horários de confirmação renovados em ciclos sem verificação; separar detecção, captura, snapshot, entrega e revalidação.
- Exercitar controles nativos, exportação/importação de chave e recuperação com chave exportada.
- Demonstrar ciclo automático após esconder a janela e retomada após interrupção forçada somente da instância isolada.
- Reexecutar testes afetados, conferir executável oficial final, manter perfil pessoal sem destino de teste.

O executável oficial ainda é o anterior (`ee1ce4baef3422e654eac26d26fa770cf5285b1a267f0b2a996f421d89cf0592`). O executável de verificação é `31d0728c6e23bf76c0b01283ff5b538c8ad6ec06d68abddc13f6e99e1e9e8efa`. Nenhuma conclusão de proteção dos dados pessoais foi declarada.

## Retomada final em 29/10/2026, 11h39

Estado pessoal reconfirmado sem gravacao, processamento ou revisao, pasta pessoal ainda nao escolhida. Instancia isolada estava encerrada e foi reiniciada com o perfil native/Lumen, inicialmente pausado. Novo ponto de restauracao: D:\Aplicativos\Lumen-restauracao-protecao-20261029-113937-final, 441 arquivos, ZIP 15.038.148 bytes, todos os SHA-256 relidos. Inclui alteracoes posteriores ao ponto anterior; ambientes, caches, modelos baixados e restauracoes antigas excluidos.

Mudancas ja presentes: intervalo Notion 30-60s, captura durante aulas, adiamento de entregas limitado a 30s, horarios de confirmacao sem renovacao artificial, revalidacao do Drive, conciliacao de snapshots orfaos, espelho Obsidian a partir de snapshot estavel, recuperacao Drive sem exigir repositorio local original. 25 testes do motor e 170 regressoes passaram na etapa anterior desta conversa; o motor esta sendo reexecutado. Seletor da protecao ganhou uma janela proprietaria visivel para foco/teclado e erros explicitos. Validacao nativa completa e executavel oficial ainda pendentes.
