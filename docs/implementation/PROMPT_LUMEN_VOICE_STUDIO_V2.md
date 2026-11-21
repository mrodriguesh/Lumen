# Prompt: Voice Studio sem janela, modelos no Lúmen e voz otimizada (fase 6, parte 2)

> Cole isto numa sessão nova do Claude Code, aberta na pasta do Lúmen, ou diga: "Leia e execute `docs/implementation/PROMPT_LUMEN_VOICE_STUDIO_V2.md`".
> Modelo: **Claude Opus 5.5, esforço `xhigh`**. Se o limite de uso apertar, use o **Claude Sonnet 5.5 em `high`**. O Fable não está disponível, e o orçamento é zero.
> Modelos de voz: os que já estão instalados no Voice Studio. Nenhum download é necessário; baixar outro motor só se o estudante escolher na tela nova.

---

A primeira parte da fase 6 está pronta (`PROMPT_LUMEN_VOZ_VOICE_STUDIO.md`, D46 a D52): o Lúmen fala com a voz do Jhonny pelo Voice Studio. O estudante pediu três correções e uma ampliação.

1. **Não precisar abrir o Voice Studio na mão.** Hoje o Lúmen pede "Abra o Voice Studio" toda vez que o app está fechado. A voz tem que funcionar sozinha, de forma discreta.
2. **Escolher os modelos direto no Lúmen:**
   - os pacotes Rápido, Equilibrado, Qualidade e Máximo, que o Voice Studio mostra em "Pacotes de modelos";
   - os motores de voz e de transcrição;
   - instalar e remover modelos;
   - a qualidade por uso.
3. **Otimizar ao máximo,** com as informações da máquina: mais rápido, menos memória, menos disco no C:.
4. **Trazer as funções do Voice Studio que ajudam a estudar.**

## 1. Situe-se primeiro

Leia, nesta ordem:

1. `docs/implementation/LUMEN_STUDY_AI_STATUS.md`, fase 6, com as pendências.
2. `LUMEN_STUDY_AI_DECISIONS.md`, de D44 a D52.
3. `LUMEN_STUDY_AI_MODELS.md`, seção Voz.
4. O código da voz:
   - `lumen/voicestudio.py`: o cliente, `status()`, `open_app()`, `mark()` e `unload_if_ours()`;
   - `lumen/study/listen.py`: quem fala, a fala do chat, os áudios longos e as rotas `/api/study/voice/*`;
   - `lumen/voice.py`, `lumen/web/voice.js` e a seção Voz de `lumen/web/study-settings.js`;
   - `tests/test_study_voice.py`, com o Voice Studio falso.

Depois confira:
- se os testes da voz e o passo 10 de `tests/study_ui.py` passam, antes de mexer;
- se o estudante já respondeu a escuta cega da fase 6 (amostras em `D:\Lumen\voz\amostras-vs`). Se respondeu, aplique a escolha antes de qualquer outra coisa.

## 2. O que já foi levantado (02/11/2026, Voice Studio 0.5.7)

Confira de novo antes de usar, porque o app se atualiza sozinho.

### 2.1 Como o app sobe o backend

O Electron (`resources\app.asar`, `out/main/index.js`) roda:

```
%APPDATA%\VoiceStudio\runtime\project\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 3900
```

- **Pasta de trabalho:** `%APPDATA%\VoiceStudio\runtime\project`.
- **Ambiente:** `PYTHONUNBUFFERED=1`, `PYTHONUTF8=1`, `OMNIVOICE_PORT=3900` e `OMNIVOICE_DESKTOP_CONTAINED=1`. Ele tira `PYTHONHOME` e `PYTHONPATH`.
- **Dois processos:** o `python.exe` do `.venv` abre o CPython de verdade, em `runtime\.python\cpython-3.11-...`.
- **O backend morre junto com o pai:** com `OMNIVOICE_DESKTOP_CONTAINED=1`, quando a entrada padrão (stdin, um pipe) fecha, o backend sai sozinho (`backend/core/parent_liveness.py`).
- **O app se conecta a um backend que já está rodando:** ao abrir, o Electron primeiro testa `GET /health`. Se a resposta vier com o cabeçalho `x-omnivoice-backend` e `{"status":"ok","version":...}`, ele se conecta (`start()` → `probe()` → `markReady`, com `managed: false`) e não abre outro. Se a porta estiver ocupada por outra coisa, ele mostra `port_in_use`.
- **A pasta `runtime\project` é uma cópia:** o app copia o backend de `resources` para lá a cada abertura (`stageRuntimeSources`). Depois de uma atualização, essa cópia só fica nova quando o app for aberto uma vez.
- **Não reproduza os dados de telemetria** que o Electron põe no ambiente (`POSTHOG_*`). A telemetria está desligada nas preferências dele.

