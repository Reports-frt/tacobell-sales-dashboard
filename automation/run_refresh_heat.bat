@echo off
REM ============================================================
REM Evening Weather Refresh — ΜΟΝΟ το μπλοκ `heat` του data.json
REM Trigger: Windows Task Scheduler, 1x ημερησιως το βραδυ
REM
REM ΓΙΑΤΙ: το tmax της ΤΡΕΧΟΥΣΑΣ ημερας ειναι προσωρινο οταν τρεχει
REM το πρωινο pipeline (11:05 / 12:00). Μετρημενο 08/08/2026:
REM   13:27 -> ΓΛΥΦΑΔΑ 36,8 (καμια σημανση) · αργοτερα -> 37,3 (ban)
REM Αν δεν αλλαξει τιποτα, το script ΔΕΝ κανει ουτε commit ουτε deploy.
REM
REM Log: _work\refresh_heat.log
REM ============================================================

cd /d "%~dp0.."

pythonw.exe "%~dp0refresh_heat.py"

exit /b %ERRORLEVEL%
