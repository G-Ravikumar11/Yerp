@echo off
rem Sends what is new once, and shows what happened.
cd /d "%~dp0"
python sync.py --once
pause
