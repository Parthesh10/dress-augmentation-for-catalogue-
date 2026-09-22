@echo off
rem Dress Studio -- stop. Since DressStudioSetup.bat launches the server
rem detached and hidden (so closing a visible window can't accidentally
rem stop it -- see DressStudioSetup.bat's own comment on this), there's no
rem window to close when you actually want to quit. This is that control.
rem Same process-matching approach as run.ps1's own stale-server cleanup
rem and Uninstall.bat's pre-delete step: match by command line, not by a
rem guessed window title or PID.

echo Stopping Dress Studio ...
> "%TEMP%\dressstudio_stop.ps1" (
    echo $found = $false
    echo Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue ^|
    echo     Where-Object { $_.CommandLine -match 'dressaug\.ui' } ^|
    echo     ForEach-Object { $found = $true; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    echo if ^($found^) { Write-Host "Stopped." } else { Write-Host "Dress Studio wasn't running." }
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\dressstudio_stop.ps1"
del "%TEMP%\dressstudio_stop.ps1" >nul 2>&1
echo.
pause
