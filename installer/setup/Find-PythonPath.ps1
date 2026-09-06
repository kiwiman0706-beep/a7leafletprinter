<#
.SYNOPSIS
    Python の実行ファイルを探して、そのパスを表示します（見つからなければ終了コード 1）。

.DESCRIPTION
    setup.exe（Inno Setup）から呼ばれる下ごしらえ用のスクリプトです。
    PATH のほか、winget や python.org のインストーラが使う既定の場所も見ます。
    winget で入れた直後は PATH がまだ反映されていないため、後者が要ります。

.PARAMETER Out
    見つかったパスを書き出すファイル。省略時は標準出力へ。
#>
[CmdletBinding()]
param([string]$Out = "")

$ErrorActionPreference = "SilentlyContinue"

function Resolve-PythonPath {
    $command = Get-Command py.exe, python.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source } | Select-Object -First 1
    if ($command) { return $command.Source }

    $patterns = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "${env:ProgramFiles(x86)}\Python3*\python.exe"
    )
    foreach ($pattern in $patterns) {
        $found = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return ""
}

$python = Resolve-PythonPath
if (-not $python) { exit 1 }

if ($Out) {
    Set-Content -LiteralPath $Out -Value $python -Encoding ASCII
} else {
    Write-Output $python
}
exit 0
