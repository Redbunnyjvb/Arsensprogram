@echo off
REM Start the ARsens project-authoring tool (GUI). Double-click me.
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 main.py %*
) else (
    python main.py %*
)

if errorlevel 1 (
    echo.
    echo De tool sloot af met een fout. Heb je Python 3 geinstalleerd?
    echo Voor Excel/pakket-functies: pip install -r requirements.txt
    pause
)
