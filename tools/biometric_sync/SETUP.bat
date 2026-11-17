@echo off
title Y ERP biometric set-up
cd /d "%~dp0"
rem The every-minute task needs an administrator: ask once (one "Yes" on the Windows prompt), then carry on.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "PY=%~dp0python\python.exe"
if exist "%PY%" goto :run
echo Getting Python for this program - about 11 MB, only the first time ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0get_python.ps1"
if exist "%PY%" goto :run
rem No private copy (older Windows, or no internet): use a Python installed on the computer, if there is one.
for /f "delims=" %%P in ('where python 2^>nul') do (set "PY=%%P" & goto :run)
echo.
echo Could not get Python - see the message above.
pause
exit /b 1
:run
"%PY%" "%~dp0sync.py" --setup
echo.
pause
