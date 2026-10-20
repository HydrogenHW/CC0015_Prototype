@echo off
rem ---------------------------------------------------------------
rem  This file is intentionally ASCII-only. cmd.exe parses .bat in
rem  the system code page, so UTF-8 Chinese here corrupts command
rem  lines. All user-facing Chinese lives in README and app logs.
rem ---------------------------------------------------------------
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

set "PY=python"
python --version >nul 2>nul
if not errorlevel 1 goto have_python

set "PYHOME=%LOCALAPPDATA%\Programs\Python\Python313"
if not exist "%PYHOME%\python.exe" goto no_python
set "PATH=%PYHOME%;%PATH%"
set "PY=%PYHOME%\python.exe"
"%PY%" --version >nul 2>nul
if errorlevel 1 goto no_python
goto have_python

:no_python
echo.
echo   Python not found.
echo   Run  .setup\install_python.py  first,
echo   or install Python 3.10+ from python.org
echo.
pause
exit /b 1

:have_python
if not exist .venv (
    echo   Creating virtual environment...
    "%PY%" -m venv .venv
    if errorlevel 1 (
        echo   Failed to create venv.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

if not exist .venv\.deps_ok (
    echo   Installing dependencies, first run takes a few minutes...
    python -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo   Dependency install failed. Check your network.
        pause
        exit /b 1
    )
    type nul > .venv\.deps_ok
)

if not exist .env (
    echo.
    echo   No .env file yet:
    echo     with keys : copy .env.example to .env and fill in both keys
    echo     just demo : put MOCK=1 in .env
    echo.
)

echo.
echo   Starting on http://127.0.0.1:8000   (close this window to stop)
echo.

start "" http://127.0.0.1:8000
python -m uvicorn app.server:app --host 127.0.0.1 --port 8000

pause
