param(
    [int]$CpuWorkers = 4,
    [int]$HarvestSlots = 2,
    [int]$AudioSlots = 2,
    [int]$CaptionWorkers = 8,
    [int]$AudioWorkers = 4,
    [double]$Sleep = 0.75,
    [string]$WhisperModel = "medium.en",
    [string]$ComputeType = "int8",
    [int]$BatchSize = 4,
    [switch]$SkipPreflight,
    [switch]$DoNotStartServers,
    [switch]$Force,
    [switch]$PreferExistingCaptions
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Missing .venv-youtube Python: $python" }

# Research-set membership lives in data/research_sets/fitts_armstrong_full.csv.
# Inclusion means acquisition relevance, not ally/coordination/financial relationship.
$researchSetPath = Join-Path $repoRoot "data\research_sets\fitts_armstrong_full.csv"
if (-not (Test-Path $researchSetPath)) { throw "Missing $researchSetPath" }
$researchSet = @(Import-Csv $researchSetPath)
$fullEntityIds = @(
    $researchSet |
        Where-Object { $_.acquisition_scope.Trim().ToLowerInvariant() -eq "full_channel" } |
        ForEach-Object { $_.entity_id }
)

$registryPath = Join-Path $repoRoot "data\youtube_channels.csv"
$entitiesPath = Join-Path $repoRoot "data\entities.csv"
if (-not (Test-Path $registryPath)) { throw "Missing $registryPath" }
if (-not (Test-Path $entitiesPath)) { throw "Missing $entitiesPath" }

$registry = @(Import-Csv $registryPath)
$selected = @(
    $registry | Where-Object {
        $fullEntityIds -contains $_.entity_id -and
        $_.enabled.ToLowerInvariant() -eq "true" -and
        $_.verification_status.Trim().ToLowerInvariant() -eq "verified"
    } | Sort-Object channel_id
)

$missingFullEntities = @($fullEntityIds | Where-Object { $_ -notin $selected.entity_id })
if ($missingFullEntities.Count -gt 0) {
    throw ("Full-channel research entities missing a verified enabled registry channel: " + ($missingFullEntities -join ", "))
}

Write-Host ""
Write-Host "=== FITTS + ARMSTRONG FULL-CORPUS ACQUISITION ===" -ForegroundColor Cyan
Write-Host "Channels selected: $($selected.Count)"
foreach ($r in $selected) {
    Write-Host ("  {0}  {1}  [{2}]" -f $r.channel_id, $r.channel_name, $r.entity_id)
}
Write-Host ""
Write-Host "Policy:" -ForegroundColor Yellow
Write-Host "  * Inventory ALL videos/shorts/streams (no video-count limit)"
if ($PreferExistingCaptions) {
    Write-Host "  * Good captions are reused as transcript text when available"
    Write-Host "  * Captionless items -> 128 kbps audio -> Moji diarization -> WhisperX transcription"
    Write-Host "  * Captioned items -> 128 kbps audio -> Moji diarization/voice indexing -> caption speaker attribution"
} else {
    Write-Host "  * EVERY harvested video -> 128 kbps audio -> Moji diarization/embedding/clustering -> WhisperX transcription"
    Write-Host "  * Existing captions are still retained as independent text evidence, but are not used to skip Whisper"
}
Write-Host "  * No bulk source-video retention"
Write-Host ""

if (-not $SkipPreflight) {
    & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "preflight_youtube_pipeline.ps1") -Mode full
    if ($LASTEXITCODE -ne 0) { throw "Preflight failed." }
}

$runRoot = Join-Path $repoRoot "research\runtime"
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$subsetRegistry = Join-Path $runRoot "fitts_armstrong_full_registry.csv"
$selected | Export-Csv -NoTypeInformation -Encoding UTF8 $subsetRegistry

if (-not $DoNotStartServers) {
    $services = Join-Path $runRoot "services.json"
    $needStart = $true
    if (Test-Path $services) {
        try {
            $state = Get-Content $services -Raw | ConvertFrom-Json
            $hub = Invoke-RestMethod -Uri ($state.hub.url + "/health") -TimeoutSec 2
            $cpu = Invoke-RestMethod -Uri ($state.cpu.url + "/health") -TimeoutSec 2
            $gpu = Invoke-RestMethod -Uri ($state.gpu.url + "/health") -TimeoutSec 2
            if ($hub.ok -and $cpu.ok -and $gpu.ok) { $needStart = $false }
        } catch {}
    }
    if ($needStart) {
        & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start_pipeline_servers.ps1") -CpuWorkers $CpuWorkers -AudioWorkers $AudioWorkers -HarvestSlots $HarvestSlots -AudioSlots $AudioSlots
        if ($LASTEXITCODE -ne 0) { throw "Could not start pipeline services." }
    } else {
        Write-Host "Pipeline services already healthy; reusing them." -ForegroundColor Green
    }
}

$runId = "fitts_armstrong_full_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$hubUrl = "http://127.0.0.1:8765"

$argsList = @(
    (Join-Path $PSScriptRoot "queue_youtube_corpus.py"),
    "--hub", $hubUrl,
    "--registry", $subsetRegistry,
    "--run-id", $runId,
    "--caption-workers", "$CaptionWorkers",
    "--audio-workers", "$AudioWorkers",
    "--sleep", "$Sleep",
    "--device", "cuda",
    "--whisper-model", $WhisperModel,
    "--compute-type", $ComputeType,
    "--batch-size", "$BatchSize"
)
# No --limit-videos / --captionless-limit / --voice-index-limit: zero means unlimited.
# Default for this special full-corpus launcher is literal full Whisper transcription.
if (-not $PreferExistingCaptions) { $argsList += "--force-whisper-all" }
if ($Force) { $argsList += "--force" }

& $python @argsList
if ($LASTEXITCODE -ne 0) { throw "Corpus queueing failed." }

Write-Host ""
Write-Host "Queued full research set as: $runId" -ForegroundColor Green
Write-Host "Watch progress with:"
Write-Host "  powershell.exe -ExecutionPolicy Bypass -File .\scripts\pipeline_status.ps1"
Write-Host ""

$entities = @(Import-Csv $entitiesPath)
$verifiedEntityIds = @(
    $registry | Where-Object {
        $_.enabled.ToLowerInvariant() -eq "true" -and
        $_.verification_status.Trim().ToLowerInvariant() -eq "verified"
    } | ForEach-Object { $_.entity_id }
)

# The CSV is the authoritative research-set definition.
$researchEntityIds = @($researchSet | ForEach-Object { $_.entity_id })

$missingVerifiedChannels = @(
    $entities | Where-Object {
        $researchEntityIds -contains $_.id -and
        $_.type -in @("person","organization") -and
        $_.id -notin $verifiedEntityIds
    } | Sort-Object cluster, priority, name
)

if ($missingVerifiedChannels.Count -gt 0) {
    Write-Host "Relevant entities WITHOUT a verified enabled own channel:" -ForegroundColor Yellow
    foreach ($e in $missingVerifiedChannels) {
        Write-Host ("  {0,-28} {1,-18} {2}" -f $e.id, $e.cluster, $e.name)
    }
    Write-Host ""
    Write-Host "These are not auto-downloaded until their channel is verified; appearances on selected ecosystem channels are still harvested."
}
