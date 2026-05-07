"""Bla Note domain service.

CRUD helpers for :class:`~app.models.BlaNote` with consistent ownership
enforcement. Anything not owned by the passed-in ``user`` raises a 404
so we don't leak existence — same pattern as the rest of the codebase
(``ChatError``, ``MemoryError``, ``ContextPackError``).

This module also contains :func:`resolve_notes_for_user` — used by the
chat send path to validate a list of note ids the user attached to a
message as "context items".
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import or_, select

from app.extensions import db
from app.models import BlaNote, Project, User
from app.models.bla_note import CONTENT_MAX, TITLE_MAX
from app.services.project_service import (
    ProjectError,
    get_for_user as get_project_for_user,
)


MAX_LIST_LIMIT = 200


class BlaNoteError(Exception):
    """Predictable, user-facing Bla Note failures."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Input normalization


def _normalize_title(raw) -> str:
    if raw is None:
        raise BlaNoteError("validation_error", "Title is required.")
    if not isinstance(raw, str):
        raise BlaNoteError("validation_error", "Title must be a string.")
    cleaned = raw.strip()
    if not cleaned:
        raise BlaNoteError("validation_error", "Title is required.")
    if len(cleaned) > TITLE_MAX:
        raise BlaNoteError(
            "validation_error",
            f"Title must be at most {TITLE_MAX} characters.",
        )
    return cleaned


def _normalize_content(raw) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise BlaNoteError("validation_error", "Content must be a string.")
    if len(raw) > CONTENT_MAX:
        raise BlaNoteError(
            "validation_error",
            f"Content must be at most {CONTENT_MAX} characters.",
        )
    return raw


