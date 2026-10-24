@echo off
rem  Pure ASCII on purpose: cmd.exe parses .bat in the system code page.
chcp 65001 >nul
cd /d "%~dp0"

set "SRC=%~dp0start_service.vbs"
set "DST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\CC0015-captions.vbs"

if not exist "%SRC%" (
    echo.
    echo   start_service.vbs not found next to this file.
    echo.
    pause
    exit /b 1
)

copy /Y "%SRC%" "%DST%" >nul
if errorlevel 1 (
    echo.
    echo   Copy failed.
    echo.
    pause
    exit /b 1
)

echo.
echo   Autostart installed.
echo   The caption service now starts silently when you log in.
echo.
echo   To remove it, delete this file:
echo   "%DST%"
echo.
pause
