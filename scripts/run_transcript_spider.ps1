param(
    [string]$ResearchRoot = "research",
    [string]$OutputDir = "data\spider",
    [string]$BatchId = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "transcript_spider.py"

$argsList = @(
    $script,
    "--research-root", (Join-Path $repoRoot $ResearchRoot),
    "--output-dir", (Join-Path $repoRoot $OutputDir)
)
if ($BatchId) { $argsList += @("--batch-id", $BatchId) }

& $python @argsList
exit $LASTEXITCODE
