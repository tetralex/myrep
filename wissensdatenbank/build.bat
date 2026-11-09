@echo off
setlocal
chcp 65001 >nul
title Baue die App ...
cd /d "%~dp0"

echo.
echo  ===  Kaeltetechnik-Wissensdatenbank: .exe bauen  ===
echo.

rem --- Python suchen (3.13 oder 3.12) ---
set "PY="
where py >nul 2>nul && (py -3.13 -c "import sys" >nul 2>nul && set "PY=py -3.13")
if not defined PY (where py >nul 2>nul && (py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"))
if not defined PY (where py >nul 2>nul && set "PY=py -3")
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
    echo [FEHLER] Python wurde nicht gefunden.
    echo Bitte Python 3.13 von https://www.python.org installieren
    echo und beim Setup "Add python.exe to PATH" anhaken.
    if not defined NOPAUSE pause
    exit /b 1
)
echo Verwende: %PY%

rem --- Virtuelle Umgebung ---
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Lege virtuelle Umgebung an ...
    %PY% -m venv .venv || goto :error
) else (
    echo [1/4] Virtuelle Umgebung vorhanden.
)
set "VPY=.venv\Scripts\python.exe"

echo [2/4] Installiere Abhaengigkeiten ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements-dev.txt || goto :error

echo [3/4] Erzeuge Icon ...
"%VPY%" tools\make_icon.py || goto :error

echo [4/4] Baue .exe mit PyInstaller ...
"%VPY%" -m PyInstaller --noconfirm --clean app.spec || goto :error

for /f "usebackq delims=" %%N in (`call "%VPY%" -c "from app.config import EXE_NAME; print(EXE_NAME)"`) do set "EXE=%%N"

echo.
echo  Fertig!  Die App liegt hier:  dist\%EXE%.exe
echo.

rem --- Optional: Installer mit Inno Setup ---
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    for /f "usebackq delims=" %%N in (`call "%VPY%" -c "from app.config import APP_NAME; print(APP_NAME)"`) do set "APPNAME=%%N"
    for /f "usebackq delims=" %%V in (`call "%VPY%" -c "from app.config import APP_VERSION; print(APP_VERSION)"`) do set "APPVER=%%V"
    echo Inno Setup gefunden - baue Installer ...
    "%ISCC%" /DMyAppName="%APPNAME%" /DMyAppVersion="%APPVER%" /DMyAppExeName="%EXE%.exe" installer.iss && echo Installer liegt in: dist\installer
) else (
    echo Tipp: Mit Inno Setup 6 ^(jrsoftware.org^) baut dieses Skript auch einen Installer.
)
echo.
if not defined NOPAUSE pause
exit /b 0

:error
echo.
echo [FEHLER] Da ist etwas schiefgelaufen - siehe Meldungen oben.
if not defined NOPAUSE pause
exit /b 1
