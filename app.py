# -*- coding: utf-8 -*-
"""
ניהול הבית — backend
Flask + SQLite. משתמשים, משקי־בית (דירות) עם קוד הזמנה,
הוצאות עם חלוקה בין שותפים, תקציבים, קניות, חשבונות ומטלות.
"""
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import date, timedelta
from functools import wraps

from flask import Flask, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from recipes import normalize as recipe_normalize, resolve_builtin

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")


def _persistent_secret():
    """מפתח סשן קבוע — נשמר לקובץ כדי שהתחברויות ישרדו הפעלה מחדש."""
    path = os.path.join(DATA_DIR, "secret_key.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    return key


app = Flask(__name__, static_folder="static", static_url_path="")
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", _persistent_secret()),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=60),
)
app.json.ensure_ascii = False  # עברית כ-UTF-8 ולא כ-\uXXXX

SCHEMA = """
CREATE TABLE IF NOT EXISTS households(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  invite_code TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  pw_hash TEXT NOT NULL,
  household_id INTEGER REFERENCES households(id),
  joined_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL REFERENCES households(id),
  name TEXT NOT NULL,
  budget REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL REFERENCES households(id),
  date TEXT NOT NULL,
  descr TEXT NOT NULL,
  amount REAL NOT NULL,
  category_id INTEGER REFERENCES categories(id),
  payer_id INTEGER NOT NULL REFERENCES users(id),
  split_type TEXT NOT NULL CHECK(split_type IN ('equal','personal','custom')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS expense_shares(
  expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  share REAL NOT NULL,
  PRIMARY KEY(expense_id, user_id)
);
CREATE TABLE IF NOT EXISTS settlements(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL REFERENCES households(id),
  date TEXT NOT NULL,
  from_id INTEGER NOT NULL REFERENCES users(id),
  to_id INTEGER NOT NULL REFERENCES users(id),
  amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS shopping(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL REFERENCES households(id),
  name TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  urgent INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  added_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS bills(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL REFERENCES households(id),
  name TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  due_day INTEGER NOT NULL DEFAULT 1,
  category_id INTEGER REFERENCES categories(id)
);
CREATE TABLE IF NOT EXISTS bill_payments(
  bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  month TEXT NOT NULL,
  payer_id INTEGER NOT NULL REFERENCES users(id),
  expense_id INTEGER REFERENCES expenses(id),
  PRIMARY KEY(bill_id, month)
);
CREATE TABLE IF NOT EXISTS chores(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL REFERENCES households(id),
  name TEXT NOT NULL,
  freq TEXT NOT NULL DEFAULT 'שבועי',
  assignee_id INTEGER REFERENCES users(id),
  last_done TEXT
);
CREATE TABLE IF NOT EXISTS private_expenses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  date TEXT NOT NULL,
  descr TEXT NOT NULL,
  amount REAL NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS recipe_cache(
  dish_key TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS bulletin_board(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id INTEGER NOT NULL REFERENCES households(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  content TEXT NOT NULL,
  is_pinned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def db():
    if "_db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        g._db = conn
    return g._db


@app.teardown_appcontext
def _close_db(exc):
    conn = g.pop("_db", None)
    if conn is not None:
        if exc is None:
            conn.commit()
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # מיגרציות עדינות לבסיסי נתונים קיימים
    user_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    if "personal_budget" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN personal_budget REAL NOT NULL DEFAULT 0")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.close()


init_db()

# ---------------------------------------------------------------- helpers

def err(msg, code=400):
    return jsonify(error=msg), code


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        user = current_user()
        if user is None:
            return err("נדרשת התחברות", 401)
        g.user = user
        return f(*a, **k)
    return wrapper


def household_required(f):
    @wraps(f)
    @login_required
    def wrapper(*a, **k):
        if not g.user["household_id"]:
            return err("אין דירה משויכת — צרו דירה או הצטרפו עם קוד", 409)
        g.hid = g.user["household_id"]
        return f(*a, **k)
    return wrapper


@app.before_request
def csrf_origin_check():
    """הגנת CSRF בסיסית: בקשות משנות־מצב חייבות להגיע מאותו origin."""
    if request.method in ("POST", "PATCH", "DELETE") and request.path.startswith("/api/"):
        origin = request.headers.get("Origin")
        if origin:
            host = origin.split("://", 1)[-1]
            if host != request.host:
                return err("בקשה ממקור לא מורשה", 403)


def body():
    return request.get_json(silent=True) or {}


def members(hid):
    return db().execute(
        "SELECT id, name, joined_at FROM users WHERE household_id=? ORDER BY joined_at, id",
        (hid,),
    ).fetchall()


def member_ids(hid):
    return [m["id"] for m in members(hid)]


def bulletin_notes(hid):
    """מודעות הדירה: נעוצות קודם, ואז מהחדשה לישנה — עם שם הכותב."""
    names = {m["id"]: m["name"] for m in members(hid)}
    return [
        {
            "id": n["id"], "content": n["content"], "is_pinned": bool(n["is_pinned"]),
            "created_at": n["created_at"],
            "author_id": n["user_id"], "author": names.get(n["user_id"], "?"),
        }
        for n in db().execute(
            "SELECT * FROM bulletin_board WHERE household_id=?"
            " ORDER BY is_pinned DESC, created_at DESC, id DESC",
            (hid,),
        )
    ]


def new_invite_code():
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # בלי אותיות/ספרות דו־משמעיות
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not db().execute("SELECT 1 FROM households WHERE invite_code=?", (code,)).fetchone():
            return code


def equal_shares(amount, ids, payer_id):
    """חלוקה שווה עם עיגול לאגורות — שארית העיגול נופלת על המשלם."""
    n = len(ids)
    base = round(amount / n, 2)
    shares = {uid: base for uid in ids}
    shares[payer_id] = round(amount - base * (n - 1), 2)
    return shares


def insert_expense(hid, date, descr, amount, category_id, payer_id, split_type, shares):
    cur = db().execute(
        "INSERT INTO expenses(household_id,date,descr,amount,category_id,payer_id,split_type)"
        " VALUES (?,?,?,?,?,?,?)",
        (hid, date, descr, amount, category_id, payer_id, split_type),
    )
    eid = cur.lastrowid
    db().executemany(
        "INSERT INTO expense_shares(expense_id,user_id,share) VALUES (?,?,?)",
        [(eid, uid, share) for uid, share in shares.items()],
    )
    return eid


def compute_balances(hid):
    """מאזן נטו לכל חבר: חיובי = מגיע לו כסף, שלילי = חייב."""
    bal = {m["id"]: 0.0 for m in members(hid)}
    for r in db().execute(
        "SELECT payer_id p, SUM(amount) s FROM expenses WHERE household_id=? GROUP BY payer_id", (hid,)
    ):
        if r["p"] in bal:
            bal[r["p"]] += r["s"]
    for r in db().execute(
        "SELECT es.user_id u, SUM(es.share) s FROM expense_shares es"
        " JOIN expenses e ON e.id=es.expense_id WHERE e.household_id=? GROUP BY es.user_id",
        (hid,),
    ):
        if r["u"] in bal:
            bal[r["u"]] -= r["s"]
    for r in db().execute("SELECT from_id, to_id, amount FROM settlements WHERE household_id=?", (hid,)):
        if r["from_id"] in bal:
            bal[r["from_id"]] += r["amount"]
        if r["to_id"] in bal:
            bal[r["to_id"]] -= r["amount"]
    return [
        {"id": m["id"], "name": m["name"], "balance": round(bal[m["id"]], 2)}
        for m in members(hid)
    ]


def suggest_transfers(balances):
    """התאמה חמדנית: החייב הגדול משלם לזכאי הגדול, עד איזון."""
    debtors = sorted(
        [dict(b) for b in balances if b["balance"] < -0.01], key=lambda x: x["balance"]
    )
    creditors = sorted(
        [dict(b) for b in balances if b["balance"] > 0.01], key=lambda x: -x["balance"]
    )
    out = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amt = round(min(-debtors[i]["balance"], creditors[j]["balance"]), 2)
        if amt > 0.01:
            out.append({
                "from_id": debtors[i]["id"], "from": debtors[i]["name"],
                "to_id": creditors[j]["id"], "to": creditors[j]["name"],
                "amount": amt,
            })
        debtors[i]["balance"] = round(debtors[i]["balance"] + amt, 2)
        creditors[j]["balance"] = round(creditors[j]["balance"] - amt, 2)
        if debtors[i]["balance"] >= -0.01:
            i += 1
        if creditors[j]["balance"] <= 0.01:
            j += 1
    return out


def seed_household(hid, creator_id):
    cats = [("סופר ומזון", 1600), ("אוכל בחוץ", 600), ("בית וניקיון", 250),
            ("חשבונות ודיור", 5500), ("בילויים", 500), ("אחר", 300)]
    ids = {}
    for name, budget in cats:
        cur = db().execute(
            "INSERT INTO categories(household_id,name,budget) VALUES (?,?,?)", (hid, name, budget)
        )
        ids[name] = cur.lastrowid
    bills_cat = ids["חשבונות ודיור"]
    for name, amount, day in [("שכר דירה", 4500, 1), ("ארנונה", 380, 15), ("חשמל", 300, 10),
                              ("מים", 120, 10), ("אינטרנט", 100, 5), ("ועד בית", 150, 1)]:
        db().execute(
            "INSERT INTO bills(household_id,name,amount,due_day,category_id) VALUES (?,?,?,?,?)",
            (hid, name, amount, day, bills_cat),
        )
    for name, freq in [("שטיפת רצפה", "שבועי"), ("כלים / מדיח", "יומי"),
                       ("הוצאת זבל", "יומיים"), ("ניקוי שירותים ואמבטיה", "שבועי")]:
        db().execute(
            "INSERT INTO chores(household_id,name,freq,assignee_id) VALUES (?,?,?,?)",
            (hid, name, freq, creator_id),
        )


# ---------------------------------------------------------------- auth

_login_fails = {}  # email -> [count, locked_until_ts]


@app.post("/api/register")
def register():
    d = body()
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip().lower()
    password = d.get("password") or ""
    if not name or len(name) > 40:
        return err("נא להזין שם (עד 40 תווים)")
    if not EMAIL_RE.match(email):
        return err("כתובת אימייל לא תקינה")
    if len(password) < 6:
        return err("סיסמה קצרה מדי — לפחות 6 תווים")
    if db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        return err("האימייל הזה כבר רשום — נסו להתחבר")
    cur = db().execute(
        "INSERT INTO users(name,email,pw_hash) VALUES (?,?,?)",
        (name, email, generate_password_hash(password)),
    )
    session.clear()
    session["uid"] = cur.lastrowid
    session.permanent = True
    return jsonify(ok=True)


@app.post("/api/login")
def login():
    d = body()
    email = (d.get("email") or "").strip().lower()
    password = d.get("password") or ""
    fails = _login_fails.get(email, [0, 0])
    if time.time() < fails[1]:
        return err("יותר מדי ניסיונות — נסו שוב בעוד דקה", 429)
    user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if user is None or not check_password_hash(user["pw_hash"], password):
        fails[0] += 1
        if fails[0] >= 5:
            fails = [0, time.time() + 60]
        _login_fails[email] = fails
        return err("אימייל או סיסמה שגויים", 401)
    _login_fails.pop(email, None)
    session.clear()
    session["uid"] = user["id"]
    session.permanent = True
    return jsonify(ok=True)


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@login_required
def me():
    hh = None
    if g.user["household_id"]:
        row = db().execute("SELECT * FROM households WHERE id=?", (g.user["household_id"],)).fetchone()
        hh = {"id": row["id"], "name": row["name"], "invite_code": row["invite_code"]}
    return jsonify(
        user={"id": g.user["id"], "name": g.user["name"], "email": g.user["email"]},
        household=hh,
    )


# ---------------------------------------------------------------- household

@app.post("/api/household")
@login_required
def create_household():
    if g.user["household_id"]:
        return err("כבר יש לך דירה משויכת")
    name = (body().get("name") or "").strip()
    if not name or len(name) > 60:
        return err("נא להזין שם לדירה (עד 60 תווים)")
    cur = db().execute(
        "INSERT INTO households(name,invite_code) VALUES (?,?)", (name, new_invite_code())
    )
    hid = cur.lastrowid
    db().execute(
        "UPDATE users SET household_id=?, joined_at=datetime('now') WHERE id=?",
        (hid, g.user["id"]),
    )
    seed_household(hid, g.user["id"])
    return jsonify(ok=True)


@app.post("/api/household/join")
@login_required
def join_household():
    if g.user["household_id"]:
        return err("כבר יש לך דירה משויכת")
    code = (body().get("code") or "").strip().upper()
    row = db().execute("SELECT id FROM households WHERE invite_code=?", (code,)).fetchone()
    if row is None:
        return err("קוד הזמנה לא נמצא — בדקו שוב")
    db().execute(
        "UPDATE users SET household_id=?, joined_at=datetime('now') WHERE id=?",
        (row["id"], g.user["id"]),
    )
    return jsonify(ok=True)


# ---------------------------------------------------------------- notifications

def build_notifications(hid, uid):
    """התראות בתוך האפליקציה — נגזרות מהמצב הנוכחי (תמיד ביחס להיום, לא לחודש המוצג).

    בלי טבלה ובלי תזמון: התראה מופיעה כשהתנאי מתקיים ונעלמת כשהוא נפתר.
    """
    today = date.today()
    month = today.strftime("%Y-%m")
    ils = lambda n: f"{n:,.0f} ₪"
    out = []

    # חשבונות שטרם שולמו החודש: באיחור / מתקרבים ליום החיוב
    paid = {r["bill_id"] for r in db().execute(
        "SELECT bp.bill_id FROM bill_payments bp JOIN bills b ON b.id=bp.bill_id"
        " WHERE bp.month=? AND b.household_id=?", (month, hid))}
    for b in db().execute("SELECT * FROM bills WHERE household_id=? ORDER BY due_day", (hid,)):
        if b["id"] in paid:
            continue
        if today.day > b["due_day"]:
            out.append({"id": f"bill-late-{b['id']}-{month}", "severity": "critical", "icon": "🧾",
                        "text": f"״{b['name']}״ באיחור — יום החיוב ({b['due_day']} בחודש) עבר",
                        "tab": "bills"})
        elif b["due_day"] - today.day <= 3:
            out.append({"id": f"bill-due-{b['id']}-{month}", "severity": "warn", "icon": "🧾",
                        "text": f"״{b['name']}״ ({ils(b['amount'])}) לתשלום עד יום {b['due_day']} בחודש",
                        "tab": "bills"})

    # תקציבי הדירה: חריגה / התקרבות לתקרה
    spent = {r["category_id"]: r["s"] for r in db().execute(
        "SELECT category_id, SUM(amount) s FROM expenses"
        " WHERE household_id=? AND substr(date,1,7)=? GROUP BY category_id", (hid, month))}
    for c in db().execute("SELECT * FROM categories WHERE household_id=? AND budget>0", (hid,)):
        s = spent.get(c["id"], 0)
        if s > c["budget"]:
            out.append({"id": f"budget-over-{c['id']}-{month}", "severity": "critical", "icon": "🎯",
                        "text": f"חריגה בתקציב ״{c['name']}״ — {ils(s)} מתוך {ils(c['budget'])}",
                        "tab": "budgets"})
        elif s >= 0.85 * c["budget"]:
            out.append({"id": f"budget-near-{c['id']}-{month}", "severity": "warn", "icon": "🎯",
                        "text": f"״{c['name']}״ מתקרב לתקרה — {ils(s)} מתוך {ils(c['budget'])}",
                        "tab": "budgets"})

    # התקציב האישי שלי (פרטי — רק המשתמש הנוכחי רואה)
    row = db().execute("SELECT personal_budget FROM users WHERE id=?", (uid,)).fetchone()
    pb = row["personal_budget"] if row else 0
    if pb > 0:
        share = db().execute(
            "SELECT COALESCE(SUM(es.share),0) s FROM expense_shares es"
            " JOIN expenses e ON e.id=es.expense_id"
            " WHERE es.user_id=? AND e.household_id=? AND substr(e.date,1,7)=?",
            (uid, hid, month)).fetchone()["s"]
        priv = db().execute(
            "SELECT COALESCE(SUM(amount),0) s FROM private_expenses"
            " WHERE user_id=? AND substr(date,1,7)=?", (uid, month)).fetchone()["s"]
        combined = share + priv
        if combined > pb:
            out.append({"id": f"personal-over-{month}", "severity": "critical", "icon": "🔒",
                        "text": f"חרגת מהתקציב האישי — {ils(combined)} מתוך {ils(pb)}",
                        "tab": "personal"})
        elif combined >= 0.85 * pb:
            out.append({"id": f"personal-near-{month}", "severity": "warn", "icon": "🔒",
                        "text": f"התקציב האישי מתקרב לתקרה — {ils(combined)} מתוך {ils(pb)}",
                        "tab": "personal"})

    # חוב פתוח שלי מול השותפים
    mine = next((b["balance"] for b in compute_balances(hid) if b["id"] == uid), 0)
    if mine < -0.01:
        out.append({"id": "debt", "severity": "info", "icon": "💸",
                    "text": f"יש לך חוב פתוח של {ils(-mine)} לשותפים — אפשר לסגור בלשונית הוצאות",
                    "tab": "expenses"})

    # מטלות שהתור שלי
    my = [c["name"] for c in db().execute(
        "SELECT name FROM chores WHERE household_id=? AND assignee_id=? ORDER BY id", (hid, uid))]
    if my:
        names = ", ".join(my[:3]) + ("…" if len(my) > 3 else "")
        out.append({"id": f"chores-{len(my)}", "severity": "info", "icon": "🧽",
                    "text": f"התור שלך: {names}", "tab": "chores"})

    # קניות דחופות
    urgent = db().execute(
        "SELECT COUNT(*) c FROM shopping WHERE household_id=? AND done=0 AND urgent=1",
        (hid,)).fetchone()["c"]
    if urgent:
        out.append({"id": f"shopping-urgent-{urgent}", "severity": "info", "icon": "🛒",
                    "text": f"{urgent} פריטים דחופים מחכים ברשימת הקניות", "tab": "shopping"})

    rank = {"critical": 0, "warn": 1, "info": 2}
    out.sort(key=lambda n: rank[n["severity"]])
    return out


# ---------------------------------------------------------------- state

@app.get("/api/state")
@household_required
def state():
    month = request.args.get("month", "")
    if not MONTH_RE.match(month):
        return err("חודש לא תקין")
    hid = g.hid
    mem = [{"id": m["id"], "name": m["name"]} for m in members(hid)]
    names = {m["id"]: m["name"] for m in mem}

    spent = {
        r["category_id"]: r["s"]
        for r in db().execute(
            "SELECT category_id, SUM(amount) s FROM expenses"
            " WHERE household_id=? AND substr(date,1,7)=? GROUP BY category_id",
            (hid, month),
        )
    }
    categories = [
        {"id": c["id"], "name": c["name"], "budget": c["budget"],
         "spent": round(spent.get(c["id"], 0), 2)}
        for c in db().execute(
            "SELECT * FROM categories WHERE household_id=? ORDER BY id", (hid,)
        )
    ]
    cat_names = {c["id"]: c["name"] for c in categories}

    expenses = [
        {"id": e["id"], "date": e["date"], "descr": e["descr"], "amount": e["amount"],
         "category_id": e["category_id"], "category": cat_names.get(e["category_id"], "—"),
         "payer_id": e["payer_id"], "payer": names.get(e["payer_id"], "?"),
         "split_type": e["split_type"]}
        for e in db().execute(
            "SELECT * FROM expenses WHERE household_id=? AND substr(date,1,7)=?"
            " ORDER BY date DESC, id DESC",
            (hid, month),
        )
    ]

    balances = compute_balances(hid)
    transfers = suggest_transfers(balances)

    settlements = [
        {"id": s["id"], "date": s["date"], "amount": s["amount"],
         "from": names.get(s["from_id"], "?"), "to": names.get(s["to_id"], "?")}
        for s in db().execute(
            "SELECT * FROM settlements WHERE household_id=? ORDER BY date DESC, id DESC LIMIT 8",
            (hid,),
        )
    ]

    shopping = [
        {"id": s["id"], "name": s["name"], "note": s["note"], "urgent": bool(s["urgent"]),
         "done": bool(s["done"]), "added_by": names.get(s["added_by"], "?")}
        for s in db().execute(
            "SELECT * FROM shopping WHERE household_id=? ORDER BY done, urgent DESC, id", (hid,)
        )
    ]

    payments = {
        p["bill_id"]: p
        for p in db().execute(
            "SELECT * FROM bill_payments WHERE month=? AND bill_id IN"
            " (SELECT id FROM bills WHERE household_id=?)",
            (month, hid),
        )
    }
    bills = []
    for b in db().execute("SELECT * FROM bills WHERE household_id=? ORDER BY due_day, id", (hid,)):
        p = payments.get(b["id"])
        bills.append({
            "id": b["id"], "name": b["name"], "amount": b["amount"], "due_day": b["due_day"],
            "category_id": b["category_id"], "category": cat_names.get(b["category_id"], "—"),
            "paid": {"payer_id": p["payer_id"], "payer": names.get(p["payer_id"], "?")} if p else None,
        })

    chores = [
        {"id": c["id"], "name": c["name"], "freq": c["freq"],
         "assignee_id": c["assignee_id"], "assignee": names.get(c["assignee_id"], "?"),
         "last_done": c["last_done"]}
        for c in db().execute("SELECT * FROM chores WHERE household_id=? ORDER BY id", (hid,))
    ]

    # סכומים חודשיים ל־6 חודשים אחורה (לגרף)
    y, m = int(month[:4]), int(month[5:7])
    chart_months = []
    for i in range(5, -1, -1):
        mm = (m - 1 - i) % 12 + 1
        yy = y + (m - 1 - i - (mm - 1)) // 12
        chart_months.append(f"{yy:04d}-{mm:02d}")
    totals = {
        r["ym"]: round(r["s"], 2)
        for r in db().execute(
            "SELECT substr(date,1,7) ym, SUM(amount) s FROM expenses"
            " WHERE household_id=? AND substr(date,1,7)>=? GROUP BY ym",
            (hid, chart_months[0]),
        )
    }
    chart = [{"month": mth, "total": totals.get(mth, 0)} for mth in chart_months]
    prev_month = chart_months[-2] if len(chart_months) > 1 else None

    # --- האזור האישי: מחושב אך ורק עבור המשתמש המחובר ---
    uid = g.user["id"]
    private_expenses = [
        {"id": p["id"], "date": p["date"], "descr": p["descr"],
         "amount": p["amount"], "category": p["category"]}
        for p in db().execute(
            "SELECT * FROM private_expenses WHERE user_id=? AND substr(date,1,7)=?"
            " ORDER BY date DESC, id DESC",
            (uid, month),
        )
    ]
    priv_by_month = {
        r["ym"]: round(r["s"], 2)
        for r in db().execute(
            "SELECT substr(date,1,7) ym, SUM(amount) s FROM private_expenses"
            " WHERE user_id=? AND substr(date,1,7)>=? GROUP BY ym",
            (uid, chart_months[0]),
        )
    }
    share_by_month = {
        r["ym"]: round(r["s"], 2)
        for r in db().execute(
            "SELECT substr(e.date,1,7) ym, SUM(es.share) s FROM expense_shares es"
            " JOIN expenses e ON e.id=es.expense_id"
            " WHERE es.user_id=? AND e.household_id=? AND substr(e.date,1,7)>=? GROUP BY ym",
            (uid, hid, chart_months[0]),
        )
    }
    personal = {
        "budget": g.user["personal_budget"],
        "expenses": private_expenses,
        "private_total": priv_by_month.get(month, 0),
        "share_total": share_by_month.get(month, 0),
        "chart": [
            {"month": mth,
             "total": round(priv_by_month.get(mth, 0) + share_by_month.get(mth, 0), 2)}
            for mth in chart_months
        ],
        "categories": [
            r["category"] for r in db().execute(
                "SELECT DISTINCT category FROM private_expenses"
                " WHERE user_id=? AND category<>'' ORDER BY category",
                (uid,),
            )
        ],
    }

    hh = db().execute("SELECT * FROM households WHERE id=?", (hid,)).fetchone()
    return jsonify(
        user={"id": g.user["id"], "name": g.user["name"], "email": g.user["email"]},
        household={"id": hh["id"], "name": hh["name"], "invite_code": hh["invite_code"]},
        members=mem, month=month, categories=categories, expenses=expenses,
        balances=balances, transfers=transfers, settlements=settlements,
        shopping=shopping, bills=bills, chores=chores, chart=chart,
        total=totals.get(month, 0), prev_total=totals.get(prev_month, 0),
        personal=personal, bulletin=bulletin_notes(hid),
        notifications=build_notifications(hid, g.user["id"]),
    )


# ---------------------------------------------------------------- expenses

@app.post("/api/expenses")
@household_required
def add_expense():
    d = body()
    descr = (d.get("descr") or "").strip()
    date = d.get("date") or ""
    split = d.get("split_type") or "equal"
    try:
        amount = round(float(d.get("amount")), 2)
        payer_id = int(d.get("payer_id"))
        category_id = int(d.get("category_id"))
    except (TypeError, ValueError):
        return err("נתונים חסרים או לא תקינים")
    if not descr or len(descr) > 120:
        return err("נא להזין תיאור (עד 120 תווים)")
    if not (0 < amount <= 1_000_000):
        return err("סכום לא תקין")
    if not DATE_RE.match(date):
        return err("תאריך לא תקין")
    ids = member_ids(g.hid)
    if payer_id not in ids:
        return err("המשלם/ת אינו חבר/ה בדירה")
    if not db().execute(
        "SELECT 1 FROM categories WHERE id=? AND household_id=?", (category_id, g.hid)
    ).fetchone():
        return err("קטגוריה לא נמצאה")

    if split == "equal":
        shares = equal_shares(amount, ids, payer_id)
    elif split == "personal":
        shares = {payer_id: amount}
    elif split == "custom":
        raw = d.get("shares") or {}
        shares = {}
        try:
            for k, v in raw.items():
                uid, val = int(k), round(float(v), 2)
                if uid not in ids or val < 0:
                    return err("חלוקה לא תקינה")
                if val > 0:
                    shares[uid] = val
        except (TypeError, ValueError):
            return err("חלוקה לא תקינה")
        if abs(sum(shares.values()) - amount) > 0.02:
            return err("סכום החלוקה חייב להיות שווה לסכום ההוצאה")
    else:
        return err("סוג חלוקה לא מוכר")

    insert_expense(g.hid, date, descr, amount, category_id, payer_id, split, shares)
    return jsonify(ok=True)


@app.delete("/api/expenses/<int:eid>")
@household_required
def delete_expense(eid):
    row = db().execute(
        "SELECT id FROM expenses WHERE id=? AND household_id=?", (eid, g.hid)
    ).fetchone()
    if row is None:
        return err("הוצאה לא נמצאה", 404)
    db().execute("DELETE FROM bill_payments WHERE expense_id=?", (eid,))
    db().execute("DELETE FROM expenses WHERE id=?", (eid,))
    return jsonify(ok=True)


# ---------------------------------------------------------------- settlements

@app.post("/api/settlements")
@household_required
def add_settlement():
    d = body()
    date = d.get("date") or ""
    try:
        from_id, to_id = int(d.get("from_id")), int(d.get("to_id"))
        amount = round(float(d.get("amount")), 2)
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    ids = member_ids(g.hid)
    if from_id not in ids or to_id not in ids or from_id == to_id:
        return err("משתתפים לא תקינים")
    if not (0 < amount <= 1_000_000):
        return err("סכום לא תקין")
    if not DATE_RE.match(date):
        return err("תאריך לא תקין")
    db().execute(
        "INSERT INTO settlements(household_id,date,from_id,to_id,amount) VALUES (?,?,?,?,?)",
        (g.hid, date, from_id, to_id, amount),
    )
    return jsonify(ok=True)


@app.delete("/api/settlements/<int:sid>")
@household_required
def delete_settlement(sid):
    db().execute("DELETE FROM settlements WHERE id=? AND household_id=?", (sid, g.hid))
    return jsonify(ok=True)


# ---------------------------------------------------------------- categories

@app.post("/api/categories")
@household_required
def add_category():
    d = body()
    name = (d.get("name") or "").strip()
    if not name or len(name) > 40:
        return err("נא להזין שם קטגוריה (עד 40 תווים)")
    budget = max(0.0, float(d.get("budget") or 0))
    db().execute(
        "INSERT INTO categories(household_id,name,budget) VALUES (?,?,?)", (g.hid, name, budget)
    )
    return jsonify(ok=True)


@app.patch("/api/categories/<int:cid>")
@household_required
def update_category(cid):
    try:
        budget = max(0.0, float(body().get("budget")))
    except (TypeError, ValueError):
        return err("תקציב לא תקין")
    db().execute(
        "UPDATE categories SET budget=? WHERE id=? AND household_id=?", (budget, cid, g.hid)
    )
    return jsonify(ok=True)


@app.delete("/api/categories/<int:cid>")
@household_required
def delete_category(cid):
    used = db().execute(
        "SELECT 1 FROM expenses WHERE category_id=? AND household_id=? LIMIT 1", (cid, g.hid)
    ).fetchone() or db().execute(
        "SELECT 1 FROM bills WHERE category_id=? AND household_id=? LIMIT 1", (cid, g.hid)
    ).fetchone()
    if used:
        return err("אי אפשר למחוק — יש הוצאות או חשבונות שמשויכים לקטגוריה")
    db().execute("DELETE FROM categories WHERE id=? AND household_id=?", (cid, g.hid))
    return jsonify(ok=True)


# ---------------------------------------------------------------- shopping

@app.post("/api/shopping")
@household_required
def add_shopping():
    d = body()
    name = (d.get("name") or "").strip()
    if not name or len(name) > 80:
        return err("נא להזין שם פריט (עד 80 תווים)")
    db().execute(
        "INSERT INTO shopping(household_id,name,note,urgent,added_by) VALUES (?,?,?,?,?)",
        (g.hid, name, (d.get("note") or "").strip()[:80], 1 if d.get("urgent") else 0, g.user["id"]),
    )
    return jsonify(ok=True)


@app.patch("/api/shopping/<int:iid>")
@household_required
def toggle_shopping(iid):
    row = db().execute(
        "SELECT done FROM shopping WHERE id=? AND household_id=?", (iid, g.hid)
    ).fetchone()
    if row is None:
        return err("פריט לא נמצא", 404)
    db().execute("UPDATE shopping SET done=? WHERE id=?", (0 if row["done"] else 1, iid))
    return jsonify(ok=True)


@app.delete("/api/shopping/<int:iid>")
@household_required
def delete_shopping(iid):
    db().execute("DELETE FROM shopping WHERE id=? AND household_id=?", (iid, g.hid))
    return jsonify(ok=True)


@app.post("/api/shopping/finish")
@household_required
def finish_shopping():
    d = body()
    done = db().execute(
        "SELECT name FROM shopping WHERE household_id=? AND done=1 ORDER BY id", (g.hid,)
    ).fetchall()
    if not done:
        return err("אין פריטים מסומנים")
    exp = d.get("expense")
    if exp:
        try:
            amount = round(float(exp.get("amount")), 2)
            payer_id = int(exp.get("payer_id"))
            category_id = int(exp.get("category_id"))
        except (TypeError, ValueError):
            return err("נתוני הוצאה לא תקינים")
        date = exp.get("date") or ""
        if not (0 < amount <= 1_000_000) or not DATE_RE.match(date):
            return err("נתוני הוצאה לא תקינים")
        ids = member_ids(g.hid)
        if payer_id not in ids:
            return err("המשלם/ת אינו חבר/ה בדירה")
        if not db().execute(
            "SELECT 1 FROM categories WHERE id=? AND household_id=?", (category_id, g.hid)
        ).fetchone():
            return err("קטגוריה לא נמצאה")
        items = ", ".join(r["name"] for r in done)
        descr = "קניות: " + (items if len(items) <= 90 else items[:90] + "…")
        insert_expense(g.hid, date, descr, amount, category_id, payer_id, "equal",
                       equal_shares(amount, ids, payer_id))
    db().execute("DELETE FROM shopping WHERE household_id=? AND done=1", (g.hid,))
    return jsonify(ok=True)


# ---------------------------------------------------------------- recipes

RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "dish": {"type": "string"},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "note": {"type": "string"}},
                "required": ["name", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["dish", "ingredients"],
    "additionalProperties": False,
}

RECIPE_PROMPT = (
    "צור רשימת קניות עבור המנה: \"{dish}\".\n"
    "כללים: מצרכים לבישול ביתי ל-2-3 סועדים, בעברית. אל תכלול מים, מלח, פלפל שחור "
    "או דברים שיש בכל מטבח. בשדה note כתוב כמות קצרה (למשל: \"500 גרם\", \"2 יחידות\", "
    "\"קופסה\"). בשדה dish כתוב את שם המנה המנוקה. "
    "אם הטקסט אינו שם של מאכל אמיתי — החזר ingredients ריק."
)


def ai_recipe(dish):
    """מצרכים מ-Claude — פעיל רק כשמוגדרים פרטי גישה ל-API (ANTHROPIC_API_KEY).
    מחזיר {dish, ingredients} או None (אין גישה / שגיאה / לא מאכל)."""
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(timeout=30.0)
        response = client.messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
            max_tokens=2000,
            output_config={"format": {"type": "json_schema", "schema": RECIPE_SCHEMA}},
            messages=[{"role": "user", "content": RECIPE_PROMPT.format(dish=dish)}],
        )
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            return None
        data = json.loads(text)
        ingredients = [
            {"name": str(i.get("name", "")).strip()[:80], "note": str(i.get("note", "")).strip()[:80]}
            for i in data.get("ingredients", []) if str(i.get("name", "")).strip()
        ][:25]
        if not ingredients:
            return None
        return {"dish": (str(data.get("dish", "")).strip() or dish)[:80], "ingredients": ingredients}
    except Exception:
        return None


@app.post("/api/shopping/recipe")
@household_required
def recipe_lookup():
    dish_raw = (body().get("dish") or "").strip()
    if not dish_raw or len(dish_raw) > 80:
        return err("נא לכתוב מה בא לכם לאכול (עד 80 תווים)")
    hit = resolve_builtin(dish_raw)
    if hit:
        return jsonify(dish=hit["dish"], ingredients=hit["ingredients"], source="builtin")
    key = recipe_normalize(dish_raw)
    if not key:
        return err("נא לכתוב שם של מאכל")
    row = db().execute("SELECT payload FROM recipe_cache WHERE dish_key=?", (key,)).fetchone()
    if row:
        cached = json.loads(row["payload"])
        return jsonify(dish=cached["dish"], ingredients=cached["ingredients"], source="cache")
    ai = ai_recipe(key)
    if ai:
        db().execute(
            "INSERT OR REPLACE INTO recipe_cache(dish_key,payload) VALUES (?,?)",
            (key, json.dumps(ai, ensure_ascii=False)),
        )
        return jsonify(dish=ai["dish"], ingredients=ai["ingredients"], source="ai")
    return err(f'לא מצאתי מתכון ל"{dish_raw}" — נסו שם מנה נפוץ יותר, או הוסיפו פריטים ידנית', 404)


@app.post("/api/shopping/bulk")
@household_required
def add_shopping_bulk():
    items = body().get("items")
    if not isinstance(items, list) or not (1 <= len(items) <= 40):
        return err("רשימת פריטים לא תקינה")
    existing = {
        r["name"].strip() for r in db().execute(
            "SELECT name FROM shopping WHERE household_id=? AND done=0", (g.hid,)
        )
    }
    added = skipped = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()[:80]
        note = str(it.get("note") or "").strip()[:80]
        if not name:
            continue
        if name in existing:
            skipped += 1
            continue
        db().execute(
            "INSERT INTO shopping(household_id,name,note,urgent,added_by) VALUES (?,?,?,0,?)",
            (g.hid, name, note, g.user["id"]),
        )
        existing.add(name)
        added += 1
    return jsonify(ok=True, added=added, skipped=skipped)


# ---------------------------------------------------------------- bills

@app.post("/api/bills")
@household_required
def add_bill():
    d = body()
    name = (d.get("name") or "").strip()
    if not name or len(name) > 60:
        return err("נא להזין שם חשבון (עד 60 תווים)")
    try:
        amount = round(float(d.get("amount") or 0), 2)
        due_day = min(31, max(1, int(d.get("due_day") or 1)))
        category_id = int(d.get("category_id"))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    if not db().execute(
        "SELECT 1 FROM categories WHERE id=? AND household_id=?", (category_id, g.hid)
    ).fetchone():
        return err("קטגוריה לא נמצאה")
    db().execute(
        "INSERT INTO bills(household_id,name,amount,due_day,category_id) VALUES (?,?,?,?,?)",
        (g.hid, name, amount, due_day, category_id),
    )
    return jsonify(ok=True)


@app.post("/api/bills/<int:bid>/pay")
@household_required
def pay_bill(bid):
    d = body()
    month = d.get("month") or ""
    if not MONTH_RE.match(month):
        return err("חודש לא תקין")
    try:
        payer_id = int(d.get("payer_id"))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    ids = member_ids(g.hid)
    if payer_id not in ids:
        return err("המשלם/ת אינו חבר/ה בדירה")
    b = db().execute(
        "SELECT * FROM bills WHERE id=? AND household_id=?", (bid, g.hid)
    ).fetchone()
    if b is None:
        return err("חשבון לא נמצא", 404)
    if db().execute(
        "SELECT 1 FROM bill_payments WHERE bill_id=? AND month=?", (bid, month)
    ).fetchone():
        return err("החשבון כבר סומן כשולם לחודש הזה")
    date = f"{month}-{min(b['due_day'], 28):02d}"
    eid = insert_expense(g.hid, date, b["name"], b["amount"], b["category_id"],
                         payer_id, "equal", equal_shares(b["amount"], ids, payer_id))
    db().execute(
        "INSERT INTO bill_payments(bill_id,month,payer_id,expense_id) VALUES (?,?,?,?)",
        (bid, month, payer_id, eid),
    )
    return jsonify(ok=True)


@app.post("/api/bills/<int:bid>/unpay")
@household_required
def unpay_bill(bid):
    month = body().get("month") or ""
    if not MONTH_RE.match(month):
        return err("חודש לא תקין")
    p = db().execute(
        "SELECT bp.* FROM bill_payments bp JOIN bills b ON b.id=bp.bill_id"
        " WHERE bp.bill_id=? AND bp.month=? AND b.household_id=?",
        (bid, month, g.hid),
    ).fetchone()
    if p is None:
        return err("לא נמצא תשלום לביטול", 404)
    db().execute("DELETE FROM bill_payments WHERE bill_id=? AND month=?", (bid, month))
    if p["expense_id"]:
        db().execute("DELETE FROM expenses WHERE id=? AND household_id=?", (p["expense_id"], g.hid))
    return jsonify(ok=True)


@app.delete("/api/bills/<int:bid>")
@household_required
def delete_bill(bid):
    db().execute("DELETE FROM bills WHERE id=? AND household_id=?", (bid, g.hid))
    return jsonify(ok=True)


# ---------------------------------------------------------------- chores

@app.post("/api/chores")
@household_required
def add_chore():
    d = body()
    name = (d.get("name") or "").strip()
    if not name or len(name) > 60:
        return err("נא להזין שם מטלה (עד 60 תווים)")
    try:
        assignee_id = int(d.get("assignee_id"))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    if assignee_id not in member_ids(g.hid):
        return err("המשויך/ת אינו חבר/ה בדירה")
    db().execute(
        "INSERT INTO chores(household_id,name,freq,assignee_id) VALUES (?,?,?,?)",
        (g.hid, name, (d.get("freq") or "שבועי").strip()[:30] or "שבועי", assignee_id),
    )
    return jsonify(ok=True)


@app.post("/api/chores/<int:cid>/done")
@household_required
def done_chore(cid):
    date = body().get("date") or ""
    if not DATE_RE.match(date):
        return err("תאריך לא תקין")
    c = db().execute(
        "SELECT * FROM chores WHERE id=? AND household_id=?", (cid, g.hid)
    ).fetchone()
    if c is None:
        return err("מטלה לא נמצאה", 404)
    ids = member_ids(g.hid)
    try:
        nxt = ids[(ids.index(c["assignee_id"]) + 1) % len(ids)]
    except ValueError:
        nxt = ids[0]
    db().execute("UPDATE chores SET last_done=?, assignee_id=? WHERE id=?", (date, nxt, cid))
    return jsonify(ok=True)


@app.delete("/api/chores/<int:cid>")
@household_required
def delete_chore(cid):
    db().execute("DELETE FROM chores WHERE id=? AND household_id=?", (cid, g.hid))
    return jsonify(ok=True)


# ---------------------------------------------------------------- bulletin board

@app.get("/api/bulletin")
@household_required
def get_bulletin():
    return jsonify(notes=bulletin_notes(g.hid))


@app.post("/api/bulletin")
@household_required
def add_bulletin_note():
    d = body()
    content = (d.get("content") or "").strip()
    if not content or len(content) > 300:
        return err("נא לכתוב תוכן למודעה (עד 300 תווים)")
    db().execute(
        "INSERT INTO bulletin_board(household_id,user_id,content,is_pinned) VALUES (?,?,?,?)",
        (g.hid, g.user["id"], content, 1 if d.get("is_pinned") else 0),
    )
    return jsonify(ok=True)


@app.delete("/api/bulletin/<int:nid>")
@household_required
def delete_bulletin_note(nid):
    # לוח משותף — כל חבר בדירה רשאי למחוק כל מודעה
    cur = db().execute(
        "DELETE FROM bulletin_board WHERE id=? AND household_id=?", (nid, g.hid)
    )
    if cur.rowcount == 0:
        return err("מודעה לא נמצאה", 404)
    return jsonify(ok=True)


# ---------------------------------------------------------------- personal (private)

@app.post("/api/personal")
@login_required
def add_private_expense():
    d = body()
    descr = (d.get("descr") or "").strip()
    date = d.get("date") or ""
    category = (d.get("category") or "").strip()[:40]
    try:
        amount = round(float(d.get("amount")), 2)
    except (TypeError, ValueError):
        return err("סכום לא תקין")
    if not descr or len(descr) > 120:
        return err("נא להזין תיאור (עד 120 תווים)")
    if not (0 < amount <= 1_000_000):
        return err("סכום לא תקין")
    if not DATE_RE.match(date):
        return err("תאריך לא תקין")
    db().execute(
        "INSERT INTO private_expenses(user_id,date,descr,amount,category) VALUES (?,?,?,?,?)",
        (g.user["id"], date, descr, amount, category),
    )
    return jsonify(ok=True)


@app.delete("/api/personal/<int:pid>")
@login_required
def delete_private_expense(pid):
    cur = db().execute(
        "DELETE FROM private_expenses WHERE id=? AND user_id=?", (pid, g.user["id"])
    )
    if cur.rowcount == 0:
        return err("הוצאה לא נמצאה", 404)
    return jsonify(ok=True)


@app.post("/api/me/budget")
@login_required
def set_personal_budget():
    try:
        budget = max(0.0, float(body().get("budget")))
    except (TypeError, ValueError):
        return err("תקציב לא תקין")
    db().execute("UPDATE users SET personal_budget=? WHERE id=?", (budget, g.user["id"]))
    return jsonify(ok=True)


# ---------------------------------------------------------------- export & pages

@app.get("/api/export")
@household_required
def export_data():
    hid = g.hid

    def rows(sql, *args):
        return [dict(r) for r in db().execute(sql, args)]

    payload = {
        "household": rows("SELECT id,name,created_at FROM households WHERE id=?", hid)[0],
        "members": rows("SELECT id,name,joined_at FROM users WHERE household_id=?", hid),
        "categories": rows("SELECT * FROM categories WHERE household_id=?", hid),
        "expenses": rows("SELECT * FROM expenses WHERE household_id=?", hid),
        "expense_shares": rows(
            "SELECT es.* FROM expense_shares es JOIN expenses e ON e.id=es.expense_id"
            " WHERE e.household_id=?", hid),
        "settlements": rows("SELECT * FROM settlements WHERE household_id=?", hid),
        "shopping": rows("SELECT * FROM shopping WHERE household_id=?", hid),
        "bills": rows("SELECT * FROM bills WHERE household_id=?", hid),
        "bill_payments": rows(
            "SELECT bp.* FROM bill_payments bp JOIN bills b ON b.id=bp.bill_id"
            " WHERE b.household_id=?", hid),
        "chores": rows("SELECT * FROM chores WHERE household_id=?", hid),
        # פרטי בלבד: רק של המשתמש שמייצא — לא של שאר החברים
        "my_private_expenses": rows(
            "SELECT * FROM private_expenses WHERE user_id=?", g.user["id"]),
    }
    resp = jsonify(payload)
    resp.headers["Content-Disposition"] = "attachment; filename=home-backup.json"
    return resp


@app.get("/")
def index():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    try:
        from waitress import serve
        print(f"* Serving on http://localhost:{port} (waitress)")
        serve(app, host="0.0.0.0", port=port)
    except ImportError:
        app.run(host="0.0.0.0", port=port)
