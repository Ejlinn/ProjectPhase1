@echo off
cd /d "%~dp0"
echo ========================================
echo Starting epaData Explorer...
echo ========================================

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate

echo Checking and installing dependencies...
python -m pip install --upgrade pip
if exist requirements.txt (
    pip install -r requirements.txt
) else (
    echo Warning: requirements.txt not found!
)

echo Launching Flask Server...
python app.py
pause