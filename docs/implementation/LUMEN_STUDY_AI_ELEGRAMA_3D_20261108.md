# /elegrama 3d e /holograma 3d: a visualização 3D dentro do chat

Pedido de 08/11/2026: gerar, direto na conversa, a mesma visualização 3D com aparência de holograma que o Lúmen já põe nas páginas das aulas
(`lumen/visual3d.py`), como material visual real: animação, imagem estática de reserva, explicação curta e download. Não é imagem de difusão
nem o diagrama SVG 2D dos Estudos (`study-diagram.js`, preservado).

Este documento registra o que foi feito e **o que foi provado nesta sessão**. Os documentos de continuidade antigos
(`docs/CONTINUIDADE-3D.md`) são histórico: os resultados deles não são testes desta sessão.

## 1. Como usar

- `/elegrama 3d <assunto>` ou `/holograma 3d <assunto>` (qualquer caixa e qualquer espaço entre as palavras). Exemplos:
  `/elegrama 3d de um computador e seus componentes`, `/elegrama 3d do sistema solar`, `/holograma 3d do ciclo da água`,
  `/holograma 3d desse processo que você explicou` (a conversa recente só é lida quando o pedido a cita).
- Menu "/": `/elegrama` e `/holograma` aparecem com `3d <assunto>`; escolher no menu escreve `/elegrama 3d ` e não envia nada.
- Sem o `3d` ou sem assunto, ou com mais de 1.500 caracteres: uma mensagem curta com um exemplo (`/elegrama 3d do sistema solar`).
  Nenhuma conversa, tarefa nem chamada de IA nasce. Não há correspondência parcial (`/elegramas`, `/elegrama3d`, `/eleg` não executam).
- O resultado aparece na conversa como um cartão: imagem 16:9, legenda, explicação curta com as partes, **Baixar animação (GIF)**,
  **Baixar PNG**, **Pausar/Reproduzir animação**, **Ampliar** (tamanho original, com rolagem só dentro do cartão) e, em conversa
  salva, **Salvar no Obsidian…/Salvar no Notion…** (a prévia de sempre; nada é publicado sozinho).

## 2. Arquitetura (o menor conjunto de mudanças)

pedido → tema → dados estruturados validados → cena 3D → renderização → arquivos conferidos → mensagem.

| Peça | Arquivo | O que faz |
| --- | --- | --- |
| Comando | `lumen/study/holo.py` `parse` | reconhece os dois nomes, `3d`, assunto e limite; devolve `{"kind": "holo", "topic"}` ou levanta o exemplo de uso |
| Registro e menu | `lumen/study/registry.py` | `elegrama` e `holograma` em `COMMANDS` (menu, autocomplete, `/ajuda`) |
| Tema | `holo.refers/explicit/recent` | só se o pedido aponta para a conversa ("desse processo") ela vira dado para a IA, sem os `[S#]` e sem arquivos gerados; sem conversa e sem assunto escrito: pede o assunto |
| Dados | `holo.schema/structure/build` | a IA devolve **só JSON** no contrato do diagrama (`diagram.schema`, mais `concept` e `sources`); `diagram.build` → `diagram.to_visual` → `visual3d.validate`. Nada que a IA escreve é executado |
| Fontes | `holo.notes` | notas e anexos que tratam do assunto entram como material; só viram fontes se a IA disser que os usou e o id existir (`geral` e ids inventados caem). Modo Livre desliga a busca |
| Desenho | `visual3d.make` | `render()` com a mesma trava de uma renderização por vez de `prepare()`; sem cache de aula, sem aula falsa, sem tocar em `visual_3d` |
| Artefato | `lumen/study/artifacts.py` `save_holo`, `save`, `file` | tipo novo **`holo`**: `file` = GIF (ou PNG na queda) e `poster.png` = PNG de reserva; MIME e extensão pelo formato real; relê do disco e confere de novo antes de publicar |
| Fila | `artifacts.run` | a mesma fila, os mesmos eventos de status e o mesmo cancelamento de `/imagem` e `/pdf` (`study_holo`) |
| Rota | `GET /api/study/artifact/file?id=…[&variant=poster]` | serve o GIF/PNG com o tipo certo; `poster` só existe para a animação |
| Cartão | `lumen/web/study.js` `holoBlock`, `study.css`, `app.js` | cartão com a animação, movimento reduzido, downloads, Ampliar; `study_holo` não parece uma aula no status global |
| Salvar | `artifacts.prepare` | o holograma vai para o Notion/Obsidian como **imagem** (`.gif` ou `.png`), pelo mesmo fluxo e a mesma prévia |

