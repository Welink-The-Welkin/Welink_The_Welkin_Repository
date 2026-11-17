@echo off
chcp 65001 >nul
title 综测提醒 - 启动
cd /d "%~dp0"

echo ============================================
echo   综测加分活动提醒 - 启动中
echo ============================================
echo.

rem ---- 已经在跑就不重复启动 ----
rem 重复启动会因端口 8765 被占用而失败，堆出一堆僵尸进程。
rem 用临时文件承接 netstat 输出：管道里 findstr 叠两层时
rem errorlevel 的语义容易出岔子，落盘再查最稳。
set "TMPCHK=%TEMP%\zongce_port_%RANDOM%.txt"
netstat -ano >"%TMPCHK%" 2>nul
findstr /C:"127.0.0.1:8765" "%TMPCHK%" | findstr /C:"LISTENING" >"%TMPCHK%.2" 2>nul
set "RUNNING="
for %%A in ("%TMPCHK%.2") do if %%~zA GTR 0 set "RUNNING=1"
del "%TMPCHK%" "%TMPCHK%.2" >nul 2>&1

if defined RUNNING (
    echo [提示] 程序已经在运行了（托盘区应该有图标）。
    echo.
    echo   想确认状态：双击「查看状态.bat」
    echo   想重启    ：右键托盘图标 → 退出，然后重新双击本文件
    echo.
    timeout /t 8 >nul
    exit /b 0
)

call "%~dp0_find_python.bat"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

rem ---- 优先用 pythonw：无控制台窗口，也就没有"窗口关了程序就停"的问题 ----
rem 从 python.exe 推出同目录的 pythonw.exe
set "PYW=%PY:python.exe=pythonw.exe%"
if /i "%PYW%"=="%PY%" set "PYW="
if defined PYW if not exist "%PYW%" set "PYW="

echo 使用解释器: %PY%
if defined PYW echo 后台模式  : 无窗口（%PYW%）
echo.

if defined PYW (
    rem start /b + pythonw：进程脱离本脚本的生命周期。
    rem 关掉本窗口、甚至关掉整个命令行环境都不会影响程序。
    start "" /b "%PYW%" run.py --tray
) else (
    rem 兜底：只有 python.exe 没有 pythonw.exe（极少见）。
    echo [注意] 没找到 pythonw.exe，将用 python.exe 启动，可能残留一个窗口。
    start "" /b "%PY%" run.py --tray
)

rem ---- 等几秒确认真的起来了，别假装成功 ----
timeout /t 4 >nul
netstat -ano >"%TMPCHK%" 2>nul
findstr /C:"127.0.0.1:8765" "%TMPCHK%" | findstr /C:"LISTENING" >"%TMPCHK%.2" 2>nul
set "OK="
for %%A in ("%TMPCHK%.2") do if %%~zA GTR 0 set "OK=1"
del "%TMPCHK%" "%TMPCHK%.2" >nul 2>&1

if not defined OK (
    echo.
    echo ============================================
    echo   [失败] 程序没能启动。
    echo.
    echo   请看 data\alert.log 末尾的报错。
    echo   常见原因：
    echo     1. 端口 8765 被别的程序占用
    echo     2. 选中的 Python 缺 pystray 或 pillow
    echo ============================================
    echo.
    pause
    exit /b 1
)

echo ============================================
echo   已启动，程序在右下角托盘区运行。
echo.
echo   本窗口可以直接关闭，不影响程序。
echo   想退出程序：右键托盘图标 → 退出
echo ============================================
echo.
timeout /t 5 >nul
exit /b 0
