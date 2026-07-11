# -*- coding: utf-8 -*-
"""System routes: JSON backup export, the SPA entry point, and a health check."""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify

from kaza.auth import household_required
from kaza.db import get_db
from kaza.models import backup as backup_repo

bp = Blueprint("system", __name__)


@bp.get("/api/export")
@household_required
def export_data():
    """Download a JSON backup of the household (plus the caller's private data)."""
    payload = backup_repo.export_household(g.hid, g.user["id"])
    response = jsonify(payload)
    response.headers["Content-Disposition"] = "attachment; filename=kaza-backup.json"
    return response


@bp.get("/")
def index():
    """Serve the single-page frontend."""
    return current_app.send_static_file("index.html")


@bp.get("/healthz")
def health_check():
    """Liveness/readiness probe: verifies the database is reachable."""
    try:
        get_db().execute("SELECT 1")
    except Exception:  # pragma: no cover - defensive
        return jsonify(status="error", database="unreachable"), 503
    return jsonify(status="ok", app="kaza")
