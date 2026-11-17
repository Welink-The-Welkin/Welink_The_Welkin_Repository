@echo off
chcp 65001 >nul
title 综测提醒 - 查看状态
cd /d "%~dp0"

call "%~dp0_find_python.bat"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

"%PY%" check.py
echo.
pause
