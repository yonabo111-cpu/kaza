# -*- coding: utf-8 -*-
"""Money routes: shared expenses, settlements, and budget categories."""
from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import household_required
from kaza.models import finance as finance_repo
from kaza.services import finance as finance_service
from kaza.services import households as households_service
from kaza.utils import DATE_RE, body, err, valid_amount

bp = Blueprint("finance", __name__)


# ------------------------------------------------------------------- expenses

@bp.post("/api/expenses")
@household_required
def add_expense():
    """Record a shared expense and its per-member split."""
    d = body()
    descr = (d.get("descr") or "").strip()
    date = d.get("date") or ""
    split = d.get("split_type") or "equal"
    try:
        amount = round(float(d.get("amount")), 2)
        payer_id = int(d.get("payer_id"))
        category_id = int(d.get("category_id"))
    except (TypeError, ValueError):
        return err("נתונים חסרים או לא תקינים")
    if not descr or len(descr) > 120:
        return err("נא להזין תיאור (עד 120 תווים)")
    if not valid_amount(amount):
        return err("סכום לא תקין")
    if not DATE_RE.match(date):
        return err("תאריך לא תקין")

    member_ids = households_service.member_ids(g.hid)
    if payer_id not in member_ids:
        return err("המשלם/ת אינו חבר/ה בדירה")
    if not finance_repo.category_exists(category_id, g.hid):
        return err("קטגוריה לא נמצאה")

    shares = _resolve_shares(split, amount, member_ids, payer_id, d.get("shares"))
    if isinstance(shares, tuple):  # validation failed → (error_response,)
        return shares[0]

    finance_repo.create_expense(g.hid, date, descr, amount, category_id, payer_id, split, shares)
    return jsonify(ok=True)


def _resolve_shares(split, amount, member_ids, payer_id, raw_shares):
    """Compute the share map for a split type, or return ``(error_response,)``."""
    if split == "equal":
        return finance_service.equal_shares(amount, member_ids, payer_id)
    if split == "personal":
        return {payer_id: amount}
    if split == "custom":
        shares: dict[int, float] = {}
        try:
            for key, value in (raw_shares or {}).items():
                uid, val = int(key), round(float(value), 2)
                if uid not in member_ids or val < 0:
                    return (err("חלוקה לא תקינה"),)
                if val > 0:
                    shares[uid] = val
        except (TypeError, ValueError):
            return (err("חלוקה לא תקינה"),)
        if abs(sum(shares.values()) - amount) > 0.02:
            return (err("סכום החלוקה חייב להיות שווה לסכום ההוצאה"),)
        return shares
    return (err("סוג חלוקה לא מוכר"),)


@bp.delete("/api/expenses/<int:expense_id>")
@household_required
def delete_expense(expense_id: int):
    """Delete a shared expense."""
    if finance_repo.get_expense(expense_id, g.hid) is None:
        return err("הוצאה לא נמצאה", 404)
    finance_repo.delete_expense(expense_id, g.hid)
    return jsonify(ok=True)


# ---------------------------------------------------------------- settlements

@bp.post("/api/settlements")
@household_required
def add_settlement():
    """Record a money transfer between two members."""
    d = body()
    date = d.get("date") or ""
    try:
        from_id, to_id = int(d.get("from_id")), int(d.get("to_id"))
        amount = round(float(d.get("amount")), 2)
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    member_ids = households_service.member_ids(g.hid)
    if from_id not in member_ids or to_id not in member_ids or from_id == to_id:
        return err("משתתפים לא תקינים")
    if not valid_amount(amount):
        return err("סכום לא תקין")
    if not DATE_RE.match(date):
        return err("תאריך לא תקין")
    finance_repo.create_settlement(g.hid, date, from_id, to_id, amount)
    return jsonify(ok=True)


@bp.delete("/api/settlements/<int:settlement_id>")
@household_required
def delete_settlement(settlement_id: int):
    """Delete a settlement record."""
    finance_repo.delete_settlement(settlement_id, g.hid)
    return jsonify(ok=True)


# ------------------------------------------------------------------ categories

@bp.post("/api/categories")
@household_required
def add_category():
    """Create a budget category."""
    d = body()
    name = (d.get("name") or "").strip()
    if not name or len(name) > 40:
        return err("נא להזין שם קטגוריה (עד 40 תווים)")
    budget = max(0.0, float(d.get("budget") or 0))
    finance_repo.create_category(g.hid, name, budget)
    return jsonify(ok=True)


@bp.patch("/api/categories/<int:category_id>")
@household_required
def update_category(category_id: int):
    """Update a category's monthly budget."""
    try:
        budget = max(0.0, float(body().get("budget")))
    except (TypeError, ValueError):
        return err("תקציב לא תקין")
    finance_repo.update_category_budget(category_id, g.hid, budget)
    return jsonify(ok=True)


@bp.delete("/api/categories/<int:category_id>")
@household_required
def delete_category(category_id: int):
    """Delete a category, unless expenses or bills still reference it."""
    if finance_repo.category_in_use(category_id, g.hid):
        return err("אי אפשר למחוק — יש הוצאות או חשבונות שמשויכים לקטגוריה")
    finance_repo.delete_category(category_id, g.hid)
    return jsonify(ok=True)
