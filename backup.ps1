# =============================================================================
# backup.ps1 — Τοπικό snapshot του dashboard, ΕΚΤΟΣ project
# -----------------------------------------------------------------------------
# ΤΟ ΙΔΙΟ ΑΡΧΕΙΟ ΣΕ KFC ΚΑΙ TACO BELL. Δεν έχει τίποτα καρφωτό: βρίσκει μόνο
# του το repo από τη θέση του και ονομάζει τον φάκελο backup από το φάκελό του.
# Αν το αλλάξεις, αντίγραψέ το και στην άλλη αλυσίδα.
#
# ΓΙΑΤΙ ΥΠΑΡΧΕΙ (11/08/2026): τα dashboard είχαν ΕΝΑ επίπεδο προστασίας — το
# GitHub. Αρκεί για «χάλασε ένα αρχείο», ΔΕΝ αρκεί για «χάθηκε ο φάκελος» ή
# «χάλασε το .git», και κυρίως δεν πιάνει ΤΙΠΟΤΑ από όσα ΔΕΝ είναι στο git:
# `_work/` (πηγαία xlsx, caches, logs), `automation/cf_overlay/`,
# `food/daily_archive/`. Αυτά ζουν ΜΟΝΟ σε αυτό το μηχάνημα.
#
# ⚠ ΔΕΝ ΚΑΝΕΙ COMMIT — ΣΚΟΠΙΜΑ, ΚΑΙ ΜΗΝ ΤΟ ΠΡΟΣΘΕΣΕΙΣ.
# Το git αυτών των repo το οδηγεί η ΑΥΤΟΜΑΤΗ ροή (update_dashboard.py 11:05/
# 12:00 και refresh_heat.py 21:00), που κάνει commit ΜΟΝΟ το data.json και
# push. Ένα `git add -A` εδώ θα ρουφούσε:
#   - το `automation/cf_overlay/` που μένει ΕΠΙΤΗΔΕΣ εκτός git (overlay του
#     agent· το GitHub Pages πρέπει να σερβίρει ΧΩΡΙΣ αυτό),
#   - ό,τι έχει στη μέση της δουλειάς του ο bot ή άλλη συνεδρία.
# Το script ΑΝΑΦΕΡΕΙ τι είναι ακαταγόγραφο και προχωράει.
#
# ΧΡΗΣΗ:
#   .\backup.ps1                     -> snapshot μόνο αν άλλαξε κάτι από το τελευταίο
#   .\backup.ps1 -Full               -> επιβάλλει snapshot
#   .\backup.ps1 -Keep 12            -> πόσα zip να κρατηθούν (default 8)
#   .\backup.ps1 -IncludeBackupFiles -> βάλε και τα data.json.backup-* (κανονικά ΟΧΙ)
# =============================================================================

param(
    [switch]$Full,
    [switch]$IncludeBackupFiles,
    [int]$Keep = 8
)

$ErrorActionPreference = 'Stop'
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$name = Split-Path -Leaf $proj
$dest = "C:\Projects\_backups\$name"
# Δευτερόλεπτα ΑΠΑΡΑΙΤΗΤΑ: δύο εκτελέσεις στο ίδιο λεπτό συγκρούονταν στο όνομα.
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'

Set-Location $proj
if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Force -Path $dest | Out-Null }

Write-Host ""
Write-Host "=== BACKUP $name  $stamp ===" -ForegroundColor Cyan
Write-Host "Project : $proj"
Write-Host "Backups : $dest"
Write-Host ""

