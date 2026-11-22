<#
.SYNOPSIS
    Gera o instalador de um botao do Lumen: dist\Lumen-Setup-<versao>.exe (Inno Setup 6).

.DESCRIPTION
    Usa o pacote dist\Lumen-<versao>.zip e o SHA256SUMS.txt do installer\publish-release.ps1 (gera os dois se faltarem)
    e compila installer\setup\Lumen.iss com o ISCC do Inno Setup 6 (winget install JRSoftware.InnoSetup).
    Com -Publish, anexa o .exe ao release v<versao> no GitHub (gh). Nada sai deste PC sem -Publish.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\setup\build-setup.ps1 -Version 2026.11.21
#>
[CmdletBinding()]
param(
    [string]$Version = (Get-Date -Format 'yyyy.MM.dd'),
    [string]$Repo = 'mrodriguesh/Lumen',
    [switch]$Publish
)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dist = Join-Path $root 'dist'
$zip = Join-Path $dist "Lumen-$Version.zip"

if (-not (Test-Path -LiteralPath $zip) -or -not (Test-Path -LiteralPath (Join-Path $dist 'SHA256SUMS.txt'))) {
    & (Join-Path $root 'installer\publish-release.ps1') -Version $Version
}
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 nao encontrado. Instale com: winget install JRSoftware.InnoSetup' }

& $iscc /Q "/DAppVersion=$Version" (Join-Path $PSScriptRoot 'Lumen.iss')
if ($LASTEXITCODE) { throw "O ISCC nao compilou o Lumen.iss (codigo $LASTEXITCODE)." }
$exe = Join-Path $dist "Lumen-Setup-$Version.exe"
'{0}  ({1:N1} MB)  SHA-256 {2}' -f $exe, ((Get-Item $exe).Length / 1MB), (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()

if ($Publish) {
    & gh release upload "v$Version" $exe --repo $Repo --clobber
    if ($LASTEXITCODE) { throw "O gh nao anexou o instalador ao release v$Version." }
}
