# -*- coding: utf-8 -*-
"""Security concerns kept out of the business logic.

Three areas live here:

* **CSRF defense-in-depth** for state-changing API calls — an Origin check, a
  ``Sec-Fetch-Site`` check, and a JSON content-type requirement on POST (HTML
  forms cannot send JSON, and cross-origin scripts cannot without a CORS
  preflight this app never grants). Combined with ``SameSite=Lax`` session
  cookies, a forged cross-site request has no way through.
* **Response security headers** — a Content-Security-Policy, clickjacking and
  MIME-sniffing protection, a minimal Permissions-Policy, and HSTS in
  production.
* **Rate limiting** — a per-email login lockout plus per-IP sliding windows on
  login and registration. In-memory (per process), which is adequate for a
  small self-hosted deployment.
"""

from __future__ import annotations

import time
from collections import deque

from flask import Flask, current_app, request
from werkzeug.wrappers import Response

from kaza.utils import err

# State-changing methods that must originate from the app itself.
_MUTATING_METHODS = ("POST", "PATCH", "PUT", "DELETE")

# Content-Security-Policy. The frontend currently uses inline style/script
# blocks and Google Fonts, so 'unsafe-inline' stays for now; everything else is
# locked down ('self' + explicit font hosts, no objects, no framing).
_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=()"
_HSTS = "max-age=31536000; includeSubDomains"


def verify_request_origin() -> tuple[Response, int] | None:
    """Reject cross-site state-changing API requests (CSRF defense).

    Returns an error response to short-circuit the request, or ``None`` to let
    it proceed. Non-browser clients (tests, curl) send none of these headers
    and pass through — the protection targets browser-based forgery, which
    cannot avoid them.
    """
    if request.method not in _MUTATING_METHODS or not request.path.startswith("/api/"):
        return None

    # Layer 1: when the browser declares an Origin, it must be ours.
    origin = request.headers.get("Origin")
    if origin:
        host = origin.split("://", 1)[-1]
        if host != request.host:
            return err("בקשה ממקור לא מורשה", 403)

    # Layer 2: modern browsers label cross-site requests explicitly.
    if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        return err("בקשה ממקור לא מורשה", 403)

    # Layer 3: POST is the only mutating method an HTML form can produce;
    # requiring JSON rules forms out entirely.
    if request.method == "POST" and not request.is_json:
        return err("הבקשה חייבת להיות בפורמט JSON", 415)

    return None


def apply_security_headers(response: Response) -> Response:
    """Attach conservative security headers to every response."""
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "same-origin")
    headers.setdefault("Content-Security-Policy", _CSP)
    headers.setdefault("Permissions-Policy", _PERMISSIONS_POLICY)
    if current_app.config.get("ENABLE_HSTS"):
        headers.setdefault("Strict-Transport-Security", _HSTS)
    return response


class SlidingWindowLimiter:
    """Allow at most ``limit`` events per ``window_seconds`` for each key."""

    # Above this many tracked keys, expired entries are pruned opportunistically.
    _PRUNE_THRESHOLD = 10_000

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Record an event for ``key`` and return whether it is within limits."""
        now = time.time()
        events = self._events.setdefault(key, deque())
        while events and events[0] <= now - self.window:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(now)
        if len(self._events) > self._PRUNE_THRESHOLD:
            self._prune(now)
        return True

    def _prune(self, now: float) -> None:
        """Drop keys whose events have all left the window."""
        stale = [key for key, q in self._events.items() if not q or q[-1] <= now - self.window]
        for key in stale:
            del self._events[key]


class LoginRateLimiter:
    """Per-email failure counter that locks out after too many bad attempts.

    After ``max_fails`` consecutive failures the email is locked for
    ``lock_seconds``. State is bounded: expired entries are pruned once the
    table grows past a threshold.
    """

    _PRUNE_THRESHOLD = 10_000

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
        if len(self._fails) > self._PRUNE_THRESHOLD:
            now = time.time()
            stale = [k for k, v in self._fails.items() if v[1] < now and v[0] == 0]
            for key in stale:
                del self._fails[key]

    def reset(self, email: str) -> None:
        """Clear all failure state after a successful login."""
        self._fails.pop(email, None)


# Shared limiter instances used by the auth routes.
login_limiter = LoginRateLimiter()
login_ip_limiter = SlidingWindowLimiter(limit=30, window_seconds=60)
register_ip_limiter = SlidingWindowLimiter(limit=30, window_seconds=600)


def client_ip() -> str:
    """Return the requesting client's address for rate-limiting purposes."""
    return request.remote_addr or "unknown"


def register_security(app: Flask) -> None:
    """Wire the origin guard and security headers into the app lifecycle."""
    app.before_request(verify_request_origin)
    app.after_request(apply_security_headers)
