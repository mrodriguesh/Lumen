# Lúmen

O Lúmen é a base local de um **segundo cérebro** para estudar: transforma aulas (gravação do som do PC, arquivo de
vídeo/áudio ou capturas de tela) em material de estudo no **Notion** e no **Obsidian**, conversa com você sobre o que já
está na sua base e protege tudo com cópias criptografadas. A transcrição e a IA rodam **no seu PC** (Whisper/Parakeet e
Ollama): sem chave de API paga e sem enviar o áudio para a nuvem.

**O Lúmen nunca cria a sua compreensão; ele complementa a que você construiu.** Antes de qualquer IA, você escreve o que
entendeu da aula; só depois a IA local analisa a sua nota contra a aula.

> Manual completo de cada tela e recurso: [docs/MANUAL.md](docs/MANUAL.md) · decisões técnicas: [docs/DECISOES.md](docs/DECISOES.md) ·
> design: [docs/DESIGN.md](docs/DESIGN.md) · teste de instalação em VM: [docs/TESTE-VM.md](docs/TESTE-VM.md)

## Funções

- **Nova aula:** grava o som que sai do PC (com pausa), abre um arquivo de vídeo/áudio ou lê capturas de tela; transcreve
  no PC (Whisper na GPU NVIDIA ou Parakeet na CPU), com detecção de fala acelerada (2× e 4×).
- **Minha compreensão:** você escreve o que entendeu (salvo a cada tecla, nas três janelas); a IA local analisa o que
  você acertou, o que faltou e o que confundiu — sem escrever por você.
- **Material salvo no Notion e/ou no Obsidian:** página da aula, mapa mental, Canvas, painel visual com as telas da aula,
  gráficos, capa (desenhada ou gerada por IA local) e visualização 3D; revisões espaçadas opcionais no Obsidian.
- **Assistir a tela junto:** lê slides, quadro e código da tela com um modelo de visão local.
- **Filtrar música externa:** protege a transcrição da música de fundo.
- **Biblioteca:** cursos, módulos, aulas avulsas, conteúdo gratuito, busca e filtros.
- **Barra flutuante:** gravar/pausar, nota da aula, conversa rápida e Pomodoro, sempre à mão na borda da tela.
- **Pomodoro** integrado (barra superior, barra flutuante e janela da nota).
- **Estudos (Lúmen Study AI):** chat com a sua base (Notion, Obsidian, PDFs e pesquisa guiada no Edge), flashcards, quiz,
  mapas, diagramas e documentos em PDF, conversa por voz e treino falado (voz local do Voice Studio), modo escuta
  (chamada transcrita ao vivo no Notion e no Obsidian).
- **Integrações:** Notion (API oficial), Obsidian, Google Drive (cópia da Proteção), Voice Studio, Open Notebook,
  HyperbookLM e o painel do Perplexity.
- **Proteção do cérebro:** cópias criptografadas e verificadas (restic) do Obsidian e do Notion, neste PC e no Google
  Drive, e o espelho Notion ↔ Obsidian.
- **Diagnóstico do sistema:** 45 verificações (obrigatórias e opcionais) com reparo do que falta.
- **Privacidade:** só IA local; tokens no Cofre de Credenciais do Windows; servidor só em `127.0.0.1` com token por sessão.

## Requisitos

