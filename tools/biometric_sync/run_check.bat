@echo off
rem Looks at the database and the key. Sends nothing.
cd /d "%~dp0"
call build.bat || (pause & exit /b 1)
YerpBiometric.exe --check
pause
