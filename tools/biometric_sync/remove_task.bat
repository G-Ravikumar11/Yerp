@echo off
rem Stops the every-minute sync. Run as Administrator.
schtasks /Delete /F /TN "YERP Biometric Sync"
pause