### 2.2 Rotas que interessam

Todas pelo loopback e sem chave. As de escrita têm `require_admin`: confira se o loopback passa, primeiro no Voice Studio falso e depois numa chamada real que o estudante pediu.

**Saúde e máquina**
- `GET /health`;
- `GET /system/info`;
- `GET /model/status`;
- `GET /model/loaded`, com `vram_mb` por modelo e `system.ram_available_gb` e `vram_free_gb`;
- `GET /api/settings/gpu-report`;
- `GET /api/settings/storage`, com o disco e o tamanho por categoria;
- `GET /generate/budget`.

**Pacotes e qualidade**
- `GET` e `PUT /api/settings/performance-profile`. Os níveis são `fast`, `balanced`, `quality`, `max` e `auto`, com valor global ou por família (`tts`, `asr`, `dictation`, `translation`). Hoje está no `max`.
- Para a fala (`tts`), os níveis valem 8, 16, 32 e 64 passos (`services/performance_profiles.py`).
- **Esse nível só vale para as gerações do próprio app** (`/generate`, audiobook, lote, dublagem). O `/v1/audio/speech` e o `/ws/tts` usam o padrão do modelo, 16 passos.
- **O `/v1/audio/speech` aceita `num_step` e `guidance_scale` por pedido. O `/ws/tts` não aceita.**

**Modelos**
- `GET /models`: tamanho, instalado ou não, motores e `license_info`;
- `GET /setup/recommendations`: os pacotes da tela "Pacotes de modelos" para "Windows x64 + CUDA";
- `POST /models/install`, `GET /models/install/status`, `GET /setup/download-stream`, `POST /models/install/cancel` e `DELETE /models/{repo_id}`.

**Motores**
- `GET /engines/tts` e `GET /engines/asr`;
- `POST /engines/select`;
- `POST /engines/{id}/install` (motores à parte);
- `GET /engines/{id}/health` e `POST /engines/{id}/selftest`;
- `GET /engines/effects/presets`.
- Disponíveis hoje: `omnivoice`, `omnivoice-subprocess` e `kittentts` (só inglês). Instaláveis com um clique: CosyVoice 3, VoxCPM2, MOSS-TTS-Nano, IndexTTS2, Supertonic3, PocketTTS e outros.

**Ajustes de desempenho**
- `/api/settings/perf/offload-after-generation`, hoje desligado;
- `/api/settings/perf/torch-compile-disabled`;
- `/api/settings/compute-device`;
- `/api/settings/storage/models-dir`;
- `POST /api/settings/storage/temp/clear`;
- `POST /setup/warmup`.

**Funções extras**
- `/pronunciation` (com `/pronunciation/test`, `export` e `import`);
- `POST /design/describe` (criar voz por descrição);
- `/profiles` (com `consent` e `attestation`);
- `/stories/encode`;
- `/longform/jobs`;
- dublagem (`dub_*`) e `/v1/audio/transcriptions`.

### 2.3 A máquina, medida pela API em 02/11

