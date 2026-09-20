param(
    [int]$CpuWorkers = 4,
    [int]$AudioWorkers = 4,
    [string]$HostAddress = "127.0.0.1",
    [int]$HubPort = 8765,
    [int]$CpuPort = 8766,
    [int]$GpuPort = 8767
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Missing .venv-youtube Python: $python" }

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
    "--workers", "$CpuWorkers", "--audio-workers", "$AudioWorkers"
) -WorkingDirectory $repoRoot -PassThru
Wait-Health $cpuUrl

$gpuProc = Start-Process -FilePath $python -ArgumentList @(
    (Join-Path $PSScriptRoot "gpu_pipeline_server.py"),
    "--hub", $hubUrl, "--host", $HostAddress, "--port", "$GpuPort"
) -WorkingDirectory $repoRoot -PassThru
Wait-Health $gpuUrl

$state = [ordered]@{
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    hub = @{ pid=$hubProc.Id; url=$hubUrl }
    cpu = @{ pid=$cpuProc.Id; url=$cpuUrl }
    gpu = @{ pid=$gpuProc.Id; url=$gpuUrl }
    database = $db
}
$state | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $runtime "services.json") -Encoding UTF8

Write-Host ""
Write-Host "Doomandgloom services running:"
Write-Host ("  HUB  {0}  PID {1}" -f $hubUrl, $hubProc.Id)
Write-Host ("  CPU  {0}  PID {1} workers={2}" -f $cpuUrl, $cpuProc.Id, $CpuWorkers)
Write-Host ("  GPU  {0}  PID {1} consumers=1" -f $gpuUrl, $gpuProc.Id)
Write-Host ("  DB   {0}" -f $db)