def _normalize_tags_input(raw):
    """Accept list[str] or comma-separated str; reject others.

    Actual clamping / dedupe lives on :meth:`BlaNote.set_tags`; we only
    guard the *shape* here.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if not isinstance(item, str):
                raise BlaNoteError(
                    "validation_error",
                    "tags must contain strings only.",
                )
        return list(raw)
    raise BlaNoteError("validation_error", "tags must be a list of strings.")


# ---------------------------------------------------------------------------
# CRUD


def create_for_project(
    user: User,
    project_id: int,
    *,
    title,
    content=None,
    tags=None,
) -> BlaNote:
    try:
        project = get_project_for_user(user, project_id)
    except ProjectError as err:
        raise BlaNoteError(err.code, err.message, status=err.status) from err

    cleaned_title = _normalize_title(title)
    cleaned_content = _normalize_content(content)
    cleaned_tags = _normalize_tags_input(tags)

    note = BlaNote(
        user_id=user.id,
        project_id=project.id,
        title=cleaned_title,
        content=cleaned_content,
    )
    if cleaned_tags is not None:
        note.set_tags(cleaned_tags)

    db.session.add(note)
    db.session.commit()
    db.session.refresh(note)
    return note


def get_for_user(user: User, note_id: int) -> BlaNote:
    note = db.session.get(BlaNote, note_id)
    if note is None or note.user_id != user.id:
        raise BlaNoteError("not_found", "Bla Note not found.", status=404)
    return note


def list_for_project(
    user: User,
    project_id: int,
    *,
    keyword: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[BlaNote], int]:
    """List notes in a project with optional keyword / tag filters.

    Returns ``(rows, total)``. ``total`` reflects the count that
    matches the filter (not the user's grand total).
    """
    try:
        project = get_project_for_user(user, project_id)
    except ProjectError as err:
        raise BlaNoteError(err.code, err.message, status=err.status) from err

    limit = _clamp_limit(limit)
    offset = max(0, int(offset or 0))

    stmt = select(BlaNote).where(
        BlaNote.user_id == user.id,
        BlaNote.project_id == project.id,
    )
    count_stmt = select(db.func.count(BlaNote.id)).where(
        BlaNote.user_id == user.id,
        BlaNote.project_id == project.id,
    )

    if keyword:
        needle = _normalize_keyword(keyword)
        if needle:
            like = f"%{needle}%"
            clause = or_(
                BlaNote.title.ilike(like),
                BlaNote.content.ilike(like),
                BlaNote.tags.ilike(like),
            )
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)

    if tag:
        # tags is a JSON array serialized as TEXT, so a LIKE on a
        # quoted token is a decent approximation without FTS.
        cleaned = _normalize_keyword(tag)
        if cleaned:
            like = f'%"{cleaned}"%'
            stmt = stmt.where(BlaNote.tags.ilike(like))
            count_stmt = count_stmt.where(BlaNote.tags.ilike(like))

    stmt = (
        stmt.order_by(BlaNote.updated_at.desc(), BlaNote.id.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = list(db.session.scalars(stmt).all())
    total = int(db.session.scalar(count_stmt) or 0)
    return rows, total


def update_for_user(
    user: User,
    note_id: int,
    *,
    patch: dict | None = None,
) -> BlaNote:
    """Patch a note. Absent keys are left untouched."""
    note = get_for_user(user, note_id)

    if patch is None or not isinstance(patch, dict):
        raise BlaNoteError("validation_error", "Update payload must be an object.")
    if not patch:
        # Nothing to change — return the note unchanged (don't bump updated_at).
        return note

    if "title" in patch:
        note.title = _normalize_title(patch["title"])

    if "content" in patch:
        note.content = _normalize_content(patch["content"])

    if "tags" in patch:
        cleaned_tags = _normalize_tags_input(patch["tags"])
        note.set_tags(cleaned_tags)

    db.session.add(note)
    db.session.commit()
    db.session.refresh(note)
    return note


def delete_for_user(user: User, note_id: int) -> None:
    note = get_for_user(user, note_id)
    db.session.delete(note)
    db.session.commit()


def delete_all_for_project(project_id: int) -> None:
    """Helper for ``project_service.delete_for_user`` cascade cleanup.

    Uses a bulk DELETE so we don't round-trip per row. The bla_notes FK
    is already ON DELETE CASCADE at the DB level, but SQLite doesn't
    enforce that by default — we clean up manually for parity with how
    the project service clears memories / context_packs.
    """
    db.session.query(BlaNote).filter(BlaNote.project_id == project_id).delete(
        synchronize_session=False
    )


# ---------------------------------------------------------------------------
# Helpers used by chat context-items integration


def resolve_notes_for_user(
    user: User,
    project_id: int,
    note_ids: Iterable[int],
) -> list[BlaNote]:
    """Fetch a batch of notes by id, enforcing ownership + project scope.

    Used by :func:`app.services.chat_service.send_user_message` when
    the client passes ``context_items`` of type ``bla_note``. The
    returned list preserves the caller's order (so a "first attached
    first" render order in the prompt is predictable) and raises on
    any id that doesn't belong to the user *and* this project.
    """
    requested = []
    seen: set[int] = set()
    for raw in note_ids:
        try:
            nid = int(raw)
        except (TypeError, ValueError):
            raise BlaNoteError(
                "validation_error",
                "contextItems note ids must be integers.",
            )
        if nid in seen:
            continue
        seen.add(nid)
        requested.append(nid)

    if not requested:
        return []

    rows = db.session.scalars(
        select(BlaNote).where(
            BlaNote.id.in_(requested),
            BlaNote.user_id == user.id,
            BlaNote.project_id == project_id,
        )
    ).all()
    by_id = {n.id: n for n in rows}

    missing = [nid for nid in requested if nid not in by_id]
    if missing:
        raise BlaNoteError(
            "not_found",
            f"Bla Note {missing[0]} not found in this project.",
            status=404,
        )

    # Caller order.
    return [by_id[nid] for nid in requested]


def _normalize_keyword(raw) -> str:
    if not isinstance(raw, str):
        return ""
    cleaned = raw.strip()
    # Strip LIKE wildcards to keep the match predictable.
    cleaned = cleaned.replace("%", " ").replace("_", " ").strip()
    return cleaned[:160]


def _clamp_limit(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 50
    if value < 1:
        return 1
    if value > MAX_LIST_LIMIT:
        return MAX_LIST_LIMIT
    return value


__all__ = [
    "BlaNoteError",
    "MAX_LIST_LIMIT",
    "create_for_project",
    "delete_all_for_project",
    "delete_for_user",
    "get_for_user",
    "list_for_project",
    "resolve_notes_for_user",
    "update_for_user",
]
