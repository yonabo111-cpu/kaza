# -*- coding: utf-8 -*-
"""Data access for the money domain.

Covers categories, expenses (with their per-member shares), settlements, and
recurring bills with their per-month payments. All reads and writes are scoped
by ``household_id`` for tenant isolation.
"""

from __future__ import annotations

from typing import Mapping

from kaza.db import Row, get_db

# ------------------------------------------------------------------ categories


def categories_for(household_id: int) -> list[Row]:
    """Return the household's categories ordered by id."""
    return (
        get_db()
        .execute("SELECT * FROM categories WHERE household_id=? ORDER BY id", (household_id,))
        .fetchall()
    )


def create_category(household_id: int, name: str, budget: float) -> int:
    """Insert a new spending category and return its id."""
    cur = get_db().execute(
        "INSERT INTO categories(household_id,name,budget) VALUES (?,?,?)",
        (household_id, name, budget),
    )
    return cur.lastrowid


def update_category_budget(category_id: int, household_id: int, budget: float) -> None:
    """Update a category's monthly budget."""
    get_db().execute(
        "UPDATE categories SET budget=? WHERE id=? AND household_id=?",
        (budget, category_id, household_id),
    )


def delete_category(category_id: int, household_id: int) -> None:
    """Delete a category (callers must ensure it is unused first)."""
    get_db().execute(
        "DELETE FROM categories WHERE id=? AND household_id=?", (category_id, household_id)
    )


def get_category(category_id: int, household_id: int) -> Row | None:
    """Return a category row if it belongs to the household."""
    return (
        get_db()
        .execute(
            "SELECT * FROM categories WHERE id=? AND household_id=?", (category_id, household_id)
        )
        .fetchone()
    )


def category_exists(category_id: int, household_id: int) -> bool:
    """True if the category belongs to the household."""
    return (
        get_db()
        .execute(
            "SELECT 1 FROM categories WHERE id=? AND household_id=?", (category_id, household_id)
        )
        .fetchone()
        is not None
    )


def category_in_use(category_id: int, household_id: int) -> bool:
    """True if any expense or bill references this category."""
    db = get_db()
    used = (
        db.execute(
            "SELECT 1 FROM expenses WHERE category_id=? AND household_id=? LIMIT 1",
            (category_id, household_id),
        ).fetchone()
        or db.execute(
            "SELECT 1 FROM bills WHERE category_id=? AND household_id=? LIMIT 1",
            (category_id, household_id),
        ).fetchone()
    )
    return used is not None


def spent_by_category(household_id: int, month: str) -> dict[int, float]:
    """Return ``{category_id: total_spent}`` for a household in ``month``."""
    return {
        r["category_id"]: r["s"]
        for r in get_db().execute(
            "SELECT category_id, SUM(amount) s FROM expenses"
            " WHERE household_id=? AND substr(date,1,7)=? GROUP BY category_id",
            (household_id, month),
        )
    }


# -------------------------------------------------------------------- expenses


def create_expense(
    household_id: int,
    date: str,
    descr: str,
    amount: float,
    category_id: int,
    payer_id: int,
    split_type: str,
    shares: Mapping[int, float],
) -> int:
    """Insert an expense plus its per-member share rows; return the expense id."""
    db = get_db()
    cur = db.execute(
        "INSERT INTO expenses(household_id,date,descr,amount,category_id,payer_id,split_type)"
        " VALUES (?,?,?,?,?,?,?)",
        (household_id, date, descr, amount, category_id, payer_id, split_type),
    )
    expense_id = cur.lastrowid
    db.executemany(
        "INSERT INTO expense_shares(expense_id,user_id,share) VALUES (?,?,?)",
        [(expense_id, uid, share) for uid, share in shares.items()],
    )
    return expense_id


def get_expense(expense_id: int, household_id: int) -> Row | None:
    """Return the expense row (id only) if it belongs to the household."""
    return (
        get_db()
        .execute(
            "SELECT id FROM expenses WHERE id=? AND household_id=?", (expense_id, household_id)
        )
        .fetchone()
    )


def delete_expense(expense_id: int, household_id: int) -> None:
    """Delete an expense and detach any bill payment that pointed at it."""
    db = get_db()
    db.execute("DELETE FROM bill_payments WHERE expense_id=?", (expense_id,))
    db.execute("DELETE FROM expenses WHERE id=? AND household_id=?", (expense_id, household_id))


def delete_expense_only(expense_id: int, household_id: int) -> None:
    """Delete a single expense row (used when reversing a bill payment)."""
    get_db().execute(
        "DELETE FROM expenses WHERE id=? AND household_id=?", (expense_id, household_id)
    )


