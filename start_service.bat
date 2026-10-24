@echo off
rem  Pure ASCII on purpose: cmd.exe parses .bat in the system code page,
rem  and UTF-8 Chinese here corrupts command lines.
rem  Started hidden by start_service.vbs, so no console window appears.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found.
    echo Run run.bat once in this folder first.
    pause
    exit /b 1
)

if not exist logs mkdir logs

rem  Two things are both required:
rem    1) use python.exe, not pythonw.exe -- pythonw has no stderr and
rem       uvicorn fails while writing to it, so the server never starts;
rem    2) redirect the output -- the inherited handles of a hidden window
rem       are not usable, and it fails the same way without this.
.venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8000 >> logs\service.log 2>&1
