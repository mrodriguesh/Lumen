# Decisões e limitações

## 04/11/2026 — Direção do produto e documentos dos Estudos

O Lúmen deve ser a base local do segundo cérebro do usuário e de tecnologias futuras. O aprendizado é uma aplicação dessa base. Preservar contexto, autoria e fontes faz parte dessa direção; não foi adicionada nesta sessão uma API pública ou integração de fase futura.

PDFs usam A4 e fundo claro por padrão, com opção escura. É uma exceção à interface sempre escura, pois o documento também é impresso. A renderização continua em `lumen/cdp.py`. Decisões da fase 7: D66–D73 em `docs/implementation/LUMEN_STUDY_AI_DECISIONS.md`.

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
  gdrive.py      Google Drive pela API oficial (OAuth de app para computador): a conta da cópia de segurança da Proteção
                 (o antigo notebook.py, do Gemini Notebook, foi retirado em 09/11/2026)
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
- Não há opção em nuvem para gerar as aulas. Nenhum serviço gratuito encontrado tinha custo e limites estáveis o bastante para cumprir
  o requisito de transparência.
- Revisto em 31/10/2026 só para a aba Estudos (Lúmen Study AI): o Claude entra como provedor **opcional**. Ele só funciona com a chave de API do
  próprio usuário e com “Permitir envio a provedores externos” ligado (desligado por padrão e restringível por projeto), e cada envio vai para
  o registro de atividades. A IA local continua sendo o padrão. Detalhes em `docs/implementation/LUMEN_STUDY_AI_DECISIONS.md`.

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

## Capas do Notion: capa em qualquer página (27/10/2026; `lumen/notion.py`, `lumen/server.py`)

- **Independente de curso:** a capa vai na própria página escolhida (comum, subpágina, raiz, registro de banco),
  com o token do Notion e nada mais: sem página raiz, sem curso, com qualquer destino das aulas. A busca usa
  `POST /v1/search` paginado (20 por vez) e inclui registros de banco; `list_pages`, dos destinos das aulas, continua
  sem eles. Títulos repetidos na mesma leva ganham o nome da mãe: o da mãe que veio na mesma leva sai dela, as
  outras são consultadas uma vez cada, 4 por vez. No workspace real (uma “Minha compreensão” por aula) a lista inicial
  caiu de 4,9 s (um GET por repetido, em fila) para 0,4 s. A busca da API só vê o que foi compartilhado com a
  integração, e a interface diz isso.
- **Link colado:** só o ID sai dele (`page_id`: `?p=` do registro aberto sobre o banco, senão o fim do caminho;
  `?v=` e `#bloco` nunca são a página). O link nunca é aberto; toda requisição autenticada vai para `api.notion.com`.
  Um ID de banco dá 400 no `GET /pages` e vira “Este link não é de uma página”.
- **Só o campo `cover`:** `PATCH /v1/pages/{id}` com `{"cover": {"type": "file_upload", ...}}` e nada mais (nada
  de propriedades, template, bloqueio ou conteúdo). 403 no PATCH = falta “Atualizar conteúdo” na integração.
- **Prévia presa ao contexto (no servidor):** página, tema, conexão (hash do token) e a mais nova da página. Fora
  disso, “gere de novo”, sem tocar no Notion. Uma aplicação por vez (clique duplo recusado).
- **Confirmação por bytes:** a capa enviada volta como `type: "file"` com URL temporária, e a documentação não traz
  um identificador do envio nela. `type == "file"` não prova nada (a página pode já ter uma capa assim), e a URL
  assinada muda a cada leitura. Por isso o Lumen relê a página, baixa a URL temporária **sem o token** e compara com
  o PNG aprovado. Diferente = “a página continua com outra capa”; sem download = “Não foi possível confirmar”. Para
  saber se a capa mudou desde a seleção, compara `cover_ref` (host + caminho, sem a assinatura).
- **Sem resposta do PATCH:** não repete às cegas (`once=True`). A tentativa seguinte confere a página primeiro e só
  reenvia se a capa não for a aprovada, reaproveitando o mesmo envio (`GET /v1/file_uploads/{id}` = `uploaded`; um
  envio anexado pode ser reusado, segundo o guia oficial). O log guarda página, envio, capa anterior e estado, para
  diagnóstico; restaurar a capa anterior não é prometido (a URL dela é temporária).
- **Gerador:** o mesmo das capas de curso (`_draw`: `llm.decorate` + Z-Image, ou emojis). Da decoração, só a
  imagem é usada: ícone e destaque da página não mudam. A capa de cor do Notion não serve de alternativa aqui (não
  há o que mostrar na prévia), então sem nenhum desenho é erro com “Tentar de novo”.
- **Botão Capa na Nova aula (cartão do Notion):** abre um diálogo com o mesmo bloco de Ajustes (`#cov-box` muda de
  lugar enquanto o diálogo está aberto): um estado, os mesmos IDs, as mesmas rotas e proteções. A página vem só de IDs
  reais (`covTarget`): curso ou módulo do catálogo com `notion_page_id`; a página onde a aula já foi publicada
  (histórico: “A organizar”, ou o material gratuito criado para ela). Módulo sem página não cai na página do curso;
  material gratuito novo, aula avulsa e “Sem curso” pedem a página (a de “Sem curso” só se conhece criando ou
  procurando pelo título, e nenhum dos dois cabe aqui). A página é validada pela API ao abrir; nada é criado. Reabrir
  para o mesmo destino mantém a escolha e a prévia; com uma geração ou aplicação em andamento, nada muda de página.
- **Curso novo:** `create_course` continua conferindo só o tipo da capa: a página acabou de ser criada com ela, não
  havia capa anterior para confundir.
- **Validado no Notion real (27/10/2026,** página de teste criada e depois enviada para a lixeira): busca e link
  acharam a página; a capa gerada (Z-Image, 1536×640, 79 s e 82 s na RTX 3060, com o texto da IA) foi aplicada e
  conferida; a URL assinada mudou entre duas leituras, o host + caminho não; os bytes baixados eram os enviados;
  título, ícone e blocos ficaram iguais; substituir uma capa `file` por outra foi confirmado, e a capa vista
  desatualizada gerou o aviso antes da troca.

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

## Pomodoro como função global (25/10/2026; `lumen/web/pomodoro.js`, `lumen/web/ui.css`)
- **O estado não mudou.** `lumen/pomodoro.py` já era a fonte única (horário de término, persistido, etapas contadas
  depois de suspender), e `pomodoro.js` já tinha um relógio só por janela. O redesign é só de interface.
- **Estados à vista** derivados no cliente: Iniciar (nada começou), Foco, Pausado, Pausa, Pausa longa, Foco concluído
  (parado no começo de uma pausa, sem início automático) e Hora de focar. No chip da barra o estado inicial diz
  “Iniciar”, não “Pronto”, porque a pílula de status do Lumen ao lado já diz “Pronto”.
- **Anel** (`stroke-dashoffset` de `--pomo-p`) no chip e no painel: identifica o Pomodoro sem depender de cor e não se
  confunde com o relógio da gravação. Sem histórico confiável de sessões, o Início não mostra métricas de foco.
- **Contexto** (“Agora: <aula>”) é só o que está aberto na tela, lido ao desenhar o painel; nada é guardado com o
  timer.
- **Sem atalho novo:** `Ctrl+Alt+P` já pausa a captura. Iniciar, pausar e abrir o Pomodoro ficam na busca (Ctrl+K).
- **Barra flutuante:** o chip mostra anel, Foco/Pausa e o tempo; para caber, o status do topo da barra ficou curto
  (Pronto, Gravando, Pausada…) com a frase inteira na dica. Os controles completos ficam na janela principal e na nota.
- Correção encontrada nos testes: recusar um envio (`_upload`) sem ler o corpo derrubava a conexão às vezes
  (WinError 10053) e a mensagem de erro se perdia; agora o corpo é lido antes, até 64 MB.

## Painel visual: o segundo Canvas (25/10/2026; `lumen/board.py`, `lumen/obsidian.py`)
- **Dois Canvas com papéis diferentes.** O Mapa conceitual (`canvas.py`, sem mudança) diz como as ideias se relacionam;
  o Painel visual (`board.py`) é uma prancha das imagens da aula para reconhecer e lembrar. Nomes: o “Mapa - <Título>”
  ficou (nenhum link quebra) e o novo é “Painel - <Título>.canvas”. A nota embute o mapa e linka o painel em
  “Mapas da aula”: dois Canvas grandes embutidos na mesma nota pesam e se atrapalham.
- **Sem extração nova de quadros.** A captura (`vision.Watch`: tela parada 1,5 s, sem bordas pretas, sem apps
  pessoais), o vídeo (`vision.extract`, quadros-chave pelo PyAV, que já traz o FFmpeg), a deduplicação (miniatura 54×96
  e texto lido) e o filtro do modelo de visão (fora rosto do professor, propaganda e tela vazia) já existiam. O painel
  escolhe entre as telas do pacote e os gráficos da aula; nenhuma imagem nova vai para o cofre por causa dele, e
  nenhuma é gerada, buscada fora ou enviada para fora do PC.
- **Escolha local e determinística, sem IA:** tipo da tela, termos em comum com os tópicos da aula (o horário só
  desempata), o que o estudante escreveu e o que a análise da nota dele destacou (não há horário na compreensão: o
  vínculo é por texto), captura feita por ele, perto de um momento-chave, qualidade. Retorno decrescente por conceito
  (com teto, para uma aula visual de um tema só não ficar com 3 imagens) e as quase iguais saem pela mesma régua da
  captura (`vision._diff`). Nota mínima: aula só de fala não ganha painel (“sem imagens úteis”). O gráfico do Lumen só
  domina a prancha se não houver tela larga.
- **Composição** pelo tipo da aula (`map_kind` e as relações): editorial (a imagem principal com o cartão ao lado,
  primárias alternando lados em alturas desencontradas e a faixa de baixo como peças empilhadas, larguras variadas),
  sequência (tutorial: zigue-zague com setas) e comparação (“contrasta com” com imagem dos dois lados). “Pessoa” não
  existe: o modelo de visão descarta essas telas. Verificado no Obsidian 1.14 (perfil isolado + CDP) com 3, 6, 10, 13
  e 15 imagens, uma sequência e a última aula real: 0 sobreposições, nenhum texto cortado.
- **Edições do usuário.** O manifesto da aula guarda as posições que o Lumen gravou (`board_layout`) e os cards que o
  usuário já moveu (`board_user`), fora do JSON Canvas. Movido fica onde ele pôs, mesmo se a imagem saiu da escolha;
  criado por ele fica; uma peça nova que caia em cima de algo mantido desce; o que o Lumen mantém no lugar não se
  move por causa de algo que o usuário pôs em cima. Sem manifesto, tudo no arquivo conta como do usuário.
- **Correção no Mapa conceitual:** o atalho “arquivo igual ao gravado → layout novo” apagava posições do usuário
  preservadas numa fusão anterior; agora só vale quando o gravado era o layout puro (`canvas_hash` vazio depois de uma
  fusão).
- **Anexos:** o nome diz o que a imagem é (`03m09 título · aula data.jpg`), porque é o rótulo do Obsidian no painel;
  nome antigo que já existe fica. Num retry dias depois, a imagem que já está no cofre é usada (antes a tela entrava só
  com o texto). Ao reprocessar, sai só o anexo que o Lumen gravou, que nada mais usa e com o mesmo tamanho; com os
  anexos desligados nada é apagado.
- **Correção na gravação** (`obsidian._write`): com o Obsidian aberto, um arquivo novo criado como temporário oculto e
  renomeado às vezes não era notado (ele ignora nomes com ponto), e a imagem aparecia como “não encontrada” até
  reiniciar; na verificação ele perdeu 4 de 33. Arquivo novo agora nasce com o nome final (criação exclusiva, apagado
  se falhar no meio); arquivo que já existe segue com a troca atômica. Depois da correção: 30 de 30.
- **Não feito:** etapa nova no processamento (a escolha leva milissegundos: não há progresso a mostrar), prévia do
  painel dentro do Lumen (o destino é o Obsidian), mapas temáticos por pessoa ou por local (não há esse dado),
  imagens externas.

## Estudos: organização por curso, módulo e tema (25/10/2026; `lumen/catalog.py`, `lumen/area.py`)
- **Pedido do usuário:** a pasta `16 Lumen` misturava notas, mapas, painéis e imagens de todas as aulas. O usuário queria
  uma biblioteca de estudos com a lógica da área Estudos do Notion: Cursos e Conteúdo gratuito, e o Lumen como
  ferramenta, não como categoria.
- **StudyClassification no StudyPackage.** `pkg["classification"]` tem `type` (`course`, `free`, `single`, `inbox`),
  `course_id`/`course`, `module_id`/`module`, `lesson`, `category` e `platform`. É do estudo, não de um destino: o
  Notion e o Obsidian a traduzem cada um à sua maneira (paridade de sentido, não de caminho). `course` saiu do hash de
  conteúdo, porque organizar não é conteúdo.
