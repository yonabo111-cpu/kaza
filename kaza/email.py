# -*- coding: utf-8 -*-
"""Outbound email — a thin wrapper over SMTP with a development fallback.

When no ``SMTP_HOST`` is configured the message is written to the log instead of
being sent, so the password-reset flow works end to end in development (and in
tests) without any provider. Setting the ``SMTP_*`` config (any provider —
Gmail, Brevo, …) switches on real delivery. Sending never raises: a failure is
logged and swallowed so callers can't distinguish "sent" from "failed" (which
would leak whether an address is registered).
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from flask import current_app


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Return True if handed off to SMTP, else False."""
    cfg = current_app.config
    host = cfg.get("SMTP_HOST")
    if not host:
        current_app.logger.info("EMAIL (no SMTP configured) → to=%s | %s\n%s", to, subject, body)
        return False

    message = EmailMessage()
    message["From"] = cfg.get("SMTP_FROM") or cfg.get("SMTP_USER")
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(host, cfg.get("SMTP_PORT", 587), timeout=10) as server:
            if cfg.get("SMTP_TLS", True):
                server.starttls()
            if cfg.get("SMTP_USER"):
                server.login(cfg.get("SMTP_USER"), cfg.get("SMTP_PASSWORD"))
            server.send_message(message)
        return True
    except Exception:
        current_app.logger.exception("Failed to send email to %s", to)
        return False
