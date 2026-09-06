; 折本（おりほん）仮想プリンタ — Inno Setup スクリプト
;
;   iscc /DAppVersion=0.2.0 installer\setup\orihon.iss
;
; SrcRoot を渡せば、別の場所に展開した一式からも組み立てられる。
;   iscc /DAppVersion=0.2.0 /DSrcRoot=C:\stage installer\setup\orihon.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SrcRoot
  #define SrcRoot "..\.."
#endif

#define AppName "A7 折本プリンター"
#define AppPublisher "kiwiman0706"
#define AppURL "https://github.com/kiwiman0706-beep/a7leafletprinter"
#define DataDir "{commonappdata}\OrihonPrinter"

[Setup]
AppId={{8F3A6C21-4E7B-4A55-9C2D-6B1E0A7D5F44}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} セットアップ

; アプリ本体は ProgramData に置く。自動更新（orihon update）が
; 管理者権限なしでファイルを入れ替えられるようにするため。
DefaultDirName={#DataDir}\app
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

OutputDir={#SrcRoot}\dist
OutputBaseFilename=OrihonPrinter-Setup-{#AppVersion}
SetupIconFile={#SrcRoot}\installer\setup\orihon.ico
UninstallDisplayIcon={app}\installer\setup\orihon.ico
UninstallDisplayName={#AppName}
LicenseFile={#SrcRoot}\LICENSE

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
MinVersion=10.0
CloseApplications=no

[Languages]
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ja.CreatingPrinter=仮想プリンタを登録しています（少し時間がかかります）...
ja.RemovingPrinter=仮想プリンタを削除しています...
ja.OpenSettings=設定画面を開く
ja.NeedPython=このソフトには Python 3.10 以上が必要です。%n%nwinget で今すぐ入れますか？%n（「いいえ」を選ぶと中止します。https://www.python.org/ から入れてやり直してください）
ja.PythonFailed=Python を導入できませんでした。%n%nhttps://www.python.org/ から Python 3.12 を入れ、「Add python.exe to PATH」にチェックを入れてから、もう一度実行してください。
ja.SetupFailed=仮想プリンタの登録に失敗しました。%n%n管理者権限の PowerShell で次を実行すると、詳しい理由が表示されます:%n%n  powershell -ExecutionPolicy Bypass -File "%1\installer\Install-OrihonPrinter.ps1"
en.CreatingPrinter=Registering the virtual printer (this takes a moment)...
en.RemovingPrinter=Removing the virtual printer...
en.OpenSettings=Open settings
en.NeedPython=This program needs Python 3.10 or later.%n%nInstall it now with winget?
en.PythonFailed=Could not install Python. Please install it from https://www.python.org/ and run this setup again.
en.SetupFailed=Failed to register the virtual printer.%n%nRun this from an elevated PowerShell to see why:%n%n  powershell -ExecutionPolicy Bypass -File "%1\installer\Install-OrihonPrinter.ps1"

[Files]
Source: "{#SrcRoot}\src\*";       DestDir: "{app}\src";       Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
Source: "{#SrcRoot}\installer\*"; DestDir: "{app}\installer"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SrcRoot}\tools\*";     DestDir: "{app}\tools";     Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
Source: "{#SrcRoot}\docs\*";      DestDir: "{app}\docs";      Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SrcRoot}\README.md";        DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\CHANGELOG.md";     DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\LICENSE";          DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\pyproject.toml";   DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; ファイル展開より前に使うので、一時フォルダへ取り出せるようにしておく
Source: "{#SrcRoot}\installer\setup\Find-PythonPath.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName} の設定"; Filename: "{code:GetPythonW}"; \
  Parameters: "-m orihon gui"; WorkingDir: "{app}\src"; \
  IconFilename: "{app}\installer\setup\orihon.ico"; Comment: "面付けの設定と更新"
Name: "{group}\監視を開始"; Filename: "{code:GetPythonW}"; \
  Parameters: "-m orihon watch --quiet"; WorkingDir: "{app}\src"; \
  IconFilename: "{app}\installer\setup\orihon.ico"; Comment: "スプールの監視を手動で開始する"
Name: "{group}\出力フォルダ"; Filename: "{userdocs}\OrihonPrinter"
Name: "{group}\{#AppName} をアンインストール"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName} の設定"; Filename: "{code:GetPythonW}"; \
  Parameters: "-m orihon gui"; WorkingDir: "{app}\src"; \
  IconFilename: "{app}\installer\setup\orihon.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
; 仮想プリンタの登録は CurStepChanged から行う（終了コードを見たいため）。
; ここではインストール直後に設定画面を開く選択肢だけを出す。
Filename: "{code:GetPythonW}"; Parameters: "-m orihon gui"; WorkingDir: "{app}\src"; \
  Description: "{cm:OpenSettings}"; Flags: postinstall nowait skipifsilent; Check: VenvReady

[UninstallRun]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\Uninstall-OrihonPrinter.ps1"""; \
  StatusMsg: "{cm:RemovingPrinter}"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveOrihonPrinter"

[UninstallDelete]
Type: filesandordirs; Name: "{#DataDir}\venv"
Type: filesandordirs; Name: "{app}\src\orihon\__pycache__"
Type: dirifempty;     Name: "{app}"

[Code]
var
  PythonPath: String;

{ 下ごしらえ用スクリプトを一時フォルダへ出して、Python を探す }
function DetectPython(): String;
var
  OutFile, Content: String;
  ResultCode: Integer;
begin
  Result := '';
  ExtractTemporaryFile('Find-PythonPath.ps1');
  OutFile := ExpandConstant('{tmp}\orihon-python.txt');
  DeleteFile(OutFile);
  if Exec('powershell.exe',
          '-NoProfile -ExecutionPolicy Bypass -File "' +
          ExpandConstant('{tmp}\Find-PythonPath.ps1') + '" -Out "' + OutFile + '"',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if (ResultCode = 0) and LoadStringFromFile(OutFile, Content) then
      Result := Trim(Content);
    DeleteFile(OutFile);
  end;
end;

function InstallPythonWithWinget(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('powershell.exe',
                 '-NoProfile -ExecutionPolicy Bypass -Command "winget install -e ' +
                 '--id Python.Python.3.12 --accept-source-agreements ' +
                 '--accept-package-agreements --scope machine"',
                 '', SW_SHOW, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

{ ファイルを展開する前に Python の有無を確かめる }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  PythonPath := DetectPython();
  if PythonPath <> '' then
    Exit;

  if MsgBox(CustomMessage('NeedPython'), mbConfirmation, MB_YESNO) = IDYES then
  begin
    InstallPythonWithWinget();
    PythonPath := DetectPython();
  end;

  if PythonPath = '' then
    Result := CustomMessage('PythonFailed');
end;

{ プリンタ・ポート・仮想環境・監視タスクの作成 }
function RunPrinterInstaller(): Boolean;
var
  ResultCode: Integer;
  Arguments: String;
begin
  Arguments := '-NoProfile -ExecutionPolicy Bypass -File "' +
               ExpandConstant('{app}\installer\Install-OrihonPrinter.ps1') + '"' +
               ' -Venv "' + ExpandConstant('{#DataDir}\venv') + '"';
  if PythonPath <> '' then
    Arguments := Arguments + ' -Python "' + PythonPath + '"';

  Result := Exec('powershell.exe', Arguments, '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
            and (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := CustomMessage('CreatingPrinter');
    if not RunPrinterInstaller() then
      MsgBox(FmtMessage(CustomMessage('SetupFailed'), [ExpandConstant('{app}')]),
             mbError, MB_OK);
  end;
end;

function VenvReady(): Boolean;
begin
  Result := FileExists(ExpandConstant('{#DataDir}\venv\Scripts\pythonw.exe'));
end;

{ ショートカットは専用の仮想環境の pythonw.exe を指す }
function GetPythonW(Param: String): String;
begin
  Result := ExpandConstant('{#DataDir}\venv\Scripts\pythonw.exe');
end;
