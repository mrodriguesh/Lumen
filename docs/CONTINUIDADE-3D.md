# Continuação da visualização 3D — 27/10/2026

## Holograma 3D também no chat — 08/11/2026

O mesmo renderizador agora responde a `/elegrama 3d <assunto>` e `/holograma 3d <assunto>` na conversa dos Estudos (artefato `holo`, GIF com PNG de
reserva). É aditivo: as páginas das aulas, o cache, `visual_3d`, a publicação e o `RENDERER holo-3` não mudaram; a comparação ganhou o arranjo
por lado e os rótulos sem quadrados (renderizações novas desses casos). Tudo desta data está em `docs/implementation/LUMEN_STUDY_AI_ELEGRAMA_3D_20261108.md`;
os resultados das seções abaixo são histórico de 27–28/10 e **não** são testes desta sessão.

## Estado atual — fechamento de 28/10/2026

**Estado: concluído nas condições verificadas abaixo.** Última ação: usuário confirmou no cliente Notion que o GIF “Computador: componentes” anima e o PNG “Revisão de um texto” mostra as quatro etapas, ambos inteiros e sem rolagem horizontal em janela normal e estreita. Essa última conferência é observação manual do usuário; não é captura nova do agente.

Implementação holo-3 preservada. Fontes e executável conferidos novamente contra `final-code.json`: os 12 hashes coincidem; nenhuma implementação alterada nesta retomada. A instância habitual serve o mesmo JS/CSS, permanece idle e não está gravando. Interface coberta pelas 100 capturas e pelo WebView2 real das fontes finais; o controlador impediu repetir a inspeção visual da janela habitual nesta data. Nenhum teste, renderização ou publicação herdados ainda em execução; nenhuma suíte ou publicação repetida. Sem próxima ação de implementação necessária.

Evidências finais já confirmadas: 522 testes gerais OK; 45 de recuperação OK; 100 capturas de UI; testes nativos; oito amostras holo-3 em produção; `normal-render.json` sem flags adicionais; `final-readback.json` com GIF/PNG iguais aos exemplos e sem duplicação. O PNG offline do Obsidian também está concluído: `obsidian-offline-png-narrow.png`, modo Leitura, quatro rótulos visíveis, parte do mesmo ensaio isolado 1.14.4 com proxy/DNS externo bloqueados. O PNG e GIF locais têm os mesmos hashes dos exemplos atuais. O cofre de produção 1.14.5 foi preservado.

Executável atual: `Lumen.exe`, SHA-256 `EE1CE4BAEF3422E654EAC26D26FA770CF5285B1A267F0B2A996F421D89CF0592`. Não recompilado nem reiniciado nesta retomada. Backup `2026-10-27-fechamento-3d-20261027-220559` revalidado: 162 hashes conferidos. Novo ponto com fontes, arquivos novos, executável final e evidências: `%USERPROFILE%\AppData\Local\Lumen\restore\2026-10-28-3d-estado-atual-070517`, 162 hashes conferidos; preserva também os avanços posteriores ao ponto anterior. Seu ZIP retrata o instante anterior a este texto de conclusão; complemento final em `encerramento.zip`, com manifesto próprio.

Limitação da automação: controlador de janelas retornou `failed to activate captured window` ao ativar Notion/Lúmen. Recuperação de janela, reconexão do kernel e ação nativa Raise não resolveram; o outro acesso informou `The browser access host is unavailable`. As capturas incorretas do VS Code não são evidência. A conferência final do Notion foi fechada pelo relato explícito do usuário em 28/10/2026; registrada em `client-final.json`. A confirmação dos bytes pela API é independente e já estava concluída. As listas antigas abaixo são histórico, não pendências atuais.

Matriz dos caminhos verificados:

| Caminho | Automação isolada | API/arquivos reais |
| --- | --- | --- |
| Curso e módulo | Passou; Notion simulado e cofre temporário | Sem novo ensaio dedicado |
| Sem curso / A organizar | Passou | Dois materiais determinísticos nos dois destinos |
| Gratuito / avulso | Passou, página própria | Sem novo ensaio dedicado |
| Vários materiais na mesma página | Passou | GIF + PNG na página existente; exemplos RAG preservados |
| Atualização / reprocessamento | Passou; preservação de conteúdo manual e cache | Duas entregas por fixture; uma imagem por material |
| Nova tentativa e resposta incerta | Passou; timeout/resposta perdida simulados e journal persistido | Nova entrega normal real, sem falha de rede forçada |
| Reorganização / mudança de destino | Passou; remapeamento de hashes e embeds | Sem novo ensaio dedicado |
| Estática / desligada / sem anexos / falha do visual | Passou; texto preservado | GIF e PNG reais; demais casos controlados nos testes |

