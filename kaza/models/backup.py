# -*- coding: utf-8 -*-
"""Read-only household export for the JSON backup feature."""
from __future__ import annotations

from typing import Any

from kaza.db import get_db


def export_household(household_id: int, user_id: int) -> dict[str, Any]:
    """Return a full JSON-serialisable snapshot of one household.

    Private expenses are limited to ``user_id`` — a backup never includes any
    other member's private ledger.
    """
    def rows(sql: str, *args: Any) -> list[dict]:
        return [dict(r) for r in get_db().execute(sql, args)]

    return {
        "household": rows("SELECT id,name,created_at FROM households WHERE id=?", household_id)[0],
        "members": rows("SELECT id,name,joined_at FROM users WHERE household_id=?", household_id),
        "categories": rows("SELECT * FROM categories WHERE household_id=?", household_id),
        "expenses": rows("SELECT * FROM expenses WHERE household_id=?", household_id),
        "expense_shares": rows(
            "SELECT es.* FROM expense_shares es JOIN expenses e ON e.id=es.expense_id"
            " WHERE e.household_id=?", household_id),
        "settlements": rows("SELECT * FROM settlements WHERE household_id=?", household_id),
        "shopping": rows("SELECT * FROM shopping WHERE household_id=?", household_id),
        "bills": rows("SELECT * FROM bills WHERE household_id=?", household_id),
        "bill_payments": rows(
            "SELECT bp.* FROM bill_payments bp JOIN bills b ON b.id=bp.bill_id"
            " WHERE b.household_id=?", household_id),
        "chores": rows("SELECT * FROM chores WHERE household_id=?", household_id),
        "my_private_expenses": rows(
            "SELECT * FROM private_expenses WHERE user_id=?", user_id),
    }
