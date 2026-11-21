# Prompt: vozes do Voice Studio no Lúmen (fase 6 do Study AI 2.0)

> Cole isto numa sessão nova do Claude Code, aberta na pasta do Lúmen, ou diga: "Leia e execute `docs/implementation/PROMPT_LUMEN_VOZ_VOICE_STUDIO.md`".
> Modelo: **Claude Opus 5.5, esforço `xhigh`**. Se o limite de uso apertar, troque para o **Claude Sonnet 5.5 em `high`**. O Fable não está disponível, e o orçamento é zero: nada de API paga.
> Modelo de voz: o **OmniVoice (`k2-fsa/OmniVoice`, 2,5 GB)**. Ele já está instalado e carregado na GPU pelo Voice Studio. Não baixe nenhum outro.

---

Você vai terminar a **fase 6 do Lúmen Study AI 2.0** (voz, áudio e fala). A mudança em relação ao plano: o motor principal de voz passa a ser o **Voice Studio** instalado neste PC. Com ele, o Lúmen usa as vozes clonadas do estudante. A voz padrão é a do **Jhonny Silverhand**, que já está clonada lá.

O Lúmen deve conseguir:

1. falar com o estudante, lendo as respostas do chat e conversando por voz;
2. gerar o resumo em áudio de uma aula e a revisão em áudio dos estudos;
3. deixar o estudante escolher a voz, o motor e o jeito de falar nas Configurações, com uma tela de integração com o Voice Studio.

Tudo isso com a mesma qualidade visual do resto do app.

## 1. Situe-se primeiro

Leia, nesta ordem:

1. `docs/implementation/LUMEN_STUDY_AI_STATUS.md`, seção Study AI 2.0, fase 6. Os itens 2 a 7 do "Próximo passo" continuam valendo. Este prompt muda só o motor e acrescenta a personalização e o resumo da aula.
2. `docs/implementation/LUMEN_STUDY_AI_DECISIONS.md`, em especial D20, D21, D44 e D45, e `docs/DESIGN.md` inteiro.
3. O código de voz que já existe e ainda não está ligado a nada (os dois arquivos ainda não foram para o git):
   - `lumen/voice.py`: `speakable()`, `sentences()`, `synth()` com conferência pelo Whisper, `mix()` e `encode()` para `.m4a`;
   - `lumen/voice_worker.py`: o processo do Chatterbox pt-br.
   Aproveite esses dois. Não reescreva o que já funciona.
4. `bench/voice_bench.py`, para ver como a escuta cega foi feita.

Confira com `git status` e com os testes da fase 5 se o repositório bate com o STATUS antes de mexer.

## 2. O que já foi levantado sobre o Voice Studio (02/11/2026)

Confira tudo de novo antes de usar, porque o app se atualiza sozinho.

**Instalação**
- **Programa:** `%USERPROFILE%\AppData\Local\Programs\VoiceStudio\VoiceStudio.exe`, versão 0.5.7. É um app Electron com um backend Python chamado "OmniVoice". O código está em `resources\backend`. A licença é **AGPL-3.0**: o Lúmen fala com ele **só por HTTP**. Não importe nem copie código dele.
- **Dados:** ficam em `%APPDATA%\OmniVoice`: `omnivoice.db` (SQLite), `voices\`, `outputs\` e `omnivoice.log`. Esses dados são do estudante. **Nunca escreva no banco.** Ler em modo só leitura serve para diagnóstico, não como caminho do app.

**API local**
- **Endereço:** `http://127.0.0.1:3900`. A porta vem de `resources\config\app.json`, em `ports.backend`.
- **Acesso:** pelo loopback, a API responde sem chave. Rotas verificadas:
  - `GET /system/info`: versão, GPU, `device`, `generate_timeout_s` (300) e `idle_timeout_seconds` (900);
  - `GET /model/status`: `status`, `loaded`, `loading` e `progress`;
  - `GET /engines/tts`: o motor ativo (`omnivoice`), `supports_cloning`, `instruct_vocabulary: "tags"`, `max_ref_seconds: 20` e `min_vram_gb: 6`;
  - `GET /profiles`: as vozes, com `id`, `name`, `kind` (clone ou design), `language`, `ref_text`, `image_url`, `audio_url`, `is_locked` e `seed`. Há também `GET /profiles/{id}/audio` (a referência) e `GET /profiles/{id}/image`;
  - `POST /v1/audio/speech`, compatível com a OpenAI. Campos: `model` (padrão `omnivoice`); `input` (até 4096 caracteres); `voice` (o **id do perfil**, que vale mais que o nome); `response_format` (`wav` ou `pcm`, que é 24 kHz, 16 bits, mono); `speed` (de 0,25 a 4); `language`; `seed`; `instruct`; `stream_format` (`audio` ou `sse`);
  - `WS /ws/tts`: envia `{"text", "voice", ...}` e recebe pedaços de PCM16 a 24 kHz e, no fim, `{"type":"done","duration_s","gen_time_s","ttfa_ms","rtf"}`. A conexão fica aberta para os pedidos seguintes. O `websocket-client` já está no `requirements.txt`;
  - `POST /model/unload/{model_id}` e `POST /system/flush-memory`.

