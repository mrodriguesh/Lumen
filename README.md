# Lumen

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

1. Instale o Python e o Ollama. Abra o Ollama uma vez.
2. Dê dois cliques em **`Iniciar Lumen.bat`**. Na primeira vez ele cria `.venv`, instala as dependências e, se encontrar
   uma GPU NVIDIA, pergunta se deve baixar o suporte a GPU (≈ 1 GB).
3. Depois disso, abra pelo **`Lumen.exe`**: uma janela nativa com ícone próprio. Para fixar, clique com o botão
   direito no ícone dele na barra de tarefas e escolha **Fixar na barra de tarefas**. Fechar a janela recolhe o app;
   para encerrar, use o botão vermelho no rodapé da barra flutuante ou **Sair do Lumen** na bandeja do Windows.

`Lumen.exe` é um programa pequeno em C# (`launcher/Lumen.cs`) que abre a interface no WebView2 do Windows e inicia o
Python em segundo plano. Para recompilar: `powershell -ExecutionPolicy Bypass -File launcher/build.ps1` (usa o
compilador C# que já vem no Windows). O ícone é gerado por `launcher\make-icon.ps1`.

Pela linha de comando: `.venv\Scripts\python -m lumen`.

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
- **Escrever depois:** a aula fica em **Continuar aprendendo**, no topo de Nova aula, até ser salva no Notion.
- **Destacar (Ctrl+Shift+D):** o ícone no canto do papel leva a nota para uma janela flutuante, sempre por cima, para
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
A barra mostra um único botão **Gravar/Parar**, o tempo da captura e atalhos discretos para abrir o app e os ajustes.
A engrenagem abre todas as configurações dentro da própria barra, organizadas em categorias: barra flutuante,
Notion, transcrição, IA local, capas e privacidade. Os campos maiores têm rolagem e os downloads mostram progresso.
A limpeza exige confirmação e fica bloqueada durante gravações e tarefas, preservando os arquivos em uso.
Instruções de silêncio e mensagens de erro aparecem quando necessárias. Ao parar, a janela principal abre com a gravação pronta para usar.
Fechar a janela principal mantém a captura e o processamento ativos.

Em **Ajustes → Lumen sempre por perto**, escolha esquerda, direita, em cima, embaixo, posição livre ou desativada;
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

### Pomodoro

Um timer só (`lumen/pomodoro.py`, guardado em `pomodoro.json`), mostrado na barra, na janela flutuante de “Minha
compreensão” (clique no tempo para os controles) e na janela principal. Foco, pausa curta, pausa longa e ciclos são
personalizáveis (25/5/15/4 por padrão; atalhos 25 e 50 min), com **Iniciar a próxima etapa sozinho** (desligado) e
**Som ao terminar** (ligado). O tempo vem do horário em que a etapa termina, não de ticks: minimizar, fechar janelas,
reiniciar o app ou suspender o PC não atrasa nada. É independente da captura: um nunca pausa o outro. No fim de uma
etapa: notificação do Windows sem som, destaque discreto no timer e um som curto do Lumen, que não toca enquanto a
captura grava (entraria na aula).

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

Os modelos não são baixados sem pedido: o app mostra o tamanho e um botão **Baixar** em Configurações.

## Conectar o Notion (API oficial)

O Lumen usa uma **integração interna** do Notion. A integração pública (OAuth) exigiria um servidor com segredo de
cliente, que um app local e gratuito não pode guardar com segurança.

1. Acesse <https://www.notion.so/profile/integrations> → **Nova integração** → tipo *Interna*, no seu workspace.
2. Capacidades: *Ler conteúdo*, *Atualizar conteúdo*, *Inserir conteúdo*. Não precisa de informações de usuários.
3. Copie o token secreto e cole em **Configurações → Notion**. Ele é validado e guardado no
   Gerenciador de Credenciais do Windows (via `keyring`), nunca em arquivo.
4. No Notion, crie uma página (ex.: “Estudos”), abra **••• → Conexões** e adicione a integração.
5. Em Configurações, escolha essa página como **página raiz dos cursos**.

Você pode escolher uma página existente ou criar uma página dentro da raiz. A aula é acrescentada diretamente
à página escolhida, com um título para o material, preservando o nome, a capa, o ícone e o conteúdo anterior.
“Sem curso” é criada sob demanda quando nenhum destino específico é escolhido; as aulas ficam no corpo dela.

O Notion só mostra à integração as páginas liberadas para ela. Para escolher as **páginas raiz** do seu workspace
(as do topo da barra lateral), libere-as em <https://www.notion.so/profile/integrations> → sua integração →
**Acesso** → *Editar acesso* (o botão “Dar acesso no Notion” do app abre essa tela). Liberar uma página raiz libera
tudo o que está dentro dela; no app elas aparecem no grupo “Páginas raiz do Notion”. A API não permite que uma
integração interna crie páginas no topo do workspace, só dentro de uma página.

## Notion e Obsidian

O Lumen escreve o material **uma vez** e salva o mesmo conteúdo em cada destino: o Notion para organizar e
acompanhar, o Obsidian para estudar a fundo e ligar ao seu segundo cérebro. Em **Ajustes → Destinos do material**:

1. Escolha **Notion + Obsidian**, **Só Notion** (padrão, como antes) ou **Só Obsidian** (não precisa do Notion).
2. Escolha o **cofre do Obsidian**. O Lumen lista os cofres registrados neste PC, mas nunca escolhe sozinho;
   **Escolher pasta…** aceita qualquer pasta com `.obsidian`.
3. **Pasta das notas de estudo**: por padrão, a área da IA do cofre (ex.: `C04 Claude Obsidian/16 Lumen`). O Lumen não
   escreve fora dela.

Para cada aula, no Obsidian:

- **Nota de estudo** `AAAA-MM-DD - Título da aula.md` (`type: ai-study`, `author: lumen-ai`,
  `status: review-required`), com:
  - a sua compreensão, intacta, e a análise da IA à parte;
  - visão geral, conceitos com o tempo da aula (no YouTube, o tempo é um link);
  - explicação, glossário, exemplos, passo a passo e telas;
  - perguntas de active recall com a resposta escondida, teste de compreensão e flashcards;
  - erros comuns, aplicações e conexões com notas reais do cofre;
  - perguntas em aberto, linha do tempo, revisões e "Possíveis notas permanentes".
- **Mapa mental** `Mapa - Título da aula.canvas`, um Canvas de verdade:
  - a nota no centro e os ramos ao redor, com as relações da aula nas setas;
  - embaixo, os grupos Processo, Conexões, Exemplos e Relações.

  Pode mover os cards: ao reprocessar, o que você moveu ou criou fica.
- **Lumen Dashboard**: para revisar hoje, atrasados, recentes, não revisados, por curso, por Anchor Topic, com
  dúvidas e ideias para notas permanentes. Usa o Bases, um plugin nativo do Obsidian.

Regras que protegem o que é seu:

- O material da IA nunca vira nota permanente sozinho. As ideias candidatas ficam marcáveis para você escrever com as
  suas palavras.
- Escreva em **Minhas anotações**, no fim da nota. Reprocessar refaz só o bloco do Lumen; suas anotações, as caixas
  marcadas e as propriedades que você mudou ficam.
- Se você editar dentro do bloco do Lumen, a próxima atualização para e avisa. **Substituir mesmo assim** guarda uma
  cópia antes.
- Reprocessar não cria cópias. A nota é achada pelo `lumen-id` mesmo se você a renomear dentro da pasta do Lumen.
- **Revisões:** marque `Revisão N` na nota. Ao abrir o Lumen, ele atualiza `next-review`. Os intervalos (padrão 1,
  3, 7, 14, 30 e 60 dias) ficam em Ajustes.
- **Profundidade** (Ajustes → IA local):
  - Rápido: uma passada.
  - Balanceado: com conexões no cofre.
  - Profundo: uma 2ª passada critica e melhora o material.

  Tudo roda no Ollama local: nada do cofre sai do PC.
- Se um destino falhar, o outro fica salvo, e **Tentar de novo só o Notion/Obsidian** refaz só o que faltou, sem
  chamar a IA.

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

Liga no cartão **Fonte** (ou em Ajustes). O Lumen passa a olhar a aula com você e põe na página o que aparece na
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

Para quem estuda ouvindo música. Liga em Ajustes → **Música de fundo** → **Filtrar música externa** (desligado por
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
aplicado. Medições, escolhas e limites em [bench/RESULTADOS_MUSICA.md](bench/RESULTADOS_MUSICA.md),
[bench/RESULTADOS_MUSICA_V2.md](bench/RESULTADOS_MUSICA_V2.md) e em [docs/DECISOES.md](docs/DECISOES.md) (“Filtro de
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

**Tempo restante:** enquanto transcreve e enquanto gera a página, o Lumen mostra quanto falta para a tarefa toda e o
horário previsto (“Faltam cerca de 1 min 15 s · Página pronta por volta de 14:32”; também no widget). A conta usa a
velocidade medida **no seu PC**: o próprio Ollama informa quantos tokens a IA lê e escreve por segundo; a
transcrição, as telas, os desenhos e os envios ao Notion são cronometrados. Cada aula afina a próxima (mediana das
últimas 15, em `tempos.json`), e durante cada etapa a conta se corrige (tokens já escritos, progresso).

**Capas com IA (opcional):** em Ajustes → *Capas com IA*, baixe o Z-Image-Turbo (≈ 6,7 GB, Apache 2.0; prefira um
SSD). Ao criar uma página com “Enfeitar com IA”, a capa vira uma ilustração do tema gerada no seu PC (≈ 30–45 s
numa RTX 3060). Sem ele, a capa é desenhada com emojis.

**Trocar o destino e refazer:** o cartão *Onde salvar* acompanha a tela: dá para mudar a página durante a
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
em [bench/RESULTADOS.md](bench/RESULTADOS.md) e [bench/README.md](bench/README.md).

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
- Medições em [bench/RESULTADOS.md](bench/RESULTADOS.md).

**Transcrição na página.** Opcional e desligada por padrão. Se ligada, vai no fim da página dentro de um título
recolhido, com os tempos.

A geração com `qwen3:8b` levou ≈ 30 s para uma aula curta na GPU. Na CPU, espere vários minutos. Aulas longas
(acima de ~40 mil caracteres de transcrição) são lidas por partes e depois consolidadas.

Para outro modelo, informe o nome em Configurações → IA local (ex.: `qwen3:4b` para PCs com menos memória).

## Privacidade

- Processado no PC: decodificação do áudio, transcrição, análise da sua compreensão, escrita do material.
- Suas notas de compreensão ficam em `%LOCALAPPDATA%\Lumen\understanding` e só vão para o Notion ao salvar.
- Enviado ao Notion: só o texto da página. Ao YouTube: apenas uma consulta ao oEmbed público para obter o título.
- Sem telemetria (o download dos modelos do Hugging Face roda com `HF_HUB_DISABLE_TELEMETRY=1`).
- O log (`%LOCALAPPDATA%\Lumen\lumen.log`) registra só etapas e tipos de erro, nunca tokens ou conteúdo.
- Gravações ficam no PC só até você confirmar a revisão. Transcrições ficam em `%LOCALAPPDATA%\Lumen\work` só até a página ser publicada, para permitir retomar após uma
  falha. Configurações → **Limpar histórico e dados locais** apaga tudo. **Desconectar Notion** também remove o token.
- Assistir a tela junto: as capturas ficam no PC e são lidas pelo modelo local; só as imagens das telas que você
  mantiver na revisão vão para o Notion. Detalhes em [Assistir a tela junto](#assistir-a-tela-junto-opcional).
- Filtrar música externa: detecção e separação no PC; o áudio filtrado é uma cópia temporária, e o log guarda só
  confianças e durações (nada do que foi dito ou cantado).
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

Para publicar de verdade numa página **sua** de teste, defina `LUMEN_E2E_TOKEN` e `LUMEN_E2E_PARENT`.
Leitura da tela: `.venv\Scripts\python -m bench.vision_bench make` e `run qwen3.5:4b` (ver `bench/README.md`).
As amostras podem ser geradas com a voz do Windows e o ffmpeg (ver `docs/DECISOES.md`).

Decisões técnicas e limitações: [docs/DECISOES.md](docs/DECISOES.md).
