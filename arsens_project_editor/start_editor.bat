@echo off
REM Start the ARsens Project Editor (PySide6 + PyVista). Double-click me.
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\python.exe" main.py %*
if errorlevel 1 (
    echo.
    echo The editor exited with an error.
    pause
)