**A voz padrão**
- O perfil é o **`1faf41ee`**. No Voice Studio, o nome está escrito **"Jhonny Sirverhand"** (com a grafia que o estudante deu lá). É uma voz clonada (`kind: clone`), com o idioma em "Auto" e uma referência de 59,2 s em português.
- **Guarde o id, não o nome.** Na tela, mostre o nome que vier da API.
- O outro perfil, `demo0001` ("Demo Voice"), é a voz de demonstração do app, em inglês.

**Medidas que já estão no log e no histórico**
- "A Arasaka é uma das maiores…": 11,7 s de fala gerados em 10,6 s, ou seja, quase tempo real na RTX 3060.
- "opa tudo bom": 1,5 s de fala levou 5,9 s. Há um custo fixo de cerca de 5 s por pedido.
- **Causa provável do custo fixo:** como a referência tem mais de 20 s, o Voice Studio procura "o melhor trecho de 15 s" a cada pedido. Soma-se a marca d'água AudioSeal.
- **Idioma:** com `language: "Portuguese (Brazil)"` aparece o aviso "not recognized", e o modelo cai no modo sem idioma. Teste `"pt"`.

**Este PC**
- **Placa:** RTX 3060 de 12 GB, dividida com o Ollama (`qwen3.5:4b` e os embeddings). O Voice Studio reserva cerca de 5 GB por geração. O Chatterbox usa 3,6 GB.
- **Disco:** o C: está quase cheio (cerca de 19 GB livres). O Voice Studio grava em `%APPDATA%`, que fica no C:.
- **Uso do próprio estudante:** o Voice Studio também é usado direto por ele. O Lúmen é um convidado e não pode atrapalhar esse uso.

## 3. Decisões que este prompt já toma (registre como D46 em diante)

1. **Motores:** `voicestudio` é o padrão; `chatterbox` (D44) é a reserva local; `off` desliga a voz. O Kokoro só entra se a medição da fala ao vivo pedir. Se não entrar, remova o ambiente e registre, como o STATUS manda.
2. **Voz padrão:** o perfil `1faf41ee` (Jhonny).
   - Se ele sumir do Voice Studio, avise com o nome da voz que faltou e use a primeira voz clonada que existir.
   - Se o Voice Studio estiver fechado, use a reserva (Chatterbox), se o estudante tiver deixado isso ligado. Ao usar a reserva, mostre qual voz está falando: **nunca troque de voz em silêncio**.
3. **Quem fala com o Voice Studio é o backend do Lúmen.** O navegador não chama a porta 3900: a CSP é `connect-src 'self'`. O áudio volta por rotas do próprio Lúmen.
4. **Não mexer no que é do estudante no Voice Studio:**
   - não apague, renomeie, trave nem edite vozes;
   - "Editar" abre o Voice Studio;
   - não desligue a marca d'água;
   - não descarregue o modelo, a menos que o próprio Lúmen o tenha carregado (`/model/status` mostrava `loaded: false` antes) e a tarefa tenha sido longa;
   - não feche nem reinicie o app dele.
