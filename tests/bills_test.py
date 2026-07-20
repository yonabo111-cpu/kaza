# -*- coding: utf-8 -*-
"""Bill-type tests: individual (each pays own), private visibility, inline edits.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/bills_test.py
Override the server URL with the API_BASE env var if needed.
"""

import os
import sys
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("API_BASE", "http://localhost:5050/api")
PASSED = []

CUR = date.today().strftime("%Y-%m")


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


def state(session):
    return session.get(f"{BASE}/state?month={CUR}").json()


a, b = requests.Session(), requests.Session()
a.post(
    f"{BASE}/register",
    json={"name": "בדיקה-א", "email": "billsa@example.com", "password": "secret1"},
).raise_for_status()
b.post(
    f"{BASE}/register",
    json={"name": "בדיקה-ב", "email": "billsb@example.com", "password": "secret2"},
).raise_for_status()
a.post(f"{BASE}/household", json={"name": "דירת חשבונות"}).raise_for_status()
code = a.get(f"{BASE}/me").json()["household"]["invite_code"]
b.post(f"{BASE}/household/join", json={"code": code}).raise_for_status()

st = state(a)
A_ID = st["user"]["id"]
B_ID = next(m["id"] for m in st["members"] if m["id"] != A_ID)
cat = st["categories"][0]["id"]


def bill_named(session, name):
    return next((x for x in state(session)["bills"] if x["name"] == name), None)


# --- individual bill: each member pays their own, no debts created ---
a.post(
    f"{BASE}/bills",
    json={
        "name": "שכר דירה לבד",
        "amount": 2000,
        "due_day": 1,
        "category_id": cat,
        "bill_type": "individual",
    },
).raise_for_status()
bill = bill_named(a, "שכר דירה לבד")
check("individual bill visible to both", bill and bill_named(b, "שכר דירה לבד") is not None)
check("individual type serialized", bill["type"] == "individual")

a.post(f"{BASE}/bills/{bill['id']}/pay", json={"month": CUR, "payer_id": A_ID}).raise_for_status()
bill = bill_named(a, "שכר דירה לבד")
check("A payment recorded", [p["payer_id"] for p in bill["payments"]] == [A_ID])
r = a.post(f"{BASE}/bills/{bill['id']}/pay", json={"month": CUR, "payer_id": A_ID})
check("A cannot pay twice", r.status_code == 400)
b.post(f"{BASE}/bills/{bill['id']}/pay", json={"month": CUR, "payer_id": B_ID}).raise_for_status()
bill = bill_named(b, "שכר דירה לבד")
check("both payments recorded", {p["payer_id"] for p in bill["payments"]} == {A_ID, B_ID})

st_a, st_b = state(a), state(b)
check(
    "individual payments create no debt",
    all(abs(x["balance"]) < 0.01 for x in st_a["balances"]),
    str(st_a["balances"]),
)
mine_a = [e for e in st_a["expenses"] if e["mine"] and e["descr"] == "שכר דירה לבד"]
check("A sees own rent expense at full amount", len(mine_a) == 1 and mine_a[0]["my_share"] == 2000)
mine_b = [e for e in st_b["expenses"] if e["mine"] and e["descr"] == "שכר דירה לבד"]
check("B sees only their own rent expense", len(mine_b) == 1)

b.post(f"{BASE}/bills/{bill['id']}/unpay", json={"month": CUR, "payer_id": B_ID}).raise_for_status()
bill = bill_named(a, "שכר דירה לבד")
check("B unpay removes only B's payment", [p["payer_id"] for p in bill["payments"]] == [A_ID])
mine_b = [e for e in state(b)["expenses"] if e["mine"] and e["descr"] == "שכר דירה לבד"]
check("B's generated expense removed on unpay", len(mine_b) == 0)

# --- private bill: owner-only visibility, pays into the private ledger ---
a.post(
    f"{BASE}/bills",
    json={
        "name": "חדר כושר",
        "amount": 199,
        "due_day": 5,
        "category_id": cat,
        "bill_type": "private",
    },
).raise_for_status()
priv = bill_named(a, "חדר כושר")
check("private bill visible to owner", priv is not None and priv["type"] == "private")
check("private bill hidden from roommate", bill_named(b, "חדר כושר") is None)
check("private bill absent from B's raw state", "חדר כושר" not in str(state(b)))

r = b.post(f"{BASE}/bills/{priv['id']}/pay", json={"month": CUR, "payer_id": B_ID})
check("roommate cannot pay a private bill", r.status_code == 404)
r = b.delete(f"{BASE}/bills/{priv['id']}")
check("roommate cannot delete a private bill", r.status_code == 404)

a.post(f"{BASE}/bills/{priv['id']}/pay", json={"month": CUR, "payer_id": A_ID}).raise_for_status()
p_exp = [e for e in state(a)["personal"]["expenses"] if e["descr"] == "חדר כושר"]
check(
    "private payment lands in owner's private ledger", len(p_exp) == 1 and p_exp[0]["amount"] == 199
)
check("private payment invisible in shared expenses", "חדר כושר" not in str(state(b)["expenses"]))

a.post(f"{BASE}/bills/{priv['id']}/unpay", json={"month": CUR}).raise_for_status()
p_exp = [e for e in state(a)["personal"]["expenses"] if e["descr"] == "חדר כושר"]
check("private unpay removes the ledger entry", len(p_exp) == 0)

# --- PATCH: edit due day and amount ---
a.patch(f"{BASE}/bills/{priv['id']}", json={"due_day": 20}).raise_for_status()
a.patch(f"{BASE}/bills/{priv['id']}", json={"amount": 249}).raise_for_status()
priv = bill_named(a, "חדר כושר")
check("due day edited", priv["due_day"] == 20)
check("amount edited", priv["amount"] == 249)
r = b.patch(f"{BASE}/bills/{priv['id']}", json={"due_day": 9})
check("roommate cannot edit a private bill", r.status_code == 404)

# --- equal bill sanity: legacy behavior intact ---
a.post(
    f"{BASE}/bills",
    json={"name": "אינטרנט משותף", "amount": 100, "due_day": 3, "category_id": cat},
).raise_for_status()
eq = bill_named(a, "אינטרנט משותף")
check("default type is equal", eq["type"] == "equal")
a.post(f"{BASE}/bills/{eq['id']}/pay", json={"month": CUR, "payer_id": A_ID}).raise_for_status()
eq = bill_named(b, "אינטרנט משותף")
check("equal bill paid shape intact", eq["paid"] and eq["paid"]["payer_id"] == A_ID)
bal_a = next(x for x in state(a)["balances"] if x["id"] == A_ID)
check("equal bill still creates debt", bal_a["balance"] > 0, str(bal_a))

print(f"ALL {len(PASSED)} CHECKS PASSED")
