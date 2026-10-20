@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    where py >nul 2>&1
    if errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        if errorlevel 1 goto python_version_error
        python -m venv venv
    ) else (
        py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        if errorlevel 1 goto python_version_error
        py -3 -m venv venv
    )
    if errorlevel 1 goto setup_error
)

"venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto python_version_error

"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto setup_error

"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_error

"venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto setup_error

if not exist ".env" (
    copy ".env.example" ".env" >nul
    if errorlevel 1 goto setup_error
    echo Created .env from .env.example. Add your API key and model before launching.
) else (
    echo Existing .env preserved.
)

echo.
echo Setup complete. Configure .env, then run agent.bat.
exit /b 0

:python_version_error
echo Python 3.10 or later is required. Install it and run setup.bat again.
exit /b 1

:setup_error
echo Setup failed. Review the error above and run setup.bat again.
exit /b 1