# --- 1. ΤΙ ΔΕΝ ΕΙΝΑΙ ΣΤΟ GIT (αναφορά, ΟΧΙ commit) ---------------------------
$changes = @(git status --porcelain)
if ($changes.Count -eq 0) {
    Write-Host "GIT: working tree καθαρό." -ForegroundColor DarkGray
} else {
    $mod = @($changes | Where-Object { $_ -notmatch '^\?\?' })
    $unt = @($changes | Where-Object { $_ -match '^\?\?' })
    if ($mod.Count -gt 0) {
        Write-Host "GIT: $($mod.Count) ΤΡΟΠΟΠΟΙΗΜΕΝΑ (δεν γίνονται commit από εδώ):" -ForegroundColor Yellow
        foreach ($c in $mod) { Write-Host "   $($c.Substring(3))" }
    }
    if ($unt.Count -gt 0) {
        Write-Host "GIT: $($unt.Count) ακαταγόγραφα — μπαίνουν ΜΟΝΟ στο zip" -ForegroundColor DarkGray
    }
}

# Το HEAD είναι ο δείκτης του snapshot. Αν το repo δεν έχει commit, σταματάμε:
# snapshot χωρίς σημείο αναφοράς δεν λέει τίποτα.
$head = "$(git rev-parse HEAD)".Trim()
if (-not $head) { throw "δεν βρέθηκε HEAD — είναι git repo;" }

# --- 2. ΧΡΕΙΑΖΕΤΑΙ SNAPSHOT; --------------------------------------------------
$existing = @(Get-ChildItem "$dest\*.zip" -ErrorAction SilentlyContinue)
$headFile = Join-Path $dest '.last_snapshot_head'
$lastHead = ''
if (Test-Path $headFile) { $lastHead = (Get-Content $headFile -Raw).Trim() }

$behind = 0
if ($lastHead -and ($lastHead -ne $head)) {
    # ⚠ ΟΧΙ `2>$null` σε νατίβε εντολή. Στο PowerShell 5.1 η ανακατεύθυνση
    # stderr τυλίγει κάθε γραμμή σε NativeCommandError και με
    # $ErrorActionPreference='Stop' ΤΕΡΜΑΤΙΖΕΙ το script — ακριβώς εκεί που
    # υποτίθεται ότι αντέχει. Το `--verify --quiet` δεν γράφει στο stderr.
    $probe = & git rev-parse --verify --quiet "$lastHead^{commit}"
    if (($LASTEXITCODE -eq 0) -and $probe) {
        $behind = [int]"$(git rev-list --count "$lastHead..HEAD")".Trim()
    }
    $global:LASTEXITCODE = 0
}

$zipReason = ''
if     ($Full)                 { $zipReason = 'ζητήθηκε -Full' }
elseif ($existing.Count -eq 0) { $zipReason = 'δεν υπάρχει κανένα snapshot' }
elseif ($lastHead -ne $head)   {
    if ($behind -gt 0) { $zipReason = "$behind commit χωρίς snapshot" }
    else               { $zipReason = 'το τελευταίο snapshot δεν έχει δείκτη commit' }
}
elseif ($changes.Count -gt 0)  { $zipReason = 'αρχεία εκτός git' }

