@echo off
TITLE AI Job Application Agent
COLOR 0A
chcp 65001 >nul
set PYTHONUTF8=1

echo ===================================================
echo     Starting AI Job Application Agent...
echo ===================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.10 or higher from python.org
    pause
    exit /b
)

:: Create virtual environment if it doesn't exist
IF NOT EXIST ".venv" (
    echo [INFO] First time setup: Creating virtual environment...
    python -m venv .venv
)

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Install dependencies
echo [INFO] Checking dependencies...
pip install -r requirements.txt
playwright install chromium

echo.
echo ===================================================
echo     Server is running! 
echo     Do NOT close this black window.
echo ===================================================
echo.

:: Open the browser automatically
timeout /t 2 /nobreak >nul
start http://127.0.0.1:8000

:: Start the FastAPI server
python backend/app/api.py

pause
