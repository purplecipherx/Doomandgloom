param(
    [switch]$Force,
    [switch]$RecoverActive
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$statePath = Join-Path $repoRoot "research\runtime\services.json"
if (-not (Test-Path $statePath)) { throw "Missing $statePath" }
$state = Get-Content $statePath -Raw | ConvertFrom-Json

$gpuUrl=[string]$state.gpu.url
try {
    $status=Invoke-RestMethod -Uri ($gpuUrl + "/status") -TimeoutSec 3
    if ($status.active -and -not $Force -and -not $RecoverActive) {
        throw ("GPU job is active: " + $status.active.job_key + ". Use -RecoverActive to safely requeue it before restart.")
    }
} catch {
    if ($_.Exception.Message -like "GPU job is active:*") { throw }
}

$gpuPid=[int]$state.gpu.pid
if ($gpuPid -gt 0) {
    $proc=Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $gpuPid) -ErrorAction SilentlyContinue
    if ($proc) {
        if ([string]$proc.CommandLine -notlike "*gpu_pipeline_server.py*") {
            throw "Refusing to stop PID $gpuPid because it is not gpu_pipeline_server.py"
        }
        Write-Host "Stopping GPU pipeline PID $gpuPid"
        Stop-Process -Id $gpuPid -Force
        Start-Sleep -Milliseconds 800
    }
}

if ($RecoverActive) {
    Write-Host "Recovering leased GPU jobs..."
    $repoPython = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
    & $repoPython (Join-Path $PSScriptRoot "recover_gpu_queue.py") --db (Join-Path $repoRoot "research\runtime\pipeline_jobs.sqlite")
    if ($LASTEXITCODE -ne 0) { throw "GPU queue recovery failed." }
}

$mojiPython=[string]$state.gpu.python
$mojiRoot=[string]$state.gpu.moji_root
$hubUrl=[string]$state.hub.url
$uri=[Uri]$gpuUrl
$gpuProc=Start-Process -FilePath $mojiPython -ArgumentList @(
    (Join-Path $PSScriptRoot "gpu_pipeline_server.py"),
    "--hub",$hubUrl,
    "--host",$uri.Host,
    "--port","$($uri.Port)",
    "--moji-root",$mojiRoot
) -WorkingDirectory $repoRoot -PassThru

$deadline=(Get-Date).AddSeconds(30)
$healthy=$false
do {
    try {
        $r=Invoke-RestMethod -Uri ($gpuUrl + "/health") -TimeoutSec 2
        if ($r.ok) { $healthy=$true; break }
    } catch {}
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
if (-not $healthy) { throw "Replacement GPU service did not become healthy." }

$state.gpu.pid=$gpuProc.Id
$state | ConvertTo-Json -Depth 5 | Set-Content $statePath -Encoding UTF8
Write-Host ("GPU pipeline restarted. PID {0}" -f $gpuProc.Id) -ForegroundColor Green
