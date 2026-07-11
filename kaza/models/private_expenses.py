# -*- coding: utf-8 -*-
"""Data access for ``private_expenses`` — a per-user, never-shared ledger.

Every query is scoped by ``user_id``; these rows must never surface to any
other household member on any endpoint.
"""

from __future__ import annotations

from kaza.db import Row, get_db


def create(user_id: int, date: str, descr: str, amount: float, category: str) -> None:
    """Add a private expense owned by ``user_id``."""
    get_db().execute(
        "INSERT INTO private_expenses(user_id,date,descr,amount,category) VALUES (?,?,?,?,?)",
        (user_id, date, descr, amount, category),
    )


def delete(private_id: int, user_id: int) -> int:
    """Delete a private expense the user owns; return affected row count."""
    cur = get_db().execute(
        "DELETE FROM private_expenses WHERE id=? AND user_id=?", (private_id, user_id)
    )
    return cur.rowcount


def list_for_month(user_id: int, month: str) -> list[Row]:
    """Return the user's private expenses for ``month``, newest first."""
    return (
        get_db()
        .execute(
            "SELECT * FROM private_expenses WHERE user_id=? AND substr(date,1,7)=?"
            " ORDER BY date DESC, id DESC",
            (user_id, month),
        )
        .fetchall()
    )


def monthly_totals(user_id: int, from_month: str) -> dict[str, float]:
    """Return ``{YYYY-MM: total}`` of the user's private spend from ``from_month``."""
    return {
        r["ym"]: round(r["s"], 2)
        for r in get_db().execute(
            "SELECT substr(date,1,7) ym, SUM(amount) s FROM private_expenses"
            " WHERE user_id=? AND substr(date,1,7)>=? GROUP BY ym",
            (user_id, from_month),
        )
    }


def total_for_month(user_id: int, month: str) -> float:
    """Return the user's total private spend for a single ``month``."""
    return (
        get_db()
        .execute(
            "SELECT COALESCE(SUM(amount),0) s FROM private_expenses"
            " WHERE user_id=? AND substr(date,1,7)=?",
            (user_id, month),
        )
        .fetchone()["s"]
    )


def distinct_categories(user_id: int) -> list[str]:
    """Return the user's non-empty private categories, for autocomplete."""
    return [
        r["category"]
        for r in get_db().execute(
            "SELECT DISTINCT category FROM private_expenses"
            " WHERE user_id=? AND category<>'' ORDER BY category",
            (user_id,),
        )
    ]