- **Catálogo** (`DATA/catalog.json`, fora de “Limpar dados”): cursos e módulos com id estável (`c-`/`m-` + 8 hex).
  Renomear muda nome, pasta, propriedades e título no Notion, e o id fica. Nome igual (sem acento e caixa) é recusado,
  porque no Windows seria a mesma pasta. Nome parecido é só avisado. Plataforma e link aceitam só http(s), sem
  `usuário:senha@`, e texto com cara de segredo é recusado: o Lumen não guarda credenciais. Por isso não há “04 -
  Acessos”: a página do curso tem só plataforma e endereço.
- **Sugestões, nunca aplicadas sozinhas:** continuar no curso e módulo das últimas 12 h (com a aula seguinte), um curso
  cujo nome aparece no título, no link ou no caminho, e Conteúdo gratuito para um link do YouTube. Cada uma aparece
  com um botão “Usar”. Uma aula que já existe traz a organização que tem: reprocessar não a manda para “A organizar”.
- **Obsidian:** a área é `obsidian_folder`. O padrão é a pasta de topo “Estudos”, com ou sem número (no cofre do
  usuário, `B02 Estudos`, decisão D011 do cofre), e `obsidian_canvas_folder` saiu.
  - **Estrutura:** `01 - Cursos/<Curso>/[NN - Módulo]/[NN - Aula]/`, `02 - Conteúdo gratuito/[Tema]/`,
    `03 - Aulas avulsas/[Tema]/` e `90 - A organizar/`. Uma pasta por aula, com `Título.md`, `Mapa - Título.canvas`,
    `Painel - Título.canvas` e `Anexos/` (só se houver imagem).
  - **Nomes únicos**, como manda o cofre (`[[Nome]]` sem caminho). `Mapa Conceitual.canvas` genérico foi descartado:
    deixaria links ambíguos e obrigaria links com caminho, que quebram ao mover.
  - **Pastas criadas sob demanda.** Tema e “A organizar” vazios saem depois de mover. Curso e módulo vazios ficam.
- **Mover sem quebrar** (`area.relocate`). A pasta da aula é renomeada (`os.rename`, atômico no mesmo disco), ou só os
  arquivos dela, quando a pasta é dividida com outras aulas. Depois o Lumen reescreve os `file` dos Canvas da área, o
  manifesto (nota, canvas, painel, `files`, `images`) e os embeds da nota renomeada. Uma falha desfaz tudo.
  - **Quando move:** só quando a organização mudou no Lumen (Organizar, ou classificação diferente da `placed` do
    manifesto). Mover a pasta no Obsidian não briga com o Lumen.
  - **Mover no próprio Obsidian:** os nomes únicos fazem os embeds continuarem valendo. O Obsidian (`alwaysUpdateLinks`)
    cuida dos Canvas.
- **Limite do Windows** (achado no teste visual). A imagem migrada de nome antigo (~100 caracteres) passou de 260 dentro
  de `curso/módulo/aula`. O Python gravou o arquivo, mas o Obsidian (Chromium) não o abre, e o card da Base ficou sem
  capa. Agora:
  - `area.MAX = 250`;
  - curso, módulo e tema com até 32 caracteres;
  - a pasta da aula encurta pelo maior arquivo que vai morar nela;
  - imagem que mesmo assim não cabe ganha um nome curto (`começo do nome + código da aula`), registrado em
    `obsidian.renamed`, que o reprocessamento respeita;
  - imagem nova numa pasta funda também encurta;
  - renomear um curso que empurraria algum arquivo além do limite é recusado.
- **Base e Home.**
  - **`Estudos.base`**, 10 visões: Biblioteca (cards), Para revisar, Continuar estudando, Recentes (cards), Cursos
    (agrupado por curso), Conteúdo gratuito e Aulas avulsas (agrupados por tema), A organizar, Gerados pelo Lumen e
    Todos.
  - **Fórmulas** `onde` (curso › módulo, tema ou A organizar) e `tipo` (em português), conferidas no Obsidian 1.14.5:
    os cards mostram título, onde e próxima revisão, sem campos vazios.
  - **Capa** em 16:9: a imagem principal do painel ou a primeira tela. Sem imagem, o card fica só com o texto. Uma
    capa que aponta para arquivo inexistente é trocada (ou sai), e a escolhida pelo usuário fica.
  - **O `.base` só é regravado se ainda for o que o Lumen gravou** (hash no catálogo): o Obsidian regrava o arquivo
    quando o usuário ajusta uma visão.
  - **`00 - Estudos.md`** embute as visões (`![[Estudos.base#Para revisar]]`) e lista cursos e temas com links. Sem
    Bases, os links e as pastas continuam servindo.
  - **A página de cada curso** (`00 - <Curso>.md`, `type: course`) tem bloco do Lumen (acesso, progresso real, módulos
    com as aulas em ordem, Para revisar filtrado por `course-id`) e as seções Sobre, Materiais relacionados e Notas
    permanentes geradas, que são do usuário.
- **Notion pela mesma classificação** (`jobs._notion_parent`):
  - curso → página do curso dentro da raiz (adota uma filha de mesmo nome só se houver exatamente uma) e módulo dentro
    dela;
  - conteúdo gratuito → uma página por material em `notion_free_page_id`, como o usuário já fazia (o tema não vira
    nível no Notion);
  - aula avulsa → “Sem curso”;
  - A organizar → onde a aula já está.

  **Mover usa o mecanismo de “refazer em outra página”:** republica o pacote na página nova e só depois apaga os
  `block_ids` antigos. A página criada só para o material vai para a lixeira se ficar vazia. As telas que já saíram
  do PC são lidas dos anexos do cofre (`obsidian.images`). Um `course_id` sem classificação (Tentar de novo de aula
  antiga) ainda vale.
- **Migração** (`area.plan`, `area.migrate`):
  - acha as notas `ai-study` com `lumen-id` na pasta antiga e os arquivos de cada aula (manifesto, ids estáveis dos
    Canvas, embeds);
  - zip da pasta antiga, diário em `DATA/migration.json` (desfeito na próxima vez se o Lumen fechar no meio) e moves para
    `90 - A organizar` sem renomear;
  - Canvas reescritos, depois reprocessamento sem IA das aulas com pacote;
  - o `Lumen Dashboard` sai se ninguém escreveu nele nem o linka. Senão vira um aviso para `[[00 - Estudos]]`. No cofre
    real, a D010 e uma sugestão o linkavam: apagá-lo quebraria esses links;
  - rodar de novo não faz nada, nem novo zip. Um zip nunca sobrescreve outro (achado ao repetir a migração real no
    mesmo segundo).
- **Interface.**
  - **Nova aula:** card Organização (tipo, trilha, Alterar, sugestão com “Usar”) acima de Destinos do estudo, que agora
    mostra o caminho em cada destino e “Nota + 2 Canvas”.
  - **Diálogo “Organizar estudo”:** tipo, curso (com os do Notion para adotar), módulo, número da aula e tema. Criar
    curso pede nome e plataforma; criar módulo, nome e ordem.
  - **Removido:** o seletor livre de páginas do Notion (busca, navegação, nova subpágina com prévia de capa). “Enfeitar
    no Notion” virou opção do novo curso.
  - **Biblioteca:** vistas, Filtros recolhidos, cards de curso e a visão do curso com módulos e progresso real, trilha e
    Organizar em cada aula. Aulas antigas mostram em que página do Notion estão.
- **Testes reais:**
  - migração no cofre do usuário: nenhum arquivo perdido (hash a hash), Canvas válidos e `vault-check` OK;
  - Obsidian 1.14.5 isolado numa cópia: Home, as 10 visões, página do curso, aula, Mapa e Painel depois de migrar e
    mover;
  - auditoria pela API do Lumen aberto, com o Notion e o Ollama reais: curso, módulo, aula, compreensão, material,
    Notion e Obsidian no lugar certo, organizar para conteúdo gratuito (nos dois destinos) e tentar de novo depois de
    mover (sem duplicar). Depois apagada (Notion na lixeira).
- **Bugs que os testes reais acharam e foram corrigidos:**
  - reorganizar uma aula sem o registro de “Minha compreensão” no PC derrubava a tarefa (`understanding.synced`);
  - caminhos acima de 260;
  - zip de migração sobrescrito na repetição;
  - painel antigo apagado com links para ele;
  - link do Notion desatualizado dentro do bloco da nota depois de mover (saiu do bloco; fica na propriedade
    `notion`);
  - página de conteúdo gratuito em branco em Integrações enquanto a lista do Notion carrega;
  - Path do Windows comparando sem maiúsculas: renomear só a caixa de um curso era ignorado.
- **Não feito:**
  - “99 - Arquivados”: o cofre já tem convenção de arquivo;
  - renomear as notas antigas para tirar a data: o nome antigo continua valendo e os links não quebram;
  - módulos e temas no Notion de conteúdo gratuito;
  - tela de detalhe da aula: a trilha fica na linha da Biblioteca e na visão do curso.

## Lumen Graph Identity: estudos em azul, Canvas em violeta no Graph View (26/10/2026; `lumen/graph.py`)
- **Pedido do usuário:** reconhecer de relance, no Graph View do Obsidian, tudo o que é estudo do Lumen, sem
  reorganizar a área, sem cor escrita em cada nota, sem CSS e sem plugin.
- **Identificação semântica, não por pasta.** A consulta é `[type:ai-study] OR [type:course]`: as aulas (os quatro
  tipos de estudo) e as páginas de curso já têm essas propriedades. Não entrou propriedade nova nem tag, e nenhuma nota
  antiga precisou de migração, porque todas já tinham `type: ai-study`. `path:` foi descartado: uma aula movida ou
  renomeada pelo usuário perderia a cor, e a central `00 - Estudos`, a `Estudos.base` e os Canvas ficariam azuis.
  Ficam de fora, de propósito: anexos, Canvas, a central (`type: system`) e as notas do usuário.
- **Cor:** `#5B8CFF` ("Lumen Study Blue"), numa constante única (`graph.STUDY_COLOR`). `STUDY_QUERY` fica ao lado: um
  grupo futuro (projetos, livros…) entra como outra consulta e outra cor, sem mudar o resto.
- **Um Color Group nativo** em `.obsidian/graph.json` (`{"query", "color": {"a": 1, "rgb"}}`). O Obsidian não tem nome
  de grupo: quem identifica o grupo é a consulta.
- **Regras de escrita:**
  - criado só se nenhum grupo tiver a consulta de estudos: a cor que o usuário escolher fica;
  - entra em primeiro, porque o Obsidian pinta com o primeiro grupo que casa;
  - o resto do arquivo não muda (forças, filtros, órfãos, tamanho, setas, outros grupos);
  - JSON inválido (ou `colorGroups` que não é lista) nunca é sobrescrito;
  - com o Obsidian aberto, espera: ele guarda as opções do Graph na memória e regravaria o arquivo. Na abertura do
    Lumen, tenta de novo a cada 5 minutos até o Obsidian fechar; cada entrega também tenta;
  - backup único `graph.json.lumen-backup` antes da primeira mudança; escrita atômica (`.graph.json.lumen-tmp` +
    `os.replace`); se o arquivo mudou entre a leitura e a escrita, não escreve.
- **Uma vez por cofre.** O catálogo guarda `meta.graph_installed`. Depois disso, a entrega de uma aula nova não lê nem
  escreve o `graph.json`. Se o usuário apagar o grupo, ele não volta.
- **Testes:**
  - unitários (`tests/test_graph.py`): arquivo ausente, vazio e sem `.obsidian`; grupo ausente, existente e com cor do
    usuário; outros grupos preservados; JSON inválido; 100 execuções seguidas; Obsidian aberto; entrega que instala
    uma vez só;
  - visuais, no Obsidian 1.14 isolado numa cópia do cofre:
    - as aulas antigas, as dos quatro tipos e uma página de curso em azul;
    - uma aula renomeada e movida de "A organizar" para um curso continua azul;
    - uma nota de projeto que linka estudos fica com o grupo do projeto, e um recurso fica com a cor padrão;
    - um grupo genérico `path:"B02 Estudos"` depois do nosso não repinta as aulas;
    - a cor trocada dentro do Obsidian sobrevive a uma nova execução do Lumen;
    - três aulas novas entregues pelo `obsidian.deliver` nascem azuis.

### Canvas dos estudos em violeta (26/10/2026; `lumen/graph.py`)
- **Pedido do usuário:** uma segunda identidade no Graph View: notas de estudo em azul, Canvas dos estudos em violeta,
  sem pintar Canvas manuais fora da área e sem trocar o azul.
- **Estado anterior:** os Canvas já apareciam no gráfico (o Obsidian 1.14 mostra `.canvas` mesmo com `showAttachments:
  false`), na cor padrão, porque a consulta dos estudos só casa `.md` com `type`.
