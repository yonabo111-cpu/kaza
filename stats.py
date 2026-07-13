#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kaza usage report — a quick, read-only snapshot of who signed up and how
active they are. Handy for tracking engagement while friends test the live app.

Run it on the server (PythonAnywhere → Consoles → Bash):

    cd ~/kaza && python3 stats.py

It opens the SQLite database read-only, so it never locks or changes live data.
Point it at a different database by passing a path:

    python3 stats.py /path/to/app.db
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

# The database sits next to this script, under data/app.db (same as the app).
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db")

W = 54  # report width


def connect(path: str) -> sqlite3.Connection:
    """Open the database read-only so we can never touch live data."""
    if not os.path.exists(path):
        sys.exit(
            f"\n⚠  לא נמצא מסד נתונים בנתיב:\n   {path}\n"
            "   (הקובץ נוצר בהרשמה הראשונה — ודא שמישהו כבר נרשם.)\n"
        )
    try:
        uri = f"{pathlib.Path(os.path.abspath(path)).as_uri()}?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except Exception:
        return sqlite3.connect(path)  # fallback: still SELECT-only below


def shk(amount: float) -> str:
    """Format a shekel amount."""
    return f"{amount:,.0f} ₪"


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    con = connect(path)
    con.row_factory = sqlite3.Row

    def rows(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return con.execute(sql, params).fetchall()

    def scalar(sql: str, params: tuple = ()) -> float:
        return con.execute(sql, params).fetchone()[0]

    def section(title: str) -> None:
        print("\n" + title)
        print("─" * W)

    print("═" * W)
    print("  📊  דוח שימוש — קאזה")
    print(f"  {datetime.now():%Y-%m-%d %H:%M}")
    print("═" * W)

    users = scalar("SELECT COUNT(*) FROM users")
    section("📈  סקירה כללית")
    print(f"  נרשמו:               {users}")
    print(f"  דירות:               {scalar('SELECT COUNT(*) FROM households')}")
    orphans = scalar("SELECT COUNT(*) FROM users WHERE household_id IS NULL")
    if orphans:
        print(f"  נרשמו בלי דירה:       {orphans}   ← לא הצטרפו/פתחו דירה")
    exp_n = scalar("SELECT COUNT(*) FROM expenses")
    exp_sum = scalar("SELECT COALESCE(SUM(amount),0) FROM expenses")
    print(f"  הוצאות משותפות:       {exp_n}  (סך הכול {shk(exp_sum)})")
    print(f"  הוצאות פרטיות:        {scalar('SELECT COUNT(*) FROM private_expenses')}")
    print(f"  פריטי קניות:          {scalar('SELECT COUNT(*) FROM shopping')}")
    print(f"  מודעות בלוח:          {scalar('SELECT COUNT(*) FROM bulletin_board')}")
    print(f"  חשבונות קבועים:       {scalar('SELECT COUNT(*) FROM bills')}")
    print(f"  מטלות:               {scalar('SELECT COUNT(*) FROM chores')}")
    print(f"  התחשבנויות שנסגרו:    {scalar('SELECT COUNT(*) FROM settlements')}")

    if users == 0:
        print("\n  אין עדיין נרשמים — שתף את הלינק והקוד וזה יתחיל להתמלא 🚀\n")
        return

    signups = rows(
        "SELECT substr(created_at,1,10) AS day, COUNT(*) AS n FROM users GROUP BY day ORDER BY day"
    )
    if signups:
        section("🗓  הרשמות לפי יום")
        for r in signups:
            print(f"  {r['day']}   {'█' * r['n']} {r['n']}")

    recent = rows(
        "SELECT u.name, u.email, u.created_at, h.name AS hh "
        "FROM users u LEFT JOIN households h ON h.id = u.household_id "
        "ORDER BY u.created_at DESC LIMIT 8"
    )
    section("🆕  נרשמו לאחרונה")
    for r in recent:
        when, name, email = r["created_at"][:16], r["name"][:14], r["email"][:26]
        print(f"  {when}   {name:<14}  {email:<26}  {r['hh'] or '—'}")

    houses = rows(
        "SELECT h.name, h.invite_code, "
        "  (SELECT COUNT(*) FROM users u WHERE u.household_id = h.id) AS members, "
        "  (SELECT COUNT(*) FROM expenses e WHERE e.household_id = h.id) AS exp, "
        "  (SELECT COALESCE(SUM(amount),0) FROM expenses e WHERE e.household_id = h.id) AS total "
        "FROM households h ORDER BY members DESC"
    )
    if houses:
        section("🏠  דירות")
        for r in houses:
            print(
                f"  {r['name'][:18]:<18} קוד {r['invite_code']}  ·  "
                f"{r['members']} חברים  ·  {r['exp']} הוצאות ({shk(r['total'])})"
            )

    # Merge per-user activity across the shared-household tables.
    act: dict[int, dict] = {}

    def bump(uid, key, val=1):
        if uid is None:
            return
        act.setdefault(uid, {"exp": 0, "paid": 0.0, "shop": 0, "notes": 0})[key] += val

    for r in rows(
        "SELECT payer_id, COUNT(*) n, COALESCE(SUM(amount),0) s FROM expenses GROUP BY payer_id"
    ):
        bump(r["payer_id"], "exp", r["n"])
        bump(r["payer_id"], "paid", r["s"])
    for r in rows("SELECT added_by, COUNT(*) n FROM shopping GROUP BY added_by"):
        bump(r["added_by"], "shop", r["n"])
    for r in rows("SELECT user_id, COUNT(*) n FROM bulletin_board GROUP BY user_id"):
        bump(r["user_id"], "notes", r["n"])

    names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM users")}
    section("🏆  החברים הכי פעילים")
    if not act:
        print("  אין עדיין פעילות מתועדת.")
    else:
        print(f"  {'שם':<14} {'הוצאות':>7} {'שילם':>9} {'קניות':>7} {'מודעות':>7}")
        ranked = sorted(
            act.items(), key=lambda kv: kv[1]["exp"] + kv[1]["shop"] + kv[1]["notes"], reverse=True
        )
        for uid, d in ranked[:10]:
            name = (names.get(uid) or "?")[:14]
            print(f"  {name:<14} {d['exp']:>7} {d['paid']:>9,.0f} {d['shop']:>7} {d['notes']:>7}")

    print()


if __name__ == "__main__":
    main()
