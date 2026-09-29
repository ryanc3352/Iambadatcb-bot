@echo off
rem Double-click to start the AI assistant (sets itself up the first time)
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 start.py %*
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python is not installed. Get it from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH" during the install.
        pause
        exit /b 1
    )
    python start.py %*
)
if errorlevel 1 pause
