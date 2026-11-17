@echo off
chcp 65001 >nul
title 综测提醒 - 自检
cd /d "%~dp0"

call "%~dp0_find_python.bat"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

echo 正在发送一条测试提醒...
echo 如果屏幕右下角弹出窗口、并且听到提示音，说明一切正常。
echo.
"%PY%" run.py --test
pause
