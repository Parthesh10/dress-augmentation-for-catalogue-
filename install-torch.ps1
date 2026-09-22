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
$py = ".venv-torch\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet

#: PyTorch retires old CUDA wheel channels as new CUDA versions ship, so a
#: single hardcoded index (this used to just say "cu121") silently stops
#: matching anything on a newer torch/Python combination -- found on a real
#: run: pip printed "from versions: none" and the script barely noticed,
#: because transformers/numpy/pillow installed fine on top of a venv that
#: was missing torch entirely. Try a short list of recent channels instead,
#: newest first, and only fall back to CPU once every one of them has
#: genuinely failed to resolve -- not guessed once and trusted.
$cudaIndexes = @(
    "https://download.pytorch.org/whl/cu128",
    "https://download.pytorch.org/whl/cu126",
    "https://download.pytorch.org/whl/cu124",
    "https://download.pytorch.org/whl/cu121"
)

$torchInstalled = $false
if ($hasNvidiaGpu) {
    foreach ($index in $cudaIndexes) {
        Write-Host "NVIDIA GPU detected -- trying the CUDA build of torch from $index ..."
        & $py -m pip install torch torchvision --index-url $index
        if ($LASTEXITCODE -eq 0) { $torchInstalled = $true; break }
        Write-Host "That channel didn't have a matching build -- trying the next one."
    }
    if (-not $torchInstalled) {
        Write-Host "No CUDA channel had a matching build for this Python version -- falling back to CPU."
    }
} else {
    Write-Host "No NVIDIA GPU detected (nvidia-smi not found on PATH) -- installing the CPU build."
}

if (-not $torchInstalled) {
    & $py -m pip install torch torchvision --index-url "https://download.pytorch.org/whl/cpu"
    if ($LASTEXITCODE -eq 0) { $torchInstalled = $true }
}

if (-not $torchInstalled) {
    Write-Error "torch failed to install from every channel tried (CUDA and CPU). Check the pip output above -- this is usually a Python version torch doesn't have a wheel for yet."
    exit 1
}

Write-Host "Installing transformers, numpy, pillow ..."
& $py -m pip install transformers numpy pillow

#: The real check, not just "did pip print success" -- confirms torch is
#: actually importable in this venv before calling the install done, so a
#: partial failure here can never look identical to a real success on the
#: next run (install-torch.ps1 is only skipped if this exact check already
#: passed once -- see below).
Write-Host "Verifying torch actually imports ..."
& $py -c "import torch; print('torch', torch.__version__, '-- CUDA available:', torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) {
    Write-Error "torch installed but does not import cleanly -- see the error above. Delete .venv-torch and re-run this script."
    exit 1
}

Write-Host ""
Write-Host "=================================================================="
Write-Host "Torch install done and verified. dressaug will find .venv-torch"
Write-Host "automatically -- no environment variable or config change needed."
Write-Host "Run the app with:  .\run.ps1"
Write-Host "=================================================================="
