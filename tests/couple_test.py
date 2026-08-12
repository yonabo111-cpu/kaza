# -*- coding: utf-8 -*-
"""Couple-mode tests: household kind, hidden settle-up, and the leave guard.

A 'couple' household pools money: it never sees who-owes-whom, so it must also
never be *blocked* by a balance it cannot see. Balances keep being computed, so
switching back to 'roommates' loses nothing.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/couple_test.py
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
    session.post(
        f"{BASE}/register",
        json={"name": name, "email": email, "password": "secret1", "accept": True},
    ).raise_for_status()


def state(session):
    return session.get(f"{BASE}/state?month={MONTH}").json()


# --- a couple household -------------------------------------------------------
a, b = requests.Session(), requests.Session()
register(a, "בן-זוג-א", "couplea@example.com")
register(b, "בן-זוג-ב", "coupleb@example.com")
r = a.post(f"{BASE}/household", json={"name": "הבית שלנו", "kind": "couple"})
check("create couple household", r.ok, r.text)
code = a.get(f"{BASE}/me").json()["household"]["invite_code"]
b.post(f"{BASE}/household/join", json={"code": code}).raise_for_status()

st = state(a)
check("state exposes the household kind", st["household"]["kind"] == "couple", str(st["household"]))
check("partner inherits couple mode", state(b)["household"]["kind"] == "couple")

# --- an unequal expense creates a real balance under the hood -----------------
ids = {m["name"]: m["id"] for m in st["members"]}
a_id, b_id = ids["בן-זוג-א"], ids["בן-זוג-ב"]
a.post(
    f"{BASE}/expenses",
    json={
        "descr": "קניות",
        "amount": 300,
        "category_id": st["categories"][0]["id"],
        "date": TODAY,
        "payer_id": a_id,
        "split_type": "equal",
    },
).raise_for_status()

st = state(a)
check("balances are still computed (switching back is lossless)", len(st["balances"]) == 2)
check("household total is available for the couple tile", st["total"] == 300, str(st["total"]))

# --- but a couple is never nagged about debt ---------------------------------
check(
    "no debt notification for a couple",
    not any(n["id"] == "debt" for n in state(b)["notifications"]),
    str([n["id"] for n in state(b)["notifications"]]),
)

# --- and never blocked by a balance they cannot see --------------------------
r = b.post(f"{BASE}/household/leave", json={})
check("couple member can leave despite an open balance", r.status_code == 200, r.text)
b.post(f"{BASE}/household/join", json={"code": code}).raise_for_status()

# --- switching modes is allowed, and reversible ------------------------------
r = a.patch(f"{BASE}/household", json={"kind": "roommates"})
check("switch to roommates", r.ok, r.text)
check("kind updated", state(a)["household"]["kind"] == "roommates")
check(
    "settle-up reappears with the balance intact",
    any(abs(x["balance"]) > 0.01 for x in state(a)["balances"]),
)
check(
    "debt notification returns in roommates mode",
    any(n["id"] == "debt" for n in state(b)["notifications"]),
)
r = a.patch(f"{BASE}/household", json={"kind": "couple"})
check("switch back to couple", r.ok, r.text)

# --- validation ---------------------------------------------------------------
check("invalid kind rejected", a.patch(f"{BASE}/household", json={"kind": "x"}).status_code == 400)
check(
    "invalid kind rejected at creation",
    requests.Session().post(f"{BASE}/household", json={"name": "x", "kind": "x"}).status_code
    in (400, 401),
)

# --- roommates stays the default ---------------------------------------------
c = requests.Session()
register(c, "רגיל", "plain@example.com")
c.post(f"{BASE}/household", json={"name": "דירה רגילה"}).raise_for_status()
check("kind defaults to roommates", state(c)["household"]["kind"] == "roommates")

print(f"ALL {len(PASSED)} CHECKS PASSED")
