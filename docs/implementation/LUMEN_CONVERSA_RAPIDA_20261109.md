# Conversa rápida na barra flutuante (09/11/2026)

> **Atualização (09/11/2026, 2ª versão):** o tamanho 420 × 620 descrito abaixo foi substituído — a conversa abre na janela compacta de 304 × 252 e
> ocupa a janela inteira; "Continuar no Cérebro" e "Nova conversa" passaram para o menu ⋯. Ver `LUMEN_CONVERSA_RAPIDA_CORRECAO_20261109.md`.

Pedido: conversar com a IA e consultar conhecimentos sem abrir a janela principal, dentro da barra flutuante, com o mesmo cérebro do Lumen.
Estado: **implementado e verificado tecnicamente** (API, interface com servidor real, WebView2 e janela nativa em instância isolada). **Não verificado:**
clique e digitação com o mouse e o teclado reais, o `Lumen.exe` oficial (está em uso; o candidato está pronto) e o juízo estético, que é seu.

## 1. Como usar

1. **Abrir:** o ícone de balão na barra, entre **Gravar** e **Ajustes** (um clique). A barra cresce para 420 × 620 (96 dpi) e o campo de mensagem já está
   pronto para digitar. Se uma conversa anterior existe, ela reaparece (é relida do servidor, só ao abrir).
2. **Livre | Notas:** o par de botões abaixo do título. **Livre** responde sem consultar o Notion nem o Obsidian (`skip_vault`); **Notas** consulta as fontes e a
   resposta traz **Fontes · n** (citadas primeiro; **Abrir** confirma pelo que o Lumen devolve). É o mesmo estado do botão do Cérebro: mudar num lugar muda no outro, e
   "Só Obsidian/Só Notion", escolhido no Cérebro, é preservado e mostrado.
3. **Continuar no Cérebro:** **Cérebro** (↗) no cabeçalho, ou "Resultado completo no Cérebro" sob uma resposta com diagrama, checagem, flashcards ou arquivo. Abre a
   MESMA conversa (mesmo identificador, mensagens, modo; temporária continua temporária). Nada é copiado e a pergunta nunca é reenviada.
4. **Recolher sem perder nada:** **‹** no cabeçalho ou **Esc** (primeiro fecha o menu, depois recolhe). A resposta em andamento **não** é cancelada; um ponto azul no ícone
   avisa que terminou. Ao reabrir, a barra mostra o painel de gravação e a conversa espera no ícone, com o texto digitado e as mensagens intactos.
5. Outros: **+** nova conversa (a atual fica no histórico) ou **temporária** (não entra no histórico nem cria memórias); **Interromper** no botão de enviar; **Copiar**;
   **Tentar de novo** depois de interromper ou falhar (reaproveita a pergunta; não duplica).

Fora de propósito: comandos `/` (têm confirmação de envio externo e custo só no Cérebro; a barra manda para lá), anexos, `/tela` e **voz/ditado** (usam o microfone e o
Voice Studio, que a barra não deve carregar durante uma gravação; não há segunda implementação de chamada).

## 2. Arquitetura

```
widget.html ── #chat-btn (rail) ── showChat() ── widget:panel:chat ──► WidgetForm.Panel(ChatPanel 420×620) ── animação nativa existente
     │                                │
     └── chat.js (QuickChat) ─────────┴─ fetch ► POST /api/study/turn (NDJSON) · POST /cancel · GET /conversation[?brief=1]  (mesmo agente)
            │  md.js (Markdown seguro, extraído do study.js)
            └─ "chat:open[:id]" ► Lumen.cs.OpenChat (valida o id) ► "desktop:chat[:id]" ► app.js ► lumenStudy.openFromHost(id) ► relê a conversa
```

Sem servidor, banco, endpoint de geração ou processo novos. Backend: `agent.ACTIVE_CONV` + `agent.generating()` (uma resposta de chat por conversa; a chamada de voz fica de fora),
`GET /api/study/conversation` com `generating` e `?brief=1`. Cérebro: `openFromHost`, `watchElsewhere` (espera uma resposta que está sendo escrita na barra) e escuta do `storage`
(Livre/Notas). Decisões **D127–D134** (`LUMEN_STUDY_AI_DECISIONS.md`); regras visuais na seção "Conversa rápida" de `docs/DESIGN.md`.

### Arquivos

