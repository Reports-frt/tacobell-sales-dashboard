# -*- coding: utf-8 -*-
"""
ΚΥΜΑ ΚΑΥΣΩΝΑ — χαρακτηρισμός ημερών για το dashboard.

ΤΙ ΜΕΤΡΗΘΗΚΕ (KFC, καταστήματα Αττικής, Ιούν-Σεπ 2023-2026, δεδομένα του ίδιου
του dashboard): σε ημέρα καύσωνα ο τζίρος ΜΕΤΑΤΟΠΙΖΕΤΑΙ, δεν χάνεται.

    ομάδα                ημέρες   13:00-17:00   19:00-23:00
    κανονικές <30C          101      31,1%         44,8%
    ελεγχου 30-35C          215      30,6% -0,5    44,8% +0,0   <- η ζεστη ΜΟΝΗ
    wave (32-37 σε κυμα)     29      30,3% -0,8    45,0% +0,2      της δεν κανει
    ban (>=37C)              40      27,7% -3,4    47,2% +2,4      τιποτα

ΑΙΤΙΑ: κρατική παύση υπαίθριων εργασιών 13:00-17:00 σε καύσωνα, που καλύπτει
τους διανομείς με δίκυκλο (επιτρέπεται κλιματιζόμενο όχημα).

⚠ ΜΟΝΟ ΕΝΔΕΙΞΗ/ΑΝΑΛΥΣΗ — ΠΟΤΕ στην πρόβλεψη τζίρου. Δοκιμάστηκε εκεί με δύο
  διατυπώσεις και ΑΠΟΡΡΙΦΘΗΚΕ: η πρόβλεψη είναι "περσινή ίδια μέρα x momentum"
  και η περσινή μέρα του Ιουλίου ήταν κι αυτή ζεστή, άρα η ζέστη είναι ΗΔΗ μέσα
  στη βάση. Εκτός δείγματος υπερδιόρθωνε (μεροληψία 0,29% -> -1,38%).
  Το ΠΟΣΟ το ξέρει ήδη· την ΩΡΑ όχι.

⚠ ΤΑ ΚΑΤΩΦΛΙΑ ΓΡΑΦΟΝΤΑΙ ΚΑΙ ΣΤΟ labour tool (worker/src/lib/heatwave.js).
  Ίδια παγίδα με το "τρεις καταναλωτές, μία φόρμουλα" της εποχικότητας. Ο
  έλεγχος tools/check_heat_thresholds.py τα συγκρίνει και σκάει αν αποκλίνουν.

⚠ Οι συντεταγμένες ΔΕΝ ξαναγράφονται εδώ — διαβάζονται από το STORE_GEO του
  index.html, που είναι ήδη η πηγή τους (από εκεί βγήκε και η migration 0026
  του labour tool). Κατάστημα χωρίς συντεταγμένες αναφέρεται ΔΥΝΑΤΑ.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
import datetime

# Κατώφλια (°C). ΑΠΟΛΥΤΑ, όχι σχετικά ως προς τον μήνα: το "κορυφαίο 2% του
# μήνα" είναι 18,8°C τον Ιανουάριο και δεν ενοχλεί κανέναν.
HEAT_THRESHOLDS = {'ban': 37, 'warm': 32}

# Ακραία καιρικά πέρα από τη ζέστη. Κατώφλια ημερήσιου αθροίσματος.
WX_THRESHOLDS = {'rain_mm': 12.0, 'snow_cm': 1.0, 'gust_kmh': 70.0}

# ⚠ Η ΣΕΙΡΑ ΜΕΤΡΑΕΙ: μια ημέρα παίρνει ΜΙΑ κατηγορία. Χιόνι > βροχή > ζέστη,
# γιατί το χιόνι είναι το σπανιότερο και το ισχυρότερο.
WX_KIND_ORDER = ['snow', 'rain', 'ban', 'wave']

ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
PAST_DAYS = 92          # όσο δέχεται το forecast API — καλύπτει το κενό του archive

# ⚠ ΤΑ ΙΔΙΑ ΠΕΔΙΑ ΚΑΙ ΣΤΑ ΔΥΟ ΣΚΕΛΗ (archive + forecast). Όταν το forecast
# ζητούσε μόνο τη μέγιστη, το store() έγραφε None στα υπόλοιπα και έσβηνε
# ό,τι είχε φέρει το archive — 79 από 87 πρόσφατες ημέρες χωρίς βροχή.
DAILY_FIELDS = ('temperature_2m_max,temperature_2m_min,rain_sum,'
                'snowfall_sum,wind_gusts_10m_max')
HTTP_TIMEOUT = 90


def read_store_geo(index_html_path, log=None):
    """Συντεταγμένες από το STORE_GEO του index.html — ΜΙΑ πηγή, χωρίς αντιγραφή."""
    with open(index_html_path, encoding='utf-8') as fh:
        src = fh.read()
    start = src.find('const STORE_GEO')
    if start < 0:
        raise RuntimeError('STORE_GEO not found in %s' % index_html_path)
    block = src[start:src.find('\n};', start)]
    geo = {}
    for m in re.finditer(r"'([^']+)'\s*:\s*\{\s*lat:\s*(-?[\d.]+)\s*,\s*lng:\s*(-?[\d.]+)", block):
        geo[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    if log:
        log.info('  [heat] STORE_GEO: %d συντεταγμένες' % len(geo))
    return geo


def _load_cache(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


# ⚠ ΤΟ 503 ΔΕΝ ΕΙΝΑΙ ΘΕΩΡΗΤΙΚΟ — 3 ΣΤΙΣ 10 ΒΡΑΔΙΝΕΣ ΕΚΤΕΛΕΣΕΙΣ (11/08/2026).
# Μετρημένο στα logs ΚΑΙ ΤΩΝ ΔΥΟ αλυσίδων: 08/08, 09/08, 10/08 στις 21:00:03,
# ταυτόχρονα σε KFC και Taco Bell. Το ίδιο αίτημα με το χέρι λίγες ώρες μετά
# περνά κανονικά — δηλαδή είναι ΔΙΑΛΕΙΠΟΝ, όχι λάθος αίτημα.
#
# Γιατί μετράει: η βραδινή εργασία υπάρχει ΜΟΝΟ για να ξαναφέρει τη ΣΗΜΕΡΙΝΗ
# θερμοκρασία αφού κορυφωθεί η μέρα. Όταν το forecast σκέλος πέφτει, η εργασία
# τερματίζει με exit 0 και «καμία αλλαγή» — δηλαδή αποτυγχάνει στη ΜΟΝΗ της
# δουλειά, σιωπηλά. Τρία βράδια στη σειρά, χωρίς να το πάρει κανείς είδηση.
RETRY_DELAYS = (3, 12, 40)      # δευτερόλεπτα· συνολικά < 1 λεπτό


def _fetch(url, params, log=None):
    q = '&'.join('%s=%s' % (k, v) for k, v in params.items())
    last = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            with urllib.request.urlopen(url + '?' + q, timeout=HTTP_TIMEOUT) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            # 4xx (εκτός 429) = λάθος αίτημα — η επανάληψη δεν το φτιάχνει.
            if e.code != 429 and e.code < 500:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        if attempt < len(RETRY_DELAYS):
            d = RETRY_DELAYS[attempt]
            if log:
                log.warning('  [heat] %s — νέα προσπάθεια σε %ds (%d/%d)'
                            % (last, d, attempt + 1, len(RETRY_DELAYS)))
            time.sleep(d)
    raise last


def _as_list(payload):
    """Το Open-Meteo γυρίζει dict για μία τοποθεσία, list για πολλές."""
    return payload if isinstance(payload, list) else [payload]


def fetch_tmax(points, start_date, end_date, cache_path, log=None):
    """{(lat,lng): {ISO ημερομηνία: tmax}} με cache στον δίσκο.

    Το ιστορικό δεν ξαναζητιέται ποτέ. Οι τελευταίες ημέρες έρχονται από το
    forecast API (past_days) γιατί το archive έχει καθυστέρηση ~5 ημερών —
    χωρίς αυτό, η σήμανση θα εμφανιζόταν με καθυστέρηση ακριβώς στις ημέρες
    που ενδιαφέρουν περισσότερο ("γιατί ήταν περίεργη η χθεσινή;").
    """
    cache = _load_cache(cache_path)
    keys = ['%.4f,%.4f' % p for p in points]

    def needs_backfill(k):
        """Λείπει ΤΕΛΕΙΩΣ, ή είναι από παλιότερη έκδοση χωρίς `tmin`;

        ⚠ ΧΩΡΙΣ ΑΥΤΟ ΤΟ ΝΕΟ ΠΕΔΙΟ ΔΕΝ ΕΡΧΕΤΑΙ ΠΟΤΕ ΓΙΑ ΤΟ ΙΣΤΟΡΙΚΟ: το
        archive καλείται μόνο για σημεία που λείπουν ΟΛΟΚΛΗΡΑ, οπότε μια
        γεμάτη cache θα έμενε για πάντα χωρίς την ελάχιστη θερμοκρασία.
        """
        days = cache.get(k)
        if not days:
            return True
        for v in days.values():                 # αρκεί μία εγγραφή για να κριθεί
            return 'tmin' not in v
        return True

    missing = [p for p, k in zip(points, keys) if needs_backfill(k)]
    fresh_from = (datetime.date.fromisoformat(end_date) -
                  datetime.timedelta(days=PAST_DAYS - 2)).isoformat()

    def store(payloads, pts):
        for payload, p in zip(payloads, pts):
            k = '%.4f,%.4f' % p
            d = payload.get('daily') or {}
            slot = cache.setdefault(k, {})
            times = d.get('time') or []
            for i, ds in enumerate(times):
                def g(name, nd=1):
                    arr = d.get(name) or []
                    v = arr[i] if i < len(arr) else None
                    return round(float(v), nd) if v is not None else None
                t = g('temperature_2m_max')
                if t is None:
                    continue
                fresh = {'tmax': t, 'tmin': g('temperature_2m_min'),
                         'rain': g('rain_sum'), 'snow': g('snowfall_sum'),
                         'gust': g('wind_gusts_10m_max', 0)}
                # ⚠ ΣΥΓΧΩΝΕΥΣΗ, ΟΧΙ ΑΝΤΙΚΑΤΑΣΤΑΣΗ. Το σκέλος forecast ζητούσε
                # ΜΟΝΟ `temperature_2m_max` ενώ το store έγραφε ΟΛΑ τα πεδία:
                # τα rain/snow/gust γίνονταν None και ΣΒΗΝΑΝ ό,τι είχε φέρει
                # το archive. ΜΕΤΡΗΜΕΝΟ: 79 από τις τελευταίες 87 ημέρες είχαν
                # `rain: None`, δηλαδή επί ~3 μήνες ΚΑΜΙΑ ημέρα δεν μπορούσε να
                # χαρακτηριστεί βροχή ή χιόνι. Πλέον και τα δύο σκέλη ζητούν τα
                # ΙΔΙΑ πεδία, ΚΑΙ το None δεν σβήνει υπάρχουσα τιμή.
                old = slot.get(ds) or {}
                slot[ds] = {**old, **{kk: vv for kk, vv in fresh.items() if vv is not None}}

    try:
        if missing:                                     # πλήρες ιστορικό, μία φορά
            if log:
                log.info('  [heat] archive: %d τοποθεσίες, %s -> %s' % (len(missing), start_date, end_date))
            store(_as_list(_fetch(ARCHIVE_URL, {
                'latitude': ','.join('%.4f' % p[0] for p in missing),
                'longitude': ','.join('%.4f' % p[1] for p in missing),
                'start_date': start_date, 'end_date': end_date,
                'daily': DAILY_FIELDS,
                'timezone': 'Europe%2FAthens',
            }, log)), missing)
        if log:
            log.info('  [heat] forecast past_days=%d για %d τοποθεσίες' % (PAST_DAYS, len(points)))
        store(_as_list(_fetch(FORECAST_URL, {                # πρόσφατες + πρόβλεψη
            'latitude': ','.join('%.4f' % p[0] for p in points),
            'longitude': ','.join('%.4f' % p[1] for p in points),
            'past_days': PAST_DAYS, 'forecast_days': 7,
            'daily': DAILY_FIELDS, 'timezone': 'Europe%2FAthens',
        }, log)), points)
    except Exception as e:
        if log:
            log.error('  [heat] ΑΠΟΤΥΧΙΑ ΚΑΙΡΟΥ: %s — το dashboard βγαίνει ΧΩΡΙΣ σήμανση '
                      'καύσωνα (τα υπόλοιπα νούμερα δεν επηρεάζονται)' % e)
        if not cache:
            return {}, fresh_from
    try:
        with open(cache_path, 'w', encoding='utf-8') as fh:
            json.dump(cache, fh)
    except Exception:
        pass
    return {p: cache.get('%.4f,%.4f' % p, {}) for p in points}, fresh_from


def _shift(ds, n):
    return (datetime.date.fromisoformat(ds) + datetime.timedelta(n)).isoformat()


def classify_wx(by_date):
    """ISO ημερομηνία -> κατηγορία ακραίου καιρού. Μία κατηγορία ανά ημέρα.

    by_date: {ds: {'tmax','rain','snow','gust'}}
    """
    heat = classify({ds: v.get('tmax') for ds, v in by_date.items()})
    out = {}
    for ds, v in by_date.items():
        if (v.get('snow') or 0) >= WX_THRESHOLDS['snow_cm']:
            out[ds] = 'snow'
        elif (v.get('rain') or 0) >= WX_THRESHOLDS['rain_mm']:
            out[ds] = 'rain'
        elif ds in heat:
            out[ds] = heat[ds]
    return out


def measure_effects(store_days, kind_of, min_n=30, window=28):
    """Πόσο πέφτουν πωλήσεις/συναλλαγές σε κάθε είδος ακραίου καιρού.

    ⚠ ΤΟ ΣΩΣΤΟ ΜΕΤΡΟ ΣΥΓΚΡΙΣΗΣ ΕΙΝΑΙ Η ΙΔΙΑ ΗΜΕΡΑ ΕΒΔΟΜΑΔΑΣ, ΟΧΙ Η ΠΕΡΣΙΝΗ
    ΙΔΙΑ ΗΜΕΡΟΜΗΝΙΑ. Παλιότερη προσέγγιση σύγκρινε τη διαφορά θερμοκρασίας από
    πέρσι και έβγαζε "καμία επίδραση" — επειδή η περσινή μέρα του Ιουλίου ήταν
    κι αυτή ζεστή. Με καθαρή βάση ίδιας ημέρας εβδομάδας (±4 εβδομάδες, ΜΟΝΟ
    κανονικές ημέρες) η επίδραση φαίνεται καθαρά:
        χιόνι  -19,6% πωλήσεις / -23,2% συναλλαγές
        καύσωνας -6,5% / -5,7%   ·  κύμα -2,3% / -2,3%  ·  βροχή -1,8% / -3,6%
        ομάδα ελέγχου (ζέστη 30-35°C χωρίς κύμα): -0,1% / +0,1%

    store_days: {si: {ds: (sales, tcs)}}
    kind_of:    (si, ds) -> κατηγορία ή None
    """
    acc = {}
    for si, days in store_days.items():
        ordered = sorted(days)
        for ds in ordered:
            kind = kind_of(si, ds)
            if not kind:
                continue
            d0 = datetime.date.fromisoformat(ds)
            bs, bt = [], []
            for n in range(-window, window + 1, 7):
                if n == 0:
                    continue
                o = (d0 + datetime.timedelta(n)).isoformat()
                if o in days and not kind_of(si, o):     # η βάση ΠΡΕΠΕΙ να είναι καθαρή
                    bs.append(days[o][0]); bt.append(days[o][1])
            if len(bs) < 3:
                continue
            ms, mt = _median(bs), _median(bt)
            if ms > 0 and mt > 0 and days[ds][0] > 0:
                a = acc.setdefault(kind, {'s': [], 't': []})
                a['s'].append(days[ds][0] / ms - 1)
                a['t'].append(days[ds][1] / mt - 1 if days[ds][1] and mt else 0.0)
    out = {}
    for kind, v in acc.items():
        if len(v['s']) >= min_n:
            # ΔΙΑΜΕΣΟΣ, όχι μέσος όρος: μια κλειστή μέρα ή ένα φεστιβάλ δεν
            # πρέπει να ορίζει τον συντελεστή που θα μπει στην πρόβλεψη.
            out[kind] = {'s': round(_median(v['s']), 4),
                         't': round(_median(v['t']), 4), 'n': len(v['s'])}
    return out


def _median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def classify(tmax_by_date):
    """ISO ημερομηνία -> 'ban' | 'wave'. Μόνο οι ημέρες που επηρεάζονται.

    Ίδιος κανόνας με το classifyHeatDays() του labour tool: >=37 πάντα, και
    32-37 ΜΟΝΟ αν γειτονεύει με >=37. Μετρημένο: μεμονωμένη ζέστη 32-37 δίνει
    delivery +1,7% (n=192)· η ΙΔΙΑ ζώνη μέσα σε κύμα δίνει -2,1% (n=25).
    """
    out = {}
    ban, warm = HEAT_THRESHOLDS['ban'], HEAT_THRESHOLDS['warm']
    for ds, t in tmax_by_date.items():
        if t is None:
            continue
        if t >= ban:
            out[ds] = 'ban'
        elif t >= warm:
            p, n = tmax_by_date.get(_shift(ds, -1)), tmax_by_date.get(_shift(ds, 1))
            if (p is not None and p >= ban) or (n is not None and n >= ban):
                out[ds] = 'wave'
    return out


def build_heat_block(store_order, index_html_path, work_dir, first_date, last_date,
                     log=None, store_days=None):
    """Το μπλοκ `heat` του data.json (ζέστη ΚΑΙ βροχή/χιόνι/άνεμος).

    {thresholds, wx_thresholds, by_store: {si: {date: [kind, tmax, rain, snow]}},
     effects: {kind: {s, t, n}}, through}
    Μόνο οι ΕΠΗΡΕΑΖΟΜΕΝΕΣ ημέρες μπαίνουν — οι υπόλοιπες είναι σιωπή.

    store_days (προαιρετικό): {si: {ds: (sales, tcs)}} για τη ΜΕΤΡΗΣΗ των
    επιδράσεων. Χωρίς αυτό μπαίνει μόνο η σήμανση, καμία διόρθωση πρόβλεψης.
    """
    geo = read_store_geo(index_html_path, log)
    pts, per_store = [], {}
    for i, name in enumerate(store_order):
        g = geo.get(name)
        if not g:
            if log:
                log.error("  [heat] ΧΩΡΙΣ ΣΥΝΤΕΤΑΓΜΕΝΕΣ: '%s' — δεν θα έχει σήμανση "
                          "καιρού. Πρόσθεσέ το στο STORE_GEO του index.html." % name)
            continue
        per_store[i] = g
        if g not in pts:
            pts.append(g)
    if not pts:
        return None
    wx, _ = fetch_tmax(pts, first_date, last_date,
                       os.path.join(work_dir, 'weather_cache.json'), log)
    by_point = {p: classify_wx(wx.get(p, {})) for p in pts}

    by_store, counts = {}, {}
    for i, p in per_store.items():
        days = by_point.get(p) or {}
        if not days:
            continue
        rows = {}
        for ds, k in sorted(days.items()):
            if ds < first_date:
                continue
            w = wx[p].get(ds) or {}
            rows[ds] = [k, w.get('tmax'), w.get('rain'), w.get('snow')]
            counts[k] = counts.get(k, 0) + 1
        if rows:
            by_store[str(i)] = rows

    effects = {}
    if store_days:
        def kind_of(si, ds):
            p = per_store.get(si)
            return (by_point.get(p) or {}).get(ds) if p else None
        effects = measure_effects(store_days, kind_of)

    # ── ΗΜΕΡΗΣΙΑ ΘΕΡΜΟΚΡΑΣΙΑ ΓΙΑ ΚΑΘΕ ΜΕΡΑ, όχι μόνο τις ακραίες ──────────
    # Το `by_store` κρατά ΜΟΝΟ τις επηρεαζόμενες ημέρες (2.679 από 29.062):
    # σωστό για τη σήμανση, αλλά με αυτό ΔΕΝ γίνεται ημερολόγιο καιρού — τα
    # 91% των κελιών θα ήταν κενά. Εδώ βγαίνει συμπαγής σειρά ανά κατάστημα
    # με ΚΟΙΝΟ ευρετήριο ημερομηνιών (ώστε να μην επαναλαμβάνονται 22 φορές).
    # Μετρημένο κόστος: ~142 KB, δηλαδή 1,0% του data.json.
    dates = sorted({ds for p in pts for ds in (wx.get(p) or {}) if ds >= first_date})
    daily, daily_rain, daily_min = {}, {}, {}
    if dates:
        pos = {ds: i for i, ds in enumerate(dates)}
        for i, p in per_store.items():
            days = wx.get(p) or {}
            arr = [None] * len(dates)
            rn = [None] * len(dates)
            mn = [None] * len(dates)
            for ds, v in days.items():
                j = pos.get(ds)
                if j is not None:
                    arr[j] = v.get('tmax')
                    rn[j] = v.get('rain')
                    mn[j] = v.get('tmin')
            if any(x is not None for x in arr):
                daily[str(i)] = arr
            if any(x for x in rn):
                daily_rain[str(i)] = rn
            if any(x is not None for x in mn):
                daily_min[str(i)] = mn

    if log:
        log.info('  [heat] %d καταστήματα · ημέρες-καταστήματος: %s'
                 % (len(by_store), ', '.join('%s %d' % kv for kv in sorted(counts.items()))))
        log.info('  [heat] ημερήσια θερμοκρασία: %d ημέρες × %d καταστήματα'
                 % (len(dates), len(daily)))
        for k, v in sorted(effects.items(), key=lambda kv: kv[1]['s']):
            log.info('  [heat] επίδραση %-5s n=%-5d πωλήσεις %+.2f%% συναλλαγές %+.2f%%'
                     % (k, v['n'], v['s'] * 100, v['t'] * 100))
    return {
        'thresholds': HEAT_THRESHOLDS,
        'wx_thresholds': WX_THRESHOLDS,
        'by_store': by_store,
        'effects': effects,
        'through': max((max(v) for v in by_store.values() if v), default=None),
        # ⚠ ΠΡΟΣΘΕΤΙΚΟ. Καταναλωτές που δεν το ξέρουν δεν επηρεάζονται —
        # το labour tool διαβάζει μόνο `effects` και `by_store`.
        'daily_tmax': {'dates': dates, 'by_store': daily},
        # ⚠ ΙΔΙΟ ευρετήριο ημερομηνιών με το `daily_tmax.dates` — δεν
        # επαναλαμβάνεται (13 KB). Βροχή σε mm, `null` όπου λείπει μέτρηση.
        'daily_rain': {'by_store': daily_rain},
        'daily_tmin': {'by_store': daily_min},   # ίδιο ευρετήριο· ελάχιστη °C
    }
