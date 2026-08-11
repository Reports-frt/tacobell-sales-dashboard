# =============================================================================
# ensure_outlook.ps1 — Το Outlook να είναι ΑΝΟΙΧΤΟ ΜΕ ΠΑΡΑΘΥΡΟ πριν τρέξουν
#                      τα pipelines που διαβάζουν email.
# -----------------------------------------------------------------------------
# ΓΙΑΤΙ ΥΠΑΡΧΕΙ — ΜΕΤΡΗΜΕΝΟ 11/08/2026, ΟΧΙ ΕΙΚΑΣΙΑ:
#
# Ο κώδικας των pipelines λέει «το Dispatch ξεκινάει το Outlook αν είναι
# κλειστό». ΙΣΧΥΕΙ, αλλά όχι με τον τρόπο που νομίζεις. Μετρήθηκε με το
# Outlook τερματισμένο:
#
#     πριν το Dispatch : 0 διεργασίες OUTLOOK
#     μετά το Dispatch : 1 διεργασία
#     Explorers        : 0        <- ΚΑΝΕΝΑ ΠΑΡΑΘΥΡΟ
#     SendAndReceive   : 0,1s     <- ασύγχρονο, επιστρέφει αμέσως
#     μετά το script   : Η ΔΙΕΡΓΑΣΙΑ ΠΕΘΑΙΝΕΙ
#
# Δηλαδή ξεκινά ένας ΑΟΡΑΤΟΣ COM server που σβήνει μαζί με το script. ΠΟΤΕ δεν
# τρέχει στο παρασκήνιο, ΠΟΤΕ δεν συγχρονίζεται μόνος του. Κάθε εκτέλεση
# ξεκινά κρύα instance με τοπική cache ΤΟΣΟ ΠΑΛΙΑ όσο η τελευταία φορά που το
# Outlook ήταν ΠΡΑΓΜΑΤΙΚΑ ανοιχτό.
#
# ⚠ ΓΙ' ΑΥΤΟ Η ΑΠΟΤΥΧΙΑ ΕΙΝΑΙ ΣΙΩΠΗΛΗ: αν το Outlook έμεινε ανοιχτό, όλα
# δουλεύουν και το πρόβλημα δεν φαίνεται ποτέ. Μόλις κάποιος το κλείσει (ή
# μετά από restart), τα pipelines διαβάζουν παγωμένη cache και γράφουν παλιά
# νούμερα ΜΕ EXIT 0. Ακριβώς το περιστατικό της 08/08/2026 στις πωλήσεις.
#
# Η ΛΥΣΗ ΠΟΥ ΜΕΤΡΗΘΗΚΕ: ρητό άνοιγμα ΠΑΡΑΘΥΡΟΥ. Τότε η διεργασία ΕΠΙΒΙΩΝΕΙ
# μετά τον τερματισμό του script και το Outlook συγχρονίζεται κανονικά, με
# τον δικό του χρονιστή, όπως όταν το ανοίγει άνθρωπος.
#
# ⚠ ΜΙΑ ΕΡΓΑΣΙΑ, ΟΧΙ ΔΥΟ. Το Outlook είναι ΕΝΑ για όλο το μηχάνημα — δεύτερη
# εργασία για την άλλη αλυσίδα δεν θα έκανε τίποτα. Το αρχείο υπάρχει και στα
# δύο repo για να μη χαθεί, αλλά ο Task Scheduler καλεί ΜΟΝΟ ένα.
#
# ΧΡΗΣΗ:
#   .\ensure_outlook.ps1              -> άνοιξε αν χρειάζεται + συγχρονισμός
#   .\ensure_outlook.ps1 -WaitSec 120 -> πόσο να περιμένει για τα νέα email
#   .\ensure_outlook.ps1 -NoSync      -> μόνο άνοιγμα, χωρίς αναμονή
# =============================================================================

param(
    [int]$WaitSec = 90,
    [switch]$NoSync
)

$ErrorActionPreference = 'Stop'
$log = "C:\Users\IT\Documents\GitHub\kfc-sales-dashboard\_work\ensure_outlook.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Say($msg) {
    $line = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

Say "=== ensure_outlook ==="

