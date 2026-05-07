"""Context Pack domain service.

Generating a Context Pack works like this:

1. Resolve the project (404 if it isn't owned by ``user``).
2. Pull the project's memories. Caller can opt-in to a specific subset
   via ``memory_ids``; otherwise we use everything we have.
3. Build a structured prompt (system + user) describing the memories
   and ask OpenRouter for a *plain Markdown* document the user can
   paste into a fresh AI session as project context.
4. Persist the resulting ``ContextPack``. The body is the raw Markdown.

The service deliberately stores zero secrets — the user's API key is
decrypted only at the moment of the OpenRouter call.

Re-running ``generate`` always creates a *new* ``ContextPack``; we
never overwrite an existing one. Users who want history can scroll the
list, users who don't can delete the old one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, or_, select

from app.extensions import db
from app.models import (
    ContextPack,
    ContextPackSource,
    Conversation,
    Memory,
    PACK_SOURCE_TYPES,
    Project,
    SOURCE_RECORD_TYPES,
    SOURCE_TYPE_ATTACHMENT,
    SOURCE_TYPE_CONVERSATION,
    SOURCE_TYPE_MESSAGE,
    SOURCE_TYPE_MIXED,
    SOURCE_TYPE_NOTE,
    SOURCE_TYPE_PROJECT,
    User,
    VISIBILITIES,
    VISIBILITY_PRIVATE,
)
from app.services.memory_service import MemoryError as MemoryServiceError
from app.providers import get_provider
from app.services.credentials_service import (
    CredentialsError,
    first_configured_provider,
    get_decrypted_key_for,
)
from app.services.llm_service import LLMError, chat_completion
from app.services.project_service import ProjectError, get_for_user as get_project_for_user

# Back-compat alias for any out-of-tree callers.
OpenRouterError = LLMError

TITLE_MAX = 160
DESCRIPTION_MAX = 500
SUMMARY_MAX = 2_000
INSTRUCTIONS_MAX = 1_000
BODY_MAX = 12_000
KEYWORDS_MAX_COUNT = 32
KEYWORD_MAX_LEN = 60
VECTOR_INDEX_ID_MAX = 120
STRUCTURED_CONTENT_MAX_CHARS = 40_000  # JSON-serialized length ceiling
GRAPH_DATA_MAX_CHARS = 40_000
SOURCE_TITLE_MAX = 240
SOURCE_METADATA_MAX_CHARS = 8_000
MAX_SOURCES_PER_PACK = 500
MEMORY_CONTENT_LIMIT = 600
MEMORIES_PER_PACK = 200
MAX_LIST_LIMIT = 100
# ``visibility`` values the MVP logic accepts from user input. The column
# supports all three enum values, but we refuse to create or update a pack
# to anything beyond ``private`` until multi-user sharing is implemented.
ALLOWED_INPUT_VISIBILITIES = (VISIBILITY_PRIVATE,)


SYSTEM_PROMPT = """You are turning a project's distilled memory bank into a "Context Pack" — a short, copy-pasteable Markdown document the user will drop into a fresh AI session so the next model picks up where the project left off.

Output format requirements:
- Output PLAIN Markdown only. No code fences. No commentary before or after.
- Start with a single `#` H1 line that is the pack title.
- Then ONE short paragraph (1-3 sentences) summarizing the project state.
- Then the following sections IN THIS ORDER, each as a `##` H2 heading:
  - `## Decisions` — bullet list of decisions already made.
  - `## Open Todos` — bullet list of things still to do.
  - `## Key Facts` — bullet list of stable facts about the project / system.
  - `## Open Questions` — bullet list of questions worth revisiting.
  - `## Notes for the next session` — 1-3 short bullets orienting whoever picks this up next.
- Skip any section whose underlying memories are empty (do not emit empty headings).
- Use concise bullets (one short sentence each). De-duplicate. Drop pleasantries.
- Stay under ~600 words.

If the user provides extra `instructions`, follow them (e.g. "focus on backend decisions only", "rewrite as a system prompt"). Their instructions override style choices but never the format above.
"""


class ContextPackError(Exception):
    """Predictable, user-facing context pack failures."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _normalize_title(raw: str | None, *, project: Project) -> str:
    if not raw:
        stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
        return _clamp(f"{project.name} · Context Pack ({stamp})", TITLE_MAX)
    cleaned = raw.strip()
    if not cleaned:
        stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
        return _clamp(f"{project.name} · Context Pack ({stamp})", TITLE_MAX)
    return _clamp(cleaned, TITLE_MAX)


