@echo off
rem Looks at the database and the key. Sends nothing.
cd /d "%~dp0"
python sync.py --check
pause
