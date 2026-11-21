<#
.SYNOPSIS
    Gera o release do Lumen para o instalador: Lumen-<versao>.zip, SHA256SUMS.txt e install.ps1 (em dist\).

.DESCRIPTION
    Roda na pasta do projeto (a copia de desenvolvimento). So empacota o que o app precisa para rodar: lumen\, docs\,
    Lumen.exe, launcher\ (bin, tools e o codigo do launcher para recompilar), requirements*.txt, Iniciar Lumen.bat e
    README.md, mais um VERSION.json. Testes, bench, scratch, .venv e .git ficam de fora. Antes de gravar, confere o
    pacote com as mesmas regras do install.ps1 (arquivos obrigatorios e o SHA-256 do restic).

    Nada sai deste PC sem -Publish. Com -Publish, cria o release no GitHub com o gh (precisa de 'gh auth login').

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\publish-release.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\publish-release.ps1 -Version 2026.11.21 -Publish
#>
[CmdletBinding()]
param(
    [string]$Version = (Get-Date -Format 'yyyy.MM.dd'),
    [string]$Repo = 'mrodriguesh/Lumen',
    [string]$OutDir = '',
    [switch]$Publish
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $OutDir) { $OutDir = Join-Path $root 'dist' }
$installer = Join-Path $PSScriptRoot 'install.ps1'
$name = "Lumen-$Version.zip"

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

# 1. O instalador: ASCII puro (o "irm | iex" do PowerShell 5.1 le sem saber a codificacao) e sem erro de sintaxe
Write-Step 'Conferindo o install.ps1'
$bytes = [IO.File]::ReadAllBytes($installer)
$bad = @($bytes | Where-Object { $_ -gt 127 }).Count
if ($bad) { throw "install.ps1 tem $bad byte(s) fora do ASCII; troque os acentos (o irm | iex do PowerShell 5.1 os corromperia)." }
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($installer, [ref]$null, [ref]$errors)
if ($errors.Count) { throw "install.ps1 tem erro de sintaxe: $($errors[0].Message) (linha $($errors[0].Extent.StartLineNumber))" }

# 2. O que entra no pacote
Write-Step 'Montando o pacote'
$files = @('Lumen.exe', 'requirements.txt', 'requirements-gpu.txt', 'Iniciar Lumen.bat', 'README.md',
    'launcher\Lumen.cs', 'launcher\WidgetForm.cs', 'launcher\NoteForm.cs', 'launcher\build.ps1', 'launcher\make-icon.ps1',
    'launcher\lumen.ico', 'launcher\lumen-256.png')
$dirs = @('lumen', 'docs', 'launcher\bin', 'launcher\tools')
$exe = Get-Item (Join-Path $root 'Lumen.exe')
$newer = @(Get-ChildItem (Join-Path $root 'launcher\*.cs') | Where-Object { $_.LastWriteTime -gt $exe.LastWriteTime })
if ($newer.Count) { Write-Warning "Lumen.exe e mais antigo que $($newer.Name -join ', '): recompile com launcher\build.ps1 antes de publicar." }

