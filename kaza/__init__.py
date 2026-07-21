# -*- coding: utf-8 -*-
"""Kaza — a household-management app for roommates.

This package exposes an application factory, :func:`create_app`, which wires
together configuration, the database, security, logging, and the API
blueprints. Layering runs strictly one way: ``routes → services → models →
db``.
"""

from __future__ import annotations

import mimetypes
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from kaza import db as db_module
from kaza.config import STATIC_DIR, BaseConfig, get_config
from kaza.logging_setup import configure_logging, init_sentry, register_request_logging
from kaza.routes import register_blueprints
from kaza.security import register_security

# Ensure static assets are served with the correct Content-Type on every OS.
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")

__all__ = ["create_app"]


def create_app(config: BaseConfig | None = None) -> Flask:
    """Build and configure a Flask application instance."""
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

    cfg = config or get_config()
    _apply_config(app, cfg)

    configure_logging(app)
    init_sentry(app)
    db_module.init_db(app)
    app.teardown_appcontext(db_module.close_db)

    register_request_logging(app)
    register_security(app)
    register_blueprints(app)
    _register_error_handlers(app)

    app.logger.info("Kaza started (env=%s)", cfg.ENV_NAME)
    return app


def _apply_config(app: Flask, cfg: BaseConfig) -> None:
    """Copy settings from the config object into the Flask app."""
    app.config.from_object(cfg)
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    app.config["DB_PATH"] = cfg.db_path
    app.config["SECRET_KEY"] = cfg.resolve_secret_key()
    app.json.ensure_ascii = False  # emit Hebrew as UTF-8, not \uXXXX escapes


def _register_error_handlers(app: Flask) -> None:
    """Return JSON errors for API paths; leave page routes to Flask defaults."""

    @app.errorhandler(404)
    def _not_found(exc):
        if request.path.startswith("/api/"):
            return jsonify(error="לא נמצא"), 404
        return exc

    if not app.debug and not app.testing:

        @app.errorhandler(Exception)
        def _server_error(exc):
            if isinstance(exc, HTTPException):
                return exc
            app.logger.exception("Unhandled error on %s", request.path)
            if request.path.startswith("/api/"):
                return jsonify(error="שגיאת שרת פנימית"), 500
            return "Internal Server Error", 500
