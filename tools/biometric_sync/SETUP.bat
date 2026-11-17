@echo off
title Y ERP biometric set-up
cd /d "%~dp0"
rem The every-minute task needs an administrator: ask once (one "Yes" on the Windows prompt), then carry on.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" 2>nul
  if errorlevel 1 (
    echo Right-click SETUP.bat and choose "Run as administrator".
    pause
  )
  exit /b
)
echo Making the program (a few seconds, nothing is downloaded) ...
call "%~dp0build.bat" force
if errorlevel 1 (
  pause
  exit /b 1
)
"%~dp0YerpBiometric.exe" --setup
echo.
pause
