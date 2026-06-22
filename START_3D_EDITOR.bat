@echo off
title ARsens Project Editor (NEW 3D - PySide6 + PyVista)
REM This launches the NEW 3D editor. The old 2D Tkinter tool is start.bat (next to this file).
set "VENV=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV%" (
    echo.
    echo Could not find the virtual environment at:
    echo   %VENV%
    echo.
    pause
    exit /b 1
)
"%VENV%" "%~dp0arsens_project_editor\main.py" %*
if errorlevel 1 (
    echo.
    echo The 3D editor exited with an error ^(see the messages above^).
    echo Copy that text and send it so it can be fixed.
    pause
)
