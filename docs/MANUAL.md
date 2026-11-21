# Lúmen — manual completo

O Lúmen está sendo construído como a base local de um **segundo cérebro**: um acervo de conhecimento com fontes,
contexto, autoria e conexões, que também possa servir às futuras tecnologias do usuário. Estudar e acelerar o
aprendizado são usos dessa base. Essa direção não significa que integrações futuras já estejam prontas.

Transforma aulas em vídeo em material de estudo salvo diretamente na página escolhida do Notion.
Gratuito, sem chave de API paga: a transcrição (Whisper) e a escrita do material (Ollama) rodam no seu PC.
Só o material gerado e o link opcional da aula vão para o Notion; o áudio permanece local.

**O Lumen nunca cria a sua compreensão; ele complementa a que você construiu.** Antes de qualquer IA, você escreve
o que entendeu da aula. Só depois a IA analisa a sua nota contra a aula (ver [Minha compreensão](#minha-compreensão)).

## Requisitos

- Windows 10/11 (prioritário). Também roda em macOS/Linux pelo navegador padrão, mas lá não foi testado.
- Python 3.11 ou mais novo (testado com 3.14).
- Modelos de fala: Whisper (OpenAI, MIT) e Parakeet TDT 0.6B v3 (NVIDIA, CC-BY-4.0; conversão ONNX de istupakov).
- [Ollama](https://ollama.com/download) (gratuito, MIT) com um modelo de texto. Padrão: `qwen3:8b` (≈ 5,2 GB, Apache 2.0).
- Espaço em disco: ≈ 0,5 GB (modelo Rápido) ou ≈ 1,6 GB (modelo Preciso), mais o modelo do Ollama.
- Memória: 16 GB de RAM recomendados para `qwen3:8b`. Uma GPU NVIDIA (CUDA 12) acelera bastante, mas é opcional.
- Opcional, para **Assistir a tela junto**: o modelo de visão `qwen3.5:4b` no Ollama (≈ 3,3 GB, Apache 2.0; Ollama
  0.30 ou mais novo), baixado pelo próprio app.
- Opcional, para **Filtrar música externa**: YAMNet (Google, Apache 2.0, 16 MB), o separador de voz UVR-MDX-NET
  (30 MB) e o modelo de voz ResNet34 do WeSpeaker (CC-BY-4.0, 26 MB), em ONNX, baixados pelo próprio app. Rodam na
  CPU; com o suporte a GPU instalado, o separador usa a GPU (DirectML). Não precisam de PyTorch.

## Instalar e abrir

A instalação automática (uma linha no PowerShell) está no [README](../README.md#instalar).

### Instalar à mão

1. Instale o Python e o Ollama. Abra o Ollama uma vez.
2. Dê dois cliques em **`Iniciar Lumen.bat`**. Na primeira vez ele cria `.venv`, instala as dependências e, se encontrar
   uma GPU NVIDIA, pergunta se deve baixar o suporte a GPU (≈ 1 GB).
3. Depois disso, abra pelo **`Lumen.exe`**: uma janela nativa com ícone próprio. Para fixar, clique com o botão
   direito no ícone dele na barra de tarefas e escolha **Fixar na barra de tarefas**. Fechar a janela recolhe o app;
   para encerrar, use o botão de desligar no rodapé da barra flutuante ou **Sair do Lumen** na bandeja do Windows.

`Lumen.exe` é um programa pequeno em C# (`launcher/Lumen.cs`) que abre a interface no WebView2 do Windows e inicia o
Python em segundo plano. Para recompilar: `powershell -ExecutionPolicy Bypass -File launcher/build.ps1` (usa o
compilador C# que já vem no Windows). O ícone é gerado por `launcher\make-icon.ps1`.

Pela linha de comando: `.venv\Scripts\python -m lumen`.

## A interface

Escura, com uma barra lateral de cinco áreas e uma barra superior que mostra sempre onde você está e o que o Lumen
está fazendo (detalhes e regras do visual em [docs/DESIGN.md](DESIGN.md)):

- **Início:** o que está acontecendo agora (gravando, processando ou a aula para continuar, com as etapas dela), as aulas
  em andamento, as salvas recentemente, as revisões do Obsidian para hoje e o estado do sistema (Notion, Obsidian, IA
  local, transcrição). Na primeira vez, “Antes de começar” lista o que falta configurar.
- **Nova aula:** Fonte → Compreensão → Análise → Salvar. À esquerda a fonte (gravar, arquivo ou capturas); à direita o
  link, a **Organização** (curso e módulo, conteúdo gratuito, aula avulsa ou "organizar depois"), os destinos que saem
  dela e as opções.
- **Biblioteca:** Todos, Cursos (cards; cada curso abre com os módulos e as aulas em ordem), Conteúdo gratuito, Aulas
  avulsas, Para revisar, A organizar e Em andamento. A busca acha aula, curso, módulo, tema e conceito; **Filtros**
  (recolhidos) têm curso, módulo, status, revisão e data. Cada aula tem **Organizar**.
- **Integrações:** os destinos do material (Notion + Obsidian, só Notion ou só Obsidian) e uma aba para cada
  integração (Notion, Obsidian, **Google Drive** e Voice Studio), com o estado resumido; abaixo, os ajustes da aba
  escolhida. O Google Drive não é um destino das aulas: é a conta da cópia de segurança da Proteção do cérebro (ver
  [Google Drive](#google-drive-a-cópia-de-segurança-da-proteção)).
- **Ajustes:** Geral, Aparência, Captura, Pomodoro, Transcrição, IA local, Capas do Notion e Privacidade e dados.
- **Barra superior:** a busca (**Ctrl+K**: telas, ajustes, ações e aulas), o status (Pronto, Gravando, Pausado,
  Processando, Erro; clique para ir até ele) e o Pomodoro.

## Estilo da interface: Clássico ou Lúmen Glass 2026 (Ajustes → Aparência)

Além das cores, a janela principal tem dois estilos. O **Clássico** é o de sempre (e o padrão). O **Lúmen Glass 2026** redesenha a apresentação: vidro escuro,
barra lateral com os nomes, controles de janela do Windows, Pomodoro em cartão no topo, Início em duas colunas (com "Comece uma nova aula", "Continue de onde
parou", a jornada Capturar → Compreender → Aprofundar → Organizar → Revisar, Ações rápidas e Revisões), as três fontes da Nova aula à vista, Biblioteca com
números e estrutura por curso, Cérebro com abas em vidro e Integrações em duas colunas. Nada do que o Lumen faz muda: as mesmas rotas, dados, gravação, IA e
integrações. A troca é imediata (sem recarregar nem perder o que está sendo digitado), fica salva (`ui_style` no `config.json`) e volta ao Clássico a qualquer
momento, pelo mesmo lugar. Detalhes em [docs/DESIGN.md](DESIGN.md) ("Lúmen Glass 2026") e decisões D161–D170 em [docs/DECISOES.md](DECISOES.md).

## Minha compreensão

O fluxo é **conteúdo → a sua compreensão → a IA analisa a sua compreensão → Notion**:

1. Escolha a fonte e clique em **Continuar**. O Lumen prepara a aula no PC (transcrição, telas) em segundo plano.
   Nenhum resumo é feito, e a transcrição e as telas não aparecem: seriam cola.
2. Na hora abre **Minha compreensão**, um editor só seu: escreva com suas palavras o que entendeu. Não há sugestão,
   autocompletar, dica nem correção de conceito por IA (só a correção ortográfica do sistema). Dá para escrever
   enquanto a aula ainda está sendo preparada.
3. **Processar minha compreensão** (ou Ctrl+Enter) libera quando a nota tem conteúdo de verdade: pelo menos 20
   palavras, 12 diferentes, com cara de texto. Só então a IA local recebe a aula e a sua nota.
4. **Análise concluída:** a sua nota, intacta, e à parte o que a IA observou: o que você compreendeu corretamente,
   o que entendeu em parte, o que faltou, possíveis confusões (as suas palavras e o que a aula diz), complementos,
   conexões e perguntas para aprofundar.
5. **Salvar no Notion** cria a página da aula, escrita a partir da sua compreensão (ela tem prioridade no pedido à
   IA), e logo abaixo dela a subpágina **Minha compreensão**: primeiro a sua nota original, em citação; depois de
   um divisor, a análise, rotulada como da IA. A revisão da transcrição e das telas fica aqui, recolhida e opcional.

- **Sem perder o que você escreveu:** salva neste PC a cada tecla e no Lumen 0,6 s depois da última; ao fechar ou
  esconder a janela, o que falta vai na hora. Ao reabrir, o texto volta (com aviso, se veio do PC).
- **Uma nota só, três janelas:** a janela principal, a barra lateral e a janela flutuante mostram sempre a **aula em
  foco** (a que foi aberta por último em qualquer uma delas): trocar de aula numa troca nas três, sem misturar textos.
  O que se digita aparece nas outras na hora (aviso entre janelas, sem esperar o disco); só a janela onde você digitou
  salva (as outras só salvam se ela fechar antes de confirmar). Cada versão tem um horário: um salvamento atrasado
  nunca apaga um texto mais novo, e quem mandou o atrasado passa a mostrar o novo.
- **Status e “por que ainda não posso processar”:** uma regra só (`understanding.readiness` no servidor, `Notes.ready`
  nas janelas) e o mesmo texto nas três: *Preparando a aula…* · *Termine a gravação para analisar* · *Aguardando
  outra tarefa terminar* · *Escreva sua compreensão para continuar* (ou quantas palavras faltam) · *Salvando sua
  compreensão…* · *Pronto para analisar* · *Analisando sua compreensão…* (com a etapa, ex. “Lendo a aula por partes
  (1 de 4)”, e o tempo estimado, que vem das velocidades medidas neste PC) · *Análise concluída* · *Não foi possível
  analisar* (com **Tentar novamente**; a nota nunca é perdida, nem se o app fechar no meio). Na barra e na janela
  flutuante aparece também **Processar**. O servidor confere tudo de novo e trava a nota no instante do pedido; a
  análise lê exatamente a versão enviada (guarda a revisão), e a nota fica só para leitura até ela terminar.
- **Escrever depois:** a aula fica no Início e na Biblioteca (**Em andamento**) até ser salva no Notion.
- **Destacar (Ctrl+Shift+D):** o botão **Destacar**, acima do papel, leva a nota para uma janela flutuante, sempre por cima, para
  escrever enquanto revê o vídeo em outro programa. Arraste pela barra, redimensione pelas bordas, minimize para ficar
  só a barra; **Voltar para o Lumen** traz o editor de volta e **fechar** só fecha a janela. Ela lembra posição e
  tamanho, não sai da tela e não cresce além de 60% × 92% da área útil. A **barra flutuante** do lado esquerdo também
  tem a nota (ícone de lápis), com o mesmo botão de destacar. É sempre o mesmo documento: o que se escreve numa das três
  aparece nas outras na hora, com o mesmo autosave. Nenhuma delas mostra análise ou sugestão de IA. Para trocar o
  atalho: `localStorage.understandingShortcut` (ex.: `"Ctrl+Alt+N"`).
- **Editar depois da análise:** a primeira versão fica guardada como **compreensão original** (nunca muda depois da
  1ª análise); a editada vira a atual, pode ser analisada de novo e as duas vão para a subpágina.
- **Estudar de novo** uma aula já salva começa uma nota nova; as anteriores entram em “Compreensões anteriores”.
- A regra fica no servidor (`lumen/understanding.py`) e vale para todas as fontes, inclusive as futuras: a geração
  de material, a análise e a publicação recusam rodar sem nota válida, mesmo chamadas diretamente pela API.
- Estados de cada aula: `studying` (preparando) → `waiting_for_understanding` → `understanding_written` →
  `processing_with_ai` → `completed` (análise pronta) → `synced_to_notion`.

## Barra flutuante e inicialização

No `Lumen.exe`, os controles ficam escondidos em uma pequena alça na borda esquerda por padrão. Passe o mouse
para revelar a barra escura com uma animação suave; ao sair, ela se recolhe automaticamente, mesmo após um clique.
Arraste pela alça superior da barra aberta para mover, inclusive para outra tela. A posição é lembrada na próxima abertura.
Perto de uma borda ou canto, a alça se encaixa automaticamente e o painel se abre para dentro da área útil,
sem cobrir a barra de tarefas. A posição salva no formato anterior é convertida ao abrir.
Nas laterais a alça é vertical; em cima e embaixo ela é horizontal. Os controles também mudam de disposição,
e a orientação é lembrada junto com a posição. Arraste a barra aberta até a borda desejada para alternar.
A barra mostra um único botão **Gravar/Parar**, o estado em palavras (Pronto, Gravando, Captura pausada), o tempo da
captura e atalhos discretos para abrir o app e os ajustes. Parada, ela não pisca: só a gravação pulsa.
A engrenagem abre todas as configurações dentro da própria barra, organizadas em categorias: barra flutuante,
Notion, transcrição, IA local, capas e privacidade. Os campos maiores têm rolagem e os downloads mostram progresso.
A limpeza exige confirmação e fica bloqueada durante gravações e tarefas, preservando os arquivos em uso.
Instruções de silêncio e mensagens de erro aparecem quando necessárias. Ao parar, a janela principal abre com a gravação pronta para usar.
Fechar a janela principal mantém a captura e o processamento ativos.

Em **Ajustes → Geral**, escolha esquerda, direita, em cima, embaixo, posição livre ou desativada;
**Restaurar posição** recoloca a barra. **Iniciar com o Windows** registra apenas o usuário atual na chave Run,
com o caminho do executável entre aspas. O login abre o Lumen em segundo plano (`--background`), sem gravar sozinho.
Mesmo com a barra desativada, a bandeja permite abrir, acessar ajustes e sair. Ao sair durante uma gravação,
o Lumen pede confirmação e finaliza o WAV antes de encerrar; na próxima abertura, a janela principal oferece
**Usar gravação** ou **Descartar**. O mesmo vale se o app fechar de repente (cada gravação em andamento tem um
`<gravação>.session` ao lado do WAV, e o cabeçalho do WAV é corrigido pelo tamanho do arquivo).

### Pausar captura

Durante a gravação, **Pausar captura** (barra, janela principal, janela flutuante da nota ou `Ctrl+Alt+P`) para de
guardar o som e as telas sem encerrar a sessão; **Retomar captura** continua no mesmo arquivo. O período pausado
não entra na aula nem como silêncio: o tempo gravado e o tempo das telas ficam parados (o tempo real e as pausas
ficam no `.session`). O som segue sendo lido e descartado, para o Windows não acumular áudio velho. O Lumen não
pausa o vídeo, o navegador nem outro programa. Pausado é âmbar e parado; gravando é vermelho e pulsa. Para trocar o
atalho: `localStorage` `captureShortcut` (tabela `SHORTCUTS` em `understanding-editor.js`).

Na **barra flutuante** o botão de pausa é uma cápsula: ao iniciar a gravação, ele **emerge do botão vermelho** (abaixo dele na barra lateral, à direita na barra deitada) e Conversa e Ajustes
dão a vez; pausado vira **Retomar** (ícone ▶, texto e âmbar), e ao encerrar tudo volta ao lugar. O botão vermelho não muda de lugar (nunca se encerra sem querer: um clique logo depois de
iniciar é ignorado e, se outra janela já mudou o estado, a barra mostra o real em vez de agir). Funciona com a conversa, os ajustes ou a nota abertos e acompanha a gravação iniciada
ou encerrada em outra janela. Com movimento reduzido a pausa só aparece, sem deslizar. Verificação: `py -3.14 tests\capsule_ui.py` e o bloco “Cápsula de gravação” de `tests\DesktopChecks.cs`.

### Pomodoro

Um timer só (`lumen/pomodoro.py`, guardado em `pomodoro.json`), sempre à vista no canto da barra superior da janela
principal, em qualquer tela, e também na barra flutuante e na janela flutuante de “Minha compreensão”. O chip mostra um
anel que se fecha com a etapa, o nome **Pomodoro**, o estado em palavras (Iniciar, Foco, Pausado, Pausa, Pausa longa,
Foco concluído, Hora de focar), o tempo e o play/pausa; em janela estreita fica só o anel e o tempo. Clicar abre o
painel: o tempo dentro do anel, a sessão (2 de 4), o que você está estudando agora, **Pausar/Continuar**, **Encerrar
foco/pausa** e **Reiniciar**, com as durações e o som recolhidos. As durações também ficam em **Ajustes → Pomodoro**, e a
busca (Ctrl+K) inicia, pausa ou abre o Pomodoro. Foco, pausa curta, pausa longa e ciclos são
personalizáveis (25/5/15/4 por padrão; atalhos 25/5 e 50/10), com **Iniciar a próxima etapa sozinho** (desligado) e
**Som ao terminar** (ligado). O tempo vem do horário em que a etapa termina, não de ticks: minimizar, fechar janelas,
reiniciar o app ou suspender o PC não atrasa nada. É independente da captura: um nunca pausa o outro. No fim de uma
etapa: notificação do Windows sem som, destaque discreto no timer e um som curto do Lumen, que não toca enquanto a
captura grava (entraria na aula).

### Conversa rápida (barra flutuante)

O ícone de balão da barra (entre **Gravar** e **Ajustes**) abre uma conversa com o mesmo cérebro do Lumen sem abrir a janela
principal, **no tamanho compacto da própria barra** (304 × 252: ela não cresce) e com o campo já pronto para digitar. É o **mesmo**
agente do Cérebro (mesmos modelos, memória, fontes, perfis e privacidade) e a mesma conversa: nada é copiado.

- **Enviar:** Enter envia; Shift+Enter quebra a linha. O botão vira **Interromper** durante a resposta. O texto só sai do campo depois
  que o Lumen confirma a pergunta; se falhar antes, ele continua lá.
- **Livre | Notas:** Livre responde sem consultar o Notion nem o Obsidian; Notas consulta as fontes e mostra, sob a resposta, **Fontes · n**
  (abrir confirma pelo Lumen: “Nota aberta no Obsidian.”). É o mesmo botão do Cérebro: mudar em um lugar muda no outro.
- **⋯ (mais opções)**: **Nova conversa** (a anterior fica no histórico), **Nova conversa temporária** (não entra no histórico nem cria
  memórias), **Continuar no Cérebro** (abre a MESMA conversa — mesmo identificador, mensagens e modo — na janela principal; nada é
  reenviado), **Ampliar a conversa** (360 × 540, só nesta sessão; o padrão é sempre o compacto) e **Ajustes desta conversa**.
- **Ajustes desta conversa** (painel interno que ocupa o lugar da conversa; **Voltar** sempre à vista): **Modelo** (padrão: *Rápido do Lumen*, o modelo rápido resolvido na hora; ou outro
  modelo local já instalado), **Novas conversas** (Normal ou Temporária) e **Tamanho** (o mesmo Compacto/Ampliado do menu), mais **Restaurar ajustes deste chat** (só estes ajustes: conversas,
  notas e modelos não mudam). Ficam no servidor (`settings.json → quick`) e valem da PRÓXIMA resposta: mudar um ajuste não reenvia, não interrompe e não apaga o rascunho; o chat principal e
  `models.fast` não mudam. O modelo pedido que não está instalado é trocado por um local instalado (o rápido, depois o principal) e a resposta diz qual respondeu (Detalhes).
- **Temporária:** um chip pequeno com o relógio e “Temporária” na linha de modo. Prova feita: não grava conversa, mensagem nem memória no banco; não lê memórias pessoais; nada dela no
  `localStorage`/`sessionStorage` (o rascunho temporário fica só na memória da página e é separado do rascunho normal); some quando o Lumen fecha ou após 24 h sem uso. Não é anonimato nem
  apagamento forense: o Windows e o Ollama seguem suas próprias regras (o Ollama mantém o modelo carregado por alguns minutos).
- **Recolher** (‹ ou Esc) esconde a barra sem cancelar a resposta; um ponto no ícone avisa quando ela termina. O texto digitado e as
  mensagens ficam; a gravação continua e aparece como um relógio discreto no cabeçalho. Esc: primeiro fecha o menu, depois recolhe.
- Comandos `/`, anexos, `/tela` e voz continuam no Cérebro (têm confirmações de custo e de envio externo que a barra não tem).

Importante: o recorte e o tamanho da janela dependem do `Lumen.exe` e das páginas serem da MESMA versão. Com um `Lumen.exe` antigo
(sem `widget:panel:chat-wide`) a conversa continua inteira no tamanho compacto, mas "Ampliar" não tem efeito; troque o executável depois
de **Sair do Lumen** pelo menu.

Verificação: `py -3.14 tests\chat_compact.py` (geometria no 304 × 252: limites, recortes, clique, quatro bordas, ampliar em passos, janela
menor, escalas do navegador), `py -3.14 tests\chat_ui.py` (servidor real e isolado, Ollama falso que transmite, 24 blocos),
`py -3.14 tests\quick_settings_ui.py` (ajustes, temporário e capturas, 14 blocos), `.venv\Scripts\python.exe -m unittest tests.test_quick_settings` (modelo, ajustes e privacidade no servidor),
`.venv\Scripts\python.exe -m unittest tests.test_quick_chat` (backend) e o bloco “Conversa rápida” de `tests\DesktopChecks.cs`
(WebView2 e janela reais; compile com `/r:System.Management.dll` além do que está abaixo).

Verificação da função: `.venv\Scripts\python.exe -m unittest tests.test_widget tests.test_record -v`.
`py tests\widget_ui.py` usa Playwright no Python do sistema e o Chrome instalado; testa a interface com API
simulada e salva imagens em `tests\desktop-artifacts`. `tests\DesktopChecks.cs` é o teste nativo: compile junto
com os três arquivos do launcher (`Lumen.cs`, `WidgetForm.cs`, `NoteForm.cs`) usando `/target:exe /main:DesktopChecks`.
`tests
ote_sync_ui.py` (precisa do Node e do Edge; ver o início do arquivo) abre a janela principal, a barra e a
flutuante juntas e confere sincronização, troca de aula e cada status. Ele também confere “Minha compreensão” nas três interfaces reais e a janela flutuante (mover, redimensionar,
minimizar, lembrar, fechar e voltar).
Os testes devem usar `LUMEN_DATA` temporário e `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` para isolar
configurações e credenciais. A verificação cobre `--background`, visibilidade, expansão, posição salva e desativação;
Também cobre mensagens atrasadas, hover repetido, quatro bordas/cantos da tela real e 480 casos de geometria com
origens negativas, telas em retrato e escalas de 100% a 300%. Não envolve reiniciar o Windows nem testar
monitores físicos com escalas diferentes.

Os modelos não são baixados sem pedido: o app mostra o tamanho e um botão **Baixar** em Ajustes.

## Conectar o Notion (API oficial)

O Lumen usa uma **integração interna** do Notion. A integração pública (OAuth) exigiria um servidor com segredo de
cliente, que um app local e gratuito não pode guardar com segurança.

1. Acesse <https://www.notion.so/profile/integrations> → **Nova integração** → tipo *Interna*, no seu workspace.
2. Capacidades: *Ler conteúdo*, *Atualizar conteúdo*, *Inserir conteúdo*. Não precisa de informações de usuários.
3. Copie o token secreto e cole em **Integrações → Notion**. Ele é validado e guardado no
   Gerenciador de Credenciais do Windows (via `keyring`), nunca em arquivo.
4. No Notion, crie uma página (ex.: “Estudos”), abra **••• → Conexões** e adicione a integração.
5. Em Integrações, escolha essa página como **página raiz dos cursos**.

A página no Notion sai da **Organização** da aula, sem escolher página à parte:

- **Curso:** `Cursos › <curso> › <módulo>`. As páginas do curso e do módulo são criadas quando precisa, ou adotadas se já
  existe uma com o mesmo nome. Os cursos que já estão no seu Notion aparecem para adotar em "Novo curso".
- **Conteúdo gratuito:** uma página por material dentro da página escolhida em **Página de conteúdo gratuito**.
- **Aula avulsa:** a página "Sem curso", criada sob demanda.
- **A organizar:** a aula fica onde já está, ou vai para "Sem curso" se ainda não tem página.

A aula entra no corpo da página, com um título para o material, preservando o nome, a capa, o ícone e o conteúdo
anterior. **Organizar** uma aula salva republica o material na página nova e só então remove a versão anterior. Uma
página que o Lumen criou só para aquele material vai para a lixeira se ficar vazia.

O Notion só mostra à integração as páginas liberadas para ela. Para escolher as **páginas raiz** do seu workspace
(as do topo da barra lateral), libere-as em <https://www.notion.so/profile/integrations> → sua integração →
**Acesso** → *Editar acesso* (o botão “Dar acesso no Notion” do app abre essa tela). Liberar uma página raiz libera
tudo o que está dentro dela; no app elas aparecem no grupo “Páginas raiz do Notion”. A API não permite que uma
integração interna crie páginas no topo do workspace, só dentro de uma página.

## Notion e Obsidian

O Lumen escreve o material **uma vez** e salva o mesmo conteúdo em cada destino: o Notion para organizar e
acompanhar, o Obsidian para estudar a fundo e ligar ao seu segundo cérebro. Em **Integrações → Destinos do material**:

1. Escolha **Notion + Obsidian**, **Só Notion** (padrão, como antes) ou **Só Obsidian** (não precisa do Notion).
2. Escolha o **cofre do Obsidian**. O Lumen lista os cofres registrados neste PC, mas nunca escolhe sozinho;
   **Escolher pasta…** aceita qualquer pasta com `.obsidian`.
3. **Área de estudos** (Avançado): por padrão, uma pasta de topo chamada Estudos (ex.: `B02 Estudos`). O Lumen não
   escreve fora dela.

A área se organiza como a sua área de estudos do Notion. As pastas só são criadas quando usadas:

```
B02 Estudos/
├── 00 - Estudos.md            a central: revisar hoje, continuar, cursos, temas, a organizar, recentes
├── Estudos.base               a base (Bases, nativo): Biblioteca em cards, Para revisar, Recentes, Cursos…
├── 01 - Cursos/<Curso>/
│   ├── 00 - <Curso>.md        a página do curso (MOC): acesso, progresso, módulos e aulas em ordem
│   └── 03 - <Módulo>/07 - <Aula>/
├── 02 - Conteúdo gratuito/<Tema>/<Material>/
├── 03 - Aulas avulsas/<Tema>/<Aula>/
└── 90 - A organizar/<Aula>/
```

**Organizar** (na Nova aula ou depois, na Biblioteca) leva a pasta inteira da aula: nota, mapa, painel e anexos. Os
Canvas e o manifesto acompanham. Curso e módulo têm id estável, então renomear um curso no Lumen renomeia a pasta, a
página do curso, as propriedades das aulas e o título no Notion, sem criar outro curso. Um curso vazio nunca é
apagado sozinho. A página do curso tem só a plataforma e o endereço: login e senha ficam no seu gerenciador de senhas.

Aulas da pasta antiga (`16 Lumen`, de antes da área de estudos) aparecem em Integrações → Obsidian → **Materiais
antigos**. **Migrar** leva cada aula inteira para "A organizar", sem renomear nada. Antes, guarda um zip da pasta antiga
em `%LOCALAPPDATA%\Lumen\obsidian-backups`. Rodar de novo não faz nada.

Cada aula tem a sua pasta, com:

- **Nota de estudo** `Título da aula.md` (`type: ai-study`, `author: lumen-ai`, `status: review-required`, mais a
  organização: `study-type`, `course`, `course-id`, `module`, `module-id`, `lesson`, `category`, `platform` e `cover`,
  a imagem dos cards), com:
  - a sua compreensão, intacta, e a análise da IA à parte;
  - visão geral, conceitos com o tempo da aula (no YouTube, o tempo é um link);
  - explicação, glossário, exemplos, passo a passo e telas;
  - perguntas de active recall com a resposta escondida, teste de compreensão e flashcards;
  - erros comuns, aplicações e conexões com notas reais do cofre;
  - perguntas em aberto, linha do tempo, revisões e "Possíveis notas permanentes".
- **Mapa conceitual** `Mapa - Título da aula.canvas`, um Canvas de verdade, para entender como as ideias se
  relacionam:
  - a nota no centro e os ramos ao redor, com as relações da aula nas setas;
  - embaixo, os grupos Processo, Conexões, Exemplos e Relações.
- **Painel visual** `Painel - Título da aula.canvas`, um segundo Canvas, para reconhecer e lembrar a aula: uma prancha
  com as telas e os gráficos que a aula mostrou.
  - Só imagens reais: as telas capturadas (as mesmas de "O que apareceu na tela") e os gráficos feitos com os dados da
    aula. Nada é gerado nem buscado na internet.
  - A escolha é local e sem IA: pesam o tipo (diagrama, gráfico e tabela antes de slide de texto), o conceito da aula
    que a tela mostra, o que **você** escreveu em "Minha compreensão" e as capturas que você mesmo fez. Telas quase
    iguais contam uma vez. Uma aula só de fala não ganha painel.
  - Composição pelo tipo da aula: a imagem mais representativa domina, com as outras em volta e um cartão curto ao
    lado de cada uma; passo a passo vira sequência com setas; um contraste da aula vira duas colunas. No topo, o
    título e os links para a nota e o mapa.
  - **Densidade** em Integrações → Obsidian: Compacto (até 5 imagens), Equilibrado (até 10, padrão) ou Visual (até 15).
    Precisa de "Telas e gráficos no cofre"; com a opção desligada, não há painel.
  - A nota leva o mapa embutido e o painel por link, em "Mapas da aula".

  Nos dois Canvas você pode mover e redimensionar os cards e criar os seus: ao reprocessar, o que você moveu ou criou
  fica, inclusive uma imagem que saiu da escolha do Lumen mas que você tinha posicionado.
- **Anexos** em `Anexos`, na pasta da aula, com o nome do que mostram (`03m09 design dramatico · aula.jpg`), que é o rótulo do
  Obsidian em cima de cada imagem no painel. Ao reprocessar, só sai o anexo que o próprio Lumen gravou e nada mais usa;
  uma imagem sua nunca é tocada.
- Nenhum caminho passa de 250 caracteres: o Obsidian não abre arquivos além do limite do Windows. A pasta da aula
  encurta pelo que vai morar nela. Se uma imagem antiga de nome longo não cabe no lugar novo, ela ganha um nome mais
  curto, e a nota, os Canvas e o manifesto acompanham.

### Estudos no Graph View

No Graph View do Obsidian, o Lumen usa dois grupos de cor nativos do Obsidian, sem plugin, sem CSS e sem nada escrito
dentro das notas ou dos Canvas:

| No gráfico | Cor | Consulta (a linha em **Grupos**) |
|---|---|---|
| Notas de estudo (aulas e páginas de curso) | azul **#5B8CFF** | `[type:ai-study] OR [type:course]` |
| Canvas dos estudos (Mapa, Painel e outros) | violeta **#A78BFA** | `path:/^B02 Estudos\// file:/\.canvas$/` |

- As notas são reconhecidas pela propriedade que já têm. A cor acompanha a aula quando ela muda de pasta ou de nome, e
  as suas notas, os anexos e a central `00 - Estudos` ficam com a cor de sempre.
- Canvas não tem propriedades, então é reconhecido pelo lugar: todo `.canvas` dentro da área de estudos fica violeta,
  inclusive um Canvas seu dentro da pasta de uma aula. Um Canvas fora da área (ex.: em Projetos) fica com a cor de
  sempre. A consulta usa regex ancorada (`^…/` e `\.canvas$`), porque `path:"B02 Estudos"` também pegaria uma pasta
  como `Arquivo/B02 Estudos antigo/` e `file:.canvas` pegaria uma nota `Ideias.canvas.md`. Ela usa o nome da área no
  momento da instalação; se você mudar a área depois, ajuste a consulta em Grupos.
- Os Canvas aparecem no gráfico sem ligar "Anexos": a opção fica como você deixou.
- Os grupos são criados **uma vez por cofre**, na primeira aula entregue ou ao abrir o Lumen. Se o Obsidian estiver
  aberto, o Lumen espera ele fechar (o Obsidian regravaria o arquivo por cima). Antes da primeira mudança, ele guarda
  uma cópia de `.obsidian/graph.json` em `graph.json.lumen-backup`. Nenhuma outra configuração do Graph muda (forças,
  filtros, anexos, órfãos, seus grupos). Se o `graph.json` estiver corrompido, nada é escrito.
- **Para mudar uma cor:** no Graph View, abra o painel do canto superior direito (o ⚙, se estiver fechado) → **Grupos**.
  Clique no círculo de cor da linha do grupo. A sua cor fica: o Lumen nunca recria nem repinta um grupo, mesmo que você
  o apague.
- Os dois grupos entram em primeiro na lista, porque o Obsidian pinta cada nó com o primeiro grupo que casa: um grupo
  seu por pasta (ex.: `path:"B02 Estudos"`) não tira as cores do Lumen. Os dois não disputam o mesmo nó (um só pega
  notas, o outro só Canvas).
- O **gráfico local** (o de uma nota só) tem grupos próprios em cada aba e não lê esta configuração; se quiser as
  cores nele também, crie os grupos lá, com as mesmas consultas.

Regras que protegem o que é seu:

- O material da IA nunca vira nota permanente sozinho. As ideias candidatas ficam marcáveis para você escrever com as
  suas palavras.
- Escreva em **Minhas anotações**, no fim da nota. Reprocessar refaz só o bloco do Lumen; suas anotações, as caixas
  marcadas e as propriedades que você mudou ficam.
- Se você editar dentro do bloco do Lumen, a próxima atualização para e avisa. **Substituir mesmo assim** guarda uma
  cópia antes.
- Reprocessar não cria cópias. A nota é achada pelo `lumen-id` mesmo se você a renomear ou mover dentro da área de
  estudos, e o Lumen não a traz de volta. Ela só muda de pasta quando você muda a organização no Lumen.
- **Revisões espaçadas (opcional, desligada por padrão):** ligue em Integrações → Obsidian → **Incluir revisões
  espaçadas** (ou no ajuste rápido do Obsidian, na Nova aula: é o mesmo switch). Ligadas, a nota ganha a seção
  “Revisões” com `- [ ] Revisão N · data`; marque cada uma e o Lumen atualiza `next-review` ao abrir. Os intervalos
  (padrão 1, 3, 7, 14, 30 e 60 dias) ficam guardados mesmo com a função desligada. As revisões do dia aparecem no
  Início, na Biblioteca (Para revisar) e no painel dos estudos. Desligadas, nada disso é gerado nem cobrado. Vale
  para novas notas e notas atualizadas: as notas existentes ficam como estão até serem salvas de novo.
- **Profundidade** (Ajustes → IA local):
  - Rápido: uma passada.
  - Balanceado: com conexões no cofre.
  - Profundo: uma 2ª passada critica e melhora o material.

  Tudo roda no Ollama local: nada do cofre sai do PC.
- Se um destino falhar, o outro fica salvo, e **Tentar de novo só o Notion/Obsidian** refaz só o que faltou, sem
  chamar a IA.

## Google Drive (a cópia de segurança da Proteção)

Integrações → **Google Drive** conecta a conta onde a **Proteção do cérebro** guarda a cópia de segurança fora deste
computador. É opcional: sem ela, a cópia neste computador continua. O Lumen usa a API oficial e gratuita do Google
Drive, com um projeto seu no Google Cloud.

1. No [console do Google Cloud](https://console.cloud.google.com), ative a **Google Drive API**.
2. Em *Tela de consentimento OAuth*, escolha *Externo* e adicione o seu e-mail como usuário de teste.
3. Em *Credenciais*, crie um *ID do cliente OAuth* do tipo **App para computador** e baixe o JSON.
4. Em Integrações → Google Drive, **Escolher o arquivo do cliente…** e **Entrar com Google** (abre o navegador do
   sistema). O painel mostra o estado do Drive e a próxima ação: não configurado, falta entrar, aguardando a
   autorização, Drive conectado, acesso expirado ou revogado (entre de novo) e não foi possível entrar.

- O Lumen pede só o escopo `drive.file`: vê apenas os arquivos que ele mesmo criou. O login segue o fluxo oficial de app
  para computador (navegador do sistema, retorno para `127.0.0.1`, PKCE e `state`). O cliente e a autorização ficam no
  Gerenciador de Credenciais do Windows, nunca em arquivo nem no log.
- Com o app em modo *Testing* no Google Cloud, a autorização vale 7 dias (regra do Google); depois, **Entrar com Google**
  de novo.
- Uma criação que ficou sem resposta nunca é repetida às cegas: o Lumen procura no Drive pela marca dele antes de
  qualquer nova tentativa, e nunca apaga nem substitui outros arquivos.
- **Desconectar Google Drive** apaga a autorização deste PC; para revogar no Google, use
  <https://myaccount.google.com/permissions>. As cópias e a recuperação ficam em Ajustes → Proteção do cérebro.

### O Gemini Notebook foi retirado (09/11/2026)

O Lumen não prepara mais fontes para o Gemini Notebook, não vincula cadernos, não envia aulas ao Drive para ele e não
importa o que volta de lá. As rotas `/api/notebook/*` deixaram de existir. O que já tinha sido feito fica como dado
antigo, sem nenhuma integração ativa: os arquivos preparados e os materiais trazidos em `%LOCALAPPDATA%\Lumen\notebook`,
o arquivo `notebook.json` com os vínculos e a pasta **Lumen - Gemini Notebook** no seu Drive. O Lumen não apagou nada no
Google (cadernos, documentos e pasta continuam lá; apague-os pelo Drive se não os quiser). Ajustes → Privacidade e
dados → **Limpar** remove os arquivos deste PC. Relatório: `docs/implementation/LUMEN_REMOCAO_GEMINI_20261109.md`.

## Open Notebook (opcional; `lumen/opennotebook.py`, `lumen/web/opennotebook.js`)

Integrações → **Open Notebook** envia a transcrição de uma aula, em texto, para um caderno do seu
[Open Notebook](https://github.com/lfnovo/open-notebook), pela API REST dele (nada de banco de dados nem de arquivos dele).

- **Conexão**: endereço da API (padrão `http://127.0.0.1:5055`), endereço da interface (`http://127.0.0.1:3000`, usado só
  para abrir os cadernos) e, se o seu Open Notebook pede, a senha (`OPEN_NOTEBOOK_PASSWORD`), guardada no Gerenciador de
  Credenciais do Windows. Estados: *Desconectado*, *Conectado*, *Serviço indisponível* e *Senha necessária*. Trocar o
  endereço da API esquece a senha e o caderno do endereço antigo.
- **Iniciar Open Notebook** (`lumen/onlocal.py`): com a instalação nativa deste PC parada, o cartão mostra o que está
  parado (banco, API, worker, interface) e o botão. Nada inicia sozinho ao abrir a aba. O clique inicia só o que falta, na
  ordem banco → API → worker → interface, em `127.0.0.1`, sem janelas de console e com um log por serviço em
  `D:\Aplicativos\OpenNotebookData\logs\lumen-*.log`. Quem já responde é reaproveitado; porta ocupada por outro programa
  vira um erro com o nome dele, e nada é encerrado. “Conectado” só aparece com `dbStatus: online` em `/api/config`, e
  “Abrir no Open Notebook” só habilita com a interface respondendo. Os serviços continuam abertos depois de fechar o Lúmen
  (o Lúmen não os encerra; para parar, feche-os pelo Gerenciador de Tarefas). Só vale para o endereço padrão da API.
- **Caderno de destino**: escolha um caderno que já existe ou crie, com um clique, o **Lúmen — Transcrições** (se já
  existir, é reaproveitado; nenhum caderno é alterado nem apagado).
- **O que vai**: só texto — título, organização (curso e módulo), data, idioma, link da fonte (quando há) e a transcrição
  com os marcadores de tempo. Áudio, vídeo, imagens e a nota de compreensão não são enviados.
- **Enviar**: na tela de resultado (**Enviar ao Open Notebook**) e em cada aula da Biblioteca (ícone do caderno). O
  diálogo diz o que vai e para onde, e oferece **Enviar** e **Enviar e abrir**. O envio automático ao terminar cada aula
  existe e vem desligado. É independente do Notion e do Obsidian: uma falha aqui não desfaz nem bloqueia a entrega.
- **Sem duplicar**: o manifesto (`history.json`, campo `opennotebook`) guarda o hash do texto, o caderno e o id da fonte.
  Repetir o clique não cria outra fonte; um envio sem resposta fica *não confirmado* e, na nova tentativa, o Lúmen procura
  a fonte no caderno antes de repetir; se o processamento falhou lá, a mesma fonte é reprocessada.
- **Estado real**: *na fila*, *processando*, *pronta* ou *falhou* vêm do Open Notebook (o processamento é assíncrono e
  depende do worker dele). Sem modelo de embeddings configurado lá, a fonte entra sem indexação.
- **Abrir no Open Notebook**: no Lumen.exe, numa janela própria (perfil WebView2 separado, sem ponte com o aplicativo,
  navegação presa ao endereço configurado; outros links vão para o navegador padrão); fora dele, no navegador.
- Limite: a transcrição só existe no PC para a última aula publicada (ou para todas, com “Manter arquivos temporários”);
  as outras aulas da Biblioteca mostram o aviso em vez do botão de enviar.

Verificação: `.venv\Scripts\python.exe -m unittest tests.test_opennotebook` (servidor falso), `py -3.14
tests\opennotebook_ui.py` (navegador headless, dados isolados e a API real instalada; cria e apaga os próprios cadernos
de teste), `tests\OpenNotebookCheck.cs` (janela nativa; compilar como o `DesktopChecks.cs`, com `/main:OpenNotebookCheck`) e
`.venv\Scripts\python.exe -m unittest tests.test_onlocal` (a partida dos serviços, simulada). A partida de verdade é conferida
com um banco descartável: a variável `LUMEN_ON_DATA` troca a pasta do banco e dos logs.

## HyperbookLM (opcional; `lumen/hyperbooklm.py`, `lumen/web/hyperbooklm.js`)

Integrações → **HyperbookLM** envia, à mão, o título e a transcrição de uma aula como fonte do
[HyperbookLM](https://github.com/hyperbrowserai/hyperbooklm) instalado neste PC (`D:\Aplicativos\hyperbooklm`). É uma
integração à parte do Open Notebook: nada dela muda o que ele faz.

O HyperbookLM guarda as fontes só na memória da página e não tem API de importação. Por isso ele ganhou uma ponte pequena
(`lib/lumenBridge.ts`, `app/api/lumen` no repositório dele): o que o Lúmen envia fica em `.lumen/sources.json`, na pasta
do HyperbookLM, e a página lê esse arquivo ao abrir e ao voltar ao foco. É isso que faz a fonte aparecer e continuar lá
depois de atualizar a página ou reiniciar o servidor.

Passo a passo (uma vez):

1. Na pasta do HyperbookLM (`D:\Aplicativos\hyperbooklm`): `npm run dev` (este PC não tem o `yarn`; com ele, `yarn dev` é o
   mesmo comando). O endereço aparece no console
   (`http://127.0.0.1:3000`, ou a porta seguinte se a 3000 estiver ocupada: o Open Notebook usa a 3000).
2. No Lúmen: Integrações → HyperbookLM → **Conectar**. O estado fica *Falta parear*.
3. **Gerar código de pareamento**. A linha `LUMEN_BRIDGE_TOKEN=…` é copiada (e mostrada só nessa hora).
4. Cole a linha no arquivo `.env.local` da pasta do HyperbookLM (crie-o a partir de `.env.local.example` se não existir;
   as outras linhas ficam como estão) e reinicie o `npm run dev`.
5. **Testar conexão**: *Conectado*. A partir daí, **Enviar transcrição ao HyperbookLM** aparece na tela de resultado e
   em cada aula da Biblioteca (ícone de camadas).

- **Endereço**: padrão `http://127.0.0.1:3000`, editável. Só endereços deste PC são aceitos (`127.0.0.1`, `localhost`,
  `::1`, em `http`, com a porta). Se o HyperbookLM não responde no endereço guardado, “Testar conexão” procura da porta
  3000 à 3010 por quem responde `app: hyperbooklm` em `/api/lumen` e corrige o endereço sozinho. Fora dessa faixa, digite
  o endereço. Abrir a aba não sonda portas.
- **Estados da conexão**: *Desconectado*, *Conectado*, *Servidor indisponível*, *Falta parear*, *Código recusado* e
  *Ponte não encontrada* (outro programa na porta, ou um HyperbookLM sem a ponte).
- **Servidor × IA**: “Conectado” diz só que o servidor do HyperbookLM respondeu e aceitou o código. A linha “IA do
  HyperbookLM” diz, à parte, se as chaves existem no `.env.local` dele: `OPENAI_API_KEY` (chat, resumo e mapa mental) e
  `GEMINI_API_KEY` (slides); `ELEVENLABS_API_KEY` é só para o áudio e `HYPERBROWSER_API_KEY` só para raspar páginas. O
  Lúmen vê apenas *existe/não existe*: nunca lê, guarda nem testa as chaves, e nenhuma chamada paga é feita na conexão ou
  no envio. Sem as chaves a transcrição chega, mas a análise do HyperbookLM não funciona. Com elas, a análise é feita pelo
  HyperbookLM, que manda o texto a esses serviços e pode gerar cobrança na conta delas.
- **O que vai**: só `title` e `text` (a transcrição com os marcadores de tempo). A ponte recusa qualquer outro campo.
  Áudio, vídeo, telas, a nota de compreensão, anotações e caminhos de arquivos não são enviados. Não há envio automático.
- **Sem duplicar**: o id da fonte é o SHA-256 de título + texto, calculado dos dois lados. Repetir o clique não reenvia
  (o Lúmen confere com a ponte); um envio sem resposta fica *não confirmado* e pode ser repetido sem criar outra fonte.
  “Guardada” só aparece depois de a ponte listar a fonte. Se ela for removida no HyperbookLM, o diálogo avisa e deixa
  enviar de novo. Registro em `history.json`, campo `hyperbooklm`.
- **Limites**: 2 MB de texto por aula, título de até 300 caracteres e 50 transcrições guardadas na ponte (remova as
  antigas no HyperbookLM). A transcrição só existe no PC para a última aula publicada (ou para todas, com “Manter
  arquivos temporários”). O próprio HyperbookLM usa só o começo de cada fonte na análise (2.000 caracteres no chat e no
  resumo, 4.000 no mapa mental, 5.000 nos slides): aulas longas são analisadas pelo início.
- **Segurança**: o código de pareamento é gerado pelo Lúmen e fica no Gerenciador de Credenciais do Windows (`Lumen` /
  `hyperbooklm`), nunca em `config.json` nem no log; no HyperbookLM fica no `.env.local`, que o git ignora. A ponte só
  aceita gravação com esse código, compara-o em tempo constante, recusa `Host` que não seja deste PC e pedidos vindos de
  outra máquina, e os scripts `dev`/`start` do HyperbookLM agora escutam só em `127.0.0.1`. A página do HyperbookLM lê e
  remove as fontes sem o código, por ser a mesma origem. Desconectar apaga o código deste PC; as fontes ficam lá.
- **HyperbookLM parado (Ajustes → Diagnóstico do sistema → Instalar / reparar)**: o diagnóstico diz se o servidor está
  parado, se o endereço salvo ficou desatualizado (ele está de pé em outra porta) ou se faltam dependências (o
  `package.json` conferido contra o `yarn.lock` e o `node_modules` de `D:\Aplicativos\hyperbooklm`). Só depois do clique e
  da confirmação, o Lúmen instala as dependências travadas (Yarn 1 com `--frozen-lockfile`; o lockfile não muda) quando
  faltam, sobe o `npm run dev -- -p <porta>` existente só no 127.0.0.1 e confere `/api/lumen` antes de dizer “pronto”. Um
  HyperbookLM já aberto é reaproveitado; outro programa numa porta nunca é parado (escolhe outra de 3000 a 3010). O
  `.env.local`, o código de pareamento e as fontes (`.lumen`) não são tocados; parear e as chaves de IA continuam sendo
  passos seus. Opcional: não conta na prontidão do Lúmen. Decisão D187.
- **Abrir o HyperbookLM**: abre dentro da janela principal do Lúmen (`SiteView`, em `launcher/Lumen.cs`): um painel
  nativo por cima da página do Lúmen, com uma barra (**Voltar ao Lúmen**, **Recarregar**, nome e estado) e um WebView2
  próprio no perfil `webview-hyperbooklm`, separado do Lúmen e do Open Notebook e sem ponte com o aplicativo. A página do
  Lúmen continua carregada por baixo: voltar mostra a mesma tela, no mesmo estado, e reabrir mostra o HyperbookLM como
  estava. A navegação fica presa ao endereço local conferido: link de fora clicado abre no navegador padrão;
  redirecionamento por script e outros esquemas (`file:`, `javascript:`) são bloqueados. Enquanto carrega, com o servidor
  fora do ar ou se o WebView2 não iniciar (30 s), o painel mostra um aviso e **Recarregar** tenta de novo. Ajustes pela
  bandeja, “Abrir no Cérebro”, a gravação pronta e a nota encaixada voltam sozinhos ao Lúmen. O Open Notebook segue na
  janela separada dele. Num `Lumen.exe` anterior a esta função a janela era separada; fora do Lumen.exe, abre no navegador.
  Conferência nativa: `D:\Lumen\hyperbooklm-embed-20261116\HyperbookEmbedCheck.cs` (compilar como o `OpenNotebookCheck.cs`).

Verificação: `.venv\Scripts\python.exe -m unittest tests.test_hyperbooklm` (ponte falsa: estados, código recusado, tempo
esgotado, duplicata, texto grande demais). Contra a ponte de verdade, com dados sintéticos e sem nenhuma chamada de IA, os
roteiros e as capturas estão em `D:\Lumen\hyperbooklm-20261116` (`bridge_live.py`, `lumen_live.py`, `lumen_ui.py`,
`HyperbookCheck.cs`): sobem o HyperbookLM em outra porta com `LUMEN_BRIDGE_TOKEN` e `LUMEN_BRIDGE_DIR` de teste.

## Fontes

| Fonte | Estado | Como funciona |
|---|---|---|
| Gravar ao assistir | Compatível | Dê play na aula em qualquer site ou app; o Lumen grava o som que sai do PC (loopback do Windows) e transcreve localmente. Nada é baixado. Leva o tempo da aula. |
| Arquivo local | Compatível | Escolher ou arrastar. O áudio é decodificado em memória; o vídeo não sai do PC. |
| Capturas de tela | Compatível | Prints de sites, textos, slides, código ou tabelas: arraste, **cole com Ctrl+V** (Win+Shift+S) ou escolha as imagens. A IA de visão local transcreve cada uma e a página sai com a seção **📸 Capturas de tela**. |

### Capturas de tela

- **Aba “Capturas de tela”:** até 30 imagens (png, jpg, webp, bmp, até 25 MB cada); título e link de origem opcionais. A
  mesma página bonita de sempre (resumo, tópicos, glossário, gráficos, perguntas) é escrita a partir do que as imagens
  mostram. Precisa do modelo de visão (`qwen3.5:4b`, o mesmo de “Assistir a tela junto”) e do Ollama abertos.
- **Em qualquer aula (gravação, YouTube, arquivo):** na revisão, **＋ Adicionar capturas** (ou soltar/colar imagens ali)
  junta prints à aula, com a leitura feita na hora; elas entram no fim, sem horário. Desmarque o que não quiser.
- **Na página:** a galeria (2 por linha, clique para ampliar) e, recolhido, o texto de cada captura: código em bloco de
  código, tabela como tabela do Notion, figuras descritas. Sites e textos são transcritos como estão; só a moldura do
  programa (abas, relógio, botões) fica de fora. Diferente das telas de uma aula, uma captura sua nunca é descartada
  por “não ser conteúdo da aula”: fica sempre que a IA leu algum texto ou figura.
- **Privacidade:** nada sai do PC além das imagens e do texto que você mantiver na revisão, que vão ao Notion. Os arquivos
  originais não são tocados; o Lumen trabalha numa cópia e apaga as cópias ao gerar a página.

Formatos testados: MP4 (H.264/AAC), MKV (H.264/AAC), WebM (VP9/Opus), MOV (H.264/AAC), MP3, M4A (AAC), WAV (PCM).
Outros formatos são recusados com uma mensagem. Arquivos sem áudio ou corrompidos são detectados antes de começar.

## Assistir a tela junto (opcional)

Liga no cartão da fonte, em Nova aula (ou em Ajustes → Captura). O Lumen passa a olhar a aula com você e põe na página o que aparece na
tela: slides, quadro, código, tabelas, fórmulas e gráficos, com as imagens. Tudo no seu PC, com um modelo de
visão local (`qwen3.5:4b`).

- **Gravar ao assistir:** enquanto o som é gravado, a tela é observada 1 vez por segundo (≈ 2% de um núcleo).
  Só fica a tela nova que parou de mudar (um slide novo, não a transição). A imagem é tirada da própria janela da
  aula, como o Windows a desenha: o que estiver por cima dela (avisos, uma conversa, outro programa) não entra.
  Ela é lida nos intervalos da aula (≈ 1,5–3 s de GPU por slide). Quando você para a gravação, quase
  tudo já foi lido. A câmera do professor num canto, uma câmera redonda, legendas animadas e vídeo em movimento
  são ignorados na comparação; quando o vídeo corta da pessoa falando para um slide, o slide entra em 1 a 4 s.
- **Arquivo de vídeo:** o Lumen lê os quadros-chave do próprio arquivo depois de transcrever (≈ 2 s por tela nova).
- **O que entra:** o modelo transcreve o texto da tela e descreve figuras; rosto do professor, anúncios, menus,
  recomendações do YouTube e notificações ficam de fora. Seus próprios programas (editor de código, anotações,
  Word, e-mail, WhatsApp, terminal, pastas) **nunca** são lidos, nem durante a aula. A janela do Lumen também
  não: se ela estiver na frente, a aula atrás ou ao lado continua sendo assistida.
- **Sensor na barra flutuante:** um chip azul mostra o estado. “Assistir ativado” (modo ligado, ainda sem gravar);
  “Vendo a tela” com a contagem de telas guardadas, com uma linha de varredura animada (a captura está rodando de
  verdade); âmbar em “Sem capturas” ou “Tela não vista” (o modo está ligado mas nada está sendo visto; passe o
  mouse para ver o motivo). Com a barra recolhida, um ponto azul na alça indica o mesmo. Sem o modo, o chip some.
- **Se nenhuma tela entrar,** a gravação mostra o motivo (“Sem capturas ainda: …”) e a revisão diz “Nenhuma tela
  foi guardada durante a gravação (motivo)”, em vez de parecer que as telas foram lidas e descartadas.
- **Na revisão** aparecem as telas escolhidas; desmarque o que não quiser na página. A IA usa o texto delas para
  acertar termos, nomes, números e fórmulas que a fala transcreveu errado.
- **Na página:** seção **O que apareceu na tela** com a galeria (2 por linha, clique para ampliar) e o texto de cada
  tela recolhido: código como bloco de código, tabela como tabela do Notion.
- **Sem acumular arquivos:** telas sem conteúdo são apagadas na hora; ao publicar, só ficam as imagens que foram
  para a página (para “Refazer página”), e elas somem quando a próxima aula é publicada. Telas de aulas nunca
  publicadas e capturas de gravações descartadas são apagadas em até 7 dias.

Limites: vídeo protegido por DRM (Netflix e alguns cursos pagos) aparece preto na captura; num arquivo, o tempo de
cada tela pode atrasar até um quadro-chave (normalmente ≤ 10 s); com vários monitores, vale o monitor da janela em
uso. Sem GPU, a leitura fica para depois da gravação e é mais lenta.

## Filtrar música externa (opcional)

Para quem estuda ouvindo música. Liga em Ajustes → **Captura** → **Filtrar música externa** (desligado por
padrão; baixa uma vez o filtro, ≈ 72 MB). Desligado, nada muda: nenhum modelo é carregado e a transcrição é a mesma
de antes. Ligado, nesta ordem:

1. **Isolar a fonte (gravação):** se um app de música estiver aberto (Spotify, Deezer, TIDAL, Apple Music, Amazon
   Music, YouTube Music para desktop, foobar2000, MusicBee, AIMP…), o som dele **não é gravado** (captura por
   processo do Windows 10 2004+/11). O resto do som do PC continua entrando. A gravação mostra “Filtro de música
   ativo: o som do Spotify fica fora da gravação”.
2. **Detectar:** antes da transcrição, o Lumen procura música no áudio (gravado ou de um arquivo) a cada 0,48 s.
   Sem música, o áudio vai para a transcrição como está.
3. **Separar:** onde a música está alta por cima da fala (≈ 5 dB acima dela ou mais), a transcrição recebe só a
   voz, separada dos instrumentos no seu PC. Com a música mais baixa, nada muda: a transcrição já se vira bem com
   ela. Onde há música e não dá para ter certeza de que é a aula (música com letra, rap, voz “falada” numa música),
   o trecho fica como está e aparece marcado como **música ao fundo** na revisão; a IA o recebe como incerto e não
   o trata como fato. Nada é apagado: na dúvida, a fala fica.
4. **Voz de quem ensina:** o Lumen tira uma referência técnica da voz das partes da aula sem música (dois
   professores, entrevista ou aluno perguntando viram referências separadas) e, nos trechos com música, protege a voz
   parecida com a delas. Serve só para o filtro: fica na memória durante o processamento, não identifica ninguém e
   não é comparada com outras aulas.
5. **Original intacto:** a transcrição usa uma cópia filtrada (na pasta de trabalho, apagada ao confirmar a revisão
   ou em 7 dias). O vídeo, o arquivo e a gravação não são alterados, e o vídeo que você assiste não muda em nada.

**Modo** (aparece com o filtro ligado):

| Modo | O que faz |
|---|---|
| Conservador | Nunca corta fala; separa a voz só com confiança alta e marca mais trechos como dúvida. Para aulas e palestras importantes. |
| Balanceado (padrão) | Separa a voz onde a música cobre a fala; nunca silencia; marca o que for duvidoso. |
| Agressivo | Separa em mais trechos, marca a voz diferente da dos professores e silencia a música ao fundo onde não há fala. Pode remover mais áudio. |

Música que toca sozinha (o professor mostrando uma música para a turma, a vinheta do vídeo) nunca é silenciada, em
nenhum modo: só aparece marcada.

O filtro preserva a fala: é melhor sobrar um pouco de música do que perder uma explicação. A letra de uma música
que toca num app de música (passo 1) não chega à transcrição; a que toca no mesmo navegador da aula pode chegar,
marcada. Se ele
falhar (modelo ausente, erro, disco), a aula é transcrita do áudio original e a revisão diz que o filtro não foi
aplicado. Medições, escolhas e limites em [bench/RESULTADOS_MUSICA.md](../bench/RESULTADOS_MUSICA.md),
[bench/RESULTADOS_MUSICA_V2.md](../bench/RESULTADOS_MUSICA_V2.md) e em [docs/DECISOES.md](DECISOES.md) (“Filtro de
música externa” e “Filtro de música v2”).

## A página gerada

Em **Vídeo da aula → Link da aula**, cole o endereço do YouTube. Você também pode adicionar, trocar ou remover
esse link em **Salvar no Notion**, antes de **Criar página no Notion**. O vídeo entra como player nativo do Notion na
seção **Assistir à aula**, com legenda discreta e divisor, antes do resumo. Na fonte **YouTube**, o link informado
já é usado automaticamente. Links curtos, Shorts e lives são normalizados; outros sites ficam como referência.
Não há download do vídeo. Vídeos privados, removidos ou com incorporação bloqueada podem não tocar no Notion.

Metadados (curso, data, fonte, duração, idioma, link), sumário, **Resumo**, **Mapa mental** (imagem em alta resolução
desenhada no seu PC com o Edge, a partir do mesmo pedido à IA, sem custo de tempo extra perceptível ≈ 2 s; se o envio
da imagem falhar, o mapa entra em tópicos aninhados), **Explicação simples** (marcada como
didática), **Tópicos principais** com marcadores de tempo, **Glossário**, **Exemplos e analogias** (separando “da aula”
de “analogia didática”), **Passo a passo** quando a aula ensina um procedimento, **Perguntas de revisão** (a pergunta
fica visível e a resposta dentro de um bloco *toggle*, que abre recolhido), **Momentos da aula** (no YouTube, são links
para o tempo exato) e **Sobre esta página** (origem, modelo usado, trechos de baixa confiança, ressalvas). Com
**Assistir a tela junto**, entra também **O que apareceu na tela** depois dos tópicos.

**Visual da página:** no topo, a ficha da aula (curso, data, fonte, duração, idioma e link). Cada seção tem
seu emoji; o resumo abre com a **ideia central** em destaque; a explicação simples vem num quadro verde; os tópicos
viram **cartões numerados** em duas colunas; glossário e momentos da aula são **tabelas**; a resposta de cada
pergunta fica num quadro verde dentro do toggle; ressalvas da aula aparecem em **Pontos de atenção** (laranja). Os
termos do glossário ficam em **negrito** onde aparecem no texto.

**Gráficos da aula:** quando a aula traz números, datas ou fórmulas, a página ganha até 3 gráficos animados (GIF que
o Notion anima sem clique) logo depois dos tópicos: barras (comparar valores), linha (evolução), rosca (partes de um
todo), curvas de fórmulas e complexidades (O(n), O(n log n)…) e linha do tempo. Cada um vem com **Ver os dados**
(a tabela dos números) e o link para o momento da aula de onde eles vêm.
- **Precisão:** a IA local só propõe. O Lumen confere cada valor na transcrição e nas telas, junto do seu rótulo
  (“o bubble sort levou 5.200 ms” vale para o bubble sort, não para o merge sort citado na mesma frase); um valor que
  não se confirma derruba o gráfico inteiro. Fórmulas são calculadas pelo próprio Lumen, e só as escritas ou ditas
  na aula. A frase sob o título só entra se for da aula; senão, vem dos dados (“Maior: Bubble sort (5.200 ms)”).
- **Toda página tem gráfico**, mesmo a aula sem dados (filosofia, conceitos), sem nada inventado: **quanto tempo a
  aula dedicou a cada tópico** (do início de um tópico ao do seguinte, pelos tempos da aula) ou, sem os tempos,
  **os termos mais citados** (contados na transcrição). Ele entra depois dos gráficos com dados, sem chamar a IA.
  Com dados: ≈ 10 s a mais de IA e ≈ 2–6 s para desenhar (no Edge, no seu PC).

**Visualização 3D (Integrações → Destinos do material):** cada aula nova ganha, logo abaixo da **ideia central**, um
esquema em 3D com aparência de holograma, feito com o próprio material: a câmera gira devagar em volta da cena, os
objetos têm profundidade (o da frente cobre o de trás) e os rótulos são os conceitos da aula. A forma segue o conteúdo:

| O material tem | A cena mostra |
|---|---|
| passo a passo (aula de procedimento) | **Processo:** plataformas que sobem em perspectiva, na ordem dos passos, com a etapa em destaque andando |
| tipo “sistema” no mapa | **Sistema:** os componentes em volta do núcleo, com as relações da aula em arcos e pulsos no sentido delas |
| tipo “livro” ou partes de um todo | **Estrutura:** camadas empilhadas, uma por parte |
| uma relação “contrasta com” entre ideias principais | **Comparação:** os dois lados de um plano, cada um com os seus detalhes |
| o resto | **Conceitos:** os ramos do mapa em volta do tema central |

- **Animada** (padrão): GIF em laço de 4 s (960 × 540, 12 quadros por segundo, até 4,5 MB), que o Notion e o Obsidian
  animam sozinhos; é uma imagem, não se gira com o mouse. **Estática:** só o PNG. **Desligada:** nada.
- Nada é inventado: só o título, o mapa mental, os passos e as relações que o material já tem, sem IA nova. Uma relação
  que não está na aula não vira seta; números, datas e proporções não entram. A imagem diz “VISUALIZAÇÃO 3D”, que é um
  esquema do Lumen (rodapé) e, na legenda, se é animação ou imagem estática; no Notion, “Sobre esta página” também avisa.
- Desenhada **uma vez** no seu PC (≈ 5 s de CPU; não usa a GPU) e guardada em `%LOCALAPPDATA%\Lumen\visuals`: o mesmo
  arquivo vai ao Notion e ao Obsidian, e tentar de novo um envio, mover a aula ou reabrir o app não desenha de novo. Se
  a animação passar do tempo ou do peso, vai o PNG (e o resultado diz por quê); se nem ele sair, a aula sai sem a
  visualização, normalmente.
- **Notion:** bloco de imagem nativo (envio oficial), conferido depois lendo o bloco e comparando os bytes. Se o GIF não
  subir, vai o PNG de reserva (sem desenhar de novo). **Obsidian:** anexo da aula em `Anexos` (precisa de “Telas e
  gráficos no cofre”), embutido com `![[…]]`: funciona sem internet e sem plugin, e acompanha a pasta da aula.
- Uma por aula, no mesmo lugar. Numa página compartilhada (o módulo, “Sem curso”), cada aula tem a sua; a página do curso
  ou do módulo em si, “Minha compreensão”, a central `00 - Estudos`, a Base e os Canvas não ganham nenhuma. Ela nunca
  entra no painel visual nem vira capa: não é uma imagem da aula.
- Páginas antigas só mudam quando você as atualiza (Atualizar material, Tentar de novo, Organizar). Desligar e atualizar
  tira o visual; um anexo que você embutiu em outra nota nunca é apagado.

**Tempo restante:** enquanto transcreve e enquanto gera a página, o Lumen mostra quanto falta para a tarefa toda e o
horário previsto (“Faltam cerca de 1 min 15 s · Página pronta por volta de 14:32”; também no widget). A conta usa a
velocidade medida **no seu PC**: o próprio Ollama informa quantos tokens a IA lê e escreve por segundo; a
transcrição, as telas, os desenhos e os envios ao Notion são cronometrados. Cada aula afina a próxima (mediana das
últimas 15, em `tempos.json`), e durante cada etapa a conta se corrige (tokens já escritos, progresso).

**Capas do Notion (qualquer página):** em Ajustes → *Capas do Notion* (também em Integrações → Notion → **Criar
capa**, no Ctrl+K “Criar capa no Notion”, no curso da Biblioteca e no botão **Capa** do cartão do Notion em *Destinos
do estudo*, na Nova aula), escolha a página, gere a imagem e aplique a capa. Na Nova aula ela abre num diálogo, já
com a página do destino quando ela existe de verdade (a do curso ou do módulo, ou a página onde a aula já está); se o
destino ainda vai ser criado, o diálogo pede a página. Fechar volta à aula como estava, sem mexer na organização.
A página pode ser comum, subpágina, raiz, criada fora do Lumen ou um registro de banco de dados: basta estar
compartilhada com a integração (busque pelo título ou cole o link). Não precisa de curso, aula nem página raiz, e
funciona com o material indo “Só para o Obsidian”. **Como você quer a capa?** é opcional (sem descrição, vale o
título). A imagem é gerada no seu PC e enviada ao Notion quando você aplicar; só o campo *capa* muda (título, ícone,
propriedades e conteúdo ficam). Se a página já tem capa, o botão diz **Substituir capa**; se a capa mudou depois que
você escolheu a página, o Lumen mostra e pede a confirmação. Depois de aplicar, ele lê a página de novo e compara a
imagem da capa com a prévia, byte a byte: só então diz “Capa aplicada”. Sem resposta do Notion, diz “Não foi
possível confirmar” e, ao tentar de novo, confere antes de reenviar (reaproveitando o envio).

**Capa no curso novo (opcional):** ao criar um curso (*Organizar estudo* → *Curso* → *Novo curso*), ligue **Capa no
Notion** e clique em **Gerar prévia**. A IA local escolhe o
ícone, as cores e uma frase de destaque, e o gerador desenha a capa no seu PC; nada vai ao Notion nessa hora. Não
gostou? **Gerar outra**. **Criar curso com a capa** publica exatamente a imagem da prévia (sem gerar de novo); se o
nome mudar ou a prévia expirar (1 h), o Lumen pede uma prévia nova em vez de trocar a imagem. A prévia diz o que é:
*ilustração com IA local*, *capa alternativa com emojis* ou *capa de cor do Notion* (quando nenhum desenho saiu). Uma
página de mesmo nome que já existe no Notion é adotada como está, sem mudar capa, ícone ou conteúdo. Depois de criar,
o Lumen consulta a página para confirmar a capa e avisa se o envio falhou. O gerador (Z-Image-Turbo, ≈ 6,7 GB, Apache
2.0; prefira um SSD) é baixado em Ajustes → *Capas do Notion* → *Gerador e detalhes técnicos*; numa RTX 3060 a prévia levou 73–76 s (texto da IA +
imagem, medido em 26/10/2026).

**Trocar o destino e refazer:** o cartão *Destinos do estudo* acompanha a tela: dá para mudar a página durante a
transcrição e na revisão. Depois de publicar, **Refazer página** pede à IA uma versão nova (com um pedido opcional,
como "mais exemplos") e remove a anterior; escolhendo outra página, a aula é movida para lá. Para isso o Lumen guarda
no PC a transcrição da última aula publicada (só ela; a anterior é apagada ao publicar a próxima).

Ao repetir uma aula, o Lumen oferece **abrir** a página existente, **atualizar material** (salva a versão nova e
remove somente os blocos gerados anteriormente pelo Lumen nessa mesma página) ou **adicionar outra cópia**.
Versões antigas em outras páginas, inclusive as subpáginas criadas antes desta correção, são preservadas.
Se a publicação falhar ou for cancelada, o app tenta remover somente os novos blocos confirmados pela API.
Se não for possível confirmar um envio ou completar a limpeza, confira a página antes de tentar novamente.

## Transcrição: modelos, revisão e velocidade 2×

Os modelos foram escolhidos por um benchmark reproduzível em português (fala lida, palestras, conversas com
sotaques, ruído, música, aula longa, aula acelerada 2×). Os critérios foram fixados antes dos resultados. Detalhes
em [bench/RESULTADOS.md](../bench/RESULTADOS.md) e [bench/README.md](../bench/README.md).

| Modo (Ajustes → Transcrição) | Com GPU NVIDIA | Sem GPU |
|---|---|---|
| Rápido | Whisper small · 0,48 GB | Parakeet TDT 0.6B v3 · 0,64 GB |
| **Equilibrado (padrão)** | **Whisper large-v3-turbo** · 1,6 GB | **Parakeet TDT 0.6B v3** · 0,64 GB |
| Maior precisão | Whisper large-v3 · 3,1 GB | Whisper large-v3-turbo (lento: ~1,6× o tempo real) |

Medido numa RTX 3060 / i5-11400F, palavras erradas (WER): turbo 11,5% numa aula longa simulada com palestras
reais, Parakeet 14,3% na CPU. Velocidade: turbo ≈ 23× o tempo real na GPU; Parakeet ≈ 19× na CPU.
Nenhum modelo é perfeito: em conversa espontânea o erro passa de 20%. Por isso há a revisão.

**Revisão antes de salvar.** Depois da sua compreensão, em **Salvar no Notion → Revisar a transcrição e as telas**,
o Lumen mostra os trechos com o tempo de cada um. Você pode editar qualquer trecho. Trechos com sinal de problema
vêm destacados:
- “trecho incerto”: confiança baixa do Whisper;
- “modelos discordam”: na GPU, um segundo modelo ouve o mesmo áudio e o app mostra o que ele ouviu, para você
  escolher;
- “número” e “nome próprio”.

O resumo, as perguntas e a página saem **exatamente da versão revisada**. Nada é trocado sozinho. Os sinais não são
probabilidades; no teste, os trechos destacados erraram de 3,6× a 7× mais que os demais.

**Velocidade da fala.** No cartão "Revisar e gerar": **Automático**, **Normal**, **2×** ou **4× Ultra**. Vale a
velocidade **real do arquivo**: assistir em 2× ou 4× no player não acelera o arquivo, então use Normal. Na opção
*Gravar ao assistir*, o som gravado sai na velocidade do player. Legendas importadas mantêm os próprios tempos.
- **2×**: o Whisper turbo desacelera o áudio 0,5× mantendo o tom (16,2% de erro no teste, contra 11,5% em 1×).
  Small e Parakeet erram muito em 2× e são trocados pelo turbo.
- **4× Ultra (experimental)**: usa o turbo, desacelera 0,5× e desliga o contexto entre trechos. Foi a melhor de 46
  combinações testadas, mas **ainda erra cerca de 53% das palavras** em fala real acelerada 4×, e perde trechos
  inteiros. Use como rascunho para revisar; se tiver o arquivo em 1× ou 2×, prefira esse.
- **Automático**: mede palavras por segundo nos primeiros 2 minutos. **Não identifica 4× com segurança**: em fala 4×
  o modelo quase não reconhece nada. Quando a fala parece acelerada, ele sugere 2× e avisa que pode ser 4×; quando
  quase nada é reconhecido, pede que você escolha. A confirmação acontece na revisão ("Transcrever de novo").
- Os tempos da página ficam sempre no relógio do arquivo e nunca passam da duração dele.

**Hardware.**
- O Whisper roda na GPU NVIDIA via CUDA (CTranslate2), com 2,4 GB de VRAM no modo padrão. O modo Maior precisão
  usa float32 quando cabem cerca de 9 GB de VRAM livre; senão, float16.
- Antes de carregar um modelo, o app confere a VRAM livre. Se não couber, usa um menor e avisa.
- O Parakeet roda só na CPU, com um terço dos núcleos. Nos testes, foi mais rápido assim do que com todos, e o PC
  ficou mais leve.
- A revisão mostra o modelo, o dispositivo e o tipo numérico realmente usados.
- Medições em [bench/RESULTADOS.md](../bench/RESULTADOS.md).

**Transcrição na página.** Opcional e desligada por padrão. Se ligada, vai no fim da página dentro de um título
recolhido, com os tempos.

A geração com `qwen3:8b` levou ≈ 30 s para uma aula curta na GPU. Na CPU, espere vários minutos. Aulas longas
(acima de ~40 mil caracteres de transcrição) são lidas por partes e depois consolidadas.

Para outro modelo, informe o nome em Ajustes → IA local → Avançado (ex.: `qwen3:4b` para PCs com menos memória).

## Estudos (Lúmen Study AI)

A aba **Estudos** é um assistente de estudos sobre o seu Notion e o seu Obsidian ao mesmo tempo.

**O que ele faz**
- **Pesquisa por palavras e por significado:** usa embeddings `qwen3-embedding:0.6b` no Ollama.
- **Conversa com fontes verificáveis:** cada `[1]` abre o trecho usado e o original, e referência inventada é removida.
- **Modos de estudo:** explica em três níveis, resume, compara, gera flashcards com revisão espaçada, monta questionários com correção, plano de estudos, mapa de conhecimento e o que falta estudar.
- **Organização:** projetos, memória (que você vê, edita e apaga) e conversa temporária.
- **Salvar:** grava no Obsidian (`C04 Claude Obsidian/01 Outputs`) ou no Notion, **sempre com prévia e confirmação**.

**Como conectar**
- **Notion:** use a mesma integração de [Conectar o Notion](#conectar-o-notion-api-oficial). Compartilhe as páginas de estudo com ela e, em Estudos → Fontes, clique em **Sincronizar**. A busca da API do Notion só vê títulos, então o conteúdo é indexado aqui no PC. Só as páginas alteradas são relidas.
- **Obsidian:** o cofre de Integrações é lido direto do disco, só leitura. Funciona com o Obsidian fechado e não precisa de plugin. A pasta `.obsidian` e a cópia do Notion criada pela Proteção do cérebro ficam de fora.
- **Provedor de IA — só a IA local:** o Lúmen responde pelo Ollama, no seu PC, sem cota de API (o limite é a placa de vídeo e a janela de contexto). O **Gemini foi retirado em 09/11/2026** (sem adaptador, modelo, chave, tela nem rota); um ajuste antigo que o escolhia volta sozinho para a IA local, uma única vez, com uma cópia do arquivo (`settings.json.antes-remocao-gemini-20261109.bak`). **Claude (Anthropic) e OpenAI estão bloqueados** (cobrados por token, sem plano gratuito comprovado). Sem modelo instalado, a tela diz como escolher ou baixar um em Ajustes → IA local (Ollama); o Lúmen não baixa modelos sozinho. Relatório da retirada: `docs/implementation/LUMEN_REMOCAO_GEMINI_20261109.md`.
- **Imagens e vídeos:** imagens e capas são geradas só pelo gerador local. O Lúmen não gera vídeo; vídeos criados antes continuam no histórico.
- **Permissão externa:** nada do que você escreve ou estuda sai do PC por IA: o texto da conversa, o áudio e as notas ficam aqui (as vozes também são sempre locais). `/web` faz a pesquisa guiada no Edge, e só a consulta vai ao buscador. A assinatura do ChatGPT/Claude não inclui a API.
- **Perplexity (Integrações → Perplexity, o botão ↗ “Pesquisar no Perplexity” na caixa de mensagem do Cérebro, ou `/perplexity <pergunta>`):** abre o site oficial do Perplexity (`https://www.perplexity.ai/search?q=…`, o modelo do `opensearch.xml` dele) num painel dentro da janela do Lúmen, com a **sua** conta de lá; não usa a API. Antes de abrir, um diálogo mostra a pergunta (editável) e avisa que só ela sai do Lúmen: conversa, notas, anexos e fontes não vão. O painel (`SiteView`, em `launcher/Lumen.cs`) tem perfil WebView2 próprio (`%LOCALAPPDATA%\Lumen\webview-perplexity`, separado do Lúmen, do HyperbookLM e do Open Notebook), que guarda o login entre aberturas; o Lúmen não lê senha, cookie nem token, não roda script na página nem clica nada nela, e a página não tem ponte com o aplicativo. Ficam dentro do painel só `https` de `www.perplexity.ai`, `perplexity.ai`, `accounts.google.com` e `appleid.apple.com` (entrar com Google ou Apple); link de fora clicado (as fontes) abre no navegador padrão, e redirecionamento para fora, outros esquemas, downloads e permissões (microfone, câmera, localização, notificações) são bloqueados, com aviso na barra. **Para trazer a resposta:** clique em Copiar no Perplexity e em **Trazer resposta ao Lúmen** na barra (ou digite `/perplexity` sem pergunta) e cole; o texto entra na caixa de mensagem com a marca *[Conteúdo do Perplexity colado por mim · não verificado pelo Lúmen]*, com fontes e links como vieram, e nada é enviado até você mandar. Acima de 8 000 caracteres (o limite de uma mensagem), entra inteiro como anexo `perplexity-….md`. Fora do `Lumen.exe` (ou num anterior a esta função), abre no navegador padrão. Limites (pela regra, ainda não vistos com conta): o login com SSO de empresa vai para o provedor da empresa, que o painel não abre (deve aparecer “Bloqueado: …”); um link de entrada recebido por e-mail abre no navegador padrão, não no painel. O login com conta (Google, Apple, e-mail) ainda não foi conferido no painel; se o Google ou a Apple recusarem o navegador embutido, o Lúmen não contorna: use o e-mail ou abra pelo navegador. Conferência nativa: `tests/PerplexityCheck.cs` (decisão D185).

**Testes**
- `.venv\Scripts\python -m unittest tests.test_study_index tests.test_study_core`
- `py -3.14 tests/study_ui.py`

Arquitetura e decisões em `docs/implementation/`.

## Privacidade

- Processado no PC: decodificação do áudio, transcrição, análise da sua compreensão, escrita do material.
- Suas notas de compreensão ficam em `%LOCALAPPDATA%\Lumen\understanding` e só vão para o Notion ao salvar.
- Enviado ao Notion: só o texto da página. Ao YouTube: apenas uma consulta ao oEmbed público para obter o título.
- Sem telemetria (o download dos modelos do Hugging Face roda com `HF_HUB_DISABLE_TELEMETRY=1`).
- O log (`%LOCALAPPDATA%\Lumen\lumen.log`) registra só etapas e tipos de erro, nunca tokens ou conteúdo.
- Gravações ficam no PC só até você confirmar a revisão. Transcrições ficam em `%LOCALAPPDATA%\Lumen\work` para permitir
  retomar após uma falha; publicada a aula, só a da última aula salva continua lá (a anterior é apagada).
- Dados antigos do Gemini Notebook (a integração foi retirada): os arquivos preparados e os materiais trazidos ficam em
  `%LOCALAPPDATA%\Lumen\notebook`, sem nenhum código que os leia. Ajustes → Privacidade e dados → **Limpar** apaga tudo.
  **Desconectar Notion** (em Integrações) também remove o token.
- Assistir a tela junto: as capturas ficam no PC e são lidas pelo modelo local; só as imagens das telas que você
  mantiver na revisão vão para o Notion. Detalhes em [Assistir a tela junto](#assistir-a-tela-junto-opcional).
- Filtrar música externa: detecção e separação no PC; o áudio filtrado é uma cópia temporária, e o log guarda só
  confianças e durações (nada do que foi dito ou cantado).
- Estudos (Lúmen Study AI): o índice, as conversas e as memórias ficam em `%LOCALAPPDATA%\Lumen\study`; a IA local é o padrão. Nenhuma IA em nuvem recebe
  texto seu; o histórico de atividades guarda só ação, modelo e contagens (nunca o conteúdo), e “Seus dados no Lúmen” mostra,
  exporta e apaga tudo. Claude e OpenAI estão bloqueados. Detalhes em [Estudos](#estudos-lúmen-study-ai).
- O servidor da interface escuta só em `127.0.0.1`, confere o cabeçalho `Host` e exige um token aleatório por sessão.

## Testes

```
.venv\Scripts\python -m unittest discover -s tests -t .
```

Não usam credenciais nem a internet: Notion e Ollama são simulados (o Notion falso confere os limites documentados
da API). Verificação ponta a ponta real (Whisper + Ollama de verdade, Notion simulado):

```
.venv\Scripts\python -m tests.e2e <pasta-com-amostras>
```

Design system: `.venv\Scripts\python -m unittest tests.test_ui_tokens` (contraste dos tokens, nenhuma cor solta, escala de texto, alinhamento).

Interface (Playwright no Python do sistema, Chrome sem GPU como o WebView2; API simulada e dados isolados):

```
py -3.14 tests\ui_shots.py [nome] [--sizes] [--zoom]
py -3.14 tests\ui_shots.py --walk          (o uso de ponta a ponta, clicando nos botões)
py -3.14 tests\widget_ui.py
```

`ui_shots.py` captura todas as telas e estados (Início, Nova aula, Minha compreensão, processamento, análise,
Biblioteca, Integrações, cada categoria de Ajustes, busca, confirmação, avisos, barra flutuante e janela da nota) em
`tests\desktop-artifacts\ui\`, de 520×560 a 1920×1040 e de 80% a 120%, e falha com erro de página, rolagem horizontal,
controle cortado ou alvo de clique menor que 24 px. `tests\test_ui_tokens.py` confere o contraste dos tokens e que não
há cor solta fora de `ui.css`. O mostruário dos componentes fica em `http://127.0.0.1:<porta>/design`.
No `DesktopChecks.cs`, defina `LUMEN_SHOTS=<pasta>` para guardar imagens das três janelas reais do WebView2.

Para publicar de verdade numa página **sua** de teste, defina `LUMEN_E2E_TOKEN` e `LUMEN_E2E_PARENT`.
Leitura da tela: `.venv\Scripts\python -m bench.vision_bench make` e `run qwen3.5:4b` (ver `bench/README.md`).
As amostras podem ser geradas com a voz do Windows e o ffmpeg (ver `docs/DECISOES.md`).

Decisões técnicas e limitações: [docs/DECISOES.md](DECISOES.md).


## Proteção do cérebro

Em Ajustes → Proteção do cérebro, use **Fazer backup agora** para guardar uma cópia sem mudar a pausa do automático. A tela acompanha o trabalho e só confirma a conclusão depois de conferir os destinos. Para as próximas cópias, use o controle **Backup automático**.

A tela separa **Backups para recuperar suas notas** (neste computador e no Google Drive: versões completas e criptografadas) de **Notas para consultar no outro aplicativo** (Notion → Obsidian e Obsidian → Notion: cópias navegáveis, que não substituem o backup). Cada destino tem o próprio sinal, com ícone e texto: *Cópia confirmada*, *Conferindo alterações*, *Copiando agora*, *Aguardando a primeira cópia*, *Cópia anterior disponível; atualização pendente*, *Precisa de atenção*, *Destino indisponível* ou *Ainda não foi possível confirmar*. Os backups dizem qual versão do Obsidian e do Notion guardam. Esses estados vêm só das confirmações gravadas pelo motor; conexão ativa, pasta existente ou pedido aceito não contam como cópia.

Se ainda faltar algo, a tela indica a próxima ação. Em **O que precisa de atenção**, cada item diz o que aconteceu, o que já está guardado e o que fazer. Em **O que guardar**, confira o cofre inteiro e as páginas do Notion ou adicione seus links. Em **Segurança e recuperação**, guarde sua chave de recuperação separada do backup. As configurações existentes são preservadas. Mantemos todas as versões, sem limpeza automática.

A recuperação cria uma pasta nova. Consulte [o guia independente](RECUPERAR-PROTECAO.md) e [os testes e limites da entrega](CONTINUIDADE-PROTECAO.md). A pasta pessoal não é configurada pelos testes.
