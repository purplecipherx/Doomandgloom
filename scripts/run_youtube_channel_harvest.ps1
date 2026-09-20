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
    [string]$MojiRoot = "",
    [ValidateSet("cuda","cpu")]
    [string]$Device = "cuda",
    [string]$WhisperModel = "medium.en",
    [string]$ComputeType = "int8",
    [int]$BatchSize = 4
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
    Write-Host "Inventory complete. No captions, audio, diarization, or transcription were run."
    exit 0
}

if (-not $ProcessCaptionless) {
    Write-Host ""
    Write-Host "Caption harvest complete."
    Write-Host "Captionless queue: $(Join-Path $channelOut 'needs_transcription.csv')"
    Write-Host "Rerun with -ProcessCaptionless for audio-only + M0J1M0J1 diarization/transcription."
    exit 0
}

if (-not $MojiRoot) {
    $candidates = @(
        "$env:USERPROFILE\Desktop\M0J1M0J1_GPU",
        "$env:USERPROFILE\Desktop\M0J1M0J1"
    )
    foreach ($candidate in $candidates) {
        if (-not (Test-Path $candidate)) { continue }
        $direct = Join-Path $candidate "voice_harvest.py"
        if (Test-Path $direct) {
            $MojiRoot = $candidate
            break
        }
        $found = Get-ChildItem $candidate -Recurse -File -Filter "voice_harvest.py" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            $MojiRoot = Split-Path -Parent $found.FullName
            break
        }
    }
}

if (-not $MojiRoot) {
    throw "Could not find voice_harvest.py under M0J1M0J1_GPU or M0J1M0J1."
}

$queue = Join-Path $channelOut "needs_transcription.csv"
$audioScript = Join-Path $PSScriptRoot "download_captionless_audio.py"
& $harvestPython $audioScript $queue
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$audioDir = Join-Path $channelOut "audio_fallback"
$audioManifest = Join-Path $audioDir "audio_manifest.jsonl"
$audioFiles = Get-ChildItem $audioDir -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -match "^\.(m4a|webm|opus|mp3|wav|aac|ogg|flac)$" }

if (-not $audioFiles -or $audioFiles.Count -eq 0) {
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
if (-not $mojiPython) {
    foreach ($root in @("$env:USERPROFILE\Desktop\M0J1M0J1_GPU", "$env:USERPROFILE\Desktop\M0J1M0J1")) {
        if (-not (Test-Path $root)) { continue }
        $found = Get-ChildItem $root -Recurse -File -Filter "python.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*\.venv-voice-harvester\Scripts\python.exe" } |
            Select-Object -First 1
        if ($found) { $mojiPython = $found.FullName; break }
    }
}
if (-not $mojiPython) {
    throw "Moji voice-harvester venv not found. Run voice_harvester\install_windows.ps1 in M0J1M0J1 first."
}

& $mojiPython -c "import os; from huggingface_hub import get_token; raise SystemExit(0 if (os.getenv('HF_TOKEN') or os.getenv('HUGGINGFACE_TOKEN') or get_token()) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "No Hugging Face authentication found. Run the Moji venv Python with: python -c \"from huggingface_hub import login; login()\""
}

$mojiOut = Join-Path $channelOut "moji_work"
$voiceHarvest = Join-Path $MojiRoot "voice_harvest.py"

Write-Host ""
Write-Host "=== M0J1M0J1 FALLBACK ==="
Write-Host "Moji root: $MojiRoot"
Write-Host "Audio-only source: $audioDir"
Write-Host ""

& $mojiPython $voiceHarvest scan --input $audioDir --output $mojiOut --hash sha256
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $mojiPython $voiceHarvest diarize --output $mojiOut --device $Device
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $mojiPython $voiceHarvest embed --output $mojiOut --embed-device cpu
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $mojiPython $voiceHarvest cluster --output $mojiOut --threshold 0.68
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $mojiPython $voiceHarvest extract --output $mojiOut
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $mojiPython $voiceHarvest transcribe --output $mojiOut --device $Device --whisper-model $WhisperModel --compute-type $ComputeType --batch-size $BatchSize
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$bridge = Join-Path $PSScriptRoot "import_moji_research_transcripts.py"
$researchOut = Join-Path $channelOut "diarized_transcripts"

& $harvestPython $bridge --moji-output $mojiOut --audio-manifest $audioManifest --output $researchOut
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== COMPLETE ==="
Write-Host "Inventory:           $(Join-Path $channelOut 'inventory.csv')"
Write-Host "Caption status:      $(Join-Path $channelOut 'caption_status.csv')"
Write-Host "Captionless queue:   $queue"
Write-Host "Moji work/audit:     $mojiOut"
Write-Host "Diarized transcript: $(Join-Path $researchOut 'diarized_transcript.csv')"
