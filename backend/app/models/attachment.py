"""Attachment model — uploaded files bound to a conversation.

An attachment goes through three lifecycle states:

1. **Detached** — just uploaded, not yet linked to a message. The
   frontend has its id and will send it alongside the next
   ``send_user_message`` call. Stale detached rows are garbage-collected
   periodically.
2. **Attached** — linked to a user Message (``message_id`` is set). The
   file is now part of the conversation record.
3. **Orphaned** — parent conversation/message was deleted. ORM cascade
   on Conversation → Message takes care of the DB row; the service
   layer deletes the file on disk in the same call path.

File bytes live on disk under
``<instance>/uploads/<user_id>/<storage_key>`` — we never shove
binary into SQLite. The DB row carries only metadata + extracted text
(bounded to 50K chars) for text-ish files.
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


# Buckets an attachment can fall into. Used to pick the right upstream
# representation when we build the multi-modal payload.
KIND_IMAGE = "image"
KIND_PDF = "pdf"
KIND_TEXT = "text"


class Attachment(db.Model):
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id = db.Column(
        db.Integer,
        db.ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Human-facing filename, as the user uploaded it. Length-capped.
    filename = db.Column(db.String(255), nullable=False)
    # Disk-safe opaque key used for the stored file's name. Never echoed
    # back to the client in URLs; served via authenticated endpoint.
    storage_key = db.Column(db.String(96), nullable=False, unique=True)
    mime_type = db.Column(db.String(120), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(16), nullable=False)  # image | pdf | text

    # Extracted plain text for PDF/MD/TXT. Bounded (~50K chars) to keep
    # prompt tokens finite; full bytes remain on disk.
    extracted_text = db.Column(db.Text, nullable=True)
    extracted_truncated = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    message = db.relationship(
        "Message",
        backref=db.backref(
            "attachments",
            lazy="selectin",
            cascade="all, delete-orphan",
            single_parent=True,
        ),
        foreign_keys=[message_id],
    )

    __table_args__ = (
        db.Index("ix_attachments_conv_created", "conversation_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "kind": self.kind,
            "has_text": bool(self.extracted_text),
            "text_truncated": bool(self.extracted_truncated),
            "created_at": _isoformat(self.created_at),
        }
