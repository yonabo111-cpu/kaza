# -*- coding: utf-8 -*-
"""Authentication: password hashing, the current user, and access decorators."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, session
from werkzeug.security import check_password_hash, generate_password_hash

from kaza.db import Row
from kaza.models import users
from kaza.utils import err


def hash_password(password: str) -> str:
    """Return a salted hash for ``password`` (Werkzeug PBKDF2)."""
    return generate_password_hash(password)


def verify_password(pw_hash: str, password: str) -> bool:
    """True if ``password`` matches the stored ``pw_hash``."""
    return check_password_hash(pw_hash, password)


def start_session(user_id: int) -> None:
    """Begin a fresh, permanent session for ``user_id``."""
    session.clear()
    session["uid"] = user_id
    session.permanent = True


def end_session() -> None:
    """Clear the current session (logout)."""
    session.clear()


def current_user() -> Row | None:
    """Return the logged-in user row from the session, or ``None``."""
    user_id = session.get("uid")
    if not user_id:
        return None
    return users.get_by_id(user_id)


def login_required(view: Callable) -> Callable:
    """Require a logged-in user; expose it as ``g.user``."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return err("נדרשת התחברות", 401)
        g.user = user
        return view(*args, **kwargs)

    return wrapper


def household_required(view: Callable) -> Callable:
    """Require a logged-in user who belongs to a household (``g.hid``)."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not g.user["household_id"]:
            return err("אין דירה משויכת — צרו דירה או הצטרפו עם קוד", 409)
        g.hid = g.user["household_id"]
        return view(*args, **kwargs)

    return wrapper
