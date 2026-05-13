"""RoutineWrapConfig — Phase 5 per-project routine wrap settings.

One row per (user, project). The row is created lazily on first
write; the GET endpoint returns the global defaults when no row
exists yet so the frontend doesn't have to special-case "never
configured".

All enum-valued columns are stored as plain strings to keep the
table SQLite-friendly (avoids DB-level enum types that don't ALTER
cleanly). Validation happens in the service layer against the
:mod:`wrap_memory.routine` enums.
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


class RoutineWrapConfig(db.Model):
    __tablename__ = "routine_wrap_configs"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    enabled = db.Column(db.Boolean, nullable=False, default=False)
    frequency = db.Column(db.String(16), nullable=False, default="weekly")
    day_of_week = db.Column(db.String(12), nullable=False, default="friday")
    # ``model`` overlaps with the chat model column name elsewhere; we
    # call it ``model_choice`` here to disambiguate (and to make the
    # ``use-global-default`` semantics obvious from the field name).
    model_choice = db.Column(
        db.String(40), nullable=False, default="use-global-default"
    )
    scope = db.Column(db.String(24), nullable=False, default="since-last-wrap")

    # Phase 5 invariants — persisted to make a future opt-out trivial
    # without a schema migration, but always written via
    # ``routine.coerce_invariants`` so they can't drift in practice.
    review_required = db.Column(db.Boolean, nullable=False, default=True)
    auto_save = db.Column(db.Boolean, nullable=False, default=False)

    last_run_at = db.Column(db.DateTime(timezone=True), nullable=True)
    dismissed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "project_id",
            name="uq_routine_wrap_configs_user_project",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "enabled": bool(self.enabled),
            "frequency": self.frequency,
            "dayOfWeek": self.day_of_week,
            "model": self.model_choice,
            "scope": self.scope,
            "reviewRequired": bool(self.review_required),
            "autoSave": bool(self.auto_save),
            "lastRunAt": _isoformat(self.last_run_at),
            "dismissedAt": _isoformat(self.dismissed_at),
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }
