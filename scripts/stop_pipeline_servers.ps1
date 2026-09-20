$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $repoRoot "research\runtime\services.json"
if (-not (Test-Path $statePath)) { throw "No services.json found: $statePath" }
$state = Get-Content $statePath -Raw | ConvertFrom-Json
foreach ($svc in @("gpu","cpu","hub")) {
    $pidValue = [int]$state.$svc.pid
    if ($pidValue -gt 0) {
        $p = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($p) {
            Stop-Process -Id $pidValue -Force
            Write-Host ("Stopped {0} PID {1}" -f $svc, $pidValue)
        }
    }
}
Remove-Item $statePath -Force -ErrorAction SilentlyContinue
