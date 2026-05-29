[CmdletBinding()]
param(
    [string]$ProxyServer = ""
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @((Join-Path $Root "tools\x_save_login_state.py"))
if ($ProxyServer) {
    $ArgsList += @("--proxy-server", $ProxyServer)
}

& $Python @ArgsList
