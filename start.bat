@echo off
title 淘宝运营工作台 - 一键启动
cd /d D:\demo

set "PY_EXE=C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "FE_DIR=D:\demo\frontend"
set "VBS=D:\demo\hidden_launch.vbs"

echo ==============================================
echo    淘宝运营工作台 - 一键启动（后台静默）
echo ==============================================
echo.

REM ---------- 依赖检查 ----------
if not exist "%PY_EXE%" (
    echo [错误] 找不到后端 Python 环境：
    echo   %PY_EXE%
    echo 请先在 WorkBuddy 里安装依赖，或修改本文件顶部的 PY_EXE 路径。
    pause
    exit /b 1
)
if not exist "%FE_DIR%\node_modules" (
    echo [错误] 前端依赖未安装。
    echo 请先在 frontend 目录执行： npm install
    pause
    exit /b 1
)

REM ---------- 日志目录 ----------
if not exist D:\demo\logs mkdir D:\demo\logs

REM ---------- 后端 8000 ----------
netstat -ano 2>nul | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [提示] 8000 端口已在运行，跳过后端启动
) else (
    echo [1/3] 后台启动后端服务  http://localhost:8000
    wscript.exe "%VBS%" backend
)

REM ---------- 前端 5173 ----------
netstat -ano 2>nul | findstr ":5173" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [提示] 5173 端口已在运行，跳过前端启动
) else (
    echo [2/3] 后台启动前端服务  http://localhost:5173
    wscript.exe "%VBS%" frontend
)

echo [3/3] 等待服务就绪，即将打开浏览器...
timeout /t 6 /nobreak >nul
start http://localhost:5173

echo.
echo 启动完成！本窗口即将自动关闭。
echo   前端页面:     http://localhost:5173
echo   后端接口文档: http://localhost:8000/docs
echo   服务日志:     D:\demo\logs\backend.log  /  frontend.log
echo   停止服务:     双击 D:\demo\stop.bat
echo.
timeout /t 4 /nobreak >nul
exit