| Item | Valor |
|---|---|
| CPU | i5-11400F, 12 threads |
| RAM | 15,8 GB, **com 2,6 GB livres** no momento da leitura |
| Placa | RTX 3060 de 12 GB, com 8,8 GB livres e o OmniVoice carregado (1,9 GB) |
| Torch | 2.8.0+cu128 |
| Disco C: | **91,7% usado, 18,5 GB livres.** O mínimo do Voice Studio é 10 GB |
| Modelos do Voice Studio | **23 GB em `%LOCALAPPDATA%\OmniVoice\hf_cache`**, no C:: OmniVoice 6,5 GB, Whisper large-v3 6,2 GB, NLLB 5,0 GB, Whisper turbo 3,2 GB, Parakeet 1,3 GB e outros |
| Disco D: | cerca de 800 GB livres |

**Medidas da fase 6 (MODELS.md → Voz):**
- 0,42 s de geração por segundo de fala;
- primeiro som no chat em 2,4 a 2,7 s;
- carga a frio do modelo em cerca de 9 s;
- pico de 11,25 GB de 12 com o `qwen3.5:4b` e a voz juntos.

## 3. Decisões que este prompt já toma (registre como D53 em diante)

1. **Backend sem janela, sob demanda.**
   - Quando a voz for usada e a porta 3900 não responder, o Lúmen sobe o backend do Voice Studio sozinho e sem janela (`CREATE_NO_WINDOW`).
   - Usa o mesmo comando, a mesma pasta e o mesmo ambiente do app, com `OMNIVOICE_DESKTOP_CONTAINED=1` e a entrada padrão num pipe que o Lúmen segura. Se o Lúmen fechar ou cair, o backend sai junto, e nada fica preso na RAM ou na placa.
   - **Nada de janela, nada de ícone, nada de abrir o Electron.**
   - Se o estudante abrir o Voice Studio enquanto isso, o app se conecta ao mesmo backend. Teste os dois sentidos e registre:
     - abrir o app com o backend do Lúmen rodando;
     - fechar o Lúmen com o app aberto (o Electron deve subir o dele de novo);
     - fechar o app com o backend do Lúmen rodando.
2. **Quem é dono do backend.**
   - Se a 3900 já responde com `x-omnivoice-backend`, o Lúmen só usa: não sobe outro e não desliga.
   - Se responde sem o cabeçalho, é outro programa: avise e não suba nada.
   - O backend que o Lúmen subiu é dele. Desliga sozinho depois de X minutos sem uso (ajuste, padrão 15), **a menos que o `VoiceStudio.exe` esteja aberto**, porque aí o estudante pode estar usando.
   - Desligar fecha o pipe da entrada. Se o processo não sair em 10 s, `taskkill /T` na árvore dele, que só tem processos que o Lúmen criou.
   - Um arquivo de trava em `DATA` impede duas instâncias do Lúmen de subirem dois backends.
3. **Versão.**
   - Antes de subir, compare a versão da cópia em `runtime\project\pyproject.toml` com a de `resources\pyproject.toml`.
   - Se forem diferentes (o app foi atualizado e ainda não foi aberto), o Lúmen não roda a cópia velha: abre o app uma vez, minimizado, e explica numa linha por quê.
   - Se o `runtime\project\.runtime-ready` não existir, o Voice Studio ainda não foi instalado direito: mostre "Termine a instalação no Voice Studio".
4. **Pré-aquecer:** carregue o modelo antes da primeira frase precisar dele (`POST /setup/warmup` ou um pedido curto descartado).
   - Quando o estudante abrir os Estudos com a leitura automática ligada.
   - Quando apertar "Ouvir".
   - Quando uma resposta começar a chegar com a voz ligada.
   - Assim a carga a frio (subir o backend mais cerca de 9 s do modelo) acontece em paralelo com o texto.
   - Mostre o estado na barra de fala ("Preparando a voz…" com o progresso de `/model/status`), nunca uma caixa de erro.
5. **Escrever nos ajustes do Voice Studio só por ação explícita do estudante numa tela do Lúmen.** Isso revê D46, em que o Lúmen não escrevia nada.
   - Vale para nível, motor, instalar, remover, mover a pasta, pronúncias e vozes novas.
   - Cada controle diz "Isto muda também no Voice Studio".
   - Nada muda sozinho.
   - O Voice Studio falso dos testes registra cada escrita, e um teste prova que nenhuma escrita acontece sem o clique.
   - Continua proibido: apagar vozes, apagar o histórico dele e desligar a marca d'água.
