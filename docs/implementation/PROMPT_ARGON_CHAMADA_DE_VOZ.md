# Prompt para o Antigravity (Gemini 4 Argon): chamada de voz em tempo real nos Estudos (fase 6, parte 3)

> **Como usar:** abra o Antigravity (app de desktop, CLI `agy` ou a extensão do VS Code; o Argon não aparece no editor avulso), abra a pasta `D:\Aplicativos\lumen 2026` como workspace e cole este arquivo inteiro numa conversa nova, ou peça: "Leia e execute `docs/implementation/PROMPT_ARGON_CHAMADA_DE_VOZ.md`".
> **Modelo:** Gemini 4 Argon, raciocínio **High**, no modo de planejamento (Planning). Se a cota semanal do Argon acabar no meio, a próxima sessão (no Argon ou no Claude Code com `PROMPT_CONTINUAR.md`) continua pelo `STATUS`.
> **Orçamento zero:** nada pago. Tudo roda neste PC.

---

Você vai continuar o **Lúmen Study AI 2.0**, a aba Estudos do app Lúmen, ainda na **fase 6 (voz)**. O pedido do estudante é uma **chamada de voz em tempo real com o chat**, parecida com o modo de voz do ChatGPT:

- ele fala, o Lúmen responde falando com as vozes clonadas do Voice Studio (a padrão é a do Jhonny), e a conversa segue como uma ligação;
- a conversa aparece em texto, ao vivo, dos dois lados;
- pela voz ele pode pedir o que já pede por texto, como "cria um mapa mental de…", "me faz um quiz", "explica com um diagrama" ou "olha minha tela";
- **o menor atraso possível** entre ele parar de falar e o Lúmen começar a responder;
- uma seção de **configurações da conversa por voz**.

Este repositório foi construído por outras sessões (Claude Code) com regras próprias, registradas nos documentos. Você não tem a memória delas: **tudo o que precisa saber está neste prompt e nos arquivos que ele manda ler.**

## 1. Antes de tudo: o que não pode acontecer

O estudante usa o app todos os dias, e o repositório tem **muito trabalho ainda não commitado** (branch `estudos`).

- **Git:** nunca rode `git checkout -- .`, `git reset`, `git clean`, `git stash` nem nada que descarte mudanças. Faça commit só se o estudante pedir.
- **Dados reais:** nunca toque no `%LOCALAPPDATA%\Lumen` real em teste: a configuração real já foi sobrescrita uma vez. Os testes e as medições usam `LUMEN_DATA` numa pasta temporária. Com `LUMEN_DATA`, os dados ficam em `<LUMEN_DATA>\Lumen\` e a mídia dos Estudos em `<LUMEN_DATA>\Lumen\study\media`.
- **Não mate nem reinicie o que é do estudante:** o Lúmen aberto (`pythonw -m lumen`), o Ollama e o Voice Studio (o `VoiceStudio.exe` e o backend em Python dele).
- **O Lúmen aberto guarda o código antigo.** Para ver o código novo, o estudante precisa Sair pelo menu e abrir de novo; peça isso a ele. O Lúmen aberto responde 403 sem o token da janela: não dá para usá-lo de fora.
- **Sem automação de mouse ou teclado na tela real.** Teste a interface com o Chrome ou o Edge sem janela, pelo servidor de teste (`tests/study_ui.py`, Playwright, rodado com `py -3.14`). O navegador do Antigravity só pode abrir o servidor de teste, nunca a instância real.
- **Edge aberto pelo Python com o terminal como administrador:** passe `--do-not-de-elevate` (D19). Sem isso, ele trava.
- **Microfone real:** não grave o microfone do estudante sem ele pedir. Nos testes, o microfone é simulado: arquivos WAV entram no lugar dele. Para fala de teste, gere frases com a própria voz do Voice Studio ou use as amostras de `D:\Lumen\voz\amostras-vs`.
- **Disco C: quase cheio:** nada grande vai para lá (modelos, caches, temporários). Use o D:. Limpe o `%TEMP%\lumen-*` que você criar.
- **Instalar:** pode instalar sem perguntar se for grátis, de fonte oficial, no D: (ou no `.venv` do projeto), sem quebrar o que existe e registrado no `CHANGELOG` (versão, tamanho, local e licença). **Não reinstale o `onnxruntime`:** o `.venv` usa o `onnxruntime-directml` no lugar dele.
- **Voice Studio** (D46 a D60):
  - o Lúmen fala com ele só por HTTP e WebSocket no loopback (`http://127.0.0.1:3900`), pelo backend, nunca pelo navegador. A CSP é `connect-src 'self'`;
  - escrever nos ajustes dele só com um clique do estudante numa tela do Lúmen (`voicestudio.write()`);
  - nunca apague vozes ou o histórico dele, nem desligue a marca d'água;
  - **nenhum teste sobe o Voice Studio real:** `tests/__init__.py` aponta os caminhos para uma pasta vazia e a URL para a porta 9, e o falso é `tests/fake_voicestudio.py`;
  - rodar um segundo backend real é perigoso, porque divide a pasta de dados e o SQLite com o app.

## 2. Situe-se, sem refazer o que já existe

Leia, nesta ordem:

1. `docs/implementation/LUMEN_STUDY_AI_STATUS.md`: tabela de fases, fase 6, "Próximo passo" e pendências.
2. `docs/implementation/LUMEN_STUDY_AI_DECISIONS.md`: de D20 em diante, **em especial D24, D27, D31, D32, D43 e D44 a D60**. As decisões valem mais que os prompts antigos.
3. `docs/implementation/LUMEN_STUDY_AI_MODELS.md`, seção Voz: as medidas deste PC.
4. `docs/DESIGN.md` inteiro: tokens, componentes e o checklist "Tela nova".
5. O código que você vai reaproveitar. Leia antes de escrever:
   - `lumen/study/listen.py`, com:
     - `who()`: quem fala;
     - `live()`: fala em pedaços, com o 1º pedaço curto (`FIRST_CHARS`, `_first_cut`), até 2 frases prontas à frente (`AHEAD`) e o cache de frases;
     - `Mic`: o microfone pelo `soundcard`, 48 kHz levados a 16 kHz;
     - `heard()`: a transcrição;
     - `_prepare` e `warm()`: o pré-aquecimento;
     - `_short_vram()` e `_make_room()`;
     - `STEPS`: passos do OmniVoice por pedido;
     - as rotas `/api/study/voice/*`;
   - `lumen/voicestudio.py`: o cliente, o backend sem janela (`BACKEND.ensure`) e o `/v1/audio/speech` em PCM com `num_step`;
   - `lumen/voice.py`: `speakable()` (tira Markdown e `[S#]`) e `sentences()`;
   - `lumen/transcribe.py`: Whisper (faster-whisper), **Parakeet TDT 0.6b v3 em ONNX int8** e o **VAD Silero em ONNX** (`ONNX_REPOS`), já baixados;
   - `lumen/loopback.py`, com `microphone()`, e `lumen/record.py`, com `active()`;
   - `lumen/study/agent.py`: a resposta com streaming, o roteador (`ROUTER_RULES` e a Função inteligente, D32), os níveis de esforço (D31) e os modos (`mindmap`, `quiz`, `flashcards`, `map`, `plan`…);
   - `lumen/llm.py`: Ollama, com `keep_alive`, `num_ctx` e `release_vram`;
   - `lumen/web/voice.js`: WebAudio, a barra de fala, o "apertar para falar" e as telas do Voice Studio. Também `lumen/web/study.js` e `study-settings.js` (seção Voz);
   - `tests/test_study_voice.py`, `tests/fake_voicestudio.py` e `tests/study_ui.py`, passo 10.
6. Confira com `git status` e com os testes da voz se o repositório bate com o `STATUS`. Se algo não bater, conserte primeiro e registre.

## 3. Fatos deste PC (medidos em 02/11/2026; confira de novo)

**A máquina**
- i5-11400F com 12 threads, 15,8 GB de RAM (muitas vezes só 2,5 a 3 GB livres) e RTX 3060 de 12 GB.
- O Python do `.venv` é o 3.14.
- A placa é dividida:
  - o `qwen3.5:4b` (o modelo Automático, com 32k de contexto, D24) e os embeddings ficam no Ollama;
  - o OmniVoice ocupa cerca de 2,7 GB carregado, mais cerca de 2,2 GB no pico de geração;
  - com o 4b e a voz juntos, o pico foi de **11,25 GB de 12**. Não sobra para mais um modelo grande na placa.

**Voz (Voice Studio 0.5.7, OmniVoice, voz do Jhonny `1faf41ee`, `language: "pt"`)**
- Geração: 0,33 s (12 passos) a 0,42 s (16 passos) por segundo de fala, com 0% de erro de palavras com `pt`.
- 1º som no chat com o modelo quente: cerca de 1,5 s com 12 passos e cerca de 1,9 s com 16. O estudante escolheu 16 passos para o chat na escuta cega (D56).
- A frio, com o backend desligado, o 1º som levou de 41 a 74 s.
- O `/ws/tts` não aceita `num_step` nem semente; por isso a fala do chat vai pelo `/v1/audio/speech` em PCM (D48, D56).

**Texto**
- O `qwen3.5:4b` sem raciocínio responde rápido. O nível Rápido é o próprio Automático (D31).
- Os níveis Profundo e Máximo carregam o `qwen3.5:9b`. Trocar de modelo custa de 10 a 142 s, porque os modelos ficam num HD.
- Mudar o `num_ctx` faz o Ollama recarregar o modelo (D24).

**Transcrição**
- O "apertar para falar" (D50) usa o modelo dos Ajustes (`large-v3-turbo`, na placa), em português.
- O Parakeet ONNX int8 roda na CPU e já está baixado.

## 4. O que construir

### 4.1 A chamada (interface)

Um botão **"Conversa por voz"** (ícone de onda) ao lado da caixa de mensagem e um destino no Ctrl+K. Ele abre a **visão de chamada** dentro dos Estudos, no lugar do chat, com a conversa atual.

- **No centro:** o avatar da voz que está falando (a imagem do perfil ou as iniciais, como "JS") dentro de um **orbe animado**. Ele muda com o estado:
  - **Ouvindo:** reage ao nível do microfone.
  - **Entendi:** um pulso curto quando a vez do estudante termina.
  - **Pensando:** uma respiração lenta.
  - **Falando:** a onda segue a amplitude real da voz.
  Use só os tokens do `DESIGN.md`. Com `prefers-reduced-motion`, nada se mexe: só a cor e o texto mudam.
- **Legenda ao vivo, abaixo do orbe:**
  - a fala do estudante aparece aos poucos (o texto parcial em cinza, o final em cor normal);
  - a resposta do Lúmen aparece junto com a voz, com a frase que está tocando destacada;
  - interrompida, a resposta fica até onde foi falada, com a marca "interrompida".
- **Cartões:** quando um pedido gera algo visual (mapa mental, diagrama, quiz, flashcards, plano, captura de tela), um cartão aparece na legenda com o resultado de verdade. É o mesmo componente que o chat já usa: não crie outro. A voz diz só uma frase curta sobre ele ("Pronto, o mapa mental tem seis ramos; está na tela.").
- **Controles:**
  - microfone ligado ou mudo;
  - "Falar agora" (interrompe o Lúmen);
  - trocar a voz;
  - legendas sim ou não;
  - minimizar;
  - **encerrar**, um botão vermelho, que também funciona com Esc.
  - O cronômetro da chamada e o estado em texto ficam em `aria-live`.
- **Minimizar:** vira uma pílula flutuante (avatar, estado, mudo e encerrar), e a chamada continua enquanto o estudante navega pelo app.
- **Microfone aberto sempre visível:** um ponto vermelho com "Microfone aberto". Com o microfone mudo, o ponto some.
- **Ao encerrar:** a conversa volta ao chat normal com tudo em texto (as falas dos dois e os cartões), salva no histórico como qualquer conversa. Na conversa temporária, nada é salvo.
- **Larguras:** 1440, 1100, 760 e 520 px, temas claro e escuro, navegação só por teclado e sem erro de CSP.

Esboço (o visual final segue os tokens):

```
┌ Conversa por voz · 03:12 ────────────────────── ● Microfone aberto ┐
│                                                                    │
│                        ╭──────────────╮                            │
│                        │   ◉  (JS)  ◉   │  ← orbe que reage         │
│                        ╰──────────────╯                            │
│                     Jhonny · falando…                              │
│                                                                    │
│  Você: cria um mapa mental de copywriting pra anúncio              │
│  Lúmen: Pronto, montei com seis ramos. ▸ [cartão do mapa mental]   │
│  Você: explica o terceiro ramo…                                    │
│                                                                    │
│   [🎙 Mudo]   [✋ Falar agora]   [Voz ▾]   [CC]   [—]   [⏺ Encerrar] │
└────────────────────────────────────────────────────────────────────┘
```

### 4.2 Configurações → Voz → "Conversa por voz" (seção nova)

Cada ajuste é validado em `settings.DEFAULTS["voice"]`, como os outros (chaves planas, D51). Os padrões vêm da medição (seção 5), não de chute.

| Ajuste | Valores | O que faz |
|---|---|---|
| Modo | mãos livres / apertar para falar / tocar para falar | Mãos livres detecta o fim da fala sozinho (VAD); os outros dois usam o botão ou a barra de espaço |
| Fim da fala | rápido, normal ou paciente (por exemplo 450, 700 ou 1100 ms de silêncio, a medir) | Quanto silêncio encerra a vez do estudante |
| Interromper falando | ligado / desligado | O estudante fala por cima e o Lúmen para (veja o eco, em 4.4) |
| Estou de fone | ligado / desligado | Com fone, a interrupção pela voz fica sensível; com caixa de som, fica conservadora ou desligada |
| Resposta antecipada | ligado / desligado | Começa a transcrever e pensar no meio do silêncio e descarta se o estudante voltar a falar (4.3) |
| Microfone | a lista dos microfones do Windows | Padrão: o do sistema |
| Voz da chamada | as vozes do Voice Studio | Um uso novo, `call`, ao lado de `chat`, `summary`, `review` e `practice` |
| Velocidade e qualidade da voz | 0,7 a 1,3; Rápido, Equilibrado ou Qualidade | A qualidade é em passos (`STEPS`). O padrão da chamada sai da medição; o estudante pode preferir 16, como no chat |
| Tamanho das respostas | curta (1 a 3 frases) / conversa / detalhada | Muda as instruções do modelo na chamada |
| Esforço na chamada | Automático (teto Equilibrado) / Rápido / Equilibrado | Profundo e Máximo só quando pedidos pela voz ("pensa com calma"). O Lúmen avisa quanto vai levar |
| Som de "entendi" | ligado / desligado | Um som curto e suave quando a vez do estudante termina, para ele saber na hora que foi ouvido |
| Preencher a espera | desligado / ligado | Se a primeira fala demorar mais que X ms, toca uma frase curta já guardada ("Deixa eu ver…"), no máximo uma por vez |
| Transcrição da chamada | Automático / Parakeet (CPU) / Whisper turbo (placa) | O Automático escolhe pela VRAM livre na hora |
| Legendas | ligadas / desligadas | — |
| Encerrar sozinho | 2, 5 ou 10 min de silêncio / nunca | Fecha o microfone se ninguém falar |
| Guardar a conversa | no histórico / como conversa temporária | O áudio nunca é guardado, só o texto |
| Mostrar os tempos | desligado | Mostra, em cada turno, o tempo de cada etapa (para medir) |

### 4.3 O caminho da fala (onde a velocidade é ganha)

