# -*- coding: utf-8 -*-
"""End-to-end API test: two users, one shared household, every flow.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/api_test.py
Override the server URL with the API_BASE env var if needed.
"""

import os
import sys
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("API_BASE", "http://localhost:5050/api")
MONTH = date.today().strftime("%Y-%m")
PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


def bal(state, uid):
    return [x for x in state["balances"] if x["id"] == uid][0]["balance"]


a = requests.Session()
b = requests.Session()

# --- הרשמה ואימות ---
r = a.post(
    f"{BASE}/register",
    json={"name": "בדיקה-א", "email": "testa@example.com", "password": "secret1"},
)
check("register A", r.ok, r.text)
r = requests.post(
    f"{BASE}/register", json={"name": "כפול", "email": "testa@example.com", "password": "secret1"}
)
check("duplicate email rejected", r.status_code == 400)
r = requests.post(f"{BASE}/login", json={"email": "testa@example.com", "password": "wrong!"})
check("wrong password 401", r.status_code == 401)
r = b.post(
    f"{BASE}/register",
    json={"name": "בדיקה-ב", "email": "testb@example.com", "password": "secret2"},
)
check("register B", r.ok, r.text)
check(
    "register weak password rejected",
    requests.post(
        f"{BASE}/register", json={"name": "x", "email": "t@t.co", "password": "123"}
    ).status_code
    == 400,
)

# --- דירה ---
check("state without household 409", a.get(f"{BASE}/state?month={MONTH}").status_code == 409)
r = a.post(f"{BASE}/household", json={"name": "דירת בדיקות"})
check("create household", r.ok, r.text)
code = a.get(f"{BASE}/me").json()["household"]["invite_code"]
check("invite code format", len(code) == 6)
check(
    "join with bad code rejected",
    b.post(f"{BASE}/household/join", json={"code": "XXXXXX"}).status_code == 400,
)
r = b.post(f"{BASE}/household/join", json={"code": code})
check("join household", r.ok, r.text)

st = a.get(f"{BASE}/state?month={MONTH}").json()
check("2 members", len(st["members"]) == 2)
check("seeded categories", len(st["categories"]) == 6)
check("seeded bills", len(st["bills"]) == 6)
check("seeded chores", len(st["chores"]) == 4)
ids = {m["name"]: m["id"] for m in st["members"]}
A, B = ids["בדיקה-א"], ids["בדיקה-ב"]
cat = st["categories"][0]["id"]

# --- הוצאות וחלוקות ---
r = a.post(
    f"{BASE}/expenses",
    json={
        "descr": "סופר",
        "amount": 100,
        "category_id": cat,
        "date": f"{MONTH}-08",
        "payer_id": A,
        "split_type": "equal",
    },
)
check("expense equal", r.ok, r.text)
st = a.get(f"{BASE}/state?month={MONTH}").json()
check("equal: A +50", bal(st, A) == 50, str(st["balances"]))
check("equal: B -50", bal(st, B) == -50)

r = b.post(
    f"{BASE}/expenses",
    json={
        "descr": "אוזניות",
        "amount": 40,
        "category_id": cat,
        "date": f"{MONTH}-08",
        "payer_id": B,
        "split_type": "personal",
    },
)
check("expense personal", r.ok, r.text)
st = a.get(f"{BASE}/state?month={MONTH}").json()
check("personal: balances unchanged", bal(st, A) == 50 and bal(st, B) == -50)

r = b.post(
    f"{BASE}/expenses",
    json={
        "descr": "שוק",
        "amount": 90,
        "category_id": cat,
        "date": f"{MONTH}-08",
        "payer_id": B,
        "split_type": "custom",
        "shares": {str(A): 60, str(B): 30},
    },
)
check("expense custom", r.ok, r.text)
st = a.get(f"{BASE}/state?month={MONTH}").json()
check("custom: A 50-60=-10", bal(st, A) == -10, str(st["balances"]))
check("custom: B -50+60=+10", bal(st, B) == 10)

r = a.post(
    f"{BASE}/expenses",
    json={
        "descr": "רע",
        "amount": 100,
        "category_id": cat,
        "date": f"{MONTH}-08",
        "payer_id": A,
        "split_type": "custom",
        "shares": {str(A): 10, str(B): 20},
    },
)
check("custom bad sum rejected", r.status_code == 400)

# --- הצעת העברות וסגירה ---
t = st["transfers"]
check(
    "transfer suggested A->B 10",
    len(t) == 1 and t[0]["from_id"] == A and t[0]["to_id"] == B and t[0]["amount"] == 10,
    str(t),
)
r = a.post(
    f"{BASE}/settlements", json={"from_id": A, "to_id": B, "amount": 10, "date": f"{MONTH}-08"}
)
check("record settlement", r.ok, r.text)
st = a.get(f"{BASE}/state?month={MONTH}").json()
check("settled: balances zero", bal(st, A) == 0 and bal(st, B) == 0, str(st["balances"]))
check("settled: no transfers", len(st["transfers"]) == 0)

# --- חשבונות קבועים ---
elec = [x for x in st["bills"] if x["name"] == "חשמל"][0]
r = b.post(f"{BASE}/bills/{elec['id']}/pay", json={"month": MONTH, "payer_id": B})
check("pay bill", r.ok, r.text)
st = a.get(f"{BASE}/state?month={MONTH}").json()
paid = [x for x in st["bills"] if x["id"] == elec["id"]][0]["paid"]
check("bill marked paid by B", paid and paid["payer_id"] == B, str(paid))
check("bill expense: A owes 150", bal(st, A) == -150, str(st["balances"]))
check("bill expense in list", any(e["descr"] == "חשמל" for e in st["expenses"]))
r = b.post(f"{BASE}/bills/{elec['id']}/pay", json={"month": MONTH, "payer_id": B})
check("double pay rejected", r.status_code == 400)
r = b.post(f"{BASE}/bills/{elec['id']}/unpay", json={"month": MONTH})
check("unpay bill", r.ok, r.text)
st = a.get(f"{BASE}/state?month={MONTH}").json()
check(
    "unpay removed expense + balance",
    bal(st, A) == 0 and not any(e["descr"] == "חשמל" for e in st["expenses"]),
)

# --- קניות ---
a.post(f"{BASE}/shopping", json={"name": "חלב", "note": "2 קרטונים", "urgent": True})
a.post(f"{BASE}/shopping", json={"name": "לחם", "urgent": False})
st = a.get(f"{BASE}/state?month={MONTH}").json()
check(
    "shopping added by name",
    any(s["name"] == "חלב" and s["added_by"] == "בדיקה-א" for s in st["shopping"]),
)
milk = [s for s in st["shopping"] if s["name"] == "חלב"][0]
b.patch(f"{BASE}/shopping/{milk['id']}")
r = b.post(
    f"{BASE}/shopping/finish",
    json={"expense": {"amount": 50, "payer_id": B, "category_id": cat, "date": f"{MONTH}-08"}},
)
check("finish shopping", r.ok, r.text)
st = a.get(f"{BASE}/state?month={MONTH}").json()
check("bought item removed", not any(s["name"] == "חלב" for s in st["shopping"]))
check("open item stays", any(s["name"] == "לחם" for s in st["shopping"]))
exp = [e for e in st["expenses"] if e["descr"].startswith("קניות:")]
check(
    "shopping expense created",
    len(exp) == 1 and exp[0]["amount"] == 50 and "חלב" in exp[0]["descr"],
)
check("shopping expense split", bal(st, A) == -25, str(st["balances"]))

# --- מטלות: רוטציה ---
chore = st["chores"][0]
check("chore starts with creator A", chore["assignee_id"] == A)
b.post(f"{BASE}/chores/{chore['id']}/done", json={"date": f"{MONTH}-08"})
st = a.get(f"{BASE}/state?month={MONTH}").json()
check("chore rotated to B", st["chores"][0]["assignee_id"] == B)
a.post(f"{BASE}/chores/{chore['id']}/done", json={"date": f"{MONTH}-08"})
st = a.get(f"{BASE}/state?month={MONTH}").json()
check("chore rotated back to A", st["chores"][0]["assignee_id"] == A)

# --- קטגוריות ---
r = a.patch(f"{BASE}/categories/{cat}", json={"budget": 2000})
check("update budget", r.ok)
r = a.post(f"{BASE}/categories", json={"name": "חיות מחמד", "budget": 100})
check("add category", r.ok)
st = a.get(f"{BASE}/state?month={MONTH}").json()
newcat = [c for c in st["categories"] if c["name"] == "חיות מחמד"][0]
check("budget updated", [c for c in st["categories"] if c["id"] == cat][0]["budget"] == 2000)
r = a.delete(f"{BASE}/categories/{newcat['id']}")
check("delete unused category", r.ok)
r = a.delete(f"{BASE}/categories/{cat}")
check("delete used category rejected", r.status_code == 400)

# --- בידוד בין דירות ---
c = requests.Session()
c.post(f"{BASE}/register", json={"name": "זר", "email": "testc@example.com", "password": "secret3"})
c.post(f"{BASE}/household", json={"name": "דירה זרה"})
some_expense = st["expenses"][0]["id"]
r = c.delete(f"{BASE}/expenses/{some_expense}")
check("cross-household delete blocked", r.status_code == 404, r.text)
stc = c.get(f"{BASE}/state?month={MONTH}").json()
check("stranger sees own empty data", len(stc["expenses"]) == 0 and len(stc["members"]) == 1)

# --- גרף וסכומים ---
check("chart 6 months", len(st["chart"]) == 6 and st["chart"][-1]["month"] == MONTH)
total = round(sum(e["amount"] for e in st["expenses"]), 2)
check("month total matches", st["total"] == total, f"{st['total']} != {total}")

print(f"ALL {len(PASSED)} CHECKS PASSED")
