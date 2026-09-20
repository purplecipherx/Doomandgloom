param(
    [int]$CpuWorkers = 4,
    [int]$AudioWorkers = 4,
    [int]$HarvestSlots = 2,
    [int]$AudioSlots = 2,
    [string]$HostAddress = "127.0.0.1",
    [int]$HubPort = 8765,
    [int]$CpuPort = 8766,
    [int]$GpuPort = 8767
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Missing .venv-youtube Python: $python" }

$mojiCandidates = @(
    "$env:USERPROFILE\Desktop\M0J1M0J1_VOICE",
    "$env:USERPROFILE\Desktop\M0J1M0J1_GPU",
    "$env:USERPROFILE\Desktop\M0J1M0J1"
)
$mojiRoot = $null
$mojiPython = $null
foreach ($candidate in $mojiCandidates) {
    $vh = Join-Path $candidate "voice_harvest.py"
    $mp = Join-Path $candidate ".venv-voice-harvester\Scripts\python.exe"
    if ((Test-Path $vh) -and (Test-Path $mp)) {
        $mojiRoot = $candidate
        $mojiPython = $mp
        break
    }
}
if (-not $mojiRoot -or -not $mojiPython) {
    throw "Could not find a ready M0J1M0J1 voice-harvester checkout + venv."
}

$runtime = Join-Path $repoRoot "research\runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$db = Join-Path $runtime "pipeline_jobs.sqlite"
$hubUrl = ("http://{0}:{1}" -f $HostAddress, $HubPort)
$cpuUrl = ("http://{0}:{1}" -f $HostAddress, $CpuPort)
$gpuUrl = ("http://{0}:{1}" -f $HostAddress, $GpuPort)

function Wait-Health([string]$url, [int]$seconds=30) {
    $deadline = (Get-Date).AddSeconds($seconds)
    do {
        try {
            $r = Invoke-RestMethod -Uri ($url + "/health") -TimeoutSec 2
            if ($r.ok) { return }
        } catch {}
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Service did not become healthy: $url"
}

$hubProc = Start-Process -FilePath $python -ArgumentList @(
    (Join-Path $PSScriptRoot "pipeline_hub.py"), "serve",
    "--db", $db, "--host", $HostAddress, "--port", "$HubPort"
) -WorkingDirectory $repoRoot -PassThru
Wait-Health $hubUrl

$cpuProc = Start-Process -FilePath $python -ArgumentList @(
    (Join-Path $PSScriptRoot "cpu_pipeline_server.py"),
    "--hub", $hubUrl, "--host", $HostAddress, "--port", "$CpuPort",
    "--workers", "$CpuWorkers", "--audio-workers", "$AudioWorkers",
    "--harvest-slots", "$HarvestSlots", "--audio-slots", "$AudioSlots"
) -WorkingDirectory $repoRoot -PassThru
Wait-Health $cpuUrl

$gpuProc = Start-Process -FilePath $mojiPython -ArgumentList @(
    (Join-Path $PSScriptRoot "gpu_pipeline_server.py"),
    "--hub", $hubUrl, "--host", $HostAddress, "--port", "$GpuPort",
    "--moji-root", $mojiRoot
) -WorkingDirectory $repoRoot -PassThru
Wait-Health $gpuUrl

$state = [ordered]@{
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    hub = @{ pid=$hubProc.Id; url=$hubUrl }
    cpu = @{ pid=$cpuProc.Id; url=$cpuUrl }
    gpu = @{ pid=$gpuProc.Id; url=$gpuUrl; moji_root=$mojiRoot; python=$mojiPython }
    database = $db
}
$state | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $runtime "services.json") -Encoding UTF8

Write-Host ""
Write-Host "Doomandgloom services running:"
Write-Host ("  HUB  {0}  PID {1}" -f $hubUrl, $hubProc.Id)
Write-Host ("  CPU  {0}  PID {1} workers={2} harvest_slots={3} audio_slots={4}" -f $cpuUrl, $cpuProc.Id, $CpuWorkers, $HarvestSlots, $AudioSlots)
Write-Host ("  GPU  {0}  PID {1} consumers=1" -f $gpuUrl, $gpuProc.Id)
Write-Host ("  DB   {0}" -f $db)
