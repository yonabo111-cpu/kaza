# -*- coding: utf-8 -*-
"""Chore routes: add, mark done (rotating the turn), and delete."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import household_required
from kaza.models import chores as chores_repo
from kaza.services import households as households_service
from kaza.utils import DATE_RE, body, clean_text, err

bp = Blueprint("chores", __name__)


@bp.post("/api/chores")
@household_required
def add_chore():
    """Create a chore assigned to a household member."""
    d = body()
    name = clean_text(d.get("name"))
    if not name or len(name) > 60:
        return err("נא להזין שם מטלה (עד 60 תווים)")
    try:
        assignee_id = int(d.get("assignee_id"))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    if assignee_id not in households_service.member_ids(g.hid):
        return err("המשויך/ת אינו חבר/ה בדירה")
    freq = clean_text(d.get("freq"))[:30] or "שבועי"
    chores_repo.create(g.hid, name, freq, assignee_id)
    return jsonify(ok=True)


@bp.post("/api/chores/<int:chore_id>/done")
@household_required
def done_chore(chore_id: int):
    """Mark a chore done and pass the turn to the next member."""
    date = body().get("date") or ""
    if not DATE_RE.match(date):
        return err("תאריך לא תקין")
    chore = chores_repo.get(chore_id, g.hid)
    if chore is None:
        return err("מטלה לא נמצאה", 404)
    member_ids = households_service.member_ids(g.hid)
    try:
        nxt = member_ids[(member_ids.index(chore["assignee_id"]) + 1) % len(member_ids)]
    except ValueError:
        nxt = member_ids[0]
    chores_repo.reassign(chore_id, nxt, date)
    return jsonify(ok=True)


@bp.delete("/api/chores/<int:chore_id>")
@household_required
def delete_chore(chore_id: int):
    """Delete a chore."""
    chores_repo.delete(chore_id, g.hid)
    return jsonify(ok=True)
