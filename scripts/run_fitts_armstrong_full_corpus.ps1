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
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Missing .venv-youtube Python: $python" }

# VERIFIED registry sources materially relevant to the Fitts/Armstrong research sets.
# Inclusion means acquisition relevance, not ally/coordination/financial relationship.
$selectedChannelIds = @(
    "YT001", # Catherine Austin Fitts / Solari
    "YT002", # Martin Armstrong / Armstrong Economics
    "YT003", # USAWatchdog - recurring Fitts/Armstrong interviewer
    "YT004", # Sarah Westall - recurring Fitts/Armstrong interviewer
    "YT005", # HighWire / Del Bigtree - Fitts media/health bridge
    "YT006", # Children's Health Defense - Solari collaboration/media ecosystem
    "YT007", # Peak Prosperity - finance/collapse media overlap
    "YT008", # UK Column - recurring Fitts/symposium/media hub
    "YT009", # Canadian Prepper - Armstrong media circuit
    "YT010", # Commodity Culture - Armstrong media circuit
    "YT011"  # Coffee and a Mike - Fitts/Armstrong interview bridge
)

$registryPath = Join-Path $repoRoot "data\youtube_channels.csv"
$entitiesPath = Join-Path $repoRoot "data\entities.csv"
if (-not (Test-Path $registryPath)) { throw "Missing $registryPath" }
if (-not (Test-Path $entitiesPath)) { throw "Missing $entitiesPath" }

$registry = @(Import-Csv $registryPath)
$selected = @(
    $registry | Where-Object {
        $selectedChannelIds -contains $_.channel_id -and
        $_.enabled.ToLowerInvariant() -eq "true" -and
        $_.verification_status.Trim().ToLowerInvariant() -eq "verified"
    }
)

$missingIds = @($selectedChannelIds | Where-Object { $_ -notin $selected.channel_id })
if ($missingIds.Count -gt 0) {
    throw ("Selected verified channel IDs missing/disabled: " + ($missingIds -join ", "))
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
Write-Host "  * Existing captions remain preferred text when available"
Write-Host "  * Captionless items -> 128 kbps audio -> Moji diarization -> WhisperX transcription"
Write-Host "  * Captioned items -> 128 kbps audio -> Moji diarization/voice indexing -> caption speaker attribution"
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

# Broad first-pass research set from the existing entity map. These are subjects/bridges
# worth acquiring, not a claim that they form one coordinated group.
$researchEntityIds = @(
    "fitts_catherine","solari","betts_carolyn","titus_john","farrell_joseph",
    "lynn_corey","oskam_ricardo","vanhamelen_elze","walters_jennifer",
    "granogger_ulrike","white_james","luschas_susan","werner_richard",
    "dowd_edward","skidmore_mark","schectman_andy","miles_franklin",
    "tommey_polly","chd","holland_mary","mercola_joseph","bigtree_del",
    "patrick_james","planet_lockdown","uk_column","robinson_mike","hudak_taylor",
    "hunter_greg","usawatchdog","westall_sarah","martenson_chris",
    "armstrong_martin","armstrong_economics","campbell_mike","lutz_kerry",
    "pletsch_erwin","coffee_mike","commodity_culture","canadian_prepper",
    "palisades_radio","doctors_appeal"
)

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
