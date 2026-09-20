param(
    [ValidateSet("inventory","captions","full")]
    [string]$Mode = "captions"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$failures = @()
$warnings = @()

function Pass($m) { Write-Host "[PASS] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow; $script:warnings += $m }
function Fail($m) { Write-Host "[FAIL] $m" -ForegroundColor Red; $script:failures += $m }

Write-Host ""
Write-Host "=== DOOMANDGLOOM PIPELINE PREFLIGHT ==="
Write-Host "Mode: $Mode"
Write-Host "Repo: $repoRoot"
Write-Host ""

# Git repository / working tree.
if (Test-Path (Join-Path $repoRoot ".git")) { Pass "Git repository found" } else { Fail "Not a Git working tree: $repoRoot" }

# YouTube venv.
$ytPython = Join-Path $repoRoot ".venv-youtube\Scripts\python.exe"
if (Test-Path $ytPython) {
    Pass ".venv-youtube Python found"
} else {
    Fail ".venv-youtube missing; run scripts\setup_youtube_harvester.ps1"
}

# Parse every PowerShell script without executing it.
$psFiles = Get-ChildItem (Join-Path $repoRoot "scripts") -Filter "*.ps1" -File
foreach ($file in $psFiles) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {
        Fail ("PowerShell syntax: " + $file.Name + " :: " + (($errors | ForEach-Object Message) -join " | "))
    }
}
if (-not ($failures | Where-Object { $_ -like "PowerShell syntax:*" })) { Pass "PowerShell scripts parse cleanly" }

# Python syntax.
if (Test-Path $ytPython) {
    $pyFiles = @(
        "youtube_channel_harvest.py",
        "download_captionless_audio.py",
        "discover_youtube_channels.py",
        "import_moji_research_transcripts.py",
        "transcript_spider.py"
    ) | ForEach-Object { Join-Path $PSScriptRoot $_ }

    & $ytPython -m py_compile @pyFiles
    if ($LASTEXITCODE -eq 0) { Pass "Python scripts compile cleanly" } else { Fail "Python syntax compilation failed" }

    & $ytPython -m yt_dlp --version
    if ($LASTEXITCODE -eq 0) { Pass "yt-dlp available" } else { Fail "yt-dlp unavailable in .venv-youtube" }
}

# Registry integrity.
$registry = Join-Path $repoRoot "data\youtube_channels.csv"
if (-not (Test-Path $registry)) {
    Fail "YouTube channel registry missing"
} else {
    $rows = Import-Csv $registry
    $enabled = @($rows | Where-Object { $_.enabled.Trim().ToLower() -eq "true" -and $_.verification_status.Trim().ToLower() -eq "verified" })
    if ($enabled.Count -gt 0) { Pass "$($enabled.Count) enabled verified YouTube channels" } else { Fail "No enabled verified YouTube channels" }

    $dupeIds = $rows | Group-Object channel_id | Where-Object Count -gt 1
    if ($dupeIds) { Fail "Duplicate channel_id values in registry" } else { Pass "No duplicate channel IDs" }

    $dupeUrls = $enabled | Group-Object youtube_url | Where-Object Count -gt 1
    if ($dupeUrls) { Warn "Duplicate enabled YouTube URLs found" } else { Pass "No duplicate enabled URLs" }

    $placeholders = $enabled | Where-Object { $_.youtube_url -match '@CHANNEL|example\.com|PLACEHOLDER' }
    if ($placeholders) { Fail "Placeholder URL exists in enabled registry" } else { Pass "No enabled placeholder URLs" }
}

# Captions need only Python/yt-dlp. Full mode additionally needs media + Moji.
if ($Mode -eq "full") {
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Pass "ffmpeg found" } else { Fail "ffmpeg not on PATH" }
    if (Get-Command ffprobe -ErrorAction SilentlyContinue) { Pass "ffprobe found" } else { Fail "ffprobe not on PATH" }

    $mojiCandidates = @(
        "$env:USERPROFILE\Desktop\M0J1M0J1_GPU",
        "$env:USERPROFILE\Desktop\M0J1M0J1"
    )

    $voiceHarvestPath = $null
    foreach ($m in $mojiCandidates) {
        if (-not (Test-Path $m)) { continue }
        $direct = Join-Path $m "voice_harvest.py"
        if (Test-Path $direct) { $voiceHarvestPath = $direct; break }
        $found = Get-ChildItem $m -Recurse -File -Filter "voice_harvest.py" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $voiceHarvestPath = $found.FullName; break }
    }

    if ($voiceHarvestPath) {
        $mojiRoot = Split-Path -Parent $voiceHarvestPath
        Pass "Moji source found: $voiceHarvestPath"
    } else {
        $mojiRoot = $null
        Fail "No local voice_harvest.py found under M0J1M0J1_GPU or M0J1M0J1"
    }

    $mojiPython = $null
    foreach ($m in $mojiCandidates) {
        if (-not (Test-Path $m)) { continue }
        $direct = Join-Path $m ".venv-voice-harvester\Scripts\python.exe"
        if (Test-Path $direct) { $mojiPython = $direct; break }
        $found = Get-ChildItem $m -Recurse -File -Filter "python.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*\.venv-voice-harvester\Scripts\python.exe" } |
            Select-Object -First 1
        if ($found) { $mojiPython = $found.FullName; break }
    }

    if ($mojiPython) {
        Pass "Moji voice-harvester venv found: $mojiPython"
        & $mojiPython -c "import torch; import pyannote.audio; import whisperx; print('torch_cuda=' + str(torch.cuda.is_available()))"
        if ($LASTEXITCODE -eq 0) {
            Pass "Moji Python dependencies import successfully"
        } else {
            Fail "Moji dependencies failed to import"
        }

        & $mojiPython -c "import os; from huggingface_hub import get_token; raise SystemExit(0 if (os.getenv('HF_TOKEN') or os.getenv('HUGGINGFACE_TOKEN') or get_token()) else 1)"
        if ($LASTEXITCODE -eq 0) {
            Pass "Hugging Face authentication available (environment or cached login)"
        } else {
            Fail "No Hugging Face authentication found. Use the Moji venv and run: python -c \"from huggingface_hub import login; login()\""
        }
    } else {
        Fail "No .venv-voice-harvester found under either Moji tree"
        foreach ($m in $mojiCandidates) {
            $installer = Join-Path $m "voice_harvester\install_windows.ps1"
            if (Test-Path $installer) {
                Warn "Bootstrap available: powershell.exe -ExecutionPolicy Bypass -File \"$installer\""
                break
            }
        }
    }
}

Write-Host ""
if ($warnings.Count -gt 0) {
    Write-Host "Warnings: $($warnings.Count)" -ForegroundColor Yellow
}
if ($failures.Count -gt 0) {
    Write-Host "PREFLIGHT FAILED: $($failures.Count) issue(s)." -ForegroundColor Red
    exit 1
}
Write-Host "PREFLIGHT PASSED." -ForegroundColor Green
exit 0
