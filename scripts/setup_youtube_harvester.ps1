$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $repoRoot ".venv-youtube"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating .venv-youtube..."
    py -3 -m venv $venv
}

& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $repoRoot "requirements-youtube.txt")

Write-Host ""
Write-Host "Ready."
Write-Host 'Inventory only:'
Write-Host '  .\scripts\run_youtube_channel_harvest.ps1 -Url "https://www.youtube.com/@CHANNEL" -InventoryOnly'
Write-Host 'Inventory + existing captions:'
Write-Host '  .\scripts\run_youtube_channel_harvest.ps1 -Url "https://www.youtube.com/@CHANNEL"'