- **Consulta:** `path:/^<área>\// file:/\.canvas$/` (no cofre do usuário, `path:/^B02 Estudos\// file:/\.canvas$/`),
  conferida no Graph View real numa cópia do cofre com Canvas-armadilha:

  | Consulta | Resultado |
  |---|---|
  | `file:.canvas` | pega o Canvas de Projetos, o do arquivo e a nota `Ideias.canvas.md` |
  | `path:"B02 Estudos" file:.canvas` | pega `B04 Archives/B02 Estudos antigo/Velho.canvas` (`path:` casa trecho) e `Ideias.canvas.md` |
  | `path:"B02 Estudos/" file:.canvas` | ainda pega `Ideias.canvas.md` |
  | `path:/^B02 Estudos\// file:/\.canvas$/` | só os 12 Canvas da área, inclusive um Canvas manual na pasta de uma aula |

  O nome da área passa por escape de regex (`Estudos (2026)` vira `Estudos \(2026\)`, também conferido no Obsidian).
- **Por lugar, não por nome nem por manifesto.** Canvas é JSON Canvas, sem frontmatter, e nada foi escrito nele. O nome
  (`Mapa - `, `Painel - `) deixaria de fora um Canvas futuro de outro tipo, e uma lista do manifesto teria de ser
  regravada no graph.json a cada aula. A área é do Lumen, e o usuário pediu que um Canvas dele dentro da pasta de uma
  aula também conte.
- **Cor:** `#A78BFA` ("Lumen Canvas Purple", `graph.CANVAS_COLOR`). No fundo escuro do Obsidian, ao lado do
  `#5B8CFF`, distingue-se de relance, inclusive em nós vizinhos; não foi ajustada.
- **Prioridade:** as duas consultas não se cruzam (uma só casa `.md` com `type`, a outra só `.canvas`); as duas entram
  antes dos grupos do usuário. Ordem na instalação: Canvas, Estudos, depois os do usuário.
- **Instalação por grupo:** `meta.graph_installed` guarda `cofre|grupo`. A marca antiga (só o cofre) vale como
  "estudos instalado": no cofre do usuário entra só o grupo violeta, e o azul (ou a ausência dele, se o usuário o
  apagou) fica como está.
- **Gráfico local:** guarda grupos próprios em cada aba (`workspace.json`) e não lê o `graph.json`. Ficou como está;
  o README explica como repetir as consultas lá.
- **Testes reais** (Obsidian 1.14 isolado, cópia do cofre, conferência de cada nó do gráfico):
  - 108 nós: 11 notas de estudo azuis, 17 Canvas violeta e nenhum nó com a cor errada;
  - aulas novas de curso com módulo, curso sem módulo, gratuito, avulsa e A organizar;
  - uma aula movida de A organizar para curso e módulo (`area.relocate`) e uma renomeada dentro do Obsidian;
  - a cor trocada para `#C084FC` no Obsidian sobreviveu a 50 execuções do Lumen (graph.json idêntico byte a byte).

## Gemini Notebook (26/10/2026; `lumen/notebook.py`, `lumen/gdrive.py`)

> **Histórico — superado em 09/11/2026.** A integração com o Gemini foi retirada do Lúmen (relatório: `docs/implementation/LUMEN_REMOCAO_GEMINI_20261109.md`). O texto abaixo registra o que foi decidido e medido na época; não descreve o código de hoje.

Pedido do usuário: levar as fontes de uma aula ao Gemini Notebook (antigo NotebookLM), vincular aulas, cursos e módulos a
cadernos, oferecer pedidos de estudo e trazer de volta o que ele exportar de lá, sem tirar do Lumen o funcionamento
local. Documentação revalidada nesta data: o anúncio do nome (blog.google, 16/07/2026), fontes e limites
(support.google.com/gemininotebook/answer/16215270), API Enterprise de cadernos, fontes e Audio Overview
(docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise), OAuth de app para computador
(developers.google.com/identity/protocols/oauth2/native-app), escopos do Drive, envio e conversão
(developers.google.com/workspace/drive/api), sincronização de Docs no NotebookLM (Workspace Updates, 26/05/2026),
segurança do WebView2 (learn.microsoft.com) e os termos da Gemini API (ai.google.dev/gemini-api/terms).

- **O que existe para a conta pessoal:** nenhuma API de cadernos. Fontes aceitas incluem `.md` e `.txt` (e Google Docs
  do Drive), até 500 mil palavras ou 200 MB por fonte e 50 fontes por caderno no plano gratuito. Por isso o caminho é
  arquivo preparado pelo Lumen + importação pelo usuário, com a confirmação registrada como **manual**. Não há endpoint
  privado, cookie, biblioteca de engenharia reversa nem automação de cliques.
- **Host:** `notebooklm.google.com/notebook/<id>` responde **301** para `notebook.google.com/notebook/<id>` com o mesmo
  caminho e o `authuser` (conferido com `curl`, sem login, com um id inexistente). Os dois hosts são aceitos por
  igualdade exata do hostname (`urlsplit`), só `https`, sem porta e sem usuário/senha, só o caminho `/notebook/<id>`; da
  consulta fica só `authuser`. O endereço guardado é o novo. O caderno é identificado pelo id do endereço, nunca pelo
  título: vincular de novo o mesmo caderno só troca o nome.
- **Destinos sem mudança:** o contrato `notion|obsidian|both` tem ~40 consumidores, e `jobs._destinations` trata
  qualquer valor desconhecido como “both”. O Notebook virou uma ação da aula (não um destino), que nunca chama
  `_destinations`: funciona sem Notion e sem cofre. Consequência aceita: o material de estudo só existe para levar
  depois de a aula ser salva num destino (é lá que a IA o escreve); a transcrição, a nota e a análise vão antes.
- **Trava (no servidor, em toda rota da aula):** `notebook._gate` exige nota enviada e analisada (a mesma regra de
  salvar), recusa durante uma análise e depois de “Estudar de novo”. Da nota só saem `original_understanding` e
  `analyzed_text`, literais; um rascunho editado depois da análise nunca sai (testado).
- **Transcrição:** lida de `work/<h>/transcript.json` (o pacote não a tem), com os parágrafos de `llm.transcript_text`:
  `[mm:ss]` é o início real do 1º trecho de cada parágrafo de ~30 s, e trechos sem tempo (legenda colada, capturas)
  ficam sem marcador. Quando a pasta foi apagada (`jobs.finish` guarda só a da última aula publicada), o item fica
  indisponível com o motivo; nenhuma persistência nova foi criada para ela.
- **Versões:** `sel` = sha256 dos nomes + conteúdos (sem número de versão nem data). A mesma seleção com o mesmo
  conteúdo devolve a versão que já existe (clique duplo, repetição, reinício); outra cria `vN+1` numa pasta nova, com
  escrita atômica e nomes de `obsidian.clean` conferidos dentro da pasta. O manifesto (nomes, itens, tamanhos, hashes)
  fica em `DATA/notebook/state.json`; os vínculos, em `DATA/notebook.json` (como o catálogo, “Limpar” não os apaga).
- **Google Drive (o “API gratuita” do usuário é um projeto Google Cloud comum):** a sincronização automática de Google
  Docs do Drive no NotebookLM (maio/2026) torna o Drive o único caminho oficial e verificável para a conta pessoal.
  - Escopo só `drive.file` (não sensível; o app vê apenas os arquivos que criou). OAuth de app para computador:
    navegador do sistema, loopback `127.0.0.1` em porta livre que aceita só o pedido com o `state` certo, PKCE S256,
    `access_type=offline`. O JSON do cliente é lido no servidor (o caminho nunca vem da interface); os endereços dele
    são ignorados. `client_id`, `client_secret` (não é segredo num app para computador, mas fica junto) e o refresh
    token vão para o keyring (“Lumen”/“google-drive”); `config.json` não muda.
  - Um Doc por item e aula, marcado com `appProperties lumen=<lumen_id>.<item>[.<parte>]`. A marca não muda entre
    versões: versão nova = `PATCH` no mesmo Doc (o caderno sincroniza). Conteúdo igual não é reenviado.
  - **Sem repetição cega:** antes de criar, procura pela marca; uma criação sem resposta (timeout, 5xx, queda do app
    com `sending` gravado) é procurada de novo e, se não aparecer, fica **resultado não confirmado** até um novo clique
    ou **Conferir no Drive**. Só `GET`/`list`/`PATCH` repetem em 5xx; 429 e 403 de limite esperam o `Retry-After`
    (teto de 30 s, 3 tentativas). 401 renova o token uma vez; `invalid_grant` apaga o refresh token e pede novo login
    (em modo *Testing* o Google o expira em 7 dias).
  - O estado “verificado” é o do Drive (id e data devolvidos pela API). Que o caderno recebeu, só o usuário confirma.
  - Testado com um Google falso (`tests/fake_google.py`: PKCE, token, multipart, falhas injetadas e uma criação que grava
    e responde depois do timeout). **Não foi validado com o Google real**: depende do cliente OAuth e do login do
    usuário.
- **Navegador incorporado: não.** Prova isolada (WebView2 155, perfil próprio em pasta temporária, host objects e
  mensagens desligados, permissões negadas, downloads cancelados): `notebooklm.google.com` → `notebook.google.com/trynow`
  (página pública “Gemini Notebook”), 6 processos e 359 MB com `--disable-gpu` (384 MB sem), 2–2,5 s de CPU na carga,
  todos encerrados 4 s depois de fechar. O login não foi tentado: o Google bloqueia login de conta em frameworks
  incorporados desde 2021 (`disallowed_useragent`, “este navegador ou app pode não ser seguro”) e a sessão do navegador
  do usuário não passa para o WebView2. Abrir no navegador padrão já leva à conta logada, sem 360 MB a mais nem uma
  superfície nova a proteger. Nada mudou no `launcher/`.
- **Enterprise (não implementado, sem acesso):** Discovery Engine `v1alpha` (prévia): `notebooks` create/get,
  `notebooks:listRecentlyViewed` (até os 500 vistos recentemente pelo usuário, não a lista completa),
  `notebooks:batchDelete`, `:share`; fontes `sources:batchCreate` (texto, web, vídeo, Drive) e `sources:uploadFile`;
  `audioOverviews.create` (um por caderno, assíncrono, sem endpoint de status nem de download: conferir no Studio).
  Autenticação Bearer; a documentação não lista os papéis do chamador. Fica para quando houver licença e projeto.
- **Gemini API: não usada.** Não acessa cadernos nem o Drive; a exportação e os pedidos saem do que a aula já tem; e o
  nível gratuito permite usar o conteúdo enviado para melhorar produtos, com revisão humana (os termos pedem para não
  enviar dados pessoais), o que contraria a IA local do Lumen.
- **Interface:** cartão em Integrações (selo “Pelo navegador” ou “Drive conectado”, nunca “conectado ao caderno”) e o
  diálogo da aula (Fontes, Pedidos de estudo, Do caderno), com uma ação principal por estado. A barra flutuante não mudou:
  o rail já está cheio em 252 px, a ação acontece depois da análise (não durante a gravação ou a escrita) e não há
  ajuste essencial do Notebook para levar a ela. As abas da fonte usavam `$$("[role=tab]")` global; agora o seletor é
  `.src-tabs [role=tab]`, para não pegarem as abas do diálogo.
- **Achado fora do escopo (não alterado):** `jobs.finish` escreve o material com `current_understanding`, que pode ser
  uma edição feita depois da análise e ainda não analisada. A interface leva a “Analisar de novo”, mas o servidor não
  exige. A exportação do Notebook não depende disso (usa a original e a analisada).
- **Limites:** o envio ao Notion/Obsidian do que voltou do caderno não foi feito (próxima etapa, pedida como ação
  explícita); áudio importado abre no player do Windows (o app não tem player); imagens só vão pelos arquivos (não pelo
  Drive); a confirmação de que o caderno recebeu é sempre do usuário.

### Capa no Notion recuperada (26/10/2026; `lumen/server.py`, `lumen/notion.py`, `web/app.js`, `tests/test_covers.py`)

- **Causa da perda:** o commit `6c7bdfa` (Estudos: organização) removeu o seletor livre de páginas, e com ele a
  prévia da capa (`/api/decor/preview`, “Gerar capa”/“Gerar outra”). Ficou só “Enfeitar a página no Notion” no novo
  curso, que gerava a capa na hora de criar, sem mostrar nada, por `_notion_course` — que também jogava fora o
  `cover_note` (falha do upload sumia) e não aceitava `preview_id`.
- **Agora:** “Capa no Notion” no formulário Novo curso: Gerar prévia (local), Gerar outra, título e destino visíveis, e
  “Criar curso com a capa” manda o `preview_id`. O servidor confere a prévia antes de criar qualquer coisa (expirada
  em 1 h, desconhecida ou de outro nome: recusa, nunca troca por outra imagem) e publica os mesmos bytes. Uma prévia
  por vez (`_preview_busy`, além do lock do gerador). Página de mesmo nome já existente: adotada como está, sem capa.
