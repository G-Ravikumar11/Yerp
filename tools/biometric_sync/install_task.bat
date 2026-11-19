@echo off
rem Run this ONCE, as Administrator, if the set-up could not. It makes a Windows scheduled task that sends new punches
rem every minute, starting by itself when the computer starts - nobody needs to be signed in.
cd /d "%~dp0"
call build.bat || (pause & exit /b 1)
schtasks /Create /F /TN "YERP Biometric Sync" /SC MINUTE /MO 1 /RU SYSTEM /RL HIGHEST /TR "\"%~dp0YerpBiometric.exe\" --once --quiet"
if errorlevel 1 (
  echo Could not create the task. Right-click this file and choose "Run as administrator".
) else (
  echo Done. The task "YERP Biometric Sync" now runs every minute. Progress is written to sync.log in this folder.
)
pause
