"""ContextPack model — the system's core context asset.

Originally produced by R11 as a copy-pasteable Markdown bundle of
project memories, and extended by R-WRAPUP with summary / keywords /
structured source tracking so conversation-level and project-level
Wrap Up flows could both target the same table.

R-PACK-CORE upgrades this model into a first-class asset with
extensibility fields the roadmap calls out explicitly:

* ``structured_content`` — JSON blob; a structured alternative / complement
  to the free-form Markdown ``body`` (sections, quotes, code blocks, etc.).
* ``visibility``         — access scope (``private`` | ``team`` | ``public``).
  MVP only accepts ``private``; the column exists so multi-user sharing
  can ship without another migration.
* ``graph_data``         — JSON blob for a future graph representation
  (nodes / edges extracted from the pack's sources).
* ``vector_index_id``    — opaque id of an external vector-store doc.
* ``version``            — monotonically increasing integer. Bumped on
  every content edit (``PATCH`` that touches body / structured_content /
  summary / keywords); lets the UI show history and the backend detect
  lost updates.
* ``parent_pack_id``     — self-FK, nullable. Supports derivation
  (branching a pack, evolving it, etc.).
* ``usage_count``        — incremented every time the pack is attached
  to a conversation or explicitly "used".
* ``last_used_at``       — timestamp of the last usage bump.

A :class:`ContextPackSource` continues to hold provenance rows (one per
project / conversation / message / note / attachment). Its schema now
carries explicit FK columns (``project_id`` / ``conversation_id`` /
``note_id`` / ``attachment_id``) in addition to the legacy generic
``source_id`` so callers can JOIN cleanly and the DB can cascade on
parent deletes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.extensions import db

# Source types for ContextPack.source_type / ContextPackSource.source_type.
# The model column is intentionally a plain VARCHAR (not a DB enum) so we
# can extend this without another migration.
SOURCE_TYPE_PROJECT = "project"
SOURCE_TYPE_CONVERSATION = "conversation"
SOURCE_TYPE_MESSAGE = "message"
SOURCE_TYPE_NOTE = "note"
SOURCE_TYPE_ATTACHMENT = "attachment"
SOURCE_TYPE_MIXED = "mixed"

# What a ContextPack's top-level ``source_type`` may be (coarse scope).
PACK_SOURCE_TYPES = (
    SOURCE_TYPE_PROJECT,
    SOURCE_TYPE_CONVERSATION,
    SOURCE_TYPE_NOTE,
    SOURCE_TYPE_ATTACHMENT,
    SOURCE_TYPE_MIXED,
)
# What ``ContextPackSource.source_type`` rows may be (granular provenance).
SOURCE_RECORD_TYPES = (
    SOURCE_TYPE_PROJECT,
    SOURCE_TYPE_CONVERSATION,
    SOURCE_TYPE_MESSAGE,
    SOURCE_TYPE_NOTE,
    SOURCE_TYPE_ATTACHMENT,
)

# Visibility enum. MVP accepts ``private`` only; the schema supports the
# others so multi-user sharing is a feature flip, not a migration.
VISIBILITY_PRIVATE = "private"
VISIBILITY_TEAM = "team"
VISIBILITY_PUBLIC = "public"
VISIBILITIES = (VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _loads_json(raw: str | None):
    """Parse a JSON text column and tolerate junk / NULL.

    Used by structured_content / graph_data / source_metadata so a row
    with legacy garbage never explodes a serialization call.
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _dumps_json(value) -> str | None:
    """Serialize a Python object for a JSON text column.

    ``None`` and empty containers round-trip to NULL so we never store
    meaningless ``"{}"`` / ``"[]"`` rows.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)) and len(value) == 0:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


class ContextPack(db.Model):
    __tablename__ = "context_packs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # R-PACK-CORE: project_id is now nullable so packs can live without a
    # project (e.g. note-only / attachment-only / cross-project 'mixed').
    # The lightweight-migrations step in app/__init__.py performs a SQLite
    # table rebuild to relax the old NOT NULL constraint on existing DBs.
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Nullable quick link to the originating conversation when the pack is
    # conversation-scoped. Cleared via SET NULL if the conversation is
    # deleted — we keep the pack because its body is self-contained.
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ---- Core content -------------------------------------------------
    title = db.Column(db.String(160), nullable=False, default="Context Pack")
    # Human-friendly description (optional, 1-2 sentences). Distinct from
    # ``summary`` (machine-generated brief) and ``body`` (Markdown body).
    description = db.Column(db.Text, nullable=True)
    body = db.Column(db.Text, nullable=False, default="")
    # Short structured summary of the pack (<= ~1000 chars). Populated by
    # wrap-up; for manually-created packs it may be empty.
    summary = db.Column(db.Text, nullable=True)
    # JSON array of string keywords. Stored as TEXT for SQLite portability.
    keywords = db.Column(db.Text, nullable=True)
    # R-PACK-CORE: structured alternative / complement to the Markdown
    # body. JSON object (sections, entities, quotes, ...). Opaque to the
    # DB; callers own the schema. Stored as TEXT for SQLite portability.
    structured_content = db.Column(db.Text, nullable=True)
    # 'project' | 'conversation' | 'note' | 'attachment' | 'mixed'.
    # NULL on legacy packs ⇒ treated as 'project'.
    source_type = db.Column(db.String(20), nullable=True, index=True)

    # ---- Extensibility hooks (R-PACK-CORE) ----------------------------
    # Access scope; only ``private`` is enforced in MVP logic.
    visibility = db.Column(
        db.String(16), nullable=False, default=VISIBILITY_PRIVATE, index=True
    )
    # JSON blob reserved for graph representations (nodes / edges) we
    # extract from the sources. Opaque to the DB.
    graph_data = db.Column(db.Text, nullable=True)
    # Opaque id of an external vector-store document. The embedding store
    # itself lives elsewhere (Pinecone / pgvector / Weaviate / ...).
    vector_index_id = db.Column(db.String(120), nullable=True, index=True)
    # Monotonically increasing integer. Starts at 1; PATCH bumps it when
    # any content field changes.
    version = db.Column(db.Integer, nullable=False, default=1)
    # Self-FK for derivation (branch / fork / evolve). Nullable.
    parent_pack_id = db.Column(
        db.Integer,
        db.ForeignKey("context_packs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    usage_count = db.Column(db.Integer, nullable=False, default=0)
    last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # ---- Generation audit (kept from R11/R-WRAPUP) --------------------
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
    # Deliberately no backref on Conversation — a conversation may spawn
    # many packs over time and we don't want to joined-load them.
    conversation = db.relationship(
        "Conversation",
        foreign_keys=[conversation_id],
        lazy="joined",
    )
    # Self-ref (parent). Use remote_side to disambiguate on the FK column.
    parent = db.relationship(
        "ContextPack",
        remote_side=[id],
        foreign_keys=[parent_pack_id],
        lazy="joined",
        post_update=True,
    )
    sources = db.relationship(
        "ContextPackSource",
        backref=db.backref("pack", lazy="joined"),
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ContextPackSource.id.asc()",
    )

    __table_args__ = (
        db.Index("ix_context_packs_project_created", "project_id", "created_at"),
        db.Index("ix_context_packs_user_created", "user_id", "created_at"),
        db.Index("ix_context_packs_user_visibility", "user_id", "visibility"),
    )

    # ------------------------------------------------------------------
    # keyword helpers — stored as JSON string on ``keywords`` column.

    def get_keywords(self) -> list[str]:
        if not self.keywords:
            return []
        try:
            data = json.loads(self.keywords)
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

    def set_keywords(self, words) -> None:
        if not words:
            self.keywords = None
            return
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in words:
            if not isinstance(item, str):
                continue
            word = item.strip()
            if not word:
                continue
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(word)
        self.keywords = json.dumps(cleaned) if cleaned else None

    # ---- structured_content / graph_data JSON helpers -----------------

    def get_structured_content(self) -> dict | list | None:
        return _loads_json(self.structured_content)

    def set_structured_content(self, payload) -> None:
        self.structured_content = _dumps_json(payload)

    def get_graph_data(self) -> dict | list | None:
        return _loads_json(self.graph_data)

    def set_graph_data(self, payload) -> None:
        self.graph_data = _dumps_json(payload)

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
        include_structured_content: bool = True,
        include_graph_data: bool = False,
        include_project: bool = False,
        include_sources: bool = False,
        body_preview: int | None = None,
    ) -> dict:
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "title": self.title,
            "description": self.description,
            "summary": self.summary,
            "keywords": self.get_keywords(),
            "source_type": self.source_type or "project",
            # Extensibility fields (always present so clients can rely on
            # their shape; body/structured_content stay opt-in because
            # they can be large).
            "visibility": self.visibility or VISIBILITY_PRIVATE,
            "vector_index_id": self.vector_index_id,
            "version": self.version or 1,
            "parent_pack_id": self.parent_pack_id,
            "usage_count": self.usage_count or 0,
            "last_used_at": _isoformat(self.last_used_at),
            # Generation audit.
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
        if include_structured_content:
            data["structured_content"] = self.get_structured_content()
        if include_graph_data:
            data["graph_data"] = self.get_graph_data()
        if include_project and self.project is not None:
            data["project"] = {
                "id": self.project.id,
                "name": self.project.name,
            }
        if include_sources:
            data["sources"] = [s.to_dict() for s in (self.sources or [])]
        return data


class ContextPackSource(db.Model):
    """Provenance row for a ContextPack.

    One ContextPack can have many source rows — at minimum one per
    underlying conversation/project/note/attachment, plus (optionally,
    when the caller asks for ``include_raw_references``) one per message
    actually included in the summary.

    ``source_type`` is the canonical discriminator:

    - ``project``      → ``project_id`` populated; also mirrored in
      ``source_id`` for back-compat.
    - ``conversation`` → ``conversation_id`` populated.
    - ``message``      → ``source_id`` holds the message id; owning
      conversation copied into ``conversation_id`` for join convenience.
    - ``note``         → ``note_id`` populated. (Notes are a roadmap
      concept; the column exists now so the migration doesn't have to
      be done twice.)
    - ``attachment``   → ``attachment_id`` populated.

    R-PACK-CORE: each row also snapshots a human-friendly ``source_title``
    (e.g. the conversation title at wrap-up time, the file name, etc.)
    so the UI can render the source list without cross-table joins, and
    the label survives even if the original source is later deleted.
    """

    __tablename__ = "context_pack_sources"

    id = db.Column(db.Integer, primary_key=True)
    context_pack_id = db.Column(
        db.Integer,
        db.ForeignKey("context_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = db.Column(db.String(20), nullable=False)
    # Generic source-id kept for back-compat + for source_types that
    # don't have a dedicated FK column yet (e.g. ``message``, ``external``).
    # For types with a dedicated FK, we also populate this field so a
    # single index can serve both.
    source_id = db.Column(db.Integer, nullable=True)

    # ---- Explicit typed FKs (R-PACK-CORE) -----------------------------
    # Populated based on source_type. Nullable; exactly one of these is
    # expected to be non-null for rows with a known source_type.
    # ON DELETE SET NULL so the source row survives the parent's deletion
    # (the pack is self-contained; losing a source shouldn't delete the
    # provenance snapshot, just orphan the FK).
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Notes don't exist as a model yet; we keep this as a plain INTEGER
    # (no FK constraint) so the schema is ready when the Note model lands.
    note_id = db.Column(db.Integer, nullable=True, index=True)
    attachment_id = db.Column(
        db.Integer,
        db.ForeignKey("attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Human-friendly label for the source at the time the pack was
    # generated. Independent of the live source (which may be deleted
    # or renamed later). <= 240 chars to stay cheap to serialize.
    source_title = db.Column(db.String(240), nullable=True)

    # Free-form metadata — JSON object. Column name is
    # ``source_metadata`` (not ``metadata``) because SQLAlchemy reserves
    # ``Model.metadata`` on the declarative base.
    source_metadata = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        db.Index(
            "ix_context_pack_sources_pack_type",
            "context_pack_id",
            "source_type",
        ),
        db.Index(
            "ix_context_pack_sources_type_source",
            "source_type",
            "source_id",
        ),
    )

    def get_metadata(self) -> dict:
        data = _loads_json(self.source_metadata)
        return data if isinstance(data, dict) else {}

    def set_metadata(self, payload: dict | None) -> None:
        if not payload or not isinstance(payload, dict):
            self.source_metadata = None
            return
        self.source_metadata = _dumps_json(payload)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "context_pack_id": self.context_pack_id,
            "source_type": self.source_type,
            # ``source_id`` is the generic discriminator; for typed rows
            # it mirrors the typed FK so callers that only read
            # source_id still work. Prefer the typed field when you know
            # the type (e.g. ``project_id`` for project rows).
            "source_id": self.source_id,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "note_id": self.note_id,
            "attachment_id": self.attachment_id,
            "source_title": self.source_title,
            "metadata": self.get_metadata(),
            "created_at": _isoformat(self.created_at),
        }


# Wrap Up job lifecycle. The sequence is linear; ``failed`` is terminal
# from any pre-completed state. ``completed`` is terminal on success.
JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"

JOB_STAGE_PREPARING = "preparing"
JOB_STAGE_COLLECTING = "collecting_messages"
JOB_STAGE_ANALYZING = "analyzing_content"
JOB_STAGE_SUMMARIZING = "generating_summary"
JOB_STAGE_CREATING = "creating_context_pack"
JOB_STAGE_COMPLETED = "completed"
JOB_STAGE_FAILED = "failed"

JOB_STAGES_ORDER = (
    JOB_STAGE_PREPARING,
    JOB_STAGE_COLLECTING,
    JOB_STAGE_ANALYZING,
    JOB_STAGE_SUMMARIZING,
    JOB_STAGE_CREATING,
    JOB_STAGE_COMPLETED,
)


class ContextPackJob(db.Model):
    """Wrap-up job record.

    MVP runs wrap-up synchronously in the request thread, so by the
    time the client reads this row back it is almost always already
    ``completed``/``failed``. The row still exists so:

    1. The frontend has a stable progress API to poll.
    2. Future iterations can flip the executor to a queue worker
       without touching the API shape.
    3. Errors are audit-logged regardless of whether the HTTP response
       reached the client.
    """

    __tablename__ = "context_pack_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Job's target scope. For conversation wrap-up, project_id is the
    # conversation's owning project and conversation_id is set.
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope = db.Column(db.String(20), nullable=False)  # 'conversation' | 'project'

    status = db.Column(
        db.String(20), nullable=False, default=JOB_STATUS_PENDING
    )
    stage = db.Column(db.String(40), nullable=False, default=JOB_STAGE_PREPARING)
    progress = db.Column(db.Integer, nullable=False, default=0)  # 0..100

    context_pack_id = db.Column(
        db.Integer,
        db.ForeignKey("context_packs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_code = db.Column(db.String(60), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    # JSON-encoded request params (title/goal/options) for debugging.
    params = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    context_pack = db.relationship(
        "ContextPack",
        foreign_keys=[context_pack_id],
        lazy="joined",
    )

    def get_params(self) -> dict:
        if not self.params:
            return {}
        try:
            data = json.loads(self.params)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def set_params(self, payload: dict | None) -> None:
        if not payload:
            self.params = None
            return
        try:
            self.params = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            self.params = None

    def to_dict(self, *, include_pack: bool = False) -> dict:
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "scope": self.scope,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "context_pack_id": self.context_pack_id,
            "error": (
                {
                    "code": self.error_code,
                    "message": self.error_message,
                }
                if self.error_code or self.error_message
                else None
            ),
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
            "completed_at": _isoformat(self.completed_at),
        }
        if include_pack and self.context_pack is not None:
            data["context_pack"] = self.context_pack.to_dict(
                include_body=False,
                include_project=True,
                body_preview=240,
            )
        return data
