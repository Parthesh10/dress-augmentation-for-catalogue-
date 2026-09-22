# Dress Studio -- one-time setup on a Windows machine.
#
# What this installs is deliberately small: Pillow, numpy, pyarrow, a HEIC
# decoder, and Gradio -- no torch. That's not an oversight; see "Matting on
# this machine" below. Run from anywhere; it resolves paths off its own
# location.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python was not found on PATH. Install Python 3.11+ from python.org (check 'Add python.exe to PATH' during install), then run this script again."
    exit 1
}

$pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Using Python $pyVersion at $($py.Source)"

if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
}

Write-Host "Installing dependencies (Pillow, numpy, Gradio -- a small install, no torch) ..."
& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host ""
Write-Host "=================================================================="
Write-Host "Base install done. Run the app with:  .\run.ps1"
Write-Host "=================================================================="
Write-Host ""
Write-Host "IMPORTANT -- background removal needs one more thing:"
Write-Host ""
Write-Host "This project's own .venv deliberately has no torch (a multi-GB"
Write-Host "install), because matting runs in a SEPARATE Python interpreter"
Write-Host "that already has torch + transformers installed. By default this"
Write-Host "app looks for that interpreter at:"
Write-Host "    ..\Boutique Business\.venv-cuda\Scripts\python.exe   (GPU)"
Write-Host "    ..\Boutique Business\.venv-birefnet\Scripts\python.exe  (CPU)"
Write-Host "relative to this folder -- i.e. it expects a sibling project"
Write-Host "folder next to this one that already has that interpreter built."
Write-Host ""
Write-Host "On a machine that doesn't have that sibling folder, set the"
Write-Host "DRESSAUG_TORCH_PYTHON environment variable to point at ANY Python"
Write-Host "interpreter that has torch + transformers + torchvision + Pillow"
Write-Host "installed -- see 'Setting up a torch interpreter from scratch'"
Write-Host "in README.md for the exact commands. Until one exists somewhere,"
Write-Host "the app runs and the UI opens, but the Process button's matting"
Write-Host "step will fail with a clear error naming the missing interpreter"
Write-Host "path, not a silent wrong result."
Write-Host ""
