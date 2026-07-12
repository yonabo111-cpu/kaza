# -*- coding: utf-8 -*-
"""Recurring-bill routes: create, pay, reverse a payment, delete."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import household_required
from kaza.models import finance as finance_repo
from kaza.services import finance as finance_service
from kaza.services import households as households_service
from kaza.utils import MONTH_RE, body, clean_text, err

bp = Blueprint("bills", __name__)


@bp.post("/api/bills")
@household_required
def add_bill():
    """Create a recurring bill."""
    d = body()
    name = clean_text(d.get("name"))
    if not name or len(name) > 60:
        return err("נא להזין שם חשבון (עד 60 תווים)")
    try:
        amount = round(float(d.get("amount") or 0), 2)
        due_day = min(31, max(1, int(d.get("due_day") or 1)))
        category_id = int(d.get("category_id"))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    if not finance_repo.category_exists(category_id, g.hid):
        return err("קטגוריה לא נמצאה")
    finance_repo.create_bill(g.hid, name, amount, due_day, category_id)
    return jsonify(ok=True)


@bp.post("/api/bills/<int:bill_id>/pay")
@household_required
def pay_bill(bill_id: int):
    """Mark a bill paid for a month, creating the matching split expense."""
    d = body()
    month = d.get("month") or ""
    if not MONTH_RE.match(month):
        return err("חודש לא תקין")
    try:
        payer_id = int(d.get("payer_id"))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    member_ids = households_service.member_ids(g.hid)
    if payer_id not in member_ids:
        return err("המשלם/ת אינו חבר/ה בדירה")
    bill = finance_repo.get_bill(bill_id, g.hid)
    if bill is None:
        return err("חשבון לא נמצא", 404)
    if finance_repo.payment_exists(bill_id, month):
        return err("החשבון כבר סומן כשולם לחודש הזה")
    date = f"{month}-{min(bill['due_day'], 28):02d}"
    expense_id = finance_repo.create_expense(
        g.hid,
        date,
        bill["name"],
        bill["amount"],
        bill["category_id"],
        payer_id,
        "equal",
        finance_service.equal_shares(bill["amount"], member_ids, payer_id),
    )
    finance_repo.record_payment(bill_id, month, payer_id, expense_id)
    return jsonify(ok=True)


@bp.post("/api/bills/<int:bill_id>/unpay")
@household_required
def unpay_bill(bill_id: int):
    """Reverse a bill payment for a month and remove its generated expense."""
    month = body().get("month") or ""
    if not MONTH_RE.match(month):
        return err("חודש לא תקין")
    payment = finance_repo.get_payment(bill_id, month, g.hid)
    if payment is None:
        return err("לא נמצא תשלום לביטול", 404)
    finance_repo.delete_payment(bill_id, month)
    if payment["expense_id"]:
        finance_repo.delete_expense_only(payment["expense_id"], g.hid)
    return jsonify(ok=True)


@bp.delete("/api/bills/<int:bill_id>")
@household_required
def delete_bill(bill_id: int):
    """Delete a recurring bill (recorded expenses remain)."""
    finance_repo.delete_bill(bill_id, g.hid)
    return jsonify(ok=True)
