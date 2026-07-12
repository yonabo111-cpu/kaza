# -*- coding: utf-8 -*-
"""Private-ledger routes: a per-user set of expenses and a personal budget.

Everything here is scoped to the logged-in user (``login_required``, not
``household_required``) so private data never touches household queries.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import login_required
from kaza.models import private_expenses as private_repo
from kaza.models import users as users_repo
from kaza.utils import DATE_RE, body, clean_text, err, valid_amount

bp = Blueprint("personal", __name__)


@bp.post("/api/personal")
@login_required
def add_private_expense():
    """Add a private expense visible only to the current user."""
    d = body()
    descr = clean_text(d.get("descr"))
    date = d.get("date") or ""
    category = clean_text(d.get("category"))[:40]
    try:
        amount = round(float(d.get("amount")), 2)
    except (TypeError, ValueError):
        return err("סכום לא תקין")
    if not descr or len(descr) > 120:
        return err("נא להזין תיאור (עד 120 תווים)")
    if not valid_amount(amount):
        return err("סכום לא תקין")
    if not DATE_RE.match(date):
        return err("תאריך לא תקין")
    private_repo.create(g.user["id"], date, descr, amount, category)
    return jsonify(ok=True)


@bp.delete("/api/personal/<int:private_id>")
@login_required
def delete_private_expense(private_id: int):
    """Delete one of the current user's private expenses."""
    if private_repo.delete(private_id, g.user["id"]) == 0:
        return err("הוצאה לא נמצאה", 404)
    return jsonify(ok=True)


@bp.post("/api/me/budget")
@login_required
def set_personal_budget():
    """Set the current user's private monthly budget."""
    try:
        budget = max(0.0, float(body().get("budget")))
    except (TypeError, ValueError):
        return err("תקציב לא תקין")
    users_repo.set_personal_budget(g.user["id"], budget)
    return jsonify(ok=True)
