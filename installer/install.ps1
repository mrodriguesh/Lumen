<#
.SYNOPSIS
    Instala, repara ou atualiza o Lumen a partir do GitHub Releases, com as dependencias e as integracoes.

.DESCRIPTION
    Uma linha, no PowerShell (sem administrador e sem conta no GitHub):

        irm https://github.com/mrodriguesh/Lumen/releases/latest/download/install.ps1 | iex

    Com opcoes:

        & ([scriptblock]::Create((irm https://github.com/mrodriguesh/Lumen/releases/latest/download/install.ps1))) -Skip capas

    Um fork privado funciona com um token em $env:LUMEN_GITHUB_TOKEN (opcional).

    O que faz, nesta ordem: confere o Windows; instala o que falta (Python 3.14, Visual C++, WebView2, Ollama) com o
    winget; baixa o ultimo release do Lumen pela API do GitHub e confere o SHA-256; troca os arquivos do programa sem
    tocar no .venv nem nos seus dados; monta o ambiente Python (com a GPU NVIDIA, se houver); baixa os modelos e as
    integracoes pelo proprio codigo do Lumen; cria os atalhos; e testa o servidor antes de abrir o app.

    Pode rodar de novo quantas vezes quiser: o que ja esta pronto e conferido e pulado. Configuracao, historico,
    notas, tokens e o cofre de credenciais nunca sao tocados (ficam em %LOCALAPPDATA%\Lumen, fora da pasta do programa).
    So endereco HTTPS; arquivo que nao confere com o SHA-256 publicado e apagado e a instalacao para.
    Log: %LOCALAPPDATA%\Lumen-Instalador\logs.

    Arquivo em ASCII de proposito: o "irm | iex" do Windows PowerShell 5.1 le o script sem saber a codificacao.

.PARAMETER Repo
    Repositorio do GitHub com os releases do Lumen (dono/nome).

.PARAMETER Version
    Tag do release (ex.: v2026.11.21) ou "latest" (padrao): o ultimo release publicado.

.PARAMETER InstallDir
    Pasta do programa. Padrao: %LOCALAPPDATA%\Programs\Lumen (so para o seu usuario, sem administrador).

.PARAMETER Package
    Zip do Lumen ja baixado (instalacao sem a API do GitHub). Precisa de um SHA256SUMS.txt ou <zip>.sha256 ao lado.

.PARAMETER Skip
    Partes a pular: gpu, ollama, fala, musica, capas, obsidian, voicestudio.

.PARAMETER Extras
    Opcionais a mais: precisao (modelo de transcricao "Maior precisao"), adulto (modelo do perfil adulto).

.PARAMETER NoShortcuts
    Nao cria nem atualiza atalhos.

.PARAMETER NoLaunch
    Nao abre o Lumen no fim.

.PARAMETER Force
    Reinstala os arquivos do programa mesmo na mesma versao e substitui atalhos que apontam para outro Lumen.
#>
[CmdletBinding()]
param(
    [string]$Repo = 'mrodriguesh/Lumen',
    [string]$Version = 'latest',
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\Lumen'),
    [string]$Package = '',
    [ValidateSet('gpu', 'ollama', 'fala', 'musica', 'capas', 'obsidian', 'voicestudio')]
    [string[]]$Skip = @(),
    [ValidateSet('precisao', 'adulto')]
    [string[]]$Extras = @(),
    [switch]$NoShortcuts,
    [switch]$NoLaunch,
    [switch]$Force
)
# caminho absoluto (relativo a pasta atual do PowerShell); aqui, no mesmo escopo do param, vale para iex, & e -File
$InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($InstallDir).TrimEnd('\')

# ======================================================================================================================
# Constantes: cada valor tem a origem no projeto ou no proprio app instalado (nada de versao solta aqui).
# ======================================================================================================================
$LumenSetup = @{
    PythonVersion    = '3.14'                           # README.md: "testado com 3.14"; o .venv do projeto usa 3.14
    PythonWinget     = 'Python.Python.3.14'
    VCRedistWinget   = 'Microsoft.VCRedist.2015+.x64'     # runtime do onnxruntime e do CTranslate2
    WebView2Winget   = 'Microsoft.EdgeWebView2Runtime'    # a janela do Lumen.exe (launcher/Lumen.cs)
    WebView2Guid     = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'  # id do WebView2 Runtime no EdgeUpdate (Microsoft)
    OllamaWinget     = 'Ollama.Ollama'
    OllamaMin        = [version]'0.30'                    # README.md: o modelo de visao pede Ollama 0.30 ou mais novo
    ObsidianWinget   = 'Obsidian.Obsidian'
    DirectML         = 'onnxruntime-directml==1.24.4'     # Iniciar Lumen.bat: filtro de musica na GPU
    VoiceStudioRepo  = 'debpalash/VoiceStudio'            # resources\app-update.yml do proprio Voice Studio
    VoiceStudioAsset = '^VoiceStudio-.+-win-x64\.exe$'
    LumenAsset       = '^Lumen-.+\.zip$'                  # nome gerado por installer/publish-release.ps1
    UserAgent        = 'Lumen-Instalador'
    Home             = Join-Path $env:LOCALAPPDATA 'Lumen-Instalador'   # cache e logs do instalador
    Marker           = '.lumen-instalacao.json'
    Report           = New-Object System.Collections.ArrayList
    LogFile          = $null
    Token            = $null
}

# ======================================================================================================================
# Infra: mensagens, log, erros, comandos externos
# ======================================================================================================================
function Write-LumenLog([string]$Text) {
    if (-not $LumenSetup.LogFile) { return }
    try { Add-Content -LiteralPath $LumenSetup.LogFile -Value ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $Text) -Encoding UTF8 } catch { }
}
function Write-Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan; Write-LumenLog "== $Text" }
function Write-Info([string]$Text) { Write-Host "    $Text"; Write-LumenLog $Text }
function Write-Done([string]$Text) { Write-Host "    [ok] $Text" -ForegroundColor Green; Write-LumenLog "[ok] $Text" }
function Write-Skipped([string]$Text) { Write-Host "    [ja estava pronto] $Text" -ForegroundColor DarkGray; Write-LumenLog "[pulado] $Text" }
function Write-Attention([string]$Text) { Write-Host "    [atencao] $Text" -ForegroundColor Yellow; Write-LumenLog "[atencao] $Text" }

function Add-Result([string]$Item, [ValidateSet('OK', 'FALTA', 'MANUAL', 'PULADO')][string]$State, [string]$Detail = '') {
    [void]$LumenSetup.Report.Add([pscustomobject]@{ Item = $Item; Estado = $State; Detalhe = $Detail })
    Write-LumenLog "[resultado] $Item = $State $Detail"
}

# Erro com explicacao para o usuario: o que aconteceu e o que fazer.
function Stop-Install([string]$What, [string]$Action = '') {
    $e = New-Object System.Exception ($What + $(if ($Action) { "`n    O que fazer: $Action" } else { '' }))
    $e.Data['lumen'] = $true
    throw $e
}

function Test-Skip([string]$Part) { return ($Skip -contains $Part) }

# Roda um programa externo. -Quiet: guarda a saida no log; sem ele, o progresso aparece direto no console.
# Devolve o codigo de saida. (2>&1 de programa nativo vira erro no PowerShell 5.1: por isso o Continue local.)
function Invoke-Native([string]$File, [string[]]$Arguments, [switch]$Quiet) {
    Write-LumenLog ('$ ' + $File + ' ' + ($Arguments -join ' '))
    $ErrorActionPreference = 'Continue'
    if ($Quiet) {
        & $File @Arguments 2>&1 | ForEach-Object { Write-LumenLog ('    ' + "$_") }
    } else {
        & $File @Arguments | Out-Host
    }
    $code = $LASTEXITCODE
    Write-LumenLog "    (codigo $code)"
    return $code
}

# Saida padrao de um programa (texto), sem mostrar nada; $null se ele nao rodar.
function Get-NativeOutput([string]$File, [string[]]$Arguments) {
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $File @Arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return (($out | ForEach-Object { "$_" }) -join "`n").Trim()
    } catch { return $null }
}

function Update-SessionPath {
    # winget e os instaladores mudam o PATH salvo; este processo so ve a mudanca se reler.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-FreePort {
    $l = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Loopback, 0)
    $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop()
    return $p
}

