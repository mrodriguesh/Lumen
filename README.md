# Lumen

Transforma aulas em vídeo em material de estudo salvo diretamente na página escolhida do Notion.
Gratuito, sem chave de API paga: a transcrição (Whisper) e a escrita do material (Ollama) rodam no seu PC.
Só o material gerado e o link opcional da aula vão para o Notion; o áudio permanece local.

## Requisitos

- Windows 10/11 (prioritário). Também roda em macOS/Linux pelo navegador padrão, mas lá não foi testado.
- Python 3.11 ou mais novo (testado com 3.14).
- Modelos de fala: Whisper (OpenAI, MIT) e Parakeet TDT 0.6B v3 (NVIDIA, CC-BY-4.0; conversão ONNX de istupakov).
- [Ollama](https://ollama.com/download) (gratuito, MIT) com um modelo de texto. Padrão: `qwen3:8b` (≈ 5,2 GB, Apache 2.0).
- Espaço em disco: ≈ 0,5 GB (modelo Rápido) ou ≈ 1,6 GB (modelo Preciso), mais o modelo do Ollama.
- Memória: 16 GB de RAM recomendados para `qwen3:8b`. Uma GPU NVIDIA (CUDA 12) acelera bastante, mas é opcional.

## Instalar e abrir

1. Instale o Python e o Ollama. Abra o Ollama uma vez.
2. Dê dois cliques em **`Iniciar Lumen.bat`**. Na primeira vez ele cria `.venv`, instala as dependências e, se encontrar
   uma GPU NVIDIA, pergunta se deve baixar o suporte a GPU (≈ 1 GB).
3. Depois disso, abra pelo **`Lumen.exe`**: uma janela nativa com ícone próprio. Para fixar, clique com o botão
   direito no ícone dele na barra de tarefas e escolha **Fixar na barra de tarefas**. Fechar a janela recolhe o app;
   para encerrar, use o botão vermelho no rodapé da barra flutuante ou **Sair do Lumen** na bandeja do Windows.

`Lumen.exe` é um programa pequeno em C# (`launcher/Lumen.cs`) que abre a interface no WebView2 do Windows e inicia o
Python em segundo plano. Para recompilar: `powershell -ExecutionPolicy Bypass -File launcher/build.ps1` (usa o
compilador C# que já vem no Windows). O ícone é gerado por `launcher\make-icon.ps1`.

Pela linha de comando: `.venv\Scripts\python -m lumen`.

## Barra flutuante e inicialização

No `Lumen.exe`, os controles ficam escondidos em uma pequena alça na borda esquerda por padrão. Passe o mouse
para revelar a barra escura com uma animação suave; ao sair, ela se recolhe automaticamente, mesmo após um clique.
Arraste pela alça superior da barra aberta para mover, inclusive para outra tela. A posição é lembrada na próxima abertura.
Perto de uma borda ou canto, a alça se encaixa automaticamente e o painel se abre para dentro da área útil,
sem cobrir a barra de tarefas. A posição salva no formato anterior é convertida ao abrir.
Nas laterais a alça é vertical; em cima e embaixo ela é horizontal. Os controles também mudam de disposição,
e a orientação é lembrada junto com a posição. Arraste a barra aberta até a borda desejada para alternar.
A barra mostra um único botão **Gravar/Parar**, o tempo da captura e atalhos discretos para abrir o app e os ajustes.
A engrenagem abre todas as configurações dentro da própria barra, organizadas em categorias: barra flutuante,
Notion, transcrição, IA local, capas e privacidade. Os campos maiores têm rolagem e os downloads mostram progresso.
A limpeza exige confirmação e fica bloqueada durante gravações e tarefas, preservando os arquivos em uso.
Instruções de silêncio e mensagens de erro aparecem quando necessárias. Ao parar, a janela principal abre com a gravação pronta para usar.
Fechar a janela principal mantém a captura e o processamento ativos.

Em **Ajustes → Lumen sempre por perto**, escolha esquerda, direita, em cima, embaixo, posição livre ou desativada;
**Restaurar posição** recoloca a barra. **Iniciar com o Windows** registra apenas o usuário atual na chave Run,
com o caminho do executável entre aspas. O login abre o Lumen em segundo plano (`--background`), sem gravar sozinho.
Mesmo com a barra desativada, a bandeja permite abrir, acessar ajustes e sair. Ao sair durante uma gravação,
o Lumen pede confirmação e finaliza o WAV antes de encerrar.

Verificação da função: `.venv\Scripts\python.exe -m unittest tests.test_widget tests.test_record -v`.
`py tests\widget_ui.py` usa Playwright no Python do sistema e o Chrome instalado; testa a interface com API
simulada e salva imagens em `tests\desktop-artifacts`. `tests\DesktopChecks.cs` é o teste nativo: compile junto
com os dois arquivos do launcher usando `/target:exe /main:DesktopChecks`.
Os testes devem usar `LUMEN_DATA` temporário e `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` para isolar
configurações e credenciais. A verificação cobre `--background`, visibilidade, expansão, posição salva e desativação;
Também cobre mensagens atrasadas, hover repetido, quatro bordas/cantos da tela real e 480 casos de geometria com
origens negativas, telas em retrato e escalas de 100% a 300%. Não envolve reiniciar o Windows nem testar
monitores físicos com escalas diferentes.

Os modelos não são baixados sem pedido: o app mostra o tamanho e um botão **Baixar** em Configurações.

## Conectar o Notion (API oficial)

O Lumen usa uma **integração interna** do Notion. A integração pública (OAuth) exigiria um servidor com segredo de
cliente, que um app local e gratuito não pode guardar com segurança.

1. Acesse <https://www.notion.so/profile/integrations> → **Nova integração** → tipo *Interna*, no seu workspace.
2. Capacidades: *Ler conteúdo*, *Atualizar conteúdo*, *Inserir conteúdo*. Não precisa de informações de usuários.
3. Copie o token secreto e cole em **Configurações → Notion**. Ele é validado e guardado no
   Gerenciador de Credenciais do Windows (via `keyring`), nunca em arquivo.
4. No Notion, crie uma página (ex.: “Estudos”), abra **••• → Conexões** e adicione a integração.
5. Em Configurações, escolha essa página como **página raiz dos cursos**.

Você pode escolher uma página existente ou criar uma página dentro da raiz. A aula é acrescentada diretamente
à página escolhida, com um título para o material, preservando o nome, a capa, o ícone e o conteúdo anterior.
“Sem curso” é criada sob demanda quando nenhum destino específico é escolhido; as aulas ficam no corpo dela.

O Notion só mostra à integração as páginas liberadas para ela. Para escolher as **páginas raiz** do seu workspace
(as do topo da barra lateral), libere-as em <https://www.notion.so/profile/integrations> → sua integração →
**Acesso** → *Editar acesso* (o botão “Dar acesso no Notion” do app abre essa tela). Liberar uma página raiz libera
tudo o que está dentro dela; no app elas aparecem no grupo “Páginas raiz do Notion”. A API não permite que uma
integração interna crie páginas no topo do workspace, só dentro de uma página.

## Fontes

| Fonte | Estado | Como funciona |
|---|---|---|
| Gravar ao assistir | Compatível | Dê play na aula em qualquer site ou app; o Lumen grava o som que sai do PC (loopback do Windows) e transcreve localmente. Nada é baixado. Leva o tempo da aula. |
| Arquivo local | Compatível | Escolher ou arrastar. O áudio é decodificado em memória; o vídeo não sai do PC. |
| YouTube | Compatível com limitações | Link + transcrição que você fornece: colar o texto de “Mostrar transcrição”, importar `.srt`/`.vtt`/`.txt` ou escolher uma cópia local autorizada. |
| Telegram | Requer importação manual | Salve o vídeo pelo Telegram Desktop e escolha o arquivo (a pasta `Downloads\Telegram Desktop` abre direto). |

Formatos testados: MP4 (H.264/AAC), MKV (H.264/AAC), WebM (VP9/Opus), MOV (H.264/AAC), MP3, M4A (AAC), WAV (PCM).
Outros formatos são recusados com uma mensagem. Arquivos sem áudio ou corrompidos são detectados antes de começar.

## A página gerada

Em **Vídeo da aula → Link da aula**, cole o endereço do YouTube. Você também pode adicionar, trocar ou remover
esse link na revisão da transcrição, antes de **Gerar página**. O vídeo entra como player nativo do Notion na
seção **Assistir à aula**, com legenda discreta e divisor, antes do resumo. Na fonte **YouTube**, o link informado
já é usado automaticamente. Links curtos, Shorts e lives são normalizados; outros sites ficam como referência.
Não há download do vídeo. Vídeos privados, removidos ou com incorporação bloqueada podem não tocar no Notion.

Metadados (curso, data, fonte, duração, idioma, link), sumário, **Resumo**, **Mapa mental** (imagem em alta resolução
desenhada no seu PC com o Edge, a partir do mesmo pedido à IA, sem custo de tempo extra perceptível ≈ 2 s; se o envio
da imagem falhar, o mapa entra em tópicos aninhados), **Explicação simples** (marcada como
didática), **Tópicos principais** com marcadores de tempo, **Glossário**, **Exemplos e analogias** (separando “da aula”
de “analogia didática”), **Passo a passo** quando a aula ensina um procedimento, **Perguntas de revisão** (a pergunta
fica visível e a resposta dentro de um bloco *toggle*, que abre recolhido), **Momentos da aula** (no YouTube, são links
para o tempo exato) e **Sobre esta página** (origem, modelo usado, trechos de baixa confiança, ressalvas).

**Capas com IA (opcional):** em Ajustes → *Capas com IA*, baixe o Z-Image-Turbo (≈ 6,7 GB, Apache 2.0; prefira um
SSD). Ao criar uma página com “Enfeitar com IA”, a capa vira uma ilustração do tema gerada no seu PC (≈ 30–45 s
numa RTX 3060). Sem ele, a capa é desenhada com emojis.

Ao repetir uma aula, o Lumen oferece **abrir** a página existente, **atualizar material** (salva a versão nova e
remove somente os blocos gerados anteriormente pelo Lumen nessa mesma página) ou **adicionar outra cópia**.
Versões antigas em outras páginas, inclusive as subpáginas criadas antes desta correção, são preservadas.
Se a publicação falhar ou for cancelada, o app tenta remover somente os novos blocos confirmados pela API.
Se não for possível confirmar um envio ou completar a limpeza, confira a página antes de tentar novamente.

## Transcrição: modelos, revisão e velocidade 2×

Os modelos foram escolhidos por um benchmark reproduzível em português (fala lida, palestras, conversas com
sotaques, ruído, música, aula longa, aula acelerada 2×). Os critérios foram fixados antes dos resultados. Detalhes
em [bench/RESULTADOS.md](bench/RESULTADOS.md) e [bench/README.md](bench/README.md).

| Modo (Ajustes → Transcrição) | Com GPU NVIDIA | Sem GPU |
|---|---|---|
| Rápido | Whisper small · 0,48 GB | Parakeet TDT 0.6B v3 · 0,64 GB |
| **Equilibrado (padrão)** | **Whisper large-v3-turbo** · 1,6 GB | **Parakeet TDT 0.6B v3** · 0,64 GB |
| Maior precisão | Whisper large-v3 · 3,1 GB | Whisper large-v3-turbo (lento: ~1,6× o tempo real) |

Medido numa RTX 3060 / i5-11400F, palavras erradas (WER): turbo 11,5% numa aula longa simulada com palestras
reais, Parakeet 14,3% na CPU. Velocidade: turbo ≈ 23× o tempo real na GPU; Parakeet ≈ 19× na CPU.
Nenhum modelo é perfeito: em conversa espontânea o erro passa de 20%. Por isso há a revisão.

**Revisão antes de gerar.** Depois de transcrever, o Lumen mostra os trechos com o tempo de cada um. Você pode
editar qualquer trecho. Trechos com sinal de problema vêm destacados:
- “trecho incerto”: confiança baixa do Whisper;
- “modelos discordam”: na GPU, um segundo modelo ouve o mesmo áudio e o app mostra o que ele ouviu, para você
  escolher;
- “número” e “nome próprio”.

O resumo, as perguntas e a página saem **exatamente da versão revisada**. Nada é trocado sozinho. Os sinais não são
probabilidades; no teste, os trechos destacados erraram de 3,6× a 7× mais que os demais.

**Velocidade da fala.** No cartão "Revisar e gerar": **Automático**, **Normal**, **2×** ou **4× Ultra**. Vale a
velocidade **real do arquivo**: assistir em 2× ou 4× no player não acelera o arquivo, então use Normal. Na opção
*Gravar ao assistir*, o som gravado sai na velocidade do player. Legendas importadas mantêm os próprios tempos.
- **2×**: o Whisper turbo desacelera o áudio 0,5× mantendo o tom (16,2% de erro no teste, contra 11,5% em 1×).
  Small e Parakeet erram muito em 2× e são trocados pelo turbo.
- **4× Ultra (experimental)**: usa o turbo, desacelera 0,5× e desliga o contexto entre trechos. Foi a melhor de 46
  combinações testadas, mas **ainda erra cerca de 53% das palavras** em fala real acelerada 4×, e perde trechos
  inteiros. Use como rascunho para revisar; se tiver o arquivo em 1× ou 2×, prefira esse.
- **Automático**: mede palavras por segundo nos primeiros 2 minutos. **Não identifica 4× com segurança**: em fala 4×
  o modelo quase não reconhece nada. Quando a fala parece acelerada, ele sugere 2× e avisa que pode ser 4×; quando
  quase nada é reconhecido, pede que você escolha. A confirmação acontece na revisão ("Transcrever de novo").
- Os tempos da página ficam sempre no relógio do arquivo e nunca passam da duração dele.

**Hardware.**
- O Whisper roda na GPU NVIDIA via CUDA (CTranslate2), com 2,4 GB de VRAM no modo padrão. O modo Maior precisão
  usa float32 quando cabem cerca de 9 GB de VRAM livre; senão, float16.
- Antes de carregar um modelo, o app confere a VRAM livre. Se não couber, usa um menor e avisa.
- O Parakeet roda só na CPU, com um terço dos núcleos. Nos testes, foi mais rápido assim do que com todos, e o PC
  ficou mais leve.
- A revisão mostra o modelo, o dispositivo e o tipo numérico realmente usados.
- Medições em [bench/RESULTADOS.md](bench/RESULTADOS.md).

**Transcrição na página.** Opcional e desligada por padrão. Se ligada, vai no fim da página dentro de um título
recolhido, com os tempos.

A geração com `qwen3:8b` levou ≈ 30 s para uma aula curta na GPU. Na CPU, espere vários minutos. Aulas longas
(acima de ~40 mil caracteres de transcrição) são lidas por partes e depois consolidadas.

Para outro modelo, informe o nome em Configurações → IA local (ex.: `qwen3:4b` para PCs com menos memória).

## Privacidade

- Processado no PC: decodificação do áudio, transcrição, escrita do material.
- Enviado ao Notion: só o texto da página. Ao YouTube: apenas uma consulta ao oEmbed público para obter o título.
- Sem telemetria (o download dos modelos do Hugging Face roda com `HF_HUB_DISABLE_TELEMETRY=1`).
- O log (`%LOCALAPPDATA%\Lumen\lumen.log`) registra só etapas e tipos de erro, nunca tokens ou conteúdo.
- Gravações ficam no PC só até você confirmar a revisão. Transcrições ficam em `%LOCALAPPDATA%\Lumen\work` só até a página ser publicada, para permitir retomar após uma
  falha. Configurações → **Limpar histórico e dados locais** apaga tudo. **Desconectar Notion** também remove o token.
- O servidor da interface escuta só em `127.0.0.1`, confere o cabeçalho `Host` e exige um token aleatório por sessão.

## Testes

```
.venv\Scripts\python -m unittest discover -s tests -t .
```

Não usam credenciais nem a internet: Notion e Ollama são simulados (o Notion falso confere os limites documentados
da API). Verificação ponta a ponta real (Whisper + Ollama de verdade, Notion simulado):

```
.venv\Scripts\python -m tests.e2e <pasta-com-amostras>
```

Para publicar de verdade numa página **sua** de teste, defina `LUMEN_E2E_TOKEN` e `LUMEN_E2E_PARENT`.
As amostras podem ser geradas com a voz do Windows e o ffmpeg (ver `docs/DECISOES.md`).

Decisões técnicas e limitações: [docs/DECISOES.md](docs/DECISOES.md).
