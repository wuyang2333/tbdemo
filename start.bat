@echo off
cd /d "%~dp0"
rem 后端守护：循环自检 8008 健康检查，掉了自动重启（脚本内置互斥，不会重复启动）
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0watchdog.ps1" -Loop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0service.ps1" -Action start -OpenBrowser
if errorlevel 1 pause
