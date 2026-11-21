# Cápsula de gravação da barra flutuante: a pausa emerge do botão vermelho (09/11/2026)

Relatório de implementação e provas. Design em `docs/DESIGN.md` (seção *Cápsula de gravação*), decisões D148–D153 em `docs/DECISOES.md`, uso em `README.md`.
Executor: Claude Code (Sonnet 5.5). Nenhum commit, push, compra, publicação externa; nenhum C# do produto, rota, captura de áudio nem dado pessoal alterado; nenhuma gravação ou chamada
pessoal usada ou interrompida (a API de gravação foi simulada dentro da página, e a verificação nativa injeta o estado por `render()`: nenhum áudio foi capturado).

## 1. O que foi confirmado antes de editar

| Item | Confirmado |
|---|---|
| Painel e trilha | Notch 304 × 252 (a 96 DPI e no WebView2 real: `Bounds 304×252`, `WebView2 304×252`); trilha 52 px (lateral) ou 52 px de altura (deitada, grade de 4 colunas). |
| Controles existentes | `#action` + `toggleRecording()`; `#pause` + `togglePause()` (era uma pílula no painel); rotas `/api/record/start|stop|pause|resume`; `recording` vindo de `/api/widget` (poll a 250 ms gravando, 1 s parado). Tudo reaproveitado. |
| Espaço livre | Barra lateral: 33 px abaixo de Ajustes (+ folga dos gaps); deitada: ~59 px à direita de Ajustes. Com Minha compreensão (5 controles) a barra lateral quase não tem folga: resolvido com constantes menores (ver 3). |
| Estado herdado | O Gravar já virava quadrado (vermelho / âmbar pausado) e a pausa já trocava ícone via `ui.setIcon`; o painel mostra “Gravando/Pausada”. |
| Outros controles de pausa | Janela principal (`app.js`) e nota flutuante (`note.js`) têm os seus e se sincronizam pelo estado do servidor; não foram tocados. |

## 2. Restauração

`D:\Lumen\restauracao\barra-gravacao-capsula-20261109`: 1776 arquivos (lumen, tests, docs, launcher, bench, README…), `git status/diff/HEAD`, settings pessoal. Integridade conferida (0 corrompidos).
`py -3.14 -I verificar.py --origem` lista o que mudou (9 arquivos agora); `--restaurar` copia de volta (não apaga arquivos novos). Nunca usar reset/clean/stash/checkout.

## 3. Como ficou

**Estrutura** (`widget.html`): `<div id="rec-group" class="rec-group">` com `i.rec-pill` (pílula decorativa), `#action` (Gravar/Encerrar, no mesmo lugar e tamanho de antes) e `#pause` (o botão de pausa,
tirado do painel e transformado em círculo; mesmo ID, mesmo `togglePause()`), mais `p#rec-live` (anúncio discreto). Nenhum ID ou listener duplicado.

**Geometria** (`widget.css`, variáveis `--cap-*` em `.rail`; px lógicos): o Gravar não se mexe; a Pausa (30 px, 28 com nota) é posicionada em absoluto a 4 px dele e **emerge de trás do vermelho**
(`translate` + `scale .55 → 1` + `opacity`, 320 ms `--ease-emphasized`); a pílula cresce atrás (`width/height`, único elemento cujo tamanho anima); Conversa, Minha compreensão e Ajustes dão a vez
com a propriedade `translate` (a grade e a janela não mudam). Lateral: descem 30/26 px (28/24/20 com nota), Ajustes termina em y = 244 de 251. Deitada: vão 34 px (32 com nota) à direita,
terminando em x = 278 de 302. Parado, as medidas são exatamente as de antes (comparado em px no teste). Sem `zoom`, `scale` global, fonte menor ou `overflow` escondendo botão; a janela não cresce.

**Estados** (`widget.js`): `renderCapsule(recording)` aplica `data-rec` quando o estado muda (primeira leitura sem animação), troca ícone/rótulo/dica da pausa, anuncia em `#rec-live` só na mudança e
roda também durante o aviso de erro (o texto do painel fica, a cápsula mostra o real). `setBusy()` dá a espera real de cada comando (anel girando, rótulos “Iniciando gravação…”/“Encerrando gravação…”,
`aria-disabled`). `toggleRecording()` age pelo que a pessoa viu (estado diferente na leitura ⇒ mostra o real e não age), ignora um clique nos 700 ms depois de iniciar, mantém `record:ready`/`record:started`.
`poll()` descarta leituras anteriores a um comando concluído e marca `data-conn=lost` (cápsula esmaecida) sem conexão. Iniciar deixou de fechar o painel de Ajustes. Dicas: pausa curta; na barra
deitada as dicas dos controles da trilha abrem para dentro (antes cobriam os vizinhos).

**Acessibilidade:** rótulos “Iniciar/Encerrar gravação”, “Pausar/Retomar gravação”; foco visível; ordem Gravar → Pausa → Conversa; Enter/Espaço e `Ctrl+Alt+P`; pausado também muda ícone (⏸ → ▶) e texto,
não só a cor; movimento reduzido: a pausa só aparece (esmaecer de 120 ms), nada desliza. Ícones do projeto (`pause`, `play`), sem emoji.

## 4. Testes e evidências

