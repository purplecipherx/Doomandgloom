param(
    [Parameter(Mandatory=$true)]
    [string]$QueueCsv,
    [string]$OutputDir = "",
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "download_captionless_audio.py"

if (-not (Test-Path $python)) {
    & (Join-Path $PSScriptRoot "setup_youtube_harvester.ps1")
}

$argsList = @($script, $QueueCsv)
if ($OutputDir) { $argsList += @("--output-dir", $OutputDir) }
if ($Limit -gt 0) { $argsList += @("--limit", "$Limit") }

& $python @argsList
exit $LASTEXITCODE
