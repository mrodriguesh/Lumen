; Instalador do Lúmen para Windows (Inno Setup 6): uma tela, um botão "Instalar".
; O pacote do app (dist\Lumen-<versão>.zip, gerado por installer\publish-release.ps1) vai dentro do setup; o resto —
; Python, Visual C++, WebView2, Ollama, ambiente Python, modelos e integrações — é baixado na instalação pelo mesmo
; installer\install.ps1 do comando de uma linha (-Package: sem a API do GitHub). Gere com installer\setup\build-setup.ps1.

#ifndef AppVersion
  #error Informe a versão: use installer\setup\build-setup.ps1 (ou ISCC /DAppVersion=aaaa.mm.dd)
#endif
#define Repo "mrodriguesh/Lumen"
#define Dist "..\..\dist"

[Setup]
AppId={{F621B13F-5DCD-43E5-9BF0-B3641964909D}
AppName=Lúmen
AppVersion={#AppVersion}
AppVerName=Lúmen {#AppVersion}
AppPublisher=mrodriguesh
AppPublisherURL=https://github.com/{#Repo}
AppSupportURL=https://github.com/{#Repo}/issues
; a mesma pasta padrão do install.ps1; só para o usuário atual, sem administrador
DefaultDirName={localappdata}\Programs\Lumen
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
; o install.ps1 troca tudo o que está na pasta do programa: o desinstalador fica fora dela
UninstallFilesDir={localappdata}\Lumen-Instalador\desinstalar
UninstallDisplayIcon={app}\Lumen.exe
UninstallDisplayName=Lúmen
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
WizardStyle=modern
SetupIconFile=..\..\launcher\lumen.ico
OutputDir={#Dist}
OutputBaseFilename=Lumen-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ShowLanguageDialog=no
CloseApplications=no

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
ptbr.ReadyLabel1=O Lúmen vai ser instalado com tudo de que precisa.
ptbr.ReadyLabel2b=Clique em Instalar. Uma janela do PowerShell mostra o progresso: Python, Ollama, ambiente Python, modelos de IA e integrações são baixados agora (dezenas de GB na primeira vez; veja o README).

[Files]
Source: "..\install.ps1"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "{#Dist}\Lumen-{#AppVersion}.zip"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "{#Dist}\SHA256SUMS.txt"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{userprograms}\Lumen"; Filename: "{app}\Lumen.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Lumen"; Filename: "{app}\Lumen.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Lumen.exe"; WorkingDir: "{app}"; Description: "Abrir o Lúmen"; Flags: postinstall nowait skipifsilent; Check: Installed

[UninstallDelete]
; o programa e o ambiente Python; dados, configuração, tokens (%LOCALAPPDATA%\Lumen), Python, Ollama e modelos ficam
Type: filesandordirs; Name: "{app}"

[Code]
var
  Ok: Boolean;

function Installed: Boolean;
begin
  Result := Ok;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Params: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  WizardForm.StatusLabel.Caption := 'Instalando o Lúmen, as dependências e os modelos (o progresso aparece na janela do PowerShell)...';
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\install.ps1') + '"' +
    ' -Package "' + ExpandConstant('{tmp}\Lumen-{#AppVersion}.zip') + '"' +
    ' -InstallDir "' + ExpandConstant('{app}') + '" -NoShortcuts -NoLaunch';
  Ok := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', SW_SHOW, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Ok then
    MsgBox('A instalação não terminou (código ' + IntToStr(Code) + '). O resumo ficou na janela do PowerShell e o log em ' +
      ExpandConstant('{localappdata}\Lumen-Instalador\logs') + '. Rode este instalador de novo: ele continua de onde parou.',
      mbError, MB_OK);
end;