5. **Arquivos do Lúmen ficam no D:**, em `MEDIA/audio`. Veja se o `/v1/audio/speech` grava cópias em `%APPDATA%\OmniVoice\outputs` ou no histórico. Se gravar, apague só o que o Lúmen criou, pela API (`DELETE /history/{id}`), ou prefira a rota que não guarda nada. Registre o que encontrar.
6. **Uma voz na placa por vez:**
   - com o Voice Studio como motor, o Chatterbox não abre;
   - antes de gerar um áudio longo, chame `llm.release_vram()`, como os `jobs` já fazem;
   - meça se o `qwen3.5:4b` e o OmniVoice cabem juntos na fala do chat. Se não couberem, a fala espera a resposta terminar e o Ollama solta a placa.
7. **Voz clonada de uma pessoa real:**
   - a referência do Jhonny é a voz do dublador brasileiro do personagem, e o uso é pessoal, neste PC;
   - na tela, a voz aparece como "voz clonada";
   - nada de áudio vai para fora do PC sem uma ação explícita do estudante: gravar no Notion pede a prévia (D11).

## 4. O que construir, em etapas (cada etapa termina testada antes da próxima)

### Etapa 1: o motor e a integração

- **`lumen/voicestudio.py`:** um cliente pequeno, com `urllib` e `websocket-client`, sem dependência nova. Funções: `status()`, `voices()`, `sample(id)`, `speak(text, out, voice, speed, language, seed, check)` (que devolve a duração) e `stream(text, voice, ...)` (que entrega os pedaços de PCM, com cancelamento).
  - **Prazos:** 2 s para o estado e o prazo do próprio Voice Studio para gerar.
  - **Erros:** use as mensagens de `AppError` que o app já tem ("O Voice Studio está fechado." / "Abrir o Voice Studio").
- **`voice.py`:** o `synth()` passa a escolher o motor pelo ajuste. A conferência pelo Whisper continua igual para os dois motores, mas só nos áudios gerados em segundo plano. Na fala ao vivo ela fica desligada.
- **"Abrir o Voice Studio":** `os.startfile` no executável, e depois `/model/status` mostra o carregamento em tempo real.
- **Ajustes:** uma seção `voice` em `lumen/study/settings.py` (`DEFAULTS`), validada como as outras. Campos:
  - `engine`, `fallback`, `voice_id` (padrão `1faf41ee`);
  - `voices_by_use`: uma voz por uso (`chat`, `summary`, `review`, `practice`; vazio quer dizer a padrão);
  - `speed` (de 0,7 a 1,3), `language` (`pt`), `seed` (fixa, para a voz soar igual todo dia) e `style` (as tags de `instruct` que o motor aceita; leia o vocabulário pela API, não escreva uma lista fixa no código);
  - `autoplay` (desligado), `read` (`answer` ou `short`, que lê só o primeiro parágrafo) e `verify_long` (ligado);
  - `summary_after_lesson` (desligado, porque gasta a placa).
- **Rotas** (nomes de exemplo): `GET /api/study/voice/state`, `GET /api/study/voice/voices`, `GET /api/study/voice/sample/<id>`, `POST /api/study/voice/test` e `POST /api/voicestudio/open`. Use o mesmo token de janela das outras rotas.

### Etapa 2: as telas de voz (Integrações e Configurações)

- **Integrações → nova aba "Voice Studio"**, ao lado de Notion, Obsidian e Caderno:
  - um cartão de estado: Conectado, Fechado (com o botão Abrir) ou Carregando o modelo (com a barra de `progress`), mais a versão, a GPU e o motor ativo;
  - a **galeria de vozes**: uma linha por voz, como no próprio Voice Studio. Cada linha tem um avatar redondo (a imagem do perfil ou as iniciais, como "JS", sobre um gradiente com o acento do app), o nome, o selo "Clonada" ou "Criada", o idioma e três ações: ▶ ouvir a referência, "Testar" (gera uma frase de exemplo em português) e ★ "Usar como padrão";
  - a voz padrão aparece com o selo "Padrão". "Editar" abre o Voice Studio. Não há "Excluir".
- **Estudos → Configurações da IA → nova seção "Voz"** (ícone `volume`), entre "Personalização" e "Privacidade":
  - motor e reserva;
  - a voz padrão, com o mesmo componente de linha de voz;
  - uma voz por uso;
  - velocidade num controle deslizante, com prévia ao soltar;
  - estilo, idioma, seed, leitura automática e o que ler;
  - um "Testar a voz" com texto editável.
