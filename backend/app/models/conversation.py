"""Conversation + Message models.

A Conversation is a single chat thread inside a Project. Messages are
ordered by ``created_at`` (and ``id`` as a stable tiebreaker).

We persist token usage per assistant message so future telemetry /
billing surfaces can lean on it without another OpenRouter round-trip.
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


class Conversation(db.Model):
    __tablename__ = "conversations"

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

    title = db.Column(db.String(200), nullable=True)
    model = db.Column(db.String(120), nullable=True)
    # R14: which API gateway runs this conversation's model.
    # NULL on legacy rows ⇒ treated as 'openrouter' for back-compat.
    provider = db.Column(db.String(40), nullable=True, index=True)
    last_message_at = db.Column(db.DateTime(timezone=True), nullable=True)

    summary = db.Column(db.Text, nullable=True)
    summarized_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # R13: optional Context Pack acting as a "Prompt Plus". When set, its
    # body is injected as the leading system message on every OpenRouter
    # call for this conversation. The pack itself is never copied into the
    # messages table — switching / clearing it does not rewrite history.
    context_pack_id = db.Column(
        db.Integer,
        db.ForeignKey("context_packs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    messages = db.relationship(
        "Message",
        backref="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id.asc()",
        lazy="dynamic",
    )

    project = db.relationship("Project", backref=db.backref("conversations", lazy="dynamic"))
    context_pack = db.relationship(
        "ContextPack",
        foreign_keys=[context_pack_id],
        # No backref — packs don't need to enumerate the conversations using them.
        lazy="joined",
    )

    __table_args__ = (
        db.Index(
            "ix_conversations_project_updated", "project_id", "updated_at"
        ),
    )

    def to_dict(
        self,
        *,
        include_messages: bool = False,
        include_message_count: bool = False,
        include_project: bool = False,
    ) -> dict:
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "title": self.title,
            "model": self.model,
            "provider": self.provider,
            "last_message_at": _isoformat(self.last_message_at),
            "summary": self.summary,
            "summarized_at": _isoformat(self.summarized_at),
            "context_pack_id": self.context_pack_id,
            "context_pack": (
                {
                    "id": self.context_pack.id,
                    "title": self.context_pack.title,
                    "project_id": self.context_pack.project_id,
                }
                if self.context_pack is not None
                else None
            ),
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }
        if include_messages:
            messages = list(self.messages)
            data["messages"] = [m.to_dict() for m in messages]
            data["message_count"] = len(messages)
        elif include_message_count:
            # ``messages`` is a dynamic relationship, so .count() runs a cheap COUNT(*).
            data["message_count"] = self.messages.count()
        if include_project and self.project is not None:
            data["project"] = {
                "id": self.project.id,
                "name": self.project.name,
            }
        return data


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role = db.Column(db.String(16), nullable=False)  # 'user' | 'assistant' | 'system'
    content = db.Column(db.Text, nullable=False)
    model = db.Column(db.String(120), nullable=True)
    # R14: which API gateway answered this turn (NULL on legacy rows).
    provider = db.Column(db.String(40), nullable=True)

    prompt_tokens = db.Column(db.Integer, nullable=True)
    completion_tokens = db.Column(db.Integer, nullable=True)
    total_tokens = db.Column(db.Integer, nullable=True)

    # R-BLA-NOTE-CHAT: JSON-encoded metadata about any "context items"
    # (bla notes now; packs / attachments / external snippets later)
    # that the user attached to *this* message at send time.
    #
    # Shape: {"context_items": [{"type": "bla_note", "id": 42,
    #                            "title": "Product ideas"}]}
    #
    # Stored as TEXT for SQLite portability. Column name is
    # ``context_metadata`` because SQLAlchemy reserves ``Model.metadata``.
    context_metadata = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    def get_context_metadata(self) -> dict:
        """Parse the JSON blob — tolerates NULL / junk."""
        if not self.context_metadata:
            return {}
        try:
            data = json.loads(self.context_metadata)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def set_context_metadata(self, payload: dict | None) -> None:
        if not payload or not isinstance(payload, dict):
            self.context_metadata = None
            return
        try:
            self.context_metadata = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            self.context_metadata = None

    def to_dict(self, *, include_attachments: bool = True) -> dict:
        data = {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "context_metadata": self.get_context_metadata() or None,
            "created_at": _isoformat(self.created_at),
        }
        if include_attachments:
            # ``attachments`` is a selectin-loaded relationship defined on
            # the Attachment model. It's empty for assistant messages.
            data["attachments"] = [
                a.to_dict() for a in (self.attachments or [])
            ]
        return data
