@echo off
chcp 65001 >nul
title 综测提醒 - 安装开机自启（静默模式）
cd /d "%~dp0"

echo ============================================
echo   安装开机自启（静默运行）
echo ============================================
echo.
echo 说明：
echo   - 用 pythonw.exe 启动，开机不显示任何终端窗口
echo   - 只在右下角托盘区出现一个小图标
echo   - 右键点托盘图标可看状态、开日志、退出
echo.
echo 只在「启动」文件夹添加一个快捷方式，不改动任何系统设置。
echo.
set /p CONFIRM=确认安装吗？(Y/N):
if /i not "%CONFIRM%"=="Y" (
    echo 已取消，未做任何改动。
    pause
    exit /b 0
)
echo.
if exist "C:\Python\python.exe" (
    "C:\Python\python.exe" startup.py install
) else (
    python startup.py install
)
echo.
pause