Crie `lumen/study/call.py` com uma máquina de estados de uma chamada por vez:

```
ouvindo → falando (estudante) → fim da fala → transcrevendo → pensando → respondendo → ouvindo
```

O backend é um `ThreadingHTTPServer`, sem WebSocket. Use o mesmo padrão do `/api/study/voice/say`:
- **eventos para a tela:** uma resposta HTTP longa, em linhas JSON, por `fetch` com `reader`, em `/api/study/call/events`. Os eventos são `state`, `level`, `partial`, `final`, `token`, `sentence`, `card`, `timing` e `error`;
- **comandos:** por `POST /api/study/call` (`start`, `stop`, `mute`, `interrupt`, `ptt_down`, `ptt_up`, `settings`);
- **token:** o mesmo da janela (`X-Lumen-Token`), como nas outras rotas.

**Etapas, cada uma com o tempo medido:**

1. **Microfone contínuo.** Amplie o `Mic` para um modo contínuo: quadros de 20 a 32 ms, 48 kHz levados a 16 kHz, um anel de cerca de 300 ms antes do início da fala (para não cortar a primeira sílaba) e o nível para o orbe.
   - Não abra durante a gravação de uma aula (`record.active()`) e não espere uma aula ser processada.
2. **VAD Silero ONNX na CPU** (o modelo já está em `transcribe.ONNX_REPOS`), por quadro. O fim da fala é o silêncio do ajuste, com um teto de duração.
3. **Legenda parcial:** a cada cerca de 600 ms de fala, transcreva o trecho até ali para mostrar o texto parcial, só se isso não atrasar o final. Se atrasar, desligue e registre.
4. **Transcrição final**, assim que a fala acaba, só do trecho do turno:
   - meça o Parakeet int8 na CPU contra o Whisper turbo na placa e contra o Whisper `small`;
   - a meta é menos de 400 ms para 5 s de fala;
   - **durante a chamada, a transcrição não pode tirar o Ollama nem o OmniVoice da placa:** nada de `llm.release_vram()` no meio de uma chamada.
5. **Resposta antecipada** (se ligada): com cerca de 250 ms de silêncio, já transcreva e comece a resposta. Se o estudante voltar a falar antes do fim da fala, cancele tudo (transcrição, modelo e voz) e descarte. Nada que foi descartado aparece na tela.
6. **O modelo de texto:**
   - na chamada, pelo mesmo caminho do chat (`agent`), com o roteador decidindo o modo. Assim "mapa mental", "quiz" e "diagrama" funcionam igual ao texto;
   - instruções próprias da chamada: fala natural, frases curtas, sem Markdown, sem listas e sem "veja abaixo";
   - o que for visual vai num cartão, e a voz só o comenta;
   - as citações `[S#]` ficam no texto e somem da voz (`speakable`);
   - **mantenha o modelo quente:** na abertura da chamada, carregue o modelo e a voz em paralelo (`warm`) e use um `keep_alive` longo enquanto ela durar;
   - não mude o `num_ctx` só para a chamada (forçaria recarregar, D24), a menos que a medição mostre ganho e você registre a decisão;
   - a busca nas notas roda junto com a transcrição final, pelo texto parcial, sempre que der.
7. **Texto para a voz em fluxo:**
   - assim que o modelo escrever a primeira oração com sentido (uma vírgula ou um ponto depois de cerca de 25 a 40 caracteres; meça), ela vai para o Voice Studio;
   - as seguintes vão por frase, com até 2 prontas à frente (`AHEAD`);
   - reaproveite o `live()` e o `_first_cut()`, sem duplicar;
   - meça a ideia de gerar **só o primeiro pedaço com menos passos** (8 ou 12) e o resto na qualidade escolhida. Só adote se o estudante não ouvir diferença numa escuta cega.
