# -*- coding: utf-8 -*-
"""Structured application logging."""
from __future__ import annotations

import logging

from flask import Flask

_LOG_FORMAT = "[%(asctime)s] %(levelname)s in %(name)s: %(message)s"


def configure_logging(app: Flask) -> None:
    """Set the app logger's level and attach a stream handler once."""
    level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    app.logger.setLevel(level)
    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        app.logger.addHandler(handler)
    app.logger.propagate = False
