param(
    [int]$ChannelWorkers = 2,
    [int]$Workers = 8,
    [int]$AudioWorkers = 4,
    [int]$LimitChannels = 0,
    [int]$LimitVideos = 0,
    [int]$CaptionlessLimit = 0,
    [double]$Sleep = 0.75,
    [ValidateSet("cuda","cpu")]
    [string]$Device = "cuda",
    [string]$WhisperModel = "medium.en",
    [string]$ComputeType = "int8",
    [int]$BatchSize = 4,
    [switch]$SkipSpider
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "youtube_pipeline_orchestrator.py"

$argsList = @(
    $script,
    "--channel-workers", "$ChannelWorkers",
    "--workers", "$Workers",
    "--audio-workers", "$AudioWorkers",
    "--sleep", "$Sleep",
    "--device", $Device,
    "--whisper-model", $WhisperModel,
    "--compute-type", $ComputeType,
    "--batch-size", "$BatchSize"
)
if ($LimitChannels -gt 0) { $argsList += @("--limit-channels", "$LimitChannels") }
if ($LimitVideos -gt 0) { $argsList += @("--limit-videos", "$LimitVideos") }
if ($CaptionlessLimit -gt 0) { $argsList += @("--captionless-limit", "$CaptionlessLimit") }
if ($SkipSpider) { $argsList += "--skip-spider" }

& $python @argsList
exit $LASTEXITCODE
