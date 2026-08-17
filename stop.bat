@echo off
title 淘宝运营工作台 - 停止服务
echo ==============================================
echo    正在停止服务...
echo ==============================================

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
)

echo.
echo 服务已停止。
echo.
timeout /t 2 /nobreak >nul
exit
