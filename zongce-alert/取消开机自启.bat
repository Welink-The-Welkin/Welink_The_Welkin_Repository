@echo off
chcp 65001 >nul
title 综测提醒 - 取消开机自启
cd /d "%~dp0"

echo ============================================
echo   取消开机自启
echo ============================================
echo.
set /p CONFIRM=确认取消开机自启吗？(Y/N):
if /i not "%CONFIRM%"=="Y" (
    echo 已取消，未做任何改动。
    pause
    exit /b 0
)

set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

if exist "%STARTUP%\综测提醒.lnk" (
    del "%STARTUP%\综测提醒.lnk"
    echo [完成] 已删除开机自启快捷方式。
) else (
    echo [提示] 没有找到开机自启项，可能本来就没安装。
)
echo.
pause