8. **Tocar:**
   - meça e escolha entre tocar no navegador (WebAudio, como hoje) e tocar pelo Python (`soundcard`);
   - a recomendação é **pelo Python**, porque o mesmo processo que ouve o microfone sabe o que está tocando: a interrupção fica imediata, o eco pode ser descontado, e a chamada continua com a janela minimizada. A tela recebe o nível da voz pelos eventos, para o orbe;
   - registre a escolha com os números.
9. **Interromper:**
   - com voz por cima (se o ajuste deixar) ou com "Falar agora" e a barra de espaço, a fala para em até cerca de 150 ms (com uma descida suave de cerca de 50 ms);
   - cancela as frases na fila e a resposta do modelo;
   - guarda no texto até onde foi falado;
   - e volta a ouvir.
10. **Comandos rápidos, sem passar pelo modelo** (regras, como o roteador faz): "para", "repete", "mais devagar", "mais rápido", "fala mais baixo" e "encerra a chamada".

**Meta, medida do último som da fala do estudante ao primeiro som da resposta, com tudo quente:**
- mediana **até 2,0 s** e 9 de 10 turnos até 3,0 s;
- o som de "entendi" em até 300 ms;
- se não chegar lá, mostre onde o tempo foi (etapa por etapa) e o que mais custaria.

Na primeira chamada a frio, a tela diz "Preparando a voz…", com o progresso real (D54), nunca uma caixa de erro.

### 4.4 Eco (caixa de som) e privacidade

**O eco:** com caixa de som, a voz do Jhonny volta pelo microfone e pode parecer o estudante falando. Faça nesta ordem e meça os disparos falsos em cada uma:
1. **com fone ("Estou de fone"):** a interrupção pela voz fica sensível;
2. **com caixa de som:**
   - um cancelamento de eco, se existir um pacote grátis, de licença compatível e com versão para o Python 3.14 do Windows;
   - se não existir, uma barreira de energia: o Lúmen sabe o que está tocando e só aceita interrupção quando o microfone fica bem acima do eco esperado, calibrado nas primeiras frases da chamada;
   - se ainda disparar sozinho, a interrupção pela voz fica desligada com caixa de som, e "Falar agora" e a barra de espaço sempre funcionam.
3. Registre o que ficou, com os números.

**Privacidade:**
- o áudio do microfone fica só na memória e nunca é gravado em arquivo, a não ser num temporário apagado logo depois da transcrição;
- o registro de atividades guarda só os tempos, sem conteúdo;
- "Salvar no Obsidian ou no Notion" pela voz **nunca grava sozinho**: abre a prévia (D11) e a voz diz "a prévia está na tela; confirme lá";
- Claude e qualquer provedor externo seguem a regra de envio externo dos Ajustes. O padrão é tudo local.

### 4.5 O que a voz pode pedir (reaproveitando o que existe)

Teste cada um ponta a ponta na chamada:
- mapa mental (`/mapa-mental`, D43);
- diagrama na explicação (D40, D41);
- flashcards;
- quiz por voz: o Lúmen lê a pergunta, espera a resposta falada, corrige e registra no `mastery`, sem inventar acerto numa resposta "não sei";
- plano de estudo;
- "o que eu errei";
- Feynman ("vou te explicar…", D52);
- `/tela` ("olha minha tela", D36);
- revisão do dia;
- trocar de voz ("fala com a voz da demo").

Pedidos que gravam algo seguem a regra da prévia.

## 5. Medições (registre em `LUMEN_STUDY_AI_MODELS.md` → "Conversa por voz")

- Crie `bench/call_bench.py`, que toca falas de teste (geradas com a voz do Voice Studio e guardadas em `D:\Lumen\voz\amostras-chamada`) no lugar do microfone. Ele mede cada etapa, com mediana e 90º percentil em pelo menos 20 turnos:
  - fim da fala;
  - transcrição;
  - primeiro trecho do modelo;
  - primeiro áudio do Voice Studio;
  - primeiro som tocado.