6. **Qualidade por uso sem mexer no global.** A fala do Lúmen escolhe os passos por pedido (`num_step` no `/v1/audio/speech`): um valor para o chat e outro para os áudios longos. O nível global do Voice Studio só muda se o estudante mexer nele na tela de pacotes.
7. **Os modelos do Voice Studio no D:.**
   - Ofereça, com uma pergunta clara e o tamanho, mover a pasta para `D:\Lumen\voicestudio\models`, por `PUT /api/settings/storage/models-dir`.
   - Siga o que a rota pede: `restart_required`, cópia, conferência dos arquivos e só depois apagar no C:, se a rota não fizer isso sozinha. Leia o código dela antes.
   - **Pergunte antes.** São cerca de 23 GB de arquivos do estudante.
   - O backend que o Lúmen sobe também usa `TEMP` e `TMP` numa pasta do D: (`D:\Lumen\cache\voicestudio-tmp`).
   - **Nunca** troque `HF_HOME` nem `OMNIVOICE_CACHE_DIR` por conta própria: com o caminho errado, ele baixa tudo de novo.

## 4. O que construir, em etapas (cada uma termina testada antes da próxima)

### Etapa 1: o backend sem janela (o pedido número 1)

- **Em `lumen/voicestudio.py`:** `ensure_running(check, progress)`, `stop_if_ours()` e um vigia de uso parado.
  - Sem módulo novo se couber no arquivo.
  - O que o backend imprime vai para um log que gira, em `D:\Lumen\logs\voicestudio.log`, com um tamanho máximo. Esvazie os pipes para o processo não travar.
- **`listen.py`:** onde hoje levanta `voicestudio.CLOSED`, chama `ensure_running` primeiro. A reserva (Chatterbox) só entra se subir o backend falhar, sempre com o aviso de qual voz fala.
- **Ajustes em `settings.DEFAULTS["voice"]`:**
  - `vs_autostart`: ligado;
  - `vs_idle_minutes`: 15;
  - `vs_warm_on_open`: desligado. Com ele ligado, sobe o backend e carrega o modelo quando o Lúmen abre.
- **Na tela:** o estado em Integrações → Voice Studio passa a ser:
  - "Pronto (rodando em segundo plano)";
  - "Pronto (o app está aberto)";
  - "Preparando a voz… 40%";
  - "Desligado, liga sozinho quando precisar".
  O botão "Abrir o Voice Studio" vira uma ação secundária ("Abrir o app"), não um requisito.
- **Prova:**
  - testes com um backend falso que demora a subir, que falha ou que já está rodando;
  - a porta ocupada por outro programa;
  - a trava entre duas instâncias;
  - o desligamento por uso parado, que não acontece com o `VoiceStudio.exe` aberto;
  - nenhuma janela;
  - teste real, com o Voice Studio fechado: a primeira fala do Lúmen sobe o backend sem janela (meça o tempo até o primeiro som a frio), e depois abrir o app conecta nele.

### Etapa 2: os modelos no Lúmen (o pedido número 2)

- **Lugar:** uma seção "Modelos de voz" em Integrações → Voice Studio, com o resumo e um atalho em Estudos → Configurações → Voz.
- **Pacotes:**
  - quatro botões segmentados, como na tela do Voice Studio, mais o "Automático";
  - cada nível mostra os modelos, o que já está instalado e quanto falta baixar;
  - um botão "Usar pacote X", com confirmação quando houver download, dizendo o tamanho e o disco onde vai ficar.
- **Modelos:** cartões com o ícone do papel (voz, transcrição, tradução, ditado), o nome, o tamanho, "instalado" ou "Baixar", a licença (`license_info`, curta, com "uso pessoal" quando for não comercial; os pesos do OmniVoice são CC-BY-NC) e "Remover", com confirmação.
  - O download mostra o progresso real, por `download-stream` ou `install/status`, e tem Cancelar.
  - Bloqueie o download se o disco de destino ficar abaixo de 10 GB livres.