Novos: `lumen/web/chat.js`, `chat.css`, `md.js`; `tests/chat_ui.py`, `tests/test_quick_chat.py`; este relatório.
Alterados: `launcher/WidgetForm.cs` (`ChatPanel`, `widget:panel:chat`), `launcher/Lumen.cs` (`OpenChat`), `lumen/study/agent.py`, `lumen/study/api.py`, `lumen/server.py` (3 rotas
estáticas), `lumen/web/{widget.html, widget.js, widget.css, icons.svg (ícone `chat`), study.js, app.js, index.html}`, `tests/{widget_ui.py, DesktopChecks.cs, fake_ollama.py, test_ui_tokens.py}`,
`README.md`, `docs/DESIGN.md`, `docs/implementation/LUMEN_STUDY_AI_{DECISIONS,STATUS}.md`, `docs/DECISOES.md`. `launcher/build.ps1`, `Lumen.exe`, configurações, dados e modelos **não** foram tocados.

## 3. Verificação (tudo com dados isolados; nada de configuração pessoal, Notion real, Ollama real ou chaves)

| O quê | Resultado |
|---|---|
| Linha de base antes de editar | `unittest` direcionado 36 OK; `widget_ui.py` **falhava** e o nativo **falhava** (ver §5); geometria 640 + 140 casos OK |
| `tests/test_quick_chat.py` (backend, novo) | 11 testes OK: segunda resposta na mesma conversa recusada sem gravar a pergunta, outra conversa livre, cancelar/erro/fechar liberam, chamada de voz fora do guarda, `brief`/`generating`, temporária, Livre sem busca × Notas com busca, tentar de novo sem duplicar |
| `tests/chat_ui.py` (novo, servidor real + Ollama falso que transmite, Chrome headless) | **24 blocos OK** (log `logs/chat-ui-final2.log`, repetido com temporários no D:): lista em `ui/chat-final2/chat-ui-report.json` |
| `tests/widget_ui.py` (existente, atualizado) | OK: trilha com o ícone nas quatro orientações |
| Nativo `DesktopChecks` (WebView2 e janela reais, instância isolada) | OK inteiro, 4 execuções seguidas no código final (`logs/native-final.log`): geometria 800 + 140 casos; bloco "Conversa rápida" com 72 verificações; mais as seções antigas (ajustes, compreensão, capas, quatro orientações) |
| Regressão do Cérebro | `study_ui.py` 33 verificações OK; `call_ui.py` 10 OK; `estudar_ui.py` OK (`logs/regressao-*.log`) |
| `node --check` (`chat.js`, `md.js`, `widget.js`, `study.js`, `app.js`) | OK |
| `test_ui_tokens` (agora inclui `chat.css`: cores só por token, tamanhos só pela escala) | OK |
| Suíte completa (`unittest discover -s tests -t .`) | **982 testes OK** em 1208,8 s (`logs/suite-full.log`): os 971 de antes + 11 novos; nenhuma das duas falhas intermitentes herdadas apareceu desta vez |

**O que o teste nativo provou na janela real:** a janela cresce para exatamente `ChatPanel × escala` (ou para a área útil, se menor) nas quatro bordas, sempre dentro da área útil; a moldura da página tem o
tamanho da janela; recolher e reabrir voltam aos tamanhos certos; o crescimento é contínuo, sem recuo nem ricochete, e **interrompido no meio e invertido, a janela continua do tamanho atual** (maior passo ≤ 50% do percurso);
recolher durante a resposta não a cancela; ponto de novidade; rascunho, mensagens e identificador intactos; trocar para Ajustes e voltar; Esc em dois passos sem encerrar o Lumen; `chat:open:<id>` só chega à
janela principal se o identificador é válido (`../..`, espaços, vazio e 70 caracteres são descartados).

**Medido (WebView2 real, renderização por software, janela invisível, resposta simulada na página: 150 pedaços a cada 30 ms, recolhida na metade; três execuções, a máquina com outras cargas):** CPU do processo do Lumen 0,03–0,14 s e do WebView2
0,50–1,23 s em ~4,7 s (com um laço de `requestAnimationFrame` de medição forçando quadros); 283–286 quadros, intervalo médio 16,7 ms, **máximo 16,9 ms, 0 tarefas longas**. Redesenhar o texto inteiro de uma resposta de 800
palavras (o que acontece ≤ 11 vezes por segundo) leva 0,4 ms de análise de Markdown (mediana de 15; 2.500 palavras: 1,5 ms). Isto **não** é "60 FPS garantidos": é o que um roteiro sintético mediu neste PC.

## 4. Capturas (inspecionadas; a aprovação estética é sua)

