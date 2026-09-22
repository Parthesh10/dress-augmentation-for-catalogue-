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
rem the app next to itself if it isn't already there (or pull the latest
rem changes if it's already there) -> install.ps1 -> install-torch.ps1
rem (GPU auto-detected) -> run.ps1. Safe to run again later -- every step
rem is skipped (or, for the code itself, re-checked against GitHub) if
rem already done.
rem
rem The desktop shortcut this creates points back at THIS .bat file, not
rem straight at run.ps1 -- found necessary the first time this shipped a
rem real fix: a colleague's shortcut launched run.ps1 directly, which never
rem re-checks GitHub for anything, so a fix pushed today would silently
rem never reach a machine already set up. Going through this file every
rem time costs a couple of seconds for the update check and is the only
rem way "double-click the icon" and "get today's code" stay the same thing.

set "REPO_URL=https://github.com/Parthesh10/dress-augmentation-for-catalogue-.git"
set "APP_DIR=%~dp0Dress Augmentation"
set "SELF_PATH=%~f0"
set "SELF_DIR=%~dp0"

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
    echo Install it from https://git-scm.com/downloads -- default options are fine,
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
    echo Checking for updates ...
    pushd "%APP_DIR%"
    git pull --ff-only >nul 2>&1
    if errorlevel 1 (
        echo Could not check for updates just now -- continuing with what's already here.
    )
    popd
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

rem Checking the interpreter file exists isn't enough -- a torch install can
rem fail partway through (a retired CUDA wheel channel did exactly this on a
rem real run) and still leave python.exe sitting there, which would make
rem every future run wrongly call it "already installed" and never retry.
rem So the real check is whether torch AND BiRefNet's own remote-code
rem dependencies (einops, kornia, timm) actually import -- checking torch
rem alone once looked sufficient right up until a real Process click failed
rem deep in the matting worker because those three were still missing.
set "TORCH_OK=0"
if exist ".venv-torch\Scripts\python.exe" (
    ".venv-torch\Scripts\python.exe" -c "import torch, einops, kornia, timm" >nul 2>&1
    if not errorlevel 1 set "TORCH_OK=1"
)

if "%TORCH_OK%"=="0" (
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

if not exist "%USERPROFILE%\Desktop\Dress Studio.lnk" (
    echo.
    echo Creating desktop shortcuts and an uninstall entry ...
    rem Windows shortcuts (.lnk) have no supported way to add a custom
    rem entry to their own right-click menu without a system-wide registry
    rem change affecting every .lnk on the machine -- too broad an edit for
    rem what this needs. The standard equivalent instead: a second, clearly
    rem labelled desktop shortcut for uninstalling, plus a real entry under
    rem Windows Settings > Apps (the normal place Windows users already look
    rem to uninstall something), both pointing at Uninstall.bat.
    > "%TEMP%\dressstudio_shortcut.ps1" (
        echo $ws = New-Object -ComObject WScript.Shell
        echo $s = $ws.CreateShortcut^("$env:USERPROFILE\Desktop\Dress Studio.lnk"^)
        echo $s.TargetPath = "%SELF_PATH%"
        echo $s.WorkingDirectory = "%SELF_DIR%"
        echo $s.IconLocation = "imageres.dll,174"
        echo $s.Save^(^)
        echo $u = $ws.CreateShortcut^("$env:USERPROFILE\Desktop\Uninstall Dress Studio.lnk"^)
        echo $u.TargetPath = "%APP_DIR%\Uninstall.bat"
        echo $u.WorkingDirectory = "%APP_DIR%"
        echo $u.IconLocation = "imageres.dll,110"
        echo $u.Save^(^)
        echo $p = $ws.CreateShortcut^("$env:USERPROFILE\Desktop\Stop Dress Studio.lnk"^)
        echo $p.TargetPath = "%APP_DIR%\StopDressStudio.bat"
        echo $p.WorkingDirectory = "%APP_DIR%"
        echo $p.IconLocation = "imageres.dll,109"
        echo $p.Save^(^)
        echo $regKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DressStudio'
        echo New-Item -Path $regKey -Force ^| Out-Null
        echo Set-ItemProperty -Path $regKey -Name DisplayName -Value 'Dress Studio'
        echo Set-ItemProperty -Path $regKey -Name UninstallString -Value '"%APP_DIR%\Uninstall.bat"'
        echo Set-ItemProperty -Path $regKey -Name Publisher -Value 'Dress Studio'
        echo Set-ItemProperty -Path $regKey -Name NoModify -Value 1
        echo Set-ItemProperty -Path $regKey -Name NoRepair -Value 1
    )
    powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\dressstudio_shortcut.ps1"
    del "%TEMP%\dressstudio_shortcut.ps1" >nul 2>&1
    echo Shortcuts created -- "Dress Studio" to launch, "Stop Dress Studio" to
    echo quit it, "Uninstall Dress Studio" to remove it. It also now appears
    echo under Windows Settings ^> Apps if you'd rather uninstall from there.
)

echo.
echo Starting Dress Studio in the background ...
rem Launched detached and hidden, not in this window -- closing this
rem window (or the desktop shortcut re-launching it) no longer stops the
rem app, which was reported directly as confusing ("close terminal, app
rem stops working"). run.ps1 itself is unchanged and still runs
rem foreground when called directly (a developer debugging it wants to see
rem its output and have Ctrl+C work); this only changes how the *launcher*
rem starts it. The server's lifetime is now controlled by StopDressStudio.bat
rem instead of a window close -- there is no window to close any more.
rem Verified this detaches for real before relying on it: a disposable test
rem process outlived its own launching .bat by design, confirmed by a
rem delayed file write happening after the launcher had already exited.
rem DRESSAUG_AUTO_SHUTDOWN, set here and inherited by the detached child
rem below (Windows processes inherit their parent's environment block by
rem default -- no extra plumbing needed): tells ui.py to also stop itself
rem automatically a short while after every browser tab showing it is
rem closed, on top of the "Stop Dress Studio" shortcut. Only set for this
rem packaged launch path, not for `run.ps1`/`python -m dressaug.ui` run
rem directly -- see ui.py's own comment on `_AUTO_SHUTDOWN` for why a
rem plain development run must not have this.
> "%TEMP%\dressstudio_launch.ps1" (
    echo $env:DRESSAUG_AUTO_SHUTDOWN = "1"
    echo Start-Process powershell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\run.ps1"' -WindowStyle Hidden
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\dressstudio_launch.ps1"
del "%TEMP%\dressstudio_launch.ps1" >nul 2>&1
echo Your browser will open automatically in a few seconds, once the server
echo actually answers. Dress Studio keeps running after you close this
echo window, and stops on its own as soon as you close the browser tab it's
echo showing in -- or use the "Stop Dress Studio" shortcut any time before
echo that.
echo.
pause
goto :eof

:fail
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