- **Notion:** o upload só é anexado com `status: uploaded`; depois de criar, `GET /pages/{id}` confere que a capa é
  um arquivo (`file`/`file_upload`), não só a resposta 200. `POST /pages` sem resposta não é repetido às cegas
  (`notion.Unconfirmed`, `request(once=True)`): procura a página nova de mesmo título e adota, ou avisa para conferir.
  Vale também para as páginas criadas pelas aulas (`jobs`), que usam `create_course`.
- **Rótulos honestos:** `ia` (ilustração com IA local), `emojis` (alternativa) e `notion` (nenhum desenho saiu: capa
  de cor do Notion). Neste PC o desenho com emojis (`cover.render`, `--screenshot` do Edge) não funciona no Edge 155
  (a mesma causa das 3 falhas antigas de gráficos e mapa mental); por isso o terceiro estado existe e é dito.
- **Medido de verdade:** geração real pela rota da prévia, RTX 3060, PNG 1536 × 640: 76 s (fria) e 73 s no WebView2
  real (`Lumen.CoverCheck`, instância isolada), sem nenhum pedido ao Notion. A interface mostra o tempo medido da prévia,
  não um número de benchmark. A publicação real ficou pendente (sem página de teste autorizada).

### Integrações em abas e o diálogo refinado (26/10/2026; `lumen/web/index.html`, `app.js`, `app.css`)

- **Por que a tela mudou:** `.integ-grid` punha Notion e Obsidian lado a lado com `align-items: start`; a linha tinha a
  altura do Obsidian (o cartão maior), o Notion deixava um vão embaixo e o Gemini Notebook caía sozinho na linha de
  baixo. Agora a página é uma coluna (até 920 px): destinos do material, uma faixa com as três integrações (abas com
  nome, ícone e estado) e o painel da escolhida. Cada formulário continua existindo uma vez só; a aba só mostra ou
  oculta o painel. Nada de altura fixa, margem negativa ou posição absoluta.
- **Destinos x Notebook:** o cartão dos destinos diz que o Gemini Notebook não é um destino (o contrato
  `notion|obsidian|both` não mudou). Integração fora dos destinos não fica mais apagada (opacidade baixava o contraste):
  um aviso em palavras com “Usar Notion e Obsidian”.
- **Defeitos corrigidos:** o “Vincular um caderno” reabria a cada 2 s durante o login do Google (o redesenho forçava
  `open`); o formulário “Vincular outro caderno” do diálogo era apagado ao marcar uma fonte; o texto colado em “Do
  caderno” se perdia num redesenho; avisos ficavam atrás do fundo escurecido de um diálogo modal (inerte); a resposta
  atrasada de uma aula podia preencher o diálogo de outra; os botões do rodapé eram trocados com o foco neles (o foco
  ia para a página); fechar o diálogo na Biblioteca redesenhava a lista e o foco se perdia; o diálogo travado ocupava a
  altura toda (`height: auto` num `<dialog>` fixo estica; o padrão dele é `fit-content`).
- **Única mudança de contrato (backend):** `gdrive.status()` ganhou `expired` (o Google recusou a renovação:
  `invalid_grant`, 7 dias em modo Testing ou acesso removido). Fica no keyring junto das credenciais e sai ao entrar de
  novo ou trocar o cliente; sem ele a interface não distinguia “acesso expirado ou revogado” de “falta entrar”. Campo
  novo, os outros iguais (testado em `tests/test_notebook.py`).
- **Ícones:** “Abrir no Obsidian” usa a gema do Obsidian em todo lugar (como na Nova aula); o livro é só do Gemini
  Notebook. Na Biblioteca, Notion, Obsidian e Notebook têm o mesmo formato (ícone + nome); o mapa e o painel ficam só
  com o ícone (com dica e rótulo para leitor de tela).

## Revisões espaçadas opcionais (27/10/2026; `lumen/obsidian.py`, `lumen/area.py`, `lumen/store.py`)

- **Uma preferência só:** `obsidian_review` (já existia) decide tudo o que é da agenda: a seção “Revisões” e as caixas
  `Revisão N · data`, `review-stage`/`next-review`, a frase de revisões em “Como usar esta nota”, o `sync_reviews` da
  abertura e de cada entrega, `due_reviews` (Início), a vista “Para revisar” e o filtro “Revisão” da Biblioteca (o
  `/api/history` não manda `next`/`stage` com ela desligada) e, no cofre, “Para revisar hoje”/“Continuar estudando” da
  Home, “Para revisar” e “· N para revisar hoje” da nota do curso e as colunas e visões de revisão de `Estudos.base`.
  Status `review-required` (conferir o material da IA), perguntas, flashcards e “Possíveis notas permanentes” não são
  revisão espaçada e não dependem dela.
- **Padrão desligado.** `store.DEFAULTS` passou a `False`: instalação nova e config sem a chave começam sem revisões.
  Um valor salvo vale como está (`{**DEFAULTS, **salvo}`; nenhum `or True`); como `save_config` grava todas as chaves,
  quem já usava o Lumen continua com o que tinha.
- **Desligar não mexe no cofre.** Nenhuma alteração em massa: vale para notas novas e para as que forem salvas de novo.
  Numa atualização com revisões desligadas, só o que é do Lumen sai: a seção (dentro do bloco gerenciado), as duas
  chaves de agenda (entram em `owned` com valor vazio → `merge_fields` as remove) e a frase em “Como usar” (troca do
  callout inteiro só se for o texto exato do Lumen; editado pelo usuário, fica). Revisões escritas fora do bloco,
  propriedades e anotações ficam; a versão anterior vai para `obsidian-backups`. Bloco editado à mão continua sendo
  conflito.
- **Ligar de novo** dá um checklist novo, uma vez, sem caixas marcadas (nada de histórico inventado), com as datas
  contadas da data do estudo como sempre. Com revisões ligadas, a proteção antiga fica: `review-stage`/`next-review`
  já existentes não são sobrescritos ao reprocessar (o `sync_reviews` é o dono deles).
- **Pacote em cache:** `review_dates` do StudyPackage não é usado na entrega; as datas saem de `cfg` na hora
  (`obsidian.deliver`). Um pacote preparado com revisões e salvo com elas desligadas sai sem a seção.
- **Ligadas, nada muda:** `base_text`, a Home, a nota do curso e os callouts saem byte a byte iguais aos de antes
  (conferido), então nenhum cofre é regravado por causa desta mudança.
- **Validação real:** instância isolada + cofre temporário + dois pacotes reais (com `review_dates`) pelo “Salvar no
  Obsidian”: desligada, nota sem seção, datas, chaves nem instrução e material completo; ligada, checklist, marcar a
  Revisão 1 → `review-stage: 1`, próxima data certa, atualizar duas vezes sem duplicar nem desmarcar; desligar e
  atualizar → o diff da nota é só as duas chaves, a frase do “Como usar”, a seção e o hash. Conferido também no
  Obsidian real (perfil isolado, modo leitura, sem links quebrados) e na interface real (headless Edge pelo CDP).

## Visualização 3D (27/10/2026; `lumen/visual3d.py`, `jobs.py`, `notion.py`, `obsidian.py`)

