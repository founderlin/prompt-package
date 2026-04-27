"""Search across the user's own messages, memories, and conversations.

R10 keeps things simple: SQLite-friendly ``LIKE`` (case-insensitive via
``func.lower``) over a small set of text fields. The service:

* Restricts every query to the calling user (404-style isolation; nothing
  belonging to other users will ever match).
* Returns three parallel result lists (``messages`` / ``memories`` /
  ``conversations``) each capped at ``limit`` rows.
* Generates a ``snippet`` per hit (a window around the first match) plus a
  ``match_field`` so the UI knows which field tripped the hit (``content`` /
  ``source_excerpt`` / ``title`` / ``summary``).

Querying is straightforward; we never expose the raw SQL ``LIKE`` to the
caller — they just send ``q``. We escape ``%`` / ``_`` / ``\\`` so user input
can't accidentally turn into wildcards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import func, or_, select

from app.extensions import db
from app.models import Conversation, Memory, Message, Project, User

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
SNIPPET_RADIUS = 80  # chars on either side of the first match
MIN_QUERY_LEN = 1
MAX_QUERY_LEN = 200

VALID_TYPES = ("messages", "memories", "conversations")


class SearchError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class _Hit:
    field: str
    text: str


def _normalize_query(raw: str | None) -> str:
    if raw is None:
        raise SearchError("validation_error", "Query is required.")
    cleaned = raw.strip()
    if len(cleaned) < MIN_QUERY_LEN:
        raise SearchError("validation_error", "Query is required.")
    if len(cleaned) > MAX_QUERY_LEN:
        raise SearchError(
            "validation_error",
            f"Query must be at most {MAX_QUERY_LEN} characters.",
        )
    return cleaned


def _normalize_limit(raw: int | str | None) -> int:
    if raw is None or raw == "":
        return DEFAULT_LIMIT
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if n < 1:
        return 1
    if n > MAX_LIMIT:
        return MAX_LIMIT
    return n


def _normalize_types(raw: Iterable[str] | str | None) -> tuple[str, ...]:
    if raw is None:
        return VALID_TYPES
    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        items = [str(t).strip() for t in raw if str(t).strip()]
    if not items or "all" in items:
        return VALID_TYPES
    cleaned = tuple(t for t in items if t in VALID_TYPES)
    return cleaned or VALID_TYPES


def _escape_like(term: str) -> str:
    # SQLAlchemy's ``ilike`` does not auto-escape; we add ``escape='\\'`` and
    # neutralise the three meta-characters.
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_snippet(text: str | None, query_lower: str) -> str | None:
    if not text:
        return None
    lower = text.lower()
    idx = lower.find(query_lower)
    if idx < 0:
        # No actual hit on this field; return None so the caller can pick another.
        return None
    start = max(0, idx - SNIPPET_RADIUS)
    end = min(len(text), idx + len(query_lower) + SNIPPET_RADIUS)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def _pick_first_hit(
    query_lower: str, candidates: list[tuple[str, str | None]]
) -> _Hit | None:
    """Among the (field, value) pairs, return the first one that contains the query."""
    for field, value in candidates:
        if not value:
            continue
        if query_lower in value.lower():
            return _Hit(field=field, text=value)
    return None


def _search_messages(user: User, query: str, *, limit: int) -> list[dict]:
    pattern = f"%{_escape_like(query)}%"
    stmt = (
        select(Message, Conversation, Project)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(Project, Conversation.project_id == Project.id)
        .where(
            Conversation.user_id == user.id,
            Message.role.in_(("user", "assistant")),
            func.lower(Message.content).like(func.lower(pattern), escape="\\"),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = db.session.execute(stmt).all()
    out: list[dict] = []
    q_lower = query.lower()
    for message, conversation, project in rows:
        snippet = _build_snippet(message.content, q_lower) or message.content
        out.append(
            {
                "type": "message",
                "match_field": "content",
                "snippet": snippet,
                "id": message.id,
                "role": message.role,
                "model": message.model,
                "created_at": _isoformat(message.created_at),
                "conversation": {
                    "id": conversation.id,
                    "title": conversation.title,
                },
                "project": {
                    "id": project.id,
                    "name": project.name,
                },
            }
        )
    return out


def _search_memories(user: User, query: str, *, limit: int) -> list[dict]:
    pattern = f"%{_escape_like(query)}%"
    stmt = (
        select(Memory, Conversation, Project)
        .outerjoin(Conversation, Memory.conversation_id == Conversation.id)
        .join(Project, Memory.project_id == Project.id)
        .where(
            Memory.user_id == user.id,
            or_(
                func.lower(Memory.content).like(func.lower(pattern), escape="\\"),
                func.lower(Memory.source_excerpt).like(
                    func.lower(pattern), escape="\\"
                ),
            ),
        )
        .order_by(Memory.created_at.desc(), Memory.id.desc())
        .limit(limit)
    )
    rows = db.session.execute(stmt).all()
    out: list[dict] = []
    q_lower = query.lower()
    for memory, conversation, project in rows:
        hit = _pick_first_hit(
            q_lower,
            [("content", memory.content), ("source_excerpt", memory.source_excerpt)],
        )
        snippet = (
            _build_snippet(hit.text, q_lower) if hit else memory.content
        ) or memory.content
        out.append(
            {
                "type": "memory",
                "match_field": hit.field if hit else "content",
                "snippet": snippet,
                "id": memory.id,
                "kind": memory.kind,
                "content": memory.content,
                "source_excerpt": memory.source_excerpt,
                "created_at": _isoformat(memory.created_at),
                "conversation": (
                    {"id": conversation.id, "title": conversation.title}
                    if conversation is not None
                    else None
                ),
                "project": {"id": project.id, "name": project.name},
            }
        )
    return out


def _search_conversations(user: User, query: str, *, limit: int) -> list[dict]:
    pattern = f"%{_escape_like(query)}%"
    stmt = (
        select(Conversation, Project)
        .join(Project, Conversation.project_id == Project.id)
        .where(
            Conversation.user_id == user.id,
            or_(
                func.lower(Conversation.title).like(
                    func.lower(pattern), escape="\\"
                ),
                func.lower(Conversation.summary).like(
                    func.lower(pattern), escape="\\"
                ),
            ),
        )
        .order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
        .limit(limit)
    )
    rows = db.session.execute(stmt).all()
    out: list[dict] = []
    q_lower = query.lower()
    for conversation, project in rows:
        hit = _pick_first_hit(
            q_lower,
            [("title", conversation.title), ("summary", conversation.summary)],
        )
        snippet = _build_snippet(hit.text, q_lower) if hit else None
        out.append(
            {
                "type": "conversation",
                "match_field": hit.field if hit else "title",
                "snippet": snippet,
                "id": conversation.id,
                "title": conversation.title,
                "summary": conversation.summary,
                "model": conversation.model,
                "last_message_at": _isoformat(conversation.last_message_at),
                "summarized_at": _isoformat(conversation.summarized_at),
                "message_count": conversation.messages.count(),
                "project": {"id": project.id, "name": project.name},
            }
        )
    return out


def _isoformat(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        # All our DB columns are timezone-aware UTC; defensive fallback.
        return value.isoformat()
    return value.isoformat()


def search(
    user: User,
    raw_query: str | None,
    *,
    types: Iterable[str] | str | None = None,
    limit: int | str | None = None,
) -> dict:
    query = _normalize_query(raw_query)
    chosen_types = _normalize_types(types)
    capped_limit = _normalize_limit(limit)

    results: dict[str, list[dict]] = {
        "messages": [],
        "memories": [],
        "conversations": [],
    }
    if "messages" in chosen_types:
        results["messages"] = _search_messages(user, query, limit=capped_limit)
    if "memories" in chosen_types:
        results["memories"] = _search_memories(user, query, limit=capped_limit)
    if "conversations" in chosen_types:
        results["conversations"] = _search_conversations(
            user, query, limit=capped_limit
        )

    totals = {bucket: len(rows) for bucket, rows in results.items()}
    return {
        "query": query,
        "types": list(chosen_types),
        "limit": capped_limit,
        "results": results,
        "totals": totals,
    }


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_QUERY_LEN",
    "SearchError",
    "VALID_TYPES",
    "search",
]
