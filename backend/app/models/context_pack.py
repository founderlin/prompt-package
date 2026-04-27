"""ContextPack model — a copy-pasteable bundle of project memory.

R11 produces these on demand from a project's existing memories. The
generated body is plain Markdown the user can drop into a fresh AI
session to bootstrap context. We keep the source memory ids so the
view layer can link back to the underlying memories, plus a snapshot
of the prompt instructions and token usage for auditing.
"""

from __future__ import annotations

import json
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


class ContextPack(db.Model):
    __tablename__ = "context_packs"

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

    title = db.Column(db.String(160), nullable=False, default="Context Pack")
    body = db.Column(db.Text, nullable=False, default="")
    model = db.Column(db.String(120), nullable=True)
    instructions = db.Column(db.Text, nullable=True)
    # Stored as a JSON array of memory ids that were fed into generation.
    source_memory_ids = db.Column(db.Text, nullable=True)
    memory_count = db.Column(db.Integer, nullable=False, default=0)

    prompt_tokens = db.Column(db.Integer, nullable=True)
    completion_tokens = db.Column(db.Integer, nullable=True)
    total_tokens = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    project = db.relationship("Project", backref=db.backref("context_packs", lazy="dynamic"))

    __table_args__ = (
        db.Index("ix_context_packs_project_created", "project_id", "created_at"),
        db.Index("ix_context_packs_user_created", "user_id", "created_at"),
    )

    def get_source_memory_ids(self) -> list[int]:
        if not self.source_memory_ids:
            return []
        try:
            data = json.loads(self.source_memory_ids)
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out: list[int] = []
        for item in data:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out

    def set_source_memory_ids(self, ids: list[int]) -> None:
        self.source_memory_ids = json.dumps([int(i) for i in ids])

    def to_dict(
        self,
        *,
        include_body: bool = True,
        include_project: bool = False,
        body_preview: int | None = None,
    ) -> dict:
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "title": self.title,
            "model": self.model,
            "instructions": self.instructions,
            "source_memory_ids": self.get_source_memory_ids(),
            "memory_count": self.memory_count or 0,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }
        body = self.body or ""
        if include_body:
            data["body"] = body
        if body_preview is not None:
            preview = body.strip()
            if len(preview) > body_preview:
                preview = preview[: body_preview - 1].rstrip() + "…"
            data["body_preview"] = preview
        if include_project and self.project is not None:
            data["project"] = {
                "id": self.project.id,
                "name": self.project.name,
            }
        return data
