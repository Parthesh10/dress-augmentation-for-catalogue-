# Dress Studio -- single-file setup + launcher, for sharing with a colleague
# as one .exe (see build-exe.ps1, which wraps this into DressStudioSetup.exe).
#
# What double-clicking this does, in order: check Python/Git are present ->
# clone the app next to itself if it isn't already there -> run install.ps1
# -> run install-torch.ps1 (GPU auto-detected) -> run.ps1. Safe to run again
# later -- every step is skipped if already done, so re-running it is just
# "open the app".

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/Parthesh10/dress-augmentation-for-catalogue-.git"
$AppFolderName = "Dress Augmentation"

function Pause-OnError($message) {
    Write-Host ""
    Write-Host "ERROR: $message" -ForegroundColor Red
    Write-Host "Press Enter to close this window."
    Read-Host | Out-Null
    exit 1
}

Write-Host "=================================================================="
Write-Host " Dress Studio -- setup"
Write-Host "=================================================================="
Write-Host ""

# ---- 1. Prerequisites ------------------------------------------------------
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Pause-OnError "Python was not found. Install Python 3.11+ from https://www.python.org/downloads/ -- tick 'Add python.exe to PATH' during install -- then run this again."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Pause-OnError "Git was not found. Install it from https://git-scm.com/downloads (default options are fine), then run this again."
}

# ---- 2. Get the code --------------------------------------------------------
# Runs from wherever it was double-clicked -- typically Desktop or Downloads.
$launchDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appPath = Join-Path $launchDir $AppFolderName

if (-not (Test-Path (Join-Path $appPath "run.ps1"))) {
    Write-Host "Downloading Dress Studio (first run only) ..."
    if (Test-Path $appPath) {
        # A folder exists but isn't a real checkout (e.g. an interrupted
        # clone) -- git clone refuses to reuse a non-empty directory, and
        # guessing at cleanup here is riskier than asking.
        Pause-OnError "A folder named '$AppFolderName' already exists next to this file but doesn't look like a real Dress Studio checkout. Move or rename it, then run this again."
    }
    git clone $RepoUrl $appPath
    if ($LASTEXITCODE -ne 0) {
        Pause-OnError "git clone failed -- check your internet connection and the repository URL in this script."
    }
} else {
    Write-Host "Dress Studio already downloaded at '$appPath'."
}

Set-Location $appPath

# ---- 3. Install (skipped automatically if already done) --------------------
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host ""
    Write-Host "Installing the app (fast, a few small packages) ..."
    & powershell -ExecutionPolicy Bypass -File install.ps1
    if ($LASTEXITCODE -ne 0) { Pause-OnError "install.ps1 failed -- see the output above." }
} else {
    Write-Host "App already installed."
}

if (-not (Test-Path ".venv-torch\Scripts\python.exe")) {
    Write-Host ""
    Write-Host "Installing the AI models (multi-GB, one-time, can take a while) ..."
    & powershell -ExecutionPolicy Bypass -File install-torch.ps1
    if ($LASTEXITCODE -ne 0) { Pause-OnError "install-torch.ps1 failed -- see the output above." }
} else {
    Write-Host "AI models already installed."
}

# ---- 4. Run ------------------------------------------------------------------
Write-Host ""
Write-Host "Starting Dress Studio ..."
& powershell -ExecutionPolicy Bypass -File run.ps1
