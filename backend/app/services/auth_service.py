"""Auth domain helpers — kept pure so routes stay thin."""

from __future__ import annotations

import re

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models import User

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128


class AuthError(Exception):
    """Raised for predictable, user-facing auth failures."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def normalize_email(raw: str | None) -> str:
    return (raw or "").strip().lower()


def validate_credentials(email: str, password: str) -> None:
    if not email or not EMAIL_RE.match(email):
        raise AuthError("validation_error", "Please enter a valid email address.")
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise AuthError(
            "validation_error",
            f"Password must be at least {MIN_PASSWORD_LEN} characters.",
        )
    if len(password) > MAX_PASSWORD_LEN:
        raise AuthError(
            "validation_error",
            f"Password must be at most {MAX_PASSWORD_LEN} characters.",
        )


def find_by_email(email: str) -> User | None:
    return db.session.scalar(select(User).where(User.email == email))


def find_by_google_sub(sub: str) -> User | None:
    return db.session.scalar(select(User).where(User.google_sub == sub))


def register_user(email: str, password: str) -> User:
    email = normalize_email(email)
    validate_credentials(email, password)

    if find_by_email(email) is not None:
        raise AuthError(
            "email_taken", "An account with this email already exists.", status=409
        )

    user = User(email=email, auth_provider="password")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(email: str, password: str) -> User:
    email = normalize_email(email)
    user = find_by_email(email)
    # Same generic message for both branches to avoid user enumeration.
    if user is None or not user.check_password(password):
        raise AuthError(
            "invalid_credentials", "Invalid email or password.", status=401
        )
    return user


# ---------------------------------------------------------------------------
# R15 — Google Sign-In via GIS id_token
# ---------------------------------------------------------------------------


def _verify_google_id_token(id_token_str: str, client_id: str) -> dict:
    """Validate the JWT signed by Google's auth servers.

    Wrapped in a helper so the smoke test can monkeypatch this function and
    stay completely offline. Returns Google's decoded claim dict on success
    and raises ``AuthError`` on any verification failure.
    """
    # Imported lazily so unit tests / smoke that monkeypatches this helper
    # don't need google-auth installed.
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            client_id,
        )
    except ValueError as exc:
        # Covers expired tokens, wrong audience, malformed JWT, etc.
        raise AuthError(
            "invalid_google_token",
            f"Google rejected the sign-in token: {exc}",
            status=401,
        ) from exc

    iss = claims.get("iss") or ""
    if iss not in {"accounts.google.com", "https://accounts.google.com"}:
        raise AuthError(
            "invalid_google_token",
            "Token was not issued by Google.",
            status=401,
        )
    return claims


def _ensure_google_login_enabled() -> str:
    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    if not client_id:
        raise AuthError(
            "google_login_disabled",
            "Google sign-in is not configured on this server.",
            status=503,
        )
    return client_id


def login_with_google_id_token(id_token_str: str) -> User:
    """Verify the ``id_token`` and return the promptpackage ``User`` it maps to.

    Lookup precedence:
      1. ``google_sub`` — stable across email changes.
      2. Verified email match — links Google onto an existing password
         account (only if Google says the email is verified, to keep
         account-takeover risk low).
      3. Otherwise create a new passwordless account.
    """
    if not id_token_str or not isinstance(id_token_str, str):
        raise AuthError(
            "validation_error", "Missing Google id_token.", status=400
        )

    client_id = _ensure_google_login_enabled()
    claims = _verify_google_id_token(id_token_str, client_id)

    sub = claims.get("sub")
    email = normalize_email(claims.get("email"))
    email_verified = bool(claims.get("email_verified", False))

    if not sub:
        raise AuthError(
            "invalid_google_token",
            "Google token is missing a subject identifier.",
            status=401,
        )

    user = find_by_google_sub(sub)
    if user is not None:
        # Refresh tracked email if Google reported a new one.
        if email and email != (user.google_email or ""):
            user.google_email = email
            db.session.commit()
        return user

    # No google_sub match → try email-based linking. Only when Google says
    # the email is verified, otherwise an attacker could create a Google
    # account with a victim's unverified address and hijack the promptpackage
    # account.
    if email and email_verified:
        existing = find_by_email(email)
        if existing is not None:
            existing.google_sub = sub
            existing.google_email = email
            # Keep ``auth_provider`` as-is — they originally signed up with
            # a password, just adding a second sign-in method.
            db.session.commit()
            return existing

    # Brand new user.
    new_email = email or f"google-{sub}@users.noreply.promptpackage"
    if find_by_email(new_email) is not None:
        # Extremely unlikely race; bail with a stable error so the client
        # can ask the user to retry.
        raise AuthError(
            "email_taken",
            "An account with this email already exists.",
            status=409,
        )
    user = User(
        email=new_email,
        google_sub=sub,
        google_email=email or None,
        auth_provider="google",
    )
    user.mark_passwordless()
    db.session.add(user)
    db.session.commit()
    return user
