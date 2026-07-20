# -*- coding: utf-8 -*-
"""ספר המתכונים המובנה: מנה → מצרכים לרשימת קניות.

הנתונים יושבים בקבצי JSON תחת ``kaza/data/recipes/`` (מפוצלים לפי קטגוריה)
ונטענים פעם אחת בייבוא. לכל מנה כינויים בעברית ובאנגלית, כך שהחיפוש עובד
בשתי השפות. הכמויות מכוונות לבישול ביתי ל-2-3 סועדים, בלי מצרכי-בסיס שיש
בכל בית (מים, מלח, פלפל). משמש כשכבה ראשונה (מהירה וחינמית) לפני ה-AI.
"""

from __future__ import annotations

import glob
import json
import os
import re

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "recipes")


def _load_book() -> dict[str, tuple[list[str], list[tuple[str, str]]]]:
    """טוען וממזג את כל קבצי הקטגוריות — dish: (aliases, [(name, note), ...])."""
    book: dict[str, tuple[list[str], list[tuple[str, str]]]] = {}
    for path in sorted(glob.glob(os.path.join(_DATA_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            for dish, entry in json.load(fh).items():
                book[dish] = (
                    list(entry.get("a", [])),
                    [(item[0], item[1]) for item in entry["i"]],
                )
    return book


RECIPES = _load_book()

# מילות ניסוח שמסירים לפני החיפוש: "אני מעוניין לאכול X" → "X"
_FILLER_HE = re.compile(
    r"\b(אני|אנחנו|רוצה|רוצים|מעוניין|מעוניינת|מעוניינים|בא|לי|לנו|לאכול|להכין|לבשל|"
    r"שנאכל|נאכל|אוכל|היום|מחר|הערב|בערב|השבוע|בסופש|לארוחת|ארוחת|ערב|צהריים|בוקר|"
    r"משהו|איזה|אולי|בבקשה|גם|ממש|כזה|טעים)\b"
)
# "i feel like some pasta tonight" → "pasta"
_FILLER_EN = re.compile(
    r"\b(i|we|im|id|want|wanna|would|love|like|feel|feeling|craving|crave|eat|eating|"
    r"make|making|cook|cooking|have|having|some|something|tonight|today|dinner|lunch|"
    r"breakfast|please|maybe|lets|us|me|my|really|hungry|for|to|a|an|the)\b",
    re.IGNORECASE,
)


def _clean(text):
    """ניקוי בסיסי: פיסוק החוצה, רווחים מכווצים. בלי הסרת מילות ניסוח."""
    text = re.sub(r"[^\w\s'\"׳״-]", " ", str(text))
    return re.sub(r"\s+", " ", text).strip()


def normalize(text):
    """מנקה ניסוח חופשי בעברית או באנגלית ומשאיר את שם המנה."""
    text = _clean(text)
    text = _FILLER_HE.sub(" ", text)
    text = _FILLER_EN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_builtin(text):
    """מחזיר {dish, ingredients} אם המנה מוכרת, אחרת None. ההתאמה הארוכה מנצחת.

    ההתאמה נבדקת גם מול הטקסט אחרי הסרת מילות ניסוח וגם מול הטקסט הגולמי —
    כך ששמות מנות שמורכבים ממילות ניסוח ("ארוחת בוקר") עדיין נמצאים.
    """
    forms = {f.lower() for f in (normalize(text), _clean(text)) if f}
    if not forms:
        return None
    candidates = []
    for dish, (aliases, ingredients) in RECIPES.items():
        for name in [dish, *aliases]:
            needle = _clean(name).lower()
            if needle and any(needle == f or needle in f for f in forms):
                candidates.append((len(needle), dish, ingredients))
    if not candidates:
        return None
    _, dish, ingredients = max(candidates)
    return {"dish": dish, "ingredients": [{"name": n, "note": q} for n, q in ingredients]}
