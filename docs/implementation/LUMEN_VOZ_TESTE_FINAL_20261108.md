# Conversa por voz: teste final com microfone real e escuta (08/11/2026)

Tudo o que dava para provar sem a sua voz e sem os seus ouvidos já foi feito (ver `LUMEN_VOZ_CONVERSA_NATURAL_20261108.md`).
**Este roteiro é a única etapa que falta**, e ela só você pode fazer: nenhum teste automatizado prova que a conversa soa natural.

## Antes de começar (2 minutos)

1. **Saia do Lúmen pelo menu e abra de novo.** O Lúmen aberto guarda o código antigo; só assim a chamada nova aparece.
2. Em Estudos → Configurações → Voz → Conversa por voz, confira: modo *mãos livres*, voz *Jhonny*, fim da fala *normal*. Nada foi trocado.
3. Escolha como vai ouvir. **Faça o roteiro duas vezes**: uma com **caixas de som** (o seu uso, `call_headphones` desligado) e uma com **fones**.
4. Opcional: ligue "Mostrar os tempos de cada etapa" para ver, em cada turno, quanto levou cada parte (inclui "notas … ms").

## Roteiro (cerca de 8 minutos)

| # | Faça | O que deve acontecer | Anote |
|---|---|---|---|
| 1 | Passe o mouse no botão de onda ao lado da caixa e clique | Abre mostrando "Preparando a voz" e só depois "Ouvindo"; sem porcentagem inventada | Quanto demorou até "Ouvindo" |
| 2 | Diga: "Me explica, em poucas palavras, como o sono ajuda a memória." | Responde direto, sem saudação, sem ler símbolos ou referências | Segundos entre o fim da sua fala e o 1º som |
| 3 | Diga uma frase com pausa no meio: "Eu queria entender… [pausa de ~1 s] …como funciona o hipocampo." | Não responde durante a pausa; se começar a responder só a 1ª metade, a retomada **junta as duas partes** numa pergunta só (a metade cortada some da legenda e do histórico) | Se cortou o seu raciocínio; se a pergunta final no histórico está inteira |
| 3b | Faça uma pausa mais longa (3 a 5 s) e retome | Passou de ~4 s e antes de ouvir qualquer som: ainda junta; depois que a resposta começou a tocar, é uma pergunta nova | Qual foi o comportamento |
| 4 | Enquanto ele fala a resposta, **fale por cima** ("espera, uma pergunta") | Para em até ~0,15 s e volta a ouvir você | Se parou sozinho com o eco da caixa (sem você falar) |
| 5 | Toque em **Interromper** no meio de outra resposta | Para na hora; a legenda marca "interrompida" | O texto guardado é só o que foi falado? |
| 6 | Diga: "Usar minhas notas" e depois "Qual é o assunto das minhas notas de memória?" | Muda para **Notas**, responde citando suas notas e a legenda mostra as referências | O controle Livre/Notas mudou na tela e no chat? |
| 7 | Diga: "Ativar modo livre" e pergunte algo geral ("Como funciona um motor a combustão?") | Muda para **Livre**; não consulta o Notion nem o Obsidian | O chat escrito também ficou em Livre? |
| 8 | Pergunte "O que é o modo livre?" | **Não** troca de modo; responde como uma pergunta normal | Se trocou sem querer |
| 9 | Clique em **Mudo** com ele falando, depois tire do mudo | A resposta continua; o ponto vermelho some e volta | |
| 10 | Minimize (setinha no canto), navegue, volte pela pílula | A chamada continua; a pílula mostra estado e Livre/Notas | |
| 11 | Escreva uma pergunta no chat durante a chamada | A fala da IA para; a resposta escrita aparece no chat | |
| 12 | Encerre (botão ou Esc) | Volta ao chat com tudo em texto, na mesma conversa | |

## Escuta cega da voz (opcional, 3 minutos)

A síntese não mudou de motor, de voz nem de passos por padrão. As medições de 8, 12 e 16 passos estão no relatório, com o erro de
palavras de cada um; **a naturalidade você decide ouvindo**. Os pares estão em `D:\Lumen\voz-conversa-20261108\escuta\<execução>\`
(`curta_8p.wav`, `curta_12p.wav`, `curta_16p.wav`, `longa_*.wav`). Se o de 8 passos soar tão bom quanto o de 12, ligue
Configurações → Voz → "1º trecho mais rápido" (se existir nesta versão) para ganhar cerca de 0,3 s; se não, deixe como está.

## Se algo der errado

- A chamada não abre: veja a mensagem na própria tela (microfone, Voice Studio ou modelo) e o `lumen.log`.
- Para voltar ao código anterior: `D:\Lumen\restauracao\voz-conversa-20261108\RESTAURAR.md`.
