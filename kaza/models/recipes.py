# -*- coding: utf-8 -*-
"""Data access for ``recipe_cache`` — memoised AI recipe lookups.

Caching each resolved dish means an external model is queried at most once per
dish, keeping the recipe feature cheap and fast on repeat requests.
"""
from __future__ import annotations

from kaza.db import get_db


def get_cached(dish_key: str) -> str | None:
    """Return the cached JSON payload for ``dish_key``, or ``None``."""
    row = get_db().execute(
        "SELECT payload FROM recipe_cache WHERE dish_key=?", (dish_key,)
    ).fetchone()
    return row["payload"] if row else None


def put_cached(dish_key: str, payload_json: str) -> None:
    """Store (or replace) the JSON payload for ``dish_key``."""
    get_db().execute(
        "INSERT OR REPLACE INTO recipe_cache(dish_key,payload) VALUES (?,?)",
        (dish_key, payload_json),
    )
