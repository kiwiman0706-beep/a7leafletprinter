<#
.SYNOPSIS
    折本（おりほん）仮想プリンタを、GitHub のリリースから取ってきて入れます。

.DESCRIPTION
    リポジトリを clone しなくても、これ 1 本でインストールできます。

        irm https://github.com/kiwiman0706-beep/a7leafletprinter/releases/latest/download/bootstrap.ps1 | iex

    最新リリースの ZIP を取得し、%ProgramData%\OrihonPrinter\app に展開してから
    同梱の Install-OrihonPrinter.ps1 を実行します。
    2 回目以降は、同じコマンドで上書き更新になります
    （設定・ログ・スプールはそのまま残ります）。

.PARAMETER Version
    入れたいバージョン（例 v0.1.0）。省略時は最新リリース。

.PARAMETER Repo
    取得元の GitHub リポジトリ（owner/repo）。

.PARAMETER InstallDir
    展開先。既定は %ProgramData%\OrihonPrinter\app

.PARAMETER DownloadOnly
    ダウンロードと展開だけ行い、インストーラは実行しません。

.EXAMPLE
    .\bootstrap.ps1

.EXAMPLE
    .\bootstrap.ps1 -Version v0.1.0
#>
[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$Repo = "kiwiman0706-beep/a7leafletprinter",
    [string]$InstallDir = (Join-Path $env:ProgramData "OrihonPrinter\app"),
    [switch]$DownloadOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "    OK  $m" -ForegroundColor Green }

if ($Repo -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "-Repo は owner/repo の形で指定してください: $Repo"
}

Write-Host ""
Write-Host "折本（おりほん）仮想プリンタ ブートストラップ" -ForegroundColor White
Write-Host "--------------------------------------------"

Write-Step "リリース情報を取得しています ($Repo)"
$api = if ($Version) {
    "https://api.github.com/repos/$Repo/releases/tags/$Version"
} else {
    "https://api.github.com/repos/$Repo/releases/latest"
}
try {
    $release = Invoke-RestMethod -Uri $api -Headers @{
        "User-Agent" = "orihon-bootstrap"
        "Accept"     = "application/vnd.github+json"
    }
} catch {
    throw "リリース情報を取得できませんでした: $($_.Exception.Message)`n" +
          "リポジトリ名とネットワークを確認してください: https://github.com/$Repo/releases"
}

$tag = $release.tag_name
Write-Ok "$tag $(if ($release.name) { "($($release.name))" })"

# 配布 ZIP があればそれを、無ければ GitHub 自動生成の zipball を使う
$asset = $release.assets | Where-Object { $_.name -like "orihon-printer*.zip" } | Select-Object -First 1
$zipUrl = if ($asset) { $asset.browser_download_url } else { $release.zipball_url }
if ($zipUrl -notlike "https://*") { throw "配布ファイルの URL が https ではありません: $zipUrl" }

$work = Join-Path ([IO.Path]::GetTempPath()) ("orihon-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work -Force | Out-Null
try {
    $zipPath = Join-Path $work "release.zip"
    Write-Step "ダウンロードしています"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -Headers @{
        "User-Agent" = "orihon-bootstrap"
    }
    Write-Ok ("{0:N1} MB" -f ((Get-Item $zipPath).Length / 1MB))

    Write-Step "展開しています"
    $extract = Join-Path $work "extract"
    Expand-Archive -Path $zipPath -DestinationPath $extract -Force
    $roots = @(Get-ChildItem -Path $extract -Directory)
    if ($roots.Count -ne 1) { throw "配布ファイルの構造が想定と違います（最上位: $($roots.Count) 個）" }
    $source = $roots[0].FullName
    if (-not (Test-Path (Join-Path $source "src\orihon\__init__.py"))) {
        throw "配布ファイルに src\orihon が見つかりません"
    }
    Write-Ok $source

    Write-Step "$InstallDir へ配置しています"
    try {
        if (-not (Test-Path $InstallDir)) {
            New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        }
        foreach ($name in @("src", "installer", "tools", "docs")) {
            $from = Join-Path $source $name
            if (-not (Test-Path $from)) { continue }
            $to = Join-Path $InstallDir $name
            if (-not (Test-Path $to)) { New-Item -ItemType Directory -Path $to -Force | Out-Null }
            # フォルダごとではなく「中身」をコピーする
            # （フォルダごとだと 2 回目に src\src と入れ子になることがある）
            Copy-Item -Path (Join-Path $from "*") -Destination $to -Recurse -Force
        }
        foreach ($name in @("README.md", "CHANGELOG.md", "LICENSE", "pyproject.toml", "requirements.txt")) {
            $from = Join-Path $source $name
            if (Test-Path $from) { Copy-Item -Path $from -Destination $InstallDir -Force }
        }
    } catch {
        throw "$InstallDir に書き込めませんでした: $($_.Exception.Message)`n" +
              "PowerShell を「管理者として実行」してからもう一度お試しください。" +
              "（あるいは -InstallDir で書き込めるフォルダを指定してください）"
    }
    Write-Ok "配置しました"

    if ($DownloadOnly) {
        Write-Host ""
        Write-Host "展開だけ行いました: $InstallDir" -ForegroundColor Green
        Write-Host "インストールする場合は次を管理者権限で実行してください:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File `"$InstallDir\installer\Install-OrihonPrinter.ps1`""
        return
    }

    $installer = Join-Path $InstallDir "installer\Install-OrihonPrinter.ps1"
    if (-not (Test-Path $installer)) { throw "インストーラが見つかりません: $installer" }

    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)

    Write-Step "インストーラを実行します"
    if ($isAdmin) {
        & $installer
    } else {
        Write-Host "    管理者権限が必要なので、昇格して実行します（UAC が出ます）" -ForegroundColor Yellow
        Start-Process powershell -Verb RunAs -Wait -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$installer`""
        )
    }
} finally {
    Remove-Item -Path $work -Recurse -Force -ErrorAction SilentlyContinue
}
