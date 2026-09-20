param(
    [string]$Venv = ".venv-moji-audio"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot $Venv

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.10+ was not found on PATH."
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg/ffprobe are required by WhisperX. Install ffmpeg and put it on PATH."
}

if (-not (Test-Path $venvPath)) {
    python -m venv $venvPath
}

$py = Join-Path $venvPath "Scripts\python.exe"
& $py -m pip install -U pip wheel setuptools

Write-Host ""
Write-Host "IMPORTANT:"
Write-Host "Install/verify CUDA-enabled torch + torchaudio in this venv before GPU use."
Write-Host "The correct wheel depends on the installed NVIDIA driver/CUDA compatibility."
Write-Host ""

& $py -m pip install -r (Join-Path $repoRoot "requirements-moji-audio.txt")

Write-Host ""
Write-Host "Moji audio environment ready: $venvPath"
Write-Host "Set your Hugging Face token before diarization:"
Write-Host '$env:HF_TOKEN = "hf_..."'