function Get-Sha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

# ======================================================================================================================
# Rede: GitHub API, downloads conferidos
# ======================================================================================================================
function Get-HttpStatus($ErrorRecord) {
    $r = $ErrorRecord.Exception.Response
    if ($r -and $r.StatusCode) { return [int]$r.StatusCode }
    return 0
}

# Token opcional (repositorio privado): variavel de ambiente ou o login do GitHub CLI. Nunca vai para o log.
function Get-GitHubToken {
    foreach ($name in 'LUMEN_GITHUB_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN') {
        $t = [Environment]::GetEnvironmentVariable($name)
        if ($t) { return $t.Trim() }
    }
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        $t = Get-NativeOutput 'gh' @('auth', 'token')
        if ($t) { return $t }
    }
    return $null
}

function Invoke-GitHubApi([string]$Path, [string]$Token) {
    $headers = @{ 'Accept' = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
    if ($Token) { $headers['Authorization'] = "Bearer $Token" }
    return Invoke-RestMethod -Uri ('https://api.github.com/' + $Path) -Headers $headers -UserAgent $LumenSetup.UserAgent -UseBasicParsing -TimeoutSec 60
}

function Get-GitHubRelease([string]$Repository, [string]$Tag, [string]$Token) {
    $path = if ($Tag -and $Tag -ne 'latest') { "repos/$Repository/releases/tags/$Tag" } else { "repos/$Repository/releases/latest" }
    try {
        return Invoke-GitHubApi $path $Token
    } catch {
        $code = Get-HttpStatus $_
        if ($code -eq 404) {
            Stop-Install "Nao encontrei o release '$Tag' em github.com/$Repository." ("Confira -Repo e -Version. Se o repositorio for privado, defina " +
                "`$env:LUMEN_GITHUB_TOKEN com um token que leia o repositorio (ou entre com 'gh auth login') e rode de novo.")
        }
        if ($code -eq 401) { Stop-Install 'O GitHub recusou o token informado.' 'Gere um token novo (leitura do repositorio) e defina $env:LUMEN_GITHUB_TOKEN.' }
        if ($code -eq 403 -or $code -eq 429) { Stop-Install 'O GitHub limitou as consultas deste IP por agora.' 'Espere alguns minutos ou defina $env:LUMEN_GITHUB_TOKEN e rode de novo.' }
        Stop-Install "Nao consegui falar com a API do GitHub ($($_.Exception.Message))." 'Confira a internet (e um proxy, se houver) e rode de novo.'
    }
}

function Select-ReleaseAsset($Release, [string]$Pattern) {
    $found = @($Release.assets | Where-Object { $_.name -match $Pattern })
    if ($found.Count -ne 1) {
        Stop-Install "O release $($Release.tag_name) tem $($found.Count) arquivo(s) com o nome esperado ($Pattern)." 'Publique exatamente um pacote do Lumen por release (installer/publish-release.ps1).'
    }
    return $found[0]
}

# SHA-256 esperado: o digest que o proprio GitHub calcula para cada arquivo do release e, se houver, o SHA256SUMS.txt
# publicado junto. Os dois tem de concordar; sem nenhum, nao instala.
function Get-ExpectedSha256($Release, $Asset, [string]$Token, [switch]$Required) {
    $hashes = @()
    if ($Asset.digest -and "$($Asset.digest)" -match '^sha256:([0-9a-fA-F]{64})$') { $hashes += $Matches[1].ToLowerInvariant() }
    $sums = @($Release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' })
    if ($sums.Count -eq 1) {
        $tmp = Join-Path $LumenSetup.Home ('sums-' + [guid]::NewGuid().ToString('N') + '.txt')
        try {
            Save-GitHubAsset $sums[0] $tmp $Token
            foreach ($line in Get-Content -LiteralPath $tmp) {
                if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+)$' -and $Matches[2].Trim() -eq $Asset.name) { $hashes += $Matches[1].ToLowerInvariant() }
            }
        } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    }
    $unique = @($hashes | Select-Object -Unique)
    if ($unique.Count -gt 1) { Stop-Install "O SHA-256 de $($Asset.name) no SHA256SUMS.txt nao bate com o do GitHub." 'O release foi alterado ou corrompido: nao instale; publique de novo.' }
    if ($unique.Count -eq 0) {
        if ($Required) { Stop-Install "O release nao publica o SHA-256 de $($Asset.name)." 'Publique o release com installer/publish-release.ps1 (gera o SHA256SUMS.txt).' }
        return $null
    }
    return $unique[0]
}

# Download so por HTTPS (inclusive os redirecionamentos), com retomada. O curl do Windows (10 1803+) mostra o progresso;
# o token vai num arquivo de cabecalhos temporario (nao aparece na linha de comando nem no log) e o curl nao o repassa
# para outro host num redirecionamento.
function Save-Url([string]$Url, [string]$OutFile, [hashtable]$Headers = @{}) {
    if ($Url -notmatch '^https://') { Stop-Install "Endereco sem HTTPS recusado: $Url" }
    $curl = Join-Path $env:WINDIR 'System32\curl.exe'
    if (-not (Test-Path -LiteralPath $curl)) {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -Headers $Headers -UserAgent $LumenSetup.UserAgent -UseBasicParsing -TimeoutSec 600
        return
    }
    $headerFile = Join-Path $LumenSetup.Home ('h-' + [guid]::NewGuid().ToString('N') + '.txt')
    try {
        $base = @('--fail', '--location', '--proto', '=https', '--proto-redir', '=https', '--tlsv1.2', '--retry', '4', '--retry-delay', '3',
            '--progress-bar', '--user-agent', $LumenSetup.UserAgent, '--output', $OutFile)
        if ($Headers.Count) {
            [IO.File]::WriteAllLines($headerFile, [string[]]@(foreach ($k in $Headers.Keys) { "${k}: $($Headers[$k])" }))
            $base += @('--header', "@$headerFile")
        }
        $code = Invoke-Native $curl ($base + @('--continue-at', '-', $Url))
        if (($code -eq 33 -or $code -eq 22) -and (Test-Path -LiteralPath $OutFile)) {
            # o servidor nao retomou (arquivo parcial velho): baixa do zero uma vez
            Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
            $code = Invoke-Native $curl ($base + @($Url))
        }
        if ($code -ne 0) { Stop-Install "O download falhou (curl $code): $Url" 'Confira a internet e rode o instalador de novo; ele retoma de onde parou.' }
    } finally { Remove-Item -LiteralPath $headerFile -Force -ErrorAction SilentlyContinue }
}

# Arquivo de um release pela API (serve para repositorio publico e privado).
function Save-GitHubAsset($Asset, [string]$OutFile, [string]$Token) {
    $headers = @{ 'Accept' = 'application/octet-stream' }
    if ($Token) { $headers['Authorization'] = "Bearer $Token" }
    Save-Url $Asset.url $OutFile $headers
}

# Baixa (ou reaproveita do cache) e confere o SHA-256. Arquivo que nao confere e apagado.
function Get-VerifiedAsset($Asset, [string]$Sha256, [string]$Token) {
    $cache = Join-Path $LumenSetup.Home 'cache'
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $dest = Join-Path $cache $Asset.name
    if ((Test-Path -LiteralPath $dest) -and (Get-Sha256 $dest) -eq $Sha256) { Write-Skipped "$($Asset.name) ja baixado e conferido"; return $dest }
    $part = "$dest.part"
    Write-Info ("Baixando {0} ({1:N1} MB)..." -f $Asset.name, ($Asset.size / 1MB))
    for ($try = 1; ; $try++) {
        Save-GitHubAsset $Asset $part $Token
        $got = Get-Sha256 $part
        if ($got -eq $Sha256) { break }
        Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue   # parte velha de outra versao ou arquivo corrompido
        if ($try -ge 2) {
            Stop-Install "O arquivo $($Asset.name) chegou diferente do publicado (SHA-256 $got, esperado $Sha256). Ele foi apagado." 'Rode de novo; se repetir, nao use este release.'
        }
        Write-Attention 'O arquivo baixado nao conferiu; baixando de novo do zero...'
    }
    Move-Item -LiteralPath $part -Destination $dest -Force
    Write-Done "$($Asset.name) conferido (SHA-256 $Sha256)"
    return $dest
}

# ======================================================================================================================
# Ajudante em Python: usa o proprio codigo do Lumen (mesmos modelos, URLs e regras do app; nada repetido aqui)
# ======================================================================================================================
$LumenHelperPy = @'
# Gerado pelo instalador do Lumen. Roda com o Python do .venv; argv: pasta do Lumen, comando, argumentos.
import json, sys
for stream in (sys.stdout, sys.stderr):  # console em cp1252: um "~" tipografico do Lumen nao pode derrubar o passo
    stream.reconfigure(errors="replace")
root, cmd, args = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, root)
from lumen import AppError