- **Motores:** um seletor por família (voz e transcrição) com os motores de `/engines/*`. Os indisponíveis aparecem esmaecidos, com o motivo e "Instalar" quando houver um clique.
  - O motor de voz do Lúmen precisa clonar (`supports_cloning`) e falar português. Os outros aparecem com o aviso ("só inglês", "não clona").
- **Qualidade por uso:** "Fala do chat" e "Áudios longos", de Rápido a Máximo, convertidos em `num_step` pelo Lúmen. O padrão sai da medição da etapa 3, não de chute.
- **Transcrição do Lúmen:** o modelo do "apertar para falar" e o da conferência (hoje o Whisper `small`) aparecem na mesma seção, com o tamanho e a VRAM. É o Whisper do próprio Lúmen, não o do Voice Studio.
- **Pasta dos modelos:** mostra onde estão e quanto ocupam, com o botão "Mover para o D:" (decisão 7).

### Etapa 3: otimização, com a máquina na tela (o pedido número 3)

- **Painel "Esta máquina"** em Configurações → Voz, ou Desempenho:
  - GPU, VRAM usada por quem (Ollama por `/api/ps`, Voice Studio por `/model/loaded`, Whisper do Lúmen);
  - RAM livre;
  - disco livre no C: e no D:;
  - o estado do backend;
  - os últimos tempos: primeiro som, geração por segundo de fala e passos usados.
  - Atualize só com a tela aberta, a cada 5 s, sem `nvidia-smi` em laço apertado.
- **Medir antes de escolher padrões** (registre em `LUMEN_STUDY_AI_MODELS.md`, com o mesmo roteiro de 106 palavras):
  - `num_step` de 8, 12, 16, 24 e 32: tempo, primeiro som, erro de palavras pelo Whisper do Lúmen, e **escuta cega do estudante** entre os dois ou três melhores;
  - o chat pelo `/ws/tts` (16 passos fixos) contra o HTTP em `pcm` com `num_step` menor, frase a frase. Fique com o menor tempo até o primeiro som que o estudante aprovar;
  - uma conexão WebSocket aberta para a resposta inteira, contra uma por frase;
  - `offload-after-generation` ligado e desligado (VRAM livre contra o tempo da frase seguinte);
  - o custo de RAM do Electron aberto contra o backend sem janela.
- **Otimizações para fazer** (cada uma com medida antes e depois):
  - pré-aquecimento (decisão 4);
  - **gerar a frase N+1 enquanto a N toca**, mantendo no máximo 2 adiantadas;
  - **cache de frases:** chave com o hash de motor, voz, texto, velocidade, passos, seed e idioma; WAV em `MEDIA/audio/cache`, com teto de tamanho (padrão 500 MB) e descarte dos mais antigos. "Ouvir" de novo e as frases repetidas da revisão saem na hora;
  - **"Automático" pela máquina:** com pouca VRAM livre (menos de 3 GB, a medir), o chat espera o Ollama soltar a placa ou cai para menos passos; com pouca RAM, não pré-aquece. Decida por números lidos na hora, não por suposição;
  - áudios longos: `llm.release_vram()` antes, como já faz, e o `eta` (`voice_rtf`) aprende por número de passos;
  - `TEMP` do backend no D: e "Limpar temporários do Voice Studio" (`/api/settings/storage/temp/clear`, com confirmação);
  - **meça antes de recomendar** `torch.compile`: o log mostra `TORCH_COMPILE_DISABLE` ligado, e no Windows ele costuma não ajudar. Se não ajudar, registre e deixe como está.
- **Meta:** medir e informar.
  - Primeiro som no chat com o modelo quente: abaixo de 1,5 s, se a escuta aprovar menos passos.
  - Primeira fala com tudo desligado: abaixo de 25 s.
  - Nenhum backend esquecido rodando depois de fechar o Lúmen.