- **Desenho:**
  - siga `docs/DESIGN.md` (tokens, componentes de `ui.css` e o checklist "Tela nova"). Nos Estudos, use o prefixo `st-` (as classes globais `.ai` e `.empty` colidem);
  - ícones de `icons.svg`: `volume`, `wave`, `play`, `pause`, `stop`, `record`, `sparkle` e `external`;
  - o avatar que estiver falando pulsa com um anel animado pela amplitude real (`AnalyserNode` do WebAudio). Com `prefers-reduced-motion`, o anel fica parado;
  - teste nas larguras de 1100, 760 e 520 px, nos temas claro e escuro, com navegação por teclado e `aria-live` no estado da fala.

Esboço da aba (o desenho final segue os tokens):

```
┌ Voice Studio ─────────────────────────────── ● Conectado · v0.5.7 · RTX 3060 ┐
│  Vozes clonadas e criadas no seu PC. Nada sai daqui.        [Abrir o Voice Studio ↗] │
├──────────────────────────────────────────────────────────────────────────────┤
│ (JS)  Jhonny Sirverhand   Clonada · pt   ★ Padrão        [▶] [Testar] [✎ ↗]   │
│ (DV)  Demo Voice          Clonada · en                   [▶] [Testar] [★] [✎ ↗]│
└──────────────────────────────────────────────────────────────────────────────┘
```

### Etapa 3: a voz no chat (falar e ouvir)

- **"Ouvir" em cada resposta:**
  - o texto passa por `speakable()` e é dividido por `sentences()`;
  - as frases são geradas uma de cada vez e tocam assim que a primeira fica pronta, pelo `/ws/tts` ou frase a frase (meça os dois e fique com o de menor tempo até o primeiro som);
  - há pausar, parar e pular frase, e a frase que está tocando fica destacada na resposta;
  - a fala para quando o estudante começa a falar ou manda outra mensagem.
- **Conversa por voz:**
  - botão "apertar para falar", com a barra de espaço segurada fora da caixa de texto;
  - grava pelo Python com `soundcard` (veja `lumen/record.py`) e transcreve com `transcribe.transcribe` em português;
  - o texto aparece na caixa para conferir e é enviado. Há um interruptor "enviar sozinho";
  - a resposta é lida com a voz do uso `chat`.
- **Barra de fala:** fica fixa sobre a caixa de mensagem enquanto o Lúmen fala, com o avatar, o nome da voz, a onda ao vivo e os controles.

```
┌───────────────────────────────────────────────────────────────┐
│ (JS)◉  Jhonny · falando  ▁▃▅▇▅▃▁▂▅▇   frase 2 de 7   ⏸  ⏭  ■   │
└───────────────────────────────────────────────────────────────┘
```

### Etapa 4: o resumo em áudio da aula e a revisão em áudio

- **Resumo da aula:**
  - o botão "Gerar resumo em áudio" fica na aula pronta (Biblioteca e tela de resultado), e o ajuste `summary_after_lesson` gera o áudio sozinho no fim do processamento;
  - o roteiro sai do resumo que a aula já tem, com um capítulo por seção. Não gere o texto de novo;
  - a geração vai pela fila de `jobs`, com `release_vram`, tempo previsto por `eta.py`, progresso e cancelar. Ao cancelar, nenhum arquivo pela metade fica (o `encode()` já grava num temporário);
  - a conferência pelo Whisper fica ligada, frase a frase (`verify_long`);
  - o arquivo é um `.m4a` com o volume igualado, em `MEDIA/audio`, e os capítulos vão num `.json` ao lado.
- **Revisão em áudio dos Estudos** (item 3 do STATUS): o mesmo caminho, com o roteiro em JSON com tetos (D18): pergunta, pausa e resposta.
- **Player com capítulos:** play e pausa, velocidade de 0,75 a 2x, a lista de capítulos clicável, a posição salva, o download e "Mostrar na pasta".
- **No Obsidian:** a opção de incluir o áudio na nota (`![[...m4a]]`, copiando para a pasta de anexos do cofre) passa pela prévia de gravação (D11). No Notion, só com confirmação, porque envia o arquivo para fora do PC.

### Etapa 5: o resto da fase 6, já com a voz nova

