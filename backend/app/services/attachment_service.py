"""Attachment lifecycle: disk storage, text extraction, garbage collection.

Design rules:

* Files live on the server under ``<instance>/uploads/<user_id>/<key>``.
  ``key`` is a URL-safe hex token, not the original filename, so
  uploads are opaque on disk and filename-collision-proof.
* Row is created *after* the bytes are safely on disk so we never have
  a DB row pointing at missing data. On failure we clean up.
* We bound size (10MB), count per conversation (8), and extracted text
  length (50K chars) so a pathological PDF can't blow up memory or
  inject a million-token prompt.
* PDF/TXT/MD text is pulled at upload time and cached on the row.
  Binary images (PNG/JPG/WEBP) skip extraction and are streamed back as
  data URLs when we build the multimodal payload.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models import Attachment, Conversation, Message, User
from app.models.attachment import KIND_IMAGE, KIND_PDF, KIND_TEXT

MAX_BYTES_PER_FILE = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS_PER_CONVERSATION = 8
MAX_EXTRACTED_CHARS = 50_000
# How long a detached attachment may linger before GC reaps it.
DETACHED_TTL_HOURS = 24

# MIME → (kind, allowed)
# Accept list is intentionally narrow — the UI advertises these, the
# backend enforces them.
_ALLOWED_MIME: dict[str, str] = {
    # Images
    "image/png": KIND_IMAGE,
    "image/jpeg": KIND_IMAGE,
    "image/jpg": KIND_IMAGE,
    "image/webp": KIND_IMAGE,
    "image/gif": KIND_IMAGE,
    # PDF
    "application/pdf": KIND_PDF,
    # Text-ish
    "text/plain": KIND_TEXT,
    "text/markdown": KIND_TEXT,
    "text/x-markdown": KIND_TEXT,
    "application/octet-stream": KIND_TEXT,  # some browsers send .md as octet-stream
}

# Fallback-by-extension when MIME is generic.
_EXT_TO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


class AttachmentError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class UploadResult:
    attachment: Attachment


# ---------- Helpers ----------------------------------------------------------


def _uploads_root() -> Path:
    instance = Path(current_app.instance_path)
    root = instance / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _user_dir(user_id: int) -> Path:
    p = _uploads_root() / str(user_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_mime(filename: str, client_mime: str | None) -> tuple[str, str]:
    """Return ``(mime, kind)`` or raise if type is unsupported."""
    mime = (client_mime or "").split(";")[0].strip().lower()
    # If browser sent a recognizable MIME, trust it.
    if mime in _ALLOWED_MIME:
        return mime, _ALLOWED_MIME[mime]

    # Otherwise fall back to extension.
    ext = Path(filename).suffix.lower()
    mapped = _EXT_TO_MIME.get(ext)
    if mapped and mapped in _ALLOWED_MIME:
        return mapped, _ALLOWED_MIME[mapped]

    raise AttachmentError(
        "unsupported_media_type",
        "File type not supported. Allowed: PDF, PNG, JPG, JPEG, WEBP, GIF, TXT, MD.",
        status=415,
    )


def _sanitize_filename(raw: str) -> str:
    name = (raw or "").strip().replace("\\", "/").split("/")[-1]
    if not name:
        name = "upload"
    # Keep it bounded; original preserved for display only, never used
    # on the filesystem.
    return name[:255]


def _new_storage_key() -> str:
    # 64 hex chars — collisions are astronomically unlikely and it's
    # URL-safe without needing base64 padding handling.
    return secrets.token_hex(32)


def _path_for(att: Attachment) -> Path:
    return _user_dir(att.user_id) / att.storage_key


def _delete_file_silently(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        current_app.logger.warning(
            "Failed to unlink attachment file %s", path
        )


def _extract_text(kind: str, data: bytes) -> tuple[str | None, bool]:
    """Return ``(text, truncated)`` for PDF / text; ``(None, False)`` for images."""
    if kind == KIND_TEXT:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # Latin-1 is a round-trip-safe last resort.
            text = data.decode("latin-1", errors="replace")
        truncated = False
        if len(text) > MAX_EXTRACTED_CHARS:
            text = text[:MAX_EXTRACTED_CHARS]
            truncated = True
        return text.strip(), truncated

    if kind == KIND_PDF:
        try:
            from pypdf import PdfReader  # local import: heavy module
        except ImportError as exc:  # pragma: no cover — dependency listed in requirements
            raise AttachmentError(
                "pdf_unsupported",
                "PDF support is not installed on the server.",
                status=500,
            ) from exc
        try:
            reader = PdfReader(BytesIO(data))
            parts: list[str] = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:  # pragma: no cover — broken PDF
                    parts.append("")
            text = "\n\n".join(p.strip() for p in parts if p and p.strip())
        except Exception as exc:
            raise AttachmentError(
                "pdf_parse_failed",
                "Could not read that PDF. Try another file.",
                status=422,
            ) from exc
        truncated = False
        if len(text) > MAX_EXTRACTED_CHARS:
            text = text[:MAX_EXTRACTED_CHARS]
            truncated = True
        return text.strip(), truncated

    return None, False


# ---------- Public API -------------------------------------------------------


def _conversation_for(user: User, conversation_id: int) -> Conversation:
    convo = db.session.get(Conversation, conversation_id)
    if convo is None or convo.user_id != user.id:
        raise AttachmentError("not_found", "Conversation not found.", status=404)
    return convo


def _count_live_attachments(conversation_id: int) -> int:
    return (
        db.session.query(Attachment.id)
        .filter(Attachment.conversation_id == conversation_id)
        .count()
    )


def upload(
    user: User,
    conversation_id: int,
    *,
    filename: str,
    mime_type: str | None,
    data: bytes,
) -> Attachment:
    convo = _conversation_for(user, conversation_id)

    if not data:
        raise AttachmentError("validation_error", "Uploaded file is empty.")
    if len(data) > MAX_BYTES_PER_FILE:
        raise AttachmentError(
            "file_too_large",
            f"File is {len(data)} bytes; limit is {MAX_BYTES_PER_FILE}.",
            status=413,
        )

    if _count_live_attachments(convo.id) >= MAX_ATTACHMENTS_PER_CONVERSATION:
        raise AttachmentError(
            "too_many_attachments",
            f"A conversation may have at most {MAX_ATTACHMENTS_PER_CONVERSATION} attachments.",
            status=409,
        )

    safe_name = _sanitize_filename(filename)
    mime, kind = _resolve_mime(safe_name, mime_type)

    # Extract text up-front; if extraction fails we abort before touching disk.
    extracted_text, truncated = _extract_text(kind, data)

    storage_key = _new_storage_key()
    target = _user_dir(user.id) / storage_key
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise AttachmentError(
            "storage_failed",
            "Could not store file on the server.",
            status=500,
        ) from exc

    att = Attachment(
        user_id=user.id,
        conversation_id=convo.id,
        message_id=None,
        filename=safe_name,
        storage_key=storage_key,
        mime_type=mime,
        size_bytes=len(data),
        kind=kind,
        extracted_text=extracted_text,
        extracted_truncated=truncated,
    )
    try:
        db.session.add(att)
        db.session.commit()
    except Exception:
        db.session.rollback()
        _delete_file_silently(target)
        raise

    return att


def get_for_user(user: User, attachment_id: int) -> Attachment:
    att = db.session.get(Attachment, attachment_id)
    if att is None or att.user_id != user.id:
        raise AttachmentError("not_found", "Attachment not found.", status=404)
    return att


def delete(user: User, attachment_id: int) -> None:
    att = get_for_user(user, attachment_id)
    if att.message_id is not None:
        raise AttachmentError(
            "already_sent",
            "This file is part of a saved message and can't be removed.",
            status=409,
        )
    path = _path_for(att)
    db.session.delete(att)
    db.session.commit()
    _delete_file_silently(path)


def list_for_conversation(
    user: User, conversation_id: int
) -> list[Attachment]:
    convo = _conversation_for(user, conversation_id)
    stmt = (
        select(Attachment)
        .where(Attachment.conversation_id == convo.id)
        .order_by(Attachment.id.asc())
    )
    return list(db.session.scalars(stmt).all())


def read_bytes(att: Attachment) -> bytes:
    path = _path_for(att)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AttachmentError(
            "missing_file",
            "The stored file could not be read.",
            status=410,
        ) from exc


def resolve_user_attachments(
    user: User, conversation_id: int, attachment_ids: Iterable[int]
) -> list[Attachment]:
    """Validate ``attachment_ids`` all belong to this user + conversation + are still detached."""
    ids = [int(i) for i in attachment_ids if str(i).strip()]
    if not ids:
        return []
    rows = (
        db.session.query(Attachment)
        .filter(Attachment.id.in_(ids))
        .all()
    )
    if len(rows) != len(set(ids)):
        raise AttachmentError(
            "not_found", "One or more attachments were not found.", status=404
        )
    for att in rows:
        if att.user_id != user.id:
            raise AttachmentError(
                "not_found", "Attachment not found.", status=404
            )
        if att.conversation_id != conversation_id:
            raise AttachmentError(
                "wrong_conversation",
                "Attachment belongs to another conversation.",
                status=409,
            )
        if att.message_id is not None:
            raise AttachmentError(
                "already_sent",
                "One of those files was already sent.",
                status=409,
            )
    # Sort to match input order for stable prompt ordering.
    by_id = {r.id: r for r in rows}
    return [by_id[i] for i in ids]


def attach_to_message(attachments: list[Attachment], message: Message) -> None:
    """Stamp ``message_id`` on each attachment so it becomes part of the message."""
    if not attachments:
        return
    for att in attachments:
        att.message_id = message.id
        db.session.add(att)
    db.session.commit()


def gc_stale_detached(*, hours: int | None = None) -> int:
    """Delete detached attachments older than ``DETACHED_TTL_HOURS``.

    Returns the number of rows removed. Called opportunistically; we
    don't rely on a scheduled job for MVP.
    """
    horizon = datetime.now(timezone.utc) - timedelta(
        hours=hours or DETACHED_TTL_HOURS
    )
    stale = (
        db.session.query(Attachment)
        .filter(
            Attachment.message_id.is_(None),
            Attachment.created_at < horizon,
        )
        .all()
    )
    count = 0
    for att in stale:
        path = _path_for(att)
        db.session.delete(att)
        _delete_file_silently(path)
        count += 1
    if count:
        db.session.commit()
    return count


__all__ = [
    "AttachmentError",
    "MAX_ATTACHMENTS_PER_CONVERSATION",
    "MAX_BYTES_PER_FILE",
    "MAX_EXTRACTED_CHARS",
    "UploadResult",
    "attach_to_message",
    "delete",
    "gc_stale_detached",
    "get_for_user",
    "list_for_conversation",
    "read_bytes",
    "resolve_user_attachments",
    "upload",
]
