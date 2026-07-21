# -*- coding: utf-8 -*-
"""Account-recovery business logic: password-reset tokens and their emails."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from flask import current_app

from kaza.auth import hash_password
from kaza.email import send_email
from kaza.models import password_resets as resets_repo
from kaza.models import users as users_repo

# How long a reset link stays valid, and the minimum acceptable new password.
_TOKEN_TTL = timedelta(hours=1)
_MIN_PASSWORD = 6
_TIME_FMT = "%Y-%m-%d %H:%M:%S"  # matches SQLite's datetime('now') (UTC)


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest stored in place of the raw token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _reset_link(token: str) -> str:
    """Build the absolute (or root-relative) link a user clicks to reset."""
    base = current_app.config.get("APP_BASE_URL", "")
    return f"{base}/?reset={token}"


def _email_body(name: str, link: str) -> str:
    """Compose the plain-text reset email."""
    return (
        f"היי {name},\n\n"
        "קיבלנו בקשה לאיפוס הסיסמה שלך בקאזה. "
        "אפשר לבחור סיסמה חדשה דרך הקישור הבא (תקף לשעה):\n\n"
        f"{link}\n\n"
        "אם לא ביקשת לאפס סיסמה, אפשר להתעלם מהמייל הזה — שום דבר לא ישתנה.\n\n"
        "צוות קאזה"
    )


def request_password_reset(email: str) -> None:
    """Issue a reset token for ``email`` and send the link. Silent if unknown.

    Callers must not reveal whether the address exists (no user enumeration),
    so this returns nothing regardless of outcome.
    """
    user = users_repo.get_by_email(email)
    if user is None:
        return
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + _TOKEN_TTL).strftime(_TIME_FMT)
    resets_repo.delete_for_user(user["id"])  # keep only the newest token
    resets_repo.create(user["id"], _hash_token(token), expires_at)
    send_email(email, "איפוס סיסמה — קאזה", _email_body(user["name"], _reset_link(token)))


def perform_password_reset(token: str, new_password: str) -> str | None:
    """Consume ``token`` and set ``new_password``. Return an error, or ``None``."""
    if len(new_password) < _MIN_PASSWORD:
        return "סיסמה קצרה מדי — לפחות 6 תווים"
    now = datetime.utcnow().strftime(_TIME_FMT)
    row = resets_repo.get_valid(_hash_token(token), now)
    if row is None:
        return "הקישור לא תקין או שפג תוקפו — בקשו איפוס חדש"
    users_repo.set_password(row["user_id"], hash_password(new_password))
    resets_repo.mark_used(row["id"])
    return None
