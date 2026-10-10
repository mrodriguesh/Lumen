# Compila Lumen.exe na raiz do projeto usando o compilador C# que já vem no Windows (.NET Framework 4.8).
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$bin = Join-Path $PSScriptRoot 'bin'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $csc /nologo /target:winexe /platform:x64 /optimize+ "/out:$root\Lumen.exe" "/win32icon:$PSScriptRoot\lumen.ico" `
    "/r:$bin\Microsoft.Web.WebView2.Core.dll" "/r:$bin\Microsoft.Web.WebView2.WinForms.dll" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll "$PSScriptRoot\Lumen.cs" "$PSScriptRoot\WidgetForm.cs"
if ($LASTEXITCODE) { throw "Falha ao compilar Lumen.exe" }
Write-Output "Lumen.exe gerado em $root"
