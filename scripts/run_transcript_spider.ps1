param(
    [Parameter(Mandatory=$true)]
    [string]$ResearchRoot,
    [string]$OutputDir = "data\spider",
    [Parameter(Mandatory=$true)]
    [string]$BatchId
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "transcript_spider.py"

$researchPath = if ([System.IO.Path]::IsPathRooted($ResearchRoot)) { $ResearchRoot } else { Join-Path $repoRoot $ResearchRoot }
$outputPath = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $repoRoot $OutputDir }

$argsList = @(
    $script,
    "--research-root", $researchPath,
    "--output-dir", $outputPath
)
if ($BatchId) { $argsList += @("--batch-id", $BatchId) }

& $python @argsList
exit $LASTEXITCODE
