@echo off
setlocal
cd /d "%~dp0"
echo ==================================================
echo   epaData - remove secrets from Git, then push
echo ==================================================
echo.

if not exist ".git" (
    echo ERROR: Put this file in your project folder, next to app.py, then run it again.
    pause
    exit /b 1
)

rem --- Safety check: no API key may be typed directly into app.py -------------
findstr /r /c:"API_KEY *= *[^ ][A-Za-z0-9][A-Za-z0-9]" app.py >nul 2>&1
if not errorlevel 1 (
    echo ERROR: app.py still has an API key typed into the code.
    echo Replace app.py with the updated version from Claude first, then run this again.
    pause
    exit /b 1
)

echo This will REPLACE your local, not-yet-pushed commits with ONE clean commit.
echo Your files and your .env file are NOT changed or deleted.
echo.
set /p OK=Type YES to continue:
if /i not "%OK%"=="YES" (
    echo Cancelled. Nothing was changed.
    pause
    exit /b 0
)

for /f "delims=" %%b in ('git branch --show-current') do set BRANCH=%%b
if "%BRANCH%"=="" (
    echo ERROR: Could not detect the current branch.
    pause
    exit /b 1
)

rem --- Make sure secrets and junk are never tracked again --------------------
call :ensure .env
call :ensure venv/
call :ensure __pycache__/
call :ensure *.db
call :ensure instance/
if not exist ".env.example" (
    >".env.example" echo EPA_API_KEY=your_epa_key_here
    >>".env.example" echo GEMINI_API_KEY=your_gemini_key_here
)

rem --- Rebuild history without the secret ------------------------------------
git fetch origin >nul 2>&1
git rev-parse --verify -q origin/%BRANCH% >nul 2>&1
if errorlevel 1 goto NOREMOTE

:REMOTE
rem GitHub already has this branch: undo local commits but keep the files, then re-commit cleanly.
git reset --soft origin/%BRANCH%
if errorlevel 1 goto FAIL
git rm -r -q --cached --ignore-unmatch .env venv >nul 2>&1
git add .
goto COMMIT

:NOREMOTE
rem Nothing on GitHub yet: start a fresh one-commit history.
git checkout --orphan clean_history
if errorlevel 1 goto FAIL
git rm -r -q --cached -f . >nul 2>&1
git add .
set NEWBRANCH=1

:COMMIT
git commit -m "Add AI search, filters, pagination; keep API keys out of the repo"
if errorlevel 1 goto FAIL
if defined NEWBRANCH (
    git branch -D %BRANCH%
    git branch -m %BRANCH%
)

rem --- Final safety check ----------------------------------------------------
git ls-files --error-unmatch .env >nul 2>&1
if not errorlevel 1 (
    echo ERROR: .env is still tracked by Git. Stopping before the push.
    pause
    exit /b 1
)

echo.
echo Pushing to GitHub...
git push -u origin %BRANCH%
if errorlevel 1 (
    echo.
    echo The push did not go through. Read the message above and send it to Claude.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   SUCCESS - clean code is on GitHub.
echo   Remember: use NEW API keys in your .env file.
echo ==================================================
pause
exit /b 0

:FAIL
echo.
echo Something went wrong. Read the message above and send it to Claude.
pause
exit /b 1

:ensure
findstr /x /c:"%~1" .gitignore >nul 2>&1 || echo %~1>> .gitignore
exit /b 0
