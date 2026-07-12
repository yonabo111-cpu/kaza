# -*- coding: utf-8 -*-
"""Assembles the single ``/api/state`` payload the frontend renders from.

One request returns everything the dashboard needs for a given month: members,
categories with spend, expenses, balances and suggested transfers, settlements,
shopping, bills, chores, a six-month trend, the caller's private ledger, the
bulletin board, and derived notifications.
"""

from __future__ import annotations

from typing import Any

from kaza.db import Row
from kaza.models import chores as chores_repo
from kaza.models import finance as finance_repo
from kaza.models import households as households_repo
from kaza.models import private_expenses as private_repo
from kaza.models import shopping as shopping_repo
from kaza.services import finance as finance_service
from kaza.services import households as households_service
from kaza.services import notifications as notifications_service

# How many months of history the trend chart shows (including the current one).
_CHART_MONTHS = 6


def _recent_months(month: str, count: int) -> list[str]:
    """Return ``count`` month keys ending at ``month`` (oldest first)."""
    year, mon = int(month[:4]), int(month[5:7])
    months = []
    for i in range(count - 1, -1, -1):
        mm = (mon - 1 - i) % 12 + 1
        yy = year + (mon - 1 - i - (mm - 1)) // 12
        months.append(f"{yy:04d}-{mm:02d}")
    return months


def build_state(household_id: int, user: Row, month: str) -> dict[str, Any]:
    """Return the full dashboard payload for ``user`` in ``month``."""
    members = households_repo.members(household_id)
    member_list = [{"id": m["id"], "name": m["name"]} for m in members]
    names = {m["id"]: m["name"] for m in members}

    categories = _build_categories(household_id, month)
    cat_names = {c["id"]: c["name"] for c in categories}

    balances = finance_service.compute_balances(household_id, month)
    chart_months = _recent_months(month, _CHART_MONTHS)
    totals = finance_repo.monthly_totals(household_id, chart_months[0])
    prev_month = chart_months[-2] if len(chart_months) > 1 else None

    household = households_repo.get(household_id)
    return {
        "user": {"id": user["id"], "name": user["name"], "email": user["email"]},
        "household": {
            "id": household["id"],
            "name": household["name"],
            "invite_code": household["invite_code"],
        },
        "members": member_list,
        "month": month,
        "categories": categories,
        "expenses": _build_expenses(household_id, month, user["id"], cat_names, names),
        "balances": balances,
        "transfers": finance_service.suggest_transfers(balances),
        "settlements": _build_settlements(household_id, names),
        "shopping": _build_shopping(household_id, names),
        "bills": _build_bills(household_id, month, cat_names, names),
        "chores": _build_chores(household_id, names),
        "chart": [{"month": m, "total": totals.get(m, 0)} for m in chart_months],
        "total": totals.get(month, 0),
        "prev_total": totals.get(prev_month, 0),
        "personal": _build_personal(household_id, user, month, chart_months),
        "bulletin": households_service.bulletin_notes(household_id),
        "notifications": notifications_service.build_notifications(household_id, user["id"]),
    }


def _build_categories(household_id: int, month: str) -> list[dict]:
    """Return categories with the amount spent this month."""
    spent = finance_repo.spent_by_category(household_id, month)
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "budget": c["budget"],
            "spent": round(spent.get(c["id"], 0), 2),
        }
        for c in finance_repo.categories_for(household_id)
    ]


def _build_expenses(
    household_id: int, month: str, user_id: int, cat_names: dict, names: dict
) -> list[dict]:
    """Return this month's expenses, tagged with the caller's own share.

    ``my_share`` is what the expense cost this user (0 if none), and ``mine`` is
    true when they either paid or hold a share — the frontend uses it to show a
    personal, "just my expenses" view.
    """
    my_shares = finance_repo.user_shares_for_expenses(user_id, household_id, month)
    result = []
    for e in finance_repo.expenses_for_month(household_id, month):
        my_share = round(my_shares.get(e["id"], 0), 2)
        result.append(
            {
                "id": e["id"],
                "date": e["date"],
                "descr": e["descr"],
                "amount": e["amount"],
                "my_share": my_share,
                "mine": my_share > 0 or e["payer_id"] == user_id,
                "category_id": e["category_id"],
                "category": cat_names.get(e["category_id"], "—"),
                "payer_id": e["payer_id"],
                "payer": names.get(e["payer_id"], "?"),
                "split_type": e["split_type"],
            }
        )
    return result


def _build_settlements(household_id: int, names: dict) -> list[dict]:
    """Return the most recent settlements with member names resolved."""
    return [
        {
            "id": s["id"],
            "date": s["date"],
            "amount": s["amount"],
            "from": names.get(s["from_id"], "?"),
            "to": names.get(s["to_id"], "?"),
        }
        for s in finance_repo.recent_settlements(household_id)
    ]


def _build_shopping(household_id: int, names: dict) -> list[dict]:
    """Return the shopping list with the adder's name resolved."""
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "note": s["note"],
            "urgent": bool(s["urgent"]),
            "done": bool(s["done"]),
            "added_by": names.get(s["added_by"], "?"),
        }
        for s in shopping_repo.list_for(household_id)
    ]


def _build_bills(household_id: int, month: str, cat_names: dict, names: dict) -> list[dict]:
    """Return bills with their paid status for the month resolved."""
    payments = finance_repo.payments_for_month(household_id, month)
    bills = []
    for b in finance_repo.bills_for(household_id):
        payment = payments.get(b["id"])
        bills.append(
            {
                "id": b["id"],
                "name": b["name"],
                "amount": b["amount"],
                "due_day": b["due_day"],
                "category_id": b["category_id"],
                "category": cat_names.get(b["category_id"], "—"),
                "paid": (
                    {"payer_id": payment["payer_id"], "payer": names.get(payment["payer_id"], "?")}
                    if payment
                    else None
                ),
            }
        )
    return bills


def _build_chores(household_id: int, names: dict) -> list[dict]:
    """Return chores with the current assignee's name resolved."""
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "freq": c["freq"],
            "assignee_id": c["assignee_id"],
            "assignee": names.get(c["assignee_id"], "?"),
            "last_done": c["last_done"],
        }
        for c in chores_repo.list_for(household_id)
    ]


def _build_personal(household_id: int, user: Row, month: str, chart_months: list[str]) -> dict:
    """Return the caller's private ledger view (never exposed to other members)."""
    user_id = user["id"]
    private_expenses = [
        {
            "id": p["id"],
            "date": p["date"],
            "descr": p["descr"],
            "amount": p["amount"],
            "category": p["category"],
        }
        for p in private_repo.list_for_month(user_id, month)
    ]
    priv_by_month = private_repo.monthly_totals(user_id, chart_months[0])
    share_by_month = finance_repo.share_by_month(user_id, household_id, chart_months[0])
    return {
        "budget": user["personal_budget"],
        "expenses": private_expenses,
        "private_total": priv_by_month.get(month, 0),
        "share_total": share_by_month.get(month, 0),
        "chart": [
            {"month": m, "total": round(priv_by_month.get(m, 0) + share_by_month.get(m, 0), 2)}
            for m in chart_months
        ],
        "categories": private_repo.distinct_categories(user_id),
    }
