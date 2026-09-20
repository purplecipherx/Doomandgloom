param(
    [ValidateSet("inventory","captions","full")]
    [string]$Mode = "inventory",
    [string]$Registry = "data\youtube_channels.csv",
    [int]$Workers = 2,
    [int]$LimitChannels = 0,
    [int]$LimitVideos = 0,
    [int]$CaptionlessLimit = 0,
    [switch]$SkipSpider
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$registryPath = Join-Path $repoRoot $Registry
$runner = Join-Path $PSScriptRoot "run_youtube_channel_harvest.ps1"
$spiderRunner = Join-Path $PSScriptRoot "run_transcript_spider.ps1"

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
Write-Host "Spider:   $(-not $SkipSpider)"
Write-Host ""

$batchLog = @()
$batchStamp = Get-Date -Format "yyyyMMdd_HHmmss"

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

    if ($LimitVideos -gt 0) { $args += @("-Limit","$LimitVideos") }
    if ($CaptionlessLimit -gt 0) { $args += @("-CaptionlessLimit","$CaptionlessLimit") }
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
        continue
    }

    if (-not $SkipSpider -and $Mode -ne "inventory") {
        $spiderBatchId = $batchStamp + "_" + $ch.channel_id
        Write-Host ""
        Write-Host "--- transcript spider: $($ch.channel_id) ---"
        $channelRoot = Join-Path (Join-Path $repoRoot "research\youtube") $safeName
        & powershell.exe -ExecutionPolicy Bypass -File $spiderRunner -ResearchRoot $channelRoot -BatchId $spiderBatchId -SourceLabel $ch.channel_id
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Spider failed for $($ch.channel_id); continuing batch."
        }
    }
}

$logDir=Join-Path $repoRoot "research\youtube"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath=Join-Path $logDir ("batch_" + $Mode + "_" + $batchStamp + ".csv")
$batchLog | Export-Csv -NoTypeInformation -Encoding UTF8 $logPath

Write-Host ""
Write-Host "Batch complete: $logPath"

if (-not $SkipSpider -and $Mode -ne "inventory") {
    Write-Host ""
    Write-Host "Spider review queue:"
    Write-Host ("  " + (Join-Path $repoRoot "data\spider\mention_candidates.csv"))
    Write-Host "Per-channel spider audit runs:"
    Write-Host ("  " + (Join-Path $repoRoot "data\spider\runs"))
}
