param(
    [string]$CookiesFromBrowser = "opera",
    [switch]$SkipPreflight
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host ""
Write-Host "=== SWITCHING FULL CORPUS TO SPARSE VOICE MODE ===" -ForegroundColor Cyan
Write-Host "Stopping old services and child downloader/ffmpeg trees..."

& powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "stop_pipeline_servers.ps1")
if ($LASTEXITCODE -ne 0) { throw "Could not stop pipeline services." }

$runtime = Join-Path $repoRoot "research\runtime"
$archive = Join-Path $runtime "job_db_archive"
New-Item -ItemType Directory -Force -Path $archive | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")

$db = Join-Path $runtime "pipeline_jobs.sqlite"
foreach ($suffix in @("", "-wal", "-shm")) {
    $src = $db + $suffix
    if (Test-Path $src) {
        $name = ("pipeline_jobs_{0}.sqlite{1}" -f $stamp,$suffix)
        $dst = Join-Path $archive $name
        Move-Item -LiteralPath $src -Destination $dst -Force
        Write-Host ("Archived {0} -> {1}" -f $src,$dst)
    }
}

Write-Host ""
Write-Host "Old scheduler state archived. Research/captions/audio remain untouched." -ForegroundColor Green
Write-Host "Starting a fresh sparse-mode generation..."

$args = @(
    "-ExecutionPolicy","Bypass",
    "-File",(Join-Path $PSScriptRoot "run_fitts_armstrong_full_corpus.ps1"),
    "-CookiesFromBrowser",$CookiesFromBrowser
)
if ($SkipPreflight) { $args += "-SkipPreflight" }

& powershell.exe @args
if ($LASTEXITCODE -ne 0) { throw "Sparse corpus launch failed." }

Write-Host ""
Write-Host "Sparse corpus generation is live." -ForegroundColor Green
Write-Host "Monitor with:"
Write-Host "  powershell.exe -ExecutionPolicy Bypass -File .\scripts\pipeline_status.ps1"