# --- 1. Τι τρέχει ΤΩΡΑ -------------------------------------------------------
# ⚠ Η ΔΙΑΚΡΙΣΗ ΕΙΝΑΙ ΤΟ ΠΑΡΑΘΥΡΟ, ΟΧΙ Η ΔΙΕΡΓΑΣΙΑ. Μια instance χωρίς
# MainWindowHandle είναι ο αόρατος COM server: υπάρχει, φαίνεται «ανοιχτό» σε
# όποιον μετρά διεργασίες, και ΔΕΝ συγχρονίζεται.
$procs   = @(Get-Process OUTLOOK -ErrorAction SilentlyContinue)
$withWin = @($procs | Where-Object { $_.MainWindowHandle -ne 0 })

if ($withWin.Count -gt 0) {
    Say ("Το Outlook ειναι ηδη ανοιχτο με παραθυρο (PID {0})" -f ($withWin[0].Id))
} else {
    if ($procs.Count -gt 0) {
        Say ("ΠΡΟΣΟΧΗ: {0} διεργασια OUTLOOK ΧΩΡΙΣ παραθυρο (αορατος COM server) — ανοιγω παραθυρο" -f $procs.Count)
    } else {
        Say "Το Outlook ειναι κλειστο — το ξεκιναω"
    }

    # Το ίδιο το outlook.exe: αν υπάρχει ήδη αόρατη instance, της δίνει UI·
    # αν δεν υπάρχει, ξεκινά κανονική. Και στις δύο περιπτώσεις μένει ζωντανό.
    $exe = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE" -ErrorAction SilentlyContinue).'(default)'
    if (-not $exe -or -not (Test-Path $exe)) { throw "δεν βρεθηκε το OUTLOOK.EXE" }
    Start-Process -FilePath $exe | Out-Null

    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        $w = @(Get-Process OUTLOOK -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 })
        if ($w.Count -gt 0) { $ok = $true; Say ("Ανοιξε σε {0}s (PID {1})" -f (($i+1)*2), $w[0].Id); break }
    }
    if (-not $ok) { throw "Το Outlook δεν εμφανισε παραθυρο μεσα σε 120s" }
}

if ($NoSync) { Say "-NoSync: τελος"; exit 0 }

# --- 2. Συγχρονισμός + αναμονή για ΝΕΑ email ---------------------------------
# ⚠ Το SendAndReceive ειναι ΑΣΥΓΧΡΟΝΟ (μετρημένο: επιστρεφει σε 0,1s). Δεν
# αρκει να το καλεσεις — πρεπει να ΔΕΙΣ οτι ηρθε κατι, αλλιως προχωρας με
# την ιδια παγωμενη cache και νομιζεις οτι συγχρονιστηκες.
try {
    $ol  = New-Object -ComObject Outlook.Application
    $ns  = $ol.GetNamespace("MAPI")
    $inb = $ns.GetDefaultFolder(6)

    function NewestTime {
        $items = $inb.Items
        $items.Sort("[ReceivedTime]", $true)
        $f = $items.GetFirst()
        if ($f) { return [datetime]$f.ReceivedTime } else { return [datetime]'1900-01-01' }
    }

    $before = NewestTime
    Say ("Νεοτερο email πριν: {0}" -f $before)
    $ns.SendAndReceive($false)

    $deadline = (Get-Date).AddSeconds($WaitSec)
    $changed  = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if ((NewestTime) -gt $before) { $changed = $true; break }
    }
    $after = NewestTime
    if ($changed) { Say ("✓ Ηρθαν νεα email — νεοτερο τωρα: {0}" -f $after) }
    else          { Say ("Καμια αλλαγη μεσα σε {0}s — νεοτερο: {1}" -f $WaitSec, $after) }
}
catch {
    # ΔΕΝ σκαμε: το ανοιγμα πετυχε, που ειναι το κυριο. Ο συγχρονισμος θα
    # γινει ουτως ή αλλως απο τον χρονιστη του ιδιου του Outlook.
    Say ("Ο συγχρονισμος δεν ολοκληρωθηκε: {0}" -f $_.Exception.Message)
}

Say "=== τελος ==="
