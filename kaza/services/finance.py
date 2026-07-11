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


def compute_balances(household_id: int) -> list[dict]:
    """Return each member's net balance (positive = owed money, negative = owes).

    Balance = everything they paid, minus the sum of their shares, adjusted by
    recorded settlements.
    """
    members = households_repo.members(household_id)
    balance = {m["id"]: 0.0 for m in members}

    for row in finance_repo.payer_totals(household_id):
        if row["p"] in balance:
            balance[row["p"]] += row["s"]
    for row in finance_repo.share_totals(household_id):
        if row["u"] in balance:
            balance[row["u"]] -= row["s"]
    for row in finance_repo.settlement_pairs(household_id):
        if row["from_id"] in balance:
            balance[row["from_id"]] += row["amount"]
        if row["to_id"] in balance:
            balance[row["to_id"]] -= row["amount"]

    return [
        {"id": m["id"], "name": m["name"], "balance": round(balance[m["id"]], 2)}
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
            transfers.append({
                "from_id": debtors[i]["id"], "from": debtors[i]["name"],
                "to_id": creditors[j]["id"], "to": creditors[j]["name"],
                "amount": amount,
            })
        debtors[i]["balance"] = round(debtors[i]["balance"] + amount, 2)
        creditors[j]["balance"] = round(creditors[j]["balance"] - amount, 2)
        if debtors[i]["balance"] >= -0.01:
            i += 1
        if creditors[j]["balance"] <= 0.01:
            j += 1
    return transfers
