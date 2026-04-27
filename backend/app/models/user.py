"""User model."""

from __future__ import annotations

from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

# R15: a sentinel hash written into ``password_hash`` for users who signed up
# via Google (no local password). It's deliberately NOT a valid pbkdf2/scrypt
# hash, so ``check_password_hash`` always returns False — i.e. there's no way
# to "log in with empty string" or any other guess. Keeping the column
# NOT NULL means we don't have to ALTER existing schemas on SQLite.
PASSWORDLESS_PLACEHOLDER = "!google-oauth-only!"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Filled in R4 — kept here so the table is shape-stable from the start.
    openrouter_api_key_encrypted = db.Column(db.Text, nullable=True)

    # R15: Google Sign-In bookkeeping. ``google_sub`` is the stable ID Google
    # gives us in the id_token (``sub`` claim) — we prefer it over email so
    # users who change their primary Google email still match the same row.
    google_sub = db.Column(db.String(64), unique=True, nullable=True, index=True)
    google_email = db.Column(db.String(255), nullable=True)
    # 'password' for accounts created via /auth/register, 'google' for
    # accounts that were first seen via /auth/google. Hybrid users (existing
    # password account that later linked Google) keep their original value
    # so the UI can still show "you have a password set".
    auth_provider = db.Column(db.String(20), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def set_password(self, raw_password: str) -> None:
        # pbkdf2 is portable across Python builds (some macOS Pythons ship
        # without scrypt support in hashlib).
        self.password_hash = generate_password_hash(
            raw_password, method="pbkdf2:sha256"
        )

    def mark_passwordless(self) -> None:
        """Mark this account as having no local password (Google-only)."""
        self.password_hash = PASSWORDLESS_PLACEHOLDER

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash) and self.password_hash != PASSWORDLESS_PLACEHOLDER

    def check_password(self, raw_password: str) -> bool:
        if not self.has_password:
            return False
        return check_password_hash(self.password_hash, raw_password)

    def to_dict(self) -> dict:
        # Lazy import — avoids a circular ref since ProviderCredential
        # imports the same models package.
        from app.models.provider_credential import ProviderCredential

        configured = {
            row.provider
            for row in db.session.query(ProviderCredential.provider)
            .filter(ProviderCredential.user_id == self.id)
            .all()
        }
        # Back-compat: a user with the legacy ``openrouter_api_key_encrypted``
        # column still set (and not yet copied) should still report as
        # configured for openrouter.
        if self.openrouter_api_key_encrypted:
            configured.add("openrouter")
        return {
            "id": self.id,
            "email": self.email,
            # Legacy field — kept so old clients don't break.
            "has_openrouter_api_key": "openrouter" in configured,
            "providers": {
                "openrouter": "openrouter" in configured,
                "deepseek": "deepseek" in configured,
                "openai": "openai" in configured,
            },
            # R15: surface enough state for the frontend to decide whether
            # to show the "set a password" hint or "Google linked" badge.
            "auth_provider": self.auth_provider or "password",
            "has_password": self.has_password,
            "google_linked": bool(self.google_sub),
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
