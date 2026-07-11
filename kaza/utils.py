# -*- coding: utf-8 -*-
"""Small request/validation helpers shared across the route layer."""
from __future__ import annotations

import re
from typing import Any

from flask import jsonify, request
from werkzeug.wrappers import Response

# Input-format validators, compiled once.
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")          # YYYY-MM
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")               # YYYY-MM-DD
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Upper bound applied to every monetary amount, guarding against overflow/typos.
MAX_AMOUNT = 1_000_000


def err(message: str, code: int = 400) -> tuple[Response, int]:
    """Build a JSON error response ``{"error": message}`` with an HTTP code."""
    return jsonify(error=message), code


def body() -> dict[str, Any]:
    """Return the parsed JSON request body, or an empty dict if absent/invalid."""
    return request.get_json(silent=True) or {}


def valid_amount(amount: float) -> bool:
    """True when ``amount`` is a positive value within the allowed ceiling."""
    return 0 < amount <= MAX_AMOUNT
