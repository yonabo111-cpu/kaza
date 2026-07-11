# -*- coding: utf-8 -*-
"""Data access for the ``bulletin_board`` (shared sticky notes)."""
from __future__ import annotations

from kaza.db import Row, get_db


def list_for(household_id: int) -> list[Row]:
    """Return the household's notes: pinned first, then newest to oldest."""
    return get_db().execute(
        "SELECT * FROM bulletin_board WHERE household_id=?"
        " ORDER BY is_pinned DESC, created_at DESC, id DESC",
        (household_id,),
    ).fetchall()


def create(household_id: int, user_id: int, content: str, is_pinned: bool) -> None:
    """Post a note authored by ``user_id``."""
    get_db().execute(
        "INSERT INTO bulletin_board(household_id,user_id,content,is_pinned) VALUES (?,?,?,?)",
        (household_id, user_id, content, 1 if is_pinned else 0),
    )


def delete(note_id: int, household_id: int) -> int:
    """Delete a note from the shared board; return affected row count."""
    cur = get_db().execute(
        "DELETE FROM bulletin_board WHERE id=? AND household_id=?", (note_id, household_id)
    )
    return cur.rowcount