- Rode com `LUMEN_DATA` temporário, o Ollama do estudante e o backend do Voice Studio que já estiver rodando. Não suba outro.
- Compare: Parakeet contra Whisper; silêncio de 450, 700 e 1100 ms; resposta antecipada ligada e desligada; primeiro pedaço com 8, 12 e 16 passos; tocar no navegador e no Python.
- Meça a VRAM e a RAM durante uma chamada de 10 minutos. Nada pode crescer sem parar.
- **Pergunte ao estudante só isto:**
  - a escuta cega dos passos do primeiro pedaço, se for testar a ideia;
  - um teste de 2 minutos com o microfone de verdade, quando ele puder, com fone e com caixa de som;
  - que ele Saia do Lúmen e abra de novo no fim, para ver na janela real.

## 6. Prova

- **Testes unitários** (`tests/test_study_call.py`), com microfone, transcrição, modelo e Voice Studio falsos:
  - a máquina de estados inteira;
  - o fim da fala;
  - a resposta antecipada cancelada sem deixar rastro;
  - a interrupção, que para a fala, cancela a fila e o modelo e guarda o texto até onde tocou;
  - os comandos rápidos;
  - o mapa mental pela voz, que vira cartão com uma fala curta;
  - o quiz por voz;
  - salvar pela voz, que abre a prévia e não grava;
  - o microfone ocupado por uma aula sendo gravada;
  - encerrar sozinho;
  - nenhum arquivo de áudio sobrando;
  - os ajustes validados.
- **`tests/study_ui.py`:** passo novo com eventos simulados: abrir a chamada, o orbe nos estados, a legenda parcial e final, o cartão, interromper, mudo, minimizar para a pílula, encerrar e voltar ao chat com o texto. Nas quatro larguras e sem erro de CSP.
- **Suíte inteira:** `.venv\Scripts\python -m unittest discover -s tests -t .` (o `-t .` é obrigatório). O `study_ui` roda com `py -3.14`.
- **No fim, uma revisão independente:** peça a um subagente com contexto novo para conferir o resultado contra este prompt, item por item, apontando a prova de cada um.

## 7. Documentação e entrega

Antes de terminar a sessão, mesmo que pela metade:

- **`STATUS`:**
  - na linha da fase 6, a "parte 3: conversa por voz", com o estado;
  - o **Próximo passo**, concreto: arquivo, função, o que falta e como provar;
  - as pendências.
- **`DECISIONS`:** as decisões novas, de **D61** em diante, cada uma com o motivo e os números.
- **`CHANGELOG`:** o que mudou, com cada instalação (versão, tamanho, local e licença).
- **`MODELS`:** as medidas.
- **`docs/implementation/PROMPT_CONTINUAR.md`:** acrescente a linha deste prompt na tabela "Fase | Prompt", para o Claude Code continuar daqui se for preciso.
- **Relatório ao estudante, em português, com frases completas:**
  - comece pelo que funciona agora e pelo que ele precisa fazer;
  - mostre os testes (quantos passaram, e a saída do que falhou) e as medidas reais;
  - **só afirme o que você conferiu nesta sessão.** O que ficou sem verificar, diga que ficou.
- Escreva a documentação no estilo que já está nos arquivos: português correto, com acentos, frases curtas e sem abreviações inventadas.

## 8. Pronto quando

- Com um clique (ou pelo Ctrl+K), o estudante entra numa chamada de voz e conversa com o Lúmen em turnos, falando e ouvindo, com a conversa aparecendo em texto ao vivo.
- O Lúmen responde com a voz escolhida do Voice Studio (o Jhonny por padrão) e pode ser interrompido.
- Pela voz, ele pede mapa mental, quiz, diagrama, plano, Feynman e `/tela`, e os resultados aparecem como cartões, sem nada gravado sem a prévia.
- A seção "Conversa por voz" das Configurações tem os ajustes da 4.2, com padrões vindos da medição.
- O atraso medido está registrado, etapa por etapa, com a meta da 4.3 atingida ou com o motivo e o próximo passo.
- Nenhuma regra da seção 1 foi quebrada. Os testes e a suíte passam, e a documentação está atualizada.
