# -*- coding: utf-8 -*-
"""Security concerns kept out of the business logic.

Provides the same-origin (CSRF) guard for state-changing API calls, a set of
conservative response security headers, and an in-memory login rate limiter.
"""
from __future__ import annotations

import time

from flask import Flask, request
from werkzeug.wrappers import Response

from kaza.utils import err

# State-changing methods that must originate from the app itself.
_MUTATING_METHODS = ("POST", "PATCH", "PUT", "DELETE")


def verify_same_origin():
    """Reject cross-origin state-changing API requests (basic CSRF defense).

    Session cookies are ``SameSite=Lax``; this adds an explicit Origin check
    so a forged cross-site request cannot mutate data even if a cookie leaks.
    Returns an error response to short-circuit the request, or ``None`` to
    allow it to proceed.
    """
    if request.method in _MUTATING_METHODS and request.path.startswith("/api/"):
        origin = request.headers.get("Origin")
        if origin:
            host = origin.split("://", 1)[-1]
            if host != request.host:
                return err("בקשה ממקור לא מורשה", 403)
    return None


def apply_security_headers(response: Response) -> Response:
    """Attach conservative, non-breaking security headers to every response."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


class LoginRateLimiter:
    """Per-email failure counter that locks out after too many bad attempts.

    Purely in-memory (per process); adequate for a small self-hosted app and
    resets on restart. After ``max_fails`` failures within a window the email
    is locked for ``lock_seconds``.
    """

    def __init__(self, max_fails: int = 5, lock_seconds: int = 60) -> None:
        self.max_fails = max_fails
        self.lock_seconds = lock_seconds
        self._fails: dict[str, list[float]] = {}  # email -> [count, locked_until_ts]

    def is_locked(self, email: str) -> bool:
        """True while ``email`` is within its lockout window."""
        return time.time() < self._fails.get(email, [0, 0])[1]

    def record_failure(self, email: str) -> None:
        """Count a failed attempt and start a lockout once the limit is hit."""
        state = self._fails.get(email, [0, 0])
        state[0] += 1
        if state[0] >= self.max_fails:
            state = [0, time.time() + self.lock_seconds]
        self._fails[email] = state

    def reset(self, email: str) -> None:
        """Clear all failure state after a successful login."""
        self._fails.pop(email, None)


# One shared limiter instance for the login route.
login_limiter = LoginRateLimiter()


def register_security(app: Flask) -> None:
    """Wire the origin guard and security headers into the app lifecycle."""
    app.before_request(verify_same_origin)
    app.after_request(apply_security_headers)