Itens 4 a 6 do STATUS:
- "Ver na aula (mm:ss)";
- Treino falado e Feynman por voz, com `mastery.record(..., origin="feynman")` e a origem nova em `mastery.ORIGINS`;
- tour narrado do diagrama, junto com o `light()` de `study-diagram.js`.

O Treino falado usa a voz do uso `practice`, para o estudante poder pôr uma voz diferente em cada personagem.

## 5. Medição e escolha do estudante (pergunte só isto)

- **Escuta cega:** use o mesmo roteiro de 106 palavras do `bench/voice_bench.py`, com o volume igualado e letras sorteadas, comparando:
  - A: Voice Studio com o Jhonny e `language: "pt"`;
  - B: Voice Studio com o Jhonny, sem idioma;
  - C: Chatterbox pt-br (D44).
  O estudante escolhe o idioma padrão e confirma se o Chatterbox continua como reserva.
- **Medições** (registre em `LUMEN_STUDY_AI_MODELS.md`):
  - tempo até o primeiro som no chat, nos dois caminhos (WS e frase a frase);
  - tempo de geração por minuto de áudio;
  - erro de palavras pela transcrição do próprio Lúmen;
  - VRAM com e sem o Ollama carregado;
  - o efeito de uma referência de até 20 s no custo fixo de 5 s. Se fizer diferença grande, **sugira** ao estudante criar no Voice Studio uma versão curta da voz. Não altere o perfil dele.

## 6. Prova

- **Testes:** um Voice Studio falso, no estilo de `tests/fake_notion.py`, com `/system/info`, `/model/status`, `/profiles`, `/v1/audio/speech` (um WAV de seno) e `/ws/tts`. Com ele, teste:
  - a escolha de motor e a reserva com o Voice Studio fechado;
  - a voz padrão sumida;
  - a validação dos ajustes;
  - o cancelamento na fila de `jobs`;
  - os tetos do roteiro;
  - a fala sem Markdown nem `[S#]`;
  - os capítulos do `.m4a`;
  - que nenhuma rota de escrita do Voice Studio é chamada (o falso registra tudo o que recebe).
- **`tests/study_ui.py`:** passos novos com áudio falso, cobrindo a aba Voice Studio, a seção Voz, "Ouvir", apertar para falar e o player, nas três larguras e sem erro de CSP.
- **Real, só leitura e com banco temporário (`LUMEN_DATA`):** uma resposta real lida pelo Jhonny e o resumo em áudio de uma aula de curso (não use documentos pessoais: veja as lições da fase 4).
- **Suíte inteira** com `-t .`. No fim, peça a um subagente com contexto novo, num modelo mais barato, para conferir o resultado contra este prompt.

## 7. Regras deste PC (resumo; as completas estão no topo de `PROMPT_LUMEN_STUDY_AI_V2.md`)

- **Instalar:** pode instalar sem perguntar se for grátis, de fonte oficial, no D: e registrado. Esta fase não deve precisar de nada novo.
- **Terminal:** é de administrador. Todo Edge aberto pelo Python leva `--do-not-de-elevate` (D19).
- **Lúmen aberto:** ele guarda o código antigo. Peça ao estudante para Sair pelo menu e abrir de novo. Não mate o processo dele, nem o Ollama, nem o Voice Studio.
- **Disco C:** está quase cheio. Limpe o `%TEMP%\lumen-*` que você criar.
- **Ao terminar a sessão:**
  - atualize o STATUS (tabela de fases e "Próximo passo"), as DECISÕES, o CHANGELOG e as MEDIDAS;
  - rode o `D:\Lumen\voz\bin\uv.exe cache clean`, com `UV_CACHE_DIR=D:\Lumen\cache\uv`;
  - registre o que ficou pendente.

## 8. Pronto quando

- O Lúmen lista as vozes do Voice Studio e fala com a voz do Jhonny por padrão, no chat, no resumo da aula e na revisão.
- O estudante troca a voz, a velocidade e o estilo pelas Configurações e por Integrações → Voice Studio, e ouve a prévia na hora.
- Com o Voice Studio fechado, o Lúmen avisa, oferece Abrir e usa a reserva escolhida, sempre dizendo qual voz está falando.
- Os testes e a suíte passam, as medições estão registradas e o estudante ouviu e aprovou as amostras.