if (-not $zipReason) {
    Write-Host ""
    Write-Host "ZIP: παραλείπεται — το snapshot είναι στο ίδιο commit ($($head.Substring(0,7)))." -ForegroundColor DarkGray
    Write-Host "     Χρήσιμο -Full για επιβολή." -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "ZIP: λόγος -> $zipReason" -ForegroundColor DarkGray

    $zip = Join-Path $dest "${name}_$stamp.zip"
    $tmp = Join-Path $env:TEMP "dashbak_${name}_$stamp"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null

    # ΤΙ ΜΕΝΕΙ ΕΞΩ ΚΑΙ ΓΙΑΤΙ:
    #  node_modules/.wrangler/__pycache__ -> παράγονται, δεν έχουν αξία
    #  data.json.backup-* + food/backups  -> ΠΛΕΟΝΑΣΜΟΣ. Είναι χρονοσφραγισμένα
    #     αντίγραφα του data.json, που το git το κρατά ΟΛΟΚΛΗΡΟ με ιστορικό.
    #     Μετρημένο στο KFC: 207 MB από 370 MB του φακέλου, δηλαδή τα 56%.
    #  .github_pat -> ΔΙΑΠΙΣΤΕΥΤΗΡΙΟ. Δεν έχει καμία δουλειά μέσα σε 8
    #     κυλιόμενα zip. Στην επαναφορά ξαναγράφεται με το χέρι (δες παρακάτω).
    $xd = @('node_modules', '.wrangler', '__pycache__')
    if (-not $IncludeBackupFiles) { $xd += 'backups' }
    $xf = @('.github_pat')
    if (-not $IncludeBackupFiles) { $xf += 'data.json.backup-*' }

    robocopy $proj $tmp /E /XD @xd /XF @xf /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy απέτυχε (exit $LASTEXITCODE)" }
    $global:LASTEXITCODE = 0

    # ⚠ ΟΧΙ Compress-Archive: παραλείπει ΣΙΩΠΗΛΑ τα ΚΡΥΦΑ στοιχεία, και το .git
    # έχει attribute Hidden στα Windows. Στο labour repo αυτό κόστισε 15
    # snapshots ΧΩΡΙΣ ιστορικό, ενώ το script δήλωνε επιτυχία. Το
    # CreateFromDirectory δεν φιλτράρει τίποτα.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path $zip) { Remove-Item -Force $zip }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $tmp, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    Remove-Item -Recurse -Force $tmp

    # ΕΠΑΛΗΘΕΥΣΗ — χωρίς ιστορικό το snapshot δεν προστατεύει από χαλασμένο
    # .git, που είναι ΟΛΟΣ ο λόγος ύπαρξής του. Καλύτερα να σκάσει τώρα.
    $arch = [System.IO.Compression.ZipFile]::OpenRead($zip)
    $allEntries = $arch.Entries.Count
    $gitEntries = @($arch.Entries | Where-Object {
        $_.FullName -like '.git\*' -or $_.FullName -like '.git/*' }).Count
    $leak = @($arch.Entries | Where-Object { $_.Name -eq '.github_pat' }).Count
    $arch.Dispose()
    if ($gitEntries -eq 0) {
        throw "Το zip ΔΕΝ περιέχει το .git ($allEntries entries) — το ιστορικό δεν προστατεύεται."
    }
    if ($leak -gt 0) {
        Remove-Item -Force $zip
        throw "Το zip περιείχε το .github_pat — διαγράφηκε. Ελεγξε τα /XF."
    }

    # Ο δείκτης γράφεται ΜΟΝΟ μετά την επαλήθευση.
    Set-Content -Path $headFile -Value $head -Encoding ascii

    $mb = [math]::Round((Get-Item $zip).Length / 1MB, 2)
    Write-Host ""
    Write-Host "ZIP: $zip  ($mb MB)" -ForegroundColor Green
    Write-Host "     $allEntries entries, από τα οποία $gitEntries του .git (ιστορικό OK)" -ForegroundColor DarkGray
    Write-Host "     χωρίς διαπιστευτήρια (.github_pat εκτός)" -ForegroundColor DarkGray
    Write-Host "     δείκτης commit: $($head.Substring(0,7))" -ForegroundColor DarkGray
}

# --- 3. Καθαρισμός παλιών ----------------------------------------------------
$all = @(Get-ChildItem "$dest\*.zip" | Sort-Object LastWriteTime -Descending)
if ($all.Count -gt $Keep) {
    foreach ($f in ($all | Select-Object -Skip $Keep)) {
        Remove-Item $f.FullName -Force
        Write-Host "   διαγράφηκε παλιό: $($f.Name)" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Σύνολο snapshots: $((Get-ChildItem "$dest\*.zip").Count) (κρατούνται $Keep)"
Write-Host "Ιστορικό git    : $(git rev-list --count HEAD) commits"
Write-Host ""
Write-Host "ΕΠΑΝΑΦΟΡΑ: αποσυμπίεσε σε καθαρό φάκελο, μετά ξαναγράψε το" -ForegroundColor DarkGray
Write-Host "           _work\.github_pat (δεν αρχειοθετείται) και τρέξε git log." -ForegroundColor DarkGray
Write-Host ""
