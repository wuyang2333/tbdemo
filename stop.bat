@echo off
title �Ա���Ӫ����̨ - ֹͣ����
echo ==============================================
echo    ����ֹͣ����...
echo ==============================================

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8008" ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5178" ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
)

echo.
echo ������ֹͣ��
echo.
timeout /t 2 /nobreak >nul
exit
