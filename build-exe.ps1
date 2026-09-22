# Builds DressStudioSetup.exe from DressStudioSetup.ps1. Run this once
# whenever DressStudioSetup.ps1 changes, then hand the resulting .exe to a
# colleague directly (email/drive/chat) -- it's gitignored, not committed,
# see .gitignore for why.
#
#   powershell -ExecutionPolicy Bypass -File build-exe.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Get-Module -ListAvailable -Name ps2exe)) {
    Write-Host "Installing ps2exe (one-time, converts .ps1 to .exe) ..."
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser | Out-Null
    Install-Module -Name ps2exe -Scope CurrentUser -Force -AllowClobber
}
Import-Module ps2exe

Invoke-ps2exe -inputFile ".\DressStudioSetup.ps1" -outputFile ".\DressStudioSetup.exe" `
    -title "Dress Studio Setup" -noConsole:$false

Write-Host ""
Write-Host "Built DressStudioSetup.exe -- hand this single file to a colleague."
Write-Host "Double-clicking it downloads the app, installs it (GPU auto-detected),"
Write-Host "and opens it in their browser. Safe to double-click again later too --"
Write-Host "it just opens the already-installed app."