Limites da evidência: ensaio real determinístico, sem uma nova aula processada por IA. Clientes: Notion nativo observado pelo agente para GIF; GIF/PNG em duas larguras confirmados pelo usuário. Obsidian isolado 1.14.4 para GIF e PNG offline; produção 1.14.5 preservada. Redução de rede restrita ao processo de teste; rede do Windows intacta. Cancelamento e limite de tempo de desenho são cooperativos, incluindo conferência após codificação. Falhas de rede e respostas perdidas foram simuladas; não foi forçada uma interrupção real do Notion. Não há bloqueio funcional reproduzido pendente; não extrapolar esses resultados para todas as aulas/máquinas.

Estado herdado: HEAD `88160399ce8858aa1dff3d976f0767e3f7595823`, 40 arquivos rastreados alterados e 11 novos. Nenhum AGENTS.md/CLAUDE.md no projeto ou nos diretórios ancestrais. Preservados o redesenho, identidade, Google/Notebook, capas e aplicativo nativo. Lúmen estava aberto, sem gravação ou tarefa ativa; não reiniciado.

Restauração: `%USERPROFILE%\AppData\Local\Lumen\restore\2026-10-27-continuacao-3d-20261027-193027`. ZIP dos 159 arquivos rastreados e novos, manifesto SHA-256 conferido, HEAD, status e diff binário. Não inclui ambiente virtual nem dados/credenciais pessoais.

Baseline executado: `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring .venv\Scripts\python.exe -m unittest tests.test_visual3d -q`: 33 testes, 28,541 s, OK. Inclui Notion simulado, cofre temporário e um render em tamanho real; não é nova conferência nos clientes reais.

Avaliação inicial:
- Confirmado agora: cena 3D, famílias temáticas, GIF/PNG, modos, cache básico e destinos simulados.
- Evidência anterior: DECISOES.md registra primeiro ensaio nos clientes reais; artefatos ainda em investigação.
- Lacunas em reprodução: cache sem proteção de erro de armazenamento e de nomes no manifesto; limites antes da decodificação; cancelamento; recuperação Notion baseada em legenda; propriedade Obsidian por tamanho.
- Ainda não verificado: clientes reais nesta continuação, matriz UI e executável final.

Fluxo: `jobs.finish` valida e salva StudyPackage → `_deliver` → `_visual` → `visual3d.spec/validate/_scene/render/inspect/prepare` → mesmo asset para `obsidian.deliver` e `jobs._notion` → upload oficial e `notion.publish/media_is` → histórico e `visualPreview`. `jobs.deliver` e `jobs.organize` reutilizam esse caminho. A subpágina Minha compreensão e os índices não recebem visual.

## Retomada após interrupção — 27/10/2026, 20h32

Novo ponto de restauração (sem sobrescrever o primeiro): `%USERPROFILE%\AppData\Local\Lumen\restore\2026-10-27-retomada-3d-20261027-203254`. 161 arquivos conferidos por SHA-256, mais ZIP das evidências existentes. Primeiro backup também revalidado. HEAD inalterado; gravação inativa e job idle, sem reiniciar o app de produção.

Avanços anteriores já presentes: manifesto com nomes restritos e hashes; cancelamento no cache/PNG; erro de armazenamento opcional; journal persistente de publicação e recuperação sem exclusão por legenda; hashes de anexos e remapeamento em organização; avisos e nova tentativa na UI. 37 testes de 3D foram confirmados na preparação pelo usuário. Nesta conversa, antes da interrupção: 37 testes combinando Pages e Notion passaram em 34,920 s; 60 de Obsidian/organização apresentaram uma falha de contagem de notas em `test_reprocessing_is_idempotent`, ainda em investigação.