### Contrato do artefato (mensagem `meta.artifact`)

`{id, kind: "holo", name, size, format: "gif"|"png", animated, poster, width, height, frames, duration_ms, alt, state: "ok"|"static-fallback",
reason, family, schematic: true, origin}`. Em `meta.holo`: a spec validada (rótulos e índices, nunca código), `renderer`, hashes SHA-256 e o tempo.
GIF nunca é gravado como `.png`, nem declarado `image/png`; a normalização para PNG de `save()` só vale para `kind == "image"`.

### Honestidade da legenda

A cena é sempre **esquemática**; a mensagem e a imagem dizem isso e que não é "modelo científico, anatômico ou técnico exato". Sem fontes
usadas: "Sem fontes das suas notas: o conteúdo foi organizado pelo Lumen a partir do seu pedido (e da conversa) e do conhecimento geral do
modelo. Confira antes de usar." e o rodapé da imagem diz "sem fontes das suas notas". Com fontes: `[S#]` reais, clicáveis, e o rodapé
"com base nas suas notas". Nunca se atribui o conteúdo às notas sem a IA ter usado uma nota existente.

### Alternativa estática

Se a animação não couber no tempo (orçamento de 45 s, limite de 120 s) ou no peso (4,5 MB), `render()` entrega só o PNG
(`state: "static-fallback"`, `reason: "tempo"|"peso"`). O cartão mostra a imagem, "Imagem estática (PNG)", a nota "A animação não coube no
limite; esta é a alternativa estática." e **sem** botão de animação nem link de GIF. A mensagem também explica o motivo.

## 3. Consumidores atualizados

`artifacts.request/run/save/file/prepare/routes`, `attachments.LABEL` (rótulo "Holograma 3D"), `registry.COMMANDS` e a linha "Diagramas e 3D" do
catálogo, `app.js` (duas listas de tarefas do chat), `study.js` (`command`, `pickSlash`, `artifactBlock`), `study.css`.
`writes._artifact` não mudou: lê `artifacts.file()`, que agora devolve `image/gif` para o holograma.

## 4. Correções feitas no caminho (com evidência)

Ver a seção 7 abaixo.

## 5. O que foi provado nesta sessão (08/11/2026)

