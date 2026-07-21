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


def clear_household(user_id: int) -> None:
    """Detach ``user_id`` from their household (used when leaving)."""
    get_db().execute("UPDATE users SET household_id=NULL, joined_at=NULL WHERE id=?", (user_id,))


def anonymize(user_id: int, name: str, email: str, pw_hash: str) -> None:
    """Scrub a user's personal data in place, keeping the row for referential
    integrity (their shared expense history must stay attributable)."""
    get_db().execute(
        "UPDATE users SET name=?, email=?, pw_hash=?, personal_budget=0,"
        " household_id=NULL, joined_at=NULL WHERE id=?",
        (name, email, pw_hash, user_id),
    )


def delete(user_id: int) -> None:
    """Hard-delete a user row (only safe when nothing references it)."""
    get_db().execute("DELETE FROM users WHERE id=?", (user_id,))


def is_referenced(user_id: int) -> bool:
    """True if any shared row still points at ``user_id``.

    Used when deleting an account: if references remain (e.g. expenses in a
    household the user already left), the row is anonymized instead of deleted.
    """
    row = (
        get_db()
        .execute(
            "SELECT EXISTS(SELECT 1 FROM expenses WHERE payer_id=:u)"
            " OR EXISTS(SELECT 1 FROM expense_shares WHERE user_id=:u)"
            " OR EXISTS(SELECT 1 FROM settlements WHERE from_id=:u OR to_id=:u)"
            " OR EXISTS(SELECT 1 FROM shopping WHERE added_by=:u)"
            " OR EXISTS(SELECT 1 FROM bills WHERE owner_id=:u)"
            " OR EXISTS(SELECT 1 FROM bill_payments WHERE payer_id=:u)"
            " OR EXISTS(SELECT 1 FROM chores WHERE assignee_id=:u)"
            " OR EXISTS(SELECT 1 FROM bulletin_board WHERE user_id=:u) AS ref",
            {"u": user_id},
        )
        .fetchone()
    )
    return bool(row["ref"])


def set_password(user_id: int, pw_hash: str) -> None:
    """Replace a user's password hash (used by the password-reset flow)."""
    get_db().execute("UPDATE users SET pw_hash=? WHERE id=?", (pw_hash, user_id))


def set_personal_budget(user_id: int, budget: float) -> None:
    """Set the user's private monthly budget."""
    get_db().execute("UPDATE users SET personal_budget=? WHERE id=?", (budget, user_id))


def get_personal_budget(user_id: int) -> float:
    """Return the user's private monthly budget (0 when unset)."""
    row = get_db().execute("SELECT personal_budget FROM users WHERE id=?", (user_id,)).fetchone()
    return row["personal_budget"] if row else 0