Evidências reaproveitadas: oito animações holo-2 em `tests/desktop-artifacts/visual3d-current`, 960×540, 48 quadros, 4 s, 2.342.831–3.493.820 bytes, renderizações de 4,68–6,24 s. A medição de memória retornou zero e NÃO é válida. Inspeção atual encontrou sobreposição no exemplo de rótulos longos; os demais pôsteres são legíveis. A UI anterior concluiu 100 capturas: 98 passaram, duas cortaram o botão de nova tentativa em 520×560 a 110/120%.

Alterações desta retomada em verificação: quebra da linha do aviso/botão; arranjo alternativo em colunas para rótulos que colidem (holo-3); cache do PNG de reserva reutilizável e renderização nova apenas na tentativa explícita. Suíte geral e matriz de UI em execução, logs em `tests/desktop-artifacts/visual3d-current`.

Página de teste anterior localizada pela API do aplicativo: `<id-da-pagina-de-teste>`, título `Lumen · teste da Visualização 3D (pode apagar)`. Reutilizar esta página, preservando os blocos antigos. Ainda não há publicação real desta continuação nem `real.json`.

## Verificação real e regressões — retomada em andamento

`bench/visual3d_check.py --publish` concluído: dois materiais determinísticos (computador animado e revisão de texto estática), duas entregas por material pelo `jobs.deliver`, com upload real, leitura dos blocos e comparação dos bytes. Uma imagem por material; nota e embed locais existentes, segunda entrega Obsidian sem alterações. Evidência nova: `tests/desktop-artifacts/visual3d-current/real.json`. Não houve geração por IA neste ensaio. Página anterior preservada, incluindo seus exemplos RAG. Cliente Notion 7.41.0 aberto e página localizada; inspeção de imagem em andamento.

O primeiro ensaio do verificador encontrou uma fixture sem `ai_analysis`; corrigida. A tentativa tinha terminado antes de escrever blocos. Conferidos remotamente ausência do título e marcador da fixture; somente o registro pendente isolado foi limpo (backup `data/Lumen/history-before-fixture-fix.json`). A intenção de publicação agora é gravada junto com o journal, após construir o conteúdo.

Matriz UI final de 3D: 100 capturas, cinco tamanhos incluindo 520×560, 1120×860, 1920×1040, zoom 80–120%, nenhum problema detectado (`ui.log`). Testes de cache/journal adicionados: identidade da integração, edição/cópia do usuário, ambiguidade, subpágina e transcrição com resposta perdida, PNG de reserva em cache, cancelamento na trava e rótulos longos. `recovery.log`: 45 testes (3D + recuperação + falha da compreensão) passaram em 38,879 s. Inclui renderização real em produção; serviços remotos simulados nesse conjunto.

A primeira regressão geral executou 515 testes em 250,103 s, quatro falhas: três renderizações pelo Edge e uma expectativa antiga de rollback. A retomada agora preserva blocos confirmados, compara a entrada de finalização e reutiliza o pacote; o teste passou a conferir IDs preservados, nenhum append duplicado e nenhuma nova IA. A contagem Obsidian passou quando executada isoladamente e na suíte geral; não foi alterada.

Falha ambiental reproduzida: Edge 156.0.4314.42 lançado pelo host de comandos retorna zero, ignora os argumentos e abre a interface, sem screenshot. O mesmo comando com `--do-not-de-elevate` produziu PNG real. A flag será usada só no processo de testes; nenhuma política global foi alterada. Mapas/gráficos serão verificados novamente com essa condição explícita.

## Fechamento após a segunda interrupção — 27/10/2026, 22h06

Resultado posterior confirmado: `regression-final.log` termina com **522 testes, 266,647 s, OK**. A execução real de Edge no processo de testes recebeu `--do-not-de-elevate`; o produto não recebeu essa flag. O wrapper PowerShell retornou 1 ao tratar stderr como erro nativo, enquanto o runner unittest concluiu OK. As mensagens intermediárias de falha fazem parte dos testes de recuperação. Não havia processo de testes ativo na retomada. Fontes relevantes ainda anteriores ao fim dessa execução; nenhuma nova suíte geral necessária.

