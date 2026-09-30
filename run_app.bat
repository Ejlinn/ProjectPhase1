@echo off
title EPA Data Explorer Quickstart
echo ===================================================
echo Starting epaData Explorer...
echo ===================================================

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate

echo Checking dependencies...
pip install -r requirements.txt

echo Launching Flask Server...
python app.py
pause