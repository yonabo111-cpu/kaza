# -*- coding: utf-8 -*-
"""Data access for the rotating ``chores`` list."""
from __future__ import annotations

from kaza.db import Row, get_db


def list_for(household_id: int) -> list[Row]:
    """Return the household's chores ordered by id."""
    return get_db().execute(
        "SELECT * FROM chores WHERE household_id=? ORDER BY id", (household_id,)
    ).fetchall()


def create(household_id: int, name: str, freq: str, assignee_id: int) -> None:
    """Add a chore assigned to ``assignee_id``."""
    get_db().execute(
        "INSERT INTO chores(household_id,name,freq,assignee_id) VALUES (?,?,?,?)",
        (household_id, name, freq, assignee_id),
    )


def get(chore_id: int, household_id: int) -> Row | None:
    """Return a chore row if it belongs to the household."""
    return get_db().execute(
        "SELECT * FROM chores WHERE id=? AND household_id=?", (chore_id, household_id)
    ).fetchone()


def reassign(chore_id: int, assignee_id: int, last_done: str) -> None:
    """Record completion and hand the chore to the next member."""
    get_db().execute(
        "UPDATE chores SET last_done=?, assignee_id=? WHERE id=?",
        (last_done, assignee_id, chore_id),
    )


def delete(chore_id: int, household_id: int) -> None:
    """Delete a chore."""
    get_db().execute(
        "DELETE FROM chores WHERE id=? AND household_id=?", (chore_id, household_id)
    )


def assigned_to(household_id: int, user_id: int) -> list[Row]:
    """Return the names of chores currently assigned to ``user_id``."""
    return get_db().execute(
        "SELECT name FROM chores WHERE household_id=? AND assignee_id=? ORDER BY id",
        (household_id, user_id),
    ).fetchall()
