<#
.SYNOPSIS
    折本（おりほん）仮想プリンタをインストールします。

.DESCRIPTION
    Windows 標準の「Microsoft Print to PDF」ドライバーを、ファイルを指す
    ローカルポートに紐づけた仮想プリンタを作ります。アプリからこのプリンタに
    印刷すると、保存ダイアログを出さずに PDF がスプールフォルダへ書き出され、
    常駐している監視プロセス（orihon watch）がそれを拾って折本の面付けに
    並べ替えます。

    管理者権限が必要です（プリンタとポートの追加、タスクの登録のため）。

.PARAMETER PrinterName
    作成する仮想プリンタの名前。

.PARAMETER DataDir
    設定・スプール・ログを置くフォルダ。

.PARAMETER DefaultPaper
    仮想プリンタの既定用紙。折本 1 ページ分の大きさを指定します（既定: A7）。
    アプリ側が A7 を扱えない場合は A4 などにしてください。

.PARAMETER Python
    使用する pythonw.exe / python.exe のパス。省略時は自動検出します。

.PARAMETER Venv
    専用の仮想環境をここに作り、そちらを使います（setup.exe 版はこれを使います）。
    ユーザーの Python 環境を汚さず、あとから壊れることもありません。

.PARAMETER NoTask
    ログオン時に監視プロセスを自動起動するタスクを作りません。

.PARAMETER NoPipInstall
    PyMuPDF / pywin32 の自動インストールを行いません。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Install-OrihonPrinter.ps1

.EXAMPLE
    .\Install-OrihonPrinter.ps1 -PrinterName "折本プリンター" -DefaultPaper A4
#>
[CmdletBinding()]
param(
    [string]$PrinterName = "A7 折本プリンター",
    [string]$DataDir = (Join-Path $env:ProgramData "OrihonPrinter"),
    [ValidateSet("A4", "A5", "A6", "A7", "B5", "B6", "Letter")]
    [string]$DefaultPaper = "A7",
    [string]$Python = "",
    [string]$Venv = "",
    [switch]$NoTask,
    [switch]$NoPipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SrcDir = Join-Path $RepoRoot "src"
$SpoolDir = Join-Path $DataDir "spool"
$PortFile = Join-Path $SpoolDir "job.pdf"
$TaskName = "OrihonPrinter Watcher"

function Write-Step   { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok     { param([string]$m) Write-Host "    OK  $m" -ForegroundColor Green }
function Write-Warn2  { param([string]$m) Write-Host "    !!  $m" -ForegroundColor Yellow }

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "管理者権限で実行してください（PowerShell を「管理者として実行」）。"
    }
}

function Find-Python {
    param([string]$Preferred)
    if ($Preferred) {
        if (Test-Path $Preferred) { return (Resolve-Path $Preferred).Path }
        throw "指定された Python が見つかりません: $Preferred"
    }
    foreach ($name in @("pythonw.exe", "python.exe")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($launcher) {
        $found = & $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { return $found.Trim() }
    }
    # PATH に入っていない場合に備えて、よくある導入先も見る
    # （winget で入れた直後は、まだ PATH が反映されていない）
    $patterns = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "${env:ProgramFiles(x86)}\Python3*\python.exe",
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.*.exe"
    )
    foreach ($pattern in $patterns) {
        $candidate = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    throw "Python が見つかりません。https://www.python.org/ から入れるか -Python でパスを指定してください。"
}

function Get-ConsolePython {
    param([string]$PythonPath)
    $console = $PythonPath -replace "pythonw\.exe$", "python.exe"
    if (Test-Path $console) { return $console }
    return $PythonPath
}

function Get-PdfDriverName {
    $names = @("Microsoft Print To PDF", "Microsoft Print to PDF")
    foreach ($n in $names) {
        if (Get-PrinterDriver -Name $n -ErrorAction SilentlyContinue) { return $n }
    }
    Write-Warn2 "「Microsoft Print to PDF」ドライバーが未導入です。有効化を試みます..."
    try {
        Enable-WindowsOptionalFeature -Online -FeatureName "Printing-PrintToPDFServices-Features" `
            -NoRestart -ErrorAction Stop | Out-Null
    } catch {
        throw "「Microsoft Print to PDF」を有効化できませんでした。Windows の機能から手動で有効にしてください。: $($_.Exception.Message)"
    }
    foreach ($n in $names) {
        if (Get-PrinterDriver -Name $n -ErrorAction SilentlyContinue) { return $n }
    }
    throw "「Microsoft Print to PDF」ドライバーが見つかりません。"
}

function Grant-UsersModify {
    param([string]$Path)
    # スプールフォルダは印刷したユーザーの権限で書かれるので、Users に書き込みを許可する
    $acl = Get-Acl -Path $Path
    $users = New-Object Security.Principal.SecurityIdentifier("S-1-5-32-545")  # BUILTIN\Users
    $rule = New-Object Security.AccessControl.FileSystemAccessRule(
        $users, "Modify", "ContainerInherit,ObjectInherit", "None", "Allow")
    $acl.AddAccessRule($rule)
    Set-Acl -Path $Path -AclObject $acl
}

# ----------------------------------------------------------------------
Write-Host ""
Write-Host "折本（おりほん）仮想プリンタ セットアップ" -ForegroundColor White
Write-Host "----------------------------------------"

Assert-Admin

Write-Step "Python を探しています"
$PythonW = Find-Python -Preferred $Python
$PythonExe = Get-ConsolePython -PythonPath $PythonW
Write-Ok $PythonW

if ($Venv) {
    Write-Step "専用の仮想環境を用意しています: $Venv"
    $venvPython = Join-Path $Venv "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        & $PythonExe -m venv $Venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
            throw "仮想環境を作れませんでした: $Venv"
        }
        Write-Ok "作成しました"
    } else {
        Write-Ok "既にあります"
    }
    $PythonExe = $venvPython
    $venvPythonW = Join-Path $Venv "Scripts\pythonw.exe"
    $PythonW = if (Test-Path $venvPythonW) { $venvPythonW } else { $venvPython }
}

if (-not $NoPipInstall) {
    Write-Step "必要な Python ライブラリを入れています (pymupdf, pywin32)"
    & $PythonExe -m pip install --disable-pip-version-check --quiet --upgrade pip
    & $PythonExe -m pip install --disable-pip-version-check --quiet --upgrade pymupdf pywin32
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "pip に失敗しました。手動で `"$PythonExe -m pip install pymupdf pywin32`" を実行してください。"
    } else {
        Write-Ok "pymupdf / pywin32"
    }
}

Write-Step "フォルダを準備しています"
foreach ($dir in @($DataDir, $SpoolDir, (Join-Path $DataDir "logs"), (Join-Path $DataDir "processed"))) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}
try {
    Grant-UsersModify -Path $DataDir
    Write-Ok "$DataDir (Users に書き込み許可)"
} catch {
    Write-Warn2 "ACL を設定できませんでした: $($_.Exception.Message)"
}

