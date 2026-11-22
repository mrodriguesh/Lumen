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
; o programa e o ambiente Python (medido: até ~2,6 GB com GPU); o mesmo mínimo do install.ps1
ExtraDiskSpaceRequired=5368709120
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
  PrevDir: String;
  DrivePage: TInputOptionWizardPage;
  DriveLetters: array of String;

function GetLogicalDrives(): Cardinal; external 'GetLogicalDrives@kernel32.dll stdcall';
function GetDriveTypeW(RootPath: String): Cardinal; external 'GetDriveTypeW@kernel32.dll stdcall';

const
  DRIVE_FIXED = 3;
  MinFreeBytes = 5368709120;  { 5 GB: o mesmo mínimo do install.ps1 }

function SystemLetter: String;
begin
  Result := UpperCase(Copy(ExpandConstant('{sd}'), 1, 1));
end;

{ Na unidade do Windows, a pasta de sempre; nas outras, <letra>:\Programas\Lumen (igual ao install.ps1). Uma instalação
  anterior na mesma unidade é mantida onde está. }
function DirForDrive(Letter: String): String;
begin
  if (PrevDir <> '') and (CompareText(Copy(PrevDir, 1, 1), Letter) = 0) then
    Result := PrevDir
  else if CompareText(Letter, SystemLetter) = 0 then
    Result := ExpandConstant('{localappdata}\Programs\Lumen')
  else
    Result := Letter + ':\Programas\Lumen';
end;

function GBText(Bytes: Int64): String;
begin
  Result := Format('%.1f GB', [Bytes / 1073741824.0]);
end;

procedure InitializeWizard;
var
  Mask: Cardinal;
  I, Idx, Pick: Integer;
  L, Text, Wanted: String;
  Free, Total: Int64;
  Enough: Boolean;
begin
  PrevDir := '';
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{F621B13F-5DCD-43E5-9BF0-B3641964909D}_is1',
      'Inno Setup: App Path', PrevDir) then
    if not DirExists(PrevDir) then
      PrevDir := '';

  DrivePage := CreateInputOptionPage(wpWelcome, 'Unidade de instalação', 'Em qual unidade instalar o Lúmen?',
    'O programa e o ambiente Python ocupam até cerca de 2,6 GB. Na unidade do Windows ficam em %LOCALAPPDATA%\Programs\Lumen; nas outras, em <letra>:\Programas\Lumen (a pasta exata aparece na tela seguinte). Os modelos de IA e os dados do Lúmen ficam no perfil do Windows, a menos que o Ollama ou o Hugging Face já estejam configurados para outro lugar.',
    True, False);

  Pick := -1;
  Mask := GetLogicalDrives;
  for I := 0 to 25 do
    if (Mask and (Cardinal(1) shl I)) <> 0 then
    begin
      L := Chr(Ord('A') + I);
      if GetDriveTypeW(L + ':\') = DRIVE_FIXED then
        if GetSpaceOnDisk64(L + ':\', Free, Total) then
        begin
          Enough := Free >= MinFreeBytes;
          Text := L + ':  ' + GBText(Free) + ' livres de ' + GBText(Total);
          if CompareText(L, SystemLetter) = 0 then
            Text := Text + '  (Windows)';
          if (PrevDir <> '') and (CompareText(Copy(PrevDir, 1, 1), L) = 0) then
            Text := Text + '  (instalação anterior)';
          if not Enough then
            Text := Text + '  (sem espaço)';
          Idx := DrivePage.Add(Text);
          SetArrayLength(DriveLetters, Idx + 1);
          DriveLetters[Idx] := L;
          DrivePage.CheckListBox.ItemEnabled[Idx] := Enough;
          { sugerida: a da instalação anterior; senão, a do Windows; senão, a primeira com espaço }
          if Enough then
          begin
            if (PrevDir <> '') and (CompareText(Copy(PrevDir, 1, 1), L) = 0) then
              Pick := Idx
            else if (Pick < 0) or ((CompareText(L, SystemLetter) = 0) and (PrevDir = '')) then
              Pick := Idx;
          end;
        end;
    end;
  if Pick >= 0 then
    DrivePage.Values[Pick] := True;

  { /DRIVE=D escolhe sem mostrar a página (também vale com /SILENT); /DIR=pasta tem a palavra final }
  Wanted := UpperCase(Copy(ExpandConstant('{param:DRIVE|}'), 1, 1));
  if Wanted <> '' then
    for I := 0 to GetArrayLength(DriveLetters) - 1 do
      if DriveLetters[I] = Wanted then
        WizardForm.DirEdit.Text := DirForDrive(Wanted);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (DrivePage <> nil) and (PageID = DrivePage.ID) and
    ((ExpandConstant('{param:DIR|}') <> '') or (ExpandConstant('{param:DRIVE|}') <> ''));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
begin
  Result := True;
  if (DrivePage <> nil) and (CurPageID = DrivePage.ID) then
  begin
    for I := 0 to GetArrayLength(DriveLetters) - 1 do
      if DrivePage.Values[I] then
        WizardForm.DirEdit.Text := DirForDrive(DriveLetters[I]);
    if GetArrayLength(DriveLetters) = 0 then
    begin
      MsgBox('Nenhuma unidade tem espaço livre suficiente (5 GB) para o Lúmen.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  { o memo não quebra linhas: um item por linha }
  Result := 'Unidade e pasta de instalação:' + NewLine + Space + WizardDirValue + NewLine + NewLine +
    'Baixados agora (o que ainda não estiver neste PC):' + NewLine +
    Space + 'Python 3.14, Visual C++ e WebView2' + NewLine +
    Space + 'Ollama e os modelos de IA' + NewLine +
    Space + 'o ambiente Python do Lúmen' + NewLine +
    Space + 'Obsidian e Voice Studio';
end;

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