def expenses_for_month(household_id: int, month: str) -> list[Row]:
    """Return the household's expenses for ``month``, newest first."""
    return (
        get_db()
        .execute(
            "SELECT * FROM expenses WHERE household_id=? AND substr(date,1,7)=?"
            " ORDER BY date DESC, id DESC",
            (household_id, month),
        )
        .fetchall()
    )


def payer_totals(household_id: int, through_month: str) -> list[Row]:
    """Return ``[{p, s}]`` — amount paid per payer through the end of ``through_month``."""
    return (
        get_db()
        .execute(
            "SELECT payer_id p, SUM(amount) s FROM expenses"
            " WHERE household_id=? AND substr(date,1,7)<=? GROUP BY payer_id",
            (household_id, through_month),
        )
        .fetchall()
    )


def share_totals(household_id: int, through_month: str) -> list[Row]:
    """Return ``[{u, s}]`` — share owed per member through the end of ``through_month``."""
    return (
        get_db()
        .execute(
            "SELECT es.user_id u, SUM(es.share) s FROM expense_shares es"
            " JOIN expenses e ON e.id=es.expense_id"
            " WHERE e.household_id=? AND substr(e.date,1,7)<=? GROUP BY es.user_id",
            (household_id, through_month),
        )
        .fetchall()
    )


def user_shares_for_expenses(user_id: int, household_id: int, month: str) -> dict[int, float]:
    """Return ``{expense_id: share}`` for one user's shares in a month's expenses."""
    return {
        r["expense_id"]: r["share"]
        for r in get_db().execute(
            "SELECT es.expense_id, es.share FROM expense_shares es"
            " JOIN expenses e ON e.id=es.expense_id"
            " WHERE es.user_id=? AND e.household_id=? AND substr(e.date,1,7)=?",
            (user_id, household_id, month),
        )
    }


def monthly_totals(household_id: int, from_month: str) -> dict[str, float]:
    """Return ``{YYYY-MM: total}`` for months at or after ``from_month``."""
    return {
        r["ym"]: round(r["s"], 2)
        for r in get_db().execute(
            "SELECT substr(date,1,7) ym, SUM(amount) s FROM expenses"
            " WHERE household_id=? AND substr(date,1,7)>=? GROUP BY ym",
            (household_id, from_month),
        )
    }


def share_by_month(user_id: int, household_id: int, from_month: str) -> dict[str, float]:
    """Return ``{YYYY-MM: user's share}`` in shared expenses from ``from_month``."""
    return {
        r["ym"]: round(r["s"], 2)
        for r in get_db().execute(
            "SELECT substr(e.date,1,7) ym, SUM(es.share) s FROM expense_shares es"
            " JOIN expenses e ON e.id=es.expense_id"
            " WHERE es.user_id=? AND e.household_id=? AND substr(e.date,1,7)>=? GROUP BY ym",
            (user_id, household_id, from_month),
        )
    }


def share_total_for_month(user_id: int, household_id: int, month: str) -> float:
    """Return a user's total shared-expense share for a single ``month``."""
    return (
        get_db()
        .execute(
            "SELECT COALESCE(SUM(es.share),0) s FROM expense_shares es"
            " JOIN expenses e ON e.id=es.expense_id"
            " WHERE es.user_id=? AND e.household_id=? AND substr(e.date,1,7)=?",
            (user_id, household_id, month),
        )
        .fetchone()["s"]
    )


# ----------------------------------------------------------------- settlements


def create_settlement(
    household_id: int, date: str, from_id: int, to_id: int, amount: float
) -> None:
    """Record a money transfer between two members."""
    get_db().execute(
        "INSERT INTO settlements(household_id,date,from_id,to_id,amount) VALUES (?,?,?,?,?)",
        (household_id, date, from_id, to_id, amount),
    )


def delete_settlement(settlement_id: int, household_id: int) -> None:
    """Delete a settlement record."""
    get_db().execute(
        "DELETE FROM settlements WHERE id=? AND household_id=?", (settlement_id, household_id)
    )


def settlement_pairs(household_id: int, through_month: str) -> list[Row]:
    """Return ``[{from_id, to_id, amount}]`` through the end of ``through_month``."""
    return (
        get_db()
        .execute(
            "SELECT from_id, to_id, amount FROM settlements"
            " WHERE household_id=? AND substr(date,1,7)<=?",
            (household_id, through_month),
        )
        .fetchall()
    )


def recent_settlements(household_id: int, limit: int = 8) -> list[Row]:
    """Return the most recent settlements, newest first."""
    return (
        get_db()
        .execute(
            "SELECT * FROM settlements WHERE household_id=? ORDER BY date DESC, id DESC LIMIT ?",
            (household_id, limit),
        )
        .fetchall()
    )


