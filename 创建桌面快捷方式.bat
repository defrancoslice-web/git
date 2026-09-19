@echo off
setlocal
cd /d "%~dp0"
title 创建桌面快捷方式

echo.
echo   正在为「灾情分析平台」创建桌面快捷方式...

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\create_shortcut.ps1" -Name "灾情分析平台" -Target "%~dp0启动.bat"

echo.
echo   以后在桌面双击「灾情分析平台」即可启动，不必再进文件夹。
echo.
pause

