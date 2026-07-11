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
