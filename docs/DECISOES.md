# Decisões e limitações

Pesquisado em outubro de 2026, nas documentações oficiais citadas.

## Arquitetura

Um único processo Python:

```
lumen/
  __main__.py    inicia o servidor e abre a janela; encerra quando a janela fecha
  server.py      HTTP só em 127.0.0.1 (stdlib): interface + API JSON
  jobs.py        uma tarefa por vez: preparar → transcrever → (nota do estudante) → analisar → gerar → publicar
  understanding.py  “Minha compreensão”: a nota do estudante, os estados e a trava de toda IA sobre a aula
  sources.py     arquivo local, link do YouTube, legendas/transcrições importadas
  transcribe.py  faster-whisper (CPU ou GPU NVIDIA)
  llm.py         Ollama: prompt, JSON Schema, validação, leitura por partes, crítica (Profundo) e conexões
  package.py     StudyPackage: a aula processada uma vez, canônica para todos os destinos (+ validador)
  notion.py      destino Notion: API REST do Notion (stdlib urllib) e montagem dos blocos
  obsidian.py    destino Obsidian: nota (renderer + writer sem destruir o que é do usuário), revisões, painel
  canvas.py      mapa mental como JSON Canvas: layout determinístico, merge com o que o usuário moveu
  vault.py       cofres do Obsidian: descoberta, estrutura (pelo type das notas) e busca de conexões
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
- **Visual**: escuro, com um design system próprio (`lumen/web/ui.css`, regras em `docs/DESIGN.md`) compartilhado
  pelas três janelas: tokens de cor, tipo, espaço, raio, vidro, sombra e movimento, ícones num sprite próprio
  (`icons.svg`). Os botões de janela continuam no estilo Mac, em grafite. A fonte é a Inter (OFL,
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
- Destino em páginas, não em banco de dados: a aula entra como blocos no corpo da página escolhida; a única
  subpágina é “Minha compreensão”, logo abaixo da aula. A criação explícita de cursos e módulos continua disponível.
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

## Sensor de “Assistir a tela junto” na barra flutuante (11/10/2026)

- O chip lê `recording.screens` (só existe com a captura rodando) e `watch` (opção ligada, enviado por `/api/widget`),
  então “Vendo a tela” nunca aparece por a opção estar apenas ligada. Cor própria (ciano) para não se confundir com
  o vermelho da gravação; âmbar quando o modo está ligado e nada é visto. Fica no rodapé do painel, que já tinha
  espaço nos quatro lados, sem mudar o tamanho da janela da barra; recolhida, um ponto na alça.

## Capturas de tela enviadas pelo usuário (11/10/2026)

- **Fonte `captures`** (`sources.captures`): até 30 imagens; a chave da aula é o conteúdo das imagens (e a ordem), então
  a mesma coleção é reconhecida como duplicada. Reaproveita todo o caminho das telas capturadas: viram a pasta `screens`
  da aula (JPEG de até 1280 px, como as da gravação), são lidas por `vision.analyze` e entram em `select`, na revisão,
  nos gráficos e na galeria. Não há fala: a “transcrição” tem um trecho por captura (“Captura 1: título”, sem horário,
  como um texto colado do YouTube sem tempos) e o texto delas vai para a IA pelo mesmo `(na tela)` de sempre.
- **Leitura própria** (`SYSTEM_CAPTURE`, `clean(manual=True)`): o prompt das telas de aula manda ignorar menus, abas,
  endereço e “telas que não são da aula”, e descarta rosto/anúncio. Numa captura escolhida pelo usuário isso apagaria
  justamente o site ou o texto que ele quis guardar. Por isso: transcreve o conteúdo (só tira a moldura do programa) e
  fica sempre que houver texto ou figura descrita.
- **Adicionar na revisão** (`jobs.add_captures`, `POST /api/captures/add`): lê na hora (≈ 2–6 s cada, até 12 por vez) em
  vez de virar uma tarefa, para não trocar o estado da revisão que a interface guarda; recusa se houver outra tarefa. Entram
  com `manual: true` e tempo depois do fim da aula (só para ordenar), sem horário e sem link de tempo na página.
- **Página:** só capturas suas → seção “📸 Capturas de tela”; misturadas com telas da aula → “🖥️ O que apareceu na tela”,
  com horário só nas telas da aula.
- **Topo da página (a pedido do usuário, 11/10/2026):** só a ficha da aula (🎓). Saíram a coluna “Nesta aula” (contagem
  de tópicos, perguntas, termos e gráficos) e o checklist de estudo; o resto da página não mudou.
- **Arquivos:** as imagens escolhidas no diálogo são copiadas para `work/uploads` (as originais não são tocadas); a
  miniatura da aba só serve arquivos dessa pasta. Cópias são apagadas ao gerar a página (adicionadas na revisão: logo
  depois da leitura) e, se esquecidas, em 7 dias.

## Barra flutuante que se recupera sozinha (17/10/2026; `launcher/WidgetForm.cs`, `launcher/Lumen.cs`)

- **Defeito:** a barra é uma página dentro do WebView2. Se o processo de renderização morria ou travava, ficava só a
  faixa de 12 px, sem alça nem painel, até reiniciar o Lumen: nada tratava `ProcessFailed`. Reproduzido derrubando o
  renderizador do WebView2 do Lumen: a barra não voltava (nenhum processo novo em 25 s). Não havia queda registrada no
  Windows nem suspensão/reset de vídeo no período da reclamação; o `Lumen.exe` já aberto desde o login não tinha
  nenhuma proteção, e um reinício resolvia.
- **Correção:** `ProcessFailed` recarrega a página (e recria o controle se o navegador inteiro caiu); um batimento a
  cada 15 s roda um script na página e, se não responder em 8 s ou voltar vazio, recarrega (na 2ª falha seguida,
  recria o controle). A janela principal também recarrega se o renderizador cair.
- **Medido:** renderizador derrubado → barra de volta em ~1 s (antes: nunca); renderizador congelado → detectado e
  trocado em ~38 s. Testes nativos do projeto (`tests\DesktopChecks.cs`) continuam passando.
- **Limite:** se a causa da reclamação foi outra (por exemplo, um jogo em tela cheia cobrindo a barra), isto não muda.

## Minha compreensão antes de qualquer IA (20/10/2026; `lumen/understanding.py`)

- **Pedido do usuário:** o Lumen deixa de pensar pelo estudante. Fluxo obrigatório: conteúdo → compreensão escrita
  por ele → a IA analisa essa compreensão → Notion. Nenhum resumo, anotação ou página antes da nota.
- **Uma regra, num lugar só.** `understanding.py` guarda a nota e decide: `check` (a nota vale?), `require` (há nota
  enviada; para salvar, também a análise), `reveal` (transcrição, telas e revisão só depois da nota) e `guard` (o
  que a interface recebe de uma tarefa). Quem gera material chama a trava: `llm.generate` e `llm.analyze` recusam
  sem nota válida (mesmo chamadas diretamente), `jobs.finish` sem nota analisada, `jobs.review`, `jobs.add_captures`
  e `/api/screen` sem nota enviada. Toda fonte passa por `jobs.process` → nota → `jobs.analyze` → `jobs.finish`;
  uma fonte nova herda a regra sem código próprio.
- **O que é uma nota válida:** ≥ 20 palavras de 2+ letras, ≥ 12 diferentes e ≥ 80% com vogal (barra “teste teste…”
  e teclas ao acaso, aceita texto imperfeito). A interface usa os mesmos números só para liberar o botão.
- **A preparação continua técnica:** transcrição e leitura das telas (sem IA de texto) rodam antes, em segundo
  plano; o editor abre assim que a aula tem nome. A tarefa entregue à interface vem sem `segments` e `screens`
  até a nota ser enviada (os dados ficam no disco para a IA).
- **Nota original × atual:** `original_understanding` é o que o estudante escreveu antes de a IA interferir: muda
  só enquanto nenhuma análise existe e congela na 1ª. Edições depois vão para `current_understanding`, que pode ser
  analisada de novo. Estudar de novo uma aula já salva começa uma nota nova e guarda as anteriores em `earlier`.
- **Guardar sem perder:** um JSON por aula em `DATA/understanding`, gravado com `os.replace` (atômico). A interface
  salva no `localStorage` a cada tecla, no Lumen 0,6 s depois (pedidos fora de ordem são ignorados pelo horário
  `at`) e por `sendBeacon` ao fechar ou esconder a janela; ao reabrir, o texto mais novo vence.
- **Análise (`llm.ANALYSIS`):** JSON Schema com confusões (trecho = as palavras do estudante; correção = o que a
  aula diz), acertos, parciais, lacunas, complementos, conexões e perguntas; listas curtas (até 5) para não virar
  relatório. Recebe a aula (transcrição + telas) e a nota no mesmo pedido; a nota nunca é reescrita. A página da aula
  também recebe a nota, com a regra de complementar o que o estudante não mencionou ou confundiu.
- **Notion:** a página da aula continua indo para o corpo da página escolhida; a subpágina “Minha compreensão” é
  criada por último, então fica logo abaixo daquela aula (a API acrescenta a subpágina no fim da página). Nota em
  bloco de citação, divisor, aviso “análise da IA local” e as seções da IA. O id dela entra nos blocos da aula:
  falha no envio, “Atualizar material” e “Refazer página” a removem junto. Limite: várias aulas na mesma página
  geram várias subpáginas com o mesmo nome, cada uma logo abaixo da sua aula.
- **Limite:** numa aula longa (> 40 mil caracteres), a leitura por partes acontece na análise e de novo na página
  (≈ 1 min a mais por parte).
- **Teste real** (aula sintética de 98 s sobre fotossíntese, voz do Windows; Whisper large-v3-turbo + qwen3:8b na
  RTX 3060; Notion simulado): preparação 8 s; análise 50 s com o modelo frio, 10–12 s quente; página + subpágina
  74 s. Nota com 3 erros de conceito (glicose “na fase clara”, oxigênio “do gás carbônico”, fase escura “só à
  noite”): com `confusoes` no fim do esquema, a 1ª ia sempre para “parciais” (3 de 3 rodadas); com `confusoes`
  primeiro e a regra “meio certa, meio errada também entra”, os 3 erros saíram em confusões nas 3 rodadas. Nota
  incompleta: as lacunas foram cloroplastos, clorofila, as duas fases, a quebra da água e a glicose. Resta, às
  vezes, um item de “parciais” que atribui ao estudante algo que ele não escreveu (limite do modelo de 8B).
- **Interface** (Edge sem janela via CDP, com o mesmo Whisper e Ollama): o editor abre 1 s depois de “Continuar”,
  com a preparação em segundo plano; a nota curta fica bloqueada e o servidor recusa o envio direto; a janela
  recarregada antes do autosave e sem sendBeacon recupera o texto do PC; claro, escuro e janela estreita conferidos.

## “Minha compreensão” destacada e na barra lateral (20/10/2026; `web/understanding-editor.js`, `launcher/NoteForm.cs`)

- **Pedido do usuário:** escrever a compreensão enquanto revê o vídeo, sem alternar telas, na janela principal e na
  barra lateral. O vídeo toca em outro programa (navegador, curso), então um painel só dentro da janela do Lumen não
  ficaria por cima dele: o modo flutuante é uma janela nativa sempre por cima (`NoteForm`), com a moldura do sistema
  sem a barra de título (bordas de redimensionar, sombra e cantos do Windows, como a janela principal). No navegador
  comum (sem o Lumen.exe), é um popup.
- **Um documento só:** `understanding-editor.js` tem o estado da nota por aula (`Notes`) e o campo (`UnderstandingEditor`,
  modos normal, lateral e flutuante; o modo só muda o visual). Os três editores usam o mesmo componente; o autosave
  que estava em `app.js` foi para ele. Cada tecla vai na hora para as outras janelas (`BroadcastChannel`, as três
  páginas são do mesmo endereço e do mesmo perfil do WebView2) e ao Lumen 0,6 s depois. Quem recebe o texto salva
  em 2,5 s se a janela onde se digitou fechar antes (o servidor ordena pelo horário `at`, salvar duas vezes não
  estraga nada). Sem o canal, cada janela confere o Lumen ao ganhar foco e a cada 3 s.
- **Sem perder texto ao trocar de modo:** destacar salva antes de abrir; fechar, voltar e minimizar salvam antes de
  agir; fechar só esconde a janela (a página vai para `about:blank`, o que dispara o envio do que faltar); ao sair
  do Lumen, as três janelas mandam o que falta (`Notes.flushAll`, `fetch` com `keepalive`).
- **Porta fixa:** o `localStorage` (cópia do rascunho neste PC, preferências da nota, páginas recentes) é guardado por
  endereço, e o Lumen.exe escolhia uma porta nova a cada abertura: a cópia do rascunho não sobrevivia a reabrir o app.
  Agora ele reusa a porta da última vez (`port.txt`) se estiver livre.
- **Janela flutuante:** padrão 400 × 500 no canto inferior direito (longe do centro, onde costuma ficar o player);
  mínimo 300 × 240, máximo 60% × 92% da área útil; sempre inteira dentro da tela (ao soltar depois de arrastar ou
  redimensionar, e ao abrir numa tela que não existe mais). Posição e tamanho em `understanding-panel.txt`; o último
  modo (destacada ou não) e a aula em `localStorage` (`understandingPanelMode`, `understandingPanelKey`; no popup
  também `understandingPanelPosition` e `understandingPanelSize`). Minimizar deixa só a barra (sem sumir da tela).
- **Barra lateral:** o ícone de lápis aparece quando há uma nota em escrita (a aula aberta na janela principal ou,
  sem ela, a mais recente); o painel cresce para 360 × 440 e não se recolhe enquanto se digita. Destacar dali
  recolhe a barra para não cobrir o vídeo.
- **IA:** as três interfaces só mostram a nota; análise, transcrição e telas continuam presas às regras de
  `understanding.py` (verificado no teste nativo: revisão e envio de nota curta recusados).
- **Atalho:** Ctrl+Shift+D (“destacar”); dentro do Lumen não conflita (no Chrome é “favoritar todas as abas”, o que
  não existe no WebView2). Trocável em `localStorage.understandingShortcut`.
- **Verificado** em `tests/DesktopChecks.cs` com as janelas reais (invisíveis) e dados isolados: escrever na principal
  → aparece na lateral; na lateral → principal; destacar; na flutuante → as outras duas; mover e esticar para fora da
  tela; mínimo; minimizar; fechar; reabrir no mesmo lugar; voltar; recarregar. 140 casos de geometria (telas com
  origem negativa, escalas de 100% a 200%, notebook 1366 × 728 e tela de 800 × 560).
- **Limite:** o teste não mostra um vídeo de verdade atrás da janela; “sempre por cima” é o `TopMost` do Windows.

## Filtro de música externa (20/10/2026; `lumen/music.py`, `lumen/loopback.py`, `bench/music_bench.py`)

- **Pedido do usuário:** estuda ouvindo música alta enquanto a aula toca; a música não pode contaminar transcrição,
  IA, “Minha compreensão” nem a página. Ajustes → **Filtrar música externa** (`music_filter`, desligado por padrão).
- **De onde vem o áudio (antes de mudar nada):** (1) arquivo local, cópia autorizada do YouTube e Telegram:
  `audio.load` decodifica a faixa de áudio do próprio arquivo (só o conteúdo estudado; a música só entra se estiver
  no arquivo); (2) “Gravar ao assistir”: loopback WASAPI do alto-falante padrão, ou seja, **todo o som do PC**,
  inclusive o Spotify. Não há microfone. YouTube com legenda colada e capturas de tela não têm áudio.
- **Desligado:** o caminho do áudio é o de antes (`record._open_recorder` e `jobs.process` só desviam com o filtro
  ligado; testado em `tests/test_music.py`), nenhum modelo é carregado e `transcript.json` não ganha campos.
- **Ligado, em ordem:**
  1. *Isolar a fonte* (gravação): se um app só de música está aberto (lista em `loopback.MUSIC_APPS`), a gravação
     usa o *process loopback* do Windows 10 2004+/11 (`ActivateAudioInterfaceAsync`,
     `PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE`) e o som dele não entra. A captura continua sendo a do
     `soundcard`; só a ativação do cliente de áudio é nova (ctypes). Verificado com a gravação real do Lumen e dois
     processos tocando tons: o “app de música” (1234 Hz) caiu de 0,0297 para 0,0 de amplitude e a “aula” (777 Hz)
     ficou em 0,0298 (0,0299 sem o filtro). Players que também tocam vídeo (VLC, Media Player) não entram na lista:
     a aula pode estar neles. Se o Windows recusar, grava todo o som, como sem o filtro.
  2. *Detectar* (`music.detect`): YAMNet (Google, AudioSet, Apache-2.0; ONNX de 16 MB, 750× o tempo real na CPU)
     dá a cada 0,48 s a confiança de fala (classes 0–3), canto/rap (24–32) e música (132–276). Música estável por
     ≈ 2 s acima de 0,3 marca o trecho. Sem música, ou com a fala clara na própria mistura (fala ≥ 0,3; música
     sozinha ficou abaixo de 0,12 em todas as faixas do MUSDB18), o áudio vai ao ASR como está e nada é separado.
  3. *Separar* (`music.separate`): nos trechos que sobraram, em blocos de até 1 min com 2 s de contexto, a voz é
     separada dos instrumentos por um MDX-Net (UVR) em ONNX, com STFT/iSTFT em numpy iguais às do UVR (sem PyTorch).
  4. *Validar a fala* (`music.decide`): a voz separada substitui o original só se a sonda tem certeza de que há fala
     (média ≥ 0,6 em ≈ 5 s) **e** a música domina a voz (acompanhamento ≥ 7 dB acima da voz separada,
     `music.dominance`), por ≥ 3 s seguidos. Fora disso fica o original; abaixo de 0,6 o trecho é marcado.
  5. *ASR e depois*: a transcrição de sempre recebe o WAV derivado (ou o próprio arquivo, se nada mudou);
     `music.mark` marca **música ao fundo** + incerto nos trechos de dúvida. Incerto chega à IA como “(?)”, que os
     pedidos mandam não tratar como fato; vale para “Minha compreensão”, página e gráficos. O texto nunca é trocado.
- **Por que uma sonda:** medido com as falas reais + MUSDB18: com a música a −5 dB da fala ou mais alta, o YAMNet
  dá fala ≈ 0 na mistura mesmo com o professor falando; na voz separada, canto e rap também parecem fala (0,3–0,9).
  A sonda é uma regressão logística (numpy, 2048 pesos em `lumen/music_probe.json`) sobre os embeddings do YAMNet da
  voz separada e da mistura, treinada com 40 falas (FLEURS/CORAA) misturadas a 100 faixas do MUSDB18 *train*
  (instrumental e com voz, −10 a +10 dB) contra as faixas sozinhas e 50 vozes a cappella. Teste com falas e faixas
  nunca vistas (MUSDB18 *test*): AUC 0,94. Testados e descartados: só a voz (AUC 0,89) e média/desvio em ±3
  quadros (AUC 0,91, apagava mais fala).
- **O que o benchmark mudou no desenho** (`bench/RESULTADOS_MUSICA.md`; transcrição de verdade, large-v3-turbo):
  - *1ª versão — voz separada em todo trecho com música:* piorava a letra. Numa música sozinha, o Whisper costuma
    não escrever nada (0 palavras em 7 de 11 faixas); com a voz isolada, sem os instrumentos, ele transcrevia a
    letra (0 → 18, 14 → 48; rap 1 → 31 palavras). Com a música a 0 dB, 0 → 14–21 palavras de letra; com a música
    baixa a voz separada não ajudava e às vezes piorava (0 → 3 erros).
  - *2ª — silenciar onde a sonda via só música:* apagou fala inteira sob piano e eletrônica que a sonda nunca viu
    (0/18 → 18/18 e 6/40 → 40/40 erros) para tirar pouca letra (52 → 40 palavras em 10 músicas sozinhas). Na
    dúvida, preservar a fala: o modo padrão **nunca silencia**.
  - *3ª — dominância ≥ 4 dB:* separava música com letra (o cantor entra na “voz”: 1 a 3,6 dB) e ilhas de 0,5–2 s
    de voz separada mudavam a decodificação inteira (num caso, de 2 para 42 palavras de letra). Daí 7 dB e ≥ 3 s.
  - *Final:* nenhum cenário piorou. Instrumental +5 / +10 / +15 dB: WER 75,7% → 48,9% / 69,4% → 52,3% / 100% →
    90,2%; palavras da fala perdidas 85 → 51 / 137 → 51 / 235 → 133. Fala sozinha, silêncio, ventilador, teclado,
    conversa ao fundo, música até 0 dB, música com letra, rap e fala 2×: idênticos a sem o filtro. Na aula real do
    app (`jobs.process`) com instrumental a +10 dB, sem o filtro o app respondia “Não foi detectada fala”; com o
    filtro, transcreveu (WER 77%) e marcou 6 trechos.
- **Modos** (`music.MODES`, prontos para uma escolha futura; a interface só liga e desliga e vale **balanceado**):
  conservador marca mais (keep 0,7); balanceado marca abaixo de 0,6; agressivo também silencia onde a sonda tem
  certeza de que só há música (abaixo de 0,3 por ≥ 2,5 s; no teste, 0% da fala e 29% da música sozinha), com o
  risco medido acima. O relatório de cada aula guarda `music_confidence`, `speech_confidence`,
  `separation_confidence` e `dominance_db`.
- **Separador escolhido** (CPU i5-11400F; SDR da voz estimada a partir de áudio 16 kHz, 4 faixas do MUSDB18):

  | Modelo | Tamanho | Velocidade (CPU) | SDR da voz | Observação |
  |---|---|---|---|---|
  | **UVR-MDX-NET 3 (9662)** | 28 MB | 8,8× o tempo real | 4,0–10,5 dB | escolhido |
  | Kim Vocal 2 (MDX-Net) | 63 MB | 3,0× | 4,0–11,5 dB | 0,3–1 dB melhor, 3× mais lento |
  | kuielab_a_vocals (MDX) | 28 MB | 8,7× | – | mesma família, mais antigo |
  | Open-Unmix UMX-L | 108 MB | – | – | SDR publicado menor que o MDX |
  | Demucs / htdemucs, BS/Mel-RoFormer | 80–700 MB | – | – | exigem PyTorch (≈ 2 GB) ou são lentos sem GPU |

  Mais threads (6 → 12) não aceleraram; o filtro usa metade dos núcleos lógicos para o PC continuar usável. Sem o
  “arena” do onnxruntime o pico do separador caiu de 1,2 GB para 0,65 GB, na mesma velocidade.
- **Custo:** sem música, só o detector (1 h ≈ 5 s). Pior caso (música com voz a aula toda, separada inteira):
  10 min em 156 s (3,9× o tempo real), ≈ 5,5 núcleos, pico de RAM +630 MB, sem GPU. Modelos: 46 MB. Áudio derivado
  só quando muda algo (≈ 115 MB por hora).
- **GPU:** o `onnxruntime` do Lumen é o de CPU (o Parakeet também usa). Trocar pelo `onnxruntime-gpu` (≈ 450 MB
  com cuFFT) mexeria na transcrição sem GPU; se um onnxruntime com CUDA ou DirectML estiver instalado, o filtro usa
  a GPU sozinho e volta para a CPU se ela falhar.
- **Original intacto e cache:** o áudio limpo é `work/<aula>/music-<chave>.wav` (16 kHz), gravado em `.tmp` e
  renomeado; a chave é o hash do áudio decodificado + versão da regra + modelos + modo, e o relatório
  (`music-<chave>.json`) guarda a decisão: transcrever de novo não processa o mesmo áudio outra vez (0,16 s). O WAV
  some ao confirmar a revisão (sem “Guardar gravações”) ou em 7 dias (`store.purge_old_uploads`).
- **Falhas:** qualquer erro do detector, do separador, da GPU, de memória ou de disco cai no áudio original
  (`music.prepare`), registra o tipo no log e a revisão mostra “Filtro de música não aplicado (…)”. Só cancelar
  interrompe. Se só sobrar música (nada de fala transcrita), o erro diz como desligar o filtro e tentar de novo.
- **Indicadores:** chip ♪ na barra flutuante (“Filtro de música ativo”; com isolamento, “o som do Spotify fica fora
  da gravação”), a mesma frase na dica da gravação, “Filtrando música externa…” no progresso e uma linha na revisão
  (“Música externa detectada e filtrada…” ou “nenhuma música externa detectada”). Nada de pop-up. Conferido no Edge
  (CDP): chip, Ajustes, gravação da preferência, sem erros de JavaScript.
- **Logs** (sem conteúdo): `sourceIsolationUsed`, `musicDetected`, `musicConfidence`, `speechConfidence`,
  `separationConfidence`, `sourceSeparationUsed`, segundos separados/incertos/removidos, tempo, CPU/GPU, e depois do
  ASR: trechos marcados e incertos (avg_logprob < −1, a confiança do ASR disponível no app; o antes/depois fica no
  benchmark, que não cabe numa aula real sem transcrever duas vezes).
- **Limites:** letra de música no mesmo navegador da aula (YouTube Music numa aba) não é tirada, só marcada: rap e
  voz “falada” parecem um professor falando sobre música alta, e na dúvida a fala fica. O isolamento exclui um app
  de música por vez, decidido no início da gravação (um aberto depois não sai). Fala sob música muito alta (+15 dB)
  continua quase perdida (90%). Fala 2× com música não melhora. Medido com fala lida/palestra/conversa reais e
  música real do MUSDB18 (pop, rock, eletrônica, acústica, um rap), mais piano e eletrônica sintéticos; não com
  aulas suas gravadas com música.
- **Melhorias possíveis (feitas na v2, abaixo):** voz do professor, sonda com rap e clássica, separador na GPU,
  modos na interface. Continua em aberto: isolar a aba do navegador (exigiria extensão).

### Filtro de música v2 (21/10/2026; `lumen/music.py`, `lumen/speaker.py`, `bench/music_bench.py run2`)

Incremental sobre a v1: mesmos detector, separador, emenda, cache, recuo e integração. Medido antes de mudar
(`run2 antes`, com a v1 congelada) e depois, no mesmo conjunto (`bench/RESULTADOS_MUSICA_V2.md`).

- **Conjunto de validação v2** (fora do app, em `bench/.data`): 16 “professores” (palestras TEDx do CORAA, 30 falas
  seguidas de cada, dev e test; o train só existe em .rar), aulas de ≈ 60 s com metade sem música, e música do MUSDB18
  test, do GTZAN 50–99 (hip-hop, clássica, rock, pop, jazz, reggae, country, metal, blues, disco; lido em fluxo do
  pacote de 1,2 GB, guardados 330 clipes) e coral (Cantoría, 5 mixagens SATB; o Zenodo recusou o acesso, veio do
  espelho no Hugging Face, conferido por SHA-256). Cenários: professor sozinho; + instrumental 0/+5/+10 dB; música a
  aula toda; + cantor (vozes femininas e masculinas); + rap; rap a aula toda; dois professores alternando; professor
  novo que só aparece sob música; + clássica 0/+5/+10; música contínua com o professor pausando (cantor, rap);
  podcast com vinheta e trilha; professor tocando uma música para a turma; coral sozinho e com fala; voz a cappella
  sozinha e com fala; instrumental e clássica sem voz; professor rápido (1,5×); professor baixo (−26 dB); conversa
  com várias pessoas; spoken word (outra pessoa falando sobre uma batida, por cima da aula); 8 gêneros. 152 casos,
  nos 3 modos.
- **Voz do professor** (`lumen/speaker.py`): embedding do ResNet34-LM do WeSpeaker (VoxCeleb, CC-BY-4.0, ONNX de
  26 MB, fbank do Kaldi reescrito em numpy, sem PyTorch). O CAM++ do WeSpeaker em ONNX foi testado primeiro e
  descartado: com as mesmas características, EER 27% nos 16 palestrantes, contra 0% do ResNet34 (mesmo palestrante
  0,76 de mediana, outro 0,26). Referência: janelas de 3 s de fala limpa da própria aula (YAMNet fala ≥ 0,5, sem
  música; se faltar, fala clara sobre música baixa), até 40 espalhadas, agrupadas por voz (ligação média, 0,35):
  dois professores, entrevista e aluno perguntando dão grupos separados, todos tratados como locutores da aula
  (16 palestras: um professor dá 1–2 grupos; 8 pares de professores nunca viraram um grupo só). Nos trechos com
  música, a voz separada é comparada com o grupo mais parecido.
  - Medido sob música (voz separada): o próprio professor fica em 0,40 de mediana (5%: 0,09); cantores 0,18,
    rappers 0,14, outros professores até 0,34. Ou seja: **similaridade alta prova que é o professor; baixa não prova
    nada**. Por isso a voz entra como proteção (≥ 0,4: nunca silenciada nem marcada, e a voz separada pode entrar
    com a sonda em dúvida), não como regra de corte.
  - “Voz diferente → marcar” (other_sim) foi medido e ficou só no agressivo: no balanceado, a 0,2, tirou 45 palavras
    de letra sem marca e marcou 750 palavras do professor a mais.
  - Privacidade: o embedding só existe na memória durante o filtro; nada de voz vai para disco (o relatório da aula
    guarda só similaridade mediana e número de locutores), nem é comparado entre aulas. O “cache de voz” é o cache do
    próprio filtro: o mesmo áudio no mesmo modo não é processado de novo.
- **Sonda retreinada** (a mesma regressão logística sobre os embeddings congelados do YAMNet; nenhum modelo grande
  treinado): + hip-hop e clássica do GTZAN 0–49 no treino e 2 sinais de ritmo (`music.rhythm`: periodicidade da
  voz separada no período da batida do acompanhamento e correlação dos ataques; AUC sozinhos rap × professor 0,73 e
  0,76). Teste (falas B, MUSDB test, GTZAN 50–99): AUC 0,860 → 0,930; rap 0,773 → 0,859; clássica 0,989 → 0,996.
  Com o limiar do app, o rap que passava por fala caiu de **64% para 19%** dos quadros, com a mesma fala mantida
  (85,8% → 85,1%) e a mesma letra cantada passando (4,5% → 4,0%). O primeiro treino (l2 = 0,1) tinha AUC 0,918 e
  calibração ruim (70% da música cantada acima do limiar: a letra passaria sem marca); ficou l2 = 0,01, MUSDB com
  peso 2 e o viés ajustado no treino (−1,0) para a música cantada passar em ≤ 3,5%.
- **Clássica**: o detector já pegava (música ≥ 0,3 em 90–100% dos quadros de orquestra e piano). O ganho veio da sonda
  e da voz do professor: professor + clássica, WER 31,7% → 16,7% (0 dB), 30,2% → 26,3% (+5), 39,9% → 28,9% (+10).
- **Música só da aula** (`music.external`): silenciar (agressivo) só vale na música que toca por baixo da fala (≥ 3 s
  de fala dentro do mesmo trecho de música). Música sozinha (o professor mostrando uma música, vinheta, faixa sem
  aula) é só marcada, em qualquer modo. Falsos positivos do agressivo (aula sem música externa e o filtro mexeu):
  12/20 → 6/20.
- **Nível**: o YAMNet perdia a música abaixo de ≈ −50 dBFS (aula gravada muito baixa: 0–2% dos quadros). O detector
  recebe o áudio quieto mais alto (até +30 dB, `music.level_gain`); o ASR recebe o volume original.
- **Separação com limiar próprio** (sep_keep): a dominância ≥ 7 dB já barra a letra, então a voz separada pode entrar
  com menos certeza de fala do que a usada para marcar. Balanceado 0,5 (5% menos palavras perdidas que 0,6, mesmo
  total de erros; abaixo disso a fala rápida e a de dois professores pioravam), agressivo 0,3, conservador 0,6.
- **GPU** (`music._session`/`_run`): o separador e a voz rodam no DirectML (onnxruntime-directml, 25 MB, qualquer GPU
  DirectX 12) ou CUDA (onnxruntime-gpu) se estiver instalado; se a sessão não abrir ou a GPU falhar no meio, refaz na
  CPU e não tenta mais a GPU naquele processo. O detector fica na CPU. Escolhido o DirectML: 25 MB contra 161 MB do
  onnxruntime-gpu (que ainda precisaria de cuFFT e cuDNN) e funciona também em AMD e Intel. Ele substitui o
  onnxruntime de CPU (mesmo módulo; o `Iniciar Lumen.bat` troca na opção de GPU); o Parakeet foi fixado na CPU para
  não mudar (Parakeet e Whisper deram o mesmo texto com o pacote novo). Medido (10 min, pior caso, RTX 3060):
  163 s → 28 s (21× o tempo real), CPU 912 s → 41 s, RAM de pico 1054 → 805 MB, +556 MB de VRAM, saída idêntica
  (diferença máxima 0).
- **Modos** (`music.MODES`, a única tabela de limiares; Ajustes → Filtrar música externa → Modo): conservador marca
  mais (keep 0,7) e separa só com confiança alta (0,6), nunca silencia; balanceado (padrão) separa a partir de 0,5,
  nunca silencia; agressivo detecta música a partir de 0,25, separa também onde a fala é razoavelmente clara, a
  partir de 0,3 e com a música 5 dB acima, marca a voz diferente da dos locutores da aula e silencia música ao fundo
  sem fala.
- **Antes × depois** (152 casos por modo; WER nas aulas com fala; sem filtro 42,2%):

  | Modo | WER v1 → v2 | Palavras perdidas | Letra sem marca | Fala marcada | Falsos positivos | Falsos negativos |
  |---|---|---|---|---|---|---|
  | conservador | 37,1% → 34,3% | 3511 → 3113 | 159 → 158 | 1647 → 1637 | 0/20 → 0/20 | 6 → 4 de 132 |
  | balanceado | 36,3% → 34,5% | 3098 → 2948 | 188 → 176 | 925 → 1119 | 0/20 → 0/20 | 6 → 4 de 132 |
  | agressivo | 35,7% → 34,1% | 3135 → 2978 | 225 → 126 | 874 → 1812 | 12/20 → 6/20 | 6 → 4 de 132 |

  No conjunto da v1 (falas isoladas de 10 s, sem trecho limpo para a referência de voz), tudo idêntico, menos
  instrumental +5 dB 48,9% → 51,5%, +10 dB 52,3% → 53,2%, +15 dB 90,2% → 86,4% e eletrônica sintética +10 dB
  41,1% → 45,2%: é a sonda nova, mais conservadora com fala curta sem referência.
- **Limites da v2:** voz cantada sem instrumentos (a cappella) não é detectada (o YAMNet dá canto ≈ 0,02 nas vozes
  do MUSDB): são os 4 falsos negativos que sobraram; a letra passa sem marca. Professor que só fala sob música alta
  não tem referência (fica com a sonda, como na v1). Mais fala marcada como dúvida no balanceado (925 → 1119
  palavras; chega à IA como “(?)”, não some). Rap com o professor junto (+5 dB) ainda deixa 16 palavras de letra sem
  marca (37 sem filtro). Spoken word por cima da aula não melhora (47 → 47). O Whisper às vezes entra em repetição
  com a entrada mudada: num caso de professor novo sob música, +100 palavras inseridas (nos outros 3, menos erros
  que na v1).

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

### Pausar captura e Pomodoro (21/10/2026; `lumen/record.py`, `lumen/pomodoro.py`, `lumen/web/pomodoro.js`)

- Pausa = flag em `record` (`_pause`), não um estado novo: a sessão continua `active`. O laço de áudio segue lendo do
  driver (senão o Windows acumula e devolve áudio velho ao retomar) e descarta os trechos lidos durante a pausa,
  conferindo antes e depois da leitura. `vision.Watch(hold=...)` não copia a tela; ao pausar, guarda a tela que
  esperava ficar parada e recomeça a comparação do zero ao retomar.
- Linha do tempo: o tempo gravado (frames do WAV) é o relógio das telas, então a pausa some da aula sem silêncio. O
  tempo real (`elapsed`) e as pausas (`at`, `from`, `to`) vão para `<gravação>.session`.
- Recuperação: um `.session` por gravação (um arquivo único era sobrescrito pela gravação seguinte e perdia a guardada).
  Sair do app com gravação usa `stop(keep=True)` e oferece a gravação na próxima abertura.
- Pomodoro no servidor (não no navegador): um estado para as três janelas, persistido, com `ends_at`; a interface só
  desenha `ends_at − agora` (relógio do servidor corrigido). Etapas vencidas durante suspensão são contadas de uma vez;
  um fim com mais de 90 s não toca nem avisa.
- Som: `winsound` com um tom gerado (sem arquivo), bloqueado com a captura gravando (o loopback gravaria o aviso).
  Notificação: balão da bandeja com `NIIF_NOSOUND` (via `Shell_NotifyIcon` com o id/janela do `NotifyIcon` por
  reflexão), uma vez por evento mesmo com várias janelas.
- “Pausar a captura durante os intervalos” não foi implementado; o ponto de entrada é `pomodoro._next`.

### Minha compreensão: uma nota, um status (22/10/2026; `lumen/understanding.py`, `lumen/web/understanding-editor.js`)

- **Causa da divergência.** A nota já era um documento só por aula (`Notes`, espelhado por BroadcastChannel, com o
  servidor ordenando por horário): com a mesma aula, as três janelas nunca divergiam (medido com as três abertas e
  digitação alternada). O que divergia era *qual aula* cada janela mostrava: a flutuante ficava presa na chave da URL ao
  trocar de aula na principal; a barra lateral usava `notes[0]` quando a aula em foco não estava na lista, e a aula
  recém-criada (sem texto, ainda preparando) não estava; e a nota sumia da barra ao entrar em análise.
  Agora há uma “aula em foco” (`Notes.setActive`, transmitida às janelas) que as três seguem; a barra só troca de
  aula depois de duas leituras seguidas sem ela e nunca ao receber o aviso (a lista pode ser a anterior).
- **Corrida corrigida.** `analyzing` só era marcado dentro do job, depois de `require` e do plano de tempo: nesse
  intervalo a nota aceitava texto que a análise não leria, e um erro cedo deixava a nota travada. O servidor trava no
  instante do pedido (`begin_analysis`) e o job solta em qualquer saída (`finally`); se o job nem começa, `_submit` solta.
- **Versões.** `rev` por escrita aceita; um autosave com horário menor que o do servidor volta `stale` com o texto novo e
  não cria revisão; `submit` leva o horário da versão que a interface tem e recusa se outra janela já gravou mais nova;
  a análise grava `submitted_rev`/`analyzed_rev`. Escolhi **bloquear a edição durante a análise** (em vez de editar com
  *snapshot*): é o mesmo resultado seguro e sem duas versões em disputa.
- **Prontidão** (`understanding.readiness`): fases preparing, prep_failed, recording, busy, writing, ready, processing,
  interrupted, completed, synced. O servidor decide o que bloqueia fora da nota (gravação, tarefa, preparação); o
  cliente (`Notes.ready`) soma o texto de agora e o estado do salvamento. `processing_since` persiste o pedido: se o
  app fechar ou a análise falhar, a nota volta como “Não foi possível analisar”, com tentar de novo.
- **Sem polling novo.** A barra e a flutuante já consultavam `/api/widget` (a flutuante agora usa ele no lugar de
  `/api/record`); o `notes` dele leva estado, prontidão e horário de cada aula, e `Notes.merge` aplica. O recarregamento
  de 3 s de antes continua como reserva se um aviso entre janelas se perder.

## Notion + Obsidian: um StudyPackage, dois destinos (23/10/2026; `lumen/package.py`, `obsidian.py`, `canvas.py`, `vault.py`)

- **Pedido do usuário:** a aula é processada uma vez e o mesmo conteúdo vai para o Notion (organização) e para o
  Obsidian (segundo cérebro: nota, Canvas, conexões, revisão). Nada de dois pipelines nem de dois resumos diferentes.
- **Fluxo:**

  ```
  Captura (record, vision, sources) → Transcrição → Minha compreensão (understanding.py, sem mudança) → análise
  → Study Processor (jobs.finish): llm.generate (1 passada) → [Profundo] llm.refine → charts.extract
                                   → [Obsidian] vault.search + llm.connect
  → StudyPackage (package.build + validate) → DATA/packages/<lumen_id>.json
  → Destination Router (jobs._deliver): Obsidian (obsidian.deliver) → Notion (jobs._notion → notion.publish)
  → manifesto (history.json)
  ```

  A IA escreve o material **uma vez**. Os destinos só renderizam: `notion.build_page`/`understanding_page` e
  `obsidian.render`/`canvas.build` leem o pacote e nunca leem um do outro. A fonte da verdade é o pacote, não o Notion
  nem o Obsidian.
- **StudyPackage** (`package.py`): `lumen_id` (`lm-` + hash da chave da fonte: o mesmo vídeo ou arquivo dá o mesmo
  id), `processor_version` (`2.0`), `content_hash` (do conteúdo, sem horários), fonte, curso, `understanding` (as
  chaves de `understanding.py`, intactas; a análise da IA fica à parte em `ai_analysis`), `lesson` (material da IA),
  mapa limpo, telas (só texto), gráficos, conexões, âncoras, flashcards e linha do tempo derivados (sem IA nova) e as
  datas de revisão. O validador recusa material sem título, resumo, tópicos ou nota do estudante, e pergunta sem
  resposta. Ele também descarta relações entre rótulos que o mapa não tem e conexões com notas que não existem, e
  troca credenciais (`ntn_`, `secret_`, `sk-`, `Bearer`, o token do keyring) por "[segredo removido]".
- **IA:** o esquema ganhou:
  - `topics[].why`;
  - `review_questions[].kind` (recordação, compreensão, relação, aplicação, diagnóstico, síntese; no máximo metade de
    recordação);
  - `map_kind` (conceitual, tutorial, argumentação, sistema, livro), que decide a forma do mapa;
  - `relations`, com tipo fechado;
  - `mistakes`, `applications`, `open_questions` e `permanent_ideas`.

  Continua sendo uma chamada. As conexões usam `llm.connect`: as notas candidatas vão num **enum do JSON Schema**,
  então o Ollama não consegue citar uma nota que não existe. Profundidade (Ajustes → IA local):
  - **Rápido:** 1 passada, sem conexões;
  - **Balanceado:** 1 passada + conexões (padrão);
  - **Profundo:** + `llm.refine`, uma 2ª passada que critica o material contra a aula e devolve o mesmo esquema. Se
    falhar, fica a 1ª versão.

  Tudo fica em `lesson.json`: "Tentar novamente" não chama a IA de novo.
- **Conexões sem banco vetorial:** o cofre tem dezenas de notas. Os candidatos saem de um BM25 simples (stdlib, sem
  acentos, palavras cortadas em 6 letras). Título e aliases pesam mais. Ficam de fora templates, notas de sistema,
  memória e logs da IA, diário e capturas. A IA local escolhe entre os 12 primeiros e os Anchor Topics, e dá o motivo
  de cada um. Nada do cofre sai do PC.
- **Onde fica no Obsidian** (decisão D010 do cofre): em `C04 Claude Obsidian/16 Lumen`, a área da IA. O CLAUDE.md do
  cofre reserva a escrita automática a C04. As notas são `type: ai-study`, `author: lumen-ai`,
  `status: review-required`, nomeadas `AAAA-MM-DD - Título da aula` (título em `aliases`), com o canvas
  `Mapa - Título da aula.canvas` e as imagens em `Anexos`. O Lumen nunca escreve fora da pasta configurada:
  `vault.inside` recusa `..`, caminho absoluto, pasta oculta e junction que sai do cofre.
- **Nota:**
  - o frontmatter segue as convenções do cofre (links entre aspas, datas `AAAA-MM-DD`, âncoras em `topics`);
  - abre com `> [!info]- Como usar esta nota` e `> [!warning] Conteúdo gerado por IA`, que o `vault-check.mjs` do
    cofre exige;
  - o material fica entre `%% lumen:begin %%` e `%% lumen:end <hash> %%`; depois vem "Minhas anotações";
  - sem emojis (preferência do cofre);
  - o texto da IA é escapado: `[[` não vira link, `#` não vira tag, `%%` e `<` são neutralizados, `|` é escapado nas
    tabelas.
- **Atualizar sem destruir:**
  - tudo fora do bloco fica byte a byte;
  - o frontmatter é mesclado linha a linha: o Lumen atualiza só as chaves dele; `status`, revisão e chaves do usuário
    ficam; `topics`, `related` e `aliases` viram a união;
  - caixas marcadas (revisões, ideias) são levadas para a versão nova;
  - se o bloco foi editado à mão (o hash no marcador não bate), nada é gravado: a interface mostra o conflito e
    "Substituir mesmo assim" faz backup em `DATA/obsidian-backups` (10 por aula);
  - a nota é achada pelo `lumen-id`, mesmo renomeada; movida para fora da pasta do Lumen, ela não é tocada;
  - o mesmo material não muda nem a data de atualização (idempotente).

  A escrita é atômica: arquivo oculto + `os.replace`.
- **Canvas** (JSON Canvas 1.0, testado no Obsidian 1.14 real pelo CDP):
  - o centro é um node `file` da nota com `subpath: "#Visão geral"` (sem o subpath, o card mostrava só o
    frontmatter);
  - ramos do mapa à direita e à esquerda, balanceados pela altura; ramos ligados por uma relação ficam do mesmo lado;
  - filhos ao lado do ramo e uma cor do Obsidian por ramo;
  - relação entre pai e filho rotula a seta que já existe (ponta em quem recebe);
  - relação entre lados opostos vira card no grupo "Relações": a seta atravessaria a nota central (visto no teste);
  - embaixo, os grupos Processo (passos encadeados), Conexões (cards com `[[nota]]` e o motivo; um card de arquivo
    mostrava só as propriedades), Exemplos e Relações; em cima, o vídeo original (node `link`);
  - IDs estáveis (`lumen-` + hash do papel e do rótulo);
  - `canvas.check` recusa sobreposição, card solto, grupo vazio, id repetido e seta para card inexistente; no Obsidian
    real, de 2 a 8 ramos, 0 sobreposições e nenhum texto cortado;
  - ao reprocessar, `canvas.merge` mantém a posição e o tamanho dos cards que o usuário mexeu e os cards e setas que
    ele criou; os grupos se ajustam. Sem o manifesto (dados locais apagados), o canvas existente é sempre tratado
    como editado: as posições ficam.
- **Revisões:**
  - `review_intervals` (padrão 1, 3, 7, 14, 30 e 60 dias depois do estudo) gera `- [ ] Revisão N · data` na nota;
  - `sync_reviews`, ao abrir o Lumen e depois de cada entrega, conta as marcadas e atualiza `review-stage` e
    `next-review` (só essas duas chaves, só nas notas `ai-study`);
  - o painel `Lumen Dashboard.md` usa Bases (core; o cofre não usa plugins da comunidade, decisão D001), com as
    visões: Para revisar hoje, Atrasados, Estudando agora, Processados recentemente, Não revisados, Por curso, Por
    Anchor Topic, Com dúvidas e Para virar nota permanente. Cada filtro foi conferido no Obsidian real com uma nota
    vencida.
- **Manifesto e repetição:**
  - `history.json` passou a mesclar as entradas: Notion (`page_id`, `block_ids`, `url`, `notion_status`),
    `obsidian` (nota, canvas, `canvas_hash`, status, erro), `lumen_id`, `content_hash` e versão;
  - o Obsidian é salvo primeiro: é local e idempotente, então repetir não duplica. Depois vem o Notion, que já desfazia
    o envio em falha ou cancelamento;
  - a falha de um destino não desfaz o outro: o job termina "parcial", e "Tentar de novo só o X" (`/api/deliver`) usa
    o pacote guardado, sem IA;
  - o canvas e o painel têm status próprio: se o canvas falhar, a nota sai sem o mapa embutido, sem link quebrado.
- **Abrir no Obsidian:** `/api/open` monta `obsidian://open?path=…` a partir do manifesto, só para arquivos do cofre
  configurado, e chama `os.startfile`. Nenhuma URI vem da interface.
- **Não feito (avaliado):**
  - canvas global do conhecimento: a Graph view (core) e o painel por Anchor Topic cobrem isso;
  - snippet CSS: `.obsidian` é área do usuário, e o tema padrão ficou limpo;
  - plugin de Spaced Repetition: os flashcards são callouts recolhidos, legíveis sem plugin;
  - migração dos materiais antigos: os `lesson.json` de antes não existem mais. Daqui em diante os pacotes ficam, e a
    Biblioteca tem "Salvar no Obsidian";
  - outro provider de IA: continua só o Ollama local (ver "IA (texto)").
- **O que o teste real mudou** (aula de teste sobre RAG, Ollama `qwen3:8b`, Notion real e o cofre real, apagados
  depois):
  1. *Gráfico derrubava o material:* no Windows, o Edge sem janela ainda segura o perfil quando o
     `TemporaryDirectory` fecha, e a limpeza levantava `PermissionError` fora do `try`. A entrega inteira falhava com
     "Erro ao ler ou gravar um arquivo". O defeito já existia (gráficos, mapa mental, capas, imagens). Agora:
     `ignore_cleanup_errors=True`; `_draw` isola a falha de cada gráfico (fica a tabela); o erro de arquivo diz qual
     arquivo; pastas `%TEMP%\lumen-*` com mais de um dia são apagadas ao abrir.
  2. *Publicação parada para sempre:* com o `--screenshot` quebrado do Edge 155, o desenho do mapa estoura o tempo;
     o Edge é morto, mas o processo auxiliar dele (crashpad) segura os pipes do `capture_output=True`, e o
     `subprocess.run` nunca volta. Nada chegou ao Notion; o processo ficou ocioso. Agora a saída do Edge (e do
     gerador de capas) vai para `DEVNULL`. Ninguém lia aquela saída.
  3. *Conexões ruins:* num cofre ainda sem notas de conhecimento, a busca trouxe notas de sistema (Agents, Skills,
     Fila de Processamento, Índice de Imagens). A IA as aceitou, chegando a escrever "não seja diretamente
     relacionado". Agora: num cofre que usa `type:`, só os tipos de conhecimento são candidatos (permanent, resource,
     project, book, ai-study; Anchor Topics à parte); a busca exige ao menos dois termos da aula em comum; a IA
     classifica cada conexão (`strength`: forte, media, fraca) e as fracas são descartadas. Flashcards repetidos
     (glossário e "O que é X?" com a mesma resposta) viram um só.
  4. *A análise da compreensão funcionou:* a nota de teste tinha um erro de conceito ("o modelo é treinado de novo
     com esses documentos"). Ele saiu em "Possíveis confusões" com a correção da aula, e a nota de estudo o trata em
     "Erros comuns".

## Redesign da interface (24/10/2026; `lumen/web/ui.css`, `docs/DESIGN.md`)

- **Sempre escuro.** O tema claro saiu; o `Lumen.exe` não lê mais o tema do Windows (`BackColor` e bordas DWM fixas
  em `--bg-base`). A barra flutuante já era só escura.
- **Navegação.** Rail com Início, Nova aula, Biblioteca, Integrações e Ajustes; barra superior com contexto, busca
  (Ctrl+K), status global e Pomodoro. Ajustes e Integrações deixaram de ser um diálogo de 9 seções e viraram páginas;
  as fontes saíram da barra lateral para um segmentado dentro da Nova aula. Os IDs que o `app.js`, o C# e os testes
  usam continuam os mesmos.
- **Vidro só simulado nas superfícies grandes.** Com a GPU desligada no WebView2, `backdrop-filter` em áreas grandes
  custa CPU a cada quadro; ele fica só na busca e nos flutuantes pequenos. Medido no Chrome sem GPU com a mesma API
  simulada (antes → depois): carga até o estado 191 → 186 ms, trocar de tela 33,0 → 32,6 ms, abrir Ajustes
  30,1 → 31,2 ms, rolar a análise 16,3 → 16,3 ms por quadro, redimensionar 27,1 → 21,8 ms, CPU com a Nova aula parada
  13 → 28 ms em 5 s e com a barra aberta parada 29 → 36 ms em 5 s (ambos abaixo de 1% de um núcleo). O heap JS não
  cresce em 50 trocas de tela (1,71 → 1,74 MB) e os elementos vivos ficam estáveis.
- **Repouso sem animação.** O botão de gravar parado não pulsa mais (na barra e na janela principal); só a gravação
  e o processamento se movem.
- **Dicas próprias, sem `title`.** O tooltip nativo some atrás das janelas sempre por cima; `ui.js` mostra uma dica
  no hover e no foco pelo teclado, dentro da janela.
- **Confirmações do Lumen** (`ui.confirm`) no lugar do `confirm()` do navegador, só para o que não se desfaz.
- **Revisões no Início.** `obsidian.due_reviews` lê o `next-review` que `sync_reviews` já mantém nas notas de estudo
  (nada é escrito) e `GET /api/reviews` liga cada nota à aula da history, para abrir pelo `/api/open` de sempre.
- **Testes visuais.** `tests/ui_shots.py` captura cada tela e estado de 520×560 a 1920×1040 e de 80% a 120% de zoom e
  confere rolagem horizontal, controles cortados e alvos pequenos; `DesktopChecks.cs` guarda imagens das janelas reais
  do WebView2 com `LUMEN_SHOTS`.
- **Limitações.** Os cantos da barra flutuante continuam serrilhados (região GDI; os cantos do DWM teriam outro raio e
  mudariam a geometria testada). A barra não ganhou modos compacto/mínimo novos: a alça recolhida já é o modo mínimo e
  mostra gravando (vermelho) e pausado (âmbar). Abaixo de 380 px de altura, a janela da nota mostra só o texto (o
  status e “Processar” ficam na janela principal e na barra).