def main():
    if cmd == "check":  # pacotes do requirements.txt na versao fixada e importaveis (as mesmas regras do diagnostico)
        import importlib, importlib.metadata as md
        from lumen import diagnostics
        bad = []
        for dist, want in diagnostics._pins("requirements.txt") or []:
            try:
                have = md.version(dist)
                importlib.import_module(diagnostics.MODULES.get(dist, dist.replace("-", "_")))
                if want and have != want:
                    bad.append(f"{dist} {have} (fixado {want})")
            except Exception as e:  # noqa: BLE001
                bad.append(f"{dist} ({type(e).__name__})")
        try:
            import tkinter  # noqa: F401  (escolha de arquivos e pastas do app)
        except ImportError:
            bad.append("tkinter (instale o Python com tcl/tk)")
        print(json.dumps({"bad": bad}))
    elif cmd == "plan":  # o que o app usa com a configuracao atual (ou a padrao, numa instalacao nova)
        from lumen import imagegen, music, store, transcribe, vision, voice
        from lumen.study import settings
        extras, cfg, s = set(args), store.load_config(), settings.load()
        gpu = transcribe.has_gpu()
        asr = {transcribe.pick(cfg["quality"])[1]["name"], transcribe.pick("equilibrado")[1]["name"], transcribe.PARAKEET}
        if gpu:
            asr.add(voice.CHECKER)  # confere a voz e da a segunda opiniao na GPU
        if "precisao" in extras:
            asr.add(transcribe.pick("maximo")[1]["name"])
        models = [cfg["ollama_model"], vision.MODEL, settings.RECOMMENDED["local"], settings.RECOMMENDED["max"], s["models"]["embed"]]
        models += [s["models"].get(k) for k in ("local", "fast", "max")]
        if "adulto" in extras or s["adult"].get("enabled"):
            models.append(s["adult"].get("model") or settings.ADULT_RECOMMENDED)
        ollama = []
        for m in models:
            if m and m not in ollama:
                ollama.append(m)
        print(json.dumps({"gpu": gpu, "asr": sorted(asr), "asr_missing": sorted(n for n in asr if not transcribe.downloaded(n)),
                          "ollama": ollama, "music": music.ready(), "capas": imagegen.ready(), "capas_dir": str(imagegen.folder()),
                          "capas_size": imagegen.ENGINES[imagegen.DEFAULT_ENGINE]["size"], "music_size": music.SIZE}))
    elif cmd == "asr":
        from lumen import transcribe
        for name in args:
            if not transcribe.downloaded(name):
                print(f"    baixando o modelo de transcricao {name} ({transcribe.SIZES.get(name, '')})...", flush=True)
                transcribe.download(name)
    elif cmd == "music":
        from lumen import music
        if not music.ready():
            music.download()
    elif cmd == "capas":
        from lumen import imagegen
        last = [-1]

        def progress(p, eta=None):
            pct = int(p * 100)
            if pct // 5 != last[0]:
                last[0] = pct // 5
                print(f"    gerador de capas: {pct}%", flush=True)
        if not imagegen.ready():
            imagegen.download(imagegen.DEFAULT_ENGINE, progress, lambda: None)
    elif cmd == "voicestudio-open":
        from lumen import voicestudio
        voicestudio.open_app(minimized=True)
    else:
        raise SystemExit("comando desconhecido: " + cmd)


try:
    main()
except AppError as e:
    print(f"ERRO: {e} {e.action}".strip(), file=sys.stderr)
    sys.exit(1)
'@

function Invoke-LumenHelper([string]$Python, [string]$Command, [string[]]$Arguments = @(), [switch]$Json) {
    $helper = Join-Path $LumenSetup.Home 'lumen-ajudante.py'
    [IO.File]::WriteAllText($helper, $LumenHelperPy, (New-Object System.Text.UTF8Encoding $false))
    $all = @($helper, $InstallDir, $Command) + $Arguments
    if ($Json) {  # $null quando o Lumen nao consegue responder (ex.: pacotes ainda nao instalados); quem chama decide
        $out = Get-NativeOutput $Python $all
        Write-LumenLog "ajudante $Command -> $out"
        if (-not $out) { return $null }
        try { return (($out -split "`n")[-1] | ConvertFrom-Json) } catch { return $null }
    }
    Push-Location $InstallDir
    try { $code = Invoke-Native $Python $all } finally { Pop-Location }
    if ($code -ne 0) { Stop-Install "O passo '$Command' falhou (codigo $code)." "Rode o instalador de novo; detalhes no log: $($LumenSetup.LogFile)" }
}

# ======================================================================================================================
# 1. Verificacoes
# ======================================================================================================================
function Get-LumenProcesses([string]$Dir) {
    $prefix = $Dir.TrimEnd('\') + '\'
    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $p = $null; try { $p = $_.Path } catch { }
            $p -and $p.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
        })
}

function Test-Prerequisites {
    Write-Step '1/8 Conferindo o Windows'
    $os = [Environment]::OSVersion.Version
    if ($os.Major -lt 10 -or ($os.Major -eq 10 -and $os.Build -lt 19041)) {
        Stop-Install "Windows $os nao e suportado." 'Use o Windows 10 2004 (build 19041) ou mais novo, ou o Windows 11.'
    }
    if (-not [Environment]::Is64BitOperatingSystem) { Stop-Install 'O Lumen precisa de um Windows de 64 bits.' }
    Write-Done ("Windows {0} (build {1}), 64 bits; PowerShell {2}" -f $(if ($os.Build -ge 22000) { 11 } else { 10 }), $os.Build, $PSVersionTable.PSVersion)
    if (Test-IsAdmin) { Write-Attention 'Rodando como administrador: nao precisa. O Lumen e instalado so para o seu usuario.' }

    if ($InstallDir -match '^[A-Za-z]:\\?$') { Stop-Install "A pasta do programa nao pode ser a raiz de um disco ($InstallDir)." }
    if ((Test-Path -LiteralPath (Join-Path $InstallDir '.git')) -and -not $Force) {
        Stop-Install "$InstallDir e uma pasta de desenvolvimento (repositorio git); o instalador trocaria os arquivos dela." 'Escolha outra pasta com -InstallDir (ou use -Force se for de proposito).'
    }
    $known = (Test-Path -LiteralPath (Join-Path $InstallDir $LumenSetup.Marker)) -or (Test-Path -LiteralPath (Join-Path $InstallDir 'Lumen.exe'))
    if ((Test-Path -LiteralPath $InstallDir) -and -not $known -and @(Get-ChildItem -LiteralPath $InstallDir -Force).Count -and -not $Force) {
        Stop-Install "$InstallDir ja tem outros arquivos e nao e uma instalacao do Lumen." 'Use uma pasta nova ou vazia com -InstallDir.'
    }

    $drive = [IO.Path]::GetPathRoot($InstallDir)
    $free = $null
    try { $free = (New-Object IO.DriveInfo $drive).AvailableFreeSpace } catch { Write-Attention "Nao consegui medir o espaco livre em $drive." }
    # medido em 21/11/2026: o .venv completo (com as bibliotecas CUDA) ocupa ~2,5 GB; o pacote do Lumen ~0,1 GB
    if ($null -ne $free -and $free -lt 5GB) { Stop-Install ("So {0:N1} GB livres em {1}; o programa e o ambiente Python precisam de ~5 GB." -f ($free / 1GB), $drive) 'Libere espaco ou escolha outro disco com -InstallDir.' }
    if ($null -ne $free) { Write-Done ("{0:N0} GB livres em {1} (os modelos de IA ficam no seu perfil e pedem bem mais: veja o passo 6)" -f ($free / 1GB), $drive) }

    if (-not $Package) {
        try { Invoke-WebRequest -Uri 'https://api.github.com' -Method Head -UseBasicParsing -TimeoutSec 20 -Headers @{ 'User-Agent' = $LumenSetup.UserAgent } | Out-Null }
        catch { if ((Get-HttpStatus $_) -eq 0) { Stop-Install 'Sem acesso a api.github.com.' 'Confira a internet (e o proxy/firewall) e rode de novo.' } }
        Write-Done 'Internet: api.github.com responde'
    }
}

