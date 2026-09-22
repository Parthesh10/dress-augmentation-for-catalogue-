# Dress Studio -- second-stage install, for a machine that does NOT have a
# `../Boutique Business/` sibling project (i.e. any machine except the
# original dev machine). Run this AFTER install.ps1.
#
# What this does: creates a second, self-contained virtual environment at
# `.venv-torch/` inside THIS project and installs torch + transformers +
# torchvision + numpy + pillow into it -- nothing else needs them. Matting
# and backdrop ground-detection run inside this interpreter as a subprocess;
# see src/dressaug/backends.py for why it's a separate interpreter at all
# (the app's own .venv deliberately stays a small, torch-free install).
#
# Installs the CUDA build automatically when this machine has an NVIDIA GPU
# (detected via `nvidia-smi`, which NVIDIA's own driver installer puts on
# PATH -- no manual CUDA toolkit install needed, the torch wheel below
# bundles its own CUDA runtime), and falls back to the CPU build otherwise.
# The rest of the pipeline needs no further change either way: backends.py's
# worker script already does `torch.cuda.is_available()` at runtime and uses
# whichever this install gave it -- CPU 30-180s/photo, GPU roughly 3x faster
# (see README.md "Matting now prefers the GPU when one's available").
#
#   powershell -ExecutionPolicy Bypass -File install-torch.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Error "No .venv found. Run install.ps1 first."
    exit 1
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python was not found on PATH. Install Python 3.11+ from python.org (check 'Add python.exe to PATH' during install), then run this script again."
    exit 1
}

if (-not (Test-Path ".venv-torch")) {
    Write-Host "Creating .venv-torch ..."
    python -m venv .venv-torch
}

$hasNvidiaGpu = $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($hasNvidiaGpu) {
    Write-Host "NVIDIA GPU detected (nvidia-smi found) -- installing the CUDA build of torch."
    $torchIndex = "https://download.pytorch.org/whl/cu121"
} else {
    Write-Host "No NVIDIA GPU detected -- installing the CPU build of torch."
    Write-Host "(If this machine does have an NVIDIA card, its driver may not be installed"
    Write-Host "or up to date -- nvidia-smi.exe wasn't found on PATH. The app still works"
    Write-Host "fully on CPU, just slower per photo.)"
    $torchIndex = "https://download.pytorch.org/whl/cpu"
}

Write-Host "Installing torch, transformers, torchvision, numpy, pillow ..."
Write-Host "This is a multi-GB download and can take several minutes on a slow connection."
& ".venv-torch\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv-torch\Scripts\python.exe" -m pip install torch torchvision --index-url $torchIndex
& ".venv-torch\Scripts\python.exe" -m pip install transformers numpy pillow

Write-Host ""
Write-Host "=================================================================="
Write-Host "Torch install done. dressaug will find .venv-torch automatically --"
Write-Host "no environment variable or config change needed. Run the app with:"
Write-Host "    .\run.ps1"
Write-Host "=================================================================="
