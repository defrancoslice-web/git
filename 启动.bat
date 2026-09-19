@echo off
setlocal
cd /d "%~dp0"
title 灾情分析平台 · 启动器

echo.
echo   ==============================================================
echo    自然灾害灾情数据自动化综合分析辅助决策支撑平台
echo    Beta 0.5.1
echo   ==============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo   [错误] 没有找到 Python。
    echo.
    echo   请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/
    echo   安装时务必勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)

echo   [1/4] 检查依赖库...
python -c "import pandas, numpy, matplotlib, openpyxl, docx, reportlab" >nul 2>nul
if errorlevel 1 (
    echo         缺少依赖，正在自动安装（首次运行需联网，约 1-3 分钟）...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [错误] 依赖安装失败。请检查网络后重试。
        echo.
        pause
        exit /b 1
    )
)
echo         通过。

echo   [2/4] 检查平台是否已在运行...
powershell -NoProfile -Command "try{$r=Invoke-RestMethod 'http://127.0.0.1:8000/api/state' -TimeoutSec 3; exit 0}catch{}; exit 1" >nul 2>nul
if not errorlevel 1 (
    echo         平台已在运行，直接为你打开浏览器。
    start "" http://127.0.0.1:8000
    timeout /t 2 >nul
    exit /b 0
)

echo   [3/4] 启动服务并预加载数据...
echo         服务运行在最小化窗口「灾情分析平台 服务」中。
start "灾情分析平台 服务" /min cmd /c "python -u -m disaster_agent.cli serve --port 8000 --autorun"

echo   [4/4] 等待平台就绪（首次约 15 秒）...
powershell -NoProfile -Command "$up=$false;for($i=0;$i -lt 40;$i++){try{$c=New-Object Net.Sockets.TcpClient;$t=$c.ConnectAsync('127.0.0.1',8000);if($t.Wait(600)){$up=$true};$c.Close()}catch{};if($up){break};Start-Sleep -Milliseconds 500};if(-not $up){exit 1};$loaded=$false;for($i=0;$i -lt 30;$i++){try{$r=Invoke-RestMethod 'http://127.0.0.1:8000/api/state' -TimeoutSec 2;if($r.charts.Count -gt 0){$loaded=$true;break}}catch{};Start-Sleep -Milliseconds 500};if($loaded){exit 0}else{exit 2}" >nul 2>nul
set PROBE=%errorlevel%

if "%PROBE%"=="0" goto ready
if "%PROBE%"=="2" goto nodata

echo.
echo   [错误] 平台未能在预期时间内启动。
echo         请还原最小化窗口「灾情分析平台 服务」查看错误信息，
echo         或运行  自检.bat  检查环境。
echo.
pause
exit /b 1

:nodata
echo.
echo   [警告] 服务已启动，但预分析没有产出结果。
echo         页面打开后请手动点「加载示例数据」，再点「一键分析」。
echo.
start "" http://127.0.0.1:8000
timeout /t 8 >nul
exit /b 0

:ready
start "" http://127.0.0.1:8000
echo.
echo   ==============================================================
echo    平台已就绪，浏览器即将打开
echo.
echo    访问地址： http://127.0.0.1:8000
echo    示例数据与完整分析结果已经预先加载好了
echo.
echo    停止平台：双击  停止.bat
echo   ==============================================================
echo.
timeout /t 5 >nul
exit /b 0

