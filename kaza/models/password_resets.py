# -*- coding: utf-8 -*-
"""Data access for ``password_resets`` — single-use, expiring reset tokens.

Only the SHA-256 hash of a token is stored, never the token itself, so a leaked
database cannot be used to reset anyone's password.
"""

from __future__ import annotations

from kaza.db import Row, get_db


def create(user_id: int, token_hash: str, expires_at: str) -> None:
    """Store a reset token hash for ``user_id`` with an expiry timestamp."""
    get_db().execute(
        "INSERT INTO password_resets(user_id,token_hash,expires_at) VALUES (?,?,?)",
        (user_id, token_hash, expires_at),
    )


def get_valid(token_hash: str, now: str) -> Row | None:
    """Return an unused, unexpired reset row matching ``token_hash``, or ``None``."""
    return (
        get_db()
        .execute(
            "SELECT * FROM password_resets"
            " WHERE token_hash=? AND used_at IS NULL AND expires_at > ?",
            (token_hash, now),
        )
        .fetchone()
    )


def mark_used(reset_id: int) -> None:
    """Mark a reset token as consumed so it cannot be reused."""
    get_db().execute("UPDATE password_resets SET used_at=datetime('now') WHERE id=?", (reset_id,))


def delete_for_user(user_id: int) -> None:
    """Remove all reset tokens for a user (on a new request, or account deletion)."""
    get_db().execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
