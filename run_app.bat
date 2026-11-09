@echo off
rem Starts the web app. Run setup.bat first (once).
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
    echo The virtual environment is missing. Run setup.bat first.
    pause
    exit /b 1
)
echo Starting epaData Explorer at http://127.0.0.1:5000
venv\Scripts\python.exe app.py
pause