# ----------------------------------------------------------------------- bills


def bills_for(household_id: int, user_id: int) -> list[Row]:
    """Return the household's bills visible to ``user_id``, ordered by due day.

    Private bills (``bill_type='private'``) are returned only to their owner.
    """
    return (
        get_db()
        .execute(
            "SELECT * FROM bills WHERE household_id=?"
            " AND (bill_type != 'private' OR owner_id=?) ORDER BY due_day, id",
            (household_id, user_id),
        )
        .fetchall()
    )


def create_bill(
    household_id: int,
    name: str,
    amount: float,
    due_day: int,
    category_id: int,
    bill_type: str = "equal",
    owner_id: int | None = None,
) -> None:
    """Insert a recurring bill (``owner_id`` is set for private bills)."""
    get_db().execute(
        "INSERT INTO bills(household_id,name,amount,due_day,category_id,bill_type,owner_id)"
        " VALUES (?,?,?,?,?,?,?)",
        (household_id, name, amount, due_day, category_id, bill_type, owner_id),
    )


def get_bill(bill_id: int, household_id: int) -> Row | None:
    """Return a bill row if it belongs to the household."""
    return (
        get_db()
        .execute("SELECT * FROM bills WHERE id=? AND household_id=?", (bill_id, household_id))
        .fetchone()
    )


def update_bill(bill_id: int, household_id: int, amount: float | None, due_day: int | None) -> None:
    """Update a bill's amount and/or due day."""
    if amount is not None:
        get_db().execute(
            "UPDATE bills SET amount=? WHERE id=? AND household_id=?",
            (amount, bill_id, household_id),
        )
    if due_day is not None:
        get_db().execute(
            "UPDATE bills SET due_day=? WHERE id=? AND household_id=?",
            (due_day, bill_id, household_id),
        )


def delete_bill(bill_id: int, household_id: int) -> None:
    """Delete a recurring bill (its recorded expenses remain)."""
    get_db().execute("DELETE FROM bills WHERE id=? AND household_id=?", (bill_id, household_id))


def payment_exists(bill_id: int, month: str, payer_id: int | None = None) -> bool:
    """True if the bill is paid for ``month`` (by ``payer_id``, if given)."""
    sql = "SELECT 1 FROM bill_payments WHERE bill_id=? AND month=?"
    params: tuple = (bill_id, month)
    if payer_id is not None:
        sql += " AND payer_id=?"
        params += (payer_id,)
    return get_db().execute(sql, params).fetchone() is not None


def record_payment(
    bill_id: int,
    month: str,
    payer_id: int,
    expense_id: int | None,
    private_expense_id: int | None = None,
) -> None:
    """Mark a bill paid for ``month``, linking the generated ledger entry."""
    get_db().execute(
        "INSERT INTO bill_payments(bill_id,month,payer_id,expense_id,private_expense_id)"
        " VALUES (?,?,?,?,?)",
        (bill_id, month, payer_id, expense_id, private_expense_id),
    )


def get_payment(
    bill_id: int, month: str, household_id: int, payer_id: int | None = None
) -> Row | None:
    """Return a bill payment row (joined to the household) for reversal."""
    sql = (
        "SELECT bp.* FROM bill_payments bp JOIN bills b ON b.id=bp.bill_id"
        " WHERE bp.bill_id=? AND bp.month=? AND b.household_id=?"
    )
    params: tuple = (bill_id, month, household_id)
    if payer_id is not None:
        sql += " AND bp.payer_id=?"
        params += (payer_id,)
    return get_db().execute(sql, params).fetchone()


def delete_payment(bill_id: int, month: str, payer_id: int | None = None) -> None:
    """Remove a bill's payment record for ``month`` (one payer, or all)."""
    sql = "DELETE FROM bill_payments WHERE bill_id=? AND month=?"
    params: tuple = (bill_id, month)
    if payer_id is not None:
        sql += " AND payer_id=?"
        params += (payer_id,)
    get_db().execute(sql, params)


def payments_for_month(household_id: int, month: str) -> dict[int, list[Row]]:
    """Return ``{bill_id: [payment_rows]}`` for a household in ``month``."""
    payments: dict[int, list[Row]] = {}
    for p in get_db().execute(
        "SELECT * FROM bill_payments WHERE month=? AND bill_id IN"
        " (SELECT id FROM bills WHERE household_id=?)",
        (month, household_id),
    ):
        payments.setdefault(p["bill_id"], []).append(p)
    return payments