| Execução | Resultado |
|---|---|
| `py -3.14 tests/capsule_ui.py` (novo; Chrome headless, servidor real só para arquivos, API simulada na página) | **16 blocos OK** (ver lista abaixo). |
| `tests/widget_ui.py` (ajustado: rótulos novos, guarda de 700 ms, cápsula nas medidas de grupo) | OK. |
| `tests/chat_ui.py` (24), `tests/chat_compact.py` (11), `tests/quick_settings_ui.py` (14) | OK (a trilha com cápsula aberta convive com a conversa e os ajustes). |
| `Lumen.Check.exe` **WebView2 real** (novo bloco “Cápsula de gravação”: 52 verificações + todo o resto) | **OK**: janela fica 304 × 252, Gravar fixo, quadros da transição sem sobreposição, pausa/retomar, volta ao lugar. |
| Suíte unitária completa (`unittest discover`, TEMP curto no D:, sem nada em paralelo) | **1002 testes OK** (25 min). |
| Mutação: removidas, uma a uma, a guarda de 700 ms, a ação por intenção e o descarte de leitura atrasada | Cada remoção é **pega** pelo teste esperado (blocos 4, 10 e 17); código restaurado idêntico. |

Blocos de `capsule_ui.py`: (1) parado: pausa indisponível e barra idêntica à anterior; (2) iniciar: espera visível, cliques repetidos = 1 comando, só ativa após confirmação, pausa aparece uma vez; (3) Gravar não
muda de lugar; (4) duplo clique após iniciar não encerra; (5) pausar/retomar mantêm a MESMA sessão e o contador, ícone/rótulo trocam; (6) encerrar: espera, recolhe só após confirmação, `record:ready` uma vez, volta ao
lugar; (7) início recusado: nada de gravação falsa; (8) falha de pausa/encerramento: a cápsula segue o servidor e a recuperação funciona; (9) estado vindo de outra janela (iniciar/pausar/retomar/encerrar):
acompanha, anuncia uma vez e **não reinicia a animação a cada leitura**; (10) estado diferente do visto: não age; (11) conversa/ajustes/recolher não pausam nem encerram, pausa por cima do chat; (12) cinco
posições (esquerda, direita, cima, baixo, livre) × com/sem Minha compreensão × parado/gravando/pausado, **durante** (quadros exatos a 0–340 ms) e depois da transição: nada fora da janela, sem sobreposição,
pílula dentro da barra, nenhum clique capturado por algo decorativo; (13) escalas de 100/125/150/200%: medidas lógicas idênticas; (14) teclado, foco visível, atalho, foco não se perde; (15) movimento reduzido;
(16) recarga já gravando (sem animação nem anúncio falsos), perda e volta de conexão, recarga parada, e resposta atrasada que não desfaz a pausa.

**Capturas e animação** (`D:\Lumen\barra-gravacao-capsula-20261109\ui`): `capsula\` (parado/gravando/pausado nas quatro bordas, com conversa aberta, movimento reduzido), `nativo\` (WebView2 real: parado, gravando,
pausado, esquerda e em cima), `quadros\quadros-{left,right,top,bottom}-{start,stop}.png` (folhas de contato com quadros EXATOS: as transições são pausadas e posicionadas em 0, 40, … 340 ms), `animacao\ciclo-{left,top}.webm`
(vídeo em tempo real de gravar → pausar → retomar → encerrar com cliques de mouse do navegador de teste) e `animacao\entrada-e-saida-{left,top}.gif` (quadros a cada 20 ms). **Sem afirmação de FPS:** a continuidade
foi inspecionada nos quadros exatos; a fluidez em tempo real no app depende do WebView2 por software, não medi taxa de quadros.

Inspeção visual: o botão sai de trás do vermelho, a pílula acompanha, Conversa/Ajustes deslizam sem encostar na pausa em nenhum quadro; com Minha compreensão (5 controles) a barra lateral é justa (pílula de 2 px,
vizinhos a 2–4 px) mas sem cortes; a barra deitada fica com folga à direita.

## 5. Executável verificado e aplicativo oficial

- **Verificado de fato:** `Lumen.Check.exe` compilado de `launcher/*.cs` (inalterados) + `tests/DesktopChecks.cs`, em `D:\Lumen\barra-gravacao-capsula-20261109\native` (WebView2 e janela reais, dados isolados em D:); mais o Chrome
  headless. É um executável de TESTE, não o aplicativo atualizado.
- **O `Lumen.exe` oficial não foi tocado** (SHA `EFA29C81…`, o mesmo de antes; não há mudança de C#). Ele serve as páginas do disco e o servidor dele não mudou (nenhuma rota nova): ao recarregar a página da barra (reabrir
  o Lumen), a barra oficial passa a mostrar a cápsula. Uma página da barra já aberta continua com o JavaScript antigo até recarregar. Não iniciei gravação no app oficial.

## 6. Limitações restantes

- **Barra lateral com Minha compreensão** (5 controles + pausa): cabe, mas sem folga; a pílula e os espaços ficam menores (2–4 px). Uma sexta função na trilha exigiria repensar a lateral.
- A cápsula só existe com a barra aberta. Recolhida, a alça continua a indicar gravando (vermelho) ou pausada (âmbar), como antes.
- A fluidez real (quadros por segundo) no WebView2 por software não foi medida; o movimento usa só `translate`/`scale`/`opacity` e uma pílula pequena, e há alternativa sem movimento.
- A dica da barra deitada agora abre para dentro (mudança pequena em todos os controles da trilha, para não cobrir a pausa).
- Só o usuário valida: gravar e pausar de verdade com mouse e teclado reais, nas quatro bordas e com vários monitores/DPI, e a aparência (não declaro aprovação).
