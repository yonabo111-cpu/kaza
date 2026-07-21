# -*- coding: utf-8 -*-
"""Delete-account tests: settle-up guard, anonymize vs. full delete, erasure.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/delete_test.py
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


def register(session, name, email, pw="secret1"):
    session.post(
        f"{BASE}/register", json={"name": name, "email": email, "password": pw}
    ).raise_for_status()


def can_login(name_email, pw="secret1"):
    s = requests.Session()
    return s.post(f"{BASE}/login", json={"email": name_email, "password": pw}).status_code == 200


# === Scenario 1: a member with roommates → anonymize, shared history survives ===
a, b = requests.Session(), requests.Session()
register(a, "מוחק-א", "dela@example.com")
register(b, "מוחק-ב", "delb@example.com")
a.post(f"{BASE}/household", json={"name": "דירת מחיקה"}).raise_for_status()
code = a.get(f"{BASE}/me").json()["household"]["invite_code"]
b.post(f"{BASE}/household/join", json={"code": code}).raise_for_status()

st = a.get(f"{BASE}/state?month={MONTH}").json()
ids = {m["name"]: m["id"] for m in st["members"]}
a_id, b_id = ids["מוחק-א"], ids["מוחק-ב"]
a.post(
    f"{BASE}/expenses",
    json={
        "descr": "קניות",
        "amount": 100,
        "category_id": st["categories"][0]["id"],
        "date": TODAY,
        "payer_id": a_id,
        "split_type": "equal",
    },
).raise_for_status()

# Guard: B owes 50 → deletion blocked.
check(
    "delete blocked with open balance", b.post(f"{BASE}/account/delete", json={}).status_code == 409
)

# Settle, then delete succeeds.
b.post(
    f"{BASE}/settlements", json={"from_id": b_id, "to_id": a_id, "amount": 50, "date": TODAY}
).raise_for_status()
check("delete allowed once settled", b.post(f"{BASE}/account/delete", json={}).status_code == 200)

# B is erased: old credentials no longer work, and B's session is dead.
check("deleted user cannot log in", not can_login("delb@example.com"))
check("deleted user's session is cleared", b.get(f"{BASE}/me").status_code == 401)
# The email is freed for reuse (it was anonymized off the row).
tmp = requests.Session()
check(
    "freed email can be reused",
    tmp.post(
        f"{BASE}/register", json={"name": "חדש", "email": "delb@example.com", "password": "secret1"}
    ).status_code
    == 200,
)

# A keeps a working household with the shared history intact.
st_a = a.get(f"{BASE}/state?month={MONTH}").json()
check("remaining roommate keeps the home", st_a["household"]["name"] == "דירת מחיקה")
check("shared expense history preserved", len(st_a["expenses"]) >= 1)
check("deleted member no longer listed", b_id not in [m["id"] for m in st_a["members"]])

# === Scenario 2: solo member → full delete of account AND household ==========
c = requests.Session()
register(c, "יחיד-מוחק", "delc@example.com")
c.post(f"{BASE}/household", json={"name": "דירת יחיד למחיקה"}).raise_for_status()
check("solo delete succeeds", c.post(f"{BASE}/account/delete", json={}).status_code == 200)
check("solo user cannot log in after delete", not can_login("delc@example.com"))
check(
    "solo user's email is freed",
    requests.Session()
    .post(
        f"{BASE}/register", json={"name": "שוב", "email": "delc@example.com", "password": "secret1"}
    )
    .status_code
    == 200,
)

# === Scenario 3: user with no household → full delete =======================
d = requests.Session()
register(d, "ללא-דירה", "deld@example.com")
check("no-household delete succeeds", d.post(f"{BASE}/account/delete", json={}).status_code == 200)
check("no-household user cannot log in", not can_login("deld@example.com"))

# === Auth is still required ==================================================
check(
    "delete requires login",
    requests.Session().post(f"{BASE}/account/delete", json={}).status_code == 401,
)

print(f"ALL {len(PASSED)} CHECKS PASSED")
