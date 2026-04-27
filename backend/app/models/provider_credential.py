"""ProviderCredential — per-(user, provider) encrypted API key + cached key info.

R14 introduces multi-provider support (OpenRouter / DeepSeek / OpenAI).
Each user can stash one API key per provider. The key is encrypted at
rest (Fernet, see ``app.utils.crypto``); we never echo plaintext back to
the client.

On first boot post-R14, ``_apply_lightweight_migrations`` copies any
existing ``users.openrouter_api_key_encrypted`` into a row here with
``provider='openrouter'``; the column on ``users`` becomes a legacy
mirror that's no longer written to.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class ProviderCredential(db.Model):
    __tablename__ = "provider_credentials"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(40), nullable=False, index=True)

    encrypted_api_key = db.Column(db.Text, nullable=False)
    # Optional metadata returned by the provider's verify endpoint.
    label = db.Column(db.String(160), nullable=True)
    usage = db.Column(db.Float, nullable=True)
    limit = db.Column(db.Float, nullable=True)
    limit_remaining = db.Column(db.Float, nullable=True)
    is_free_tier = db.Column(db.Boolean, nullable=True)
    last_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "provider", name="uq_provider_credentials_user_provider"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "usage": self.usage,
            "limit": self.limit,
            "limit_remaining": self.limit_remaining,
            "is_free_tier": self.is_free_tier,
            "last_verified_at": _isoformat(self.last_verified_at),
            "updated_at": _isoformat(self.updated_at),
        }
