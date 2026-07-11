# -*- coding: utf-8 -*-
"""WSGI entry point for production servers (e.g. ``gunicorn wsgi:app``)."""

from __future__ import annotations

from kaza import create_app

app = create_app()