### Etapa 4: funções do Voice Studio que ajudam a estudar (o pedido número 4)

Em ordem de valor para os cursos do estudante: marketing, Premiere, persuasão, negócios e inglês.

1. **Pronúncias** (`/pronunciation`):
   - Configurações → Voz → "Pronúncias", com a lista, a adição, o teste (ouvir como fica) e a importação e exportação;
   - o botão "Sugerir das minhas notas" encontra termos em inglês e siglas frequentes no índice (Premiere, keyframe, After Effects, copy, CTA, ROI…) e propõe a grafia falada, para o estudante aceitar um por um;
   - confira se o `/v1/audio/speech` aplica o dicionário. Se não aplicar, o Lúmen aplica no texto antes de enviar, pela mesma lista.
2. **Vozes por descrição** (`/design/describe`, com as tags de `instruct` do OmniVoice):
   - "Criar voz para personagem" (por exemplo, "cliente cético, homem, 40 anos" ou "recrutadora americana");
   - cria o perfil no Voice Studio com o nome marcado "(Lúmen)", só pelo clique do estudante.
3. **Treino falado** (a pendência da fase 6): role-play em turnos de voz, com venda, negociação e entrevista em inglês.
   - Cada personagem tem a sua voz (as criadas no item 2, ou as clonadas). O estudante fala pelo "apertar para falar".
   - No fim, uma avaliação por rubrica, que vai para o `mastery`.
4. **Revisão em formato de conversa:** a revisão em áudio com duas vozes (narrador e Jhonny), alternando pergunta e resposta.
   - Use o mix do próprio Lúmen (`voice.mix`). Veja se `/stories/encode` ajuda; se não, não use.
5. **Efeitos de voz** (`/engines/effects/presets`): se o `/v1/audio/speech` aceitar um preset, ofereça "efeito" por uso (por exemplo, um rádio leve para o Jhonny no chat). Se não aceitar, não implemente: registre e siga.
6. **Opcional, por último e só se as etapas 1 a 5 estiverem prontas:** "Dublar esta aula para português", para aulas em inglês da Biblioteca, pela dublagem do Voice Studio.
   - Meça o tempo e a VRAM numa aula curta de curso antes de pôr na tela.
   - Se passar de 3x a duração da aula, deixe só como ação manual, com aviso de tempo.

**Não traga:** ditado com o widget dele, chamadas telefônicas, compartilhamento em rede, MCP, nuvem ou marketplace. O Lúmen já tem o próprio caminho, ou a função não ajuda a estudar.

### Etapa 5: interface

- **Guia de desenho:** siga `docs/DESIGN.md`, `ui.css` e o checklist "Tela nova". Nos Estudos, use o prefixo `st-`.
- **Ícones** de `icons.svg`: `cpu`, `download`, `trash`, `volume`, `wave`, `sync`, `shield` e `external`.
- **Visual:** a tela de pacotes segue o visual da do Voice Studio (botões segmentados e cartões de modelo com a marca de instalado), com os tokens do Lúmen.
- **Painel da máquina:** barras finas com rótulo e número, sem gráfico pesado, e o texto dizendo o que fazer ("Pouca VRAM livre: a voz vai esperar a resposta terminar").
- **Larguras e acessibilidade:** 1440, 1100, 760 e 520 px, temas claro e escuro, teclado, `aria-live` nos estados e `prefers-reduced-motion`.

Esboço da seção nova:

