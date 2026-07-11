# -*- coding: utf-8 -*-
"""Household-level business logic: membership, invites, seeding, bulletin shaping."""
from __future__ import annotations

import secrets

from kaza.models import bulletin as bulletin_repo
from kaza.models import chores as chores_repo
from kaza.models import finance as finance_repo
from kaza.models import households as households_repo

# Invite-code alphabet without visually ambiguous characters (no 0/O, 1/I/L).
_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_INVITE_LENGTH = 6

# Default content created for a brand-new household.
_SEED_CATEGORIES = [
    ("סופר ומזון", 1600), ("אוכל בחוץ", 600), ("בית וניקיון", 250),
    ("חשבונות ודיור", 5500), ("בילויים", 500), ("אחר", 300),
]
_SEED_BILLS = [
    ("שכר דירה", 4500, 1), ("ארנונה", 380, 15), ("חשמל", 300, 10),
    ("מים", 120, 10), ("אינטרנט", 100, 5), ("ועד בית", 150, 1),
]
_SEED_CHORES = [
    ("שטיפת רצפה", "שבועי"), ("כלים / מדיח", "יומי"),
    ("הוצאת זבל", "יומיים"), ("ניקוי שירותים ואמבטיה", "שבועי"),
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