Write-Step "PDF ドライバーを確認しています"
$DriverName = Get-PdfDriverName
Write-Ok $DriverName

Write-Step "ローカルポートを作成しています: $PortFile"
if (Get-PrinterPort -Name $PortFile -ErrorAction SilentlyContinue) {
    Write-Ok "既にあります"
} else {
    Add-PrinterPort -Name $PortFile
    Write-Ok "作成しました"
}

Write-Step "仮想プリンタを作成しています: $PrinterName"
$existing = Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.PortName -ne $PortFile) {
        Set-Printer -Name $PrinterName -PortName $PortFile
        Write-Ok "既存のプリンタのポートを付け替えました"
    } else {
        Write-Ok "既にあります"
    }
} else {
    Add-Printer -Name $PrinterName -DriverName $DriverName -PortName $PortFile
    Write-Ok "作成しました"
}

Write-Step "既定の用紙を $DefaultPaper にしています"
try {
    Set-PrintConfiguration -PrinterName $PrinterName -PaperSize $DefaultPaper -ErrorAction Stop
    Write-Ok "$DefaultPaper"
} catch {
    Write-Warn2 "既定用紙を $DefaultPaper にできませんでした（アプリ側で用紙を選んでください）: $($_.Exception.Message)"
}

Write-Step "起動用のショートカットを作成しています"
$startWatcher = Join-Path $DataDir "監視を開始.cmd"
@"
@echo off
rem 折本プリンタの監視プロセスを開始します
cd /d "$SrcDir"
"$PythonExe" -m orihon watch
pause
"@ | Set-Content -Path $startWatcher -Encoding OEM

$openSettings = Join-Path $DataDir "設定を開く.cmd"
@"
@echo off
rem 折本プリンタの設定画面を開きます
cd /d "$SrcDir"
start "" "$PythonW" -m orihon gui
"@ | Set-Content -Path $openSettings -Encoding OEM
Write-Ok $startWatcher
Write-Ok $openSettings

if (-not $NoTask) {
    Write-Step "ログオン時に監視を自動起動するタスクを登録しています"
    try {
        $action = New-ScheduledTaskAction -Execute $PythonW `
            -Argument "-m orihon watch --quiet" -WorkingDirectory $SrcDir
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Settings $settings -Description "折本仮想プリンタのスプール監視" -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Ok "$TaskName （今すぐ開始しました）"
    } catch {
        Write-Warn2 "タスクを登録できませんでした: $($_.Exception.Message)"
        Write-Warn2 "「$startWatcher」を手で実行しても動きます。"
    }
}

Write-Step "動作確認"
Push-Location $SrcDir
try {
    & $PythonExe -m orihon doctor
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "セットアップが終わりました。" -ForegroundColor Green
Write-Host ""
Write-Host "  1. 好きなアプリの印刷ダイアログで「$PrinterName」を選んで印刷します。"
Write-Host "  2. 面付けされた PDF が開き、そのまま印刷ダイアログが出ます。"
Write-Host "  3. 設定を変えるには「$openSettings」を実行してください。"
Write-Host ""
if (-not (Get-Command "SumatraPDF" -ErrorAction SilentlyContinue)) {
    Write-Host "  ヒント: winget install SumatraPDF.SumatraPDF を入れておくと、" -ForegroundColor Yellow
    Write-Host "          Windows 本来の印刷ダイアログ（両面・トレイ指定など）が出せます。" -ForegroundColor Yellow
    Write-Host ""
}
Write-Host "  スプール : $SpoolDir"
Write-Host "  ログ     : $(Join-Path $DataDir 'logs\orihon.log')"
Write-Host ""
