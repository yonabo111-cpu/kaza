# -*- coding: utf-8 -*-
"""Access-log tests: API requests are logged (method/path/status/duration);
the health probe is not. Server-less; run directly or via tests/run_all.py.

    python tests/logging_test.py
"""

import logging
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["KAZA_ENV"] = "testing"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="kaza-log-test-")

from kaza import create_app  # noqa: E402

PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


app = create_app()

captured = []


class _Capture(logging.Handler):
    def emit(self, record):
        captured.append(record.getMessage())


app.logger.addHandler(_Capture())
app.logger.setLevel(logging.INFO)
client = app.test_client()

# An API request (401, unauthenticated) is still logged with its details.
client.get("/api/me")
check("API request is access-logged", any("/api/me" in m and "401" in m for m in captured))
check(
    "log line carries method and duration",
    any(m.startswith("GET /api/me") and "ms" in m for m in captured),
)

# The health probe is intentionally not access-logged (would be noise).
before = len(captured)
client.get("/healthz")
check("healthz is not access-logged", not any("/healthz" in m for m in captured))
check("healthz adds no log line", len(captured) == before)

print(f"ALL {len(PASSED)} CHECKS PASSED")
