# -*- coding: utf-8 -*-
"""Data access for the ``users`` table."""
from __future__ import annotations

from kaza.db import Row, get_db


def get_by_id(user_id: int) -> Row | None:
    """Return the full user row for ``user_id``, or ``None``."""
    return get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def get_by_email(email: str) -> Row | None:
    """Return the full user row for ``email`` (already normalised), or ``None``."""
    return get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()


def email_exists(email: str) -> bool:
    """True if a user is already registered with ``email``."""
    return get_db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone() is not None


def create(name: str, email: str, pw_hash: str) -> int:
    """Insert a new user and return its id."""
    cur = get_db().execute(
        "INSERT INTO users(name,email,pw_hash) VALUES (?,?,?)",
        (name, email, pw_hash),
    )
    return cur.lastrowid


def set_household(user_id: int, household_id: int) -> None:
    """Attach ``user_id`` to a household and stamp their join time."""
    get_db().execute(
        "UPDATE users SET household_id=?, joined_at=datetime('now') WHERE id=?",
        (household_id, user_id),
    )


def set_personal_budget(user_id: int, budget: float) -> None:
    """Set the user's private monthly budget."""
    get_db().execute("UPDATE users SET personal_budget=? WHERE id=?", (budget, user_id))


def get_personal_budget(user_id: int) -> float:
    """Return the user's private monthly budget (0 when unset)."""
    row = get_db().execute("SELECT personal_budget FROM users WHERE id=?", (user_id,)).fetchone()
    return row["personal_budget"] if row else 0
