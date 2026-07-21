# -*- coding: utf-8 -*-
"""Password-reset tests: token issue/consume, expiry, single-use, no enumeration.

Server-less: builds the app on a throwaway database and drives it with Flask's
test client, capturing the reset link by stubbing the mailer. Run directly or
via tests/run_all.py.

    python tests/password_reset_test.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["KAZA_ENV"] = "testing"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="kaza-reset-test-")

from kaza import create_app  # noqa: E402
from kaza.services import accounts as accounts_service  # noqa: E402

PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
    else:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)


# Capture outgoing mail instead of sending it, and remember the last link.
sent = []
accounts_service.send_email = lambda to, subject, body: sent.append((to, body)) or True


def token_from_last_email():
    return sent[-1][1].split("?reset=")[1].split()[0].strip()


app = create_app()
client = app.test_client()

client.post(
    "/api/register", json={"name": "מאיה", "email": "reset@example.com", "password": "oldpass1"}
)
client.post("/api/logout")

# --- forgot for a real address issues a link ---------------------------------
r = client.post("/api/password/forgot", json={"email": "reset@example.com"})
check("forgot returns ok", r.status_code == 200)
check("an email was queued", len(sent) == 1 and sent[-1][0] == "reset@example.com")
token = token_from_last_email()

# --- forgot for an unknown address looks identical (no enumeration) ----------
r = client.post("/api/password/forgot", json={"email": "nobody@example.com"})
check("forgot for unknown still returns ok", r.status_code == 200)
check("no email queued for unknown address", len(sent) == 1)

# --- too-short new password is rejected --------------------------------------
r = client.post("/api/password/reset", json={"token": token, "password": "123"})
check("short password rejected", r.status_code == 400)

# --- a wrong token is rejected -----------------------------------------------
r = client.post("/api/password/reset", json={"token": "not-a-real-token", "password": "newpass1"})
check("invalid token rejected", r.status_code == 400)

# --- the valid token resets the password -------------------------------------
r = client.post("/api/password/reset", json={"token": token, "password": "newpass1"})
check("valid token resets password", r.status_code == 200)

# --- old password no longer works; new one does ------------------------------
check(
    "old password no longer works",
    client.post(
        "/api/login", json={"email": "reset@example.com", "password": "oldpass1"}
    ).status_code
    == 401,
)
client.post("/api/logout")
check(
    "new password works",
    client.post(
        "/api/login", json={"email": "reset@example.com", "password": "newpass1"}
    ).status_code
    == 200,
)
client.post("/api/logout")

# --- the token is single-use -------------------------------------------------
r = client.post("/api/password/reset", json={"token": token, "password": "another1"})
check("used token cannot be reused", r.status_code == 400)

# --- an expired token is rejected --------------------------------------------
import hashlib  # noqa: E402

from kaza.models import password_resets as resets_repo  # noqa: E402
from kaza.models import users as users_repo  # noqa: E402

with app.app_context():
    from kaza.db import get_db

    uid = users_repo.get_by_email("reset@example.com")["id"]
    expired_token = "expired-token-xyz"
    resets_repo.create(
        uid, hashlib.sha256(expired_token.encode()).hexdigest(), "2000-01-01 00:00:00"
    )
    get_db().commit()
r = client.post("/api/password/reset", json={"token": "expired-token-xyz", "password": "afterexp1"})
check("expired token rejected", r.status_code == 400)

print(f"ALL {len(PASSED)} CHECKS PASSED")
