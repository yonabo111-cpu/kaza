# -*- coding: utf-8 -*-
"""Household routes: create a new apartment or join one with an invite code."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import household_required, login_required
from kaza.models import households as households_repo
from kaza.models import users as users_repo
from kaza.services import households as households_service
from kaza.utils import body, clean_text, err

bp = Blueprint("households", __name__)


@bp.post("/api/household")
@login_required
def create_household():
    """Create a household, seed its defaults, and join the creator to it."""
    if g.user["household_id"]:
        return err("כבר יש לך דירה משויכת")
    name = clean_text(body().get("name"))
    if not name or len(name) > 60:
        return err("נא להזין שם לדירה (עד 60 תווים)")
    household_id = households_repo.create(name, households_service.new_invite_code())
    users_repo.set_household(g.user["id"], household_id)
    households_service.seed_household(household_id, g.user["id"])
    return jsonify(ok=True)


@bp.post("/api/household/join")
@login_required
def join_household():
    """Join an existing household by its invite code."""
    if g.user["household_id"]:
        return err("כבר יש לך דירה משויכת")
    code = (body().get("code") or "").strip().upper()
    row = households_repo.find_by_invite(code)
    if row is None:
        return err("קוד הזמנה לא נמצא — בדקו שוב")
    users_repo.set_household(g.user["id"], row["id"])
    return jsonify(ok=True)


@bp.post("/api/household/leave")
@household_required
def leave_household():
    """Leave the current household (blocked while the caller has an open balance)."""
    error = households_service.leave_household(g.hid, g.user["id"])
    if error:
        return err(error, 409)
    return jsonify(ok=True)
