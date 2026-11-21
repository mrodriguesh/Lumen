<#
Aplica ou desfaz a escolha de modelos da IA local dos Estudos, pelo mesmo código que as Configurações usam (settings.save).

  .\aplicar-modelo-estudos.ps1 -Local "huihui_ai/qwen3.5-abliterated:4B" -Max "huihui_ai/qwen3.5-abliterated:9b"
  .\aplicar-modelo-estudos.ps1 -Revert        # volta ao Automático (campos vazios), que era o estado de 07/11/2026

- Recusa rodar com o Lúmen aberto (uma instância aberta pode regravar os ajustes): use Sair pelo menu antes.
- Faz backup do settings.json (com SHA-256) em BackupDir antes de gravar e relê o arquivo depois.
- Só mexe nos campos models.local / models.fast / models.max; o resto dos ajustes não é tocado.
- -DataDir existe para testes: aponta o LUMEN_DATA para uma pasta temporária (o app grava em <DataDir>\Lumen\study).
#>
param(
    [string]$Local,
    [string]$Fast,
    [string]$Max,
    [switch]$Revert,
    [string]$DataDir,
    [string]$BackupDir = "D:\Lumen\restauracao\modelos-20261107",
    [switch]$SkipRunningCheck
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Python do Lúmen não encontrado em $py" }
if (-not $Revert -and -not ($Local -or $Fast -or $Max)) { throw "Informe -Local, -Fast e/ou -Max, ou use -Revert." }
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
    $bak = Join-Path $BackupDir "settings-antes-$stamp.json"
    Copy-Item -LiteralPath $file -Destination $bak
    $h1 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash; $h2 = (Get-FileHash -LiteralPath $bak -Algorithm SHA256).Hash
    if ($h1 -ne $h2) { throw "Backup divergente; nada foi gravado." }
    Write-Host "Backup conferido: $bak (SHA-256 $($h2.Substring(0,16))...)"
}
$patch = @{}
if ($Revert) { $patch = @{ local = ""; fast = ""; max = "" } }
else {
    if ($PSBoundParameters.ContainsKey('Local')) { $patch.local = $Local }
    if ($PSBoundParameters.ContainsKey('Fast')) { $patch.fast = $Fast }
    if ($PSBoundParameters.ContainsKey('Max')) { $patch.max = $Max }
}
$env:LUMEN_APPLY_PATCH = ($patch | ConvertTo-Json -Compress)
if ($DataDir) { $env:LUMEN_DATA = $DataDir }
Push-Location $repo
try {
    $code = "import json,os; from lumen.study import settings; p=json.loads(os.environ['LUMEN_APPLY_PATCH']); " +
            "m=settings.save({'models': p})['models']; print(json.dumps({k:m[k] for k in ('local','fast','max')}, ensure_ascii=False))"
    $out = & $py -c $code
    if ($LASTEXITCODE -ne 0) { throw "settings.save falhou." }
} finally { Pop-Location; Remove-Item Env:\LUMEN_APPLY_PATCH -ErrorAction SilentlyContinue; if ($DataDir) { Remove-Item Env:\LUMEN_DATA -ErrorAction SilentlyContinue } }
$read = (Get-Content -LiteralPath $file -Raw | ConvertFrom-Json).models
Write-Host "Gravado (releitura do arquivo): local='$($read.local)' fast='$($read.fast)' max='$($read.max)'"
foreach ($k in $patch.Keys) { if ($read.$k -ne $patch[$k]) { throw "Releitura diferente do esperado para models.$k" } }
Write-Host "OK. Abra o Lúmen normalmente; Estudos → Configurações → Modelos mostra a seleção."
