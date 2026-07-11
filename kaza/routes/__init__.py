# -*- coding: utf-8 -*-
"""HTTP layer: one Flask blueprint per domain.

Route handlers validate input, enforce access via the auth decorators, call
the service/model layers, and shape the JSON response. They contain no SQL and
no business rules of their own.
"""
from __future__ import annotations

from flask import Flask

from kaza.routes import (
    auth,
    bills,
    bulletin,
    chores,
    finance,
    households,
    personal,
    shopping,
    state,
    system,
)

# Every blueprint that makes up the API surface.
_BLUEPRINTS = (
    auth.bp,
    households.bp,
    state.bp,
    finance.bp,
    shopping.bp,
    bills.bp,
    chores.bp,
    bulletin.bp,
    personal.bp,
    system.bp,
)


def register_blueprints(app: Flask) -> None:
    """Attach all API blueprints to the application."""
    for blueprint in _BLUEPRINTS:
        app.register_blueprint(blueprint)
