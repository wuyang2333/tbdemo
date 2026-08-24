@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0service.ps1" -Action start -OpenBrowser
if errorlevel 1 pause
