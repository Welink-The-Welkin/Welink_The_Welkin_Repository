@rem 本文件由 codex 辅助生成（外围模块）
@echo off
echo Starting game from "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
    echo.
    echo Startup failed. Review the error above.
    pause
)
