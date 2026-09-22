@echo off
setlocal enabledelayedexpansion

rem Dress Studio -- uninstall. Lives at the project root (not gitignored) so
rem every machine that has the app also has a matching uninstaller, kept up
rem to date by the same `git pull` DressStudioSetup.bat already does. Reached
rem via the "Uninstall Dress Studio" desktop shortcut, or Windows Settings ->
rem Apps -> Dress Studio -> Uninstall (both created by DressStudioSetup.bat).

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

echo ==================================================================
echo  Dress Studio -- uninstall
echo ==================================================================
echo.
echo This removes the installed app environment and AI models from this
echo machine (frees several GB of disk space), the desktop shortcuts, and
echo the entry under Windows Settings ^> Apps. Your saved backdrop photos
echo and any processed images are NOT touched by this step.
echo.
rem `choice`, not a second `set /p` -- a script with two `set /p` prompts
rem reading from a non-live-console stdin can silently drop the second
rem one (a real, documented cmd.exe quirk, not a hypothetical), and the
rem second prompt below gates an irreversible delete. Proven by testing
rem this exact script with piped input before trusting it: with two
rem `set /p` calls, the second read back empty every time; with `choice`
rem here instead, leaving exactly one `set /p` in the whole script, the
rem later DELETE confirmation reads correctly.
choice /c YN /n /m "Continue? [Y/N] "
if errorlevel 2 (
    echo Cancelled -- nothing was changed.
    pause
    exit /b 0
)

echo.
echo Stopping Dress Studio if it's currently running ...
rem A running server holds every .dll/.pyd it loaded open, and Windows
rem won't delete a file a process still has open -- found on a real run:
rem rmdir hit "Access is denied" on dozens of files (torch, numpy, pandas,
rem pyarrow's native extensions, and python.exe itself) because the app
rem was still running when uninstall started. run.ps1 already stops a
rem stale server before starting one; this needs the same step before
rem deleting, not after finding out the hard way.
> "%TEMP%\dressstudio_stop_server.ps1" (
    echo Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue ^|
    echo     Where-Object { $_.CommandLine -match 'dressaug\.ui' } ^|
    echo     ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    echo Start-Sleep -Milliseconds 800
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\dressstudio_stop_server.ps1"
del "%TEMP%\dressstudio_stop_server.ps1" >nul 2>&1

echo Removing installed environments ...
if exist "%APP_DIR%\.venv" rmdir /s /q "%APP_DIR%\.venv"
if exist "%APP_DIR%\.venv-torch" rmdir /s /q "%APP_DIR%\.venv-torch"
if exist "%APP_DIR%\.venv" (
    echo WARNING: some files in .venv could not be removed -- Dress Studio
    echo may still be running, or another program has a file open. Close
    echo it and run this uninstaller again.
)

echo Removing desktop shortcuts ...
del "%USERPROFILE%\Desktop\Dress Studio.lnk" >nul 2>&1
del "%USERPROFILE%\Desktop\Uninstall Dress Studio.lnk" >nul 2>&1

echo Removing the Windows Settings ^> Apps entry ...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DressStudio" /f >nul 2>&1

echo.
echo Done -- the app environment, AI models, and shortcuts are removed.
echo.
echo Your code checkout, saved backdrop photos, and processed images are
echo still here at:
echo     %APP_DIR%
echo.
set /p DELETE_ALL=Also PERMANENTLY delete that whole folder -- including saved backdrop photos and processed images? Type DELETE to confirm, anything else to keep it:
echo ^(you typed: "%DELETE_ALL%"^)
if /i "%DELETE_ALL%"=="DELETE" (
    echo.
    echo Deleting "%APP_DIR%" in a couple of seconds -- this window will close.
    rem Deleting this script's own folder while it's still running from
    rem inside it is unreliable (cmd.exe can lose track of the batch file
    rem mid-execution). A detached helper script that waits for this one to
    rem fully exit first, then deletes, avoids that -- written to a temp
    rem file rather than nested inline (a path with spaces inside a nested
    rem "start ... cmd /c "..."" is exactly the kind of quoting that broke
    rem this project's setup script once already; a single-level quoted
    rem path in its own file has no such nesting to get wrong).
    > "%TEMP%\dressstudio_finish_uninstall.bat" (
        echo @echo off
        echo timeout /t 2 /nobreak ^>nul
        echo rmdir /s /q "%APP_DIR%"
    )
    start "" cmd /c "%TEMP%\dressstudio_finish_uninstall.bat"
    exit /b 0
) else (
    echo Keeping "%APP_DIR%" -- nothing in it was touched. Delete it
    echo yourself later, or run this uninstaller again, if you change your
    echo mind.
)
echo.
pause
