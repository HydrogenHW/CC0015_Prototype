@echo off
rem  ASCII-only on purpose: cmd.exe parses .bat in the system code page,
rem  so UTF-8 Chinese here would corrupt command lines.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

rem ---- find python ----
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
rem ---- first run: virtualenv + dependencies ----
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

echo.
echo   Starting on http://127.0.0.1:8000
echo   The browser opens by itself in a few seconds.
echo   Close this window to stop the service.
echo.

rem  Delay the browser a few seconds: opening it first would just show
rem  "can't reach this site" while uvicorn is still booting.
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 6; Start-Process 'http://127.0.0.1:8000'"

python -m uvicorn app.server:app --host 127.0.0.1 --port 8000

pause