def _normalize_instructions(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    return _clamp(cleaned, INSTRUCTIONS_MAX)


def _normalize_memory_ids(raw) -> list[int] | None:
    """Accept ``None`` (use all), an empty iterable (also use all), or a list of ids."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple, set)):
        raise ContextPackError(
            "validation_error",
            "memory_ids must be a list of memory IDs.",
        )
    cleaned: list[int] = []
    for item in raw:
        try:
            cleaned.append(int(item))
        except (TypeError, ValueError):
            raise ContextPackError(
                "validation_error",
                "memory_ids must contain integers only.",
            )
    if not cleaned:
        return None
    # Preserve order, deduplicate.
    seen: set[int] = set()
    out: list[int] = []
    for mid in cleaned:
        if mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out[:MEMORIES_PER_PACK]


def _fetch_memories(
    user: User, project: Project, memory_ids: list[int] | None
) -> list[Memory]:
    base = (
        select(Memory)
        .where(Memory.user_id == user.id, Memory.project_id == project.id)
    )
    if memory_ids is not None:
        base = base.where(Memory.id.in_(memory_ids))
    base = base.order_by(Memory.created_at.asc(), Memory.id.asc())
    rows = list(db.session.scalars(base).all())
    if memory_ids is not None and not rows:
        raise ContextPackError(
            "no_memories_selected",
            "None of the selected memories belong to this project.",
        )
    return rows[:MEMORIES_PER_PACK]


def _format_memories_for_prompt(memories: Iterable[Memory]) -> str:
    grouped: dict[str, list[Memory]] = {
        "decision": [],
        "todo": [],
        "fact": [],
        "question": [],
    }
    others: list[Memory] = []
    for mem in memories:
        if mem.kind in grouped:
            grouped[mem.kind].append(mem)
        else:
            others.append(mem)

    blocks: list[str] = []

    def render(kind: str, label: str) -> None:
        items = grouped.get(kind, [])
        if not items:
            return
        lines = [f"### {label}"]
        for mem in items:
            content = _clamp((mem.content or "").strip(), MEMORY_CONTENT_LIMIT)
            if not content:
                continue
            lines.append(f"- {content}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    render("decision", "Decisions (kind=decision)")
    render("todo", "Open todos (kind=todo)")
    render("fact", "Key facts (kind=fact)")
    render("question", "Open questions (kind=question)")

    if others:
        lines = ["### Other"]
        for mem in others:
            content = _clamp((mem.content or "").strip(), MEMORY_CONTENT_LIMIT)
            if not content:
                continue
            lines.append(f"- ({mem.kind}) {content}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    if not blocks:
        return ""
    return "\n\n".join(blocks)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        # ```markdown\n...\n``` or ```\n...\n```
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1 :]
        else:
            stripped = stripped[3:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    return stripped


def list_for_project(user: User, project_id: int) -> list[ContextPack]:
    try:
        project = get_project_for_user(user, project_id)
    except ProjectError as err:
        raise ContextPackError(err.code, err.message, status=err.status) from err

    stmt = (
        select(ContextPack)
        .where(
            ContextPack.user_id == user.id,
            ContextPack.project_id == project.id,
        )
        .order_by(ContextPack.created_at.desc(), ContextPack.id.desc())
    )
    return list(db.session.scalars(stmt).all())


def list_recent_for_user(user: User, *, limit: int = 20) -> list[ContextPack]:
    if limit < 1:
        limit = 1
    if limit > MAX_LIST_LIMIT:
        limit = MAX_LIST_LIMIT
    stmt = (
        select(ContextPack)
        .where(ContextPack.user_id == user.id)
        .order_by(ContextPack.created_at.desc(), ContextPack.id.desc())
        .limit(limit)
    )
    return list(db.session.scalars(stmt).all())


def count_for_user(user: User) -> int:
    return db.session.query(ContextPack).filter(ContextPack.user_id == user.id).count()


def get_for_user(user: User, pack_id: int) -> ContextPack:
    pack = db.session.get(ContextPack, pack_id)
    if pack is None or pack.user_id != user.id:
        raise ContextPackError("not_found", "Context Pack not found.", status=404)
    return pack


def delete_pack(user: User, pack_id: int) -> None:
    pack = get_for_user(user, pack_id)
    db.session.delete(pack)
    db.session.commit()


def update_pack(
    user: User,
    pack_id: int,
    *,
    patch: dict | None = None,
    # Legacy kw-only args kept for back-compat with existing callers
    # (title/body-only edits from the single-pack edit view):
    title: str | None = None,
    body: str | None = None,
    title_provided: bool = False,
    body_provided: bool = False,
) -> ContextPack:
    """Patch a pack's mutable fields.

    Two calling conventions are supported:

    1. **Explicit patch dict** (preferred) — callers pass
       ``patch={"field": value, ...}``. Only keys actually present in
       the dict are considered "intent to update"; this lets PATCH
       clear a nullable field by passing ``{"description": None}``.
    2. **Legacy kwargs** — ``title_provided`` / ``body_provided``
       booleans drive the logic the way the original R11 edit view
       expects. Kept so ``/api/context-packs/:id`` PATCH from the
       ContextPackView continues to work unchanged.

    The pack's ``version`` is bumped iff any *content* field changes
    (title / body / summary / description / structured_content /
    keywords / graph_data). Non-content edits (visibility, parent, tags)
    still touch ``updated_at`` but don't bump version.
    """
    pack = get_for_user(user, pack_id)

    # Merge the two calling conventions into a single "dirty" dict.
    # The keys are the *model attribute names*.
    dirty: dict = {}

    if patch is not None:
        if not isinstance(patch, dict):
            raise ContextPackError(
                "validation_error",
                "Update payload must be a JSON object.",
            )
        dirty.update(patch)

    # Map the legacy kwargs into the patch dict.
    if title_provided and "title" not in dirty:
        dirty["title"] = title
    if body_provided and "body" not in dirty:
        dirty["body"] = body

    if not dirty:
        # Nothing to change — return the pack unchanged. Callers should
        # have caught this at the route layer, but we don't want the
        # service to bump updated_at needlessly.
        return pack

    # Fields whose change counts as a content update (bumps ``version``).
    CONTENT_FIELDS = frozenset(
        {
            "title",
            "body",
            "summary",
            "description",
            "structured_content",
            "keywords",
            "graph_data",
        }
    )

    bump_version = False

    if "title" in dirty:
        cleaned_title = _normalize_title_input(dirty["title"])
        if cleaned_title != pack.title:
            pack.title = cleaned_title
            bump_version = True

    if "body" in dirty:
        cleaned_body = _normalize_body_input(dirty["body"])
        if cleaned_body != (pack.body or ""):
            pack.body = cleaned_body
            bump_version = True

    if "summary" in dirty:
        cleaned_summary = _normalize_long_text(
            dirty["summary"], SUMMARY_MAX, field="summary"
        )
        if cleaned_summary != pack.summary:
            pack.summary = cleaned_summary
            bump_version = True

    if "description" in dirty:
        cleaned_desc = _normalize_long_text(
            dirty["description"], DESCRIPTION_MAX, field="description"
        )
        if cleaned_desc != pack.description:
            pack.description = cleaned_desc
            bump_version = True

    if "keywords" in dirty:
        cleaned_keywords = _normalize_keywords_input(dirty["keywords"])
        if cleaned_keywords != pack.get_keywords():
            pack.set_keywords(cleaned_keywords)
            bump_version = True

    if "structured_content" in dirty:
        normalized = _normalize_json_blob(
            dirty["structured_content"],
            STRUCTURED_CONTENT_MAX_CHARS,
            field="structured_content",
        )
        if normalized != pack.get_structured_content():
            pack.set_structured_content(normalized)
            bump_version = True

    if "graph_data" in dirty:
        normalized_graph = _normalize_json_blob(
            dirty["graph_data"],
            GRAPH_DATA_MAX_CHARS,
            field="graph_data",
        )
        if normalized_graph != pack.get_graph_data():
            pack.set_graph_data(normalized_graph)
            bump_version = True

    # Non-content fields — changeable but don't bump version.
    if "visibility" in dirty:
        pack.visibility = _normalize_visibility_input(dirty["visibility"])

    if "source_type" in dirty:
        pack.source_type = _normalize_pack_source_type_input(dirty["source_type"])

    if "vector_index_id" in dirty:
        pack.vector_index_id = _normalize_vector_index_id(dirty["vector_index_id"])

    if "parent_pack_id" in dirty:
        pack.parent_pack_id = _normalize_parent_pack_id(
            user, pack, dirty["parent_pack_id"]
        )

    # Caller could pass ``project_id`` to re-home a pack, or clear it.
    if "project_id" in dirty:
        pack.project_id = _normalize_project_id_input(user, dirty["project_id"])

    if "conversation_id" in dirty:
        pack.conversation_id = _normalize_conversation_id_input(
            user, dirty["conversation_id"]
        )

    if bump_version:
        pack.version = (pack.version or 1) + 1

    db.session.add(pack)
    db.session.commit()
    db.session.refresh(pack)
    return pack


# =============================================================================
# R-PACK-CORE: CRUD helpers and source utilities.
# =============================================================================


def create_for_user(
    user: User,
    *,
    title: str | None = None,
    description: str | None = None,
    summary: str | None = None,
    body: str | None = None,
    keywords=None,
    structured_content=None,
    source_type: str | None = None,
    project_id: int | None = None,
    conversation_id: int | None = None,
    visibility: str | None = None,
    vector_index_id: str | None = None,
    parent_pack_id: int | None = None,
    sources: list | None = None,
) -> ContextPack:
    """Create a Context Pack from user-supplied content.

    Used by ``POST /api/context-packs`` — distinct from
    :func:`generate` (which derives a pack from memories via LLM) and
    from :func:`wrap_up_service.wrap_up_*` (which derives one from
    conversation transcripts). Those two continue to be the primary
    production paths; this constructor exists for manual entry,
    external imports, tests, and future programmatic callers.

    Validation errors surface as :class:`ContextPackError` with code
    ``validation_error``.
    """
    cleaned_title = _normalize_title_input(title) if title is not None else None
    if not cleaned_title:
        cleaned_title = _default_title()

    cleaned_body = _normalize_body_input(body if body is not None else "")
    cleaned_desc = _normalize_long_text(
        description, DESCRIPTION_MAX, field="description"
    )
    cleaned_summary = _normalize_long_text(
        summary, SUMMARY_MAX, field="summary"
    )
    cleaned_keywords = _normalize_keywords_input(keywords)
    cleaned_structured = _normalize_json_blob(
        structured_content,
        STRUCTURED_CONTENT_MAX_CHARS,
        field="structured_content",
    )
    cleaned_source_type = _normalize_pack_source_type_input(source_type)
    cleaned_visibility = (
        _normalize_visibility_input(visibility)
        if visibility is not None
        else VISIBILITY_PRIVATE
    )
    cleaned_vector_id = _normalize_vector_index_id(vector_index_id)

    resolved_project_id = _normalize_project_id_input(user, project_id)
    resolved_conversation_id = _normalize_conversation_id_input(
        user, conversation_id
    )

    pack = ContextPack(
        user_id=user.id,
        project_id=resolved_project_id,
        conversation_id=resolved_conversation_id,
        title=cleaned_title,
        description=cleaned_desc,
        summary=cleaned_summary,
        body=cleaned_body,
        source_type=cleaned_source_type,
        visibility=cleaned_visibility,
        vector_index_id=cleaned_vector_id,
        version=1,
        usage_count=0,
    )
    pack.set_keywords(cleaned_keywords)
    pack.set_structured_content(cleaned_structured)

    db.session.add(pack)
    db.session.flush()  # need pack.id before we write parent + sources

    # parent_pack_id must be validated *after* flush so we can guard
    # against self-references without an extra round-trip.
    if parent_pack_id is not None:
        pack.parent_pack_id = _normalize_parent_pack_id(user, pack, parent_pack_id)

    if sources:
        _write_source_rows(user, pack, sources)

    db.session.commit()
    db.session.refresh(pack)
    return pack


def list_for_user(
    user: User,
    *,
    keyword: str | None = None,
    project_id: int | None = None,
    source_type: str | None = None,
    visibility: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ContextPack], int]:
    """Paginated + filtered listing of a user's packs.

    Returns ``(rows, total)`` where ``total`` is the count **matching
    the filter**, not the user's overall total. Callers that want both
    totals can also call :func:`count_for_user`.

    Filter semantics:

    * ``keyword`` — case-insensitive substring match on
      ``title`` / ``description`` / ``summary`` / ``keywords``.
    * ``project_id`` — exact match on the pack's ``project_id``.
    * ``source_type`` — exact match on the pack's ``source_type``.
    * ``visibility`` — exact match. Defaults to no filter so the user
      sees all their own packs regardless of scope.
    """
    limit = _clamp_limit(limit)
    offset = max(0, int(offset or 0))

    stmt = select(ContextPack).where(ContextPack.user_id == user.id)
    count_stmt = (
        select(func.count(ContextPack.id)).where(ContextPack.user_id == user.id)
    )

    if project_id is not None:
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            raise ContextPackError(
                "validation_error", "projectId must be an integer."
            )
        stmt = stmt.where(ContextPack.project_id == pid)
        count_stmt = count_stmt.where(ContextPack.project_id == pid)

    if source_type is not None:
        cleaned = _normalize_pack_source_type_input(source_type)
        if cleaned is not None:
            stmt = stmt.where(ContextPack.source_type == cleaned)
            count_stmt = count_stmt.where(ContextPack.source_type == cleaned)

    if visibility is not None:
        cleaned_vis = _normalize_visibility_input(visibility)
        stmt = stmt.where(ContextPack.visibility == cleaned_vis)
        count_stmt = count_stmt.where(ContextPack.visibility == cleaned_vis)

    if keyword:
        needle = _normalize_keyword_query(keyword)
        if needle:
            like = f"%{needle}%"
            # SQLite's LIKE is case-insensitive for ASCII only; for an
            # MVP this is acceptable. Postgres/MySQL would use ILIKE.
            clause = or_(
                ContextPack.title.ilike(like),
                ContextPack.description.ilike(like),
                ContextPack.summary.ilike(like),
                ContextPack.keywords.ilike(like),
            )
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)

    stmt = (
        stmt.order_by(ContextPack.created_at.desc(), ContextPack.id.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = list(db.session.scalars(stmt).all())
    total = int(db.session.scalar(count_stmt) or 0)
    return rows, total


def list_sources_for_pack(user: User, pack_id: int) -> list[ContextPackSource]:
    """Return a pack's provenance rows (ownership-checked).

    ``ContextPackSource.pack`` already has joined loading, so this is a
    single SELECT + ORDER BY; we re-derive the list via
    ``pack.sources`` so SQLAlchemy's session cache is the single source
    of truth.
    """
    pack = get_for_user(user, pack_id)
    # ``sources`` is selectin-loaded on the model; materialize to list
    # for a stable return type.
    return list(pack.sources or [])


def register_usage(user: User, pack_id: int) -> ContextPack:
    """Bump ``usage_count`` + ``last_used_at`` on a pack.

    Callers: the Prompt+ attach flow, any future "use this pack" button,
    and the wrap-up flow when a pack is re-seeded into a new
    conversation. Keeping the bump in one place means the counter can
    never disagree with ``last_used_at``.
    """
    pack = get_for_user(user, pack_id)
    pack.usage_count = (pack.usage_count or 0) + 1
    pack.last_used_at = _utcnow()
    db.session.add(pack)
    db.session.commit()
    db.session.refresh(pack)
    return pack


# -------- Input normalization helpers ------------------------------------


def _default_title() -> str:
    stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
    return _clamp(f"Context Pack ({stamp})", TITLE_MAX)


def _normalize_title_input(raw) -> str:
    if raw is None:
        return _default_title()
    if not isinstance(raw, str):
        raise ContextPackError("validation_error", "Title must be a string.")
    cleaned = raw.strip()
    if not cleaned:
        raise ContextPackError("validation_error", "Title cannot be empty.")
    return _clamp(cleaned, TITLE_MAX)


def _normalize_body_input(raw) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ContextPackError("validation_error", "Body must be a string.")
    if len(raw) > BODY_MAX:
        raise ContextPackError(
            "validation_error", f"Body must be at most {BODY_MAX} characters."
        )
    return raw


def _normalize_long_text(raw, limit: int, *, field: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ContextPackError(
            "validation_error", f"{field} must be a string or null."
        )
    cleaned = raw.strip()
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise ContextPackError(
            "validation_error", f"{field} must be at most {limit} characters."
        )
    return cleaned


def _normalize_keywords_input(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        # Accept comma-separated strings as a convenience.
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, (list, tuple)):
        raise ContextPackError(
            "validation_error", "keywords must be a list of strings."
        )
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ContextPackError(
                "validation_error", "keywords must contain strings only."
            )
        word = item.strip()
        if not word:
            continue
        if len(word) > KEYWORD_MAX_LEN:
            raise ContextPackError(
                "validation_error",
                f"Each keyword must be at most {KEYWORD_MAX_LEN} characters.",
            )
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(word)
        if len(out) >= KEYWORDS_MAX_COUNT:
            break
    return out


def _normalize_json_blob(raw, max_chars: int, *, field: str):
    if raw is None:
        return None
    if not isinstance(raw, (dict, list)):
        raise ContextPackError(
            "validation_error", f"{field} must be a JSON object or array."
        )
    try:
        encoded = json.dumps(raw, ensure_ascii=False)
    except (TypeError, ValueError) as err:
        raise ContextPackError(
            "validation_error", f"{field} is not JSON-serializable: {err}"
        ) from err
    if len(encoded) > max_chars:
        raise ContextPackError(
            "validation_error",
            f"{field} exceeds the {max_chars}-character serialized limit.",
        )
    return raw


def _normalize_pack_source_type_input(raw) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ContextPackError(
            "validation_error", "sourceType must be a string."
        )
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    if cleaned not in PACK_SOURCE_TYPES:
        raise ContextPackError(
            "validation_error",
            f"sourceType must be one of: {', '.join(PACK_SOURCE_TYPES)}.",
        )
    return cleaned


def _normalize_visibility_input(raw) -> str:
    if raw is None:
        return VISIBILITY_PRIVATE
    if not isinstance(raw, str):
        raise ContextPackError(
            "validation_error", "visibility must be a string."
        )
    cleaned = raw.strip().lower()
    if cleaned not in VISIBILITIES:
        raise ContextPackError(
            "validation_error",
            f"visibility must be one of: {', '.join(VISIBILITIES)}.",
        )
    if cleaned not in ALLOWED_INPUT_VISIBILITIES:
        # Column supports it; MVP logic doesn't.
        raise ContextPackError(
            "validation_error",
            f"visibility={cleaned!r} is reserved for a future release. "
            f"Use {VISIBILITY_PRIVATE!r} for now.",
        )
    return cleaned


def _normalize_vector_index_id(raw) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ContextPackError(
            "validation_error", "vectorIndexId must be a string."
        )
    cleaned = raw.strip()
    if not cleaned:
        return None
    if len(cleaned) > VECTOR_INDEX_ID_MAX:
        raise ContextPackError(
            "validation_error",
            f"vectorIndexId must be at most {VECTOR_INDEX_ID_MAX} characters.",
        )
    return cleaned


def _normalize_project_id_input(user: User, raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        raise ContextPackError(
            "validation_error", "projectId must be an integer or null."
        )
    try:
        project = get_project_for_user(user, pid)
    except ProjectError as err:
        raise ContextPackError(err.code, err.message, status=err.status) from err
    return project.id


def _normalize_conversation_id_input(user: User, raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        cid = int(raw)
    except (TypeError, ValueError):
        raise ContextPackError(
            "validation_error", "conversationId must be an integer or null."
        )
    convo = db.session.get(Conversation, cid)
    if convo is None or convo.user_id != user.id:
        # Same "treat as not-found" policy the rest of the codebase uses
        # (avoid leaking existence).
        raise ContextPackError(
            "not_found", "Conversation not found.", status=404
        )
    return convo.id


def _normalize_parent_pack_id(
    user: User, pack: ContextPack, raw
) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        raise ContextPackError(
            "validation_error", "parentPackId must be an integer or null."
        )
    if pack.id is not None and pid == pack.id:
        raise ContextPackError(
            "validation_error", "parentPackId cannot reference the pack itself."
        )
    parent = db.session.get(ContextPack, pid)
    if parent is None or parent.user_id != user.id:
        raise ContextPackError(
            "not_found", "Parent Context Pack not found.", status=404
        )
    return parent.id


def _normalize_keyword_query(raw) -> str:
    if not isinstance(raw, str):
        return ""
    cleaned = raw.strip()
    # SQLite LIKE wildcards need escaping if we want literal %/_; for
    # keyword search we just strip them to keep things predictable.
    cleaned = cleaned.replace("%", " ").replace("_", " ").strip()
    return cleaned[:160]


def _clamp_limit(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 20
    if value < 1:
        return 1
    if value > MAX_LIST_LIMIT:
        return MAX_LIST_LIMIT
    return value


# -------- Source-row helpers --------------------------------------------


def _write_source_rows(
    user: User, pack: ContextPack, raw_sources: list
) -> None:
    """Validate + persist an incoming list of source rows.

    Each entry must be a dict with at least ``sourceType``. Typed FKs
    and free-form metadata are resolved here. Used both by the
    POST /api/context-packs endpoint and (via a different wrapper) by
    the wrap-up service when it stamps provenance rows.
    """
    if not isinstance(raw_sources, list):
        raise ContextPackError(
            "validation_error", "sources must be a list."
        )
    if len(raw_sources) > MAX_SOURCES_PER_PACK:
        raise ContextPackError(
            "validation_error",
            f"Too many sources; max is {MAX_SOURCES_PER_PACK}.",
        )
    for idx, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ContextPackError(
                "validation_error", f"sources[{idx}] must be an object."
            )
        source_type = item.get("sourceType") or item.get("source_type")
        if not isinstance(source_type, str) or not source_type.strip():
            raise ContextPackError(
                "validation_error",
                f"sources[{idx}].sourceType is required.",
            )
        cleaned_type = source_type.strip().lower()
        if cleaned_type not in SOURCE_RECORD_TYPES:
            raise ContextPackError(
                "validation_error",
                f"sources[{idx}].sourceType must be one of: "
                f"{', '.join(SOURCE_RECORD_TYPES)}.",
            )

        # Extract the typed FK fields. We accept both camelCase (coming
        # from the JSON API) and snake_case (for python callers).
        project_id = _coerce_id(
            item.get("projectId") or item.get("project_id")
        )
        conversation_id = _coerce_id(
            item.get("conversationId") or item.get("conversation_id")
        )
        note_id = _coerce_id(item.get("noteId") or item.get("note_id"))
        attachment_id = _coerce_id(
            item.get("attachmentId") or item.get("attachment_id")
        )
        source_id = _coerce_id(item.get("sourceId") or item.get("source_id"))

        # For typed rows, also ensure ownership of the referenced entity
        # where we can (project / conversation). Notes + attachments are
        # trusted ids (notes have no model yet; attachments are already
        # guarded by the attachment service at use time).
        if cleaned_type == SOURCE_TYPE_PROJECT:
            if project_id is None:
                project_id = source_id
            if project_id is None:
                raise ContextPackError(
                    "validation_error",
                    f"sources[{idx}] requires projectId for source_type='project'.",
                )
            _normalize_project_id_input(user, project_id)  # raises on bad
            source_id = project_id
        elif cleaned_type == SOURCE_TYPE_CONVERSATION:
            if conversation_id is None:
                conversation_id = source_id
            if conversation_id is None:
                raise ContextPackError(
                    "validation_error",
                    f"sources[{idx}] requires conversationId for source_type='conversation'.",
                )
            _normalize_conversation_id_input(user, conversation_id)
            source_id = conversation_id
        elif cleaned_type == SOURCE_TYPE_MESSAGE:
            if source_id is None:
                raise ContextPackError(
                    "validation_error",
                    f"sources[{idx}] requires sourceId for source_type='message'.",
                )
            # Best-effort: if conversation_id is passed, trust it;
            # otherwise leave null (we don't want to run an extra join
            # per source here — the caller or the wrap-up flow already
            # knows it).
        elif cleaned_type == SOURCE_TYPE_NOTE:
            if note_id is None:
                note_id = source_id
            if note_id is None:
                raise ContextPackError(
                    "validation_error",
                    f"sources[{idx}] requires noteId for source_type='note'.",
                )
            source_id = note_id
        elif cleaned_type == SOURCE_TYPE_ATTACHMENT:
            if attachment_id is None:
                attachment_id = source_id
            if attachment_id is None:
                raise ContextPackError(
                    "validation_error",
                    f"sources[{idx}] requires attachmentId for source_type='attachment'.",
                )
            source_id = attachment_id

        raw_title = item.get("sourceTitle") or item.get("source_title")
        source_title: str | None
        if raw_title is None:
            source_title = None
        else:
            if not isinstance(raw_title, str):
                raise ContextPackError(
                    "validation_error",
                    f"sources[{idx}].sourceTitle must be a string.",
                )
            source_title = _clamp(raw_title.strip(), SOURCE_TITLE_MAX) or None

        metadata = item.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ContextPackError(
                "validation_error",
                f"sources[{idx}].metadata must be an object.",
            )
        if metadata is not None:
            encoded = json.dumps(metadata, ensure_ascii=False)
            if len(encoded) > SOURCE_METADATA_MAX_CHARS:
                raise ContextPackError(
                    "validation_error",
                    f"sources[{idx}].metadata exceeds size limit.",
                )

        row = ContextPackSource(
            context_pack_id=pack.id,
            source_type=cleaned_type,
            source_id=source_id,
            project_id=project_id,
            conversation_id=conversation_id,
            note_id=note_id,
            attachment_id=attachment_id,
            source_title=source_title,
        )
        row.set_metadata(metadata)
        db.session.add(row)


def _coerce_id(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ContextPackError(
            "validation_error", "Source ids must be integers or null."
        )


def generate(
    user: User,
    project_id: int,
    *,
    title: str | None = None,
    instructions: str | None = None,
    memory_ids=None,
    model: str | None = None,
) -> ContextPack:
    """Build a new Context Pack for ``project_id`` and persist it."""
    try:
        project = get_project_for_user(user, project_id)
    except ProjectError as err:
        raise ContextPackError(err.code, err.message, status=err.status) from err

    cleaned_ids = _normalize_memory_ids(memory_ids)
    cleaned_instructions = _normalize_instructions(instructions)
    cleaned_title = _normalize_title(title, project=project)

    memories = _fetch_memories(user, project, cleaned_ids)
    if not memories:
        raise ContextPackError(
            "no_memories",
            "This project has no memories yet. Wrap up a conversation first.",
        )

    summary_provider = first_configured_provider(user) or "openrouter"

    try:
        api_key = get_decrypted_key_for(user, summary_provider)
    except CredentialsError as err:
        raise ContextPackError(err.code, err.message, status=err.status) from err
    if not api_key:
        raise ContextPackError(
            "no_api_key",
            "Add an LLM API key in Settings (OpenRouter, DeepSeek, or OpenAI) "
            "before generating a pack.",
        )

    cfg = get_provider(summary_provider)
    chosen_model = (model or cfg.summary_model).strip() or cfg.summary_model

    memories_block = _format_memories_for_prompt(memories)
    if not memories_block:
        raise ContextPackError(
            "no_memories",
            "Selected memories are empty after trimming.",
        )

    user_prompt_parts = [
        f"Project name: {project.name!r}.",
    ]
    if project.description:
        user_prompt_parts.append(f"Project description: {project.description.strip()}")
    user_prompt_parts.append(f"Pack title to use as the H1: {cleaned_title!r}.")
    if cleaned_instructions:
        user_prompt_parts.append(
            f"Extra user instructions (must follow):\n{cleaned_instructions}"
        )
    user_prompt_parts.append("===== MEMORIES =====")
    user_prompt_parts.append(memories_block)
    user_prompt_parts.append("===== END MEMORIES =====")

    payload = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_prompt_parts)},
    ]

    try:
        completion = chat_completion(
            api_key,
            model=chosen_model,
            messages=payload,
            provider=summary_provider,
            temperature=0.2,
        )
    except LLMError as err:
        raise ContextPackError(err.code, err.message, status=err.status) from err

    body_text = _strip_code_fences(completion.content or "")
    if not body_text.strip():
        raise ContextPackError(
            "generation_failed",
            "The model returned an empty pack.",
            status=502,
        )
    body_text = body_text[:BODY_MAX]

    pack = ContextPack(
        user_id=user.id,
        project_id=project.id,
        title=cleaned_title,
        body=body_text,
        model=completion.model or chosen_model,
        instructions=cleaned_instructions,
        memory_count=len(memories),
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        total_tokens=completion.total_tokens,
    )
    pack.set_source_memory_ids([m.id for m in memories])
    db.session.add(pack)
    db.session.commit()
    db.session.refresh(pack)
    return pack


# Re-export upstream MemoryError for callers that already handle it.
MemoryError = MemoryServiceError


__all__ = [
    "ALLOWED_INPUT_VISIBILITIES",
    "BODY_MAX",
    "ContextPackError",
    "DESCRIPTION_MAX",
    "INSTRUCTIONS_MAX",
    "KEYWORDS_MAX_COUNT",
    "KEYWORD_MAX_LEN",
    "MAX_LIST_LIMIT",
    "MEMORIES_PER_PACK",
    "SUMMARY_MAX",
    "TITLE_MAX",
    "count_for_user",
    "create_for_user",
    "delete_pack",
    "generate",
    "get_for_user",
    "list_for_project",
    "list_for_user",
    "list_recent_for_user",
    "list_sources_for_pack",
    "register_usage",
    "update_pack",
]
