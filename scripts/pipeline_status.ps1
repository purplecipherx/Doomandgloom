param(
    [string]$HostAddress = "127.0.0.1",
    [int]$HubPort = 8765,
    [int]$CpuPort = 8766,
    [int]$GpuPort = 8767
)

$ErrorActionPreference = "Stop"
$hub = ("http://{0}:{1}" -f $HostAddress, $HubPort)
$cpu = ("http://{0}:{1}" -f $HostAddress, $CpuPort)
$gpu = ("http://{0}:{1}" -f $HostAddress, $GpuPort)

Write-Host "=== HUB ==="
(Invoke-RestMethod -Uri ($hub + "/stats") -TimeoutSec 5) | ConvertTo-Json -Depth 8
Write-Host ""
Write-Host "=== CPU ==="
(Invoke-RestMethod -Uri ($cpu + "/status") -TimeoutSec 5) | ConvertTo-Json -Depth 8
Write-Host ""
Write-Host "=== GPU ==="
(Invoke-RestMethod -Uri ($gpu + "/status") -TimeoutSec 5) | ConvertTo-Json -Depth 8
