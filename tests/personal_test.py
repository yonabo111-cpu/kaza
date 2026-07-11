# -*- coding: utf-8 -*-
"""Personal-ledger tests: privacy between roommates, totals, personal budget.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/personal_test.py
Override the server URL with the API_BASE env var if needed.
"""

import json
import os
import sys
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("API_BASE", "http://localhost:5050/api")
MONTH = date.today().strftime("%Y-%m")
SECRET_DESCR = "מתנה סודית לשותפה"
PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


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
ids = {m["name"]: m["id"] for m in st["members"]}
A, B = ids["בדיקה-א"], ids["בדיקה-ב"]
cat = st["categories"][0]["id"]

# --- א' מוסיף הוצאה פרטית ---
r = a.post(
    f"{BASE}/personal",
    json={"descr": SECRET_DESCR, "amount": 200, "category": "מתנות", "date": f"{MONTH}-08"},
)
check("add private expense", r.ok, r.text)

sta = a.get(f"{BASE}/state?month={MONTH}").json()
check("owner sees private expense", len(sta["personal"]["expenses"]) == 1)
check("owner private_total", sta["personal"]["private_total"] == 200)
check("private not in shared expenses", len(sta["expenses"]) == 0)
check("shared month total unaffected", sta["total"] == 0)
check("balances unaffected", all(x["balance"] == 0 for x in sta["balances"]))
check("shared category spent unaffected", all(c["spent"] == 0 for c in sta["categories"]))

# --- הבדיקה הקריטית: ב' לא רואה את זה בשום מקום ---
# מפענחים את ה-JSON ובודקים על התוכן האמיתי (בלי תלות בקידוד \uXXXX)
stb = b.get(f"{BASE}/state?month={MONTH}").json()
stb_flat = json.dumps(stb, ensure_ascii=False)
check("PRIVACY: secret absent from B's entire state", SECRET_DESCR not in stb_flat)
check(
    "sanity: secret IS in A's state",
    SECRET_DESCR in json.dumps(a.get(f"{BASE}/state?month={MONTH}").json(), ensure_ascii=False),
)
check(
    "B personal empty",
    len(stb["personal"]["expenses"]) == 0 and stb["personal"]["private_total"] == 0,
)
check(
    "B export has no secret",
    SECRET_DESCR not in json.dumps(b.get(f"{BASE}/export").json(), ensure_ascii=False),
)
check(
    "A export includes own private",
    SECRET_DESCR in json.dumps(a.get(f"{BASE}/export").json(), ensure_ascii=False),
)

# --- הוצאה משותפת: החלק שלי מחושב נכון ---
a.post(
    f"{BASE}/expenses",
    json={
        "descr": "סופר",
        "amount": 100,
        "category_id": cat,
        "date": f"{MONTH}-08",
        "payer_id": A,
        "split_type": "equal",
    },
).raise_for_status()
sta = a.get(f"{BASE}/state?month={MONTH}").json()
stb = b.get(f"{BASE}/state?month={MONTH}").json()
check("A share_total 50", sta["personal"]["share_total"] == 50, str(sta["personal"]))
check("B share_total 50", stb["personal"]["share_total"] == 50)
check(
    "A combined chart 250",
    sta["personal"]["chart"][-1]["total"] == 250,
    str(sta["personal"]["chart"]),
)
check("B combined chart 50", stb["personal"]["chart"][-1]["total"] == 50)

# --- ב' לא יכול למחוק הוצאה פרטית של א' ---
pid = sta["personal"]["expenses"][0]["id"]
check("B cannot delete A's private", b.delete(f"{BASE}/personal/{pid}").status_code == 404)
sta = a.get(f"{BASE}/state?month={MONTH}").json()
check("A's private still exists", len(sta["personal"]["expenses"]) == 1)

# --- תקציב אישי ---
a.post(f"{BASE}/me/budget", json={"budget": 1500}).raise_for_status()
sta = a.get(f"{BASE}/state?month={MONTH}").json()
stb = b.get(f"{BASE}/state?month={MONTH}").json()
check("A budget 1500", sta["personal"]["budget"] == 1500)
check("B budget still 0", stb["personal"]["budget"] == 0)

# --- קטגוריות פרטיות להשלמה אוטומטית ---
check("private categories list", sta["personal"]["categories"] == ["מתנות"])

# --- מחיקה ע"י הבעלים ---
check("A deletes own private", a.delete(f"{BASE}/personal/{pid}").ok)
sta = a.get(f"{BASE}/state?month={MONTH}").json()
check(
    "private gone after delete",
    len(sta["personal"]["expenses"]) == 0 and sta["personal"]["private_total"] == 0,
)

# --- ולידציות ---
check(
    "private bad amount rejected",
    a.post(f"{BASE}/personal", json={"descr": "x", "amount": -5, "date": f"{MONTH}-08"}).status_code
    == 400,
)
check(
    "private bad date rejected",
    a.post(f"{BASE}/personal", json={"descr": "x", "amount": 5, "date": "לא תאריך"}).status_code
    == 400,
)
check(
    "private requires login",
    requests.post(
        f"{BASE}/personal", json={"descr": "x", "amount": 5, "date": f"{MONTH}-08"}
    ).status_code
    == 401,
)

print(f"ALL {len(PASSED)} CHECKS PASSED")
