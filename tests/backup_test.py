# -*- coding: utf-8 -*-
"""Backup & restore tests for backup.py.

Self-contained: builds its own throwaway SQLite database on disk, so it needs
no running server. Run directly or via tests/run_all.py.

    python tests/backup_test.py
"""

import os
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import backup  # noqa: E402  (path set up above)

PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


def _make_db(path, rows):
    """Create a tiny users table with ``rows`` names, using WAL like production."""
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    con.executemany("INSERT INTO users(name) VALUES (?)", [(n,) for n in rows])
    con.commit()
    con.close()


def _count(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        con.close()


work = tempfile.mkdtemp(prefix="kaza-backup-test-")
db = os.path.join(work, "app.db")

# --- backup of a missing database fails cleanly -----------------------------
try:
    backup.create_backup(db)
    check("missing db raises", False)
except FileNotFoundError:
    check("missing db raises", True)

# --- a snapshot captures current data and passes its integrity check --------
_make_db(db, ["מאיה", "איתי", "נועה"])
snap1 = backup.create_backup(db)
check("snapshot file created", os.path.exists(snap1))
check("snapshot lands in data/backups", os.path.basename(os.path.dirname(snap1)) == "backups")
check("snapshot row count matches source", _count(snap1) == 3)
check("snapshot passes integrity check", backup._integrity_ok(snap1))

# --- a snapshot is a frozen point in time -----------------------------------
con = sqlite3.connect(db)
con.execute("INSERT INTO users(name) VALUES ('דניאל')")
con.commit()
con.close()
check("live db moved on to 4 rows", _count(db) == 4)
check("old snapshot still shows 3 rows", _count(snap1) == 3)

snap2 = backup.create_backup(db)
check("second snapshot has the new row", _count(snap2) == 4)
check("list returns both, newest first", backup.list_backups(db)[0] == snap2)

# --- restore rewinds the live db and safety-copies the current one ----------
# (Done before rotation so the snapshot we restore from is still on disk.)
before = _count(db)  # 4
safety = backup.restore_backup(snap1, db)  # snap1 held 3 rows
check("restore rewinds live db to snapshot", _count(db) == 3)
check("restore left a pre-restore safety copy", os.path.exists(safety))
check("safety copy preserved the pre-restore state", _count(safety) == before)
check("db still usable after restore (WAL sidecars cleared)", backup._integrity_ok(db))

# --- restore refuses a corrupt file -----------------------------------------
junk = os.path.join(work, "corrupt.db")
with open(junk, "wb") as fh:
    fh.write(b"this is not a sqlite database at all")
try:
    backup.restore_backup(junk, db)
    check("corrupt restore refused", False)
except ValueError:
    check("corrupt restore refused", True)
check("live db untouched after refused restore", _count(db) == 3)

# --- rotation keeps only the newest N (run last: it prunes old snapshots) ----
for _ in range(5):
    backup.create_backup(db, keep=3)
check("rotation keeps exactly N", len(backup.list_backups(db)) == 3)
check("pre-restore safety copies are never pruned", os.path.exists(safety))

print(f"ALL {len(PASSED)} CHECKS PASSED")
