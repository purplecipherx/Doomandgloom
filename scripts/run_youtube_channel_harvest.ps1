param(
    [Parameter(Mandatory=$true)]
    [string]$Url,
    [string]$Name = "",
    [string]$Output = "research/youtube",
    [int]$Workers = 2,
    [double]$Sleep = 0.75,
    [int]$Limit = 0,
    [switch]$InventoryOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "youtube_channel_harvest.py"

if (-not (Test-Path $python)) {
    & (Join-Path $PSScriptRoot "setup_youtube_harvester.ps1")
}

$argsList = @(
    $script,
    $Url,
    "--output", (Join-Path $repoRoot $Output),
    "--workers", "$Workers",
    "--sleep", "$Sleep"
)

if ($Name) { $argsList += @("--name", $Name) }
if ($Limit -gt 0) { $argsList += @("--limit", "$Limit") }
if ($InventoryOnly) { $argsList += "--inventory-only" }

& $python @argsList
exit $LASTEXITCODE
