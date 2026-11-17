@echo off
chcp 65001 >nul
title 综测提醒 - 查看状态
cd /d "%~dp0"

if exist "C:\Python\python.exe" (
    "C:\Python\python.exe" check.py
) else (
    python check.py
)
echo.
pause