# ======================================================================================================================
# 2. Dependencias do sistema (winget primeiro; so o Visual C++ costuma pedir administrador)
# ======================================================================================================================
function Get-Winget {
    $w = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $w) {
        # Windows novo: o App Installer existe mas ainda nao foi registrado para este usuario (procedimento da Microsoft)
        try { Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe -ErrorAction Stop } catch { }
        Update-SessionPath
        $w = Get-Command winget -ErrorAction SilentlyContinue
    }
    if (-not $w) {
        Stop-Install 'O winget (Instalador de Aplicativo do Windows) nao esta disponivel.' 'Instale o "Instalador de Aplicativo" pela Microsoft Store, abra um PowerShell novo e rode de novo.'
    }
    return $w.Source
}

function Install-WingetPackage([string]$Id, [string]$Label, [switch]$UserScope, [string]$AdminReason = '') {
    $winget = Get-Winget
    if ($AdminReason) { Write-Attention "O Windows pode pedir permissao de administrador para $Label`: $AdminReason" }
    Write-Info "Instalando $Label pelo winget ($Id)..."
    $args_ = @('install', '--id', $Id, '--exact', '--source', 'winget', '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity')
    if ($UserScope) { $args_ += @('--scope', 'user') }
    $code = Invoke-Native $winget $args_
    if ($code -ne 0 -and $UserScope) {
        Write-Info "Sem instalador so para o usuario; tentando o padrao do pacote..."
        $code = Invoke-Native $winget ($args_[0..($args_.Count - 3)])
    }
    Update-SessionPath
    return $code
}

function Find-Python {
    $cands = New-Object System.Collections.Generic.List[string]
    $v = $LumenSetup.PythonVersion
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $p = Get-NativeOutput 'py.exe' @("-$v", '-c', 'import sys; print(sys.executable)')
        if ($p) { $cands.Add($p) }
    }
    $nodot = $v.Replace('.', '')
    foreach ($p in @((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$nodot\python.exe"), (Join-Path $env:ProgramFiles "Python$nodot\python.exe"))) { $cands.Add($p) }
    foreach ($c in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) { if ($c.Source -notmatch '\\WindowsApps\\') { $cands.Add($c.Source) } }
    foreach ($p in $cands) {
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $ok = Get-NativeOutput $p @('-c', "import sys, venv, tkinter; print(sys.version_info[:2] == ($($v.Replace('.', ', '))) and sys.maxsize > 2**32)")
        if ($ok -eq 'True') { return $p }
    }
    return $null
}

function Test-VCRedist {
    foreach ($k in 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64') {
        $p = Get-ItemProperty -Path $k -ErrorAction SilentlyContinue
        if ($p -and $p.Installed -eq 1) { return $p.Version }
    }
    return $null
}

function Get-WebView2Version {
    $g = $LumenSetup.WebView2Guid
    foreach ($k in "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$g", "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$g", "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$g") {
        $pv = (Get-ItemProperty -Path $k -ErrorAction SilentlyContinue).pv
        if ($pv -and $pv -ne '0.0.0.0') { return $pv }
    }
    return $null
}

function Find-Edge {
    # os mesmos lugares que lumen/cdp.py procura
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if ($base) { $e = Join-Path $base 'Microsoft\Edge\Application\msedge.exe'; if (Test-Path -LiteralPath $e) { return $e } }
    }
    return $null
}

function Install-Dependencies {
    Write-Step '3/8 Dependencias do sistema'
    $py = Find-Python
    if ($py) { Write-Skipped "Python $($LumenSetup.PythonVersion): $py" }
    else {
        Install-WingetPackage $LumenSetup.PythonWinget "Python $($LumenSetup.PythonVersion)" -UserScope | Out-Null
        $py = Find-Python
        if (-not $py) { Stop-Install "O Python $($LumenSetup.PythonVersion) nao ficou disponivel." "Instale o Python $($LumenSetup.PythonVersion) (64 bits, com tcl/tk) em python.org e rode de novo." }
        Write-Done "Python $($LumenSetup.PythonVersion): $py"
    }
    Add-Result "Python $($LumenSetup.PythonVersion)" 'OK' $py

    $vc = Test-VCRedist
    if ($vc) { Write-Skipped "Visual C++ 2015-2022 x64 ($vc)" }
    else {
        Install-WingetPackage $LumenSetup.VCRedistWinget 'o Visual C++ 2015-2022 (x64)' -AdminReason 'e uma biblioteca do sistema (usada pelo onnxruntime e pelo CTranslate2) que so instala para todos os usuarios.' | Out-Null
        $vc = Test-VCRedist
    }
    if ($vc) { Add-Result 'Visual C++ 2015-2022 x64' 'OK' $vc } else { Add-Result 'Visual C++ 2015-2022 x64' 'FALTA' 'a instalacao nao terminou (permissao negada?)' }

    $wv = Get-WebView2Version
    if ($wv) { Write-Skipped "WebView2 Runtime $wv" }
    else {
        Install-WingetPackage $LumenSetup.WebView2Winget 'o WebView2 Runtime' -AdminReason 'o instalador da Microsoft pode instalar para todos os usuarios.' | Out-Null
        $wv = Get-WebView2Version
    }
    if ($wv) { Add-Result 'WebView2 Runtime (janela do Lumen)' 'OK' $wv } else { Add-Result 'WebView2 Runtime (janela do Lumen)' 'FALTA' 'sem ele o Lumen.exe nao abre' }

    $edge = Find-Edge
    if ($edge) { Add-Result 'Microsoft Edge (capas, PDFs, /web)' 'OK' $edge }
    else { Add-Result 'Microsoft Edge (capas, PDFs, /web)' 'FALTA' 'repare o Edge pelo Windows (Configuracoes > Aplicativos)' }

    $net = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -ErrorAction SilentlyContinue).Release
    if ($net -ge 528040) { Add-Result '.NET Framework 4.8 (Lumen.exe)' 'OK' "release $net" }
    else { Add-Result '.NET Framework 4.8 (Lumen.exe)' 'FALTA' 'atualize o Windows (Windows Update)' }
    return $py
}

