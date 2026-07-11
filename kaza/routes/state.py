# -*- coding: utf-8 -*-
"""The aggregate dashboard-state route."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from kaza.auth import household_required
from kaza.services import state as state_service
from kaza.utils import MONTH_RE, err

bp = Blueprint("state", __name__)


@bp.get("/api/state")
@household_required
def state():
    """Return the full dashboard payload for the requested month."""
    month = request.args.get("month", "")
    if not MONTH_RE.match(month):
        return err("חודש לא תקין")
    return jsonify(state_service.build_state(g.hid, g.user, month))