- **Renderer escolhido pela menor complexidade que atingiu a qualidade, com prova.** Ambiente conferido antes: i5-11400F,
  RTX 3060 (10,8 GB livres), NumPy 2.5 e PyAV 16.1 no `.venv`, Blender ausente (procurado em `Program Files`, `D:\`,
  `%LOCALAPPDATA%`, `%APPDATA%`, Downloads e no registro), Edge 155 com `--screenshot` quebrado (ver a nota dos
  gráficos). Por isso nem o caminho do Edge (o dos gráficos) nem um motor completo: um renderizador próprio, pequeno, em
  NumPy + **Pillow** (desenho e texto), na CPU, dentro do processo. O Blender ficou para “necessidade demonstrada”, que
  não apareceu: a cena tem perspectiva real, órbita de câmera com paralaxe, oclusão (ordem de profundidade por objeto
  convexo; faces translúcidas escurecem o que fica atrás), faces de trás e arestas escondidas apagadas, borda mais clara
  quando a face é vista de lado, brilho por desfoque, chão em grade que some na distância e varredura. Não há processo
  externo para encerrar (o limite de tempo é cooperativo, quadro a quadro).
- **Pillow 12.3.0** (MIT-CMU), instalado só no `.venv` a partir do wheel oficial do PyPI
  (`pillow-12.3.0-cp314-cp314-win_amd64.whl`, 7.237.707 bytes, SHA-256 `fdafc9cc…14048d` conferido com o do PyPI;
  ≈ 16 MB em `.venv\Lib\site-packages\PIL`). A 13.0.0 tinha 11 dias: ficou a última da linha anterior, de 01/07/2026.
  Ele lê a Inter do projeto (`web/fonts/*.woff2`, OFL, variável no peso); para caracteres que ela não tem (→, Ω, ≤),
  a Segoe UI do Windows. `Iniciar Lumen.bat` instala o Pillow numa instalação antiga que não o tenha; sem ele, a aula
  sai sem a visualização e o resultado diz o motivo.
- **Fluxo e limites.** `spec(pkg)` monta, sem IA, um objeto pequeno (família, conceito, título, até 7 elementos com
  rótulos de até 52 caracteres, até 12 ligações por índice, as origens no material como `steps[2]`,
  `mind_map.branches[1]`, `relations[0]`) e `validate` recusa qualquer campo a mais, tipo errado (bool não vale como
  número, NaN não passa), índice fora, relação fora da lista do pacote, rótulo com controle ou longo e origem que não
  seja um destes caminhos. A cena só lê rótulos e índices: nada da aula ou da IA vira código, caminho ou shader.
  Família: `contrasta com` entre ideias principais → comparação; `map_kind` tutorial com 3+ passos → processo; sistema →
  sistema; livro (ou 2+ “parte de”) → estrutura; 3+ passos → processo; o resto → conceitos. Relações que a aula não
  afirma não viram seta: a ligação de cada ramo ao centro vem do próprio mapa (tracejada, sem pulso, sem rótulo).
- **Arquivo e orçamento.** 960 × 540, 48 quadros a 12 fps (4,0 s), laço contínuo (todo movimento é periódico no laço:
  giros por múltiplos da simetria de cada forma, pulsos e anel tracejado), paleta de **128 cores** (comparada a 256 num
  recorte ampliado: igual a olho nu e ≈ 22% menor; a 96 cores é o segundo passo). Acima de 4,5 MB: 36 quadros, depois
  800 × 450, depois PNG. Orçamento de tempo de 45 s (medido nos 4 primeiros quadros: se o ritmo passar, vai o PNG) e
  limite de 120 s. Antes de entregar, `inspect` confere assinatura, decodificação (PyAV), tamanho, quadros, atrasos,
  repetição (NETSCAPE 0), movimento (quadros vizinhos diferentes e o do meio longe do primeiro), imagem não vazia e
  peso; o PNG, assinatura, IHDR, decodificação e peso (até 1,5 MB; estático típico ≈ 200 KB).
- **Medido (RAG, sistema, 5 componentes e 3 relações):** 5,4 s de CPU de ponta a ponta (sem GPU: uso e memória da RTX
  iguais durante o desenho), pico do processo 312 MB (59 MB antes), GIF 2,91 MB, PNG 216 KB; as sete amostras de
  bancada (processo, sistema, conceitos, estrutura, comparação, um conceito só, rótulos com Ω e →) ficaram entre 2,9 e
  4,1 MB a 256 cores e 7–9 s com medição de memória ligada. Uma renderização por vez (`_LOCK`); a IA local não precisa
  ser descarregada (o desenho não usa VRAM).
- **Uma vez, dois destinos.** `jobs._visual` chama `visual3d.prepare` uma vez por entrega; o arquivo fica em
  `DATA/visuals/<lumen_id>/<hash>.{gif,png,json}` (um por aula: o anterior sai), e o mesmo vale para Notion e Obsidian.
  Tentar de novo um envio, Organizar, Atualizar e reabrir o app reaproveitam o arquivo (o cache passa pela mesma
  conferência; estragado, é desenhado de novo). O manifesto (`history.json`) guarda o registro mínimo: hash da spec,
  versão do renderer (`holo-1`), modo, família, origens, arquivo, tamanho, quadros, duração, bytes e estado; nada de
  base64 no pacote nem no histórico. Pacotes antigos funcionam (a spec sai deles na hora; sem mapa, os tópicos).
- **Notion.** Envio oficial (`file_uploads`, MIME `image/gif`/`image/png`, só anexado com `status: uploaded`) e bloco
  nativo `image` só com tipo, envio e legenda, logo depois do callout “Ideia central”. Depois de publicar,
  `media_is` lê o bloco e baixa a URL temporária (sem o token) para comparar os bytes: `confirmed`, `mismatch` ou
  `unconfirmed`. GIF que não sobe → o PNG de reserva (o mesmo desenho). Antes de publicar, o estado vira `pending`; se a
  publicação ficar sem resposta (o Notion pode ter gravado), a próxima tentativa procura, na página, imagens com a marca
  desta aula na legenda (`ref. <8 do lumen_id>`) que não estejam nos blocos registrados nem na lista de visuais
  confirmados (cópias pedidas pelo usuário) e as tira antes de publicar de novo. Limite conhecido, de antes: o texto
  de um lote sem resposta não tem marca e continua sendo conferido pelo usuário (a mensagem já pede isso).
- **Obsidian.** Anexo da aula (`Anexos/visualização 3d · <aula>.gif`) no mesmo manifesto de propriedade (`files`) das
  telas e gráficos, embutido com `![[…]]` logo depois da ideia central e com a legenda em itálico. Nome estável
  (reprocessar não duplica); um arquivo com esse nome que o Lumen não gravou (tamanho diferente do manifesto) não é
  sobrescrito: o visual ganha outro nome. Caminho dentro de `area.MAX`. A limpeza (`_tidy`) agora também confere se o
  anexo é citado em alguma nota, Canvas ou Base do cofre antes de apagar: vale para telas e gráficos também. Migração
  (sem o desenho em mãos) mantém o visual que já está. Não entra no painel visual (`board`), na capa, no mapa nem no
  Gemini Notebook. Depende de “Telas e gráficos no cofre” (um cofre sem imagens fica sem imagens).
- **Primeiro marco, real (27/10/2026).** Página de teste nova no Notion real (filha da raiz configurada, “Lumen · teste
  da Visualização 3D (pode apagar)”): blocos `image`/`file`, bytes baixados idênticos aos enviados (GIF 2.913.648, PNG
  215.679), envio do GIF 1,9 s. Reaberta no Notion desktop (CDP, só a área do conteúdo): o GIF anima (diferença média
  9,9 e 11,1 entre capturas na área da imagem; 0,00 no texto) e ocupa a coluna em todas as larguras, sem rolagem
  horizontal (`scrollWidth = clientWidth`). Obsidian real num cofre isolado novo, perfil separado e **sem internet**
  (proxy para uma porta fechada; `fetch` externo falha): anexos locais carregados, nenhum link sem destino, animando
  (10,3), 700 × 394 na largura de leitura e 504 × 284 com 640 px de janela, sem cortes.
- **Interface:** Integrações → Destinos do material → **Visualização 3D** (Animada, Estática, Desligada; detalhes
  técnicos recolhidos). O resultado do processamento mostra a mesma imagem (`/api/visual`), com o PNG quando o sistema
  pede menos movimento (`<picture>` + `prefers-reduced-motion`); a preferência do sistema não muda o GIF exportado, por
  isso o modo Estática publica PNG de verdade.

## Conversa rápida na barra flutuante (09/11/2026; `lumen/web/chat.js`, `launcher/WidgetForm.cs`, `launcher/Lumen.cs`)

- **O que é:** um painel de chat dentro da barra (ícone de balão entre Gravar e Ajustes) que usa o MESMO agente, as mesmas rotas e a mesma conversa do Cérebro; "Abrir no Cérebro" abre o
  mesmo identificador. Sem servidor, banco ou processo novos. Decisões D127–D134 em `docs/implementation/LUMEN_STUDY_AI_DECISIONS.md`; relatório e provas em
  `docs/implementation/LUMEN_CONVERSA_RAPIDA_20261109.md`.
- **Janela nativa (corrigido em 09/11, 2ª versão):** a conversa abre na janela COMPACTA de sempre (`WidgetForm.ChatPanel = MainPanel`, 304 × 252: a barra não cresce); "Ampliar" pede `ChatWide`
  360 × 540 (`widget:panel:chat-wide`, só na sessão). A 1ª versão (420 × 620 + `--chat-w/--chat-h`) cortava a conversa quando o `Lumen.exe` em uso não conhecia o pedido de tamanho. Agora o `.notch` da
  conversa é `100vw × 100vh` (a página acompanha a janela, nunca o contrário) e a animação é a existente (`Approach`), interrompida continua do tamanho atual (maior passo ≤ 50% do percurso, sem
  recuo). `chat:open[:id]` é validada no `Lumen.exe` (`^(tmp-)?[A-Za-z0-9_-]{1,64}$`) e de novo no `app.js`. Decisões D135–D140.
- **Foco:** abrir por hover continua sem ativar a janela; o clique ativa e o campo recebe o foco. Com a conversa aberta e o foco na barra o mouse sair não recolhe; perder o foco recolhe. Esc: menu, depois recolher.
- **Sem GPU global, sem blur, sem animação contínua parado.** O WebView2 continua em software. A resposta em escrita é redesenhada no máximo ~11 vezes por segundo e nada é desenhado recolhido.
- **Linha de base herdada:** `widget_ui.py` e `DesktopChecks.cs` já falhavam antes (7ª categoria de Ajustes; duplo de teste sem `/api/protection`); corrigidos só nos testes. A trilha ganhou um quarto controle e
  Gravar deixou de ser o do meio (teste atualizado).
- **Limites:** sem comandos `/`, anexos, `/tela` nem voz na barra (confirmações de custo/envio externo e microfone ficam no Cérebro). O executável oficial só muda depois de Sair e trocar o arquivo.

## Gemini gratuito e bloqueio de serviços pagos (09/11/2026; `lumen/study/policy.py`)

> **Histórico — superado em 09/11/2026.** A integração com o Gemini foi retirada do Lúmen (relatório: `docs/implementation/LUMEN_REMOCAO_GEMINI_20261109.md`). O texto abaixo registra o que foi decidido e medido na época; não descreve o código de hoje.

- **Regra:** só entra na IA externa o que está comprovado gratuito em documentação oficial (lista de permissões). Local (Ollama) sempre; Google Gemini só chat de texto, em
  `policy.GEMINI_FREE_CHAT` (4 modelos “Free of charge” na tabela de preços de 09/11/2026), e só depois de três aceites do estudante (cotas, uso de dados do plano gratuito, plano
  do projeto da chave). Claude, OpenAI, imagem/vídeo em nuvem, busca hospedada, TTS/ASR/embeddings em nuvem e armazenamento remoto: **bloqueados no backend**, antes de qualquer requisição.
- **“Gratuito e sem cotas” não existe** no Gemini (a documentação publica só a camada gratuita com limites, sem números por modelo): o Gemini fica **desativado por padrão** e a
  exigência não é flexibilizada em silêncio. O plano do projeto não é consultável só com a chave: vale a confirmação do estudante, atada à chave (trocar a chave pede de novo);
  um HTTP 402 trava o Gemini para aquela chave. O Lúmen nunca gera “para ver se cobra” nem sugere ativar faturamento.
- **Um ponto só:** `policy.authorize` (chat, JSON, alternativo, capas, listagem) + `policy.normalize` em `settings.load()` (ajuste antigo nunca reativa serviço pago) + enums fechados em
  `settings.save()` (a seção `gemini` só muda pela rota `/api/study/gemini`). Migração única com `settings.json.antes-gemini-gratis-20261109.bak`.
- **Privacidade:** no plano gratuito o Google usa o conteúdo e revisores podem lê-lo; a tela diz isso antes do aceite. Áudio nunca sai (vozes locais); `/web` usa a pesquisa guiada no Edge.
- **Erros/cotas:** mensagens distintas (chave, acesso, plano/região, modelo, cota, indisponível, timeout); 429 lê `Retry-After`/`retryDelay`, no máximo UMA nova tentativa, só antes de
  qualquer trecho da resposta e com espera curta; nunca troca de projeto/chave nem sugere pagar. Falha no meio do streaming com alternativo: o texto parcial é trocado, não duplicado.
- **Protocolo:** `thoughtSignature` e `id` das chamadas voltam na mesma parte (exigência do Gemini 3/4); sem ferramentas hospedadas. `generateContent` é legado na documentação; migrar para a
  Interactions API só com validação real. Relatório: `docs/implementation/LUMEN_GEMINI_GRATUITO_20261109.md`. Restauração: `D:\Lumen\restauracao\gemini-gratis-20261109`.

## Retirada completa do Gemini (09/11/2026; `lumen/study/policy.py`, `lumen/study/settings.py`, `lumen/gdrive.py`)

- **Decisão do estudante:** tirar o Gemini do Lúmen e seguir só com IA local (Ollama), sem cobrança por chamada de API. Vale para o
  chat (adaptador, modelos, chave, aceites), para a mídia em nuvem e para o conector **Gemini Notebook** (`lumen/notebook.py`).
  Não se troca o Gemini por outra API externa. Claude e OpenAI continuam **bloqueados**.
- **O que fica:** Ollama e os motores locais (embeddings, voz, transcrição, imagens, visão); Notion e Obsidian; a pesquisa guiada no
  Edge; a gravação e a captura; a Proteção e a restauração; **o Google Drive da Proteção** (`gdrive.py` + `protection_drive.py`).
- **`gdrive.py` é compartilhado:** perde só o que era do Notebook (pasta “Lumen - Gemini Notebook”, `create`, `update`, `folder`,
  conversão para Google Doc). Login OAuth, token, `find`, `_call` e a política de erros e repetições ficam. As rotas do Drive saíram de
  `/api/notebook/drive/*` para `/api/drive*` (a Proteção chamava a de login por esse caminho).
- **Política única (`policy.py`):** `PROVIDERS = ("ollama",)`. Claude e OpenAI: `paid_provider`. `google` e `gemini`:
  `removed_provider` (só para a recusa explicar). Qualquer outro nome: `unknown_provider`. Recursos em nuvem: `paid_feature`.
- **Migração (`settings.migrate`, idempotente):** é guiada pelo conteúdo do arquivo (não por uma marca): se ele ainda guarda `gemini`,
  `models.google`, `models.image_google`, `privacy.external` ou um provedor/imagem/vídeo que não existe mais, reescreve só isso
  (principal → local, alternativo → nenhum, imagem → local, vídeo → desativado), preserva o resto (inclusive o modelo local escolhido,
  sem inventar nome) e guarda **uma** cópia, `settings.json.antes-remocao-gemini-20261109.bak`. Rodar de novo não faz nada e não cria outra
  cópia. A leitura (`load`) já neutraliza o arquivo antigo antes de a migração rodar.
- **Credencial:** a migração apaga do cofre do Windows só a entrada `Lumen` / `google-api-key` (sem lê-la), nunca as do Drive, do Notion,
  da Proteção nem de outros aplicativos. Apagar a cópia local **não revoga** a chave na conta Google.
- **Dados antigos do Notebook:** `DATA/notebook/` (arquivos preparados e materiais trazidos) e `DATA/notebook.json` (vínculos) ficam
  no PC, sem nenhum código que os leia; “Limpar dados” apaga a pasta, como já fazia. Nada é apagado no Google (cadernos, documentos,
  pasta no Drive).
- **Testes:** `tests/test_gemini_removed.py` (migração, rejeição, rotas, credencial em cofre simulado, dados antigos, IA local e
  varredura do código), `tests/test_gdrive.py` (Drive que a Proteção usa), `tests/local_ai_ui.py` (Chrome headless). O `tests/__init__.py`
  passou a instalar um cofre em memória: nenhum teste toca no Gerenciador de Credenciais do Windows.

## Conversa rápida: modelo rápido como padrão, ajustes próprios e temporário discreto (09/11/2026; `lumen/study/settings.py`, `agent.py`, `providers.py`, `lumen/web/chat.js`)

Relatório e provas: `docs/implementation/LUMEN_CONVERSA_RAPIDA_AJUSTES_20261109.md`.

- **D141 · A barra pede, o servidor decide.** A requisição da barra leva `surface: "quick"` (e nada de modelo, provedor ou URL). O agente lê os ajustes `quick.*` NO COMEÇO de cada resposta
  (`agent._turn`), então mudar um ajuste nunca altera a resposta em andamento e vale da próxima. O Cérebro (sem `surface`) não é tocado, e `models.fast` global nunca é gravado pela barra.
- **D142 · "Rápido" = nível Rápido + modelo rápido.** Sem escolha própria (`quick.model` vazio), a barra envia o esforço `rapido` (sem raciocínio; 4 fontes; 2 rodadas de ferramentas: a definição
  que o nível já tinha) e usa `settings.fast_model()` resolvido na hora (nunca um nome fixo). O modelo é FIXADO no provedor (`Ollama.pin`): resposta, entender a pergunta, título, memória e
  resumo usam o mesmo, e nenhum outro sai do HD. Com modelo escolhido, o nível segue o automático e o modelo vale em todos os níveis. O perfil adulto, quando escolhido, mantém o modelo dedicado
  e nada dele passa pelo modelo da barra.
- **D143 · Modelo escolhido é validado no backend.** `settings.quick_choices()` = modelos de chat instalados no Ollama (sem embeddings e sem o modelo dedicado ao perfil adulto); `_check` recusa
  nome fora da lista, caminho, URL, provedor e Ollama fora do ar (não dá para conferir). Ajuste editado à mão com valor inválido volta ao padrão na leitura.
- **D144 · Modelo ausente: recuperação local ou erro claro.** `settings.quick_resolve()`: pedido → rápido → principal, só entre os instalados. Se o respondente difere do pedido, a resposta
  traz o evento `fallback`, `meta.quick.fallback` e a tela diz qual respondeu. Sem nenhum modelo local: erro claro DEPOIS de confirmar a pergunta (Tentar de novo). Nada é baixado e nada
  sai do computador.
- **D145 · Ajustes próprios, pequenos.** `settings.json → quick: {model, new_chat}` (migração = padrões de `DEFAULTS`); rota `GET/POST /api/study/quick` (grava só essas duas chaves; `{"reset": true}`
  volta só elas). O tamanho Compacto/Ampliado continua sendo UMA configuração (`lumen.quick.wide`, só da sessão); o painel de ajustes e o menu chamam a mesma função `setWide`.
- **D146 · Temporário.** Segue o contrato existente (`chats.TEMP` em memória, sem memórias, `temporary_private`). Novo: o servidor segue `quick.new_chat` quando o pedido não diz `temporary`
  (escolha explícita do menu vale mais; conversa que existe nunca muda de tipo); a tela não grava NADA temporário no navegador (mensagens vêm do servidor; rascunho temporário só na memória da
  página; sem ponteiro em `localStorage`; ponteiro temporário de versão anterior é apagado); rascunho normal e temporário são dois espaços; erros de ferramenta numa conversa temporária deixam
  de registrar argumentos e mensagem no registro de atividades. Indicador: chip neutro com relógio e o texto "Temporária" na linha de modo, sem pulso nem cor de alerta.
- **D147 · Painel interno em vez de janela.** "Ajustes desta conversa" substitui a conversa dentro do painel (a janela não cresce): Modelo, Novas conversas, Tamanho, Restaurar, com Voltar sempre à
  vista e rolagem só no corpo. Leituras e gravações dos ajustes passam pela mesma fila na tela (uma leitura iniciada antes não devolve o valor velho). Barra em cima/embaixo: o menu de 5 ações
  usa itens de 26 px para caber sem rolar (ampliada: 40 px).

## Cápsula de gravação da barra flutuante (09/11/2026; `lumen/web/widget.html`, `widget.css`, `widget.js`)

Relatório e provas: `docs/implementation/LUMEN_BARRA_GRAVACAO_CAPSULA_20261109.md`. Nenhum C# do produto, rota ou captura de áudio foi alterado.

- **D148 · Um estado da interface existente.** A Pausa é o `#pause` e o `togglePause()` de antes (mesmas rotas `/api/record/pause|resume`, mesmo atalho), movido do painel para a trilha;
  o Gravar é o `#action` e o `toggleRecording()` de antes. Não há segundo botão de pausa na mesma apresentação, nem ID ou listener duplicado.
- **D149 · O Gravar não se mexe.** O grupo `.rec-group` tem o tamanho do botão; a Pausa é posicionada em absoluto e emerge de trás dele; os vizinhos deslizam com `translate` (a grade e
  a janela não mudam). Parado, a barra é idêntica à anterior (comparado em px). Em vez de refazer a grade (que obrigaria a mover o Gravar), cada orientação tem constantes pequenas
  (`--cap-*`) conferidas contra os 250 px da barra lateral e os 302 px da deitada, com e sem Minha compreensão.
- **D150 · O servidor é a fonte; a animação segue a mudança de estado.** `renderCapsule()` aplica `data-rec` só quando o estado muda e roda também durante o aviso de erro de um comando (o
  texto do painel fica; a cápsula mostra o real). Primeira leitura = sem animação (`data-capsule=init`).
- **D151 · Segurança do toque.** O clique age pelo que a pessoa viu (estado diferente ⇒ mostra, não age); 700 ms de guarda depois de iniciar; comandos pendentes recusam cliques
  (`aria-disabled`, não `disabled`); respostas anteriores a um comando concluído são descartadas. O fluxo de depois de parar (`record:ready`) não mudou.
- **D152 · Não força painel.** Iniciar a gravação deixou de fechar o painel de Ajustes (a cápsula já mostra o estado); conversa, ajustes e nota seguem abertos, e recolher a barra não pausa
  nem encerra.
- **D153 · Dicas.** A dica da Pausa é curta e, na barra deitada, as dicas dos controles da trilha abrem para o lado de dentro (antes cobriam os vizinhos à direita).

## Estilo da interface Lúmen Glass 2026 (10/11/2026; `lumen/web/glass.css`, `glass.js`, `index.html`, ganchos em `app.js`; relatório em `docs/implementation/LUMEN_GLASS_2026_20261110.md`)

- **D161 · Estilo da interface.** O redesign muda disposição, geometria, vidro e movimento. É um eixo à parte: `config.json → ui_style`
  (`classic` | `glass`; ausente = `classic`), escolhido em Ajustes → Aparência → Estilo da interface pelo mesmo `/api/settings` de sempre (qualquer outro valor é recusado). O Clássico continua o
  padrão e intocado.
- **D162 · O servidor marca o `<html>`.** `index.html` traz `data-ui="{{UI_STYLE}}" data-theme-kind="{{THEME_KIND}}"`; `server._page_marks` troca só por valores fixos (`store.UI_STYLES`; `default`
  quando `themes.rev()` é `d0`) e recalcula o ETag. A janela abre no estilo certo, sem piscar o outro. Trocar em Ajustes não recarrega: `glass.js` muda o atributo e reorganiza o que precisa.
- **D163 · Tudo escopado; Clássico provado idêntico.** Toda regra de `glass.css` está sob `:root[data-ui="glass"]` (teste lê cada bloco) e o arquivo entra por último (depois de `study.css`), então
  sobrepõe sem `!important`. As peças só do Glass ficam no HTML com `.g-only` (ocultas no Clássico por uma regra em `app.css`) e o texto só do Clássico com `.c-only`. Prova: estilos calculados
  (39 propriedades, de cor a tamanho, margem, grade, transformação e animação) de 69 080 elementos em 39 telas/estados, cópia de antes × atual, no Clássico: 0 diferenças.
- **D164 · Reorganizar movendo, nunca recriando.** As colunas independentes do Início, a faixa do Pomodoro dentro da área de trabalho (rola com a página, nunca cobre o conteúdo) e o corpo da
  Biblioteca (estrutura + lista) exigem outra ordem de elementos. `glass.js` MOVE os elementos que já existem (ouvintes, foco e estado continuam) e, ao voltar ao Clássico, devolve cada um ao lugar e
  à ordem originais (teste compara a ordem antes/depois). Nada é recriado nem duplicado; formulários e rascunhos não se perdem na troca.
- **D165 · Nenhuma função inventada.** O que as referências mostravam e o Lumen não faz ficou de fora: "Outro link" como fonte, "Áudio do sistema" com chave (o som do PC é a própria gravação;
  vira um aviso), destinos com caixa de seleção na Nova aula (isso é em Integrações), Tags, miniaturas de vídeo, porcentagens, "Trabalhar com o seu conhecimento" no Cérebro e alternância
  grade/lista. Ações rápidas e atalhos só chamam o que existe (Planejar → Estudar › Plano de estudos; Organizar → Biblioteca › A organizar; Buscar → Ctrl+K). A jornada marca a etapa pelo
  estado real da aula (gravação, tarefa ou primeira pendente); sem aula, fica neutra. Os números da Biblioteca são contados das mesmas listas que ela mostra.
- **D166 · As fontes da Nova aula voltam à vista.** As abas Gravar/Arquivo/Capturas estavam ocultas (só pela busca). No Glass há três cartões que acionam as abas de sempre (`selectTab` faz o
  resto); o link do YouTube continua como referência da aula, não como fonte. O botão de gravar continua vermelho coral; em repouso não pulsa (D168).
- **D167 · Vidro sem GPU.** O WebView2 roda com `--disable-gpu` (D anterior: estabilidade). O vidro dos cartões é material em camadas (preenchimento translúcido derivado dos tokens do tema,
  reflexo especular, borda óptica com máscara, sombra de contato) sobre um fundo ambiente fixo; `backdrop-filter` só em flutuantes pequenos (menus, painel do Pomodoro, diálogo, aviso, dica) e
  NUNCA em elemento sticky (a barra de ação ficou quase opaca: o desfoque seria refeito a cada quadro de rolagem). A "luz que segue o mouse" dos cartões fica desligada no Glass (recalculava
  o estilo dos filhos a cada movimento). Medido no Chrome sem GPU: rolagem a 60 quadros/s sem quadro longo nas quatro telas, troca de tela em ~2 quadros, como no Clássico.
  Mica/Acrylic não foram usados: o WebView2 pinta a área cliente inteira de opaco, então o material do Windows só apareceria tornando a janela transparente (risco que o projeto já evitou).
- **D168 · Movimento pela régua Emil Kowalski.** Curvas fortes de ease-out nas mesmas variáveis do Lumen (`--ease-standard/emphasized/exit`), 100–280 ms, pressão `scale(.95–.98)`, nenhuma
  animação infinita decorativa (pulso do botão principal, do gravador em repouso, do passo atual e do ponto do Monitor saem), troca de tela instantânea, popover nascendo da origem (painel do
  Pomodoro: canto superior direito), aviso com `@starting-style` (interrompível). Reduzir movimento: sem deslocamento, mas aviso, diálogo, painel e dica mantêm um fade curto.
  Reduzir transparência e contraste alto têm variantes.
- **D169 · Windows em vez de macOS na moldura.** No Glass a barra de título traz a marca à esquerda e minimizar/maximizar(restaurar)/fechar no formato do Windows à direita (`data-g-window`,
  mesmas mensagens `window:*` ao `Lumen.exe`, só com a moldura própria). O ícone vira "restaurar" quando a janela ocupa a área de trabalho. Limite: botões em HTML não abrem o menu de
  Snap Layouts ao passar o mouse (isso exigiria o hit-test nativo de HTMAXBUTTON); arrastar para as bordas, Win+Z, Win+setas e duplo clique na barra funcionam.
- **D170 · Paleta só sobre o tema padrão.** A paleta da direção visual (#0B0D12, #F1F2F6, #A0A6B4…) vale com `data-theme-kind="default"`; com um tema personalizado, o Glass usa as cores dele
  (os materiais são derivados dos tokens por `color-mix`). O azul principal #5571EF ficou #4C69EE (2% mais escuro, visualmente igual) para o texto branco passar 4,5:1; secundário #A8AEBB e
  terciário #9097A6 pelo mesmo motivo (teste de contraste igual ao do padrão).

- **D171 · Resultado em cartões por destino (Glass, 12/11/2026).** O resultado de uma aula mostra, no Glass, um cartão por destino (Notion, Obsidian), a visualização
  3D e as ações em duas fileiras. Os fatos são os MESMOS das linhas do Clássico: `obsidianParts` e `visualFacts` (`app.js`) alimentam os dois; o bloco `.g-result` é
  `.g-only` e existe nos dois estilos (a troca sem recarregar não redesenha). "Tentar de novo" de um destino fica no cartão dele; com um destino só, o rodapé não repete
  o botão. O foco vai para a ação do primeiro destino e a tela fica no topo. De passagem: resultado sem visualização mostrava o texto "null" (corrigido nos dois estilos).
- **D172 · A barra e a nota conhecem o estilo.** `/widget` e `/note` passam por `_page_marks` (`<html data-ui>`) e `/api/widget` devolve `ui`; as duas janelas trocam
  o atributo na leitura que já faziam (o caminho do tema). O que é do Glass na barra fica num bloco do `widget.css` em que toda regra começa por
  `:root[data-ui="glass"]` (teste). Primeiro uso: os Ajustes da barra em ladrilhos (R35), só com a barra em cima/embaixo — na lateral não há largura.
- **D173 · Capas, Proteção e Diagnóstico só por apresentação.** Capas: a trilha de três passos é um espelho visual (`aria-hidden`) do estado do fluxo, lido pelo CSS
  (`#cov-page`, `#cov-img[data-empty]`); "Como funciona" repete a frase de sempre em três passos; `settingsArrange` aceita `[data-g-group]` (começa um cartão) e
  `[data-g-free]` (fica solto). Proteção: nenhuma linha do `protection.js` mudou — o Glass reorganiza os blocos existentes por CSS (situação em cartão, etapas com o
  estado em selo, cópias lado a lado). Diagnóstico: o selo grande espelha o `data-tone` do selo da porcentagem.
- **D174 · Ícones dos cartões e das linhas das Configurações da IA.** `Glass.aiSection` → `aiCards` põe um ladrilho no título de cada cartão e um ícone em cada linha,
  por tabelas de título/rótulo → ícone (`CARD_ICO`, `ROW_ICO`); são decorativos (`aria-hidden`, `.g-only`). Num cartão, as linhas só ganham ícone quando todas têm um.
  Nenhuma classe nova em elemento existente (a comparação do Clássico acusa): o CSS reconhece o cartão com frase por `:has()`.
- **D175 · Configurações da IA em peças `.g-only` (12/11, 4ª sessão).** Atividades vira linha do tempo por dia (`Glass.activity`, mesmos registros da tabela, lotes de 30
  sem chamada nova), Avaliação ganha contador, estado vazio e trilha (`Glass.evaluation`), PDFs e Personalização são um cartão do Clássico desenhado como vários cartões
  de vidro (`Glass.split`: fundos e cabeçalhos `.g-only`, nada é movido), o Catálogo ganha ladrilho por skill. `study-settings.js` só chama os ganchos opcionais
  `window.Glass?.x` e entrega os mesmos valores aos dois estilos. Na barra (R37), bandeja e filete são só desenho: a geometria é contrato com `launcher/WidgetForm.cs`.
- **D176 · Reestruturar por CSS quando a marcação já tem tudo (14/11).** Monitor (R25) e o cartão de descrição do menu de modo (R36) mudam de "centralizado" para
  "ladrilho + filete + texto à esquerda" sem tocar no `app.js`/`study.js`: o contêiner do título vira `display: contents`, o ícone vira o ladrilho (caixa de conteúdo com
  `padding`) e o filete é o `::after` do cartão, todos posicionados numa grade. O Monitor ganha `max-height` e rola (`flex-shrink: 0` nos filhos) em janela baixa.
- **D177 · Coluna "Salvar" da Análise (R02) e Salvos (R08) (14/11).** No Glass a coluna tem `clamp(340px, 30%, 420px)` acima de 1100 px e o cartão de destinos entra
  sem moldura (o Clássico já fazia isso; a regra genérica de cartão do Glass a devolvia). O ladrilho dos Salvos reusa a regra de `.g-tile-ico` por `:is()`.
  Busca, filtros por tipo e ordenação dos Salvos e os filtros das Atividades não foram desenhados: seriam função nova, fora do escopo do estilo.
- **D178 · Centralizar só o texto curto e independente, por token (14/11/2026).** O pedido foi centralizar os textos de todas as interfaces sem redesenhar. O inventário
  mediu 650 tipos de contêiner de texto no Glass e 605 no Clássico (90 telas/estados cada): a maioria está ancorada a um ícone, a um controle ou à borda de uma lista,
  e centralizá-la mudaria o desenho aprovado (referências R01–R38). Decisão: centralizam as mensagens independentes (cartão do Início gravando/pausado/processando no
  Glass, mensagem do Pomodoro, estado vazio das conversas, notas de rodapé de cartão, rótulo "Posição na tela" da barra), por dois tokens (`--ta-short`, `--jc-short`)
  e uma regra central no `ui.css`; o bloco de centralização do Clássico passou a usar o mesmo token (mesmo resultado visual). Títulos de página/seção do Glass
  continuam à esquerda: são a borda de leitura do estilo, e mudar isso é decisão de desenho do usuário (`--ta-short` não os alcança de propósito).
  Achado ao medir: no Clássico a barra de progresso do cartão do Início tinha largura 0 desde a centralização antiga (coluna flex centralizada); corrigido com
  `align-self: stretch`. O launcher não mudou (não desenha texto: só o menu da bandeja e o aviso, que são do Windows), então não houve executável novo.

- **D179 · Temas personalizados removidos (15/11/2026).** O usuário pediu para retirar a função de temas "sem deixar rastro e sem quebrar o código; é inútil". Saiu: `lumen/themes.py`, as rotas
  `/api/themes*` e `/theme.css`, o `config.json → theme` (o arquivo deixa de gravar a chave), `theme.js`, `theme-settings.js`, a seção "Temas" de Ajustes → Aparência (fica só o
  Estilo da interface), a categoria "Aparência" da barra flutuante, `.theme-scope`/`html.theme-swapping` no `ui.css`, o atributo `data-theme-kind` do `<html>` (a paleta Glass vale agora
  só sob `:root[data-ui="glass"]`), o `NativeTheme` do launcher (virou `NativeColors`, com as mesmas cores fixas do padrão e a mesma chamada ao DWM) e as mensagens `theme:native:*` e
  `window:settings:appearance`, o bloco "Temas" de `tests/DesktopChecks.cs`, `tests/test_themes.py`, `tests/themes_ui.py`, `tests/themes/` e os guias `docs/TEMAS.md`, `docs/temas/`.
  O harness de servidor dos testes de interface passou de `tests/themes_harness.py` para `tests/ui_harness.py`. As decisões D154–D160 (o formato dos temas) foram retiradas junto;
  D162, D170 e D172 falavam de `data-theme-kind` e de "paleta só sobre o tema padrão" (hoje a paleta Glass vale sempre sob `data-ui="glass"`). O visual de sempre não mudou.
  Restauração: tag `PRE-REMOVER-TEMAS-20261115` (commit de snapshot, fora da branch) e `D:\Lumen\restauracao\remover-temas-20261115\antes.zip`.
- **D181 · Open Notebook: só a transcrição em texto, pela API, sem duplicar (15/11/2026).** `lumen/opennotebook.py` fala com a API REST do Open Notebook
  (rotas conferidas no `/openapi.json` da 1.15.1): `POST /api/sources` em multipart com `type=text`, `async_processing=true` e `notebooks=[id]`; nunca o banco dele.
  Fica fora do roteador de destinos (`jobs._deliver`) de propósito: é um envio à parte, pedido aula por aula (ou automático, desligado por padrão e numa thread
  depois da entrega), e a falha dele não muda o resultado do Notion nem do Obsidian. O estado mora no manifesto que já existia (`history.json`, campo
  `opennotebook`: hash do texto, caderno, id da fonte, estado); não há outro banco. Um envio sem resposta vira `unconfirmed` e a nova tentativa procura a fonte no
  caderno antes de repetir: a API assíncrona só preenche `full_text` depois do processamento, então a fonte ainda na fila é reconhecida pelo título e pela data
  de criação (5 min de folga de relógio) e a já processada, pelo `lumen_id` no texto. `embed` só vai `true` quando o Open Notebook tem modelo de embeddings
  padrão (sem ele o processamento falharia). Falha de processamento lá usa `POST /api/sources/{id}/retry` na mesma fonte. Pedidos sem proxy e sem seguir
  redirecionamento (a senha e o texto não vão a outro endereço); a senha fica no cofre (`Lumen`/`opennotebook`) e é esquecida ao trocar o endereço da API.
  “Abrir no Open Notebook” usa uma janela própria (`NotebookForm` em `launcher/Lumen.cs`): perfil WebView2 separado, `IsWebMessageEnabled=false`, navegação presa
  à origem; a janela principal nunca sai do Lúmen. Restauração: tag `PRE-OPEN-NOTEBOOK-20261115` e `D:\Lumen\open-notebook-20261115\Lumen.exe.antes`.
- **D182 · “Iniciar Open Notebook”: só a pedido, só o que falta, sem encerrar ninguém (15/11/2026).** O “Serviço indisponível” era a instalação nativa
  parada depois de reiniciar o PC, não o endereço. `lumen/onlocal.py` inicia banco (SurrealDB em `127.0.0.1:8000`), API, worker e interface nessa ordem, com
  caminhos fixos, argumentos em lista e `shell=False`; a senha do banco vem do `.env` do Open Notebook e vai pelo ambiente do processo (`SURREAL_USER`/`SURREAL_PASS`),
  nunca na linha de comando nem no log. Cada componente é reconhecido antes de qualquer partida: `/version` do SurrealDB, `dbStatus` em `/api/config`, `apiUrl` em
  `/config` da interface e a linha de comando do worker (ele não tem porta). Porta aberta sem essa resposta é “outro programa”: erro com o nome do processo, nada
  encerrado (o módulo não tem nenhuma chamada que encerre processo). Uma partida por vez; repetir o clique devolve o andamento. Os serviços têm de sobreviver ao
  Lúmen, então o grupo de processos do `Lumen.exe` passou a permitir saída (`KILL_ON_JOB_CLOSE | BREAKAWAY_OK`) e só eles pedem `CREATE_BREAKAWAY_FROM_JOB`; com
  um `Lumen.exe` anterior a pedido é negado, o serviço inicia preso ao Lúmen e a interface diz isso (`tied`). Restauração: tag `PRE-ON-INICIAR-20261115`.

- **D183 · HyperbookLM: título e transcrição, à mão, por uma ponte local autenticada (16/11/2026).** O HyperbookLM guarda as fontes só no estado React da
  página (`useState` em `app/page.tsx`; o `useLocalSources` com `localStorage` existe, mas não é usado) e não tem rota de importação: as rotas dele só chamam
  provedores pagos. Importar pela interface seria automação de cliques, e gravar no `localStorage` de outra origem não é possível. Por isso a integração tem
  duas metades. No HyperbookLM, uma ponte (`lib/lumenBridge.ts`, `app/api/lumen`, `app/api/lumen/sources`) guarda o que chega em `.lumen/sources.json`
  (escrita atômica, uma por vez) e a página lê esse arquivo ao abrir e ao voltar ao foco; remover a fonte na página a apaga do arquivo. No Lúmen,
  `lumen/hyperbooklm.py` é um módulo à parte do Open Notebook (reaproveita só o abridor sem proxy/redirecionamento e a sonda de porta) com as rotas
  `/api/hyperbooklm*`, a aba e o diálogo em `hyperbooklm.js`. Vai só `{title, text}`; a ponte recusa qualquer outro campo. O id é o SHA-256 de título + texto,
  calculado dos dois lados: reenviar nunca duplica, um tempo esgotado fica *não confirmado* e pode ser repetido, e “Guardada” só vale depois de a ponte listar o
  id. Sem envio automático. Segurança: o Lúmen gera o código (`secrets.token_urlsafe(32)`), guarda no cofre do sistema e mostra uma vez a linha
  `LUMEN_BRIDGE_TOKEN=…` para o `.env.local` do HyperbookLM (o Lúmen não escreve em arquivos de outro aplicativo: o pareamento é o único passo manual). A ponte
  exige o código para gravar (comparação em tempo constante), atende a página por mesma origem (`Sec-Fetch-Site`), recusa `Host` e `x-forwarded-for` que não
  sejam deste PC, e os scripts `dev`/`start` do HyperbookLM passaram a escutar só em `127.0.0.1` (o `x-forwarded-for` do Next pode ser forjado; o que isola de
  verdade é a escuta local mais o código). O Lúmen só aceita endereço `http` de loopback. “Conectado” é o servidor; as chaves de IA aparecem à parte e só como
  *existe/não existe* (a ponte lê `process.env` e não chama nenhum provedor). A ponte responde por análise (`features`: `text`, `slides`, `audio`, `scrape`),
  não por provedor, para a interface do Lúmen não voltar a citar o provedor retirado (o guarda de `tests/test_gemini_removed.py` segue valendo, sem exceção nova). Porta: o `next dev` sobe a porta quando a 3000 está ocupada (o Open Notebook a
  usa), então “Testar conexão” procura da 3000 à 3010 por `app: hyperbooklm` quando o endereço guardado não responde; abrir a aba não sonda nada. Janela:
  `NotebookForm` ganhou título e perfil como parâmetros (`webview-hyperbooklm`), e o `Lumen.exe` novo se anuncia no User-Agent (`LumenShell/2`) para a página
  cair no navegador padrão quando o executável é anterior. A aba de Integrações passou de cinco colunas para duas fileiras de três. Também foi preciso trocar
  `require("tailwindcss-animate")` por `import` no `tailwind.config.ts` do HyperbookLM: no Node 26 deste PC o arquivo é carregado como módulo ES e o `require`
  derrubava o servidor ao compilar a página. Restauração: cópias conferidas por hash em `D:\Lumen\hyperbooklm-20261116\rollback` (com `RESTAURAR.md`).

- **D184 · HyperbookLM dentro da janela principal, num painel nativo com WebView2 próprio (16/11/2026).** A janela separada (`NotebookForm`) tirava o
  usuário do Lúmen. Agora `hyperbooklm:open:` mostra `HyperbookView` (`launcher/Lumen.cs`): um `Panel` filho do `MainForm`, por cima do WebView2 do Lúmen,
  com uma barra nativa (botões de janela como os da página, **Voltar ao Lúmen**, **Recarregar**, nome e estado; a barra arrasta a janela e dois cliques
  maximizam, porque sem a barra de título nativa não haveria onde pegar) e um WebView2 no mesmo perfil de antes (`webview-hyperbooklm`). Um `<iframe>` na
  página do Lúmen foi descartado: dividiria o perfil e o processo com o Lúmen, exigiria afrouxar a CSP dele (`default-src 'self'`) e não daria para prender
  a navegação por origem. A página do Lúmen não é recarregada nem escondida, só coberta: voltar é esconder o painel, e o estado dela fica intacto; o
  HyperbookLM também fica carregado para a próxima abertura. Isolamento igual ao da janela antiga (sem ponte de mensagens, sem DevTools, sem preenchimento
  automático), com a navegação mais restrita: fora da origem só sai para o navegador padrão o que o usuário clicou (`IsUserInitiated`) e é http(s);
  redirecionamento por script e outros esquemas são só bloqueados. O painel nunca fica em branco: “Abrindo…”, “não está respondendo” (falha de rede na
  navegação; uma página de erro HTTP do próprio servidor é mostrada como veio) e “WebView2 demorou demais” (30 s; a partida trava em vez de falhar quando o
  perfil é inacessível, então a tentativa é descartada e “Recarregar” cria outra). Medidas em pixels pela escala da janela (`GetDpiForWindow`), refeitas no
  `WM_DPICHANGED`. Pedidos que precisam da página do Lúmen (Ajustes pela bandeja, “Abrir no Cérebro”, gravação pronta, nota encaixada) escondem o painel.
  O Open Notebook continua na janela separada. A página (`hyperbooklm.js`) não mudou: a mesma mensagem, outro destino. Restauração:
  `D:\Lumen\hyperbooklm-embed-20261116\rollback` (inclui o `Lumen.exe` oficial de antes).

- **D185 · Perplexity: o site oficial num painel do Lúmen, só a pergunta vai, a volta é colar (19/11/2026).** `/perplexity <pergunta>` (Estudos) abre um
  diálogo com a pergunta editável e o aviso de que só ela sai do Lúmen; ao confirmar, a página manda `perplexity:open:<endereço>` ao `Lumen.exe` (`LumenShell/3`
  no User-Agent; o `hyperbooklm.js` passou a aceitar 2 ou depois). O endereço é o modelo de busca publicado pelo próprio site (`https://www.perplexity.ai/opensearch.xml`:
  `/search?s=o&q={searchTerms}`), sem o `s=o`, que marca buscas da barra do navegador; conferido em 19/11/2026: `perplexity.ai` → `www.perplexity.ai`, e
  `/search?q=` → `/search/new?q=`, que faz a busca e troca o endereço por `/session/<id>`; sem conta, a busca roda e depois o site pede para entrar
  (Google, Apple, e-mail ou SSO). Nada de API, script na página, leitura do DOM ou clique automático: o Lúmen só abre o endereço. O `Lumen.exe` confere de novo
  (`MainForm.PerplexityStart`: https, porta padrão, `www.perplexity.ai`, só `/` ou `/search?q=`, sem usuário nem fragmento). O painel é o do HyperbookLM (D184)
  com parâmetros, renomeado `SiteView` (nome, perfil, hosts liberados, aviso de indisponível e o botão **Trazer resposta ao Lúmen**). Perfil próprio
  `webview-perplexity` na pasta de dados do Lúmen: o login fica nele, gerido pelo WebView2; o Lúmen não lê senha, cookie nem token (senha e preenchimento
  automático desligados). Ficam no painel só `https` de `www.perplexity.ai`, `perplexity.ai`, `accounts.google.com` e `appleid.apple.com`; o resto: link
  clicado (http/https) abre no navegador padrão, redirecionamento e outros esquemas são bloqueados com “Bloqueado: <host>” na barra (e, se a própria abertura
  foi levada para fora, um aviso no lugar de “Abrindo…”, defeito do painel que valia também para o HyperbookLM). Em site da internet (`allow`), downloads
  são cancelados com aviso, toda permissão é negada e esquema externo não abre aplicativo; nos dois painéis, sem ponte de mensagens, objetos do aplicativo
  nem DevTools. Atenção: o `Navigate` do aplicativo conta como gesto do usuário no WebView2 (`IsUserInitiated`), por isso a regra também exige `!IsRedirected`.
  A volta é sempre do usuário: Copiar no Perplexity, **Trazer resposta ao Lúmen** (volta e manda `desktop:perplexity:paste` à página, sem conteúdo) ou
  `/perplexity` sem pergunta abrem um diálogo de colar; o texto entra na caixa de mensagem marcado “[Conteúdo do Perplexity colado por mim · não verificado
  pelo Lúmen]”, com fontes e links como vieram, sem envio automático. Acima de 8 000 caracteres (o corte do `agent.py`) vira o anexo `perplexity-….md`, inteiro.
  O `/web` (pesquisa guiada no Edge) não mudou. Conferido: `tests/test_perplexity.py` e a verificação nativa `tests/PerplexityCheck.cs` (site oficial sem conta,
  site local para downloads, permissões e redirecionamentos). Falta conferir com conta: entrar com Google/Apple/e-mail no painel e copiar uma resposta de verdade;
  se o provedor recusar o navegador embutido, o limite fica assim, sem contorno. Restauração: `D:\Lumen\perplexity-20261119\rollback` (com `SHA256.txt`).
  Acréscimo (19/11/2026, a pedido: o usuário não achou a função): botão ↗ “Pesquisar no Perplexity” na caixa de mensagem do Cérebro e a aba
  **Integrações → Perplexity** (`#integ-perplexity`): campo da pergunta com o aviso de que só ele sai, “Pesquisar”, “Abrir o Perplexity” (página
  inicial), “Colar resposta no Cérebro”, os três passos e a lista de privacidade. Sem conexão a testar: o estado diz só se abre no painel ou no navegador.

- **D186 · Diagnóstico do sistema: tudo o que o app usa, só com leituras, sem sucesso falso (19/11/2026; `lumen/diagnostics.py`).** O diagnóstico antigo dava
  “ok” sem prova (versão do Voice Studio fixa “0.5.7”, Restic “verificado” só por existir, WebView2 e servidor sempre ok, erro desconhecido do Notion virava ok,
  `info` contava como ok na nota e o selo mostrava “100%” antes de rodar). Agora são 45 verificações em 11 grupos, do inventário do código: Python e pacotes
  fixados (versão e importação), pacotes de GPU, pasta de dados e espaço, cofre do Windows, servidor (o próprio pedido: endereço, porta, token), janela do
  Lumen.exe (WebView2 pelo registro e o `LumenShell/N` de quem chamou), Edge (CDP), abrir com o Windows, loopback, microfone, PyAV/FFmpeg, eco, motores e
  modelo de transcrição (arquivos no cache), CUDA, Ollama (/api/version, /api/tags e /api/show — metadados e capacidade, sem rodar o modelo), modelos do
  chat, embedding, perfil adulto, política só local, banco dos Estudos (SQLite FTS5 aberto só para leitura), pastas autorizadas, /web, Voice Studio
  (instalação, backend, modelos, voz escolhida), Chatterbox, Notion (/users/me e a página raiz por GET), Obsidian, Open Notebook (API e caderno, sem o
  `view()` que grava o endereço da interface), HyperbookLM, Perplexity (só se o painel já foi usado), Restic (`restic version` e `cat config --no-lock
  --no-cache` com a chave do cofre), cópia local pelos recibos, Google Drive (renovação feita aqui sem gravar no cofre + uma listagem), gerador de imagens,
  filtro de música, 3D e GPU. Cada item: obrigatório/opcional, ligado, estado (ok, faltando, configuração incorreta, inacessível, desativado, não
  verificado, bloqueado), etapas (instalado, configurado, autenticado, alcançável, utilizável), evidência, próximo passo seguro, limite do que não foi
  provado e tempo. Obrigatórios: o fluxo da aula (gravar → transcrever → IA local → destinos escolhidos em `destinations`). Verificação que quebra ou passa
  do prazo conta como obrigatória e não verificada. Cobertura (o que rodou) e prontidão (obrigatórias ok; é o número do selo) são separadas; “100%
  operacional” só com todas as obrigatórias ok. Paralelo, 30 s no total, 3 s por sonda local e 6 s na internet; segredos conhecidos e formatos de token
  viram ••••. Testes: `tests/test_diagnostics.py` (servidores falsos e cofre em memória). Restauração: `D:\Lumen\diagnostico-20261119\rollback`.

- **D187 · Instalar / reparar no Diagnóstico e linhas legíveis (19/11/2026; `lumen/repair.py`, `/api/repair`).** O diagnóstico continua só leitura; ele
  só aponta (`repair` no item) e o estudante decide. O que pode rodar é recalculado no servidor a cada pedido, só a partir de manifestos do projeto: os pacotes
  do `requirements.txt` que não estão instalados (pip do próprio ambiente, versão fixada; versão diferente fica para o Iniciar Lumen.bat com o Lúmen fechado;
  opcionais nunca) e o HyperbookLM (`package.json` × `yarn.lock` × `node_modules`; faltando, Yarn 1 com `--frozen-lockfile`, pelo yarn instalado ou pelo
  corepack com `COREPACK_ENABLE_AUTO_PIN=0`; depois o `npm run dev -- -p <porta>` existente, fora do grupo do Lumen.exe como o Open Notebook, e “pronto” só
  quando `/api/lumen` responde como a ponte). Um HyperbookLM já de pé em outra porta só corrige o endereço salvo; porta ocupada por outro programa nunca é
  mexida. Um reparo por vez, passos reais na tela, Cancelar encerra só o que ele iniciou e ainda não ficou pronto (taskkill /T no PID dele), prazos de 30 min
  (instalar) e 180 s (a ponte responder), log em DATA/logs/repair-*.log. Nada de administrador, comando vindo de texto, `.env.local`, código de pareamento,
  `.lumen`, lockfile ou dados do estudante. Linhas do diagnóstico: grid `20px minmax(0, 1fr) auto` (ícone | nome e estado | ação) com o detalhe, o próximo
  passo, as etapas e o limite na largura toda; com o contêiner estreito (≤ 560 px) a ação desce. O Glass perdeu a coluna fixa de 180–270 px que espremia o
  texto. Em 19/11 o HyperbookLM real estava parado com as 29 dependências completas: o reparo seria só iniciar, sem baixar nada.

- **D188 · Memória e CPU neste PC (21/11/2026; i5-11400F 6c/12t, 16 GB, RTX 3060, Lúmen no HD D:).** Medido com o Lumen.exe isolado
  (`LUMEN_DATA`), 60 s parado: servidor Python com a interface de 228 → 77 MB únicos (USS) e 695 → 73 MB comprometidos; janela à vista
  sem foco 23,5% → 4,1% de um núcleo. O que mudou, sem mudar o que o app faz:
  - `transcribe.has_gpu()` confere que o cuBLAS/cuDNN carregam e os solta (`_ctypes.FreeLibrary`): presos, custavam ~86 MB de RAM e
    ~240 MB comprometidos sem transcrição nenhuma. O CTranslate2 os carrega de novo quando um modelo vai para a GPU (verificado: turbo
    na GPU, float16, depois da conferência).
  - `OPENBLAS_NUM_THREADS=1` (`lumen/__init__.py`, `OWN_ENV`): o OpenBLAS do numpy reservava ~30 MB por thread lógica (12) ao carregar;
    as contas do Lúmen com ele são pequenas. Não vai para o Voice Studio, o Open Notebook nem os instaladores (`_env`/`_spawn` o tiram).
  - faster-whisper, PyAV, Pillow e pypdf só carregam no uso; `downloaded()` confere o disco pelo huggingface_hub com os mesmos
    repositórios e arquivos do faster-whisper 1.2.1 (`WHISPER_REPOS`; `tests/test_transcribe.py` compara).
  - Modelos de fala parados há 15 min (`transcribe._loaded`, `call._ASR_MODELS`) saem da memória (`release_idle`, no laço de
    `lumen/__main__.py`); nunca com transcrição ou chamada em andamento. Libera ~2,1 GB de VRAM; a RAM do runtime CUDA (~0,7 GB depois de
    usar a GPU) só volta ao fechar o Lúmen.
  - Proteção: `peek()` lê o `state.json` (24 MB aqui) só quando ele muda (mtime + tamanho + id do arquivo) nas leituras que não gravam
    (o `deliver_local` a cada 5 s, a tela a cada 5 s); `/api/protection` vai sem `item_versions` (23,7 MB → 0,19 MB por atualização).
  - Os pulsos de chamar atenção (`fx-pulse`, ponto do monitor) param com a janela sem foco (`body.inactive`, também ao abrir sem foco):
    sem GPU no WebView2 cada quadro custa CPU, ~20% de um núcleo só com a janela à vista. Com foco, continuam iguais.
  - Janela principal escondida ou minimizada: `MemoryUsageTargetLevel.Low` no WebView2 (os scripts seguem rodando).
  - Saíram o SDK `anthropic` (o Claude é bloqueado pela política antes de qualquer rede; o cliente era inalcançável) e as 11 dependências
    só dele, e o Playwright do `.venv` (os testes de interface usam o do Python do sistema).
