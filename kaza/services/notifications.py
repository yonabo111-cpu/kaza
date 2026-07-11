# -*- coding: utf-8 -*-
"""Derived in-app notifications.

Notifications are computed from current state on every request — there is no
table and no scheduler. Each alert appears while its condition holds and
disappears once resolved. Everything here is relative to *today*, not the month
being viewed, so reminders stay accurate regardless of navigation.
"""
from __future__ import annotations

from datetime import date

from kaza.models import chores as chores_repo
from kaza.models import finance as finance_repo
from kaza.models import private_expenses as private_repo
from kaza.models import shopping as shopping_repo
from kaza.models import users as users_repo
from kaza.services import finance as finance_service

# Sort order for the notification feed (most urgent first).
_SEVERITY_RANK = {"critical": 0, "warn": 1, "info": 2}

# Fraction of a budget at which a "approaching the cap" warning starts.
_NEAR_LIMIT = 0.85


def _ils(amount: float) -> str:
    """Format an amount as whole shekels, e.g. ``1,234 ₪``."""
    return f"{amount:,.0f} ₪"


def build_notifications(household_id: int, user_id: int) -> list[dict]:
    """Return the ordered notification feed for ``user_id`` in ``household_id``."""
    today = date.today()
    month = today.strftime("%Y-%m")
    out: list[dict] = []

    _bill_notifications(household_id, today, month, out)
    _budget_notifications(household_id, month, out)
    _personal_budget_notifications(household_id, user_id, month, out)
    _debt_notification(household_id, user_id, out)
    _chore_notification(household_id, user_id, out)
    _shopping_notification(household_id, out)

    out.sort(key=lambda n: _SEVERITY_RANK[n["severity"]])
    return out


def _bill_notifications(household_id: int, today: date, month: str, out: list[dict]) -> None:
    """Flag unpaid bills that are overdue or due within three days."""
    paid = finance_repo.paid_bill_ids(household_id, month)
    for bill in finance_repo.bills_for(household_id):
        if bill["id"] in paid:
            continue
        if today.day > bill["due_day"]:
            out.append({
                "id": f"bill-late-{bill['id']}-{month}", "severity": "critical", "icon": "🧾",
                "text": f"״{bill['name']}״ באיחור — יום החיוב ({bill['due_day']} בחודש) עבר",
                "tab": "bills",
            })
        elif bill["due_day"] - today.day <= 3:
            out.append({
                "id": f"bill-due-{bill['id']}-{month}", "severity": "warn", "icon": "🧾",
                "text": f"״{bill['name']}״ ({_ils(bill['amount'])}) לתשלום עד יום {bill['due_day']} בחודש",
                "tab": "bills",
            })


def _budget_notifications(household_id: int, month: str, out: list[dict]) -> None:
    """Flag household categories that are over or near their monthly budget."""
    spent = finance_repo.spent_by_category(household_id, month)
    for category in finance_repo.categories_for(household_id):
        if category["budget"] <= 0:
            continue
        used = spent.get(category["id"], 0)
        if used > category["budget"]:
            out.append({
                "id": f"budget-over-{category['id']}-{month}", "severity": "critical", "icon": "🎯",
                "text": f"חריגה בתקציב ״{category['name']}״ — {_ils(used)} מתוך {_ils(category['budget'])}",
                "tab": "budgets",
            })
        elif used >= _NEAR_LIMIT * category["budget"]:
            out.append({
                "id": f"budget-near-{category['id']}-{month}", "severity": "warn", "icon": "🎯",
                "text": f"״{category['name']}״ מתקרב לתקרה — {_ils(used)} מתוך {_ils(category['budget'])}",
                "tab": "budgets",
            })


def _personal_budget_notifications(
    household_id: int, user_id: int, month: str, out: list[dict]
) -> None:
    """Flag the user's private budget (visible only to them)."""
    budget = users_repo.get_personal_budget(user_id)
    if budget <= 0:
        return
    combined = (
        finance_repo.share_total_for_month(user_id, household_id, month)
        + private_repo.total_for_month(user_id, month)
    )
    if combined > budget:
        out.append({
            "id": f"personal-over-{month}", "severity": "critical", "icon": "🔒",
            "text": f"חרגת מהתקציב האישי — {_ils(combined)} מתוך {_ils(budget)}",
            "tab": "personal",
        })
    elif combined >= _NEAR_LIMIT * budget:
        out.append({
            "id": f"personal-near-{month}", "severity": "warn", "icon": "🔒",
            "text": f"התקציב האישי מתקרב לתקרה — {_ils(combined)} מתוך {_ils(budget)}",
            "tab": "personal",
        })


def _debt_notification(household_id: int, user_id: int, out: list[dict]) -> None:
    """Flag an open balance the user owes the household."""
    mine = next(
        (b["balance"] for b in finance_service.compute_balances(household_id) if b["id"] == user_id),
        0,
    )
    if mine < -0.01:
        out.append({
            "id": "debt", "severity": "info", "icon": "💸",
            "text": f"יש לך חוב פתוח של {_ils(-mine)} לשותפים — אפשר לסגור בלשונית הוצאות",
            "tab": "expenses",
        })


def _chore_notification(household_id: int, user_id: int, out: list[dict]) -> None:
    """Flag chores currently assigned to the user."""
    mine = [c["name"] for c in chores_repo.assigned_to(household_id, user_id)]
    if mine:
        names = ", ".join(mine[:3]) + ("…" if len(mine) > 3 else "")
        out.append({
            "id": f"chores-{len(mine)}", "severity": "info", "icon": "🧽",
            "text": f"התור שלך: {names}", "tab": "chores",
        })


def _shopping_notification(household_id: int, out: list[dict]) -> None:
    """Flag urgent, not-yet-bought shopping items."""
    urgent = shopping_repo.urgent_open_count(household_id)
    if urgent:
        out.append({
            "id": f"shopping-urgent-{urgent}", "severity": "info", "icon": "🛒",
            "text": f"{urgent} פריטים דחופים מחכים ברשימת הקניות", "tab": "shopping",
        })
