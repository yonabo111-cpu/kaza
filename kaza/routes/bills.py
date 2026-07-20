# -*- coding: utf-8 -*-
"""Recurring-bill routes: create, edit, pay, reverse a payment, delete.

Three bill types:

- ``equal`` — one member pays the whole bill and it is split equally.
- ``individual`` — everyone sees the bill but each member pays their own
  (e.g. rent paid straight to the landlord); each payment is recorded as a
  personal-split expense, so it counts in the payer's spending without
  creating debts between roommates.
- ``private`` — visible to its owner only (e.g. a gym membership); payments
  go to the owner's private ledger.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import household_required
from kaza.models import finance as finance_repo
from kaza.models import private_expenses as private_repo
from kaza.services import finance as finance_service
from kaza.services import households as households_service
from kaza.utils import MONTH_RE, body, clean_text, err

bp = Blueprint("bills", __name__)

BILL_TYPES = ("equal", "individual", "private")


@bp.post("/api/bills")
@household_required
def add_bill():
    """Create a recurring bill."""
    d = body()
    name = clean_text(d.get("name"))
    if not name or len(name) > 60:
        return err("נא להזין שם חשבון (עד 60 תווים)")
    bill_type = d.get("bill_type") or "equal"
    if bill_type not in BILL_TYPES:
        return err("סוג חשבון לא מוכר")
    try:
        amount = round(float(d.get("amount") or 0), 2)
        due_day = min(31, max(1, int(d.get("due_day") or 1)))
        category_id = int(d.get("category_id"))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    if not finance_repo.category_exists(category_id, g.hid):
        return err("קטגוריה לא נמצאה")
    owner_id = g.user["id"] if bill_type == "private" else None
    finance_repo.create_bill(g.hid, name, amount, due_day, category_id, bill_type, owner_id)
    return jsonify(ok=True)


@bp.patch("/api/bills/<int:bill_id>")
@household_required
def update_bill(bill_id: int):
    """Edit a bill's amount and/or due day."""
    bill = finance_repo.get_bill(bill_id, g.hid)
    if bill is None:
        return err("חשבון לא נמצא", 404)
    if bill["bill_type"] == "private" and bill["owner_id"] != g.user["id"]:
        return err("חשבון לא נמצא", 404)
    d = body()
    amount = due_day = None
    try:
        if d.get("amount") is not None:
            amount = round(float(d["amount"]), 2)
            if amount < 0:
                return err("נתונים לא תקינים")
        if d.get("due_day") is not None:
            due_day = min(31, max(1, int(d["due_day"])))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    finance_repo.update_bill(bill_id, g.hid, amount, due_day)
    return jsonify(ok=True)


@bp.post("/api/bills/<int:bill_id>/pay")
@household_required
def pay_bill(bill_id: int):
    """Mark a bill paid for a month, recording the matching ledger entry."""
    d = body()
    month = d.get("month") or ""
    if not MONTH_RE.match(month):
        return err("חודש לא תקין")
    try:
        payer_id = int(d.get("payer_id"))
    except (TypeError, ValueError):
        return err("נתונים לא תקינים")
    bill = finance_repo.get_bill(bill_id, g.hid)
    if bill is None:
        return err("חשבון לא נמצא", 404)
    member_ids = households_service.member_ids(g.hid)
    if payer_id not in member_ids:
        return err("המשלם/ת אינו חבר/ה בדירה")
    date = f"{month}-{min(bill['due_day'], 28):02d}"

    if bill["bill_type"] == "private":
        # Only the owner sees or pays a private bill; it lands in their ledger.
        if bill["owner_id"] != g.user["id"]:
            return err("חשבון לא נמצא", 404)
        if finance_repo.payment_exists(bill_id, month):
            return err("החשבון כבר סומן כשולם לחודש הזה")
        private_id = private_repo.create_returning_id(
            g.user["id"], date, bill["name"], bill["amount"], _category_name(bill)
        )
        finance_repo.record_payment(bill_id, month, g.user["id"], None, private_id)
        return jsonify(ok=True)

    if bill["bill_type"] == "individual":
        # Each member pays their own share; no debt is created.
        if finance_repo.payment_exists(bill_id, month, payer_id):
            return err("התשלום כבר סומן לחודש הזה")
        expense_id = finance_repo.create_expense(
            g.hid,
            date,
            bill["name"],
            bill["amount"],
            bill["category_id"],
            payer_id,
            "personal",
            {payer_id: bill["amount"]},
        )
        finance_repo.record_payment(bill_id, month, payer_id, expense_id)
        return jsonify(ok=True)

    # equal (default): one payment covers everyone, split equally.
    if finance_repo.payment_exists(bill_id, month):
        return err("החשבון כבר סומן כשולם לחודש הזה")
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
    """Reverse a bill payment for a month and remove its generated entry."""
    d = body()
    month = d.get("month") or ""
    if not MONTH_RE.match(month):
        return err("חודש לא תקין")
    bill = finance_repo.get_bill(bill_id, g.hid)
    if bill is None:
        return err("חשבון לא נמצא", 404)
    if bill["bill_type"] == "private" and bill["owner_id"] != g.user["id"]:
        return err("חשבון לא נמצא", 404)
    # Individual bills reverse one member's payment; the others reverse the
    # single monthly payment regardless of who is asking (house trust model).
    payer_id = None
    if bill["bill_type"] == "individual":
        try:
            payer_id = int(d.get("payer_id"))
        except (TypeError, ValueError):
            return err("נתונים לא תקינים")
    payment = finance_repo.get_payment(bill_id, month, g.hid, payer_id)
    if payment is None:
        return err("לא נמצא תשלום לביטול", 404)
    finance_repo.delete_payment(bill_id, month, payer_id)
    if payment["expense_id"]:
        finance_repo.delete_expense_only(payment["expense_id"], g.hid)
    if payment["private_expense_id"]:
        private_repo.delete(payment["private_expense_id"], g.user["id"])
    return jsonify(ok=True)


@bp.delete("/api/bills/<int:bill_id>")
@household_required
def delete_bill(bill_id: int):
    """Delete a recurring bill (recorded expenses remain)."""
    bill = finance_repo.get_bill(bill_id, g.hid)
    if bill is None:
        return err("חשבון לא נמצא", 404)
    if bill["bill_type"] == "private" and bill["owner_id"] != g.user["id"]:
        return err("חשבון לא נמצא", 404)
    finance_repo.delete_bill(bill_id, g.hid)
    return jsonify(ok=True)


def _category_name(bill) -> str:
    """The bill's category name, for the free-text private-ledger field."""
    row = finance_repo.get_category(bill["category_id"], bill["household_id"])
    return row["name"] if row else ""
