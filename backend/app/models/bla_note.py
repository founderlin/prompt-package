"""Bla Note model — project-scoped, user-authored Markdown notes.

Bla Notes are the hand-written counterpart to :class:`Memory`:

* ``Memory`` rows are **auto-distilled** from chat transcripts by the
  wrap-up flow (``memory_service.summarize_conversation``).
* ``BlaNote`` rows are **manually created** by the user inside a
  project, for things they want to remember, reference, or attach to
  a future chat but don't want the LLM to auto-extract.

They share the same owner / project / tagged-content shape, which is
why the schema deliberately mirrors the :class:`Memory` layout. That
also makes them trivially composable with :class:`ContextPackSource`
(``source_type = 'note'`` + ``note_id`` — both already declared on the
source-row model).

Forward-compat hooks:

* ``tags`` is stored as a JSON array in a TEXT column so we don't need
  a junction table yet — callers read/write via
  :meth:`BlaNote.get_tags` / :meth:`BlaNote.set_tags`.
* :class:`BlaNoteAttachment` is declared but deliberately **not
  wired up to an upload route in this MVP**. The table exists so when
  the time comes we can reuse the attachment service's text-extraction
  pipeline without another schema change.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.extensions import db


TITLE_MAX = 200
CONTENT_MAX = 50_000
TAG_MAX = 40
TAGS_MAX_COUNT = 20


ATTACHMENT_STATUS_PENDING = "pending"
ATTACHMENT_STATUS_READY = "ready"
ATTACHMENT_STATUS_FAILED = "failed"

BLA_NOTE_ATTACHMENT_STATUSES = (
    ATTACHMENT_STATUS_PENDING,
    ATTACHMENT_STATUS_READY,
    ATTACHMENT_STATUS_FAILED,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class BlaNote(db.Model):
    """A hand-written Markdown note scoped to a single project."""

    __tablename__ = "bla_notes"

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

    title = db.Column(db.String(TITLE_MAX), nullable=False, default="Untitled note")
    # Markdown text. Large but bounded to keep a single note from
    # dominating the prompt budget when it's referenced in chat.
    content = db.Column(db.Text, nullable=False, default="")
    # JSON array of string tags. Stored as TEXT for SQLite portability,
    # same pattern as ``ContextPack.keywords``.
    tags = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    project = db.relationship(
        "Project", backref=db.backref("bla_notes", lazy="dynamic")
    )
    attachments = db.relationship(
        "BlaNoteAttachment",
        backref=db.backref("note", lazy="joined"),
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BlaNoteAttachment.id.asc()",
    )

    __table_args__ = (
        db.Index("ix_bla_notes_user_created", "user_id", "created_at"),
        db.Index("ix_bla_notes_project_created", "project_id", "created_at"),
    )

    # ---- Tag helpers ---------------------------------------------------

    def get_tags(self) -> list[str]:
        if not self.tags:
            return []
        try:
            data = json.loads(self.tags)
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out: list[str] = []
        for item in data:
            if isinstance(item, str):
                word = item.strip()
                if word:
                    out.append(word)
        return out

    def set_tags(self, raw) -> None:
        """Normalize + persist a list of tags.

        Accepts either a list of strings or a comma-separated string.
        De-duplicates case-insensitively while preserving the first
        occurrence's casing, trims whitespace, clamps length.
        """
        if raw is None or raw == "":
            self.tags = None
            return
        if isinstance(raw, str):
            raw = [part for part in raw.split(",")]
        if not isinstance(raw, (list, tuple)):
            self.tags = None
            return
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            word = item.strip()
            if not word:
                continue
            if len(word) > TAG_MAX:
                word = word[: TAG_MAX - 1].rstrip() + "…"
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(word)
            if len(cleaned) >= TAGS_MAX_COUNT:
                break
        self.tags = json.dumps(cleaned) if cleaned else None

    def to_dict(
        self,
        *,
        include_content: bool = True,
        content_preview: int | None = None,
        include_attachments: bool = False,
        include_project: bool = False,
    ) -> dict:
        content = self.content or ""
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "title": self.title,
            "tags": self.get_tags(),
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }
        if include_content:
            data["content"] = content
        if content_preview is not None:
            preview = content.strip()
            if len(preview) > content_preview:
                preview = preview[: content_preview - 1].rstrip() + "…"
            data["content_preview"] = preview
        if include_attachments:
            data["attachments"] = [
                a.to_dict() for a in (self.attachments or [])
            ]
        if include_project and self.project is not None:
            data["project"] = {"id": self.project.id, "name": self.project.name}
        return data


class BlaNoteAttachment(db.Model):
    """Optional attachment file bound to a :class:`BlaNote`.

    **MVP scope:** the table is created and the model is usable from
    Python, but there is **no upload endpoint yet**. This lets us
    reserve storage columns (`storage_path`, `extracted_text`,
    `status`) so when the upload flow is built it will slot in with a
    single service + route file, no schema change.

    Deliberately *not* sharing a table with :class:`Attachment` because
    that model requires a conversation id (NOT NULL) and we don't want
    a note-only attachment to force one.
    """

    __tablename__ = "bla_note_attachments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note_id = db.Column(
        db.Integer,
        db.ForeignKey("bla_notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Copied from the note at creation time so attachment cleanup / bulk
    # project deletion is fast without joining through bla_notes.
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(80), nullable=True)  # MIME type
    file_size = db.Column(db.Integer, nullable=True)  # bytes

    # Relative path under instance/uploads/notes/... where the raw
    # file lives. Nullable while status='pending'.
    storage_path = db.Column(db.String(512), nullable=True)
    extracted_text = db.Column(db.Text, nullable=True)

    # 'pending' → upload accepted, nothing extracted yet
    # 'ready'   → stored + (optionally) extracted
    # 'failed'  → processing failed; error in extracted_text or future field
    status = db.Column(
        db.String(16),
        nullable=False,
        default=ATTACHMENT_STATUS_PENDING,
    )

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
        db.Index("ix_bla_note_attachments_note", "note_id"),
        db.Index("ix_bla_note_attachments_user", "user_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "note_id": self.note_id,
            "project_id": self.project_id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "status": self.status,
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }


__all__ = [
    "ATTACHMENT_STATUS_FAILED",
    "ATTACHMENT_STATUS_PENDING",
    "ATTACHMENT_STATUS_READY",
    "BLA_NOTE_ATTACHMENT_STATUSES",
    "BlaNote",
    "BlaNoteAttachment",
    "CONTENT_MAX",
    "TAG_MAX",
    "TAGS_MAX_COUNT",
    "TITLE_MAX",
]