Ambiente: Windows 11, Python 3.14, RTX 3060 12 GB, dados isolados (`LUMEN_DATA` e temporários em `D:\Lumen\elegrama-3d-20261108\tmp`). O Ollama
pessoal (11434) não foi reiniciado nem usado nos testes; as medições com modelo de verdade usaram uma instância isolada na porta 11435, com os
mesmos modelos de `D:\Ollama\models`, encerrada ao fim. Evidências em `D:\Lumen\elegrama-3d-20261108\` (logs, amostras e capturas).

| Prova | Resultado |
| --- | --- |
| Linha de base (7 módulos relacionados, ordem própria) | 164 testes, **25 falhas** por um vazamento de teste preexistente (seção 7, bug 1); com a ordem da descoberta alfabética a suíte da tarefa anterior tinha passado (877 OK) |
| `tests/test_study_holo.py` (novo) | **34 testes OK** |
| `tests/test_visual3d.py` (+3 de rótulos), `tests/test_study_adult.py` (+1), `tests/test_study_core.py` (+1, banco novo) | OK; 39 testes novos no total |
| Suíte completa `unittest discover -s tests -t .` | **916 OK em 1251,5 s (`D:/Lumen/elegrama-3d-20261108/logs/suite-full-2.log`; a primeira rodada, com 915, passou em 1259,9 s antes da correção do banco)** (`logs/suite-full-1.log`) |
| `py -3.14 tests/study_ui.py` (Chrome headless, backend real isolado, Ollama falso, desenho no tamanho real) | **passou: 33 verificações, nenhum erro de página, CSP ou HTTP 5xx, backend sem erro registrado (`D:/Lumen/elegrama-3d-20261108/logs/ui-6.log`)**, com o cenário novo 17 |
| Fluxo real pelo `agent.turn` com modelo de verdade (instância isolada) | 7 pedidos reais com o qwen3.5:9b, 7/7 com GIF de 48 quadros distintos e reabertura, 14–59 s por pedido (`amostras/reais-final`) |

### O que o teste de interface (cenário 17) confere, na tela

Menu "/" mostra `/elegrama` e `/holograma` com `3d <assunto>`; Tab escreve `/holograma 3d ` e não envia; `/elegrama 3d` sem assunto mostra o exemplo e
não envia nada; `/ELEGRAMA 3D  de um computador…` com espaços e caixa diferentes gera; os estados reais da fila passam pela barra de status, sem
porcentagem; o cartão traz a imagem 960×540 (16:9, `naturalWidth` conferido), `alt` com o assunto, "Animação (GIF) · 960×540 · 4 s · 48 quadros";
o GIF servido tem `content-type: image/gif` e **48 quadros, 47 ou mais distintos**; o PNG de reserva é PNG; os dois downloads gravam GIF de 48
quadros e PNG válido, com o nome certo; Pausar mostra o PNG e Reproduzir volta ao GIF; nas quatro larguras (1440, 1100, 760, 520) a imagem cabe
na conversa, mantém 16:9 e a página não rola na horizontal; Ampliar mostra o tamanho original com rolagem só dentro do cartão; com
`prefers-reduced-motion` a conversa reaberta mostra o PNG parado e só anima pelo botão; a alternativa estática (cartão com `format: png`) não tem
botão de animação nem link de GIF; "Salvar no Obsidian…" mostra a prévia ("nada foi gravado"), e ao confirmar grava `lumen-<id>.gif` no cofre de
teste com 48 quadros.

### Renderizações reais inspecionadas

`D:\Lumen\elegrama-3d-20261108\amostras\`: `fixas` (respostas fixas, conteúdo conhecido, cinco assuntos: processo, sistema, estrutura,
comparação e rótulos de estresse), `fixas-2` (os dois casos corrigidos), `reais`/`reais-2`/`reais-max` (modelo de verdade) e `reais-final` (versão
final). Todas: GIF 960×540, 48 quadros, 4 s, 2,3–3,4 MB (limite 4,5 MB), PNG 176–248 KB, 4,9–6,7 s de desenho, 47 de 47 transições com
movimento e 48 quadros distintos. Cada caso tem o PNG, o GIF e uma folha com início, terço, dois terços e fim da animação (`*-quadros.png`).
Conferido a olho: legibilidade, enquadramento, sobreposição, coerência do tema e movimento da câmera, dos giros e dos pulsos.

## 6. Exemplos gerados (modelo de verdade, instância isolada)

| Pedido | Família | Modelo | Resultado |
| --- | --- | --- | --- |
| `/elegrama 3d de um computador e seus componentes` | sistema | qwen3.5:9b | processador, RAM, placa-mãe, armazenamento, fonte, placa de vídeo, sistema operacional |
| `/elegrama 3d do sistema solar` | sistema | qwen3.5:9b | Sol, planetas internos, cinturão de asteroides, planetas gigantes, Kuiper, Oort |
| `/elegrama 3d de uma célula` | estrutura | qwen3.5:9b | membrana, citoplasma, núcleo, ribossomos, mitocôndrias |
| `/holograma 3d do ciclo da água` | sistema (anel) | qwen3.5:9b | evaporação → condensação → precipitação → infiltração → escoamento |
| `/holograma 3d desse processo que você explicou` | processo | qwen3.5:9b | glicólise, Krebs, cadeia transportadora, oxigênio (tirados da conversa semeada) |
| `/elegrama 3d diferenças entre mitose e meiose` | comparação | qwen3.5:9b | lados Mitose × Meiose com número de divisões, de cromossomos e variação genética |

O mesmo pedido de comparação com o `qwen3.5:4b` (o "rápido") saiu errado: lados "Células somáticas × Gamas sexuais" e termos inventados
("Mesomorfismo", "Heteromorfismo"). Por isso o holograma usa o maior modelo local instalado (D106). Qualquer conteúdo gerado sem fontes diz
"Confira antes de usar".

## 7. Bugs e achados (reproduzidos antes de corrigir)

1. **Vazamento de teste preexistente** (`tests/test_visual3d.py` `Pages`): o patch de `llm._chat` empilhado sobre o do `Flow` era desfeito
   depois do tearDown do Flow, devolvendo ao `llm._chat` o mock do Flow, que contaminava os testes seguintes (o título "Fotossíntese" nos testes de
   Estudos). Só aparecia fora da ordem alfabética (a baseline que montei: 25 falhas). Reproduzido com `Pages` + dois testes de Estudos, com e
   sem o cache de falha do Ollama (não era dele); corrigido parando o patch na ordem inversa; a mesma combinação passou (18 OK).
2. **Comparação com os detalhes na coluna do lado errado** (`visual3d._layout`, arranjo em duas colunas): "Dupla hélice" (DNA) aparecia junto
   do RNA e "Fita simples" (RNA) junto do DNA. Reproduzido no código antigo (`logs/repro-old-visual.txt`) e na imagem
   (`amostras/fixas/comparacao-dna-rna.png`); corrigido: cada rótulo vai para a coluna do seu lado. Teste novo `Labels`.
3. **Caracteres sem glifo viravam quadrado** (`ℏ`, expoentes `⁻³⁴`): `_font` escolhia a primeira fonte da lista quando nenhuma tinha tudo, e o
   rótulo saía com "▯". Agora escolhe a que perde menos e `_drawable` troca o caractere pelo equivalente de compatibilidade (`ℏ` → `ħ`, `⁴` → `4`)
   ou o tira. Teste novo. `RENDERER` continua `holo-3` (D104).
4. **`artifacts.run` deixava OSError escapar** (disco cheio, pasta sem permissão): virava "Erro inesperado (OSError)". Agora é uma mensagem
   clara, para `/imagem`, `/pdf` e `/elegrama 3d`.
5. **`previous_profile` e arquivos gerados** (falha da minha tarefa do perfil adulto, D105): depois de um arquivo gerado numa conversa do perfil
   adulto, a conversa voltava ao principal sem aviso. Teste novo.
6. **Escolha da família e do modelo** (qualidade, medida com modelo de verdade): com o 4B, o sistema solar saiu como pilha de "camadas", a
   comparação trocou o assunto e o ciclo da água virou uma rampa sem volta. A orientação à IA ganhou exemplos por família, o ciclo passou a ser
   um anel de componentes ligados em sequência (D100/D101) e o maior modelo local organiza os dados (D106).
7. **App.js tratava a tarefa nova como uma aula**: `study_holo` entrou nas duas listas de tarefas do chat (como `study_image` e `study_pdf`).
8. **Corrida no primeiro acesso a um banco novo dos Estudos** (`db.connect`): várias threads trocando o `journal_mode` para WAL ao mesmo tempo recebiam `database is locked` na hora (essa troca não espera pelo `busy_timeout`); a primeira chamada de `/api/study/state` dava HTTP 500. Só acontece com o banco ainda inexistente (instalação nova), mas derrubou uma rodada do teste de interface (`ui-run4-falhou-db-locked`). Reproduzido com um script (115 erros em 150 bancos novos × 8 threads, `logs/repro-dblock-antes.txt`); corrigido serializando a preparação de cada conexão nova (`_CONNECT`); depois, 0 erros (`logs/repro-dblock-depois.txt`). Teste novo `FirstConnection`, que falha sem o lock (controle negativo) e passa com ele.
9. **Texto da alternativa estática** sem ponto entre "…gerada pelo Lumen" e "A animação não coube…" (achado na captura; corrigido).
10. **Defeitos do meu teste, não do código** (corrigidos no teste): `explicit("disso")` e "do que falamos" nas expressões de referência; texto
   alternativo sem o assunto (corrigido no código); pasta de mídia não isolada por teste.

## 8. Limitações (ditas sem rodeio)

- **Não foi verificado na janela nativa (WebView2)**: o teste de interface é Chrome headless contra o backend real; o `Lumen.exe` aberto carrega o código
  antigo até você **Sair pelo menu e abrir de novo**. Também não foi testado o Notion real (só a prévia e o `writes._artifact`; o fluxo de
  upload/confirmação é o das imagens e dos PDFs, já testado antes) e não houve publicação real.
- A cena é um **esquema**: não é um modelo científico, anatômico ou técnico exato (e diz isso). A qualidade do conteúdo depende do modelo local; o
  4B erra, o 9B acertou nos casos medidos (7 pedidos, um modelo, uma execução cada: sinal, não prova). Sem fontes, o conteúdo é do modelo.
- Rótulos pequenos em janela estreita (520 px): a imagem encolhe com a conversa; a lista de partes na mensagem tem o texto legível e **Ampliar**
  mostra o tamanho original com rolagem só dentro do cartão.
- Cada pedido leva 10–60 s (o modelo de 9B pode precisar ser carregado na GPU; o desenho leva ~5,5 s). Fila de uma tarefa por vez, como `/pdf`.
- A comparação mostra até dois detalhes por lado, as estruturas até cinco partes e os processos até seis etapas (limites do renderizador); o que passa
  disso vira "(+N fora da imagem)" na legenda.
- O rodapé da imagem pode ter o anel do chão passando por trás do texto em alguns quadros (desenho herdado, legível).
- **Interface intermitente no início:** das seis rodadas completas do `tests/study_ui.py`, uma falhou no primeiro carregamento da página (o estado geral não apareceu em 5 s; o log do backend ficou vazio, e a causa **não foi identificada** nem reproduzida nas rodadas seguintes), outra falhou pelo `database is locked` acima (corrigido) e as demais passaram. Os logs das duas falhas estão preservados.
- Regenerar uma resposta de arquivo gerado (API) não repete o comando: o botão não aparece no cartão (como em `/imagem` e `/pdf`).

## 9. Como desfazer

Nada foi commitado. Restauração completa (372 arquivos, SHA-256 conferido, HEAD `8816039`): `D:\Lumen\restauracao\elegrama-3d-20261108`
(`restauracao.zip`, `manifest.json`, `git-status.txt`). Para voltar um arquivo: extrair `repo/<caminho>` do ZIP sobre o original, com o Lúmen
fechado. Os arquivos novos desta tarefa podem simplesmente ser apagados: `lumen/study/holo.py`, `tests/test_study_holo.py`,
`bench/holo_chat_check.py` e este relatório; as mudanças em arquivos existentes estão na lista da seção 3 e no CHANGELOG. As conversas que já tenham
um holograma continuam abrindo (o registro é um anexo comum de `kind: "holo"`); sem o código novo, o cartão mostraria só o nome do arquivo.

## 10. O que ainda depende de você

1. **Sair pelo menu e abrir o Lúmen de novo** (o aberto carrega o código antigo), digitar `/elegrama 3d do sistema solar` e conferir o cartão na
   janela de verdade: animação, Pausar, Baixar GIF e PNG, e a largura mínima da janela.
2. Com o Notion configurado, "Salvar no Notion…" num holograma: conferir que o GIF anima lá.
3. Se o `Chat local` estiver em Automático (qwen3.5:4b), o holograma usa o maior modelo instalado (qwen3.5:9b), que a primeira vez demora mais
   para carregar. Para forçar o rápido: `/esforco rápido`.
