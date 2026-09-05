<#
.SYNOPSIS
    折本（おりほん）仮想プリンタをアンインストールします。

.PARAMETER PrinterName
    削除する仮想プリンタの名前。

.PARAMETER DataDir
    設定・スプール・ログのフォルダ。

.PARAMETER RemoveData
    設定・ログ・スプールのフォルダごと削除します（既定では残します）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Uninstall-OrihonPrinter.ps1
#>
[CmdletBinding()]
param(
    [string]$PrinterName = "A7 折本プリンター",
    [string]$DataDir = (Join-Path $env:ProgramData "OrihonPrinter"),
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SpoolDir = Join-Path $DataDir "spool"
$PortFile = Join-Path $SpoolDir "job.pdf"
$TaskName = "OrihonPrinter Watcher"

function Write-Step { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "    OK  $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "    !!  $m" -ForegroundColor Yellow }

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "管理者権限で実行してください。"
}

Write-Step "監視タスクを削除しています"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Ok $TaskName
} else {
    Write-Ok "タスクはありません"
}

Write-Step "仮想プリンタを削除しています"
if (Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue) {
    Remove-Printer -Name $PrinterName
    Write-Ok $PrinterName
} else {
    Write-Ok "プリンタはありません"
}

Write-Step "ローカルポートを削除しています"
if (Get-PrinterPort -Name $PortFile -ErrorAction SilentlyContinue) {
    try {
        Remove-PrinterPort -Name $PortFile
        Write-Ok $PortFile
    } catch {
        Write-Warn2 "ポートを削除できませんでした（使用中かもしれません）: $($_.Exception.Message)"
    }
} else {
    Write-Ok "ポートはありません"
}

if ($RemoveData) {
    Write-Step "データフォルダを削除しています"
    if (Test-Path $DataDir) {
        Remove-Item -Path $DataDir -Recurse -Force
        Write-Ok $DataDir
    }
} else {
    Write-Host ""
    Write-Host "設定とログは残してあります: $DataDir" -ForegroundColor Yellow
    Write-Host "完全に消す場合は -RemoveData を付けて実行してください。"
}

Write-Host ""
Write-Host "アンインストールが終わりました。" -ForegroundColor Green
