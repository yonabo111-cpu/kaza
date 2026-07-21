# -*- coding: utf-8 -*-
"""Household-level business logic: membership, invites, seeding, bulletin shaping."""

from __future__ import annotations

import secrets
from datetime import date

from kaza.auth import hash_password
from kaza.models import bulletin as bulletin_repo
from kaza.models import chores as chores_repo
from kaza.models import finance as finance_repo
from kaza.models import households as households_repo
from kaza.models import password_resets as resets_repo
from kaza.models import private_expenses as private_repo
from kaza.models import users as users_repo
from kaza.services import finance as finance_service

# Placeholder name shown for an anonymized (deleted) account in shared history.
_DELETED_NAME = "חשבון שנמחק"

# Invite-code alphabet without visually ambiguous characters (no 0/O, 1/I/L).
_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_INVITE_LENGTH = 6

# Default content created for a brand-new household. Category budgets are 0 —
# the app measures spending against each member's PERSONAL budget instead.
_SEED_CATEGORIES = [
    ("סופר ומזון", 0),
    ("אוכל בחוץ", 0),
    ("בית וניקיון", 0),
    ("חשבונות ודיור", 0),
    ("בילויים", 0),
    ("אחר", 0),
]
_SEED_BILLS = [
    ("שכר דירה", 4500, 1),
    ("ארנונה", 380, 15),
    ("חשמל", 300, 10),
    ("מים", 120, 10),
    ("אינטרנט", 100, 5),
    ("ועד בית", 150, 1),
]
_SEED_CHORES = [
    ("שטיפת רצפה", "שבועי"),
    ("כלים / מדיח", "יומי"),
    ("הוצאת זבל", "יומיים"),
    ("ניקוי שירותים ואמבטיה", "שבועי"),
]
_BILLS_CATEGORY = "חשבונות ודיור"


def member_ids(household_id: int) -> list[int]:
    """Return the household's member ids in join order."""
    return [m["id"] for m in households_repo.members(household_id)]


def member_name_map(household_id: int) -> dict[int, str]:
    """Return ``{user_id: name}`` for the household's members."""
    return {m["id"]: m["name"] for m in households_repo.members(household_id)}


def is_member(household_id: int, user_id: int) -> bool:
    """True if ``user_id`` belongs to the household."""
    return user_id in member_ids(household_id)


def new_invite_code() -> str:
    """Generate a unique, unambiguous 6-character invite code."""
    while True:
        code = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(_INVITE_LENGTH))
        if not households_repo.invite_code_exists(code):
            return code


def seed_household(household_id: int, creator_id: int) -> None:
    """Populate a new household with default categories, bills, and chores."""
    category_ids: dict[str, int] = {}
    for name, budget in _SEED_CATEGORIES:
        category_ids[name] = finance_repo.create_category(household_id, name, budget)

    bills_category = category_ids[_BILLS_CATEGORY]
    for name, amount, due_day in _SEED_BILLS:
        finance_repo.create_bill(household_id, name, amount, due_day, bills_category)

    for name, freq in _SEED_CHORES:
        chores_repo.create(household_id, name, freq, creator_id)


def leave_household(household_id: int, user_id: int) -> str | None:
    """Remove ``user_id`` from a household. Return an error message, or ``None``.

    Leaving is blocked while the member has an open balance — otherwise a
    departing roommate could walk away from a debt (or an uncollectable credit).
    A solo member always nets to zero and can leave freely. On success their
    chore assignments are cleared and their private bills removed; shared
    expense history stays intact for the remaining members.
    """
    month = date.today().strftime("%Y-%m")
    balances = finance_service.compute_balances(household_id, month)
    mine = next((b["balance"] for b in balances if b["id"] == user_id), 0)
    if abs(mine) >= 0.01:
        return "יש לך יתרה פתוחה בדירה — סגרו את ההתחשבנות לפני עזיבה"

    chores_repo.unassign_all(household_id, user_id)
    finance_repo.delete_private_bills_for(household_id, user_id)
    users_repo.clear_household(user_id)
    return None


def delete_account(user_id: int) -> str | None:
    """Delete a user's account. Return an error message, or ``None`` on success.

    The same settle-up guard as leaving applies. If the user is the last member
    of their household, the whole household and its data are removed. Otherwise
    they are detached and their personal data is erased. The user row itself is
    hard-deleted when nothing references it anymore, or anonymized (name/email/
    password scrubbed) when shared history still points at it — so a departed
    roommate's expenses stay attributable without exposing who they were.
    """
    user = users_repo.get_by_id(user_id)
    if user is None:
        return None
    household_id = user["household_id"]

    if household_id:
        month = date.today().strftime("%Y-%m")
        balances = finance_service.compute_balances(household_id, month)
        mine = next((b["balance"] for b in balances if b["id"] == user_id), 0)
        if abs(mine) >= 0.01:
            return "יש לך יתרה פתוחה בדירה — סגרו את ההתחשבנות לפני מחיקת החשבון"
        others = [m for m in member_ids(household_id) if m != user_id]
        chores_repo.unassign_all(household_id, user_id)
        finance_repo.delete_private_bills_for(household_id, user_id)
        users_repo.clear_household(user_id)
        if not others:
            households_repo.delete_cascade(household_id)

    private_repo.delete_all_for(user_id)
    resets_repo.delete_for_user(user_id)

    if users_repo.is_referenced(user_id):
        placeholder = f"deleted-{user_id}-{secrets.token_hex(4)}@kaza.invalid"
        dead_hash = hash_password(secrets.token_hex(16))
        users_repo.anonymize(user_id, _DELETED_NAME, placeholder, dead_hash)
    else:
        users_repo.delete(user_id)
    return None


def bulletin_notes(household_id: int) -> list[dict]:
    """Return shaped bulletin notes with author names attached."""
    names = member_name_map(household_id)
    return [
        {
            "id": note["id"],
            "content": note["content"],
            "is_pinned": bool(note["is_pinned"]),
            "created_at": note["created_at"],
            "author_id": note["user_id"],
            "author": names.get(note["user_id"], "?"),
        }
        for note in bulletin_repo.list_for(household_id)
    ]
