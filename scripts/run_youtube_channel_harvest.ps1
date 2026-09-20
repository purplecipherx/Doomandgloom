param(
    [Parameter(Mandatory=$true)]
    [string]$Url,
    [string]$Name = "",
    [string]$Output = "research/youtube",
    [int]$Workers = 2,
    [double]$Sleep = 0.75,
    [int]$Limit = 0,
    [switch]$InventoryOnly,
    [switch]$ProcessCaptionless,
    [string]$MojiRoot = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$harvestPython = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
$harvestScript = Join-Path $PSScriptRoot "youtube_channel_harvest.py"

if (-not (Test-Path $harvestPython)) {
    & (Join-Path $PSScriptRoot "setup_youtube_harvester.ps1")
}

if (-not $Name) {
    if ($Url -match '/@([^/?]+)') { $Name = $Matches[1] } else { $Name = "youtube_source" }
}

$channelOut = Join-Path (Join-Path $repoRoot $Output) $Name

$argsList = @(
    $harvestScript,
    $Url,
    "--output", (Join-Path $repoRoot $Output),
    "--name", $Name,
    "--workers", "$Workers",
    "--sleep", "$Sleep"
)
if ($Limit -gt 0) { $argsList += @("--limit", "$Limit") }
if ($InventoryOnly) { $argsList += "--inventory-only" }

Write-Host ""
Write-Host "=== DOOMANDGLOOM YOUTUBE HARVEST ==="
Write-Host "URL:    $Url"
Write-Host "Name:   $Name"
Write-Host "Output: $channelOut"
Write-Host ""

& $harvestPython @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($InventoryOnly) {
    Write-Host ""
    Write-Host "Inventory complete. No captions, audio, or diarization were run."
    exit 0
}

if (-not $ProcessCaptionless) {
    Write-Host ""
    Write-Host "Caption harvest complete."
    Write-Host "Captionless queue: $(Join-Path $channelOut 'needs_transcription.csv')"
    Write-Host "Rerun with -ProcessCaptionless to use audio-only + M0J1M0J1."
    exit 0
}

if (-not $MojiRoot) {
    $candidates = @(
        "$env:USERPROFILE\Desktop\M0J1M0J1_GPU",
        "$env:USERPROFILE\Desktop\M0J1M0J1"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path (Join-Path $candidate "voice_harvest.py")) {
            $MojiRoot = $candidate
            break
        }
    }
}

if (-not $MojiRoot) { throw "Could not find M0J1M0J1_GPU or M0J1M0J1 with voice_harvest.py." }

$queue = Join-Path $channelOut "needs_transcription.csv"
$audioScript = Join-Path $PSScriptRoot "download_captionless_audio.py"
& $harvestPython $audioScript $queue
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$audioDir = Join-Path $channelOut "audio_fallback"
$audioFiles = Get-ChildItem $audioDir -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -match "^\.(m4a|webm|opus|mp3|wav|aac|ogg|flac)$" }
if (-not $audioFiles) {
    Write-Host "No captionless audio requires Moji processing."
    exit 0
}

$mojiPythonCandidates = @(
    (Join-Path $MojiRoot ".venv-voice-harvester\Scripts\python.exe"),
    "$env:USERPROFILE\Desktop\M0J1M0J1\.venv-voice-harvester\Scripts\python.exe",
    "$env:USERPROFILE\Desktop\M0J1M0J1_GPU\.venv-voice-harvester\Scripts\python.exe"
)
$mojiPython = $null
foreach ($candidate in $mojiPythonCandidates) {
    if (Test-Path $candidate) { $mojiPython = $candidate; break }
}
if (-not $mojiPython) { throw "Moji voice-harvester venv not found." }

$mojiOut = Join-Path $channelOut "moji_work"
$voiceHarvest = Join-Path $MojiRoot "voice_harvest.py"

Write-Host ""
Write-Host "Using Moji: $MojiRoot"
Write-Host "Audio only: $audioDir"

& $mojiPython $voiceHarvest scan --input $audioDir --output $mojiOut --hash sha256
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $mojiPython $voiceHarvest diarize --output $mojiOut --device cuda
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Moji diarization complete: $mojiOut"
Write-Host "Transcription/attribution import is the next stage."
