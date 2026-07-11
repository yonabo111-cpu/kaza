# -*- coding: utf-8 -*-
"""Shopping-list routes, including recipe lookup and bulk add."""
from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import household_required
from kaza.models import finance as finance_repo
from kaza.models import shopping as shopping_repo
from kaza.services import finance as finance_service
from kaza.services import households as households_service
from kaza.services import recipes as recipes_service
from kaza.utils import DATE_RE, body, err, valid_amount

bp = Blueprint("shopping", __name__)


@bp.post("/api/shopping")
@household_required
def add_shopping():
    """Add a single item to the shopping list."""
    d = body()
    name = (d.get("name") or "").strip()
    if not name or len(name) > 80:
        return err("נא להזין שם פריט (עד 80 תווים)")
    note = (d.get("note") or "").strip()[:80]
    shopping_repo.create(g.hid, name, note, bool(d.get("urgent")), g.user["id"])
    return jsonify(ok=True)


@bp.patch("/api/shopping/<int:item_id>")
@household_required
def toggle_shopping(item_id: int):
    """Toggle an item's done state."""
    row = shopping_repo.get_done_flag(item_id, g.hid)
    if row is None:
        return err("פריט לא נמצא", 404)
    shopping_repo.set_done(item_id, not row["done"])
    return jsonify(ok=True)


@bp.delete("/api/shopping/<int:item_id>")
@household_required
def delete_shopping(item_id: int):
    """Remove an item from the shopping list."""
    shopping_repo.delete(item_id, g.hid)
    return jsonify(ok=True)


@bp.post("/api/shopping/finish")
@household_required
def finish_shopping():
    """Clear checked-off items, optionally recording them as a shared expense."""
    done = shopping_repo.done_names(g.hid)
    if not done:
        return err("אין פריטים מסומנים")
    expense = body().get("expense")
    if expense:
        error = _record_shopping_expense(expense, done)
        if error is not None:
            return error
    shopping_repo.delete_done(g.hid)
    return jsonify(ok=True)


def _record_shopping_expense(expense: dict, done_items: list) -> object | None:
    """Persist a shopping run as an equally-split expense; return an error or ``None``."""
    try:
        amount = round(float(expense.get("amount")), 2)
        payer_id = int(expense.get("payer_id"))
        category_id = int(expense.get("category_id"))
    except (TypeError, ValueError):
        return err("נתוני הוצאה לא תקינים")
    date = expense.get("date") or ""
    if not valid_amount(amount) or not DATE_RE.match(date):
        return err("נתוני הוצאה לא תקינים")
    member_ids = households_service.member_ids(g.hid)
    if payer_id not in member_ids:
        return err("המשלם/ת אינו חבר/ה בדירה")
    if not finance_repo.category_exists(category_id, g.hid):
        return err("קטגוריה לא נמצאה")
    items = ", ".join(r["name"] for r in done_items)
    descr = "קניות: " + (items if len(items) <= 90 else items[:90] + "…")
    finance_repo.create_expense(
        g.hid, date, descr, amount, category_id, payer_id, "equal",
        finance_service.equal_shares(amount, member_ids, payer_id),
    )
    return None


@bp.post("/api/shopping/recipe")
@household_required
def recipe_lookup():
    """Resolve a free-text dish to an ingredient list."""
    dish_raw = (body().get("dish") or "").strip()
    if not dish_raw or len(dish_raw) > 80:
        return err("נא לכתוב מה בא לכם לאכול (עד 80 תווים)")
    status, payload = recipes_service.resolve(dish_raw)
    if status == recipes_service.FOUND:
        return jsonify(dish=payload["dish"], ingredients=payload["ingredients"], source=payload["source"])
    if status == recipes_service.INVALID:
        return err("נא לכתוב שם של מאכל")
    return err(f'לא מצאתי מתכון ל"{dish_raw}" — נסו שם מנה נפוץ יותר, או הוסיפו פריטים ידנית', 404)


@bp.post("/api/shopping/bulk")
@household_required
def add_shopping_bulk():
    """Add several items at once, skipping ones already on the open list."""
    items = body().get("items")
    if not isinstance(items, list) or not (1 <= len(items) <= 40):
        return err("רשימת פריטים לא תקינה")
    existing = shopping_repo.open_item_names(g.hid)
    added = skipped = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:80]
        note = str(item.get("note") or "").strip()[:80]
        if not name:
            continue
        if name in existing:
            skipped += 1
            continue
        shopping_repo.create(g.hid, name, note, False, g.user["id"])
        existing.add(name)
        added += 1
    return jsonify(ok=True, added=added, skipped=skipped)
