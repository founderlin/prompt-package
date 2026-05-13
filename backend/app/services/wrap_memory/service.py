"""Phase 3 service layer — bridges HTTP routes ↔ pure wrap_memory pipeline.

Adds two pieces of glue on top of Phase 1/2:

1. :func:`build_request_from_conversation` — pulls a conversation +
   its messages from the DB, applies sensible defaults, and produces a
   :class:`WrapRequest` ready for :func:`create_wrap_draft`.

2. :func:`save_wrap_draft` — takes a (possibly user-edited) draft +
   metadata, renders Markdown via :func:`build_markdown_with_frontmatter`,
   writes it to ``<wraps_dir>/<project_id>/<filename>``, and returns
   a small descriptor the route can echo back.

This is the only module in the wrap_memory package that touches the
database and the filesystem. Everything below it (types, prompts,
parser, providers, draft_service) stays pure / unit-testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models import Conversation, Message, Project, User

from .draft_service import create_wrap_draft
from .filename import build_wrap_file_name
from .markdown_builder import WrapMarkdownMeta, build_markdown_with_frontmatter
from .providers import WrapProviderError
from .settings import DEFAULT_FILTERS, DEFAULT_MODEL
from .storage import ensure_wraps_dir
from .types import (
    FilterAction,
    WrapAnalysisResult,
    WrapFilters,
    WrapMessage,
    WrapMode,
    WrapModel,
    WrapRequest,
    WrapScope,
)


# ---------------------------------------------------------------------------
# Errors.


class WrapServiceError(Exception):
    """Predictable, user-facing service-layer failures.

    The route handler maps ``status`` directly onto the HTTP response.
    """

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Draft assembly from DB rows.


def _conversation_messages(convo: Conversation) -> list[WrapMessage]:
    """Pull user+assistant turns from a conversation, in chronological order."""
    rows = list(convo.messages.order_by(Message.id.asc()).all())
    out: list[WrapMessage] = []
    for m in rows:
        if m.role not in ("user", "assistant"):
            continue
        content = (m.content or "").strip()
        if not content:
            continue
        out.append(
            WrapMessage(
                role=m.role,
                content=content,
                message_id=m.id,
                created_at=getattr(m, "created_at", None),
            )
        )
    return out


def build_request_from_conversation(
    *,
    user: User,
    project: Project,
    conversation: Conversation,
    mode: WrapMode = WrapMode.QUICK,
    model: WrapModel = DEFAULT_MODEL,
    filters: WrapFilters | None = None,
    user_instruction: str | None = None,
) -> WrapRequest:
    """Compose a :class:`WrapRequest` from DB rows + sensible defaults.

    Raises :class:`WrapServiceError` when the conversation has no
    user/assistant turns yet — quick-wrapping an empty chat would just
    produce a placeholder and waste a model call.
    """
    if conversation.user_id != user.id:
        raise WrapServiceError(
            "not_found", "Conversation not found.", status=404
        )
    if conversation.project_id != project.id:
        raise WrapServiceError(
            "validation_error",
            "Conversation does not belong to this project.",
            status=400,
        )

    messages = _conversation_messages(conversation)
    if not messages:
        raise WrapServiceError(
            "transcript_too_short",
            "This conversation has no user/assistant messages to wrap yet.",
            status=400,
        )

    return WrapRequest(
        project_id=project.id,
        project_name=project.name or "Untitled project",
        mode=mode,
        model=model,
        scope=WrapScope.CONVERSATION,
        messages=messages,
        filters=filters or DEFAULT_FILTERS,
        user_instruction=(user_instruction or None),
    )


# ---------------------------------------------------------------------------
# Quick draft entry point used by routes.


@dataclass
class WrapDraftBundle:
    """Bundle returned to the route layer for a draft preview.

    The route serializes ``analysis`` into JSON and includes a separate
    ``suggested_filename`` + ``markdown`` so the frontend can show the
    save path without having to render the file itself.
    """

    request: WrapRequest
    analysis: WrapAnalysisResult
    markdown: str
    suggested_filename: str
    save_path_relative: str
    used_mock: bool

    def to_dict(self) -> dict:
        return {
            "analysis": self.analysis.to_dict(),
            "markdown": self.markdown,
            "suggestedFilename": self.suggested_filename,
            "savePathRelative": self.save_path_relative,
            "mode": self.request.mode.value,
            "model": self.request.model.value,
            "usedMock": self.used_mock,
        }


def wrap_draft(
    *,
    user: User,
    project: Project,
    conversation: Conversation,
    mode: WrapMode = WrapMode.QUICK,
    model: WrapModel = DEFAULT_MODEL,
    filters: WrapFilters | None = None,
    user_instruction: str | None = None,
    allow_network: bool = True,
) -> WrapDraftBundle:
    """Build a wrap preview bundle (the *unified* draft entry point).

    Both Quick and Advanced wrap flows route through here:

    * Quick (Phase 3): mode + defaults — see :func:`quick_wrap_draft`.
    * Advanced (Phase 4): caller supplies a custom model + filters +
      optional user instruction. Everything else is identical, so we
      keep a single code path for prompt assembly, provider routing,
      Markdown rendering, and ``used_mock`` detection.

    The LLM call routes through :func:`create_wrap_draft`, which
    transparently falls back to :class:`MockWrapProvider` when the
    user has no provider key on file. ``used_mock`` lets the UI hint
    that "real wraps need an API key".
    """
    request = build_request_from_conversation(
        user=user,
        project=project,
        conversation=conversation,
        mode=mode,
        model=model,
        filters=filters,
        user_instruction=user_instruction,
    )
    return wrap_draft_from_request(
        request, user=user, project=project, allow_network=allow_network
    )


def wrap_draft_from_request(
    request: WrapRequest,
    *,
    user: User,
    project: Project,
    allow_network: bool = True,
) -> WrapDraftBundle:
    """Run the LLM + render-Markdown pipeline on a *pre-built* request.

    Phase 5 introduces this entry point so the Routine flow can
    assemble its own :class:`WrapRequest` (narrowed by scope) without
    re-implementing the boilerplate around :func:`create_wrap_draft`
    and Markdown rendering. ``wrap_draft`` is a thin wrapper that
    just builds the request from a conversation first.

    Errors:

    * :class:`WrapProviderError` is rewrapped as
      :class:`WrapServiceError` so the route layer can return clean
      JSON without depending on the provider module.
    """
    try:
        analysis = create_wrap_draft(
            request,
            allow_network=allow_network,
            user=user,
        )
    except WrapProviderError as err:
        raise WrapServiceError(
            err.code, err.message, status=err.status
        ) from err

    created_at = datetime.now(timezone.utc)
    filename = build_wrap_file_name(analysis.title, created_at)
    meta = WrapMarkdownMeta(
        project_id=project.id,
        wrap_mode=request.mode,
        model=request.model,
        created_at=created_at,
    )
    markdown = build_markdown_with_frontmatter(analysis, meta)
    save_path_relative = _relative_save_path(project.id, filename)

    return WrapDraftBundle(
        request=request,
        analysis=analysis,
        markdown=markdown,
        suggested_filename=filename,
        save_path_relative=save_path_relative,
        used_mock=_used_mock(allow_network, user, request.model),
    )


def quick_wrap_draft(
    *,
    user: User,
    project: Project,
    conversation: Conversation,
    model: WrapModel | None = None,
    allow_network: bool = True,
) -> WrapDraftBundle:
    """Quick Wrap: defaults across the board.

    Thin wrapper around :func:`wrap_draft`. Kept as its own public
    entry point so route handlers and tests can express intent
    ("Quick Wrap, no knobs") without spelling out the defaults.

    ``model`` is optional so the frontend's "default wrap model"
    user preference can flow through. Pass ``None`` to keep using the
    server-side :data:`DEFAULT_MODEL`.
    """
    return wrap_draft(
        user=user,
        project=project,
        conversation=conversation,
        mode=WrapMode.QUICK,
        model=model if model is not None else DEFAULT_MODEL,
        allow_network=allow_network,
    )


def _relative_save_path(project_id: int, filename: str) -> str:
    return f"project-memory/wraps/{project_id}/{filename}"


def _used_mock(allow_network: bool, user: User, model: WrapModel) -> bool:
    """Best-effort guess of whether the mock fallback was used.

    Mirrors the logic in :func:`wrap_memory.providers.get_wrap_provider`
    but stays defensive: if the credential service errors out, we
    assume the mock path. Used purely for UI hinting — never a security
    boundary.
    """
    if not allow_network:
        return True
    try:
        from app.services.credentials_service import (
            CredentialsError,
            get_decrypted_key_for,
        )
        from .llm_adapter import route_for_model

        route = route_for_model(model)
        return not bool(get_decrypted_key_for(user, route.provider_id))
    except (CredentialsError, Exception):
        return True


# ---------------------------------------------------------------------------
# Save (write to disk).


@dataclass
class SavedWrap:
    """File-system record produced by :func:`save_wrap_draft`."""

    project_id: int
    filename: str
    absolute_path: Path
    relative_path: str
    bytes_written: int

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "filename": self.filename,
            "absolutePath": str(self.absolute_path),
            "relativePath": self.relative_path,
            "bytesWritten": self.bytes_written,
        }


def save_wrap_draft(
    *,
    user: User,
    project: Project,
    markdown: str,
    filename: str | None = None,
    base_dir: str | Path | None = None,
) -> SavedWrap:
    """Persist a rendered Markdown wrap to disk.

    ``markdown`` is written verbatim — the caller is expected to have
    rendered it already via :func:`build_markdown_with_frontmatter`.
    This keeps the writer single-purpose (no surprise re-rendering)
    and lets Phase 4 reuse it for routine drafts that the user edited.

    Returns a :class:`SavedWrap` describing where the file landed.
    """
    if project.user_id != user.id:
        raise WrapServiceError(
            "not_found", "Project not found.", status=404
        )
    if not isinstance(markdown, str) or not markdown.strip():
        raise WrapServiceError(
            "validation_error", "Wrap markdown is required.", status=400
        )

    name = _validate_filename(filename) if filename else build_wrap_file_name("wrap")

    target_dir = ensure_wraps_dir(project.id, base_dir=base_dir)

    # Disambiguate to avoid silent overwrites. Two save attempts inside
    # the same minute (Quick Wrap + Quick Wrap again, or two concurrent
    # routine saves) would otherwise collide because the filename's
    # timestamp prefix has minute resolution. We append ``_2``, ``_3``,
    # … until O_EXCL accepts the path.
    final_name, target_path, bytes_written = _write_unique(
        target_dir, name, markdown.encode("utf-8")
    )

    return SavedWrap(
        project_id=project.id,
        filename=final_name,
        absolute_path=target_path,
        relative_path=_relative_save_path(project.id, final_name),
        bytes_written=bytes_written,
    )


# Hard cap on suffix retries — anything beyond this is almost certainly
# a malicious caller hammering the endpoint, not a real collision.
_MAX_SUFFIX_ATTEMPTS = 64


def _write_unique(
    target_dir: Path, name: str, body: bytes
) -> tuple[str, Path, int]:
    """Atomically write ``body`` to ``target_dir / name`` without overwriting.

    Uses ``os.open`` with ``O_CREAT | O_EXCL | O_WRONLY`` so the
    "does it exist?" check and the create are a single syscall — no
    TOCTOU window where two concurrent requests can both decide they
    have a unique name. On collision, retries with ``<stem>_N.md``
    for N=2..64.

    Returns ``(final_name, absolute_path, bytes_written)``.
    """
    stem, ext = _split_md_name(name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    # Match Python's default umask + Path.write_bytes mode (0o666).
    mode = 0o644

    for attempt in range(1, _MAX_SUFFIX_ATTEMPTS + 1):
        candidate = name if attempt == 1 else f"{stem}_{attempt}{ext}"
        candidate_path = target_dir / candidate
        try:
            fd = os.open(str(candidate_path), flags, mode)
        except FileExistsError:
            continue
        except OSError as exc:
            raise WrapServiceError(
                "io_error",
                f"Could not write wrap file: {exc}",
                status=500,
            ) from exc

        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(body)
        except OSError as exc:
            # Clean up the empty file we managed to create.
            try:
                candidate_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise WrapServiceError(
                "io_error",
                f"Could not write wrap file: {exc}",
                status=500,
            ) from exc

        return candidate, candidate_path, len(body)

    raise WrapServiceError(
        "io_error",
        f"Could not pick a unique filename for {name!r} after "
        f"{_MAX_SUFFIX_ATTEMPTS} attempts.",
        status=500,
    )


def _split_md_name(name: str) -> tuple[str, str]:
    """Split ``foo.md`` → ``("foo", ".md")``. Falls back gracefully if
    the validator slipped a non-md name through (defensive only — the
    public callers always end in ``.md``)."""
    if name.endswith(".md"):
        return name[:-3], ".md"
    return name, ""


# ---------------------------------------------------------------------------
# Validation helpers.


_INVALID_FILENAME_CHARS = set('/\\\x00\r\n')


def _validate_filename(name: str) -> str:
    """Reject filenames that try to escape the wraps directory or use
    forbidden control characters. Phase 1 ``build_wrap_file_name`` already
    produces safe names; this guard exists for caller-supplied names that
    a clever Advanced-Wrap user might want to override."""
    cleaned = name.strip()
    if not cleaned:
        raise WrapServiceError(
            "validation_error", "Filename cannot be empty.", status=400
        )
    if not cleaned.endswith(".md"):
        raise WrapServiceError(
            "validation_error",
            "Filename must end with .md",
            status=400,
        )
    if any(ch in _INVALID_FILENAME_CHARS for ch in cleaned):
        raise WrapServiceError(
            "validation_error",
            "Filename contains forbidden characters.",
            status=400,
        )
    if cleaned in {".", ".."} or "/" in cleaned or ".." in cleaned.split("."):
        # Belt + braces: the char check above already excludes "/" but
        # we don't want to encourage `../foo.md` either.
        raise WrapServiceError(
            "validation_error",
            "Filename must be a plain file name, not a path.",
            status=400,
        )
    if len(cleaned) > 240:
        raise WrapServiceError(
            "validation_error",
            "Filename is too long (max 240 chars).",
            status=400,
        )
    return cleaned


__all__ = [
    "SavedWrap",
    "WrapDraftBundle",
    "WrapServiceError",
    "build_request_from_conversation",
    "quick_wrap_draft",
    "save_wrap_draft",
    "wrap_draft",
    "wrap_draft_from_request",
]