| | |
|---|---|
| Sistema | **Windows 11** ou Windows 10 2004 (build 19041) ou mais novo, 64 bits. macOS e Linux: só pelo navegador, sem instalador e **não testado** (ver [Outros sistemas](#outros-sistemas)). |
| Python | 3.14 (o instalador instala se faltar) |
| Memória (RAM) | **16 GB recomendados** pelo projeto para o modelo de texto `qwen3:8b`. Medido: o Lúmen aberto, sem modelo carregado, ocupa ~0,6 GB (todos os processos); `qwen3:8b` carregado ocupa 5,59 GB e `qwen3.5:4b` 3,14 GB (Ollama, contexto de 4096). |
| Placa de vídeo | Opcional. Com NVIDIA (CUDA 12), a transcrição e a IA usam a GPU; o Whisper `large-v3-turbo` usa ~2,25 GB de VRAM (medido numa RTX 3060 12 GB). Sem GPU, tudo roda na CPU. |
| Internet | Na instalação (downloads abaixo) e para Notion, Google Drive e pesquisa na web. O resto funciona offline. |

### Espaço em disco

Medido neste projeto (GB = 10⁹ bytes). O instalador baixa tudo o que está marcado como padrão.

| Componente | Tamanho | Padrão? |
|---|---:|:---:|
| Programa do Lúmen (pacote do release: 0,015 GB) | 0,04 GB | sim |
| Ambiente Python (`.venv`) com GPU NVIDIA (CUDA) | 2,55 GB | sim (com NVIDIA) |
| Ambiente Python (`.venv`) sem GPU | [medido no teste: ver docs/TESTE-VM.md] | sim (sem NVIDIA) |
| Python 3.14 | 1,11 GB | se faltar |
| Ollama (programa) | 3,36 GB | sim |
| Modelos do Ollama (lista abaixo) | 15,74 GB | sim |
| Modelos de transcrição com GPU / sem GPU | 2,78 GB / 0,67 GB | sim |
| Filtro de música (3 modelos) | 0,07 GB | sim |
| Gerador de capas com IA | 6,79 GB | sim |
| Obsidian | 0,41 GB | sim |
| Voice Studio (programa) | 0,98 GB | sim |
| **Total com GPU NVIDIA** | **≈ 33,8 GB** | |

O Voice Studio baixa sozinho, na primeira abertura, o próprio ambiente e os modelos de voz do perfil escolhido nele (neste
PC: 10,17 GB de ambiente + 26,64 GB de modelos e dados); isso não entra no total acima. Os modelos ficam no seu perfil do
Windows (Ollama e Hugging Face) e o programa em `%LOCALAPPDATA%\Programs\Lumen`.

### Modelos locais que o instalador baixa

Sim: o comando de instalação baixa os modelos locais que o Lúmen usa. A lista vem do próprio código do Lúmen
(`installer/install.ps1` pergunta ao app quais usa); os tamanhos foram medidos no disco.

| Modelo | Para quê | Tamanho |
|---|---|---:|
| `qwen3:8b` (Ollama) | material das aulas (modelo padrão) | 5,2 GB |
| `qwen3.5:4b` (Ollama) | visão (telas) e chat dos Estudos | 3,3 GB |
| `qwen3.5:9b` (Ollama) | esforço “Máximo” dos Estudos | 6,6 GB |
| `qwen3-embedding:0.6b` (Ollama) | busca por significado | 0,64 GB |
| Whisper `large-v3-turbo` | transcrição (com GPU) | 1,62 GB |
| Whisper `small` | conferência da voz e segunda opinião (com GPU) | 0,49 GB |
| Parakeet TDT 0.6B v3 (ONNX int8) | transcrição na CPU e conversa por voz | 0,67 GB |
| Silero VAD | detecção de fala | 0,002 GB |
| YAMNet, UVR-MDX-NET, WeSpeaker ResNet34 | filtro de música | 0,07 GB |
| Z-Image-Turbo + stable-diffusion.cpp | capas geradas por IA | 6,79 GB |

Opcionais (só com `-Extras`): Whisper `large-v3` (“Maior precisão”, ≈ 3,1 GB segundo o projeto; não medido) com
`-Extras precisao`, e `qwen3.5-heretic:9b` (perfil adulto, 5,5 GB) com `-Extras adulto`.

## Instalar

O repositório é **privado**, então o instalador precisa de um token do GitHub que leia este repositório:

1. No GitHub: **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**;
   em *Repository access* escolha só **mrodriguesh/Lumen** e em *Permissions → Contents* marque **Read-only**.
2. Abra o **PowerShell** (não precisa de administrador), troque `<seu token>` pelo token e rode:

```powershell
$env:LUMEN_GITHUB_TOKEN = '<seu token>'; irm -Headers @{ Authorization = "Bearer $env:LUMEN_GITHUB_TOKEN"; Accept = 'application/vnd.github.raw' } https://api.github.com/repos/mrodriguesh/Lumen/contents/installer/install.ps1 | iex
```

O instalador ([installer/install.ps1](installer/install.ps1)) faz, em ordem: confere o Windows; busca o último release
pela API do GitHub e confere o SHA-256 do pacote; instala com o **winget** o que faltar (Python 3.14, Visual C++,
WebView2, Ollama, Obsidian); monta o ambiente Python (com GPU NVIDIA, se houver); baixa os modelos e o Voice Studio;
cria os atalhos; testa o servidor do Lúmen e abre o app. Mostra o progresso e um resumo `[OK]` / `[FALTA]` / `[MANUAL]`;
o log fica em `%LOCALAPPDATA%\Lumen-Instalador\logs`.

Pode rodar de novo quando quiser (para reparar, atualizar ou reinstalar depois de desinstalar): o que já está pronto é
pulado, e sua configuração, histórico, notas e tokens (em `%LOCALAPPDATA%\Lumen`) nunca são tocados.

Opções (troque `| iex` por `& ([scriptblock]::Create(...))` para passá-las):

```powershell
& ([scriptblock]::Create((irm -Headers @{ Authorization = "Bearer $env:LUMEN_GITHUB_TOKEN"; Accept = 'application/vnd.github.raw' } https://api.github.com/repos/mrodriguesh/Lumen/contents/installer/install.ps1))) -Skip capas
```

| Opção | Efeito |
|---|---|
| `-Skip gpu,ollama,fala,musica,capas,obsidian,voicestudio` | pula essas partes |
| `-Extras precisao,adulto` | baixa os modelos opcionais |
| `-InstallDir D:\Programas\Lumen` | outra pasta para o programa |
| `-Package <zip>` | instala de um pacote já baixado (com o `SHA256SUMS.txt` ao lado) |
| `-NoShortcuts`, `-NoLaunch`, `-Force` | sem atalhos, sem abrir no fim, reinstalar os arquivos |

**Só você pode fazer** (são segredos ou escolhas suas): colar o token da integração do Notion, entrar na conta do Google
Drive, escolher o cofre do Obsidian e a pasta/chave da Proteção. Open Notebook, HyperbookLM (com a ponte do Lúmen) e o
ambiente do Chatterbox não têm origem registrada no projeto: [fill in: como instalar Open Notebook, HyperbookLM com a
ponte do Lúmen e o Chatterbox]; o instalador só confere se já existem.

### Outros sistemas

O Lúmen roda no macOS e no Linux só pelo navegador, sem `Lumen.exe` e **sem teste** ([docs/MANUAL.md](docs/MANUAL.md#requisitos)).
Comandos do projeto, a partir de uma cópia do repositório: `python3 -m venv .venv`, `.venv/bin/pip install -r requirements.txt`
e `.venv/bin/python -m lumen`. [fill in: confirmar em macOS e Linux, que não foram testados]

## Como usar

1. Abra o **Lúmen** pelo atalho da Área de Trabalho ou do Menu Iniciar. Na primeira vez, “Antes de começar” lista o que
   falta configurar.
2. Em **Integrações**, conecte o Notion (token da integração em <https://www.notion.so/profile/integrations> e a página
   raiz) e/ou escolha o cofre do Obsidian.
3. Em **Nova aula**, escolha a fonte (gravar o som do PC, arquivo ou capturas) e clique em **Continuar**. Enquanto o Lúmen
   prepara a aula, escreva **Minha compreensão** e clique em **Processar minha compreensão** (Ctrl+Enter).
4. Leia a análise e clique em **Salvar no Notion** (ou no Obsidian). A aula fica na **Biblioteca**.
5. Use a **barra flutuante** na borda da tela para gravar, anotar e conversar; e **Estudos** para conversar com a sua base.
6. Para conferir tudo: **Ajustes → Diagnóstico do sistema**.

Fechar a janela recolhe o Lúmen na bandeja; para sair, use **Sair do Lumen** na bandeja do Windows.

## Estrutura do repositório

```
lumen/        o app: servidor local em Python (lumen/web: a interface; lumen/study: os Estudos)
launcher/     Lumen.exe em C# (WebView2), bibliotecas do WebView2 e o restic (Proteção)
installer/    install.ps1 (instalador) e publish-release.ps1 (gera o release)
docs/         manual completo, decisões, design, recuperação da Proteção e o teste em VM
tests/        testes automáticos (unittest) e verificações de interface
bench/        benchmarks que escolheram os modelos e os resultados
requirements.txt, requirements-gpu.txt, requirements-bench.txt   dependências Python
Lumen.exe, Iniciar Lumen.bat                                       abrir e instalação manual a partir do repositório
```

## Desenvolvimento

- Testes: `.venv\Scripts\python -m unittest discover -s tests -t .`
- Recompilar o `Lumen.exe`: `powershell -ExecutionPolicy Bypass -File launcher\build.ps1`
- Publicar uma versão: `powershell -ExecutionPolicy Bypass -File installer\publish-release.ps1 -Version <aaaa.mm.dd> -Publish`
  (gera o zip, o `SHA256SUMS.txt` e o `constraints.txt` com as versões testadas, e cria o release com o `gh`).
