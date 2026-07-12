# -*- coding: utf-8 -*-
"""Security tests: headers, CSRF layers, auth walls, isolation, lockout, input hygiene.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/security_test.py
Override the server URL with the API_BASE env var if needed.
"""

import os
import sys
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("API_BASE", "http://localhost:5050/api")
SITE = BASE.rsplit("/api", 1)[0]  # e.g. http://127.0.0.1:5099
MONTH = date.today().strftime("%Y-%m")
PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


# --- הקמה: משתמש + דירה ---
a = requests.Session()
reg = a.post(
    f"{BASE}/register",
    json={"name": "בדיקה-א", "email": "testa@example.com", "password": "secret1"},
)
reg.raise_for_status()
a.post(f"{BASE}/household", json={"name": "דירת בדיקות"}).raise_for_status()
st = a.get(f"{BASE}/state?month={MONTH}").json()
cat = st["categories"][0]["id"]
me_id = st["user"]["id"]

# --- כותרות אבטחה על העמוד ועל ה-API ---
for path, label in ((SITE + "/", "page"), (f"{BASE}/me", "api")):
    h = a.get(path).headers
    check(f"CSP on {label}", "default-src 'self'" in h.get("Content-Security-Policy", ""))
    check(f"nosniff on {label}", h.get("X-Content-Type-Options") == "nosniff")
    check(f"frame deny on {label}", h.get("X-Frame-Options") == "DENY")
check("referrer policy", a.get(SITE + "/").headers.get("Referrer-Policy") == "same-origin")
check("permissions policy", "camera=()" in a.get(SITE + "/").headers.get("Permissions-Policy", ""))
csp = a.get(SITE + "/").headers.get("Content-Security-Policy", "")
check("CSP allows google fonts", "fonts.googleapis.com" in csp and "fonts.gstatic.com" in csp)
check(
    "CSP blocks objects & framing", "object-src 'none'" in csp and "frame-ancestors 'none'" in csp
)

# --- דגלי עוגיית סשן ---
fresh = requests.Session()
r = fresh.post(
    f"{BASE}/register",
    json={"name": "בדיקה-ב", "email": "testb@example.com", "password": "secret2"},
)
set_cookie = r.headers.get("Set-Cookie", "")
check("cookie HttpOnly", "HttpOnly" in set_cookie)
check("cookie SameSite=Lax", "SameSite=Lax" in set_cookie)

# --- CSRF: שלוש שכבות ---
payload = {"content": "בדיקת CSRF"}
r = a.post(f"{BASE}/bulletin", json=payload, headers={"Origin": "https://evil.example"})
check("cross-origin Origin blocked", r.status_code == 403, r.text)
r = a.post(f"{BASE}/bulletin", json=payload, headers={"Sec-Fetch-Site": "cross-site"})
check("Sec-Fetch-Site cross-site blocked", r.status_code == 403)
r = a.post(f"{BASE}/bulletin", data={"content": "form"})  # טופס HTML קלאסי
check("non-JSON POST blocked", r.status_code == 415, str(r.status_code))
r = a.post(f"{BASE}/bulletin", json=payload, headers={"Origin": SITE})
check("same-origin POST allowed", r.ok, r.text)

# --- חומת אימות: כל endpoint מוגן מחזיר 401 בלי סשן ---
anon = requests.Session()
protected = [
    ("GET", f"{BASE}/state?month={MONTH}", None),
    ("GET", f"{BASE}/me", None),
    ("GET", f"{BASE}/export", None),
    ("GET", f"{BASE}/bulletin", None),
    ("POST", f"{BASE}/expenses", {"descr": "x"}),
    ("POST", f"{BASE}/personal", {"descr": "x"}),
    ("POST", f"{BASE}/shopping", {"name": "x"}),
    ("DELETE", f"{BASE}/expenses/1", None),
]
walls = [anon.request(m, url, json=body_) for m, url, body_ in protected]
check(
    "all protected endpoints 401",
    all(r.status_code == 401 for r in walls),
    str([r.status_code for r in walls]),
)
check("healthz is public", anon.get(SITE + "/healthz").json()["status"] == "ok")

# --- בידוד בין דירות ---
b = fresh  # בדיקה-ב
b.post(f"{BASE}/household", json={"name": "דירה זרה"}).raise_for_status()
a.post(
    f"{BASE}/expenses",
    json={
        "descr": "סודי",
        "amount": 50,
        "category_id": cat,
        "date": date.today().isoformat(),
        "payer_id": me_id,
        "split_type": "personal",
    },
).raise_for_status()
exp_id = a.get(f"{BASE}/state?month={MONTH}").json()["expenses"][0]["id"]
check("cross-household delete 404", b.delete(f"{BASE}/expenses/{exp_id}").status_code == 404)
stb = b.get(f"{BASE}/state?month={MONTH}").json()
check("stranger sees no foreign data", stb["expenses"] == [] and "סודי" not in str(stb))

# --- נעילת התחברות לפי אימייל ---
attacker = requests.Session()
codes = [
    attacker.post(
        f"{BASE}/login", json={"email": "testa@example.com", "password": f"wrong{i}"}
    ).status_code
    for i in range(6)
]
check("lockout after repeated failures", codes[:5] == [401] * 5 and codes[5] == 429, str(codes))
check(
    "locked even with right password",
    attacker.post(
        f"{BASE}/login", json={"email": "testa@example.com", "password": "secret1"}
    ).status_code
    == 429,
)

# --- היגיינת קלט ---
r = a.post(f"{BASE}/bulletin", json={"content": "שלום\x00עולם\x1f!"})
check("control chars accepted", r.ok, r.text)
notes = a.get(f"{BASE}/bulletin").json()["notes"]
check("control chars stripped", any(n["content"] == "שלוםעולם!" for n in notes), str(notes[:2]))

sqli = "x'); DROP TABLE users;--"
r = a.post(
    f"{BASE}/expenses",
    json={
        "descr": sqli,
        "amount": 10,
        "category_id": cat,
        "date": date.today().isoformat(),
        "payer_id": me_id,
        "split_type": "personal",
    },
)
check("sqli payload stored as data", r.ok, r.text)
st2 = a.get(f"{BASE}/state?month={MONTH}").json()
check("sqli stored verbatim", any(e["descr"] == sqli for e in st2["expenses"]))
check(
    "users table intact after sqli",
    requests.post(
        f"{BASE}/register", json={"name": "ג", "email": "testc@example.com", "password": "secret3"}
    ).ok,
)

xss = "<script>alert(1)</script>"
a.post(f"{BASE}/shopping", json={"name": xss}).raise_for_status()
st3 = a.get(f"{BASE}/state?month={MONTH}").json()
check("xss stored raw (escaped at render)", any(s["name"] == xss for s in st3["shopping"]))

check(
    "amount ceiling enforced",
    a.post(
        f"{BASE}/expenses",
        json={
            "descr": "ענק",
            "amount": 2_000_000,
            "category_id": cat,
            "date": date.today().isoformat(),
            "payer_id": me_id,
            "split_type": "personal",
        },
    ).status_code
    == 400,
)

print(f"ALL {len(PASSED)} CHECKS PASSED")
