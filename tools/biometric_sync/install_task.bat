@echo off
rem Run this ONCE, as Administrator. It makes a Windows scheduled task that sends new punches every minute,
rem starting by itself when the computer starts - nobody needs to be signed in.
cd /d "%~dp0"
for /f "delims=" %%P in ('where python') do (set "PY=%%P" & goto :found)
echo Python was not found. Install Python 3 from python.org (tick "Add python.exe to PATH") and run this again.
pause
exit /b 1
:found
schtasks /Create /F /TN "YERP Biometric Sync" /SC MINUTE /MO 1 /RU SYSTEM /RL HIGHEST /TR "\"%PY%\" \"%~dp0sync.py\" --once"
if errorlevel 1 (
  echo Could not create the task. Right-click this file and choose "Run as administrator".
) else (
  echo Done. The task "YERP Biometric Sync" now runs every minute. Progress is written to sync.log in this folder.
)
pause
