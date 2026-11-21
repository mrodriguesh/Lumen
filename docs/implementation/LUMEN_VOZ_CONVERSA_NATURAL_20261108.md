# Conversa por voz natural: diagnóstico, correções e medições (08/11/2026)

Pedido: deixar a chamada de voz do Lúmen contínua, responsiva e ligada de verdade ao chat (Livre/Notas), com medições antes/depois.
Nada foi publicado, commitado ou enviado para fora. Restauração conferida antes de qualquer mudança
(`D:\Lumen\restauracao\voz-conversa-20261108`, 272 arquivos, manifesto com SHA-256, 0 divergências; `lumen/study` e quase toda a voz **não estão no git**,
só essa cópia os preserva). Evidências desta sessão em `D:\Lumen\voz-conversa-20261108\` (`logs\`, `bench\`, `ui\`, `escuta\`).

> **O que é medido e o que não é.** Os números abaixo vêm de: Ollama real (`qwen3.5:4b`, 32k), Voice Studio real (OmniVoice, voz Jhonny `1faf41ee`,
> 12 passos), Parakeet CPU int8 real, VAD Silero real, saída WASAPI real **em ganho zero** (mede a latência do driver sem tocar nas caixas) e
> **microfone simulado** com falas sintéticas (as 10 amostras de `D:\Lumen\voz\amostras-chamada`, geradas pela própria voz). Isso **não** é conversa
> com voz humana, não prova eco acústico real das suas caixas e não prova naturalidade percebida. Esse teste é o roteiro de
> `LUMEN_VOZ_TESTE_FINAL_20261108.md`. Também não é a janela nativa (WebView2): a interface foi conferida em Chrome headless.

## 1. Estado de referência (revalidado nesta sessão)

- CPU i5-11400F (6 núcleos, 12 threads), 15,8 GB de RAM (livre durante as medições: mediana ~1,0 GB, mínimo 0,29 GB), RTX 3060 12 GB (6,8 GB livres no início;
  com Ollama + Voice Studio carregados o uso ficou em 10,1 GB, pico 10,4 GB). C: com 11,4 GB livres, D: com 799 GB.
- Áudio (enumerado sem abrir fluxo): microfone padrão **Microfone (USB AUDIO)**, mono; alto-falante padrão **Alto-falantes (Realtek High Definition Audio)**, estéreo;
  também existem Microfone Realtek, Alto-falantes USB AUDIO, NVIDIA HD Audio e saída digital. Microfone e caixa são aparelhos diferentes: o caminho
  acústico de eco existe de verdade e só a sua escuta o valida.
- Configuração pessoal lida (somente leitura) e **mantida**: `engine voicestudio`, `voice_id 1faf41ee`, `call_mode handsfree`, `call_silence normal`, `call_headphones false`,
  `call_early true`, `call_asr auto`, `call_quality balanced`, `call_effort auto`, `call_length short`, `call_barge_in true`; além disso `vs_warm_on_open true`,
  `fallback chatterbox`, `chat_quality balanced`. Nenhuma voz, modelo, motor ou permissão foi trocada.

## 2. Linha de base (código original, congelado em `D:\Lumen\voz-conversa-20261108\baseline-src`)

Perguntas comuns (sem busca/ferramenta), aquecidas, 20 turnos em tempo real (~9,8 min), p50 / p90:

| Etapa | p50 | p90 |
|---|---|---|
| Fim da fala → "entendi" (silêncio de 700 ms) | 641 ms | 668 ms |
| Reconhecimento (Parakeet CPU) | 375 ms | 453 ms |
| Primeira palavra do modelo (desde o fim da fala) | 778 ms | 929 ms |
| Síntese do 1º trecho (`tts_first_ms`) | **2083 ms** | 2434 ms |
| **1º som com conteúdo, desde o fim da fala** | **3,61 s** | 4,08 s |
| Confirmação sonora ("entendi") | 48 ms | 57 ms |
| Lacunas entre frases | ~0 ms | 11 ms |

Pedidos com cartão/ferramenta (mapa mental, quiz, diagrama, erros): 1º som 3,5 s (p50) a 6,7 s (p90); mapa mental 7,7 s.
A frio (processo novo, Voice Studio fechado): backend 11 s, modelo de voz 106–127 s, **1ª síntese 165–183 s**, Parakeet 5–8 s para carregar e 2,4–4,0 s na 1ª inferência *durante a partida a frio* (disputando CPU e disco com os outros modelos); isolado e com o PC parado, a 1ª fala custa só ~100 ms a mais (412–420 ms contra 304–319 ms).
Recursos: CPU do sistema mediana 24,8% (pico 87%); o processo do Lúmen usa ~0,1 núcleo (pico 2,0); RSS estável 975–1073 MB; VRAM 10,1 GB (pico 10,4); RAM livre
com mínimo de 292 MB (o PC fica no limite quando Ollama, Voice Studio, Lúmen e navegador coexistem).

Gargalo real: a **síntese do 1º trecho** (57% do caminho), não o modelo (a 1ª palavra chega em ~0,8 s) nem o reconhecimento (sobreposto ao silêncio).

## 3. Problemas encontrados e as causas

| # | Problema | Causa (no código) | Como foi provado |
|---|---|---|---|
| 1 | **Frases do turno antigo reapareciam no turno seguinte** (tocavam e entravam na legenda) | O cancelamento era um `threading.Event` único (`_speak_cancel`) que `_commit_user_turn` "limpava" ao começar o turno novo; a síntese que ainda estava pendurada (o intervalo de ~1,5 s de "pensando") terminava depois, via o evento limpo e seguia | Teste novo reproduziu antes da correção (`['Resposta nova…', 'Primeira frase velha…', 'Segunda velha…']`) e passa depois |
| 2 | **A chamada ignorava Livre/Notas** | `openCall()`/`_build_agent_payload` não enviavam `skip_vault`, `vault_sources` nem `profile`, que o chat escrito envia; uma chamada aberta em Livre consultava Notion e Obsidian | Teste: payload e requisição ao modelo (a nota só aparece no modo Notas) |
| 3 | Caminhos especiais fora da regra | Feynman buscava em todas as fontes mesmo em Livre ou com "só Obsidian"; "salvar no Obsidian" por voz preparava a nota em Livre (o chat recusa) | Testes com `search.search` bloqueado em Livre |
| 4 | Busca antecipada podia sobrar do modo antigo | O agente aceitava `prefetched_search` só pelas palavras-chave, sem as fontes | Teste com resultado "envenenado" |
| 5 | **Falar durante "pensando" era ignorado** | `_on_mic_frame` descartava todo quadro fora de `listening`/`user_speaking`/`speaking` | Teste de barge-in durante o estado "pensando" |
| 6 | Interromper no "pensando" deixava a thread presa | O consumo da resposta antecipada bloqueava em `queue.get()` até a 1ª palavra do modelo, e um `agent.cancel` anterior ao registro do turno se perdia | Testes (`PRE_CANCEL`, iterador que acorda a cada 100 ms) |
| 7 | Fim de fala sem tolerância a pensar | Silêncio fixo (450/700/1100 ms), sem olhar a frase; VAD com o mesmo limiar para começar e continuar | Testes + sonda com Silero/Parakeet reais (seção 5) |
| 8 | Microfone que some deixava a chamada "ouvindo" para sempre | A thread do microfone morria em silêncio (`self.error`), e ninguém olhava | Testes de reabertura e de falha definitiva |
| 9 | "Preparando a voz… 35%" inventado; a voz fria custava minutos na 1ª resposta | `prepBarFill` usava 35% quando não havia `pct`; nada aquecia a 1ª síntese | Medida a frio (165–183 s) e leitura do código |
| 10 | Tópico do Feynman deslocado ("emória e sono") | `text[len(text)-len(grupo):]` com o ponto final do Parakeet fora da conta | Teste existente passou a falhar quando o ASR falso ganhou a pontuação real; corrigido |
| 11 | A interface tentava reconectar com uma função inexistente (`get`) | `ReferenceError` engolido por `catch {}` | Leitura do código (a reconexão não consultava o estado) |
| 12 | Voz soletrava símbolos e fechava o 1º trecho como frase acabada; prompt forçava 1ª frase de 4–8 palavras sempre | `voice.speakable` não lê "%", "=", "→"; o corte na vírgula virava ponto; regra 3 do `CALL_SYSTEM` | Testes de `speech_text` |
| 13 | A resposta interrompida perdia o que o modelo escreveu; interrupção sem fala criava bolha vazia | `chats.update_message` substituía o texto; `interrupted` sempre emitido | Testes de histórico |
| 14 | Possível vazamento de thread de síntese | `audio_q.put(None)` bloqueava com a fila cheia e o tocador já fora | Leitura + sinal `stop_synth` |
| 15 | **Uma pausa longa no meio da frase cortava a fala em dois turnos** e a resposta vinha só da 2ª metade | Fim de fala por silêncio fixo; a regra da pontuação não pegou porque o Parakeet fechou a 1ª metade com "?" | Benchmark no pipeline real (pausas de 0,9 e 1,3 s: 2 turnos) e, depois da mesclagem, 1 pergunta no histórico |
| 16 | A legenda repetia a fala do estudante em todo turno | `understanding` emitia `final` e o evento `user` emitia de novo | Teste novo (um `final` por turno) |
| 17 | Os primeiros ~250 ms da fala por cima se perdiam | Os quadros do microfone chegavam enquanto a interrupção ainda parava o áudio e eram descartados | Teste dos quadros guardados |

## 4. O que foi implementado (e onde)

- **Turno isolado** (`call.Turn`, `_emit`/`_set_state` que descartam o turno cancelado, `turn_id` e `seq` em todo evento, `agent.PRE_CANCEL`, `_iter_spec`).
- **Livre/Notas de verdade** (`start`/`set_vault`/`_vault_snapshot`, fotografia por turno, antecipada descartada se o modo mudou, rota `action: "vault"`, evento `vault`,
  comandos de voz com `FREE_ON_RE`/`FREE_OFF_RE`/`NOTES_ON_RE`/`NOTES_ONLY_RE`; Feynman e salvar respeitam o modo; `agent` confere as fontes da busca antecipada).
- **Conversa natural:** espera extra de até 0,9 s para frase inacabada (`looks_unfinished`, `_hold_extra_ms`), histerese do VAD (0,5/0,35), falar por cima também durante "entendi/transcrevendo/pensando",
  resposta longa só quando pedida (`LONG_ASK_RE`), instruções de fala (`CALL_SYSTEM`), símbolos lidos como palavras e 1º trecho terminando em vírgula (`speech_text`).
- **Pausa no meio da frase (D110, D120):** além da espera por frase inacabada, retomar a fala antes de qualquer som, em até 4 s, **mescla** as duas partes num turno só (retira a pergunta e a resposta ainda não faladas, transcreve as duas partes juntas, a tela tira a metade cortada).
- **Histórico coerente:** o que foi ouvido vai para a mensagem; o que o modelo escreveu fica em `meta.generated` (a conversa escrita mostra "Ver o que a IA já tinha escrito (não foi falado)").
- **Robustez:** microfone perdido → 3 reaberturas ou fim com mensagem (`_watch_mic`, `Mic.last_frame_at`, geração por abertura); "Ouvindo" só com áudio chegando; reenvio dos eventos perdidos (`?since=seq`, anel de 400 eventos);
  erro de síntese ou de saída de áudio vira aviso sem derrubar a chamada; quadro com erro não mata a thread do microfone; "ainda preparando a resposta" após 6 s.
- **Medição por etapa na própria chamada** (evento `timing`): `agent_prep_ms`, `understand_ms`, `search_ms` (+ `searched`), `synth_first_ms`, `gap_max_ms`, `underruns`, `q_audio_max`, `complete_ms`, `ready_ms` (no estado).
- **Aquecimento:** 1ª síntese e inferência de mentira do Parakeet na preparação; passar o mouse no botão aquece a voz. Opção `call_first_quality` (desligada).
- **Interface refeita** (seção 8), com `tests/call_ui.py`.
- **Instrumentos:** `bench/call_bench.py` com diretório único por execução (não apaga mais `D:\Lumen\cache\lumen-call-bench`, que existe com um `study.db` herdado) e saída em `D:\Lumen\voz-conversa-20261108\bench\<execução>`;
  comandos novos `turns`, `realtime`, `probe`, `endpoint`, `afterturns`; amostrador de CPU/RAM/VRAM; `bench/asr_first_utterance.py`.

## 6. Livre/Notas na voz: como funciona

- **Mesmo estado do chat escrito** (`window.lumenStudy.vault`): o controle Livre | Notas da chamada, o botão do chat, `/livre`, `/notas` e os comandos de voz mudam o mesmo estado e se refletem entre si.
- **Fotografia por turno:** o modo vale para o turno no instante em que a sua fala fecha. Mudar no meio de uma resposta vale para a **próxima**; a tela mostra "Vale a partir da próxima resposta." (`vault_pending`).
  Uma resposta antecipada que nasceu no modo antigo é descartada e refeita (o texto já transcrito é reaproveitado).
- **Livre:** `skip_vault` chega ao agente, que não busca, não oferece ferramentas de notas e não usa busca antecipada nem cache; a mensagem fica com `meta.free_mode`. **Notas:** usa as fontes autorizadas e as escolhidas (todas, só Obsidian ou só Notion) e mantém as referências na legenda e nos cartões.
- **Independentes de Livre:** memória, perfil adulto (o `profile` escolhido segue), modelo, web e gravação. Livre não liga nem desliga nenhum deles.
- **Comandos de voz:** "ativar modo livre", "usar minhas notas", "usar só o Obsidian/Notion" (e variações com "por favor", "pode"…). Só valem como frase curta e inteira; "o que é o modo livre?" ou "ele disse ativar modo livre" não trocam nada.
- **Caminhos especiais:** quiz e revisão só usam o banco de estudos (sem notas); Feynman usa a fotografia (Livre = sem busca nas notas; fontes escolhidas filtram); salvar no Obsidian/Notion em Livre é recusado com a explicação (como no chat).

## 9. Configuração recomendada para este computador

Nada precisa mudar: a configuração atual (voz Jhonny, 12 passos, Parakeet CPU, resposta antecipada, silêncio "normal", caixas de som com eco cancelado) é a que as medições sustentam.
Recomendações opcionais:
1. Manter "Deixar a voz pronta ao abrir o Lúmen" ligado (já está): evita a partida a frio de minutos do Voice Studio.
2. Experimentar "Primeiro trecho da resposta: mais rápido (8 passos)" depois de ouvir os pares cegos; só vale se soar igual ao seu ouvido (ganho esperado ~0,3–0,4 s).
3. Com a RAM livre abaixo de ~1 GB (medido), fechar o navegador ou outros apps antes de conversar por voz melhora a estabilidade; não há ajuste de software que compense.
4. Fones deixam o corte por fala sobreposta mais sensível e sem depender do cancelamento de eco; com caixas de som, ligar `call_headphones` **não** é necessário.

## 5. Antes × depois, por etapa (tempo real, 24 turnos em ~10 min, mesma máquina, mesmas falas sintéticas)

"Antes" = código original congelado (`baseline-realtime-20261108`); "depois" = código final (`depois4-20261108`). Milissegundos, p50 / p90. Erros: 0 e 0.

**Perguntas comuns (20 turnos, sem busca nem ferramenta)**

| Etapa | Antes p50 | Antes p90 | Depois p50 | Depois p90 |
|---|---|---|---|---|
| Fim da fala → "entendi" (silêncio de 700 ms) | 641 | 668 | 660 | 670 |
| Reconhecimento (Parakeet CPU) | 375 | 453 | 314 | 347 |
| 1ª palavra do modelo (desde o "entendi") | 778 | 929 | 764 | 937 |
| 1ª oração pronta (desde o início do modelo) | 930 | 1106 | 1068 | 1242 |
| Síntese do 1º trecho | 2083 | 2434 | 2128 | 2410 |
| **1º som com conteúdo, desde o fim da fala** | **3610** | **4079** | **3635** | **4093** |
| Confirmação sonora ("entendi", opcional) | 48 | 57 | 43 | 44 |
| Lacuna entre frases (voz parada) | 0,2 | 10,6 | 0,2 | 10,7 |
| Conclusão do turno (volta a ouvir) | 16 920 | 17 324 | 19 818 | 22 833 |

Etapas que só passaram a ser medidas (depois): preparo do agente até o modelo (intenção + busca + memória + contexto) p50 153 / p90 193 ms; intenção 0–18 ms; **busca nas notas p50 0 / p90 2 ms (cofre de teste de 3 notas: não representa o seu cofre grande; ligue "mostrar os tempos" para ver o seu)**;
maior lacuna em um turno: 0 ms (p50, p90 e máximo nos 22 turnos medidos). (A profundidade das filas e as vozes paradas por turno são registradas pelo código novo, mas o instrumento desta rodada não as copiou; ficam para a próxima.)

**Pedidos com cartão/ferramenta (4 turnos: mapa mental, quiz, diagrama, "o que errei")**: 1º som p50 3523 → 3988 ms; p90 6727 → 10 220 ms. Com só 4 amostras e o modelo gerando JSON de duração variável (o mapa mental levou 8–10 s em uma rodada),
**não dá para afirmar piora nem melhora**; a rodada "depois" anterior (`depois2`, ainda com a regressão de lacuna abaixo) deu p50 3935 / p90 6559 ms.

**Recursos (10 min, 24 turnos)**: processo do Lúmen RSS 842–1072 MB (antes 975–1073), sem crescimento; 0,1 núcleo de mediana (pico 1,6); VRAM 8,0–8,3 GB estável (antes 7,9–10,4; a diferença é do que estava carregado no PC em cada rodada, não da chamada);
RAM livre do PC p50 648 MB, **mínimo 181 MB** (antes 292 MB): o PC fica no limite de memória quando Ollama + Voice Studio + navegador coexistem. CPU do sistema p50 7,3% (antes 24,8%: a linha de base rodou junto com as minhas capturas de interface e testes; compare só as latências).

**O que melhorou e o que não.** O 1º som com conteúdo **não mudou** (3,6 s p50, 4,1 s p90): o piso é a síntese do 1º trecho (57% do caminho), que no Voice Studio/OmniVoice desta RTX 3060 leva ~1,6 s sozinha e ~3,4 s com o modelo de texto decodificando ao mesmo tempo (seção 7).
Melhoraram o reconhecimento (-60 ms p50), a confirmação sonora (p90 57 → 44 ms), a correção (turnos antigos não vazam), o modo Livre/Notas, a tolerância a pausas, a robustez e a interface. Não há como prometer "poucos segundos" menor que isso neste hardware sem trocar o motor de voz ou aceitar menos passos.

**Regressão que eu introduzi e corrigi (medida, não suposta).** Na rodada intermediária (`depois2`) a lacuna entre o 1º e o 2º trecho foi de 0,2 para **390 ms (p50) e 1233 ms (p90)** e a resposta ficou ~70% mais longa (turno de 17 para 29 s): ao tirar do prompt a 1ª frase "forçada" de 4–8 palavras (pedido seu) tirei também o "frases curtas". Correção:
prompt com "frases curtas (até uns 12 palavras)" sem forçar a 1ª frase (resposta média de 30 → 37 palavras, 1ª frase com 15 em média, de 8 a 23) e cronograma de tamanho de pedaço (`CHUNK_CHARS`, D119). Resultado: lacuna de volta a ~0.

## 7. Sondas do caminho crítico (Voice Studio real, Parakeet CPU, Silero)

| Medida | Resultado |
|---|---|
| Síntese por passos, mesmo material (6 trechos + 3 frases, p50) | 8 passos 1320 ms · 12 passos 1698 ms · 16 passos 2054 ms |
| Erro de palavras do que foi sintetizado (Parakeet como juiz, 9 textos) | 9,28% · 9,23% · 8,63% (diferença dentro do ruído; vem de termos técnicos como "sístole" e "NADPH") |
| Silêncio no começo e no fim de cada frase sintetizada | ~40 ms e ~30 ms (a síntese já é justa; aparar o silêncio foi medido e descartado) |
| 1º trecho (12 passos) sozinho × com o modelo de texto decodificando | 1639 ms × 3353 ms (2,05×: as duas coisas disputam a mesma GPU) |
| 1ª fala do Parakeet em processo novo, PC parado: sem × com o aquecimento | 412–420 ms × 304–319 ms |
| Fim da fala (Silero + Parakeet reais, 10 falas completas): esperas falsas | 0/10 |
| Fim da fala, 10 cortes sintéticos no meio da frase: espera por frase inacabada ligou | 2/10 (os outros 8 cortes caíram em fim de frase, que o reconhecedor fecha com ponto) |
| Cauda das palavras com a histerese do VAD (falas sintéticas) | sem diferença mensurável (0 ms nos dois): a fala sintética termina de uma vez |

Lidos com honestidade: **o aumento de passos não melhora a inteligibilidade medida** e **o corte de 12 para 8 passos economiza ~0,38 s por trecho**, mas se 8 passos soam tão naturais quanto 12 só a sua escuta diz;
por isso a opção `call_first_quality` existe e **vem desligada**. A espera por frase inacabada e a histerese são mecanismos testados por unidade e na sonda acima, **mas sua utilidade real depende de como você faz pausas**: é para o teste ao vivo.

## 8. Interface

Antes (`D:\Lumen\voz-conversa-20261108\ui\antes\`): seis botões em linha (Mudo, Falar agora, Voz, Legendas, Minimizar, Encerrar), orbe com anel duplo e brilho, estado e microfone no topo, sem Livre/Notas, barra de preparo fixa em 35%.
Depois (`...\ui\depois-1\` e seguintes): orbe único; estado em texto grande (Preparando a voz, Ouvindo, Você está falando, Consultando suas notas, Preparando a resposta, Falando, Microfone silenciado, Reconectando, erro); dica de uma linha; **Livre | Notas** com menu de fontes;
três ações grandes (mudo, interromper, encerrar); voz, legendas e minimizar discretos no cabeçalho; pílula com estado, tempo e modo. Verificado em Chrome headless em 1440, 1100, 760 e 520 px (sem rolagem horizontal, sem texto cortado, controles ao alcance), movimento reduzido, foco visível, atalhos Esc/Espaço/M, reconexão sem duplicar e sincronização do Livre/Notas com o chat (`tests/call_ui.py`, 10 verificações; `tests/study_ui.py` passo 12).
O app é só escuro (D9); não existe tema claro para validar.

## 7b. Interrupção e pausa no pipeline real (`bench/call_bench.py interrupts`, 8 interrupções + 2 pausas)

Voz sintética entrando pelo microfone simulado enquanto a resposta A **toca de verdade** (Voice Studio, Ollama, Parakeet e Silero reais; saída em ganho zero; sem eco, `call_headphones` ligado só para esta medição). A tabela mede a partir do **início real da voz**
(o WAV tem 0,4–0,7 s de ruído antes da fala; o início foi achado com o próprio Silero).

| Medida | Resultado (n = 8) |
|---|---|
| Início da voz → interrupção registrada (estado "você falando") | p50 335 ms, p90 347 ms, máx 356 ms |
| **Início da voz → áudio parado (buffer esvaziado)** | **p50 137 ms, p90 156 ms, máx 157 ms** (meta: ~150 ms) |
| Eventos (frase ou legenda) do turno interrompido depois da interrupção | **0** nas 8 |
| Resposta interrompida marcada como interrompida no histórico | 8 de 8 |

Quem estiver com **fones** (a medição acima) corta com 3 quadros de voz; com **caixas de som** (o seu uso, `call_headphones` desligado) o corte exige 5 quadros acima da barreira de eco: ~64 ms a mais, mais o que o cancelamento de eco decidir. **Isso só o seu teste com as caixas de verdade prova.**

**Pausa no meio da frase** ("Qual é a diferença entre memória de trabalho… [pausa] …e memória de longo prazo no cérebro"):

| Versão | Pausa de 0,9 s | Pausa de 1,3 s |
|---|---|---|
| 1ª medição (só espera por frase inacabada) | cortou em **2 turnos** (a 1ª metade foi respondida) | cortou em **2 turnos** |
| Depois da mesclagem (D120) | **1 pergunta** no histórico, 1 retirada | **1 pergunta** no histórico, 1 retirada |

O que a 1ª medição mostrou: o Parakeet fechou a 1ª metade com "?", então a regra da pontuação (D118) não bastou. A mesclagem não depende do que o reconhecedor escreve: retomar antes de qualquer som, em até 4 s, junta as duas partes.
Medição extra descoberta no caminho: a legenda repetia a fala do estudante em **todo** turno (`understanding` e depois `user` emitiam `final`); corrigido, com teste.

## 10. Testes e provas desta sessão

| O quê | Resultado |
|---|---|
| `tests/test_call_natural.py` (novo) | 55 testes, todos OK |
| Relacionados (`test_study_call`, `test_study_free_mode`, `test_ui_tokens`) | OK |
| Suíte completa `unittest discover -s tests -t .` | **971 OK em 1024,1 s** (`logs/suite-full-2.log`); a rodada anterior, antes da mesclagem, foi 965 OK em 992,4 s |
| `py -3.14 tests/study_ui.py` (inclui o passo 12, a chamada) | passou: 33 verificações, nenhum erro de página, CSP ou HTTP 5xx (`logs/study-ui-4.log`; uma rodada falhou no passo 16, perfil adulto, sem relação com a voz, e passou na seguinte) |
| `py -3.14 tests/call_ui.py` | 10 verificações (estados, Livre/Notas sincronizado, 4 larguras, movimento reduzido, teclado, pílula), 0 erros |
| JavaScript alterado (`study.js`, `study-call.js`, `study-settings.js`) | `node --check` OK |
| Medições reais | seções 2, 5, 7 e 7b |

**Tipos de evidência (não se misturam):** microfone falso e VAD/ASR falsos nos testes unitários; áudio sintético (voz do próprio Voice Studio) no benchmark; **reconhecimento real** (Parakeet), **VAD real** (Silero), **modelo real** (Ollama) e **síntese real** (Voice Studio) no benchmark; **reprodução real em ganho zero** (WASAPI); janela **headless** (Chrome) na interface; **nenhuma** janela nativa WebView2; **nenhuma** conversa ao vivo com a sua voz.

## 11. Estado da validação no aplicativo oficial

**Não validado.** O Lúmen do dia a dia não estava aberto quando a sessão terminou e não foi aberto nem reiniciado por mim; a janela nativa (WebView2), o executável oficial e o microfone/caixas reais **não foram exercitados**. O código novo só vale depois de **Sair pelo menu e abrir de novo**. Roteiro: `LUMEN_VOZ_TESTE_FINAL_20261108.md`.

## 12. Limitações restantes

- **O 1º som útil continua em ~3,6 s (p50) e ~4,1 s (p90)** neste PC. O piso é a síntese do 1º trecho na RTX 3060 dividida com o modelo de texto (1,6 s sozinha, 3,4 s com o modelo decodificando). Sem trocar o motor, aceitar menos passos (opção `call_first_quality`) ou liberar a GPU, não há como baixar muito. Não há equivalência demonstrada com o modo de voz do ChatGPT (nuvem).
- A partida a frio do Voice Studio leva minutos (modelo 106–127 s + 1ª síntese 165–183 s); com `vs_warm_on_open` ligado (o seu caso) isso acontece na abertura do Lúmen, e a chamada aquece o resto.
- A RAM livre chegou a 181–292 MB nas medições: com Ollama + Voice Studio + navegador abertos, o PC fica no limite.
- A espera por frase inacabada pega só 2 de 10 cortes sintéticos (a regra depende da pontuação do Parakeet); a mesclagem (4 s) é a rede de segurança principal.
- Cobertura de eco: só o simulador e testes unitários (barreira de energia, `pyaec`); o eco acústico real das suas caixas Realtek no microfone USB não foi medido.
- Pedidos com cartão (mapa mental etc.): só 4 amostras; o tempo varia com a geração do JSON pelo modelo.
- A busca nas notas foi medida com um cofre de teste de 3 notas (~0 ms); no seu cofre pode ser maior (ligue "mostrar os tempos").
- Naturalidade percebida (entonação, 8 × 12 passos, vírgulas no 1º trecho, "frases curtas") só a sua escuta decide.

## 13. Reversão

1. Arquivos: `D:\Lumen\restauracao\voz-conversa-20261108\RESTAURAR.md` (copie `arquivos\<caminho>` de volta; `manifesto.json` tem o SHA-256 de cada um). `lumen/study` não está no git: só essa cópia o preserva. **Não use** `git reset`, `clean`, `stash` nem `checkout`.
2. Configuração pessoal: não foi alterada (cópia em `config.json.bak` na mesma pasta, só por precaução). O único ajuste novo é `voice.call_first_quality`, que vem `same` (sem efeito).
3. Voltar só a interface da chamada: restaurar `lumen/web/study-call.js`, `study.css`, `study.js` e `icons.svg` da cópia (a nova interface exige o backend novo; a antiga funciona com ele).
4. Remover as evidências desta sessão (opcional, só se quiser espaço): `D:\Lumen\voz-conversa-20261108\` (o `baseline-src` e o `before-ui` são cópias de código).
