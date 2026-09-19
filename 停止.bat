@echo off
setlocal
cd /d "%~dp0"
title 灾情分析平台 · 停止

echo.
echo   正在停止灾情分析平台...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop_server.ps1" -Port 8000

echo.
timeout /t 3 >nul
exit /b 0