# ======================================================================================================================
# 3. Download e arquivos do programa
# ======================================================================================================================
function Get-LumenPackage {
    Write-Step '2/8 Baixando o Lumen'
    if ($Package) {
        $zip = (Resolve-Path -LiteralPath $Package).Path
        $name = Split-Path $zip -Leaf
        $want = $null
        $side = "$zip.sha256"
        $sums = Join-Path (Split-Path $zip -Parent) 'SHA256SUMS.txt'
        foreach ($f in @($side, $sums)) {
            if (-not (Test-Path -LiteralPath $f)) { continue }
            foreach ($line in Get-Content -LiteralPath $f) {
                if ($line -match '^([0-9a-fA-F]{64})(\s+\*?(.+))?$' -and (-not $Matches[3] -or $Matches[3].Trim() -eq $name)) { $want = $Matches[1].ToLowerInvariant() }
            }
        }
        if (-not $want) { Stop-Install "Sem SHA-256 para $name." "Ponha o SHA256SUMS.txt (ou $name.sha256) do release ao lado do zip." }
        $got = Get-Sha256 $zip
        if ($got -ne $want) { Stop-Install "$name nao confere com o SHA-256 publicado." 'Baixe o pacote de novo.' }
        Write-Done "$name (local) conferido (SHA-256 $got)"
        if (Test-InstalledCurrent $got) {
            Write-Skipped "este pacote ja esta instalado e completo em $InstallDir"
            return @{ Zip = $null; Tag = (Read-Marker).tag; Sha256 = $got; Source = $zip }
        }
        return @{ Zip = $zip; Tag = ''; Sha256 = $got; Source = $zip }
    }
    $LumenSetup.Token = Get-GitHubToken
    $release = Get-GitHubRelease $Repo $Version $LumenSetup.Token
    $asset = Select-ReleaseAsset $release $LumenSetup.LumenAsset
    $sha = Get-ExpectedSha256 $release $asset $LumenSetup.Token -Required
    Write-Info "Ultimo release: $($release.tag_name) ($($release.published_at)) em github.com/$Repo"
    if (Test-InstalledCurrent $sha) {
        Write-Skipped "Lumen $($release.tag_name) ja instalado e completo em $InstallDir"
        return @{ Zip = $null; Tag = $release.tag_name; Sha256 = $sha; Source = "github.com/$Repo" }
    }
    $zip = Get-VerifiedAsset $asset $sha $LumenSetup.Token
    return @{ Zip = $zip; Tag = $release.tag_name; Sha256 = $sha; Source = "github.com/$Repo" }
}

function Read-Marker {
    $f = Join-Path $InstallDir $LumenSetup.Marker
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    try { return (Get-Content -LiteralPath $f -Raw | ConvertFrom-Json) } catch { return $null }
}

function Wait-LumenClosed {
    $running = Get-LumenProcesses $InstallDir
    if (-not $running.Count) { return }
    Write-Attention "O Lumen desta pasta esta aberto ($(($running | ForEach-Object { $_.ProcessName }) -join ', '))."
    for ($i = 0; $i -lt 3 -and $running.Count; $i++) {
        if (-not [Environment]::UserInteractive) { break }
        Read-Host '    Feche o Lumen (bandeja do Windows > Sair do Lumen) e aperte Enter para continuar' | Out-Null
        $running = Get-LumenProcesses $InstallDir
    }
    if ($running.Count) { Stop-Install 'O Lumen continua aberto; os arquivos dele nao podem ser trocados agora.' 'Feche o Lumen pela bandeja (Sair do Lumen) e rode o instalador de novo.' }
}

# Os arquivos de que o app precisa (lumen/diagnostics.py, check_shell e check_restic; protection_drive copia os docs) e
# o restic com o hash registrado no restic-origin.json. Devolve o que falta ou nao confere (vazio = completo).
function Test-PackageContent([string]$Dir) {
    $needed = @('Lumen.exe', 'requirements.txt', 'requirements-gpu.txt', 'lumen\__main__.py', 'lumen\server.py', 'lumen\web\index.html',
        'launcher\bin\Microsoft.Web.WebView2.Core.dll', 'launcher\bin\Microsoft.Web.WebView2.WinForms.dll', 'launcher\bin\WebView2Loader.dll',
        'launcher\tools\restic.exe', 'launcher\tools\restic-origin.json', 'docs\RECUPERAR-PROTECAO.md', 'docs\recuperar-drive.py')
    $problems = @($needed | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Dir $_)) })
    if (-not $problems.Count) {
        $origin = Get-Content -LiteralPath (Join-Path $Dir 'launcher\tools\restic-origin.json') -Raw | ConvertFrom-Json
        if ((Get-Sha256 (Join-Path $Dir 'launcher\tools\restic.exe')) -ne "$($origin.exe_sha256)".ToLowerInvariant()) { $problems += 'restic.exe (SHA-256)' }
    }
    return $problems
}

function Test-InstalledCurrent([string]$Sha256) {
    $marker = Read-Marker
    return ($marker -and $marker.sha256 -eq $Sha256 -and -not $Force -and -not @(Test-PackageContent $InstallDir).Count)
}

