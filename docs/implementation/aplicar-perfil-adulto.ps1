<#
Liga, configura ou desliga o perfil adulto dos Estudos (D92), pelo mesmo código que as Configurações usam (settings.save).

  .\aplicar-perfil-adulto.ps1 -Model "gemma4-heretic:12b"            # liga o perfil, no modo automático, com esse modelo
  .\aplicar-perfil-adulto.ps1 -Model "gemma4-heretic:12b" -Mode main  # liga, mas só vale quando eu escolher na conversa
  .\aplicar-perfil-adulto.ps1 -Revert                                 # desliga (enabled=false) e limpa o modelo; o principal não muda

- Recusa rodar com o Lúmen aberto (uma instância aberta pode regravar os ajustes): use Sair pelo menu antes.
- Faz backup do settings.json (com SHA-256) em BackupDir antes de gravar e relê o arquivo depois.
- Só mexe na seção "adult"; nenhum ajuste do modelo principal, voz, visão ou embeddings é tocado.
- Não baixa modelo. O modelo precisa estar instalado no Ollama (ou use Configurações → Perfil adulto → Baixar).
- -DataDir existe para testes: aponta o LUMEN_DATA para uma pasta temporária (o app grava em <DataDir>\Lumen\study).
#>
param(
    [string]$Model,
    [ValidateSet('auto', 'main', 'adult')][string]$Mode = 'auto',
    [switch]$Revert,
    [string]$DataDir,
    [string]$BackupDir = "D:\Lumen\restauracao\perfil-adulto-20261108",
    [switch]$SkipRunningCheck
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Python do Lúmen não encontrado em $py" }
if (-not $Revert -and -not $Model) { throw "Informe -Model, ou use -Revert." }
if (-not $DataDir -and -not $SkipRunningCheck) {
    if (Get-Process -Name Lumen -ErrorAction SilentlyContinue) {
        throw "O Lúmen está aberto. Use Sair pelo menu e rode de novo (o app aberto pode regravar os ajustes)."
    }
}
$root = if ($DataDir) { Join-Path $DataDir "Lumen" } else { Join-Path $env:LOCALAPPDATA "Lumen" }
$file = Join-Path $root "study\settings.json"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
if (Test-Path $file) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $bak = Join-Path $BackupDir "settings-antes-adulto-$stamp.json"
    Copy-Item -LiteralPath $file -Destination $bak
    $h1 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash; $h2 = (Get-FileHash -LiteralPath $bak -Algorithm SHA256).Hash
    if ($h1 -ne $h2) { throw "Backup divergente; nada foi gravado." }
    Write-Host "Backup conferido: $bak (SHA-256 $($h2.Substring(0,16))...)"
}
if ($Revert) { $patch = @{ enabled = $false; model = "" } }
else { $patch = @{ enabled = $true; mode = $Mode; model = $Model } }
$env:LUMEN_APPLY_PATCH = ($patch | ConvertTo-Json -Compress)
if ($DataDir) { $env:LUMEN_DATA = $DataDir }
Push-Location $repo
try {
    $code = "import json,os; from lumen.study import settings; p=json.loads(os.environ['LUMEN_APPLY_PATCH']); " +
            "m=settings.save({'adult': p})['adult']; print(json.dumps({k:m[k] for k in ('enabled','mode','model')}, ensure_ascii=False))"
    $out = & $py -c $code
    if ($LASTEXITCODE -ne 0) { throw "settings.save falhou." }
} finally { Pop-Location; Remove-Item Env:\LUMEN_APPLY_PATCH -ErrorAction SilentlyContinue; if ($DataDir) { Remove-Item Env:\LUMEN_DATA -ErrorAction SilentlyContinue } }
$read = (Get-Content -LiteralPath $file -Raw | ConvertFrom-Json).adult
Write-Host "Gravado (releitura do arquivo): enabled=$($read.enabled) mode='$($read.mode)' model='$($read.model)'"
foreach ($k in $patch.Keys) { if ($read.$k -ne $patch[$k]) { throw "Releitura diferente do esperado para adult.$k" } }
Write-Host "OK. Abra o Lúmen normalmente; Estudos → Configurações → Perfil adulto mostra a seleção."
