@echo off
setlocal enabledelayedexpansion

rem Dress Studio -- single-file setup + launcher. Plain batch on purpose,
rem not a compiled .exe: a compiled binary that spawns git/PowerShell tends
rem to get killed mid-run by security software on a machine it's never seen
rem before, even when there's nothing actually wrong with it. A .bat file
rem calling the same install.ps1 / install-torch.ps1 / run.ps1 a manual
rem install would runs identically but doesn't trip that.
rem
rem What double-clicking this does: check Python/Git are present -> clone
rem the app next to itself if it isn't already there -> install.ps1 ->
rem install-torch.ps1 (GPU auto-detected) -> run.ps1. Safe to run again
rem later -- every step is skipped if already done.

set "REPO_URL=https://github.com/Parthesh10/dress-augmentation-for-catalogue-.git"
set "APP_DIR=%~dp0Dress Augmentation"

echo ==================================================================
echo  Dress Studio -- setup
echo ==================================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo Tick "Add python.exe to PATH" during install, then run this again.
    goto :fail
)

where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: Git was not found.
    echo Install it from https://git-scm.com/downloads (default options are fine),
    echo then run this again.
    goto :fail
)

if not exist "%APP_DIR%\run.ps1" (
    if exist "%APP_DIR%" (
        echo ERROR: A folder named "Dress Augmentation" already exists next to this
        echo file but doesn't look like a real Dress Studio checkout. Move or rename
        echo it, then run this again.
        goto :fail
    )
    echo Downloading Dress Studio ^(first run only^) ...
    git clone "%REPO_URL%" "%APP_DIR%"
    if errorlevel 1 (
        echo ERROR: git clone failed -- check your internet connection.
        goto :fail
    )
) else (
    echo Dress Studio already downloaded at "%APP_DIR%".
)

cd /d "%APP_DIR%"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Installing the app ^(fast, a few small packages^) ...
    powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
    if errorlevel 1 (
        echo ERROR: install.ps1 failed -- see the output above.
        goto :fail
    )
) else (
    echo App already installed.
)

if not exist ".venv-torch\Scripts\python.exe" (
    echo.
    echo Installing the AI models ^(multi-GB, one-time, can take a while^) ...
    powershell -NoProfile -ExecutionPolicy Bypass -File install-torch.ps1
    if errorlevel 1 (
        echo ERROR: install-torch.ps1 failed -- see the output above.
        goto :fail
    )
) else (
    echo AI models already installed.
)

echo.
echo Starting Dress Studio ...
powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1
goto :eof

:fail
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