```
┌ Voice Studio ─────────────── ● Pronto · em segundo plano · v0.5.7 ┐
│ A voz liga sozinha quando o Lúmen precisa e desliga após 15 min parada. │
│ [ ] Deixar pronta ao abrir o Lúmen          Abrir o app ↗         │
├ Modelos de voz ─────────────────────────────────────────────────┤
│ ( Rápido | Equilibrado | Qualidade | [Máximo] | Automático )      │
│ ▣ OmniVoice · voz · 2,4 GB · instalado ✓   ▣ Whisper large-v3 ✓   │
│ Pasta: C:\…\OmniVoice\hf_cache · 23 GB  [Mover para o D:]        │
├ Qualidade da fala do Lúmen ─────────────────────────────────────┤
│ Chat: Equilibrado (12 passos) ▾    Áudios longos: Qualidade ▾     │
├ Esta máquina ───────────────────────────────────────────────────┤
│ Placa  ████████░░░░ 7,9/12 GB  (Ollama 4,1 · Voz 1,9 · Lúmen 0,6) │
│ RAM    █████████████░ 13,2/15,8 GB    C: 18,5 GB livres  D: 800 GB │
│ Último: 1º som 1,3 s · 0,31 s por s de fala · 12 passos          │
└─────────────────────────────────────────────────────────────────┘
```

## 5. Prova

- **Testes**, ampliando o Voice Studio falso de `tests/test_study_voice.py`:
  - `/health` com o cabeçalho;
  - subida lenta, falha e porta de outro programa;
  - trava, uso parado e o `VoiceStudio.exe` aberto (com a lista de processos simulada);
  - versões diferentes;
  - pacotes, instalar com progresso e cancelar;
  - mover a pasta;
  - `num_step` por uso;
  - cache de frases (acerto, teto e descarte);
  - pronúncias aplicadas;
  - nenhuma escrita sem clique.
- **`tests/study_ui.py`:** passos novos para a seção Modelos de voz, o painel da máquina, as pronúncias e o Treino falado, nas quatro larguras e sem erro de CSP.
- **Real:** com o Voice Studio fechado, só leitura no cofre e banco temporário:
  - a primeira fala a frio;
  - abrir o app depois;
  - fechar o Lúmen e conferir que nenhum processo do backend sobrou.
  Não use documentos pessoais (lições da fase 4).
- **Suíte inteira** com `-t .`. No fim, peça a um subagente com contexto novo, num modelo mais barato, para conferir o resultado contra este prompt.

## 6. Regras deste PC

As completas estão em `PROMPT_CONTINUAR.md`. As que mais pesam aqui:

- **Terminal de administrador:** um backend subido pelo terminal do Claude Code roda como administrador. Nos testes reais, prefira que o Lúmen do estudante suba o backend, depois de Sair e abrir de novo. Se precisar subir pelo terminal, desligue no fim.
- **Não mate nada do estudante:** nem o `VoiceStudio.exe`, nem o backend que o app dele abriu, nem o Ollama, nem o Lúmen aberto. Para testar a subida a frio, peça ao estudante para fechar o Voice Studio.
- **O C: está quase cheio:** nada novo vai para lá. Limpe `%TEMP%\lumen-*`.
- **Ao terminar:**
  - atualize o STATUS (fase 6, com o "Próximo passo"), as DECISÕES (D53 em diante), o CHANGELOG e as MEDIDAS;
  - acrescente este prompt na tabela de `PROMPT_CONTINUAR.md`.

## 7. Perguntas ao estudante (só estas)

1. Mover os 23 GB de modelos do Voice Studio para o D:? Mostre o antes e o depois do espaço livre.
2. Escuta cega dos passos da fala do chat (os dois ou três melhores da medição).
3. Se o estudante não tiver respondido, a escuta cega da fase 6.
4. Fechar o Voice Studio e o Lúmen nos momentos dos testes reais.

## 8. Pronto quando

- Com o Voice Studio fechado, o Lúmen fala na voz do Jhonny sem pedir nada. Não aparece janela, e o backend desliga sozinho depois de parado.
- Abrir o app do Voice Studio com o Lúmen rodando funciona, sem conflito de porta.
- O estudante escolhe pacote, motor, qualidade por uso e modelos (baixar e remover) pelo Lúmen, e vê o que muda também no Voice Studio.
- O painel mostra a máquina de verdade, e os padrões de velocidade vêm de medição e da escuta dele.
- A primeira fala e o chat ficaram mais rápidos que as medidas de 02/11, com os números registrados.
- Pronúncias, vozes por descrição, Treino falado e revisão a duas vozes funcionam e estão testados.
- Testes e suíte passam, e a documentação está atualizada.
