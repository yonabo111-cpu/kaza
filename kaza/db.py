# -*- coding: utf-8 -*-
"""Database access layer.

A thin abstraction over the connection so the rest of the app is written
against a single ``get_db()`` accessor. SQLite is the default; setting
``DATABASE_URL`` to a ``postgres://`` URL selects PostgreSQL (wired here,
schema-compatibility completed in a later phase). The connection is stored on
Flask's request-scoped ``g`` and committed once per successful request.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Mapping

from flask import Flask, current_app, g

# A DB row behaves like a read-only mapping regardless of driver.
Row = Mapping[str, Any]

# Full schema (idempotent). Kept SQLite-flavoured; the connection factory is
# responsible for adapting it when another driver is selected.
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
  category_id INTEGER REFERENCES categories(id),
  bill_type TEXT NOT NULL DEFAULT 'equal'
    CHECK(bill_type IN ('equal','individual','private')),
  owner_id INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS bill_payments(
  bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  month TEXT NOT NULL,
  payer_id INTEGER NOT NULL REFERENCES users(id),
  expense_id INTEGER REFERENCES expenses(id),
  private_expense_id INTEGER REFERENCES private_expenses(id),
  PRIMARY KEY(bill_id, month, payer_id)
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
CREATE TABLE IF NOT EXISTS password_resets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Indexes that back the app's hottest lookups (all keyed by household/user).
# Creating them is idempotent and safe on every startup.
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_users_household ON users(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_categories_household ON categories(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_expenses_household_date ON expenses(household_id, date)",
    "CREATE INDEX IF NOT EXISTS idx_expense_shares_user ON expense_shares(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_settlements_household ON settlements(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_shopping_household ON shopping(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_bills_household ON bills(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_chores_household ON chores(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_private_user_date ON private_expenses(user_id, date)",
    "CREATE INDEX IF NOT EXISTS idx_bulletin_household ON bulletin_board(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_password_resets_token ON password_resets(token_hash)",
]


def using_postgres() -> bool:
    """True when a PostgreSQL connection URL is configured."""
    url = os.environ.get("DATABASE_URL", "")
    return url.startswith(("postgres://", "postgresql://"))


def _connect_sqlite(path: str) -> sqlite3.Connection:
    """Open a SQLite connection with row-mapping access and FK enforcement."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    """Return the request-scoped database connection, opening it on first use."""
    if "_db" not in g:
        g._db = _connect_sqlite(current_app.config["DB_PATH"])
    return g._db


def close_db(exc: BaseException | None = None) -> None:
    """Commit on a clean request, then close. On error, close without commit."""
    conn = g.pop("_db", None)
    if conn is not None:
        if exc is None:
            conn.commit()
        conn.close()


def init_db(app: Flask) -> None:
    """Create tables and indexes, and apply lightweight in-place migrations."""
    path = app.config["DB_PATH"]
    conn = _connect_sqlite(path)
    try:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
        for statement in INDEXES:
            conn.execute(statement)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Additive schema changes that keep existing databases compatible."""
    user_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
    if "personal_budget" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN personal_budget REAL NOT NULL DEFAULT 0")

    # Bill types: 'equal' (one payer, split between all), 'individual' (each
    # member pays their own), 'private' (visible to its owner only).
    bill_cols = [row[1] for row in conn.execute("PRAGMA table_info(bills)")]
    if "bill_type" not in bill_cols:
        conn.execute("ALTER TABLE bills ADD COLUMN bill_type TEXT NOT NULL DEFAULT 'equal'")
    if "owner_id" not in bill_cols:
        conn.execute("ALTER TABLE bills ADD COLUMN owner_id INTEGER REFERENCES users(id)")

    # bill_payments: individual bills need one payment row per member per
    # month, so the primary key must include payer_id; private-bill payments
    # link to the private ledger instead of the shared expenses table.
    payment_cols = [row[1] for row in conn.execute("PRAGMA table_info(bill_payments)")]
    if "private_expense_id" not in payment_cols:
        conn.execute("ALTER TABLE bill_payments RENAME TO bill_payments_old")
        conn.execute(
            "CREATE TABLE bill_payments("
            " bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,"
            " month TEXT NOT NULL,"
            " payer_id INTEGER NOT NULL REFERENCES users(id),"
            " expense_id INTEGER REFERENCES expenses(id),"
            " private_expense_id INTEGER REFERENCES private_expenses(id),"
            " PRIMARY KEY(bill_id, month, payer_id))"
        )
        conn.execute(
            "INSERT INTO bill_payments(bill_id, month, payer_id, expense_id)"
            " SELECT bill_id, month, payer_id, expense_id FROM bill_payments_old"
        )
        conn.execute("DROP TABLE bill_payments_old")
