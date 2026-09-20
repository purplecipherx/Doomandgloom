param(
    [ValidateSet("inventory","captions","full")]
    [string]$Mode = "inventory",
    [string]$Registry = "data\youtube_channels.csv",
    [int]$Workers = 2,
    [int]$LimitChannels = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$registryPath = Join-Path $repoRoot $Registry
$runner = Join-Path $PSScriptRoot "run_youtube_channel_harvest.ps1"

if (-not (Test-Path $registryPath)) { throw "Missing registry: $registryPath" }

$channels = Import-Csv $registryPath | Where-Object {
    $_.enabled -eq "true" -and $_.verification_status -eq "verified"
}

if ($LimitChannels -gt 0) {
    $channels = $channels | Select-Object -First $LimitChannels
}

Write-Host ""
Write-Host "=== DOOMANDGLOOM VERIFIED YOUTUBE BATCH ==="
Write-Host "Mode:     $Mode"
Write-Host "Channels: $($channels.Count)"
Write-Host ""

$batchLog = @()

foreach ($ch in $channels) {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "$($ch.channel_id)  $($ch.channel_name)"
    Write-Host "$($ch.youtube_url)"
    Write-Host "============================================================"

    $safeName = ($ch.channel_id -replace '[^A-Za-z0-9._-]','_')
    $args = @(
        "-ExecutionPolicy","Bypass",
        "-File",$runner,
        "-Url",$ch.youtube_url,
        "-Name",$safeName,
        "-Workers","$Workers"
    )

    if ($Mode -eq "inventory") { $args += "-InventoryOnly" }
    if ($Mode -eq "full") { $args += "-ProcessCaptionless" }

    $started=(Get-Date).ToUniversalTime().ToString("o")
    & powershell.exe @args
    $code=$LASTEXITCODE
    $ended=(Get-Date).ToUniversalTime().ToString("o")

    $batchLog += [pscustomobject]@{
        channel_id=$ch.channel_id
        entity_id=$ch.entity_id
        channel_name=$ch.channel_name
        youtube_url=$ch.youtube_url
        mode=$Mode
        started_at=$started
        ended_at=$ended
        exit_code=$code
    }

    if ($code -ne 0) {
        Write-Warning "Channel failed with exit code $code; continuing batch."
    }
}

$logDir=Join-Path $repoRoot "research\youtube"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$logPath=Join-Path $logDir "batch_$($Mode)_$stamp.csv"
$batchLog | Export-Csv -NoTypeInformation -Encoding UTF8 $logPath

Write-Host ""
Write-Host "Batch complete: $logPath"
