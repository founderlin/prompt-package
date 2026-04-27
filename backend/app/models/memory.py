"""Memory model — distilled, reusable facts from a conversation.

R9 produces these as a side effect of "wrapping up" a conversation:
the model is asked to read the transcript and emit a JSON document with
a 1-2 sentence summary plus a flat list of memories. Each memory is one
of a small fixed set of kinds so we can render them grouped on the
project page (Decisions / Facts / Todos / Open questions).
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


# Keep this list short and stable — the prompt depends on it.
KINDS = ("fact", "decision", "todo", "question")


class Memory(db.Model):
    __tablename__ = "memories"

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
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    kind = db.Column(db.String(16), nullable=False, default="fact")
    content = db.Column(db.Text, nullable=False)
    source_excerpt = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    project = db.relationship("Project", backref=db.backref("memories", lazy="dynamic"))
    conversation = db.relationship(
        "Conversation", backref=db.backref("memories", lazy="dynamic")
    )

    __table_args__ = (
        db.Index("ix_memories_project_kind", "project_id", "kind"),
        db.Index("ix_memories_conversation_created", "conversation_id", "created_at"),
    )

    def to_dict(self, *, include_conversation: bool = False) -> dict:
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "kind": self.kind,
            "content": self.content,
            "source_excerpt": self.source_excerpt,
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }
        if include_conversation and self.conversation is not None:
            data["conversation"] = {
                "id": self.conversation.id,
                "title": self.conversation.title,
            }
        return data
