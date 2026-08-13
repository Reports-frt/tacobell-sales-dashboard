@echo off
REM ============================================================
REM Taco Bell Dashboard Daily Auto-Update
REM Trigger: Windows Task Scheduler (1x daily)
REM Runs hidden via pythonw.exe; logs to _work\update.log
REM ============================================================

cd /d "C:\Users\IT\Documents\GitHub\tacobell-sales-dashboard"

REM Use pythonw.exe to suppress console window
REM
REM ΑΛΛΑΞΕ 13/08/2026: το deploy_cf_pages.py ΔΕΝ καλειται πια απο εδω. Τρεχει
REM ΜΕΣΑ απο το update_dashboard.py (STEP 5), ΠΡΙΝ το git push, ωστε η σειρα
REM «Cloudflare -> git» να ειναι ρητη και σε ΕΝΑ σημειο. Αν ξαναμπει εδω, το
REM deploy θα γινεται ΔΥΟ φορες σε καθε εκτελεση.
pythonw.exe "C:\Users\IT\Documents\GitHub\tacobell-sales-dashboard\automation\update_dashboard.py"

exit /b %ERRORLEVEL%
