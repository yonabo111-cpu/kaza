# -*- coding: utf-8 -*-
"""Bulletin-board routes: list, post, and delete shared notes."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import household_required
from kaza.models import bulletin as bulletin_repo
from kaza.services import households as households_service
from kaza.utils import body, clean_text, err

bp = Blueprint("bulletin", __name__)


@bp.get("/api/bulletin")
@household_required
def get_bulletin():
    """Return the household's bulletin notes."""
    return jsonify(notes=households_service.bulletin_notes(g.hid))


@bp.post("/api/bulletin")
@household_required
def add_bulletin_note():
    """Post a note to the shared board."""
    d = body()
    content = clean_text(d.get("content"))
    if not content or len(content) > 300:
        return err("נא לכתוב תוכן למודעה (עד 300 תווים)")
    bulletin_repo.create(g.hid, g.user["id"], content, bool(d.get("is_pinned")))
    return jsonify(ok=True)


@bp.delete("/api/bulletin/<int:note_id>")
@household_required
def delete_bulletin_note(note_id: int):
    """Delete a note. The board is shared, so any member may remove any note."""
    if bulletin_repo.delete(note_id, g.hid) == 0:
        return err("מודעה לא נמצאה", 404)
    return jsonify(ok=True)
