# -*- coding: utf-8 -*-
"""Connection-factory tests: every SQLite connection enforces the right pragmas.

Server-less. Run directly or via tests/run_all.py.

    python tests/db_test.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from kaza.db import _connect_sqlite  # noqa: E402

PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


db_path = os.path.join(tempfile.mkdtemp(prefix="kaza-db-test-"), "t.db")
conn = _connect_sqlite(db_path)

check("foreign keys enforced", conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1)
check(
    "busy_timeout set to 5000ms so writers wait instead of erroring",
    conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000,
)

# Rows behave like read-only mappings (accessible by column name).
conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, name TEXT)")
conn.execute("INSERT INTO t(name) VALUES ('x')")
check(
    "row is mapping-accessible by column name",
    conn.execute("SELECT * FROM t").fetchone()["name"] == "x",
)

# A foreign-key violation is actually rejected (proves the pragma is live).
conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
conn.execute("CREATE TABLE child(pid INTEGER REFERENCES parent(id))")
try:
    conn.execute("INSERT INTO child(pid) VALUES (999)")
    check("foreign-key violation rejected", False)
except Exception:
    check("foreign-key violation rejected", True)

conn.close()
print(f"ALL {len(PASSED)} CHECKS PASSED")
