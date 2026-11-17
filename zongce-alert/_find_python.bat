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
rem
rem  为什么必须验证 pystray：
rem    实测踩过——机器上同时存在多个 Python，PATH 里排第一的
rem    （如 WorkBuddy / conda / IDE 自带的）能 import tkinter 却**没有 pystray**，
rem    于是托盘起不来、程序静默退出。只验证 tkinter 是不够的。
rem    tkinter 管弹窗，pystray 管托盘，两个都得有。
rem ============================================================

set PY=

rem --- 1. PATH 里的 python：必须同时具备 tkinter 和 pystray ---
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import tkinter, pystray" >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%i in ('where python') do (
            if not defined PY (
                "%%i" -c "import tkinter, pystray" >nul 2>&1
                if not errorlevel 1 set "PY=%%i"
            )
        )
    )
)

rem --- 2. py launcher：Windows 官方安装器会装，排在 PATH 假货之后是因为
rem        很多工具会把自带的 python 塞到 PATH 最前面 ---
if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -c "import tkinter, pystray" >nul 2>&1
        if not errorlevel 1 (
            for /f "delims=" %%i in ('py -c "import sys; print(sys.executable)"') do (
                if not defined PY set "PY=%%i"
            )
        )
    )
)

rem --- 3. 常见安装位置兜底（含作者的 C:\Python）---
if not defined PY (
    for %%d in (
        "C:\Python"
        "%LOCALAPPDATA%\Programs\Python\Python313"
        "%LOCALAPPDATA%\Programs\Python\Python312"
        "%LOCALAPPDATA%\Programs\Python\Python311"
        "%LOCALAPPDATA%\Programs\Python\Python310"
        "%ProgramFiles%\Python313"
        "%ProgramFiles%\Python312"
        "%ProgramFiles%\Python311"
    ) do (
        if not defined PY if exist "%%~d\python.exe" (
            "%%~d\python.exe" -c "import tkinter, pystray" >nul 2>&1
            if not errorlevel 1 set "PY=%%~d\python.exe"
        )
    )
)

if not defined PY (
    echo [错误] 找不到可用的 Python。
    echo.
    echo 需要 3.10+，并且同时装有 tkinter 和 pystray。
    echo.
    echo 如果你确认装过 Python，问题多半是 PATH 里排第一的那个
    echo 是别的软件自带的（WorkBuddy、conda、IDE 等），缺依赖。
    echo.
    echo 两个办法任选：
    echo   A. 给那个 Python 补依赖：
    echo        python -m pip install pystray pillow
    echo   B. 用你正式安装的 Python（推荐）：
    echo        py -m pip install pystray pillow
    echo.
    echo 装好后关掉这个窗口，重新双击本脚本。
    exit /b 1
)

exit /b 0
