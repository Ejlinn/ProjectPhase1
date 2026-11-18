@echo off
rem One-time setup: creates the virtual environment, installs packages,
rem loads TRACI factors, and trains the CO2 models. Run again only after
rem requirements.txt changes or if you delete the venv folder.
cd /d "%~dp0"
echo ========================================
echo epaData setup
echo ========================================

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 goto :fail
)

call venv\Scripts\activate
if errorlevel 1 goto :fail

echo Installing packages from requirements.txt...
pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Loading TRACI impact factors...
python importtraci.py
if errorlevel 1 goto :fail

echo Training the CO2 models, one per state. This can take a few minutes when the daily CAMPD data is loaded...
python train_model.py
if errorlevel 1 echo Model training was skipped. It needs daily CAMPD data: run python scripts\fetch_campd_hourly.py first ^(needs EPA_API_KEY in .env^), then python train_model.py.

echo.
echo Setup finished. Start the app with run_app.bat.
pause
exit /b 0

:fail
echo.
echo Setup stopped with an error. Read the message above.
pause
exit /b 1
