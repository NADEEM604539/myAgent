@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

if not exist ".env" (
    echo .env not found. Run setup.bat and configure your API key.
    pause
    exit /b 1
)

call "venv\Scripts\activate.bat"
python frontend\main.py

pause
