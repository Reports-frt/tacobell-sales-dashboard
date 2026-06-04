@echo off
REM ============================================================
REM Taco Bell Dashboard Daily Auto-Update
REM Trigger: Windows Task Scheduler (1x daily, after KFC pipeline)
REM Runs hidden via pythonw.exe; logs to _work\update.log
REM ============================================================

cd /d "C:\Users\IT\Documents\GitHub\tacobell-sales-dashboard"

REM Use pythonw.exe to suppress console window
pythonw.exe "C:\Users\IT\Documents\GitHub\tacobell-sales-dashboard\automation\update_dashboard.py"

exit /b %ERRORLEVEL%
