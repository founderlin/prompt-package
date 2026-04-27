"""Authentication endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.services.auth_service import (
    AuthError,
    authenticate,
    login_with_google_id_token,
    register_user,
)
from app.utils.auth import get_current_user, issue_token, login_required

auth_bp = Blueprint("auth", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _auth_response(user, token: str, status: int = 200):
    return (
        jsonify({"user": user.to_dict(), "token": token, "token_type": "Bearer"}),
        status,
    )


def _error(err: AuthError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@auth_bp.post("/register")
def register():
    data = _payload()
    try:
        user = register_user(email=data.get("email"), password=data.get("password"))
    except AuthError as err:
        return _error(err)
    token = issue_token(user)
    return _auth_response(user, token, status=201)


@auth_bp.post("/login")
def login():
    data = _payload()
    try:
        user = authenticate(email=data.get("email"), password=data.get("password"))
    except AuthError as err:
        return _error(err)
    token = issue_token(user)
    return _auth_response(user, token)


@auth_bp.post("/google")
def google_login():
    """Sign in via a Google Identity Services id_token (R15)."""
    data = _payload()
    id_token = data.get("id_token") or data.get("credential")
    try:
        user = login_with_google_id_token(id_token)
    except AuthError as err:
        return _error(err)
    token = issue_token(user)
    return _auth_response(user, token)


@auth_bp.get("/google/config")
def google_config():
    """Tells the frontend whether Google login is wired up server-side.

    The frontend already knows its own VITE_GOOGLE_CLIENT_ID, but exposing
    this lets us hide the button when only one side is configured (e.g.
    backend hasn't rolled out yet).
    """
    return jsonify(
        {
            "enabled": bool(current_app.config.get("GOOGLE_CLIENT_ID")),
            "client_id": current_app.config.get("GOOGLE_CLIENT_ID"),
        }
    )


@auth_bp.post("/logout")
@login_required
def logout():
    """For JWT we have no server state to clear; the client should discard the token."""
    return jsonify({"status": "ok"})


@auth_bp.get("/me")
@login_required
def me():
    user = get_current_user()
    return jsonify({"user": user.to_dict()})
