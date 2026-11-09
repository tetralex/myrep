@echo off
rem Startet die App direkt aus dem Quellcode (ohne .exe), z. B. zum Testen.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Bitte zuerst build.bat ausfuehren ^(legt die Umgebung an^).
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
