# -*- coding: utf-8 -*-
"""Development entry point.

Builds the app via the factory and serves it with waitress (falling back to
Flask's built-in server). For production, prefer ``wsgi:app`` behind gunicorn.
Run directly: ``python app.py``.
"""
from __future__ import annotations

import os

from kaza import create_app

app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    try:
        from waitress import serve

        print(f"* Serving on http://localhost:{port} (waitress)")
        serve(app, host="0.0.0.0", port=port)
    except ImportError:
        app.run(host="0.0.0.0", port=port)
