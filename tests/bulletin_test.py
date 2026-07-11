# -*- coding: utf-8 -*-
"""Bulletin-board tests: ordering, author names, delete permissions, isolation.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/bulletin_test.py
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


# א' יוצר את הדירה (= מנהל הבית), ב' מצטרף
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

# --- יצירת מודעות ---
check("post note", a.post(f"{BASE}/bulletin", json={"content": "הטכנאי מגיע מחר"}).ok)
check(
    "post pinned note",
    b.post(
        f"{BASE}/bulletin", json={"content": "קוד ה-Wi-Fi החדש: 12345678", "is_pinned": True}
    ).ok,
)
check("post another note", a.post(f"{BASE}/bulletin", json={"content": "נגמר סבון כלים"}).ok)

# --- שליפה: נעוצות קודם, ואז מהחדשה לישנה, עם שם הכותב ---
notes = a.get(f"{BASE}/bulletin").json()["notes"]
check("three notes", len(notes) == 3)
check("pinned first", notes[0]["is_pinned"] and "Wi-Fi" in notes[0]["content"], str(notes[0]))
check(
    "then newest first",
    notes[1]["content"] == "נגמר סבון כלים" and notes[2]["content"] == "הטכנאי מגיע מחר",
)
check("author name attached", notes[0]["author"] == "בדיקה-ב" and notes[1]["author"] == "בדיקה-א")

# --- מחיקה: לוח משותף — כל שותף מוחק כל מודעה ---
wifi_id = notes[0]["id"]
tech_id = notes[2]["id"]
check(
    "member deletes someone else's note", b.delete(f"{BASE}/bulletin/{tech_id}").ok
)  # ב' מוחק של א'
check("author deletes own note", b.delete(f"{BASE}/bulletin/{wifi_id}").ok)
check("deleting a missing note 404", a.delete(f"{BASE}/bulletin/{wifi_id}").status_code == 404)
check("board reflects deletions", len(a.get(f"{BASE}/bulletin").json()["notes"]) == 1)

# --- ולידציות ---
check(
    "empty content rejected", a.post(f"{BASE}/bulletin", json={"content": "   "}).status_code == 400
)
check(
    "too-long content rejected",
    a.post(f"{BASE}/bulletin", json={"content": "א" * 301}).status_code == 400,
)

# --- בידוד בין דירות ---
c = requests.Session()
c.post(
    f"{BASE}/register", json={"name": "זר", "email": "testc@example.com", "password": "secret3"}
).raise_for_status()
c.post(f"{BASE}/household", json={"name": "דירה זרה"}).raise_for_status()
check("stranger sees empty board", c.get(f"{BASE}/bulletin").json()["notes"] == [])
remaining_id = a.get(f"{BASE}/bulletin").json()["notes"][0]["id"]
check("stranger cannot delete", c.delete(f"{BASE}/bulletin/{remaining_id}").status_code == 404)
check("note survives stranger's attempt", len(a.get(f"{BASE}/bulletin").json()["notes"]) == 1)

# --- הלוח כלול ב-state (לרינדור הדשבורד) ---
st = a.get(f"{BASE}/state?month={MONTH}").json()
check(
    "state includes bulletin", any(n["content"] == "נגמר סבון כלים" for n in st.get("bulletin", []))
)

print(f"ALL {len(PASSED)} CHECKS PASSED")
