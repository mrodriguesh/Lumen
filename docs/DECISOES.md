# Decisões e limitações

Pesquisado em outubro de 2026, nas documentações oficiais citadas.

## Arquitetura

Um único processo Python:

```
lumen/
  __main__.py    inicia o servidor e abre a janela; encerra quando a janela fecha
  server.py      HTTP só em 127.0.0.1 (stdlib): interface + API JSON
  jobs.py        uma tarefa por vez: preparar → transcrever → gerar → publicar; guarda etapas para retomar
  sources.py     arquivo local, link do YouTube, legendas/transcrições importadas
  transcribe.py  faster-whisper (CPU ou GPU NVIDIA)
  llm.py         Ollama: prompt, JSON Schema, validação, leitura por partes
  notion.py      API REST do Notion (stdlib urllib) e montagem dos blocos
  store.py       config.json, history.json, token no cofre do sistema
  web/           HTML/CSS/JS sem framework
```

- **Interface**: HTML servido localmente. No Windows, o `Lumen.exe` (C#, `launcher/Lumen.cs`) mostra essa
  interface numa janela nativa com o WebView2 (já instalado no Windows 11), escolhe uma porta livre, inicia
  `pythonw -m lumen` e coloca tudo num Job Object, para que fechar o app encerre também o Python. Sem o exe,
  `python -m lumen` abre o Edge com `--app` ou o navegador padrão.
- **Janela estilo Mac**: o `Lumen.exe` remove a barra de título nativa (WM_NCCALCSIZE, mantendo bordas, sombra e
  Snap) e a página desenha a barra com os três botões de janela. A área arrastável usa `app-region: drag`
  (`IsNonClientRegionSupportEnabled`, WebView2 123+); os botões enviam `window:close|minimize|maximize` por
  `postMessage`. Com WebView2 mais antigo, volta a barra nativa. Limitação: não dá para redimensionar pela borda de cima.
- **Barra flutuante**: `launcher/WidgetForm.cs` cria uma segunda janela WinForms sem moldura, sempre sobre as demais,
  com a interface `web/widget.*`. Compartilha o servidor e o perfil do WebView2. O loopback é único e os comandos
  de iniciar/parar/descartar são serializados entre as duas interfaces. A gravação parada é entregue à janela
  principal por mensagens do host; fechar a janela recolhe o app, e sair finaliza o WAV antes de encerrar o Python.
  A posição fica em `%LOCALAPPDATA%\Lumen\widget-position.txt`; o ajuste de posição respeita a área útil de cada tela.
  A inicialização automática usa a chave Run do usuário com `Lumen.exe --background`, sem gravar automaticamente.
  A apresentação segue o tamanho real do WebView2, evitando que mensagens de recolhimento atrasadas deixem
  uma alça ampliada no lugar dos controles. A posição v3 registra o canto superior e a orientação da alça;
  posições anteriores são convertidas. A alça e os controles assumem disposição horizontal nas bordas superior
  e inferior. O encaixe considera os dois eixos e o painel se mantém dentro da área útil ao crescer.
  A interface usa renderização por software no WebView2, configurada apenas no processo do Lumen. A verificação
  nativa apresentou encerramentos com aceleração gráfica durante o redimensionamento e passou com esse modo.
  Os motores de transcrição usam suas próprias configurações de hardware.
- **Visual**: inspirado na linguagem dos apps da Apple (cartões agrupados, barra translúcida, controle segmentado,
  chave liga/desliga), com desenho próprio: sem fontes, ícones ou imagens da Apple. A fonte é a Inter (OFL,
  `lumen/web/fonts/OFL.txt`). As DLLs do SDK do WebView2 (licença BSD da Microsoft, `launcher/bin/LICENSE-WebView2.txt`)
  vêm do pacote NuGet oficial `Microsoft.Web.WebView2`. Electron, pywebview e Qt foram descartados:
  são dependências grandes, e o pythonnet do pywebview ainda não acompanha o Python 3.14.
- **Escolha de arquivo**: diálogo nativo do `tkinter` (stdlib) num subprocesso, que devolve o caminho real sem copiar
  o vídeo. Arrastar para a janela copia o arquivo para `work\uploads` (o navegador não expõe caminhos); a cópia é
  apagada depois da publicação.
- **Dependências**: `faster-whisper` (MIT), `av` (BSD), `keyring` (MIT). GPU opcional: bibliotecas CUDA da NVIDIA via pip.
  O resto é stdlib (HTTP, JSON, cliente do Notion e do Ollama).
- **`av` fixado em 16.1.0**: as versões 17+ removeram o argumento `metadata_errors`, que o faster-whisper 1.2.1 usa.

## Transcrição (auditada em 07/10/2026; ver bench/)

- **Motores**: faster-whisper/CTranslate2 (GPU float16 ou CPU int8) e, na CPU, Parakeet TDT 0.6B v3 via
  `onnx-asr` (MIT; ONNX int8 + VAD Silero; sem PyTorch). Os modelos são baixados só com o clique em **Baixar**,
  e a transcrição usa sempre arquivos locais. Se a GPU falhar antes do primeiro trecho, o app tenta na CPU.
- **Escolha dos modelos**: benchmark com FLEURS pt-BR e CORAA (transcrição humana) mais condições derivadas,
  e critérios fixados antes ([bench/CRITERIOS.md](../bench/CRITERIOS.md)). Turbo, large-v3 e Parakeet empataram
  (menos de 1 ponto de diferença em palestra + aula longa), e venceu o mais rápido na GPU. O medium reprovou: inventou
  texto em silêncio/música. Na CPU, o turbo reprovou em velocidade (1,6×) e o Parakeet passou (19×). O Canary
  1B v2 passou nos critérios, mas perdeu em qualidade e velocidade.
- **Opções auditadas**: `condition_on_previous_text=True` (aula longa: 11,5% contra 12,8% com `False`) e VAD ligado
  (sem ele apareceu texto em trecho sem fala). Idioma automático deu o mesmo resultado que forçar `pt`.
  **Hotwords** (vocabulário do curso) melhoraram o texto, mas deslocaram os timestamps em ~15 s, então não são
  usados. Correção de termos fica na revisão manual.
- **Sinais para revisão** (critério 10: trechos marcados erram ≥ 2× mais):
  - `avg_logprob < -1` (7,2×, mas marca poucos trechos);
  - divergência com o whisper-small na GPU (limite 0,2 pela regra registrada antes: marca 27,5%, que erram 3,6×
    mais). O segundo modelo custa cerca de 4% do tempo na GPU e nunca troca o texto: só marca e mostra a
    alternativa.

  A divergência com o Parakeet foi um sinal melhor (5,4×), mas custaria quase o dobro do tempo; ficou registrada
  como alternativa.
- **Fala 2×** (sintética: palestras reais aceleradas com atempo). O controle por reamostragem, que muda o tom, ficou
  com 45–90% de erro. Com as opções finais do app, desacelerar 0,5× mantendo o tom melhorou o turbo (GPU 17,7% →
  16,2%; CPU 20,9% → 16,0%), piorou ou empatou o large-v3 e o small, e Parakeet e small erram demais em 2× (36% e
  26%). Os tempos voltam à linha do tempo do arquivo (erro mediano 0,07 s).
- **4× Ultra** (adendo 3; `bench.ultra`): 6 configurações × preparações direto/0,5/0,33/0,25 (atempo), mais
  Rubber Band (FFmpeg do sistema) e `condition_on_previous_text=False`. Nenhuma passou no critério 12 (≤ 30%).
  Melhor: turbo + 0,5× + sem contexto entre trechos (53,2%). Voltar à velocidade natural (0,25×) foi pior
  (64–83%), e o Rubber Band também (64–81%). Por isso o 4× é **experimental**, com o erro medido na tela.
  Acelerar 4× com algoritmos que preservam o tom descarta cerca de 3/4 da forma de onda, e nenhum modelo recupera isso.
- **Automático**: limite de 2,9 palavras/s entre 1× e 2× (faixas encostadas, 2,90 × 3,00), por isso é só sugestão.
  Com fala 4×, o modelo reconhece quase nada (0,06–8,6 palavras/s), e depois de desacelerar 0,5× as faixas de 2× e 4×
  se sobrepõem. O app nunca afirma 4×: sugere 2× ("pode ser 2× ou 4×") e, abaixo de 1,2 palavra/s, pede a escolha.
- **Hardware** (medido; GPU% é da placa inteira via nvidia-smi):
  - Whisper: CUDA via CTranslate2, de 34% a 84% de uso médio da GPU e 1,5 a 5 núcleos de CPU. A GPU não satura
    porque a busca em feixe é sequencial.
  - Lotes (`BatchedInferencePipeline`): 2× mais rápido, mas mais erro e timestamps grosseiros, então não foi
    adotado (critério 14).
  - Float16 × float32: turbo igual (−0,14 ponto); large-v3 +0,57 ponto em 1×. Por isso o modo Maior precisão usa
    float32 quando a VRAM permite. É um caso de fronteira, dentro da variação entre execuções.
  - Parakeet: onnxruntime só para CPU; o pacote com CUDA conflitaria com o onnxruntime que o faster-whisper usa.
    Com 4 threads (1/3 dos núcleos lógicos) foi 2× mais rápido que com 12 e deixou outro programa só 1,4× mais lento.
  - A prioridade baixa do processo não trouxe ganho medido e ficou desligada. A API local respondeu com p95 ≤ 287 ms
    em todos os casos.
  - Antes de carregar um modelo na GPU, o app confere a VRAM livre (`nvidia-smi`). Se ela não for suficiente, usa
    um modelo menor ou a CPU. Uma falha de CUDA antes do primeiro trecho leva à CPU.
- **Variação**: com o fallback de temperatura do Whisper, a mesma configuração pode mudar entre execuções (o
  large-v3 2× desacelerado deu 26,7% numa rodada e 17,3% na outra).

## IA (texto)

- Ollama (MIT) em `127.0.0.1:11434`, com `format` = JSON Schema (saídas estruturadas) e `think: false`.
  Modelo padrão `qwen3:8b` (Apache 2.0, contexto de 40k). Usa `num_ctx` de 20480 tokens.
- A resposta passa por `llm.validate`: campos obrigatórios, listas limpas, marcadores de tempo inexistentes ou além
  da duração descartados. Se vier malformada, tenta mais uma vez. Na segunda falha, gera um erro recuperável e nada
  é publicado.
- O prompt exige usar só a transcrição. A explicação simples e as analogias são rotuladas como didáticas na página.
- Não há opção em nuvem. Nenhum serviço gratuito encontrado tinha custo e limites estáveis o bastante para cumprir
  o requisito de transparência.

## Notion

- API REST oficial, `Notion-Version: 2026-03-11` (a mais recente). Nessa versão: `archived` → `in_trash`, e o
  `after` do append virou `position`. O Lumen usa `in_trash` e não usa `position`.
- Limites respeitados (developers.notion.com/reference/request-limits): até 100 blocos por requisição (o resto vai
  em lotes por `PATCH /blocks/{id}/children`), 2000 caracteres por rich text (textos longos são divididos), até dois
  níveis de aninhamento por requisição (o toggle tem um), e 429 tratado com `Retry-After`.
- **Integração interna** com token, não OAuth público: o OAuth exige um `client_secret` num servidor, o que um app
  local e gratuito não tem.
- Destino em páginas, não em banco de dados: a aula entra como blocos no corpo da página escolhida,
  sem criar uma subpágina. A criação explícita de cursos e módulos continua disponível.
- Respostas das perguntas ficam como filhas de blocos `toggle`. O Notion abre toggles recolhidos, e o estado aberto é
  por leitor e não é exposto pela API.
- Publicação: uma aula comum (≈ 30–60 blocos) é acrescentada numa requisição. Se um lote falhar ou o usuário
  cancelar, somente os blocos novos confirmados são removidos; a página e o conteúdo anterior são preservados.
  O append não é repetido automaticamente após erro de rede ou HTTP 5xx: a API pode já ter recebido o lote.
  Falhas na confirmação ou limpeza pedem conferência no Notion antes de tentar novamente.
- Duplicatas: `history.json` associa a fonte (ID do YouTube, ou hash do tamanho + primeiro MB do arquivo) à página.
  Antes de oferecer a escolha, o app confere pela API se a página ainda existe fora da lixeira.
  Guarda também os IDs dos blocos publicados: atualizar remove apenas esses blocos após salvar a nova versão.
  Se o destino mudou ou o histórico é antigo, preserva a página anterior e informa isso na interface.
- **Imagens não foram incluídas.** Um quadro do vídeo exigiria a File Upload API (limite de 5 MB por arquivo no
  plano gratuito) e só valeria para arquivos locais. Os metadados, callouts e o sumário já dão a hierarquia visual.

## Capas com IA (08/10/2026)

- **Gerador:** stable-diffusion.cpp (build Vulkan, MIT) + **Z-Image-Turbo** Q4_K (Apache 2.0, Alibaba Tongyi), com
  Qwen3-4B como codificador de texto. Tudo local, sem chave e sem nuvem; ≈ 6,7 GB, baixados só com o clique em Ajustes.
- **Comparação:** mesmos 4 temas e mesma semente contra o FLUX.2 [klein] 4B. O Z-Image fez ilustrações mais bonitas e
  não desenhou texto deformado; o klein desenhou letras ilegíveis nas capas.
- **Ollama descartado:** a geração de imagem do Ollama exige MLX (só macOS).
- **Tempo (RTX 3060, 1536×640, 8 passos):** ≈ 33 s com os pesos num SSD (CUDA: 29 s, mas +1,1 GB e só NVIDIA, por
  isso Vulkan). Num HD a leitura de 6 GB somava ~100 s. Com `--offload-to-cpu --vae-tiling` passou de 4 min.
- **Pedido da imagem:** o qwen3 escreve a cena em inglês (`image_prompt`), sai da VRAM (`keep_alive=0`) e o Lumen
  remove palavras que viram texto falso ou moldura (interface, tela, código, documento, banner…).
- **Sem o gerador**, a capa é desenhada com emojis e paleta do tema (Edge sem janela) e, se até isso falhar, um
  gradiente do Notion. A capa sobe pela File Upload API oficial.

## Gravar ao assistir

- Captura o som que sai do PC pelo loopback WASAPI do Windows (biblioteca `soundcard`, BSD). Não baixa o vídeo,
  não lê o player e funciona com qualquer site ou app: YouTube, plataformas de curso, Telegram.
- Grava WAV 16 kHz mono (≈ 115 MB por hora) na pasta `work/uploads` dos dados do app. O arquivo é apagado assim
  que a transcrição termina (a retomada usa a transcrição salva), e gravações esquecidas somem ao abrir o app
  depois de 7 dias. Uma gravação sem som ou com menos de 3 s é descartada com aviso. A gravação para se o
  disco ficar quase cheio.
- Limites: leva o tempo real da aula; sons do sistema (notificações) também entram; com o PC no mudo alguns drivers
  entregam silêncio; os marcadores de tempo seguem a gravação, não o vídeo.
- Use para estudo pessoal, respeitando os termos da plataforma de onde a aula vem.

## Assistir a tela junto (10/10/2026; `lumen/vision.py`, `bench/vision_bench.py`)

- **Modelo de visão:** `qwen3.5:4b` no Ollama (Apache 2.0, ≈ 3,3 GB, 3,1 GB de VRAM com `num_ctx` 4096). Teste com
  18 telas sintéticas com gabarito (slides, tabela, código, diagrama, gráfico, fórmula, quadro escrito à mão, texto
  pequeno dentro do player, professor com câmera, YouTube com recomendações e notificação, anúncio, editor e
  anotações do aluno): 100% do texto lido, 18/18 decisões certas de guardar ou descartar, nenhum texto de
  recomendação/notificação copiado, 1,5 s por tela na RTX 3060. Perderam: `qwen3-vl:4b` (o padrão “pensa” antes:
  32 s por tela), `qwen3-vl:4b-instruct` (99,1%, 2,9 s, 4,2 GB de VRAM e o Ollama 0.40 guarda uma 2ª cópia
  convertida no disco: 6,4 GB). Saída em JSON Schema; a ordem dos campos importa (com o tipo primeiro, quase tudo
  virava “pessoa”). Em código, o pedido manda manter a indentação (sem isso o modelo a tirava).
- **Captura da tela:** GDI (`BitBlt` do monitor da janela em foco) via `ctypes`, sem dependência nova. Pega vídeo
  tocando no navegador (testado no Edge); conteúdo com DRM sai preto. 1 captura por segundo, miniatura 96×54 em
  cinza: tela nova = parada ≥ 1,5 s e diferente das já guardadas (≥ 1% das células). As células que mudam quase
  sempre (câmera do professor, vídeo) saem da comparação, com histerese (uma troca de slide não as marca). Um slide
  ganhando tópicos (< 5% de mudança) guarda o estado mais recente a cada 20 s ou ao trocar de slide.
- **Qual janela:** a mudança é localizada na janela onde aconteceu (voto de até 25 pontos com `WindowFromPoint`).
  A imagem guardada vem da **própria janela** (`PrintWindow` com `PW_RENDERFULLCONTENT`, o Windows desenha a janela,
  inclusive o vídeo da GPU; 28 ms), não da cópia da tela: avisos, conversas e outros programas por cima ficam de
  fora. Testado com uma janela “PRIVADO” por cima do vídeo durante toda a aula: nenhuma imagem a trouxe. Se um
  programa não se deixar desenhar assim (sai preto), a tela não é guardada: recortar a cópia da tela e cobrir o que
  estava por cima dependeria das janelas de um instante depois da cópia (uma conversa que fechasse nesse meio
  ficaria na imagem). Nunca vai a tela inteira; janela pequena (aviso, menu) não é guardada. O modelo recebe
  “título — programa.exe”. Programas do aluno
  (editores, anotações, Office, e-mail, WhatsApp, terminal, Explorer) nunca são lidos: no teste, o modelo aceitou o
  VS Code do aluno como “aula” mesmo sabendo a janela, por isso a lista fixa. Testado na tela real: as 4 telas de
  aula vieram da janela do vídeo e o professor falando foi descartado. Uma trava na “janela da aula” foi
  descartada: se a primeira tela lida fosse de outra janela, todo o resto se perdia.
- **Área do conteúdo:** pedir ao modelo a região do slide funcionou nas telas sintéticas (IoU 0,94), mas na
  captura real cortava o título dos slides; foi retirada. A imagem só perde faixas pretas uniformes das bordas.
- **Quando lê:** na gravação, entre um slide e outro (fila; pausa se outra aula estiver sendo processada); o que
  faltar é lido ao processar. Num arquivo, depois da transcrição, só nos quadros-chave (o x264 os põe nas trocas de
  cena; o tempo pode atrasar até o próximo quadro-chave). Telas parecidas com uma de “pessoa falando” já lida não
  são relidas.
- **Na IA de texto:** as telas entram intercaladas na transcrição como linhas “(na tela)”, no tempo em que
  apareceram. Na aula de teste, a fala dizia “kick sort” (erro do Whisper) e a página saiu com “quicksort” e com as
  complexidades O(n²) e O(n log n) que só estavam na tabela do slide.
- **Na página:** galeria em `column_list` de 2 colunas (dois níveis de aninhamento, o limite da API), imagens pela
  File Upload API em 3 envios paralelos (com novas tentativas), e o texto em toggles (código em `code`, tabela em
  `table`). Os envios são divididos pelos três limites do Notion por pedido: 100 blocos no nível de cima, 1000 no
  total (contando os internos) e 500 KB. 20 telas com 80 linhas (1674 blocos) foram em 2 pedidos no Notion real.
- **Telas repetidas:** comparadas linha a linha, em ordem e com todos os símbolos (“x > 0” e “x < 0”, “x²” e
  “x2” ficam as duas; Unicode em NFC, não NFKC, que troca “²” por “2”); um slide que ganha tópicos vira um só apenas quando todas as linhas do anterior continuam no seguinte.
- **Ciclo de vida:** a captura da tela para junto com o som em qualquer saída (parar, falha do áudio, disco cheio,
  sair do app); uma gravação nova nunca deixa a anterior capturando. Parar espera a captura até 5 s e fecha a
  pasta das telas: uma captura presa (programa travado ao ser desenhado) ou uma leitura em andamento que terminem
  depois não gravam mais nada nem recriam a pasta descartada.
- **Tempo (aula de teste de 91 s, 6 telas, RTX 3060):** transcrição 18 s + leitura da tela 10 s; escrita e envio 42 s.
- **Pares de gráficos (`valores`, no fim do esquema):** o texto solto de um gráfico de barras (“5.200 ms / Bubble
  sort / 180 ms / Merge sort”) não diz de quem é cada valor, e a IA de texto o leu como Bubble = 180. Pedir no texto
  “rótulo: valor na mesma linha” não foi seguido; um campo próprio foi (os 3 pares certos). No começo do esquema ele
  esvaziava o texto do slide; no fim, não. A/B na mesma sessão: mesma velocidade por token, ≈ 8 tokens (0,1 s) a
  mais por tela comum e ≈ 1,4 s nas telas de gráfico; texto lido 100% e 18/18 guardadas certo.

## Gráficos da aula (10/10/2026; `lumen/charts.py`)

- **Precisão antes de quantidade.** A IA (o mesmo modelo de texto, `qwen3:8b`, temperatura 0) recebe só os trechos
  com números, datas ou fórmulas e propõe até 3 gráficos em JSON. Tudo é conferido no código:
  - cada valor precisa aparecer **junto do seu rótulo**: no mesmo trecho da fala (com o seguinte) ou na mesma linha
    da tela. Linhas vizinhas não valem: com elas, o par trocado da IA (Bubble = 180) passava. De quem é o valor
    segue o jeito da frase: começando por valor (“78% de nitrogênio, 21% de oxigênio”), é do rótulo seguinte;
    começando por rótulo (“o bubble sort levou 5.200 e o merge sort, 180”; “Quicksort | 150”), do anterior. Os
    rótulos são comparados pelas palavras que só eles têm (“merge”, não “sort”);
  - com várias séries, cada valor precisa ser também da sua coluna (revisão do Codex: “Alpha 2024 10 2025 20” com
    2024 = 20 passava): ou os nomes das séries estão no trecho, cada valor com o seu pela mesma regra, ou é uma
    linha de tabela na tela com os valores na ordem de um cabeçalho que lista as séries nessa ordem. Na fala sem
    os nomes das séries, o gráfico é recusado. E o mesmo número precisa ser da linha e da coluna: “Alpha 2024 10
    2025 20; Beta 2024 20 2025 10” não deixa o Alpha usar os números do Beta (2ª revisão);
  - números lidos como a aula escreve (“5.200” = 5200 em português, 5,2 em inglês; “1 milhão”; “cinco”); arredondar
    (10,7 → 11), inventar um ponto, uma série ou porcentagens que não fecham 100% derruba o gráfico inteiro;
  - a frase da IA sob o título saiu errada no teste (“o merge sort é o mais rápido”); ela só entra se 75% das
    palavras estiverem num mesmo trecho da aula. Senão, o subtítulo é tirado dos dados;
  - fórmulas: parser com lista fechada (números, x/n/t, + − × ÷ ^, !, log, sqrt, sen…; nada de nomes, atributos ou
    chamadas), calculadas com numpy. A da IA precisa ser **a mesma função** de uma fórmula da aula (O(…), o lado
    direito de cada “=”, a linha da tela; “igual a”, “ao quadrado”, “mais” falados viram símbolos), comparada
    pelos valores em 12 pontos de prova, não pelo texto: comparar o texto sem parênteses aceitava “x+1^2” por
    “(x+1)^2” (revisão do Codex). “3 - 4x + x²” vale por “x² − 4x + 3”. Os pontos incluem todo o trecho
    desenhado: só os fixos aceitavam “8-x” por “abs(x-8)” em [-10, 10] e recusavam “sqrt(x-10)” em [10, 20]
    (2ª revisão). E a IA só aponta qual: o que se desenha e se mostra é a fórmula escrita na aula, nunca a da IA.
- **Complexidades sem IA:** a IA desenhava uma curva por algoritmo e não comparava; as notações O(…) citadas viram
  um gráfico só, com as curvas calculadas e em ordem de crescimento (log n, n, n log n, n²), n de 1 a 32. Uma curva
  que dispara (2ⁿ perto de n²) sai pelo alto em vez de achatar as outras.
- **Teste com a IA real** (aulas curtas de 7 matérias): história → linha do tempo; ciências → rosca 78/21/1;
  matemática → parábola; economia → inflação ano a ano; algoritmos → barras 5.200/180/150 ms e as 4 complexidades;
  filosofia e um número solto → nenhum gráfico (sem chamar a IA no primeiro). ≈ 3–10 s por aula.
- **Desenho:** HTML/SVG no Edge headless (o mesmo do mapa mental); os 30 quadros da animação (1,2 s, depois 8 s
  parado) saem num só print de 6000×4050 em grade, recortados e juntados em GIF pelo FFmpeg do PyAV (palettegen +
  paletteuse, só a parte que muda em cada quadro): 40–160 KB, ≈ 2 s por gráfico, vários em paralelo. GIF porque o
  Notion anima sem clique; vídeo pediria play. Sem Edge ou se o envio falhar, entram o título e a tabela.
- **Notion real:** os GIFs foram aceitos pela File Upload API e voltaram iguais (GIF89a, 30 quadros); página de
  teste apagada em seguida.
- **Nunca impede a página:** falha da IA nos gráficos só deixa a página sem eles (fica no log), e não é guardada
  (“Tentar novamente” procura de novo). Os gráficos conferidos ficam em `lesson.json`: atualizar a página não pergunta
  de novo.
- **Toda página tem gráfico (11/10/2026):** pedido do usuário. Para não inventar dados, o gráfico de uma aula sem
  números vem da estrutura da própria aula (`charts.structure`, sem IA): o tempo de cada tópico (do início de um ao
  do seguinte, pelos tempos que a IA deu e que a validação já confere contra a duração) ou, sem tempos, quantas vezes
  cada termo do glossário foi dito. Entra por último, só se sobrar vaga entre os 3; se a IA dos gráficos falhar, ele
  entra sozinho (e nada é guardado). O rodapé do desenho diz “Calculado pelo Lumen a partir da aula”.

## Tempo restante (11/10/2026; `lumen/eta.py`)

- **Por etapa, com a velocidade deste PC:** a IA pelo que o Ollama mede em cada resposta (tokens lidos e escritos
  por segundo, carga do modelo) × o tamanho do pedido e o tamanho típico de cada resposta (página, notas de uma aula
  longa, gráficos); transcrição e telas por segundo de áudio/vídeo; mapa mental, gráficos, envio das telas e pedidos
  ao Notion cronometrados. Mediana das últimas 15 medidas (uma aula fora do comum não puxa a conta).
- **Durante a etapa:** tokens já escritos (a IA) e progresso (transcrição, telas) corrigem o que falta; passou da
  estimativa, ainda mostra um pouco (nunca “0 s” antes de terminar).
- **Medido (vídeo de 91 s, ponta a ponta no Notion real):** com os valores iniciais genéricos, a página levou 83 s e
  a estimativa errava até 21 s; depois de uma aula, 71 s e erro de no máximo 5 s. Com os valores iniciais medidos
  neste PC (RTX 3060, qwen3:8b), já na 1ª aula: página de 67 s com erro de até 6 s; transcrição + telas de 44 s com
  erro de até 7 s. Aula longa (48 mil caracteres, lida em 3 partes, 208 s): erro de −51 a +24 s; o tamanho de cada
  resposta da IA varia de uma vez para outra, e é isso que sobra de erro.
- **Tamanho da resposta cresce com o pedido:** página ≈ 1.300 + 0,25 × tokens do pedido (aula curta ≈ 1.700, longa
  ≈ 3.400); o que se aprende é a correção deste PC sobre essa forma.
- **Teto em cada resposta da IA (`llm.MAX_OUT`, ~3× o normal):** medindo a aula longa, as notas de uma parte
  passaram de 9 min: a IA repetia texto até encher o contexto e o Ollama seguia gerando. Com o teto, uma parte
  leva no máximo ≈ 50 s, e as notas juntas sempre cabem numa leitura.
- **Resposta cortada no teto (2ª revisão do Codex):** o Ollama avisa (`done_reason: length`); antes, as notas
  cortadas entravam como completas. Agora a parte é relida em dois pedaços, no máximo 2 vezes na aula toda
  (`llm.MAX_SPLITS`): sem esse limite, uma aula em que todas as partes cortam levou 27 min em vez de 3,5 (7× mais
  chamadas). O que ainda cortar segue como veio e a página mostra em “Pontos de atenção” quais partes ficaram
  incompletas. Aula longa de teste, toda densa: 10 min com o limite (pior caso); aulas normais não cortam.
- **Previsão das chamadas** (`llm.calls`) usa o corte real em partes (por linha) em todas as rodadas de resumo, e
  o tempo restante também chega ao widget (`eta_total` na lista de campos de `/api/widget`).

## YouTube: limitação real

- `captions.download` (YouTube Data API v3) exige OAuth **e permissão para editar o vídeo**. Para vídeos de
  terceiros, a resposta é 403. Não há API oficial que entregue a transcrição de vídeos alheios.
- Por isso o Lumen **não** baixa vídeo nem raspa o player. Ele usa o oEmbed público oficial (título e canal) e
  pede a transcrição ao usuário: colar o texto do painel “Mostrar transcrição” (com marcadores de tempo), importar
  `.srt`/`.vtt`/`.txt`, ou escolher uma cópia local autorizada.
- Para vídeos **próprios** seria possível usar `captions.download` com OAuth. Isso não foi implementado porque
  exigiria que cada usuário criasse um projeto no Google Cloud. A importação de `.srt` exportado do YouTube Studio
  cobre esse caso.
- Não há extensão de navegador. Ela só serviria de atalho, e qualquer leitura da transcrição dentro da página seria
  justamente a automação frágil do player que o projeto evita.

## Player do YouTube na página

- O link opcional de uma gravação ou arquivo também pode ser editado durante a revisão. Na retomada, vale
  o link atual, mesmo que o áudio temporário já tenha sido apagado.
- Links do YouTube são validados e normalizados para `https://www.youtube.com/watch?v=ID`. A API oficial do
  Notion aceita esse endereço em um bloco `video` externo, com legenda, sem download nem HTML personalizado.
- O player fica após os metadados, em “Assistir à aula”, separado do sumário e do resumo por um divisor.
  A atualização e o cancelamento usam os mesmos IDs dos blocos para incluir/remover o player com o material.
- Uma gravação pode começar no meio de um vídeo: o link opcional não converte seus tempos em timestamps
  do YouTube. Os links de tempo continuam restritos à fonte YouTube.
- Privacidade, disponibilidade e permissão de incorporação são controladas pelo YouTube e pelo Notion.

## Telegram: limitação real

- Bot API: o bot só acessa mídias enviadas a ele, e o `getFile` baixa no máximo 20 MB, pequeno demais para aulas.
- API de cliente (MTProto, ex. Telethon): exige `api_id`/`api_hash` próprios (my.telegram.org) e login com o
  telefone, o que dá acesso a **todas** as conversas da conta. Não existe escopo mínimo.
- Por isso a fonte Telegram é **importação manual** do arquivo salvo pelo Telegram Desktop. O app explica isso
  e não promete acesso a chats, canais ou grupos.

## Gerar amostras de teste (autorizadas)

Voz sintética do Windows (PowerShell, `System.Speech`, voz “Maria” pt-BR) gravando `aula.wav`. Depois:

```
ffmpeg -f lavfi -i color=c=0x1d3557:s=640x360:r=25 -i aula.wav -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac aula.mp4
ffmpeg -f lavfi -i color=c=0x1d3557:s=640x360:r=25 -i aula.wav -shortest -c:v libvpx-vp9 -b:v 200k -c:a libopus aula.webm
ffmpeg -i aula.mp4 -c copy aula.mkv && ffmpeg -i aula.mp4 -c copy aula.mov
ffmpeg -i aula.wav -c:a libmp3lame aula.mp3 && ffmpeg -i aula.wav -c:a aac aula.m4a
ffmpeg -f lavfi -i color=c=red:s=320x240:r=10 -t 3 -c:v libx264 -pix_fmt yuv420p sem_audio.mp4
echo "isto nao e um video" > falso.mp4
```

## Assistir a tela junto: captura que falha tenta de novo (11/10/2026)

- **Defeito:** quando a imagem da janela não podia ser guardada num instante (`window_image` recusou, janela de um
  programa seu por cima…), a tela já tinha sido marcada como “vista”. Numa página quase parada (vídeo de aula), nada
  mudava o bastante para ser uma tela nova e nenhuma outra captura acontecia: uma gravação de 9 min 48 s guardou
  só 1 tela. Veio da correção de privacidade que deixou de recortar a cópia da tela (a captura passou a poder falhar).
- **Correção:** `Picker.feed` desfaz o “visto” quando a imagem falha, e a mesma tela é tentada de novo no instante
  parado seguinte (custo: uma tentativa por segundo, ≈ 15 ms). Durante a gravação, o app mostra o motivo se ainda não
  houve nenhuma captura (“não achei a janela da aula”, “programa seu”, “janela pequena”, “o programa não deixou o
  Lumen desenhar a janela”).
- **Medido:** `PrintWindow` desenha o Opera GX (perfil e página de teste isolados) com texto e com vídeo tocando,
  10/10 capturas, ≈ 16 ms. Vídeo de aula de teste por arquivo: 5 telas lidas e na página.
- **A causa principal (gravação seguinte, 5 min, nenhuma tela):** a área que muda sempre (câmera, vídeo) sai da
  comparação e só volta depois de ~28 s parada (`LIVE_OFF`, para a câmera do professor num canto não piscar).
  Num vídeo do YouTube o vídeo é quase a tela toda: com a pessoa falando ele vira “vivo” e, quando corta para um
  slide de 10–20 s, o slide nunca é guardado. Simulação (fala, slides de 15, 12 e 35 s): antes, só o último, 19 s
  depois de aparecer; agora os três, 1 s depois. Correção: quando a tela inteira para (no máximo 0,2% das células
  mudando por `STILL_S`), nada mais está vivo. Câmera num canto e pessoa falando continuam iguais (testes).
- **Erro numa tela não para mais a captura:** antes, qualquer erro que não fosse `OSError` encerrava a thread em
  silêncio pelo resto da gravação; agora fica no log (só o tipo, sem texto da tela) e a tela é tentada de novo.
- **Programa seu não vota na janela da aula (gravação seguinte, 2 min, 1 tela):** a janela fotografada é a que
  tem mais pontos da mudança (na primeira tela, mais pontos do monitor). Um programa seu (VS Code, Notion…) maior
  que o vídeo, ou com o que você escreveu nele diferente da última tela guardada, ganhava em toda tela nova; a tela
  era recusada por privacidade e tentada de novo para sempre. Teste ao vivo (Opera GX de teste, 1300×820, vídeo de
  demonstração com câmera redonda e mouse, VS Code maximizado atrás): antes 0 de 7 telas, 77 recusas; agora 7 de 7,
  todas da janela de teste, lidas como aula. Agora vence a janela que não é programa seu e tem ≥ 10% dos pontos
  (amostra de até 100); sem nenhuma, continua recusada (o programa seu nunca é fotografado). Ao parar, o log
  registra quantas telas e as recusas por motivo (só os motivos, nada da tela).
## Assistir a tela junto: validação ponta a ponta (11/10/2026)

- **Defeito principal (gravação real de 8 min 43 s: 0 telas, 0 recusas):** a área do vídeo que se mexe sai da
  comparação e só voltava quando a **tela inteira** parava. Num vídeo editado (YouTube), a câmera redonda e a legenda
  animada nunca param: depois de uma fala, nenhum slide voltava a contar. Simulação (falas com a imagem toda se
  mexendo, 4 slides com câmera redonda e legenda): antes 1 de 4 (aos 67 s, slide de 57 s), agora 4 de 4 com ≤ 4 s.
  Correção (`Scenes.feed`): toda área “viva” parada por `STILL_S` com as 8 vizinhas também paradas volta à
  comparação, se somar ≥ `QUIET` (10%) da tela. A vizinhança evita que células soltas da legenda voltem e, ao mudar
  de novo, façam a tela parecer “ainda mudando”. A câmera num canto que para um instante é pequena e continua fora.
- **Lumen na frente:** com a janela principal do Lumen em primeiro plano (clicou em Gravar e não clicou no vídeo),
  `grab` devolvia None e nada era assistido, sem recusa e com a gravação dizendo “Assistindo a tela junto”. Agora
  a área do Lumen sai preta na cópia de comparação e o resto da tela segue. Limite: uma janela “sempre por cima”
  (vídeo em picture-in-picture) sobre a área do Lumen fica fora da comparação enquanto o Lumen estiver na frente.
- **Falhas visíveis:** sem acesso à tela ou cópia que falha viram recusas com motivo (antes: silêncio). As recusas por
  motivo ficam no `index.json` das telas; a revisão diz “Nenhuma tela foi guardada durante a gravação (motivo)” em vez
  de “nenhuma tela com conteúdo da aula”. Log: cópias da tela, telas guardadas e recusas ao parar; telas guardadas e
  para a página ao processar; blocos e telas (no texto da IA, na página, sem imagem) ao publicar. Nada da tela.
- **Nova aula depois de uma gravação:** a gravação é apagada ao gerar a página; “Nova aula” conferia de novo o
  arquivo apagado e mostrava “Arquivo não encontrado”. Agora a gravação deixa de ser a fonte ao gerar a página.
- **Validação real pelo Lumen.exe** (interface via CDP do WebView2, sem mouse/teclado; Opera GX de teste em perfil
  isolado tocando aulas de teste com voz Maria, câmera redonda e legenda animada; Notion real, destino “Sem curso”):
  aula 1: 4 de 4 slides guardados ao aparecer e lidos durante a gravação; “Exemplo visual: 7 × 8 = 56” (só na
  tela, nunca falado) chegou ao material da IA (tópico, exemplo, resposta) e à seção “O que apareceu na tela”, lido
  de volta pela API e pelo conector do Notion. Aula 2: 3 de 3 slides; a equação só da tela chegou à página; nenhuma
  aula tem conteúdo da outra; os blocos anteriores da página continuam, na mesma ordem.

## Limitações conhecidas

- O áudio inteiro é decodificado em memória: ≈ 230 MB por hora de aula (o dobro em 2× desacelerado).
- Precisão real em **aulas suas** ainda não foi medida: o benchmark usa FLEURS/CORAA e misturas sintéticas.
  Para medir, veja "Usar suas próprias aulas" em bench/README.md.
- Não há amostra **real** de aula gravada em 2× ou 4×; ambos foram testados com fala real acelerada artificialmente
  (atempo). Players e editores podem acelerar com outros algoritmos.
- As medições de hardware valem para este PC (i5-11400F, RTX 3060 12 GB). Em outra máquina, a reserva de núcleos e
  os limites de VRAM são estimativas.
- O Parakeet foi treinado com português europeu; nos testes com pt-BR foi bem, mas pode grafar palavras à europeia.
- Cancelar durante a decodificação inicial do áudio só tem efeito quando ela termina (segundos a ~1 min).
- Uma tarefa por vez. Fechar a janela cancela a tarefa em andamento; o que já foi feito fica guardado para retomar.
- Não foi testado em macOS/Linux nem em GPUs AMD/Intel (nesses casos o app usa a CPU).
- Publicar num workspace real do Notion depende do seu token: os testes automáticos usam um Notion simulado.
- Assistir a tela junto: DRM aparece preto; com vários monitores, só o da janela em uso; tempo das telas de um
  arquivo limitado aos quadros-chave; aulas reais (não sintéticas) ainda não foram medidas com gabarito.