`native.log`: passaram 480 casos de geometria do widget, 140 da nota, orientações, ajustes, capas no WebView2, compreensão/autosave nas três interfaces. Foi `Lumen.DesktopCheck.exe`, compilado das fontes atuais com entrada de testes e dados isolados. Também compilado `launcher/Lumen.next.exe` das fontes atuais; ainda não substituiu o executável habitual.

Oito amostras holo-3 regeneradas, sem cache: `measures.json` e `render-final.log`. Todas 960×540, 48 quadros, 4 s; GIF 2.342.831–2.992.050 bytes, PNG 165.599–248.292 bytes; 5,212–6,375 s por amostra. Pico do processo medido pela API do Windows com handle 64 bits: 306,8 MiB. Essa é a medição válida, substituindo o zero anterior. Começo/meio/fim inspecionados nas duas folhas `quadros-*.jpg`; rótulos longos agora separados, símbolos/acento legíveis. `loop-audit.json` registra diferenças entre quadros e hashes, sem salto isolado acima dos outros quadros do laço.

Notion cliente 7.41.0: novo GIF de Computador visto na coluna, em duas capturas com geometria diferente (animação ativa), mesma referência `224c635c` publicada por `jobs.deliver`. Captura `notion-client-gif.png`. PNG e largura estreita ainda em conferência. Exemplos RAG antigos permaneceram na página.

Novo backup verificado: `%USERPROFILE%\AppData\Local\Lumen\restore\2026-10-27-fechamento-3d-20261027-220559`, 162 arquivos com hashes + ZIP das evidências. Backup de 20h32 revalidado integralmente. App habitual ainda idle, sem gravação.

Condição ambiental comprovada pela consulta do token de processo: host de comandos elevado; Lumen.exe PID 28080 e Python PIDs 4388/8004 sem elevação. O primeiro Obsidian isolado herdou elevação e não recebeu a automação normal; encerrado somente esse processo de teste, sem nota aberta. Relançamento pelo Explorer em verificação. A checagem de mapas/gráficos/capa usa as funções reais sem flags extras, com dados isolados, no mesmo nível de privilégio do Lúmen habitual.

`normal-render.json` concluído: processo sem elevação, **nenhuma flag adicional**, funções reais do produto produziram mapa PNG (1.217.867 bytes, 1,601 s), gráfico GIF (53.564 bytes, 3,525 s) e capa PNG (949.971 bytes, 1,399 s). Arquivos decodificados. A primeira fixture faltava o campo emoji e foi corrigida somente no verificador. A execução via Explorer corresponde ao nível de privilégio do launcher/backend habitual; não precisou alterar o produto, trocar navegador ou política. Artefatos `normal-mapa.png`, `normal-grafico.gif`, `normal-capa.png`.

Executável final: `Lumen.exe` substituído pela compilação atual já testada, SHA-256 `EE1CE4BAEF3422E654EAC26D26FA770CF5285B1A267F0B2A996F421D89CF0592`. App anterior encerrado pelo botão **Ajustes → Sair**, depois de conferir idle/sem gravação e nenhuma edição aberta. Reiniciado pelo Explorer às 22h16 (PID 30756, backend 16528/8928), carregando arquivos atuais. Hash da configuração antes/depois idêntico. `final-code.json` identifica fontes e executável. Nenhum modelo local encerrado ou configuração global alterada.

`final-readback.json`: nova releitura real dos dois arquivos do Notion, bytes iguais aos exemplos atuais e anexos do cofre; uma imagem por material. Dois exemplos RAG anteriores preservados. Não foi necessário republicar as amostras porque seus hashes não mudaram.

Obsidian 1.14.4 (versão empacotada instalada) em perfil isolado, cofre existente, modo Leitura: GIF observado animando em 1024×801 e 608×801; sem corte/rolagem horizontal. Em janela estreita foi recolhida a barra lateral para leitura. Processo iniciado com proxy local indisponível e resolução externa bloqueada; nenhuma conexão TCP ativa nesses processos. Capturas `obsidian-offline-gif-normal.png` e `obsidian-offline-gif-narrow.png`; anexos locais conferidos por hash. Instância/cofre de produção 1.14.5 preservados.

Próxima ação exata: concluir PNG nos dois clientes, largura estreita do Notion e inspeção final do Lúmen reiniciado; registrar limitações e entregar. Não confundir API real, cliente real e simulação.
