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
import urllib.request
import datetime

# Κατώφλια (°C). ΑΠΟΛΥΤΑ, όχι σχετικά ως προς τον μήνα: το "κορυφαίο 2% του
# μήνα" είναι 18,8°C τον Ιανουάριο και δεν ενοχλεί κανέναν.
HEAT_THRESHOLDS = {'ban': 37, 'warm': 32}

ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
PAST_DAYS = 92          # όσο δέχεται το forecast API — καλύπτει το κενό του archive
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


def _fetch(url, params):
    q = '&'.join('%s=%s' % (k, v) for k, v in params.items())
    with urllib.request.urlopen(url + '?' + q, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode('utf-8'))


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
    missing = [p for p, k in zip(points, keys) if not cache.get(k)]
    fresh_from = (datetime.date.fromisoformat(end_date) -
                  datetime.timedelta(days=PAST_DAYS - 2)).isoformat()

    def store(payloads, pts):
        for payload, p in zip(payloads, pts):
            k = '%.4f,%.4f' % p
            d = payload.get('daily') or {}
            slot = cache.setdefault(k, {})
            for ds, t in zip(d.get('time') or [], d.get('temperature_2m_max') or []):
                if t is not None:
                    slot[ds] = round(float(t), 1)

    try:
        if missing:                                     # πλήρες ιστορικό, μία φορά
            if log:
                log.info('  [heat] archive: %d τοποθεσίες, %s -> %s' % (len(missing), start_date, end_date))
            store(_as_list(_fetch(ARCHIVE_URL, {
                'latitude': ','.join('%.4f' % p[0] for p in missing),
                'longitude': ','.join('%.4f' % p[1] for p in missing),
                'start_date': start_date, 'end_date': end_date,
                'daily': 'temperature_2m_max', 'timezone': 'Europe%2FAthens',
            })), missing)
        if log:
            log.info('  [heat] forecast past_days=%d για %d τοποθεσίες' % (PAST_DAYS, len(points)))
        store(_as_list(_fetch(FORECAST_URL, {                # πρόσφατες + πρόβλεψη
            'latitude': ','.join('%.4f' % p[0] for p in points),
            'longitude': ','.join('%.4f' % p[1] for p in points),
            'past_days': PAST_DAYS, 'forecast_days': 7,
            'daily': 'temperature_2m_max', 'timezone': 'Europe%2FAthens',
        })), points)
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


def build_heat_block(store_order, index_html_path, work_dir, first_date, last_date, log=None):
    """Το μπλοκ `heat` του data.json.

    {thresholds, by_store: {storeIdx: {date: [kind, tmax]}}, generated_through}
    Μόνο οι ΕΠΗΡΕΑΖΟΜΕΝΕΣ ημέρες μπαίνουν — οι υπόλοιπες είναι σιωπή.
    """
    geo = read_store_geo(index_html_path, log)
    pts, per_store = [], {}
    for i, name in enumerate(store_order):
        g = geo.get(name)
        if not g:
            if log:
                log.error("  [heat] ΧΩΡΙΣ ΣΥΝΤΕΤΑΓΜΕΝΕΣ: '%s' — δεν θα έχει σήμανση "
                          "καύσωνα. Πρόσθεσέ το στο STORE_GEO του index.html." % name)
            continue
        per_store[i] = g
        if g not in pts:
            pts.append(g)
    if not pts:
        return None
    tmax, _ = fetch_tmax(pts, first_date, last_date, os.path.join(work_dir, 'weather_cache.json'), log)
    by_point = {p: classify(tmax.get(p, {})) for p in pts}
    by_store, counts = {}, {'ban': 0, 'wave': 0}
    for i, p in per_store.items():
        days = by_point.get(p) or {}
        if not days:
            continue
        by_store[str(i)] = {ds: [k, tmax[p].get(ds)] for ds, k in sorted(days.items())
                            if ds >= first_date}
        for ds, k in days.items():
            if ds >= first_date:
                counts[k] += 1
    if log:
        log.info('  [heat] %d καταστήματα · ημέρες-καταστήματος: ban %d, wave %d'
                 % (len(by_store), counts['ban'], counts['wave']))
    return {
        'thresholds': HEAT_THRESHOLDS,
        'by_store': by_store,
        'through': max((max(v) for v in by_store.values() if v), default=None),
    }