# Troca os arquivos do programa: o novo e extraido ao lado, conferido, e so entao entra no lugar do antigo (que fica em
# .anterior ate o fim, para desfazer se algo falhar). O .venv e a marca da instalacao ficam.
function Install-LumenFiles($Pkg) {
    Write-Step '4/8 Arquivos do programa'
    if (-not $Pkg.Zip) { Add-Result "Lumen $($Pkg.Tag)" 'OK' "ja instalado em $InstallDir"; Write-Skipped "Lumen $($Pkg.Tag) em $InstallDir"; return }
    Wait-LumenClosed
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $parent = Split-Path $InstallDir -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $stage = Join-Path $parent ('.lumen-novo-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $old = Join-Path $InstallDir '.anterior'
    $keep = @('.venv', $LumenSetup.Marker, '.anterior')
    try {
        Write-Info 'Extraindo e conferindo o pacote...'
        [IO.Compression.ZipFile]::ExtractToDirectory($Pkg.Zip, $stage)
        $problems = @(Test-PackageContent $stage)
        if ($problems.Count) { Stop-Install "O pacote do Lumen esta incompleto ou alterado ($($problems -join ', '))." 'Nao instale este pacote; publique o release de novo com installer/publish-release.ps1.' }
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
        New-Item -ItemType Directory -Path $old | Out-Null
        $moved = New-Object System.Collections.Generic.List[string]
        try {
            foreach ($item in @(Get-ChildItem -LiteralPath $InstallDir -Force | Where-Object { $keep -notcontains $_.Name })) {
                Move-Item -LiteralPath $item.FullName -Destination (Join-Path $old $item.Name); $moved.Add($item.Name)
            }
            foreach ($item in @(Get-ChildItem -LiteralPath $stage -Force)) { Move-Item -LiteralPath $item.FullName -Destination (Join-Path $InstallDir $item.Name) }
        } catch {
            Write-Attention 'A troca falhou; voltando a versao anterior...'
            # depois da saida dos antigos, o que nao e protegido ($keep) so pode ser do pacote novo
            foreach ($item in @(Get-ChildItem -LiteralPath $InstallDir -Force | Where-Object { $keep -notcontains $_.Name })) {
                Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction SilentlyContinue
            }
            foreach ($name in $moved) { Move-Item -LiteralPath (Join-Path $old $name) -Destination (Join-Path $InstallDir $name) -ErrorAction SilentlyContinue }
            Stop-Install "Nao foi possivel trocar os arquivos do Lumen ($($_.Exception.Message)). A versao anterior foi mantida." 'Feche o Lumen e programas abertos nessa pasta e rode de novo.'
        }
        Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
    }
    $version = ''
    $vf = Join-Path $InstallDir 'VERSION.json'
    if (Test-Path -LiteralPath $vf) { $version = (Get-Content -LiteralPath $vf -Raw | ConvertFrom-Json).version }
    $tag = $(if ($Pkg.Tag) { $Pkg.Tag } else { $version })
    $marker = [ordered]@{ tag = $tag; version = $version; sha256 = $Pkg.Sha256; source = $Pkg.Source; installed = (Get-Date).ToString('o') }
    [IO.File]::WriteAllText((Join-Path $InstallDir $LumenSetup.Marker), ($marker | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))
    $Pkg.Tag = $tag
    Write-Done "Lumen $tag em $InstallDir"
    Add-Result "Lumen $tag" 'OK' $InstallDir
}

# ======================================================================================================================
# 4. Ambiente Python (.venv) com os pacotes fixados no requirements.txt (e os de GPU, se houver NVIDIA)
# ======================================================================================================================
function Test-NvidiaGpu { return [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue) }   # o mesmo teste do Iniciar Lumen.bat

function Install-PythonEnvironment([string]$Python) {
    Write-Step '5/8 Ambiente Python do Lumen'
    $venv = Join-Path $InstallDir '.venv'
    $vpy = Join-Path $venv 'Scripts\python.exe'
    $v = $LumenSetup.PythonVersion
    # sem aspas duplas no codigo: o PowerShell 5.1 nao as escapa ao passar argumentos para programas externos
    $now = if (Test-Path -LiteralPath $vpy) { Get-NativeOutput $vpy @('-c', "import sys; print('%d.%d' % sys.version_info[:2])") } else { $null }
    if ($now -ne $v) {
        if (Test-Path -LiteralPath $venv) { Write-Info "O .venv existente nao roda com o Python $v; recriando..."; Wait-LumenClosed; Remove-Item -LiteralPath $venv -Recurse -Force }
        Write-Info 'Criando o .venv...'
        if ((Invoke-Native $Python @('-m', 'venv', $venv) -Quiet) -ne 0) { Stop-Install 'Nao foi possivel criar o ambiente Python (.venv).' "Veja o log: $($LumenSetup.LogFile)" }
    }
    $gpu = (Test-NvidiaGpu) -and -not (Test-Skip 'gpu')
    $req = Join-Path $InstallDir 'requirements.txt'
    $reqGpu = Join-Path $InstallDir 'requirements-gpu.txt'
    # constraints.txt: as versoes exatas de TODAS as dependencias (inclusive as indiretas) do ambiente em que o release foi
    # testado (publish-release.ps1); sem ele, o pip escolheria versoes novas nao testadas (ex.: huggingface-hub 2.x)
    $cons = Join-Path $InstallDir 'constraints.txt'
    $c = @(); if (Test-Path -LiteralPath $cons) { $c = @('-c', $cons) }
    $want = (Get-Sha256 $req) + $(if ($c.Count) { '+c:' + (Get-Sha256 $cons) } else { '' }) +
        $(if ($gpu) { '+gpu:' + (Get-Sha256 $reqGpu) + ':' + $LumenSetup.DirectML } else { '' })
    $stamp = Join-Path $venv '.lumen-requisitos'
    $ready = (Test-Path -LiteralPath $stamp) -and ((Get-Content -LiteralPath $stamp -Raw).Trim() -eq $want)
    if ($ready) {
        $check = Invoke-LumenHelper $vpy 'check' -Json
        $ready = $check -and -not @($check.bad).Count
    }
    if ($ready) { Write-Skipped 'pacotes do requirements.txt nas versoes fixadas' }
    else {
        Wait-LumenClosed
        $pip = @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-input')
        Write-Info 'Instalando os pacotes do requirements.txt (a primeira vez demora)...'
        if ((Invoke-Native $vpy ($pip + @('-r', $req) + $c)) -ne 0) { Stop-Install 'O pip nao conseguiu instalar os pacotes do Lumen.' 'Confira a internet e rode de novo (o pip retoma).' }
        if ($gpu) {
            Write-Info 'GPU NVIDIA: bibliotecas CUDA (requirements-gpu.txt, ~1 GB) e onnxruntime-directml...'
            if ((Invoke-Native $vpy ($pip + @('-r', $reqGpu) + $c)) -ne 0) { Stop-Install 'O pip nao conseguiu instalar o suporte a GPU.' 'Rode de novo, ou use -Skip gpu para transcrever na CPU.' }
            # o onnxruntime-directml ocupa o lugar do onnxruntime de CPU (mesmo modulo), como no Iniciar Lumen.bat. Os dois
            # gravam na mesma pasta onnxruntime\: desinstalar o de CPU apaga arquivos do DirectML, que entao e reposto.
            $again = @()
            if (Get-NativeOutput $vpy @('-m', 'pip', 'show', '--disable-pip-version-check', 'onnxruntime')) {
                Invoke-Native $vpy @('-m', 'pip', 'uninstall', '--disable-pip-version-check', '-y', 'onnxruntime') -Quiet | Out-Null
                if (Get-NativeOutput $vpy @('-m', 'pip', 'show', '--disable-pip-version-check', 'onnxruntime-directml')) { $again = @('--force-reinstall', '--no-deps') }
            }
            if ((Invoke-Native $vpy ($pip + $again + @($LumenSetup.DirectML) + $c)) -ne 0) {
                Write-Attention 'onnxruntime-directml nao instalou; voltando ao onnxruntime de CPU.'
                Invoke-Native $vpy ($pip + @('onnxruntime')) | Out-Null
            }
        }
        $check = Invoke-LumenHelper $vpy 'check' -Json
        if (-not $check) { Stop-Install 'O Lumen nao conseguiu carregar depois da instalacao dos pacotes.' "Veja o log: $($LumenSetup.LogFile)" }
        if (@($check.bad).Count) { Stop-Install "Pacotes do Lumen com problema: $(@($check.bad) -join '; ')." "Rode de novo; detalhes no log: $($LumenSetup.LogFile)" }
        [IO.File]::WriteAllText($stamp, $want)
        Set-Content -LiteralPath (Join-Path $venv '.instalado') -Value 'ok' -Encoding ASCII   # o Iniciar Lumen.bat nao reinstala
        Write-Done 'pacotes instalados e conferidos'
    }
    Add-Result 'Ambiente Python (.venv)' 'OK' $(if ($gpu) { 'com GPU NVIDIA (CUDA + DirectML)' } else { 'CPU' })
    return $vpy
}

# ======================================================================================================================
# 5. Integracoes e modelos
# ======================================================================================================================
function Find-Ollama {
    $c = Get-Command ollama -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $p) { return $p }
    return $null
}

function Get-OllamaApi([string]$Path) {
    try { return Invoke-RestMethod -Uri ("http://127.0.0.1:11434" + $Path) -UseBasicParsing -TimeoutSec 5 } catch { return $null }
}

function Install-Ollama {
    $exe = Find-Ollama
    if (-not $exe) {
        Install-WingetPackage $LumenSetup.OllamaWinget 'o Ollama (IA local)' | Out-Null
        $exe = Find-Ollama
        if (-not $exe) { Stop-Install 'O Ollama nao ficou instalado.' 'Instale o Ollama (ollama.com) e rode o instalador de novo.' }
    }
    $ver = Get-NativeOutput $exe @('--version')
    if ($ver -match '(\d+\.\d+(\.\d+)?)' -and [version]$Matches[1] -lt $LumenSetup.OllamaMin) {
        Write-Info "Ollama $($Matches[1]) e antigo (o Lumen pede $($LumenSetup.OllamaMin)+); atualizando..."
        Invoke-Native (Get-Winget) @('upgrade', '--id', $LumenSetup.OllamaWinget, '--exact', '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity') | Out-Null
    }
    if (-not (Get-OllamaApi '/api/version')) {
        $app = Join-Path (Split-Path $exe -Parent) 'ollama app.exe'
        if (Test-Path -LiteralPath $app) { Start-Process -FilePath $app } else { Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden }
        for ($i = 0; $i -lt 60 -and -not (Get-OllamaApi '/api/version'); $i++) { Start-Sleep -Seconds 1 }
    }
    $api = Get-OllamaApi '/api/version'
    if (-not $api) { Stop-Install 'O Ollama nao respondeu em 127.0.0.1:11434.' 'Abra o Ollama pelo menu Iniciar uma vez e rode o instalador de novo.' }
    Write-Done "Ollama $($api.version) respondendo"
    return $exe
}

function Install-OllamaModels([string]$Exe, [string[]]$Models) {
    $have = @((Get-OllamaApi '/api/tags').models | ForEach-Object { $_.name })
    foreach ($m in $Models) {
        $full = if ($m -match ':') { $m } else { "$m`:latest" }
        if ($have -contains $m -or $have -contains $full) { Write-Skipped "modelo $m"; continue }
        Write-Info "Baixando o modelo $m pelo Ollama..."
        if ((Invoke-Native $Exe @('pull', $m)) -ne 0) { Stop-Install "O Ollama nao baixou o modelo $m." 'Confira a internet e o espaco em disco e rode de novo (o download retoma).' }
    }
}

