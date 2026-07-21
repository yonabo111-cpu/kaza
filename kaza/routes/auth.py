# -*- coding: utf-8 -*-
"""Account routes: register, login, logout, and the current-user summary."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from kaza.auth import end_session, hash_password, login_required, start_session, verify_password
from kaza.models import households as households_repo
from kaza.models import users as users_repo
from kaza.security import client_ip, login_ip_limiter, login_limiter, register_ip_limiter
from kaza.services import households as households_service
from kaza.utils import EMAIL_RE, body, clean_text, err

bp = Blueprint("auth", __name__)


@bp.post("/api/register")
def register():
    """Create an account and start a session (rate-limited per IP)."""
    if not register_ip_limiter.allow(client_ip()):
        return err("יותר מדי הרשמות — נסו שוב מאוחר יותר", 429)
    d = body()
    name = clean_text(d.get("name"))
    email = (d.get("email") or "").strip().lower()
    password = d.get("password") or ""
    if not name or len(name) > 40:
        return err("נא להזין שם (עד 40 תווים)")
    if not EMAIL_RE.match(email):
        return err("כתובת אימייל לא תקינה")
    if len(password) < 6:
        return err("סיסמה קצרה מדי — לפחות 6 תווים")
    if users_repo.email_exists(email):
        return err("האימייל הזה כבר רשום — נסו להתחבר")
    user_id = users_repo.create(name, email, hash_password(password))
    start_session(user_id)
    return jsonify(ok=True)


@bp.post("/api/login")
def login():
    """Authenticate an existing account, rate-limited per email and per IP."""
    if not login_ip_limiter.allow(client_ip()):
        return err("יותר מדי ניסיונות — נסו שוב בעוד דקה", 429)
    d = body()
    email = (d.get("email") or "").strip().lower()
    password = d.get("password") or ""
    if login_limiter.is_locked(email):
        return err("יותר מדי ניסיונות — נסו שוב בעוד דקה", 429)
    user = users_repo.get_by_email(email)
    if user is None or not verify_password(user["pw_hash"], password):
        login_limiter.record_failure(email)
        return err("אימייל או סיסמה שגויים", 401)
    login_limiter.reset(email)
    start_session(user["id"])
    return jsonify(ok=True)


@bp.post("/api/logout")
def logout():
    """Clear the current session."""
    end_session()
    return jsonify(ok=True)


@bp.post("/api/account/delete")
@login_required
def delete_account():
    """Permanently delete the caller's account (blocked while they owe/are owed)."""
    error = households_service.delete_account(g.user["id"])
    if error:
        return err(error, 409)
    end_session()
    return jsonify(ok=True)


@bp.get("/api/me")
@login_required
def me():
    """Return the logged-in user and their household (if any)."""
    household = None
    if g.user["household_id"]:
        row = households_repo.get(g.user["household_id"])
        household = {"id": row["id"], "name": row["name"], "invite_code": row["invite_code"]}
    return jsonify(
        user={"id": g.user["id"], "name": g.user["name"], "email": g.user["email"]},
        household=household,
    )
