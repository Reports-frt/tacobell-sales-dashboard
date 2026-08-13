# -*- coding: utf-8 -*-
"""ΒΡΑΔΙΝΗ ΑΝΑΝΕΩΣΗ ΤΟΥ ΜΠΛΟΚ `heat` — τιποτα αλλο.

ΓΙΑΤΙ ΥΠΑΡΧΕΙ (08/08/2026): το `temperature_2m_max` της ΤΡΕΧΟΥΣΑΣ ημερας ειναι
ΠΡΟΣΩΡΙΝΟ και αναθεωρειται οσο μπαινουν παρατηρησεις. Το ημερησιο pipeline
τρεχει πρωι (11:05 KFC / 12:00 TB), δηλαδη ΠΡΙΝ κορυφωθει η μερα. Μετρημενο:

    13:27  το pipeline ρωτα για ΣΗΜΕΡΑ  ->  ΓΛΥΦΑΔΑ 36,8  ->  ΚΑΜΙΑ σημανση
    14:5x  η μερα εχει κορυφωθει        ->  ΓΛΥΦΑΔΑ 37,3  ->  ban (-6%)

Ολη μερα η οθονη δειχνει λαθος, και το labour tool — που ρωτα το Open-Meteo
ΜΟΝΟ ΤΟΥ τη στιγμη που πατας «⟳ Προβλεψη» — διαφωνει ορατα με το dashboard.

⚠ ΔΕΝ ΕΙΝΑΙ ΜΠΑΓΙΑΤΙΚΟ CACHE. Το `fetch_tmax` ΗΔΗ ξαναζητα τις προσφατες
ημερες σε καθε εκτελεση (`past_days`, και το `store()` γραφει χωρις ορους) —
επαληθευτηκε σε αντιγραφο του cache: 7 εγγραφες αλλαξαν, ΓΛΥΦΑΔΑ 36,8 -> 37,3.
Το θεμα ειναι Η ΩΡΑ, οχι ο μηχανισμος. Γι' αυτο η λυση ειναι δευτερη ΕΚΤΕΛΕΣΗ,
οχι αλλαγη στο cache. ΜΗΝ προσθεσεις «αγνοησε το cache για N ημερες» — θα ειναι
κωδικας που δεν κανει τιποτα.

ΤΙ ΚΑΝΕΙ: ξαναχτιζει ΜΟΝΟ το `data['heat']`, και ΜΟΝΟ αν οντως αλλαξε κατι.
Αν δεν αλλαξε -> ουτε commit ουτε deploy (αλλιως καθε βραδυ ενα κενο commit).

Τρεξε:  python automation\\refresh_heat.py [--dry-run]
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

LOG_FILE = os.path.join(REPO, '_work', 'refresh_heat.log')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

log = logging.getLogger('refresh_heat')
log.setLevel(logging.INFO)
log.propagate = False                       # ΟΧΙ στο root — το update.log ειναι αλλου
_handlers = [logging.FileHandler(LOG_FILE, encoding='utf-8')]
if sys.stdout is not None:          # ⚠ με pythonw.exe το stdout ειναι None
    _handlers.append(logging.StreamHandler(sys.stdout))
for h in _handlers:
    h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    log.addHandler(h)

DRY = '--dry-run' in sys.argv
# Γραψε το data.json τοπικα ΑΛΛΑ μη δημοσιευσεις — για επαληθευση στην οθονη
# πριν φυγει σε 22 καταστηματα.
NO_PUBLISH = '--no-publish' in sys.argv


# ──────────────────────────────── git ────────────────────────────────
def find_git():
    cand = [os.environ.get('GIT_EXE') or '']
    up = os.environ.get('USERPROFILE', '')
    gh = os.path.join(up, 'AppData', 'Local', 'GitHubDesktop')
    if os.path.isdir(gh):
        for e in sorted(os.listdir(gh), reverse=True):
            if e.startswith('app-'):
                cand.append(os.path.join(gh, e, 'resources', 'app', 'git', 'cmd', 'git.exe'))
    cand += [r'C:\Program Files\Git\cmd\git.exe', 'git']
    for c in cand:
        if not c:
            continue
        try:
            subprocess.run([c, '--version'], capture_output=True, timeout=20, check=True)
            return c
        except Exception:
            continue
    raise RuntimeError('δεν βρεθηκε git')


def github_slug(git_exe):
    """`owner/repo` απο το ΙΔΙΟ το remote — οχι αντιγραφη ρυθμισης.

    Ετσι το αρχειο ειναι ΤΑΥΤΟΣΗΜΟ σε KFC και Taco Bell, οπως το heatwave.py.
    """
    r = subprocess.run([git_exe, 'remote', 'get-url', 'origin'], cwd=REPO,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    url = (r.stdout or '').strip()
    if not url:
        raise RuntimeError('κενο remote origin')
    slug = url.split('github.com')[-1].lstrip(':/').removesuffix('.git')
    if slug.count('/') != 1:
        raise RuntimeError('ακαταλαβιστικο remote: %s' % url)
    return slug


# ─────────────────────────── heat block ────────────────────────────
def build(data):
    import heatwave
    store_days = {}
    for r in data['records_st']:
        d = store_days.setdefault(r[1], {})
        p = d.get(r[0]) or (0.0, 0)
        d[r[0]] = (p[0] + r[3], p[1] + r[4])
    return heatwave.build_heat_block(
        data['meta']['stores'],
        os.path.join(REPO, 'index.html'),
        os.path.join(REPO, '_work'),
        data['meta']['first_date'], data['meta']['latest_date'], log,
        store_days=store_days)


def diff_report(old, new, stores):
    """ΤΙ ακριβως αλλαξε — αλλιως η ανανεωση ειναι σιωπηλη και αναποδεικτη."""
    o = (old or {}).get('by_store') or {}
    n = (new or {}).get('by_store') or {}
    rows = []
    for si in sorted(set(o) | set(n), key=lambda x: int(x)):
        od, nd = o.get(si) or {}, n.get(si) or {}
        for ds in sorted(set(od) | set(nd)):
            a, b = od.get(ds), nd.get(ds)
            if a == b:
                continue
            name = stores[int(si)] if int(si) < len(stores) else si
            fmt = lambda v: ('%s %.1fC' % (v[0], v[1])) if v and v[1] is not None else (v[0] if v else '—')
            rows.append('%s %s: %s -> %s' % (name, ds, fmt(a), fmt(b)))
    return rows


# ──────────────────────────────── main ────────────────────────────────
def main():
    log.info('=' * 60)
    log.info('ΒΡΑΔΙΝΗ ΑΝΑΝΕΩΣΗ ΚΑΙΡΟΥ — %s%s', REPO, '  (DRY RUN)' if DRY else '')

    json_path = os.path.join(REPO, 'data.json')
    with open(json_path, encoding='utf-8') as fh:
        data = json.load(fh)
    n_before = len(data.get('records_st') or [])
    log.info('  data.json: %d εγγραφες records_st, latest_date %s',
             n_before, data['meta']['latest_date'])

    old = data.get('heat')
    new = build(data)
    if not new:
        log.error('  build_heat_block γυρισε κενο — ΚΑΜΙΑ αλλαγη')
        return 1

    if json.dumps(old, sort_keys=True) == json.dumps(new, sort_keys=True):
        log.info('  Καμια αλλαγη στον καιρο — ουτε commit ουτε deploy.')
        return 0

    for line in diff_report(old, new, data['meta']['stores']):
        log.info('  ΑΛΛΑΞΕ: %s', line)
    log.info('  through: %s -> %s', (old or {}).get('through'), new.get('through'))

    if DRY:
        log.info('  DRY RUN — δεν γραφτηκε τιποτα.')
        return 0

    # ── γραψιμο: αντιγραφο ασφαλειας -> ατομικη αντικατασταση -> επαληθευση ──
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = os.path.join(REPO, 'data.json.backup-heat-%s' % ts)
    import shutil
    shutil.copy(json_path, backup)
    log.info('  αντιγραφο: %s', os.path.basename(backup))

    data['heat'] = new
    fd, tmp = tempfile.mkstemp(dir=REPO, suffix='.tmp')
    os.close(fd)
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
        # ⚠ ΕΠΑΛΗΘΕΥΣΗ ΠΡΙΝ την αντικατασταση: μισογραμμενο data.json σβηνει
        # 3,5 χρονια πωλησεων. Ο ελεγχος ειναι στο ΝΕΟ αρχειο, οχι στη μνημη.
        with open(tmp, encoding='utf-8') as fh:
            chk = json.load(fh)
        if len(chk.get('records_st') or []) != n_before:
            raise RuntimeError('records_st %d -> %d' % (n_before, len(chk.get('records_st') or [])))
        if chk['meta']['latest_date'] != data['meta']['latest_date']:
            raise RuntimeError('latest_date αλλαξε')
        if not chk.get('heat', {}).get('by_store'):
            raise RuntimeError('κενο heat.by_store')
        os.replace(tmp, json_path)
        log.info('  ✓ γραφτηκε (%d εγγραφες ακεραιες)', len(chk['records_st']))
    except Exception as e:
        log.error('  ΑΠΟΤΥΧΙΑ ΕΓΓΡΑΦΗΣ: %s — το data.json ΔΕΝ αγγιχτηκε', e)
        if os.path.exists(tmp):
            os.remove(tmp)
        return 1

    if NO_PUBLISH:
        log.info('  --no-publish: γραφτηκε ΤΟΠΙΚΑ, χωρις git και χωρις deploy.')
        return 0

    # ── commit (ΧΩΡΙΣ push ακομα) ──
    committed = False
    try:
        git_exe = find_git()
        subprocess.run([git_exe, 'config', 'user.name', 'Auto-Update Bot'], cwd=REPO, check=True)
        subprocess.run([git_exe, 'config', 'user.email', 'auto@kfc.local'], cwd=REPO, check=True)
        subprocess.run([git_exe, 'add', 'data.json'], cwd=REPO, check=True)
        if subprocess.run([git_exe, 'diff', '--cached', '--quiet'], cwd=REPO).returncode == 0:
            log.info('  git: καμια διαφορα — χωρις commit')
        else:
            subprocess.run([git_exe, 'commit', '-m',
                            'Weather refresh: heat block through %s (%s)'
                            % (new.get('through'), datetime.now().strftime('%Y-%m-%d %H:%M'))],
                           cwd=REPO, check=True)
            committed = True
    except Exception as e:
        log.error('  git commit: %s (το data.json ειναι γραμμενο τοπικα)', e)

    # ── Cloudflare Pages — ΠΡΩΤΑ ─────────────────────────────────────────
    # ⚠ Η ΣΕΙΡΑ ΑΛΛΑΞΕ (13/08/2026): το Cloudflare ειναι πλεον η ΠΡΑΓΜΑΤΙΚΗ
    # φιλοξενια — απο εκει διαβαζει και το labour tool. Το git ειναι ιστορικο.
    # Πρωτα φτανει στον χρηστη, μετα καταγραφεται.
    dep = os.path.join(HERE, 'deploy_cf_pages.py')
    if os.path.exists(dep):
        r = subprocess.run([sys.executable, dep], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=900)
        log.info('  deploy_cf_pages: exit %d', r.returncode)
        if r.returncode != 0:
            log.error('    %s', ((r.stdout or '') + (r.stderr or '')).strip()[-500:])
    else:
        log.warning('  δεν βρεθηκε deploy_cf_pages.py')

    # ── git push — ΜΕΤΑ, σε καθρεφτη + (μεχρι 24/08) GitHub ───────────────
    if committed:
        try:
            import git_targets
            git_targets.push_all(REPO, log)
        except Exception as e:
            log.error('  git push: %s (το commit εγινε τοπικα)', e)

    log.info('=== ΤΕΛΟΣ ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
