"""JWT helpers and the ``login_required`` decorator.

Tokens are issued on login/register and verified on each request via the
``Authorization: Bearer <token>`` header. We deliberately keep things
stateless (no server-side session store) for MVP simplicity.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any

import jwt
from flask import current_app, g, jsonify, request

from app.extensions import db
from app.models import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue_token(user: User) -> str:
    """Sign a JWT for the given user. Returns the encoded string."""
    cfg = current_app.config
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(days=cfg["JWT_EXPIRES_DAYS"])).timestamp()),
    }
    token = jwt.encode(payload, cfg["JWT_SECRET_KEY"], algorithm=cfg["JWT_ALGORITHM"])
    return token if isinstance(token, str) else token.decode("utf-8")


def decode_token(token: str) -> dict[str, Any]:
    cfg = current_app.config
    return jwt.decode(token, cfg["JWT_SECRET_KEY"], algorithms=[cfg["JWT_ALGORITHM"]])


def _extract_bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip() or None


def _unauthorized(message: str = "Authentication required."):
    return jsonify({"error": "unauthorized", "message": message}), 401


def login_required(view):
    """Reject requests without a valid bearer token.

    On success the resolved ``User`` is attached to ``flask.g.current_user``.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        if not token:
            return _unauthorized("Missing bearer token.")
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return _unauthorized("Token expired.")
        except jwt.InvalidTokenError:
            return _unauthorized("Invalid token.")

        user_id = payload.get("sub")
        if not user_id:
            return _unauthorized("Token missing subject.")

        user = db.session.get(User, int(user_id))
        if user is None:
            return _unauthorized("User no longer exists.")

        g.current_user = user
        return view(*args, **kwargs)

    return wrapper


def get_current_user() -> User | None:
    return getattr(g, "current_user", None)
