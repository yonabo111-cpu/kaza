# -*- coding: utf-8 -*-
"""Application observability: logging, per-request access logs, and Sentry."""

from __future__ import annotations

import logging
import time

from flask import Flask, g, request

_LOG_FORMAT = "[%(asctime)s] %(levelname)s in %(name)s: %(message)s"


def configure_logging(app: Flask) -> None:
    """Set the app logger's level and attach a stream handler once."""
    level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    app.logger.setLevel(level)
    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        app.logger.addHandler(handler)
    app.logger.propagate = False


def register_request_logging(app: Flask) -> None:
    """Log one line per API request: method, path, status, and duration.

    Only ``/api/`` requests are logged — static assets and the health probe
    would just be noise. Gives visibility into activity and response times even
    under the dev server, which logs nothing by default.
    """

    @app.before_request
    def _start_timer() -> None:
        g._t0 = time.perf_counter()

    @app.after_request
    def _log_request(response):
        if request.path.startswith("/api/"):
            t0 = g.get("_t0")
            duration = f"{(time.perf_counter() - t0) * 1000:.0f}ms" if t0 else "?"
            app.logger.info(
                "%s %s → %s (%s)", request.method, request.path, response.status_code, duration
            )
        return response


def init_sentry(app: Flask) -> None:
    """Enable Sentry error monitoring when ``SENTRY_DSN`` is configured.

    A no-op without a DSN, so the app runs unchanged in development. The SDK is
    an optional dependency (the ``monitoring`` extra); if it is missing while a
    DSN is set, we warn and carry on rather than crash.
    """
    dsn = app.config.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        app.logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; monitoring disabled")
        return
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.0),
        environment=app.config.get("ENV_NAME", "production"),
        send_default_pii=False,  # never ship user data to the monitoring service
    )
    app.logger.info("Sentry monitoring enabled")
