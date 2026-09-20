param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $repoRoot "research\runtime\services.json"

function Stop-ProcessTree([int]$ProcessId) {
    $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { [int]$_.ParentProcessId -eq $ProcessId })
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path $statePath)) {
    Write-Host "No pipeline services state file found."
    exit 0
}

$state = Get-Content $statePath -Raw | ConvertFrom-Json
$targets = @(
    @{ name="cpu"; pid=[int]$state.cpu.pid; marker="cpu_pipeline_server.py" },
    @{ name="gpu"; pid=[int]$state.gpu.pid; marker="gpu_pipeline_server.py" },
    @{ name="hub"; pid=[int]$state.hub.pid; marker="pipeline_hub.py" }
)

foreach ($t in $targets) {
    if ($t.pid -le 0) { continue }
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $t.pid) -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host ("{0}: PID {1} is not running" -f $t.name,$t.pid)
        continue
    }

    $cmd = [string]$proc.CommandLine
    $matches = $cmd -like ("*{0}*" -f $t.marker)
    if (-not $matches -and -not $Force) {
        Write-Warning ("Refusing to stop PID {0}: command line does not contain {1}. Use -Force only if you verified the PID." -f $t.pid,$t.marker)
        continue
    }

    Write-Host ("Stopping {0}: PID {1}" -f $t.name,$t.pid)
    Stop-ProcessTree -ProcessId $t.pid
}

Start-Sleep -Milliseconds 500
Remove-Item $statePath -Force -ErrorAction SilentlyContinue
Write-Host "Pipeline service state cleared."
