# -*- coding: utf-8 -*-
"""Money business logic: split calculation, balances, and settlement suggestions."""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from kaza.models import finance as finance_repo
from kaza.models import households as households_repo


def equal_shares(amount: float, member_ids: Sequence[int], payer_id: int) -> dict[int, float]:
    """Split ``amount`` equally, giving the rounding remainder to the payer.

    Each member owes ``round(amount / n, 2)``; the payer absorbs the difference
    so the shares always sum back to exactly ``amount``.
    """
    n = len(member_ids)
    base = round(amount / n, 2)
    shares = {uid: base for uid in member_ids}
    shares[payer_id] = round(amount - base * (n - 1), 2)
    return shares


def previous_month(month: str) -> str:
    """Return the month key immediately before ``month`` (YYYY-MM)."""
    year, mon = int(month[:4]), int(month[5:7])
    year, mon = (year - 1, 12) if mon == 1 else (year, mon - 1)
    return f"{year:04d}-{mon:02d}"


def _net_balances(household_id: int, through_month: str) -> dict[int, float]:
    """Return ``{member_id: net balance}`` cumulative through ``through_month``.

    Balance = everything paid, minus the sum of shares, adjusted by settlements —
    counting only activity dated on or before the end of the given month.
    """
    balance = {m["id"]: 0.0 for m in households_repo.members(household_id)}
    for row in finance_repo.payer_totals(household_id, through_month):
        if row["p"] in balance:
            balance[row["p"]] += row["s"]
    for row in finance_repo.share_totals(household_id, through_month):
        if row["u"] in balance:
            balance[row["u"]] -= row["s"]
    for row in finance_repo.settlement_pairs(household_id, through_month):
        if row["from_id"] in balance:
            balance[row["from_id"]] += row["amount"]
        if row["to_id"] in balance:
            balance[row["to_id"]] -= row["amount"]
    return balance


def compute_balances(household_id: int, month: str) -> list[dict]:
    """Return each member's balance as of ``month`` (positive = owed, negative = owes).

    Balances are month-anchored with carry-over: the total reflects everything up
    to and including ``month`` (so unsettled debt rolls forward), while
    ``carryover`` isolates what was already open at the end of the previous month.
    """
    members = households_repo.members(household_id)
    total = _net_balances(household_id, month)
    carried = _net_balances(household_id, previous_month(month))
    return [
        {
            "id": m["id"],
            "name": m["name"],
            "balance": round(total[m["id"]], 2),
            "carryover": round(carried[m["id"]], 2),
        }
        for m in members
    ]


def suggest_transfers(balances: Iterable[Mapping]) -> list[dict]:
    """Propose a minimal set of transfers that settles all balances.

    Greedy matching: the largest debtor pays the largest creditor until both
    are cleared, repeating until everyone nets to zero.
    """
    debtors = sorted(
        [dict(b) for b in balances if b["balance"] < -0.01], key=lambda x: x["balance"]
    )
    creditors = sorted(
        [dict(b) for b in balances if b["balance"] > 0.01], key=lambda x: -x["balance"]
    )
    transfers: list[dict] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = round(min(-debtors[i]["balance"], creditors[j]["balance"]), 2)
        if amount > 0.01:
            transfers.append(
                {
                    "from_id": debtors[i]["id"],
                    "from": debtors[i]["name"],
                    "to_id": creditors[j]["id"],
                    "to": creditors[j]["name"],
                    "amount": amount,
                }
            )
        debtors[i]["balance"] = round(debtors[i]["balance"] + amount, 2)
        creditors[j]["balance"] = round(creditors[j]["balance"] - amount, 2)
        if debtors[i]["balance"] >= -0.01:
            i += 1
        if creditors[j]["balance"] <= 0.01:
            j += 1
    return transfers
