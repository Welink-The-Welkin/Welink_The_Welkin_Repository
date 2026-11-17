@echo off
chcp 65001 >nul
title 综测提醒 - 主程序（可关闭此窗口，程序在托盘运行）
cd /d "%~dp0"

echo ============================================
echo   综测加分活动提醒 - 启动中
echo ============================================
echo.
echo 程序会启动并在右下角托盘区显示图标。
echo 这个窗口可以最小化，但请别关——关了程序就停了。
echo.
echo   想彻底后台运行（无窗口）：用「安装开机自启.bat」
echo   想退出程序：右键点托盘图标 → 退出
echo.
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 goto use_C_python
python -c "import tkinter" >nul 2>&1
if errorlevel 1 goto use_C_python
set PY=python
goto run

:use_C_python
if exist "C:\Python\python.exe" (
    set PY=C:\Python\python.exe
    goto run
)
echo [错误] 找不到可用的 Python（需要带 tkinter）
echo 请安装 Python 3.10+ 并勾选 tcl/tk 组件。
pause
exit /b 1

:run
echo 使用解释器: %PY%
echo.
"%PY%" run.py --tray
echo.
echo 程序已退出。若异常，请查看 data\alert.log
pause
