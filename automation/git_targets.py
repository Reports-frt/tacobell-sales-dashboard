# -*- coding: utf-8 -*-
"""ΠΟΥ ΠΑΕΙ ΤΟ PUSH — ενα σημειο για ολα τα pipelines.

ΓΙΑΤΙ ΥΠΑΡΧΕΙ: το push γινεται απο ΤΡΙΑ scripts ανα repo
(update_dashboard.py, foodcost/build_pipeline.py, refresh_heat.py). Με την
ημερομηνια ληξης γραμμενη τρεις φορες, η αποκλιση ειναι θεμα χρονου — ιδια
παγιδα με το «ΜΙΑ φορμουλα, τρεις καταναλωτες» του forecast.

Η ΑΠΟΦΑΣΗ (13/08/2026): η φιλοξενια περναει στο Cloudflare. Το GitHub μενει
ως δευτερος προορισμος ΜΕΧΡΙ ΚΑΙ τις 24/08/2026 και μετα σταματα μονο του.
Ο ΤΟΠΙΚΟΣ ΚΑΘΡΕΦΤΗΣ ειναι πλεον ο κυριος προορισμος και ΔΕΝ σταματα ποτε.

⚠ ΣΕΙΡΑ: πρωτα ο καθρεφτης, μετα το GitHub. Αν πεσει το GitHub (ή λήξει),
το ιστορικο ειναι ΗΔΗ ασφαλες. Η αντιστροφη σειρα θα αφηνε παραθυρο οπου
μια αποτυχια δικτυου χανει τη μερα.

⚠ ΤΟ ΙΔΙΟ ΑΡΧΕΙΟ ΚΑΙ ΣΤΑ ΔΥΟ REPOS, οπως το heatwave.py. Ο προορισμος
βγαινει απο το ΟΝΟΜΑ του φακελου, οχι απο ρυθμιση που μπορει να αποκλινει.
"""
import datetime
import os
import subprocess

# Τελευταια ημερα που το push παει ΚΑΙ στο GitHub (συμπεριλαμβανεται).
GITHUB_UNTIL = datetime.date(2026, 8, 24)

# Ο τοπικος καθρεφτης. Bare repos: <MIRROR_ROOT>\<ονομα-repo>.git
MIRROR_ROOT = r'C:\Projects\_git-mirror'


def find_git():
    up = os.environ.get('USERPROFILE', '')
    cand = []
    gh = os.path.join(up, 'AppData', 'Local', 'GitHubDesktop')
    if os.path.isdir(gh):
        for e in sorted(os.listdir(gh), reverse=True):
            if e.startswith('app-'):
                cand.append(os.path.join(gh, e, 'resources', 'app', 'git', 'cmd', 'git.exe'))
    cand += [r'C:\Program Files\Git\cmd\git.exe', 'git']
    for c in cand:
        try:
            subprocess.run([c, '--version'], capture_output=True, timeout=20, check=True)
            return c
        except Exception:
            continue
    raise RuntimeError('δεν βρεθηκε git')


def github_open(today=None):
    """Στελνουμε ακομα στο GitHub;"""
    return (today or datetime.date.today()) <= GITHUB_UNTIL


def _run(git, args, cwd, log, timeout=300):
    p = subprocess.run([git] + args, cwd=cwd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=timeout)
    return p


def push_all(repo_path, log, branch='HEAD:main'):
    """Push στον καθρεφτη και (μεχρι τη ληξη) στο GitHub.

    Επιστρεφει dict {'mirror': bool, 'github': bool|None} — None = παραλειφθηκε.
    ΔΕΝ πεταει εξαιρεση: το push ειναι το ΤΕΛΕΥΤΑΙΟ βημα του pipeline και μια
    αποτυχια δικτυου δεν πρεπει να ακυρωσει δεδομενα που ηδη γραφτηκαν και
    ανεβηκαν στο Cloudflare.
    """
    git = find_git()
    name = os.path.basename(repo_path.rstrip('\\/'))
    out = {'mirror': False, 'github': None}

    # ── 1. ΤΟΠΙΚΟΣ ΚΑΘΡΕΦΤΗΣ — παντα, πρωτος ──────────────────────────────
    mirror = os.path.join(MIRROR_ROOT, name + '.git')
    if not os.path.isdir(mirror):
        log.error('  [git] ΔΕΝ ΒΡΕΘΗΚΕ Ο ΚΑΘΡΕΦΤΗΣ: %s — το ιστορικο ΔΕΝ '
                  'προστατευεται. Φτιαξ\' τον με: git clone --mirror', mirror)
    else:
        p = _run(git, ['push', mirror, branch], repo_path, log)
        if p.returncode == 0:
            out['mirror'] = True
            log.info('  [git] καθρεφτης OK -> %s', mirror)
        else:
            log.error('  [git] καθρεφτης ΑΠΕΤΥΧΕ: %s', (p.stderr or p.stdout).strip()[:300])

    # ── 2. GITHUB — μεχρι και τη GITHUB_UNTIL ─────────────────────────────
    today = datetime.date.today()
    if not github_open(today):
        log.info('  [git] GitHub: ΠΑΡΑΛΕΙΠΕΤΑΙ — η φιλοξενια εληξε στις %s '
                 '(σημερα %s). Το Cloudflare ειναι ο μονος προορισμος.',
                 GITHUB_UNTIL.isoformat(), today.isoformat())
        return out

    pat_file = os.path.join(repo_path, '_work', '.github_pat')
    if not os.path.exists(pat_file):
        log.warning('  [git] GitHub: δεν βρεθηκε PAT (%s) — παραλειπεται', pat_file)
        out['github'] = False
        return out
    with open(pat_file, encoding='utf-8') as fh:
        pat = fh.read().strip()

    r = _run(git, ['remote', 'get-url', 'origin'], repo_path, log)
    url = (r.stdout or '').strip()
    slug = url.split('github.com')[-1].lstrip(':/')
    if slug.endswith('.git'):
        slug = slug[:-4]
    if slug.count('/') != 1:
        log.error('  [git] GitHub: ακαταλαβιστικο remote «%s» — παραλειπεται', url)
        out['github'] = False
        return out

    p = _run(git, ['push', 'https://x-access-token:%s@github.com/%s.git' % (pat, slug),
                   branch], repo_path, log)
    msg = ((p.stdout or '') + (p.stderr or '')).replace(pat, '***TOKEN***').strip()
    out['github'] = (p.returncode == 0)
    left = (GITHUB_UNTIL - today).days
    if out['github']:
        log.info('  [git] GitHub OK (απομενουν %d ημερες)  %s', left,
                 msg.splitlines()[-1] if msg else '')
    else:
        log.error('  [git] GitHub ΑΠΕΤΥΧΕ: %s', msg[:300])
    return out
