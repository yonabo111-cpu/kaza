# -*- coding: utf-8 -*-
"""Leave-household tests: the settle-up guard, detachment, and isolation.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/leave_test.py
Override the server URL with the API_BASE env var if needed.
"""

import os
import sys
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("API_BASE", "http://localhost:5050/api")
TODAY = date.today().isoformat()
MONTH = date.today().strftime("%Y-%m")
PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


def register(session, name, email):
    r = session.post(f"{BASE}/register", json={"name": name, "email": email, "password": "secret1"})
    r.raise_for_status()


# --- two roommates who share an expense --------------------------------------
a, b = requests.Session(), requests.Session()
register(a, "עוזב-א", "leavea@example.com")
register(b, "עוזב-ב", "leaveb@example.com")
a.post(f"{BASE}/household", json={"name": "דירת עזיבה"}).raise_for_status()
code = a.get(f"{BASE}/me").json()["household"]["invite_code"]
b.post(f"{BASE}/household/join", json={"code": code}).raise_for_status()

st = a.get(f"{BASE}/state?month={MONTH}").json()
members = {m["name"]: m["id"] for m in st["members"]}
a_id, b_id = members["עוזב-א"], members["עוזב-ב"]
cats = st["categories"]

# A pays 100 split equally → B owes 50, A is owed 50.
a.post(
    f"{BASE}/expenses",
    json={
        "descr": "קניות משותפות",
        "amount": 100,
        "category_id": cats[0]["id"],
        "date": TODAY,
        "payer_id": a_id,
        "split_type": "equal",
    },
).raise_for_status()

# --- the settle-up guard blocks BOTH the debtor and the creditor -------------
rb = b.post(f"{BASE}/household/leave", json={})
check("debtor blocked from leaving", rb.status_code == 409, str(rb.status_code))
ra = a.post(f"{BASE}/household/leave", json={})
check("creditor blocked from leaving", ra.status_code == 409, str(ra.status_code))
check("both are still members", len(a.get(f"{BASE}/state?month={MONTH}").json()["members"]) == 2)

# --- settle up, then leaving is allowed --------------------------------------
b.post(
    f"{BASE}/settlements",
    json={"from_id": b_id, "to_id": a_id, "amount": 50, "date": TODAY},
).raise_for_status()
rb = b.post(f"{BASE}/household/leave", json={})
check("leaving allowed once settled", rb.status_code == 200, str(rb.status_code))

# --- B is detached; A keeps the home with only themselves --------------------
check("B has no household after leaving", b.get(f"{BASE}/me").json()["household"] is None)
check("B loses access to household state", b.get(f"{BASE}/state?month={MONTH}").status_code == 409)
st_a = a.get(f"{BASE}/state?month={MONTH}").json()
member_ids = [m["id"] for m in st_a["members"]]
check("A remains a member", a_id in member_ids)
check("B no longer listed as a member", b_id not in member_ids)
check("shared expense history is preserved", len(st_a["expenses"]) >= 1)

# --- B can rejoin with the same code -----------------------------------------
b.post(f"{BASE}/household/join", json={"code": code}).raise_for_status()
check("B can rejoin the home", b.get(f"{BASE}/me").json()["household"] is not None)

# --- a solo member always nets to zero and can leave freely ------------------
c = requests.Session()
register(c, "יחיד", "solo@example.com")
c.post(f"{BASE}/household", json={"name": "דירת יחיד"}).raise_for_status()
rc = c.post(f"{BASE}/household/leave", json={})
check("solo member can leave immediately", rc.status_code == 200, str(rc.status_code))
check("solo member is detached", c.get(f"{BASE}/me").json()["household"] is None)

# --- leaving with no household is rejected by the guard decorator -------------
rc = c.post(f"{BASE}/household/leave", json={})
check("leave without a household is 409", rc.status_code == 409, str(rc.status_code))

print(f"ALL {len(PASSED)} CHECKS PASSED")