function Find-VoiceStudio { $p = Join-Path $env:LOCALAPPDATA 'Programs\VoiceStudio\VoiceStudio.exe'; if (Test-Path -LiteralPath $p) { return $p }; return $null }   # lumen/voicestudio.py: EXE

function Install-VoiceStudio([string]$Python) {
    if (Find-VoiceStudio) { Write-Skipped 'Voice Studio (ele se atualiza sozinho)'; return }
    $release = Get-GitHubRelease $LumenSetup.VoiceStudioRepo 'latest' $null
    $asset = Select-ReleaseAsset $release $LumenSetup.VoiceStudioAsset
    $sha = Get-ExpectedSha256 $release $asset $null -Required
    $exe = Get-VerifiedAsset $asset $sha $null
    $sig = Get-AuthenticodeSignature -LiteralPath $exe
    if ($sig.Status -ne 'Valid') { Write-Attention "O instalador do Voice Studio nao tem assinatura digital valida ($($sig.Status)); conferido pelo SHA-256 do GitHub." }
    Write-Info "Instalando o Voice Studio $($release.tag_name) (silencioso, so para o seu usuario)..."
    $p = Start-Process -FilePath $exe -ArgumentList '/S' -Wait -PassThru
    if (-not (Find-VoiceStudio)) { Stop-Install "O instalador do Voice Studio terminou (codigo $($p.ExitCode)) mas o app nao apareceu." 'Rode o instalador de novo.' }
    # a primeira abertura do app prepara o backend e baixa os modelos de voz (tudo feito pelo proprio Voice Studio)
    Invoke-LumenHelper $Python 'voicestudio-open'
    Write-Done "Voice Studio $($release.tag_name) instalado; ele termina a preparacao (modelos de voz) aberto, minimizado"
}

function Invoke-Part([string]$Name, [string]$Label, [scriptblock]$Body) {
    if (Test-Skip $Name) { Add-Result $Label 'PULADO' "-Skip $Name"; return }
    try { $detail = & $Body; Add-Result $Label 'OK' "$detail" }
    catch {
        $msg = $_.Exception.Message
        Write-Attention "$Label`: $msg"
        Add-Result $Label 'FALTA' ($msg -split "`n")[0]
    }
}

function Install-Integrations([string]$Python) {
    Write-Step '6/8 Modelos e integracoes'
    $plan = Invoke-LumenHelper $Python 'plan' $Extras -Json
    if (-not $plan) { Stop-Install 'Nao consegui ler do Lumen quais modelos ele usa.' "Veja o log: $($LumenSetup.LogFile)" }
    Write-Info ("Modelos que o Lumen usa nesta configuracao: Ollama {0}; transcricao {1}" -f (@($plan.ollama) -join ', '), (@($plan.asr) -join ', '))

    Invoke-Part 'ollama' 'Ollama e modelos de IA local' {
        $exe = Install-Ollama
        Install-OllamaModels $exe @($plan.ollama)
        (@($plan.ollama) -join ', ')
    }
    Invoke-Part 'fala' 'Modelos de transcricao' {
        if (@($plan.asr_missing).Count) { Invoke-LumenHelper $Python 'asr' @($plan.asr_missing) } else { Write-Skipped "transcricao: $(@($plan.asr) -join ', ')" }
        (@($plan.asr) -join ', ')
    }
    Invoke-Part 'musica' 'Filtro de musica externa (modelos)' {
        if ($plan.music) { Write-Skipped 'filtro de musica' } else { Write-Info "Baixando o filtro de musica ($($plan.music_size))..."; Invoke-LumenHelper $Python 'music' }
        $plan.music_size
    }
    Invoke-Part 'capas' 'Gerador de capas com IA' {
        if ($plan.capas) { Write-Skipped 'gerador de capas' } else { Write-Info "Baixando o gerador de capas ($($plan.capas_size), em $($plan.capas_dir))..."; Invoke-LumenHelper $Python 'capas' }
        $plan.capas_dir
    }
    Invoke-Part 'obsidian' 'Obsidian (app)' {
        if (Test-Path 'HKCU:\Software\Classes\obsidian') { Write-Skipped 'Obsidian' }   # o Lumen abre as notas por obsidian://
        else {
            Install-WingetPackage $LumenSetup.ObsidianWinget 'o Obsidian' -UserScope | Out-Null
            if (-not (Test-Path 'HKCU:\Software\Classes\obsidian') -and -not (Test-Path 'HKLM:\Software\Classes\obsidian')) { Stop-Install 'O Obsidian nao ficou instalado.' }
        }
        'escolha o cofre em Integracoes > Obsidian'
    }
    Invoke-Part 'voicestudio' 'Voice Studio (voz dos Estudos)' { Install-VoiceStudio $Python; Find-VoiceStudio }
    Add-ManualItems
}

# O que depende de conta, segredo ou de uma origem que o projeto nao registra: fica dito, nunca inventado.
function Add-ManualItems {
    Add-Result 'Notion' 'MANUAL' 'Integracoes > Notion: cole o token (https://www.notion.so/profile/integrations) e escolha a pagina raiz'
    Add-Result 'Protecao do cerebro (backup)' 'MANUAL' 'Ajustes > Protecao do cerebro: escolha a pasta da copia e guarde a chave (o restic ja vem no pacote)'
    Add-Result 'Google Drive (copia da Protecao)' 'MANUAL' 'Integracoes > Google Drive: entre com a sua conta (opcional)'
    Add-Result 'Perplexity' 'MANUAL' 'nada a instalar; entre no site pelo painel, se quiser (opcional)'
    $on = 'D:\Aplicativos\open-notebook'   # lumen/onlocal.py: REPO (caminho fixo do app)
    if (Test-Path -LiteralPath $on) { Add-Result 'Open Notebook' 'OK' "encontrado em $on" }
    else { Add-Result 'Open Notebook' 'MANUAL' '[fill in: como instalar o Open Notebook (lfnovo/open-notebook) nas pastas que lumen/onlocal.py espera]' }
    $hb = $(if ($env:LUMEN_HYPERBOOKLM_DIR) { $env:LUMEN_HYPERBOOKLM_DIR } else { 'D:\Aplicativos\hyperbooklm' })   # lumen/repair.py: HB_REPO
    if (Test-Path -LiteralPath (Join-Path $hb 'app\api\lumen\route.ts')) { Add-Result 'HyperbookLM' 'OK' "encontrado em $hb (o Diagnostico do Lumen instala as dependencias dele)" }
    else { Add-Result 'HyperbookLM' 'MANUAL' '[fill in: repositorio do HyperbookLM com a ponte do Lumen (app/api/lumen); o hyperbrowserai/hyperbooklm original nao a tem]' }
    $cb = Join-Path $(if ($env:LUMEN_VOICE_DIR) { $env:LUMEN_VOICE_DIR } else { 'D:\Lumen\voz' }) 'chatterbox\Scripts\python.exe'   # lumen/voice.py
    if (Test-Path -LiteralPath $cb) { Add-Result 'Chatterbox (voz de reserva)' 'OK' $cb }
    else { Add-Result 'Chatterbox (voz de reserva)' 'MANUAL' '[fill in: origem do ambiente D:\Lumen\voz\chatterbox] (opcional; o Voice Studio e o motor principal)' }
}

# ======================================================================================================================
# 6. Configuracao do Windows: atalhos e "Abrir com o Windows" (so repara o que aponta para um Lumen que nao existe mais)
# ======================================================================================================================
function Set-Shortcut([string]$Path, [string]$Exe) {
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $Path) {
        $target = $shell.CreateShortcut($Path).TargetPath
        if ($target -ieq $Exe) { Write-Skipped "atalho $Path"; return 'OK' }
        if ($target -and (Test-Path -LiteralPath $target) -and -not $Force) {
            Write-Attention "O atalho $Path aponta para outro Lumen ($target); mantido (use -Force para trocar)."
            return 'MANTIDO'
        }
    }
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $Exe
    $lnk.WorkingDirectory = Split-Path $Exe -Parent
    $lnk.IconLocation = "$Exe,0"
    $lnk.Description = 'Lumen'
    $lnk.Save()
    Write-Done "atalho $Path"
    return 'OK'
}

