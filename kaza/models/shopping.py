# -*- coding: utf-8 -*-
"""Data access for the shared ``shopping`` list."""
from __future__ import annotations

from kaza.db import Row, get_db


def list_for(household_id: int) -> list[Row]:
    """Return the shopping list: open items first, urgent before regular."""
    return get_db().execute(
        "SELECT * FROM shopping WHERE household_id=? ORDER BY done, urgent DESC, id",
        (household_id,),
    ).fetchall()


def create(household_id: int, name: str, note: str, urgent: bool, added_by: int) -> None:
    """Add an item to the shopping list."""
    get_db().execute(
        "INSERT INTO shopping(household_id,name,note,urgent,added_by) VALUES (?,?,?,?,?)",
        (household_id, name, note, 1 if urgent else 0, added_by),
    )


def get_done_flag(item_id: int, household_id: int) -> Row | None:
    """Return the item's ``done`` flag row if it belongs to the household."""
    return get_db().execute(
        "SELECT done FROM shopping WHERE id=? AND household_id=?", (item_id, household_id)
    ).fetchone()


def set_done(item_id: int, done: bool) -> None:
    """Set an item's done flag."""
    get_db().execute("UPDATE shopping SET done=? WHERE id=?", (1 if done else 0, item_id))


def delete(item_id: int, household_id: int) -> None:
    """Remove a single item from the list."""
    get_db().execute(
        "DELETE FROM shopping WHERE id=? AND household_id=?", (item_id, household_id)
    )


def done_names(household_id: int) -> list[Row]:
    """Return the names of checked-off items, ordered by id."""
    return get_db().execute(
        "SELECT name FROM shopping WHERE household_id=? AND done=1 ORDER BY id", (household_id,)
    ).fetchall()


def delete_done(household_id: int) -> None:
    """Clear all checked-off items."""
    get_db().execute("DELETE FROM shopping WHERE household_id=? AND done=1", (household_id,))


def open_item_names(household_id: int) -> set[str]:
    """Return the set of names of currently open (not done) items."""
    return {
        r["name"].strip()
        for r in get_db().execute(
            "SELECT name FROM shopping WHERE household_id=? AND done=0", (household_id,)
        )
    }


def urgent_open_count(household_id: int) -> int:
    """Return how many urgent, not-yet-bought items are on the list."""
    return get_db().execute(
        "SELECT COUNT(*) c FROM shopping WHERE household_id=? AND done=0 AND urgent=1",
        (household_id,),
    ).fetchone()["c"]
