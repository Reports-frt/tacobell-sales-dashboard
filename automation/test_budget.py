# -*- coding: utf-8 -*-
"""Δοκιμή της load_budget του Taco Bell ΧΩΡΙΣ να τρέξει το pipeline.

Επαληθεύει ανεξάρτητα: διαβάζει το xlsx με δικό του κώδικα και συγκρίνει
με ό,τι επέστρεψε η load_budget. Αν συμφωνούσε με τον εαυτό της, δεν θα
απεδείκνυε τίποτα.
"""
import ast
import json
import sys
import datetime as dt

import openpyxl

SRC = r"C:\Users\IT\Documents\GitHub\tacobell-sales-dashboard\automation\update_dashboard.py"
XLSX = r"C:\Users\IT\Documents\GitHub\tacobell-sales-dashboard\_work\budget_source.xlsx"
DATA = r"C:\Users\IT\Documents\GitHub\tacobell-sales-dashboard\data.json"

# --- φόρτωση μόνο των ορισμών, χωρίς το main() ---
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
keep = [n for n in tree.body if isinstance(
    n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign, ast.ClassDef))]
ns = {"__name__": "tb_probe"}
exec(compile(ast.Module(body=keep, type_ignores=[]), SRC, "exec"), ns)

fails = []


def check(label, cond, detail=""):
    print(f"  {'[ΟΚ]    ' if cond else '[ΑΠΟΤΥΧΙΑ]'} {label}" + (f"  -> {detail}" if detail else ""))
    if not cond:
        fails.append(label)


print("=" * 70)
print("1. ΕΚΤΕΛΕΣΗ load_budget")
print("=" * 70)
budget = ns["load_budget"](XLSX)

print()
print("=" * 70)
print("2. ΤΑ ΚΛΕΙΔΙΑ ΤΑΙΡΙΑΖΟΥΝ ΜΕ ΤΟ meta.stores (αλλιώς το index.html δεν βρίσκει τίποτα)")
print("=" * 70)
stores = json.load(open(DATA, encoding="utf-8"))["meta"]["stores"]
for s in stores:
    check(f"υπάρχει budget για {s!r}", s in budget)
extra = [k for k in budget if k not in stores]
check("δεν υπάρχουν κλειδιά εκτός meta.stores", not extra, str(extra))

print()
print("=" * 70)
print("3. ΑΝΕΞΑΡΤΗΤΗ ΕΠΑΛΗΘΕΥΣΗ ΑΡΙΘΜΩΝ (δεύτερη ανάγνωση του xlsx)")
print("=" * 70)
wb = openpyxl.load_workbook(XLSX, data_only=True, read_only=True)
ws = wb["Result excl. All EORD"]
grid = [row for row in ws.iter_rows(min_row=1, max_col=20, values_only=True)]

# στήλες budget: γραμμή 2 περιέχει "Budget", γραμμή 4 είναι ημερομηνία
bud_cols = {}
act_cols = {}
for c in range(6, 20):
    v4 = grid[3][c - 1]
    if isinstance(v4, dt.datetime):
        scen = str(grid[1][c - 1] or "")
        (bud_cols if "budget" in scen.lower() else act_cols)[v4.month] = c
print(f"  μήνες BUDGET στο αρχείο: {sorted(bud_cols)}")
print(f"  μήνες ACTUAL στο αρχείο: {sorted(act_cols)}  (ΔΕΝ πρέπει να μπουν)")

MAP = ns["CONFIG"]["budget_store_map"]
mism = 0
for xl_name, dash_name in MAP.items():
    for r in range(4, len(grid)):
        row = grid[r]
        if str(row[1] or "").strip() != xl_name:
            continue
        desc = str(row[4] or "").strip()
        key = {"Sales, Total": "Sales", "Transactions, Total": "TCs",
               "Ave Spend, Total": "AvgTicket"}.get(desc)
        if not key:
            continue
        for m, c in bud_cols.items():
            raw = row[c - 1]
            if raw is None:
                continue
            expect = float(raw) * (1000 if key in ("Sales", "TCs") else 1)
            got = budget.get(dash_name, {}).get(m, {}).get(key)
            if got is None or abs(got - expect) > 0.01:
                mism += 1
                if mism <= 5:
                    print(f"    ΔΙΑΦΟΡΑ {dash_name} μήνας {m} {key}: "
                          f"περίμενα {expect}, πήρα {got}")
check("κάθε τιμή budget ταυτίζεται με το xlsx", mism == 0, f"διαφορές: {mism}")

leaked = 0
for xl_name, dash_name in MAP.items():
    for r in range(4, len(grid)):
        row = grid[r]
        if str(row[1] or "").strip() != xl_name:
            continue
        if str(row[4] or "").strip() != "Sales, Total":
            continue
        for m, c in act_cols.items():
            raw = row[c - 1]
            if raw is None:
                continue
            got = budget.get(dash_name, {}).get(m, {}).get("Sales")
            if got is not None and abs(got - float(raw) * 1000) < 0.01:
                leaked += 1
check("ΚΑΝΕΝΑ actual δεν πέρασε ως budget", leaked == 0, f"διαρροές: {leaked}")

print()
print("=" * 70)
print("4. ΣΥΝΟΛΑ ΑΝΑ ΚΑΤΑΣΤΗΜΑ (όπως θα τα αθροίσει το dashboard)")
print("=" * 70)
gs = gt = 0
for s in stores:
    b = budget.get(s, {})
    sales = sum(b.get(m, {}).get("Sales", 0) for m in range(1, 13))
    tcs = sum(b.get(m, {}).get("TCs", 0) for m in range(1, 13))
    months = sorted(m for m in range(1, 13) if b.get(m, {}).get("Sales"))
    gs += sales
    gt += tcs
    print(f"  {s:<26} {sales:>12,.0f} €   {tcs:>9,.0f} TCs   μήνες {months}")
print(f"  {'ΣΥΝΟΛΟ':<26} {gs:>12,.0f} €   {gt:>9,.0f} TCs")

print()
print("=" * 70)
print(f"ΣΥΝΟΛΟ: {'ΟΛΑ ΠΕΡΑΣΑΝ' if not fails else 'ΑΠΕΤΥΧΑΝ ' + str(len(fails))}")
for f in fails:
    print("  - " + f)
print("=" * 70)
sys.exit(1 if fails else 0)
