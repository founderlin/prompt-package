"""UserModelSelection — which LLM models a user has enabled for a provider.

A user can curate, per provider, an allow-list of models that should
appear in the chat picker. One row per (user, provider, model_id).
Labels are optional; when the model id matches one of our curated
constants we render the label from the frontend catalogue.
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


class UserModelSelection(db.Model):
    __tablename__ = "user_model_selections"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(40), nullable=False, index=True)
    model_id = db.Column(db.String(160), nullable=False)
    label = db.Column(db.String(160), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "provider", "model_id",
            name="uq_user_model_selections_user_provider_model",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "model_id": self.model_id,
            "label": self.label,
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }
