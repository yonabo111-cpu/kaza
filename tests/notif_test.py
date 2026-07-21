# -*- coding: utf-8 -*-
"""In-app notification tests: bills, budgets, personal budget, debt, chores, urgency.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/notif_test.py
Override the server URL with the API_BASE env var if needed.
"""

import os
import sys
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("API_BASE", "http://localhost:5050/api")
TODAY = date.today()
MONTH = TODAY.strftime("%Y-%m")
PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


def notifs(session):
    return session.get(f"{BASE}/state?month={MONTH}").json()["notifications"]


def has(items, id_prefix, severity=None):
    return any(
        n["id"].startswith(id_prefix) and (severity is None or n["severity"] == severity)
        for n in items
    )


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

st = a.get(f"{BASE}/state?month={MONTH}").json()
check("state includes notifications", isinstance(st.get("notifications"), list))
cats = st["categories"]

# --- הוצאות בסיס (ההוצאה השווה יוצרת את החוב לבדיקה בהמשך) ---
a.post(
    f"{BASE}/expenses",
    json={
        "descr": "קניות",
        "amount": 100,
        "category_id": cats[0]["id"],
        "date": TODAY.isoformat(),
        "payer_id": st["members"][0]["id"],
        "split_type": "equal",
    },
).raise_for_status()
a.post(
    f"{BASE}/expenses",
    json={
        "descr": "הוצאה אישית",
        "amount": 90,
        "category_id": cats[1]["id"],
        "date": TODAY.isoformat(),
        "payer_id": st["members"][0]["id"],
        "split_type": "personal",
    },
).raise_for_status()
na = notifs(a)
check("no household-budget notifications", not any(n["id"].startswith("budget-") for n in na))

# --- חשבונות: נוצר חשבון שיום החיוב שלו היום → אזהרה ---
a.post(
    f"{BASE}/bills",
    json={"name": "חשבון בדיקה", "amount": 123, "due_day": TODAY.day, "category_id": cats[0]["id"]},
).raise_for_status()
na = notifs(a)
check("bill due-today is warn", has(na, "bill-due-", "warn"), str([n["id"] for n in na]))
if TODAY.day > 1:  # שכר הדירה המובנה (יום 1) טרם שולם → באיחור
    check("overdue bill is critical", has(na, "bill-late-", "critical"))

# --- חוב: ב' חייב אחרי ההוצאה השווה — רק ב' רואה ---
nb = notifs(b)
check("debtor sees debt notification", has(nb, "debt"))
check("creditor does not", not has(na, "debt"))

# --- תקציב אישי: פרטי למשתמש ---
a.post(f"{BASE}/me/budget", json={"budget": 10}).raise_for_status()
a.post(
    f"{BASE}/personal", json={"descr": "פרטי", "amount": 50, "date": TODAY.isoformat()}
).raise_for_status()
na, nb = notifs(a), notifs(b)
check("personal-over for its owner", has(na, "personal-over-", "critical"))
check("personal-over hidden from others", not has(nb, "personal-"))

# --- מטלות: המטלות המובנות משויכות ליוצר הדירה (א') ---
check("chore turn for assignee", has(na, "chores-"))
check("no chore notification for others", not has(nb, "chores-"))

# --- קניות דחופות: שני השותפים רואים ---
a.post(f"{BASE}/shopping", json={"name": "נייר טואלט", "urgent": True}).raise_for_status()
na, nb = notifs(a), notifs(b)
check(
    "urgent shopping for all members", has(na, "shopping-urgent-") and has(nb, "shopping-urgent-")
)

# --- מבנה: ממוין לפי חומרה, מזהים ייחודיים ---
check("sorted by severity", na[0]["severity"] == "critical")
ranks = [{"critical": 0, "warn": 1, "info": 2}[n["severity"]] for n in na]
check("severity order monotonic", ranks == sorted(ranks))
check("ids unique", len({n["id"] for n in na}) == len(na))
check(
    "every notification has a target tab",
    all(
        n["tab"] in ("dash", "expenses", "personal", "budgets", "shopping", "bills", "chores")
        for n in na
    ),
)

print(f"ALL {len(PASSED)} CHECKS PASSED")
