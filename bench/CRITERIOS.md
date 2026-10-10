# Critérios de aprovação (definidos em 07/10/2026, antes de qualquer resultado)

Estes limites não serão alterados depois de ver os números. Se nenhum modelo passar, o relatório diz isso.

## Conjuntos

| Conjunto | Origem | O que representa |
|---|---|---|
| `leitura` | FLEURS pt-BR, split *dev* (CC-BY 4.0), 80 frases | Fala lida, vários falantes, números e nomes próprios. Transcrição humana. |
| `palestra` | CORAA v1.1, TEDx pt-BR, split *dev*, 60 trechos | Fala espontânea de palestra (o mais próximo de uma aula). Transcrição humana. |
| `conversa` | CORAA v1.1 NURC-Recife, SP2010, C-ORAL-BRASIL, *dev*, 60 trechos | Entrevista/conversa espontânea com sotaques de Recife, São Paulo e Minas. Transcrição humana validada (≥ 2 votos, 0 contra). |
| `ruido` / `musica` | 40 frases de `leitura` + ruído rosa ou música sintética a 10 dB SNR | Ruído e música moderados (mistura sintética sobre fala real). |
| `aula_longa` | 40 trechos de `palestra` concatenados, falantes alternados, pausas de 0,4–3 s, 8 s de silêncio, 6 s de música sem fala, ruído de fundo a 20 dB | Aula longa com pausas e vários falantes; testa junção de segmentos, omissões e timestamps. |
| `aula_longa_2x` | `aula_longa` acelerada 2× com preservação de tom (atempo) | Conteúdo **efetivamente** acelerado (sintético a partir de fala real). |
| `sem_fala` | 30 s de silêncio, música sintética e ruído | Não pode gerar texto. |

## Critérios para o modelo padrão (GPU desta máquina)

1. `leitura`: WER ≤ 10%.
2. `palestra`: WER ≤ 20%.
3. `aula_longa`: WER ≤ 25%, taxa de omissão (D/N) ≤ 8%, nenhum trecho de referência com menos de 50% das palavras reconhecidas.
4. `sem_fala`: 0 palavras geradas. Em `aula_longa`, os trechos sem fala não podem receber texto (≥ 3 palavras com timestamp dentro do silêncio/música = falha).
5. Velocidade: ≥ 5× tempo real na GPU desta máquina (RTX 3060).
6. Gratuito, local, licença que permita uso: obrigatório.

`conversa` é reportado, mas não é critério de aprovação: é fala de conversa com sobreposição, e não o caso principal do app.

## Escolha

Entre os aprovados, vence o menor WER médio de `palestra` + `aula_longa`. Diferença menor que 1 ponto percentual
conta como empate, e o empate vai para o mais rápido. Os modos **Rápido** e **Maior precisão** serão os
melhores em velocidade e em WER, entre os que passam nos critérios 1, 4 e 6.

## Velocidade 2×

7. Em `aula_longa_2x`, a estratégia escolhida deve ter WER ≤ 1,5 × o WER do mesmo modelo em `aula_longa`.
8. Timestamps convertidos para a linha do tempo do arquivo acelerado: erro mediano ≤ 1,0 s no início dos trechos.
9. Estratégias comparadas: transcrever direto; desacelerar 0,5× com preservação de tom (atempo); desacelerar
   por reamostragem (muda o tom; incluída só como controle).

## Sinal de confiança

10. Um sinal só pode ser usado para marcar trechos "para revisão" se, em `palestra` + `conversa`, os trechos
    marcados tiverem WER pelo menos 2× maior que os não marcados. Não será exibido como probabilidade.

### Adendo (07/10/2026, antes de medir limites alternativos)

Depois do primeiro resultado parcial (turbo × small), que mostrou que a divergência entre dois modelos é um sinal
útil, fica fixada esta regra para escolher o limite de divergência por trecho (1 − semelhança entre as palavras,
`difflib`): testar 0,2, 0,3 e 0,4 e usar **o menor limite com razão ≥ 2×** (critério 10) **que marque no máximo
35% dos trechos**. A segunda transcrição só serve para marcar trechos para revisão, nunca para trocar texto
automaticamente.

### Adendo 2 (07/10/2026, antes de medir janelas aceleradas)

Modo **Automático** de velocidade: a função do app (`speech_rate`, janela de 120 s) é medida em janelas de fala
normal (palestra e conversa, falantes reais) e nas mesmas janelas aceleradas 2× com atempo. O limite `FAST_WPS` é
o ponto médio entre a maior taxa normal e a menor taxa 2×. Se as faixas se sobrepuserem, o modo Automático não é
confiável: o app passa a só sugerir e pedir confirmação. Em qualquer caso, a velocidade detectada aparece na
revisão e pode ser corrigida.

## Adendo 3 — 4x Ultra, auditoria do 2x e uso de hardware (07/10/2026, antes de qualquer medição desta rodada)

Áudio: `aula_longa` (palestras reais do CORAA com transcrição humana) acelerada 2× e 4× com atempo. Isso é
aceleração **sintética** de fala real. Não há amostra humana de aula gravada a 4×.

Modelos comparados nas mesmas condições (caminho real do app, `bench.app_check`): whisper-large-v3-turbo (atual),
whisper-large-v3, whisper-small, Parakeet TDT 0.6B v3 (CPU) e turbo em float32 (para medir a perda do float16).
Preparações: 2× → direto e 0,5×; 4× → direto, 0,5×, 0,33× e 0,25× (todas com atempo, que preserva o tom).

11. **2×**: continua valendo o critério 7 (WER ≤ 1,5 × o WER do mesmo modelo em 1×) e o 8 (timestamp ≤ 1,0 s).
    O modelo/preparação padrão de 2× é o de menor WER em 2× entre os aprovados; empate (< 1 ponto) vai para o mais rápido.
12. **4× Ultra**: aprovado se WER ≤ 2,0 × o WER do mesmo modelo em 1× **e** ≤ 30%, sem trecho de referência
    com menos de 50% das palavras reconhecidas, timestamp mediano ≤ 1,0 s e 0 palavras inventadas em
    silêncio/música. Vence o menor WER em 4× (prioridade é precisão; o tempo só desempata). Se nenhum passar, o
    modo é oferecido como **experimental**, com o erro medido mostrado ao usuário, e não como preciso.
13. **Automático**: só pode afirmar 4× se as faixas de taxa de fala (janelas de 120 s) de 2× e 4× não se
    sobrepuserem, com folga ≥ 0,5 palavra/s. Senão, quando suspeitar de aceleração, pede ao usuário para escolher.
14. **Quantização**: se float16 tiver WER maior que float32 em mais de 0,5 ponto (1× ou 2×), o modo
    "Maior precisão" usa float32.
15. **Responsividade**: durante uma transcrição longa, a API local deve responder com p95 ≤ 300 ms, e uma
    tarefa de CPU de referência rodando em paralelo não pode ficar mais de 2× mais lenta que com o PC ocioso.
    A configuração de threads/prioridade escolhida é a que cumpre isso com a menor perda de velocidade.
