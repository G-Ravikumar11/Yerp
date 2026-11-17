@echo off
title Y ERP biometric set-up
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python is not installed on this computer yet.
  echo.
  echo  1. Go to https://www.python.org/downloads/ and download Python 3 for Windows ^(64-bit^).
  echo  2. Run it, and TICK "Add python.exe to PATH" on the first screen.
  echo  3. Then double-click SETUP.bat again.
  echo.
  start https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
python sync.py --setup
echo.
pause
