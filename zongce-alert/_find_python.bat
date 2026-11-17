@echo off
chcp 65001 >nul
rem ============================================================
rem  解释器探测 —— 被其他 .bat 用 call 引用，不要直接双击运行
rem
rem  成功：设置 PY 为可用的 python.exe 路径
rem  失败：设置 PY 为空，并置 ERRORLEVEL=1
rem
rem  为什么不用 pythonw 跑交互脚本：
rem    pythonw 没有 stdout，自检/查看状态看不到任何输出。
rem    pythonw 只在「安装开机自启」创建快捷方式时才需要。
rem ============================================================

set PY=

rem --- 1. PATH 里的 python，且必须能 import tkinter ---
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import tkinter" >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%i in ('where python') do (
            if not defined PY set "PY=%%i"
        )
    )
)

rem --- 2. py launcher（Windows 官方安装器会装）---
if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -c "import tkinter" >nul 2>&1
        if not errorlevel 1 (
            for /f "delims=" %%i in ('py -c "import sys; print(sys.executable)"') do (
                if not defined PY set "PY=%%i"
            )
        )
    )
)

rem --- 3. 常见安装位置兜底（不含作者私有的 C:\Python）---
if not defined PY (
    for %%d in (
        "%LOCALAPPDATA%\Programs\Python\Python313"
        "%LOCALAPPDATA%\Programs\Python\Python312"
        "%LOCALAPPDATA%\Programs\Python\Python311"
        "%LOCALAPPDATA%\Programs\Python\Python310"
        "%ProgramFiles%\Python313"
        "%ProgramFiles%\Python312"
        "%ProgramFiles%\Python311"
    ) do (
        if not defined PY if exist "%%~d\python.exe" (
            "%%~d\python.exe" -c "import tkinter" >nul 2>&1
            if not errorlevel 1 set "PY=%%~d\python.exe"
        )
    )
)

if not defined PY (
    echo [错误] 找不到可用的 Python（需要 3.10+ 且带 tkinter）
    echo.
    echo 请从 https://www.python.org/downloads/ 安装，安装时勾选：
    echo   [x] Add python.exe to PATH
    echo   [x] tcl/tk and IDLE
    echo.
    echo 装好后关掉这个窗口，重新双击本脚本。
    exit /b 1
)

exit /b 0
