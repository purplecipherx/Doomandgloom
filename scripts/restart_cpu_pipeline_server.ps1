param(
    [int]$CpuWorkers = 4,
    [int]$AudioWorkers = 2,
    [int]$HarvestSlots = 2,
    [int]$AudioSlots = 1
)

$ErrorActionPreference = "Stop"

function Stop-ProcessTree([int]$RootPid) {
    $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { [int]$_.ParentProcessId -eq $RootPid })
    foreach ($child in $children) {
        Stop-ProcessTree -RootPid ([int]$child.ProcessId)
    }
    Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
$statePath = Join-Path $repoRoot "research\runtime\services.json"
$db = Join-Path $repoRoot "research\runtime\pipeline_jobs.sqlite"
if (-not (Test-Path $python)) { throw "Missing Python: $python" }
if (-not (Test-Path $statePath)) { throw "Missing pipeline services state: $statePath" }

$state = Get-Content $statePath -Raw | ConvertFrom-Json
$cpuPid = [int]$state.cpu.pid
if ($cpuPid -gt 0) {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $cpuPid) -ErrorAction SilentlyContinue
    if ($proc) {
        if ([string]$proc.CommandLine -notlike "*cpu_pipeline_server.py*") {
            throw "Refusing to stop PID $cpuPid because it is not cpu_pipeline_server.py"
        }
        Write-Host "Stopping CPU pipeline PID $cpuPid and its child process tree"
        Stop-ProcessTree -RootPid $cpuPid
        Start-Sleep -Milliseconds 700
    }
}

Write-Host "Recovering leased CPU jobs and rebalancing queue..."
& $python (Join-Path $PSScriptRoot "recover_cpu_queue.py") --db $db
if ($LASTEXITCODE -ne 0) { throw "CPU queue recovery failed." }

$hubUrl = [string]$state.hub.url
$cpuUrl = [string]$state.cpu.url
$uri = [Uri]$cpuUrl
$hostAddress = $uri.Host
$port = $uri.Port

$cpuProc = Start-Process -FilePath $python -ArgumentList @(
    (Join-Path $PSScriptRoot "cpu_pipeline_server.py"),
    "--hub", $hubUrl,
    "--host", $hostAddress,
    "--port", "$port",
    "--workers", "$CpuWorkers",
    "--audio-workers", "$AudioWorkers",
    "--harvest-slots", "$HarvestSlots",
    "--audio-slots", "$AudioSlots"
) -WorkingDirectory $repoRoot -PassThru

$deadline=(Get-Date).AddSeconds(30)
$healthy=$false
do {
    try {
        $r=Invoke-RestMethod -Uri ($cpuUrl + "/health") -TimeoutSec 2
        if ($r.ok) { $healthy=$true; break }
    } catch {}
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
if (-not $healthy) { throw "Replacement CPU service did not become healthy." }

$state.cpu.pid=$cpuProc.Id
$state.started_at=(Get-Date).ToUniversalTime().ToString("o")
$state | ConvertTo-Json -Depth 5 | Set-Content $statePath -Encoding UTF8

Write-Host ""
Write-Host "CPU pipeline recovered." -ForegroundColor Green
Write-Host ("  CPU PID {0}" -f $cpuProc.Id)
Write-Host ("  Hub unchanged: {0}" -f $hubUrl)
Write-Host ("  GPU unchanged: {0}" -f $state.gpu.url)
Write-Host ""