`D:\Lumen\conversa-rapida-20261109\ui\chat-final2\` (Chrome, 2×): `01-vazio`, `02-respondendo`, `03-fontes`, `04-interrompida` (parcial rotulado), `06-respondendo-em-outra-janela`, `07-resposta-longa`,
`08-durante-gravacao`, `09-borda-{left,right,top,bottom}`, `10-janela-menor` (360 × 440), `00-barra-com-conversa`, `00-barra-com-compreensao-{left,top}` (cinco controles), `05-cerebro-mesma-conversa`.
WebView2 real: `ui\nativo-final\chat-left.png`, `chat-top.png`, `chat-respondendo.png`.

## 5. Falhas herdadas encontradas na linha de base (corrigidas só nos testes, não no produto)

- `tests/widget_ui.py` exigia a última categoria de Ajustes visível sem rolar; com a 7ª categoria (Proteção do cérebro) o menu rola (alcançável). Passou a rolar até a entrada.
- O servidor simulado do `widget_ui.py` devolvia `{}` para `/api/protection` e o painel de proteção quebrava ("reading 'operation'"). Agora devolve erro 503 de teste.
- `DesktopChecks.cs` esperava 6 categorias de Ajustes; são 7.
- Duas decisões minhas que mudam um teste existente: a trilha ganhou um quarto controle, então **Gravar deixou de ser o do meio** (a asserção passou a exigir o grupo centralizado, Gravar o maior e o espaçamento regular).

## 6. Limitações e o que não foi verificado

- **Mouse e teclado reais:** a barra abre por hover sem ativar a janela (`ShowWithoutActivation`; sem `WS_EX_NOACTIVATE`, conferidos); que o **clique** ative a janela e o campo receba o teclado é o comportamento padrão do Windows e do WebView2,
  mas não foi provado com um clique físico (a janela de teste é invisível e desativada, para não mexer no seu desktop).
- **Vários monitores com escalas diferentes:** só a geometria (5 áreas, de 100% a 300% de escala, origens negativas e tela pequena: 800 casos) e o painel limitado à área útil; nenhum monitor físico.
- **Recuperação do WebView2:** a recarga da página no meio de uma resposta foi provada (a pergunta volta sem resposta, tentar de novo não duplica); o evento `ProcessFailed` real não foi provocado (o código de recuperação não mudou).
- **IA:** o streaming usa um Ollama falso (incremental) e, no nativo, um `fetch` simulado na página; nenhum modelo real foi carregado. **Notion real** e **Obsidian real** não foram abertos (o abrir do Obsidian é interceptado no teste).
- **Gravação:** o indicador foi provado alimentando `QuickChat.recording()`; nenhuma gravação real foi iniciada. O código de gravar/pausar não mudou.
- **Executável oficial:** `Lumen.exe` (04/11, em uso) **não foi substituído**. O candidato, compilado com as mesmas opções do `launcher/build.ps1`, está em `D:\Lumen\conversa-rapida-20261109\native\Lumen.Isolado.exe`
  (SHA-256 `348B8AFC…D415487`, 98.304 bytes). Ele inclui também mudanças anteriores do launcher que ainda não estavam no `Lumen.exe` de 04/11.
- Os testes automáticos usam o `LUMEN_DATA` temporário do `tests/__init__.py`. A suíte completa e as primeiras rodadas usaram a pasta temporária do sistema (apagada ao fim); as rodadas finais de `widget_ui`/`chat_ui` e todas as nativas usaram pastas no D:.

## 7. Para você

1. **Sair do Lumen pelo menu** (o aberto guarda o código antigo) e, com ele fechado, copiar o candidato por cima do executável:
   `Copy-Item 'D:\Lumen\conversa-rapida-20261109\native\Lumen.Isolado.exe' 'D:\Aplicativos\lumen 2026\Lumen.exe' -Force`; abrir o Lumen.
2. Olhar: o ícone na barra (esquerda, direita, em cima e embaixo), abrir, perguntar nos dois modos, recolher no meio de uma resposta, **Abrir no Cérebro**, digitar e clicar em outro programa.
3. Julgar a estética (tamanho 420 × 620, a trilha com quatro e cinco controles, o tom das respostas). Se o tamanho incomodar, é uma constante (`WidgetForm.ChatPanel` e as variáveis `--chat-w/--chat-h` de `widget.js`).

## 8. Reversão

Restauração verificada **antes** da primeira edição: `D:\Lumen\restauracao\conversa-rapida-20261109` (241 arquivos, `MANIFEST.sha256`, `verificar.py`, `RESTAURAR.md`; inclui `lumen\study`, que não está no git).
`py -3.14 -I verificar.py --origem` lista o que mudou; `--restaurar` copia de volta. Arquivos **novos** a apagar à mão se quiser desfazer tudo: `lumen/web/chat.js`, `lumen/web/chat.css`, `lumen/web/md.js`,
`tests/chat_ui.py`, `tests/test_quick_chat.py` e este relatório. Não use `git reset`, `clean`, `stash` nem `checkout`.
