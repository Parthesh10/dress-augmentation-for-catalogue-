# Dress Studio -- everyday launcher.
#
# Double-click-able: right-click this file -> "Run with PowerShell", or from
# a terminal:  powershell -ExecutionPolicy Bypass -File run.ps1
#
# Starts exactly one server and opens it in the default browser. If a Dress
# Studio server from an earlier session is still running (the app was closed
# by closing the terminal window rather than Ctrl+C, the most common way to
# end up with a stale one), this stops it first -- editing the code and then
# looking at a browser tab still pointed at the old process is the single
# most confusing way this app can seem broken, because every fix looks like
# it did nothing.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Error "No .venv found. Run install.ps1 first."
    exit 1
}

$stale = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'dressaug\.ui' }
foreach ($p in $stale) {
    Write-Host "Stopping an already-running Dress Studio server (PID $($p.ProcessId)) ..."
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($stale) { Start-Sleep -Seconds 1 }

$env:PYTHONPATH = "src"
Write-Host "Starting Dress Studio -- http://127.0.0.1:7860"

# Opens the browser once the server actually answers, rather than
# immediately (Gradio takes a few seconds to build -- an immediate open
# just shows "can't reach this page" and needs a manual refresh).
Start-Job -ScriptBlock {
    param($url)
    for ($i = 0; $i -lt 30; $i++) {
        try {
            if ((Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200) {
                Start-Process $url
                return
            }
        } catch { Start-Sleep -Seconds 1 }
    }
} -ArgumentList "http://127.0.0.1:7860" | Out-Null

# Foreground on purpose: closing this window (or Ctrl+C) stops the server,
# which is what keeps a stale instance from accumulating in the first place.
& ".venv\Scripts\python.exe" -m dressaug.ui
