# -*- coding: utf-8 -*-
"""Monthly-balance tests: per-month scoping, carry-over, and per-user expense fields.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/monthly_test.py
Override the server URL with the API_BASE env var if needed.
"""

import os
import sys
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("API_BASE", "http://localhost:5050/api")
PASSED = []

TODAY = date.today()
CUR = TODAY.strftime("%Y-%m")
_py, _pm = (TODAY.year - 1, 12) if TODAY.month == 1 else (TODAY.year, TODAY.month - 1)
PREV = f"{_py:04d}-{_pm:02d}"
CUR_DATE = TODAY.replace(day=min(TODAY.day, 28)).isoformat()
PREV_DATE = f"{PREV}-15"


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


def state(session, month):
    return session.get(f"{BASE}/state?month={month}").json()


def balance_of(session, month, uid):
    return next(x for x in state(session, month)["balances"] if x["id"] == uid)


a, b = requests.Session(), requests.Session()
a.post(
    f"{BASE}/register",
    json={"name": "בדיקה-א", "email": "testa@example.com", "password": "secret1"},
).raise_for_status()
b.post(
    f"{BASE}/register",
    json={"name": "בדיקה-ב", "email": "testb@example.com", "password": "secret2"},
).raise_for_status()
a.post(f"{BASE}/household", json={"name": "דירת בדיקות"}).raise_for_status()
code = a.get(f"{BASE}/me").json()["household"]["invite_code"]
b.post(f"{BASE}/household/join", json={"code": code}).raise_for_status()

st = state(a, CUR)
ids = {m["name"]: m["id"] for m in st["members"]}
A, B = ids["בדיקה-א"], ids["בדיקה-ב"]
cat = st["categories"][0]["id"]


def add_expense(session, amount, when, payer, split):
    return session.post(
        f"{BASE}/expenses",
        json={
            "descr": "בדיקה",
            "amount": amount,
            "category_id": cat,
            "date": when,
            "payer_id": payer,
            "split_type": split,
        },
    )


# --- per-expense my_share / mine on an equal split ---
add_expense(a, 100, CUR_DATE, A, "equal").raise_for_status()
ea = state(a, CUR)["expenses"][0]
check("payer my_share = half", ea["my_share"] == 50, str(ea))
check("payer mine=True", ea["mine"] is True)
eb = next(e for e in state(b, CUR)["expenses"] if e["id"] == ea["id"])
check("other member my_share = half", eb["my_share"] == 50)
check("other member mine=True", eb["mine"] is True)

# --- personal split: only the payer is involved ---
add_expense(a, 40, CUR_DATE, A, "personal").raise_for_status()
pe_a = next(e for e in state(a, CUR)["expenses"] if e["split_type"] == "personal")
check("personal: payer my_share = full", pe_a["my_share"] == 40)
pe_b = next(e for e in state(b, CUR)["expenses"] if e["id"] == pe_a["id"])
check("personal: non-payer my_share = 0", pe_b["my_share"] == 0)
check("personal: non-payer mine=False", pe_b["mine"] is False)

# --- month scoping: a prior-month expense counts only from that month on ---
add_expense(a, 100, PREV_DATE, A, "equal").raise_for_status()

prev_a = balance_of(a, PREV, A)
check("prev month sees only prev expense", prev_a["balance"] == 50, str(prev_a))
check("prev month carryover is 0", prev_a["carryover"] == 0)
check("prev month excludes current expenses", balance_of(a, PREV, B)["balance"] == -50)

# --- carry-over: current month = cumulative through now, carryover = through prev ---
cur_a = balance_of(a, CUR, A)
# A paid 100(prev)+100(cur)+40(personal)=240; shares 50+50+40=140 → +100.
check("current balance is cumulative", cur_a["balance"] == 100, str(cur_a))
check("carryover = prior-month balance", cur_a["carryover"] == 50)
cur_b = balance_of(a, CUR, B)
check("other member cumulative", cur_b["balance"] == -100)
check("other member carryover", cur_b["carryover"] == -50)

# --- a settlement in the current month reduces the rolled-up balance ---
a.post(
    f"{BASE}/settlements", json={"from_id": B, "to_id": A, "amount": 100, "date": CUR_DATE}
).raise_for_status()
check("settlement clears cumulative balance", balance_of(a, CUR, A)["balance"] == 0)
check("prev month unaffected by later settlement", balance_of(a, PREV, A)["balance"] == 50)

print(f"ALL {len(PASSED)} CHECKS PASSED")
