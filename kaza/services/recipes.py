# -*- coding: utf-8 -*-
"""Recipe → shopping-list resolution.

Resolution order: the built-in Israeli cookbook (offline, instant) → the SQLite
cache → an AI lookup (only when ``ANTHROPIC_API_KEY`` is configured). AI results
are cached so each dish is resolved at most once.
"""

from __future__ import annotations

import json
import os
from typing import Any

from kaza.models import recipes as recipe_repo

# The offline built-in cookbook + query normaliser.
from kaza.recipe_book import normalize as normalize_dish
from kaza.recipe_book import resolve_builtin

# JSON schema the model must return — a dish name plus name/quantity pairs.
RECIPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dish": {"type": "string"},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "note": {"type": "string"}},
                "required": ["name", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["dish", "ingredients"],
    "additionalProperties": False,
}

RECIPE_PROMPT = (
    'צור רשימת קניות עבור המנה: "{dish}".\n'
    "כללים: מצרכים לבישול ביתי ל-2-3 סועדים, בעברית. אל תכלול מים, מלח, פלפל שחור "
    'או דברים שיש בכל מטבח. בשדה note כתוב כמות קצרה (למשל: "500 גרם", "2 יחידות", '
    '"קופסה"). בשדה dish כתוב את שם המנה המנוקה. '
    "אם הטקסט אינו שם של מאכל אמיתי — החזר ingredients ריק."
)

# Resolution outcome statuses returned to the route layer.
FOUND = "found"
INVALID = "invalid"
NOT_FOUND = "not_found"


def ai_recipe(dish: str) -> dict | None:
    """Ask Claude for a dish's ingredients; ``None`` if unavailable or not a dish.

    Active only when the ``anthropic`` package and an API key are present. Any
    failure (missing key, network error, refusal, empty result) degrades
    gracefully to ``None`` so the feature never breaks the request.
    """
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(timeout=30.0)
        response = client.messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
            max_tokens=2000,
            output_config={"format": {"type": "json_schema", "schema": RECIPE_SCHEMA}},
            messages=[{"role": "user", "content": RECIPE_PROMPT.format(dish=dish)}],
        )
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            return None
        data = json.loads(text)
        ingredients = [
            {
                "name": str(i.get("name", "")).strip()[:80],
                "note": str(i.get("note", "")).strip()[:80],
            }
            for i in data.get("ingredients", [])
            if str(i.get("name", "")).strip()
        ][:25]
        if not ingredients:
            return None
        dish_name = (str(data.get("dish", "")).strip() or dish)[:80]
        return {"dish": dish_name, "ingredients": ingredients}
    except Exception:
        return None


def resolve(dish_raw: str) -> tuple[str, dict | None]:
    """Resolve a free-text dish to ingredients.

    Returns ``(status, payload)`` where status is :data:`FOUND` (payload has
    ``dish``/``ingredients``/``source``), :data:`INVALID` (not a dish name), or
    :data:`NOT_FOUND` (nothing matched).
    """
    builtin = resolve_builtin(dish_raw)
    if builtin:
        return FOUND, {
            "dish": builtin["dish"],
            "ingredients": builtin["ingredients"],
            "source": "builtin",
        }

    key = normalize_dish(dish_raw)
    if not key:
        return INVALID, None

    cached = recipe_repo.get_cached(key)
    if cached:
        payload = json.loads(cached)
        return FOUND, {
            "dish": payload["dish"],
            "ingredients": payload["ingredients"],
            "source": "cache",
        }

    ai = ai_recipe(key)
    if ai:
        recipe_repo.put_cached(key, json.dumps(ai, ensure_ascii=False))
        return FOUND, {"dish": ai["dish"], "ingredients": ai["ingredients"], "source": "ai"}

    return NOT_FOUND, None