$stage = Join-Path $env:TEMP ('lumen-release-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    foreach ($f in $files) {
        $dest = Join-Path $stage $f
        New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
        Copy-Item -LiteralPath (Join-Path $root $f) -Destination $dest
    }
    foreach ($d in $dirs) {
        $src = Join-Path $root $d
        Get-ChildItem -LiteralPath $src -Recurse -File -Force |
            Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -ne '.pyc' } |
            ForEach-Object {
                $dest = Join-Path $stage ($d + $_.FullName.Substring($src.Length))
                New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
                Copy-Item -LiteralPath $_.FullName -Destination $dest
            }
    }
    $ErrorActionPreference = 'Continue'   # aviso do git no stderr nao e erro (no PowerShell 5.1 viraria)
    $commit = (& git -C $root rev-parse --short HEAD 2>$null)
    $dirty = [bool](& git -C $root status --porcelain 2>$null)
    $ErrorActionPreference = 'Stop'
    # As versoes exatas do ambiente de desenvolvimento (onde o release foi testado), dependencias indiretas incluidas: o
    # instalador as usa como restricao (-c). "pip list --format=freeze" da nome==versao mesmo para o que veio de um .whl.
    $ErrorActionPreference = 'Continue'
    $frozen = @(& (Join-Path $root '.venv\Scripts\python.exe') -m pip list --format=freeze --disable-pip-version-check --exclude pip 2>$null)
    $ErrorActionPreference = 'Stop'
    if (-not $frozen.Count) { throw 'Nao consegui ler as versoes do .venv (pip list); rode o Iniciar Lumen.bat antes.' }
    # sem GPU NVIDIA o instalador fica com o onnxruntime de CPU: a mesma versao do DirectML testado aqui
    $dml = @($frozen | Where-Object { $_ -match '^onnxruntime-directml==' })
    if ($dml.Count -and -not @($frozen | Where-Object { $_ -match '^onnxruntime==' }).Count) { $frozen += $dml[0] -replace '^onnxruntime-directml==', 'onnxruntime==' }
    [IO.File]::WriteAllLines((Join-Path $stage 'constraints.txt'), [string[]](@("# Versoes testadas: .venv de desenvolvimento em $(Get-Date -Format 'yyyy-MM-dd') (pip list --format=freeze)") + $frozen))
    $info = [ordered]@{ version = $Version; commit = "$commit$(if ($dirty) { '+alteracoes-locais' })"; built = (Get-Date).ToString('o') }
    [IO.File]::WriteAllText((Join-Path $stage 'VERSION.json'), ($info | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))

    # 3. As mesmas regras do instalador, no pacote montado (dot-source dentro da funcao: nada do install.ps1 vaza para ca)
    function Test-Staging([string]$Dir) { . $installer; return @(Test-PackageContent $Dir) }
    $problems = Test-Staging $stage
    if ($problems.Count) { throw "Pacote incompleto: $($problems -join ', ')" }

    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $zip = Join-Path $OutDir $name
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    # entrada por entrada: o CreateFromDirectory do .NET Framework grava "\" nos nomes, fora do padrao do zip ("/")
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $stream = [IO.File]::Open($zip, [IO.FileMode]::CreateNew)
    $archive = New-Object IO.Compression.ZipArchive ($stream, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in Get-ChildItem -LiteralPath $stage -Recurse -File -Force) {
            $entry = $file.FullName.Substring($stage.Length + 1).Replace('\', '/')
            [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entry, [IO.Compression.CompressionLevel]::Optimal)
        }
    } finally { $archive.Dispose(); $stream.Dispose() }
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}

Copy-Item -LiteralPath $installer -Destination (Join-Path $OutDir 'install.ps1') -Force
$sums = foreach ($f in @($name, 'install.ps1')) { '{0}  {1}' -f (Get-FileHash -LiteralPath (Join-Path $OutDir $f) -Algorithm SHA256).Hash.ToLowerInvariant(), $f }
[IO.File]::WriteAllLines((Join-Path $OutDir 'SHA256SUMS.txt'), [string[]]$sums)
Write-Step "Pronto em $OutDir"
Get-ChildItem -LiteralPath $OutDir | ForEach-Object { Write-Host ("    {0,-28} {1,10:N1} MB" -f $_.Name, ($_.Length / 1MB)) }
$sums | ForEach-Object { Write-Host "    $_" }

$tag = "v$Version"
$assets = @($zip, (Join-Path $OutDir 'install.ps1'), (Join-Path $OutDir 'SHA256SUMS.txt'))
$notes = "Lumen $Version (commit $($info.commit)).`n`nInstalar ou reinstalar (PowerShell):`n`n    irm https://github.com/$Repo/releases/latest/download/install.ps1 | iex`n"
if ($Publish) {
    Write-Step "Criando o release $tag em github.com/$Repo"
    & gh release create $tag @assets --repo $Repo --title "Lumen $Version" --notes $notes
    if ($LASTEXITCODE) { throw 'O gh nao criou o release (confira gh auth status e se a tag ja existe).' }
} else {
    Write-Host ''
    Write-Host 'Nada foi enviado. Para publicar:' -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File installer\publish-release.ps1 -Version $Version -Publish"
}
