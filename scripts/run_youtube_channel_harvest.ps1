param(
    [Parameter(Mandatory=$true)]
    [string]$Url,

    [string]$Name = "",
    [string]$Output = "research/youtube",

    [int]$Workers = 2,
    [double]$Sleep = 0.75,
    [int]$Limit = 0,

    [switch]$InventoryOnly,
    [switch]$FullPipeline,

    [ValidateSet("cuda","cpu")]
    [string]$Device = "cuda",

    [string]$WhisperModel = "medium.en",
    [string]$Language = "en",
    [string]$ComputeType = "int8",
    [int]$BatchSize = 4,

    [int]$AudioLimit = 0,
    [int]$MojiLimit = 0
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$youtubePython = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
$harvestScript = Join-Path $PSScriptRoot "youtube_channel_harvest.py"
$audioScript = Join-Path $PSScriptRoot "download_captionless_audio.py"
$mojiScript = Join-Path $PSScriptRoot "moji_diarize_transcribe.py"
$runStarted = (Get-Date).ToUniversalTime().ToString("o")

function Resolve-SourceName {
    param([string]$InputUrl, [string]$ExplicitName)
    if ($ExplicitName) { return $ExplicitName }

    $clean = $InputUrl.TrimEnd("/")
    foreach ($suffix in @("/videos","/shorts","/streams","/featured")) {
        if ($clean.EndsWith($suffix)) {
            $clean = $clean.Substring(0, $clean.Length - $suffix.Length)
            break
        }
    }

    $leaf = ($clean -split "/")[-1]
    if (-not $leaf) { $leaf = "youtube" }
    return ($leaf -replace '[^A-Za-z0-9._-]', '_')
}

$sourceName = Resolve-SourceName -InputUrl $Url -ExplicitName $Name
$outputRoot = Join-Path $repoRoot $Output
$channelRoot = Join-Path $outputRoot $sourceName

Write-Host ""
Write-Host "=== DOOMANDGLOOM YOUTUBE HARVEST ==="
Write-Host "URL:       $Url"
Write-Host "Name:      $sourceName"
Write-Host "Output:    $channelRoot"
Write-Host "Mode:      $(if ($InventoryOnly) {'inventory only'} elseif ($FullPipeline) {'FULL: captions -> audio-only fallback -> Moji diarize/transcribe'} else {'inventory + existing captions'})"
Write-Host ""

if (-not (Test-Path $youtubePython)) {
    Write-Host "YouTube environment not found; creating it..."
    powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup_youtube_harvester.ps1")
}
if (-not (Test-Path $youtubePython)) {
    throw "YouTube Python environment was not created: $youtubePython"
}

# Stage 1: channel inventory + existing captions (unless InventoryOnly).
$harvestArgs = @(
    $harvestScript,
    $Url,
    "--output", $outputRoot,
    "--name", $sourceName,
    "--workers", "$Workers",
    "--sleep", "$Sleep"
)
if ($Limit -gt 0) { $harvestArgs += @("--limit", "$Limit") }
if ($InventoryOnly) { $harvestArgs += "--inventory-only" }

Write-Host "STAGE 1: YouTube inventory/captions"
& $youtubePython @harvestArgs
if ($LASTEXITCODE -ne 0) {
    throw "YouTube harvest failed with exit code $LASTEXITCODE"
}

if ($InventoryOnly) {
    Write-Host ""
    Write-Host "Inventory complete:"
    Write-Host "  $channelRoot\inventory.csv"
    exit 0
}

if (-not $FullPipeline) {
    Write-Host ""
    Write-Host "Caption harvest complete."
    Write-Host "Captionless queue:"
    Write-Host "  $channelRoot\needs_transcription.csv"
    Write-Host ""
    Write-Host "Run again with -FullPipeline to download AUDIO ONLY for captionless items and process them with the Moji diarizer."
    exit 0
}

# Stage 2: audio-only fallback for videos that have no usable captions.
$queueCsv = Join-Path $channelRoot "needs_transcription.csv"
if (-not (Test-Path $queueCsv)) {
    throw "Captionless queue not found: $queueCsv"
}

$queueRows = @(Import-Csv $queueCsv)
if ($queueRows.Count -eq 0) {
    Write-Host ""
    Write-Host "No captionless videos. Moji fallback not needed."
    exit 0
}

Write-Host ""
Write-Host "STAGE 2: AUDIO-ONLY fallback for $($queueRows.Count) captionless item(s)"
$audioArgs = @($audioScript, $queueCsv)
if ($AudioLimit -gt 0) { $audioArgs += @("--limit", "$AudioLimit") }

& $youtubePython @audioArgs
if ($LASTEXITCODE -ne 0) {
    throw "Audio-only fallback failed with exit code $LASTEXITCODE"
}

# Stage 3: Moji-derived pyannote + WhisperX speaker transcript.
$mojiPython = Join-Path $repoRoot ".venv-moji-audio\Scripts\python.exe"
if (-not (Test-Path $mojiPython)) {
    Write-Host ""
    Write-Host "Moji environment not found; creating it..."
    powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup_moji_audio.ps1")
}
if (-not (Test-Path $mojiPython)) {
    throw "Moji Python environment was not created: $mojiPython"
}

if (-not $env:HF_TOKEN -and -not $env:HUGGINGFACE_TOKEN) {
    throw 'HF_TOKEN is required for pyannote/speaker-diarization-community-1. Set: $env:HF_TOKEN = "hf_..."'
}

Write-Host ""
Write-Host "STAGE 3: M0J1M0J1-derived diarization + WhisperX transcription"
$mojiArgs = @(
    $mojiScript,
    "--channel-root", $channelRoot,
    "--device", $Device,
    "--whisper-model", $WhisperModel,
    "--language", $Language,
    "--compute-type", $ComputeType,
    "--batch-size", "$BatchSize"
)
if ($MojiLimit -gt 0) { $mojiArgs += @("--limit", "$MojiLimit") }

& $mojiPython @mojiArgs
if ($LASTEXITCODE -ne 0) {
    throw "Moji diarization/transcription failed with exit code $LASTEXITCODE"
}

$topManifest = @{
    pipeline = "doomandgloom-youtube-full"
    started_at = $runStarted
    completed_at = (Get-Date).ToUniversalTime().ToString("o")
    url = $Url
    source_name = $sourceName
    output = $channelRoot
    inventory_manifest = (Join-Path $channelRoot "run_manifest.json")
    audio_manifest = (Join-Path $channelRoot "audio_fallback\run_manifest.json")
    moji_manifest = (Join-Path $channelRoot "moji\run_manifest.json")
    media_policy = "captions first; audio-only fallback; no bulk video download"
    moji_provenance = "purplecipherx/M0J1M0J1 voice_harvester core: pyannote Community-1 + WhisperX"
}
$topManifest | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $channelRoot "full_pipeline_manifest.json")

Write-Host ""
Write-Host "=== COMPLETE ==="
Write-Host "Inventory:          $channelRoot\inventory.csv"
Write-Host "Caption status:     $channelRoot\caption_status.csv"
Write-Host "Captionless queue:  $channelRoot\needs_transcription.csv"
Write-Host "Moji transcripts:   $channelRoot\moji\"
Write-Host "Audit manifest:     $channelRoot\full_pipeline_manifest.json"
