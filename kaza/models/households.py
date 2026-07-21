# -*- coding: utf-8 -*-
"""Data access for the ``households`` table and household membership."""

from __future__ import annotations

from kaza.db import Row, get_db


def get(household_id: int) -> Row | None:
    """Return the household row, or ``None``."""
    return get_db().execute("SELECT * FROM households WHERE id=?", (household_id,)).fetchone()


def create(name: str, invite_code: str) -> int:
    """Insert a new household and return its id."""
    cur = get_db().execute(
        "INSERT INTO households(name,invite_code) VALUES (?,?)", (name, invite_code)
    )
    return cur.lastrowid


def find_by_invite(code: str) -> Row | None:
    """Return the household row matching an invite ``code``, or ``None``."""
    return get_db().execute("SELECT id FROM households WHERE invite_code=?", (code,)).fetchone()


def invite_code_exists(code: str) -> bool:
    """True if an invite ``code`` is already in use."""
    return (
        get_db().execute("SELECT 1 FROM households WHERE invite_code=?", (code,)).fetchone()
        is not None
    )


def delete_cascade(household_id: int) -> None:
    """Delete a household and every row scoped to it (used on solo account delete).

    Bills are removed before expenses so their payment rows (which reference
    expenses) cascade away first; child rows fall away via ON DELETE CASCADE.
    Callers must first detach any remaining member so no user row references it.
    """
    db = get_db()
    db.execute("DELETE FROM bills WHERE household_id=?", (household_id,))  # cascades bill_payments
    db.execute("DELETE FROM expenses WHERE household_id=?", (household_id,))  # cascades shares
    db.execute("DELETE FROM settlements WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM shopping WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM chores WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM bulletin_board WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM categories WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM households WHERE id=?", (household_id,))


def members(household_id: int) -> list[Row]:
    """Return household members ordered by join time then id."""
    return (
        get_db()
        .execute(
            "SELECT id, name, joined_at FROM users WHERE household_id=? ORDER BY joined_at, id",
            (household_id,),
        )
        .fetchall()
    )