function Set-LumenConfiguration {
    Write-Step '7/8 Atalhos e inicializacao'
    $exe = Join-Path $InstallDir 'Lumen.exe'
    if ($NoShortcuts) { Add-Result 'Atalhos' 'PULADO' '-NoShortcuts' }
    else {
        $states = @(
            Set-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Lumen.lnk') $exe
            Set-Shortcut (Join-Path ([Environment]::GetFolderPath('Programs')) 'Lumen.lnk') $exe
        )
        Add-Result 'Atalhos (Area de Trabalho e Menu Iniciar)' 'OK' $(if ($states -contains 'MANTIDO') { 'algum aponta para outro Lumen (mantido)' } else { $exe })
    }
    # "Iniciar com o Windows" e escolha do usuario (Ajustes > Geral); so conserta o valor que aponta para um exe apagado
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $run = (Get-ItemProperty -Path $runKey -ErrorAction SilentlyContinue).Lumen
    if ($run -and $run -match '^"([^"]+)"' -and -not (Test-Path -LiteralPath $Matches[1])) {
        Set-ItemProperty -Path $runKey -Name 'Lumen' -Value ('"' + $exe + '" --background')
        Write-Done 'Abrir com o Windows: apontava para um Lumen apagado; agora abre este'
    }
}

# ======================================================================================================================
# 7. Verificacao: arquivos, pacotes, e o servidor de verdade (dados temporarios, sem tocar nos seus)
# ======================================================================================================================
function Test-LumenServer([string]$Python) {
    $port = Get-FreePort
    $data = Join-Path $env:TEMP ('lumen-verificacao-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $psi = New-Object System.Diagnostics.ProcessStartInfo $Python, '-m lumen'
    $psi.WorkingDirectory = $InstallDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.EnvironmentVariables['LUMEN_DATA'] = $data
    $psi.EnvironmentVariables['LUMEN_PORT'] = "$port"
    $psi.EnvironmentVariables['LUMEN_NO_WINDOW'] = '1'
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $up = $false
        for ($i = 0; $i -lt 120 -and -not $up -and -not $proc.HasExited; $i++) {
            try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect('127.0.0.1', $port); $c.Close(); $up = $true } catch { Start-Sleep -Milliseconds 500 }
        }
        if (-not $up) { throw "o servidor nao abriu a porta $port" }
        $html = (Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 30).Content
        if ($html -notmatch 'name="lumen-token" content="([^"]+)"') { throw 'a pagina principal veio sem o token' }
        return Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/state" -Headers @{ 'X-Lumen-Token' = $Matches[1] } -UseBasicParsing -TimeoutSec 120
    } finally {
        if (-not $proc.HasExited) { Invoke-Native 'taskkill.exe' @('/T', '/F', '/PID', "$($proc.Id)") -Quiet | Out-Null }   # o .venv abre o Python real como filho
        Start-Sleep -Milliseconds 500
        Remove-Item -LiteralPath $data -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Test-LumenInstall([string]$Python) {
    Write-Step '8/8 Conferindo a instalacao'
    try {
        $state = Test-LumenServer $Python
        Write-Done 'o servidor do Lumen abriu e respondeu /api/state'
        Add-Result 'Servidor do Lumen (teste real)' 'OK' $(if ($state.gpu) { 'GPU NVIDIA em uso' } else { 'CPU' })
        $w = $state.whisper.models.($state.whisper.active)
        if ($w.downloaded) { Add-Result 'Transcricao pronta' 'OK' "$($w.name) ($($w.label))" }
        elseif (-not (Test-Skip 'fala')) { Add-Result 'Transcricao pronta' 'FALTA' "modelo $($w.name) nao encontrado" }
        if (-not (Test-Skip 'ollama')) {
            if ($state.ollama.running -and $state.ollama.installed) { Add-Result 'IA local pronta' 'OK' 'Ollama com o modelo das aulas' }
            else { Add-Result 'IA local pronta' 'FALTA' 'o Ollama nao respondeu ou falta o modelo das aulas' }
        }
    } catch {
        Write-Attention "o teste do servidor falhou: $($_.Exception.Message)"
        Add-Result 'Servidor do Lumen (teste real)' 'FALTA' "$($_.Exception.Message); log em $($LumenSetup.LogFile)"
    }
}

function Show-Report {
    Write-Host ''
    Write-Host 'Resumo' -ForegroundColor Cyan
    $colors = @{ OK = 'Green'; FALTA = 'Red'; MANUAL = 'Yellow'; PULADO = 'DarkGray' }
    foreach ($r in $LumenSetup.Report) {
        Write-Host ('  [{0,-6}] ' -f $r.Estado) -ForegroundColor $colors[$r.Estado] -NoNewline
        Write-Host ("{0}{1}" -f $r.Item, $(if ($r.Detalhe) { " - $($r.Detalhe)" } else { '' }))
    }
    Write-Host ''
    Write-Host "Log: $($LumenSetup.LogFile)" -ForegroundColor DarkGray
}

# ======================================================================================================================
# Principal
# ======================================================================================================================
function Install-Lumen {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'   # a barra do Invoke-WebRequest deixa o PowerShell 5.1 muito lento
    foreach ($p in 'Tls12', 'Tls13') {
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::$p } catch { }
    }
    $logs = Join-Path $LumenSetup.Home 'logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $LumenSetup.LogFile = Join-Path $logs ('instalacao-{0:yyyyMMdd-HHmmss}.log' -f (Get-Date))
    $LumenSetup.Report.Clear()
    Write-Host ''
    Write-Host 'Instalador do Lumen' -ForegroundColor Cyan
    Write-Info "Pasta do programa: $InstallDir"
    Write-Info "Origem: $(if ($Package) { $Package } else { "github.com/$Repo ($Version)" })"
    Write-Info 'Nao precisa de administrador; se o Windows pedir, e so para uma biblioteca do sistema (o motivo aparece antes).'
    Write-LumenLog "parametros: Repo=$Repo Version=$Version InstallDir=$InstallDir Package=$Package Skip=$($Skip -join ',') Extras=$($Extras -join ',') NoShortcuts=$NoShortcuts NoLaunch=$NoLaunch Force=$Force"
    $ok = $false
    try {
        Test-Prerequisites
        $pkg = Get-LumenPackage          # antes das dependencias: um repositorio ou token errado aparece logo
        $python = Install-Dependencies
        Install-LumenFiles $pkg
        $vpy = Install-PythonEnvironment $python
        Install-Integrations $vpy
        Set-LumenConfiguration
        Test-LumenInstall $vpy
        $ok = -not @($LumenSetup.Report | Where-Object { $_.Estado -eq 'FALTA' }).Count
    } catch {
        $msg = $_.Exception.Message
        Write-Host ''
        Write-Host "A instalacao parou: $msg" -ForegroundColor Red
        Write-LumenLog "ERRO: $msg"
        if (-not $_.Exception.Data['lumen']) { Write-LumenLog ($_ | Out-String) }
        Add-Result 'Instalacao' 'FALTA' ($msg -split "`n")[0]
    }
    Show-Report
    if ($ok) {
        Write-Host 'Pronto: o Lumen esta instalado.' -ForegroundColor Green
        if (-not $NoLaunch) { Start-Process -FilePath (Join-Path $InstallDir 'Lumen.exe') -WorkingDirectory $InstallDir }
    } else {
        Write-Host 'Algo ficou faltando (veja acima). Rode o instalador de novo: ele continua de onde parou.' -ForegroundColor Yellow
    }
    return $ok
}

# Dot-source (". .\install.ps1") so carrega as funcoes (testes); qualquer outra forma (irm | iex, &, -File) instala.
if ($MyInvocation.InvocationName -ne '.') {
    $done = Install-Lumen
    if (-not $done -and $MyInvocation.MyCommand.Path) { exit 1 }   # so com -File: com "irm | iex", exit fecharia a janela
}
