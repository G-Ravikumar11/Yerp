@echo off
rem Sends what is new once, and shows what happened. To bring in more history: YerpBiometric.exe --backfill 30
cd /d "%~dp0"
call build.bat || (pause & exit /b 1)
YerpBiometric.exe --once
pause
