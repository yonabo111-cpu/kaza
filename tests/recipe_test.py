# -*- coding: utf-8 -*-
"""Recipe-to-shopping-list tests: dish detection, free-form phrasing, bulk add, dedup.

Run against a DISPOSABLE database (the test registers its own users):
    DATA_DIR=/tmp/home-test python app.py
    python tests/recipe_test.py
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


a = requests.Session()
a.post(f"{BASE}/register", json={"name": "בדיקה-א", "email": "testa@example.com", "password": "secret1"}).raise_for_status()
a.post(f"{BASE}/household", json={"name": "דירת בדיקות"}).raise_for_status()

# --- זיהוי מנה בניסוח חופשי (בדיוק הדוגמה של המשתמש) ---
r = a.post(f"{BASE}/shopping/recipe", json={"dish": "אני מעוניין לאכול פסטה בולונז"})
check("free-text resolves", r.status_code == 200, r.text)
d = r.json()
check("dish name cleaned", d["dish"] == "פסטה בולונז", d["dish"])
check("source builtin", d["source"] == "builtin")
check("has ingredients", len(d["ingredients"]) >= 6)
check("ingredient shape", all("name" in i and "note" in i for i in d["ingredients"]))
check("meat is there", any("בשר טחון" in i["name"] for i in d["ingredients"]))

# --- כינויים וניסוחים נוספים ---
check("alias בולונז", a.post(f"{BASE}/shopping/recipe", json={"dish": "בא לי בולונז"}).json()["dish"] == "פסטה בולונז")
check("שקשוקה הערב", a.post(f"{BASE}/shopping/recipe", json={"dish": "רוצים שקשוקה הערב"}).json()["dish"] == "שקשוקה")
check("מגדרה בלי גרש", a.post(f"{BASE}/shopping/recipe", json={"dish": "מגדרה"}).json()["dish"] == "מג'דרה")

# --- מנה לא מוכרת: 404 בלי מפתח API, או תשובת AI אם יש מפתח בסביבה ---
r = a.post(f"{BASE}/shopping/recipe", json={"dish": "קרפזולית מעופפת בטמפורה"})
check("unknown dish handled", r.status_code == 404 or (r.status_code == 200 and r.json()["source"] == "ai"),
      f"{r.status_code} {r.text[:120]}")

# --- ולידציות ---
check("empty dish rejected", a.post(f"{BASE}/shopping/recipe", json={"dish": "  "}).status_code == 400)
check("filler-only rejected", a.post(f"{BASE}/shopping/recipe", json={"dish": "בא לי לאכול משהו טעים"}).status_code in (400, 404))

# --- הוספה בכמות לרשימה ---
items = [{"name": i["name"], "note": (i["note"] + " · " if i["note"] else "") + "לפסטה בולונז"} for i in d["ingredients"][:5]]
r = a.post(f"{BASE}/shopping/bulk", json={"items": items})
check("bulk add", r.ok and r.json()["added"] == 5, r.text)
st = a.get(f"{BASE}/state?month={MONTH}").json()
names = [s["name"] for s in st["shopping"]]
check("items in list", all(i["name"] in names for i in items))
check("note tagged with dish", any("לפסטה בולונז" in s["note"] for s in st["shopping"]))

# --- כפילויות מדולגות ---
r = a.post(f"{BASE}/shopping/bulk", json={"items": items + [{"name": "פריט חדש לגמרי", "note": ""}]})
check("duplicates skipped", r.json()["added"] == 1 and r.json()["skipped"] == 5, r.text)

# --- ולידציית bulk ---
check("bulk empty rejected", a.post(f"{BASE}/shopping/bulk", json={"items": []}).status_code == 400)
check("bulk too many rejected", a.post(f"{BASE}/shopping/bulk", json={"items": [{"name": "x"}] * 41}).status_code == 400)

print(f"ALL {len(PASSED)} CHECKS PASSED")
