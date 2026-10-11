@echo off
setlocal
cd /d "%~dp0"

set "PY=python"
if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PY=%LOCALAPPDATA%\Python\bin\python.exe"

"%PY%" main.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to start game music player.
    echo Please make sure Python 3.8+ is installed and dependencies are installed via:
    echo     pip install -r requirements.txt
    echo.
    pause
)
endlocal
