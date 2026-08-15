@echo off
REM Double-click this each session. It sets the script policy for the window
REM and activates the dicing venv, then leaves you at an activated prompt.
REM (This is "steps 2 and 3" from the setup notes, in one click.)
powershell.exe -NoExit -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%~dp0'; & '%~dp0venv\Scripts\Activate.ps1'; Write-Host 'dicing venv ready.  Try:  python optiscan.py info' -ForegroundColor Green"
