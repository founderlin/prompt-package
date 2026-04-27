"""Memory domain service.

Wrapping up a conversation works in three steps:

1. Build a transcript from the user/assistant messages already on the
   conversation.
2. Ask OpenRouter to return a JSON document with a 1-2 sentence
   ``summary`` plus a flat list of ``memories`` (each with a ``kind``
   from :data:`app.models.MEMORY_KINDS`).
3. Persist the summary on the conversation and replace any existing
   memories for that conversation with the freshly extracted ones.

Re-running ``summarize_conversation`` on the same conversation is safe;
it overwrites the previous summary/memories instead of duplicating them.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select

from app.extensions import db
from app.models import MEMORY_KINDS, Conversation, Memory, Message, User
from app.services.chat_service import (
    ChatError,
    DEFAULT_MODEL,
    get_conversation_for_user,
)
from app.providers import get_provider, normalize_provider
from app.services.credentials_service import (
    CredentialsError,
    first_configured_provider,
    get_decrypted_key_for,
)
from app.services.llm_service import LLMError, chat_completion
from app.services.project_service import ProjectError, get_for_user as get_project_for_user

# Back-compat alias so any out-of-tree callers / tests that still
# reference ``OpenRouterError`` keep working.
OpenRouterError = LLMError

CONTENT_MAX = 1_000
EXCERPT_MAX = 600
MEMORIES_PER_RUN = 20
TRANSCRIPT_CHAR_LIMIT = 24_000  # rough proxy for prompt size; per-message clamp below
MESSAGE_CHAR_LIMIT = 4_000


SYSTEM_PROMPT = """You are an assistant that distills *reusable project memory* from chat transcripts.

You are given a transcript between a user and an assistant. Read it and produce a JSON object describing what should be remembered for future sessions on the same project.

Output schema (and ONLY this schema):

{
  "summary": "1-2 sentences in plain English describing what was discussed and concluded.",
  "memories": [
    {
      "kind": "fact" | "decision" | "todo" | "question",
      "content": "A short standalone statement that makes sense without the transcript.",
      "source_excerpt": "Optional 1-2 line direct quote from the transcript that supports this memory."
    }
  ]
}

Rules:
- Only include memories worth carrying into future conversations. Skip pleasantries, retries, and meta-talk about the assistant itself.
- Use "decision" when the user committed to an approach, choice, or value.
- Use "fact" for stable information about the project, system, constraints, or environment.
- Use "todo" for things still to be done, ideally action-oriented.
- Use "question" for open questions the user explicitly wanted to revisit.
- Prefer short, specific statements over long ones.
- Output VALID JSON only. Do not wrap in markdown fences. Do not add commentary before or after the JSON.
"""


class MemoryError(Exception):
    """Predictable, user-facing memory failures."""

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


def _build_transcript(messages: Iterable[Message]) -> str:
    parts: list[str] = []
    total = 0
    for msg in messages:
        if msg.role not in ("user", "assistant"):
            continue
        body = (msg.content or "").strip()
        if not body:
            continue
        body = _clamp(body, MESSAGE_CHAR_LIMIT)
        speaker = "User" if msg.role == "user" else "Assistant"
        block = f"{speaker}:\n{body}"
        total += len(block)
        if total > TRANSCRIPT_CHAR_LIMIT and parts:
            # Keep the earliest turns + drop the overflow tail to control prompt size.
            break
        parts.append(block)
    return "\n\n".join(parts)


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        # ```json\n{...}\n``` or ```\n{...}\n```
        stripped = re.sub(r"^```[a-zA-Z0-9]*\s*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    return stripped


def parse_extraction(raw: str) -> tuple[str, list[dict]]:
    """Parse the model's reply into ``(summary, memories)``.

    Tolerates Markdown code fences and stray prose. Raises
    :class:`MemoryError` if no valid JSON object can be recovered.
    """
    if not raw or not raw.strip():
        raise MemoryError(
            "summarization_failed",
            "The model returned an empty response.",
        )

    candidate = _strip_code_fences(raw)
    data: dict | None = None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(candidate)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        raise MemoryError(
            "summarization_failed",
            "The model did not return JSON we can parse.",
        )

    summary_raw = data.get("summary")
    summary = ""
    if isinstance(summary_raw, str):
        summary = summary_raw.strip()
    summary = _clamp(summary, CONTENT_MAX)

    raw_items = data.get("memories")
    if not isinstance(raw_items, list):
        raw_items = []

    memories: list[dict] = []
    for item in raw_items[:MEMORIES_PER_RUN]:
        if not isinstance(item, dict):
            continue
        kind = (item.get("kind") or "fact").strip().lower()
        if kind not in MEMORY_KINDS:
            kind = "fact"
        content_raw = item.get("content")
        if not isinstance(content_raw, str):
            continue
        content = content_raw.strip()
        if not content:
            continue
        excerpt_raw = item.get("source_excerpt")
        excerpt: str | None = None
        if isinstance(excerpt_raw, str) and excerpt_raw.strip():
            excerpt = _clamp(excerpt_raw.strip(), EXCERPT_MAX)
        memories.append(
            {
                "kind": kind,
                "content": _clamp(content, CONTENT_MAX),
                "source_excerpt": excerpt,
            }
        )

    return summary, memories


def _replace_conversation_memories(
    *, user_id: int, project_id: int, conversation_id: int, items: list[dict]
) -> list[Memory]:
    """Drop any prior memories for this conversation, write the fresh batch."""
    db.session.query(Memory).filter(
        Memory.conversation_id == conversation_id
    ).delete(synchronize_session=False)

    created: list[Memory] = []
    for item in items:
        mem = Memory(
            user_id=user_id,
            project_id=project_id,
            conversation_id=conversation_id,
            kind=item["kind"],
            content=item["content"],
            source_excerpt=item.get("source_excerpt"),
        )
        db.session.add(mem)
        created.append(mem)
    return created


def summarize_conversation(
    user: User,
    conversation_id: int,
    *,
    model: str | None = None,
) -> tuple[Conversation, list[Memory]]:
    """Run the wrap-up flow on a conversation and persist results.

    Returns the refreshed conversation plus the freshly persisted memories.
    """
    convo = get_conversation_for_user(user, conversation_id)

    messages = list(convo.messages.order_by(Message.id.asc()).all())
    real_messages = [m for m in messages if m.role in ("user", "assistant")]
    if len(real_messages) < 2:
        raise MemoryError(
            "transcript_too_short",
            "Send at least one user/assistant exchange before wrapping up.",
        )

    summary_provider = (
        normalize_provider(convo.provider)
        if convo.provider
        else (first_configured_provider(user) or "openrouter")
    )

    try:
        api_key = get_decrypted_key_for(user, summary_provider)
    except CredentialsError as err:
        raise MemoryError(err.code, err.message, status=err.status) from err
    if not api_key:
        raise MemoryError(
            "no_api_key",
            "Add an LLM API key in Settings (OpenRouter, DeepSeek, or OpenAI) "
            "before summarizing.",
        )

    transcript = _build_transcript(real_messages)
    if not transcript:
        raise MemoryError(
            "transcript_too_short",
            "Conversation does not contain any text to summarize.",
        )

    # Pick a model: prefer the conversation's own (it's already known to
    # work on its provider) but fall back to the provider's cheap default.
    cfg = get_provider(summary_provider)
    chosen_model = (model or convo.model or cfg.summary_model).strip() or cfg.summary_model

    payload = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Project transcript follows. Project name: {convo.project.name!r}. "
                f"Conversation title: {convo.title or 'Untitled'!r}.\n\n"
                "===== TRANSCRIPT =====\n"
                f"{transcript}\n"
                "===== END TRANSCRIPT ====="
            ),
        },
    ]

    try:
        completion = chat_completion(
            api_key,
            model=chosen_model,
            messages=payload,
            provider=summary_provider,
            temperature=0.2,
            extra={"response_format": {"type": "json_object"}},
        )
    except LLMError as err:
        # Convert to MemoryError so the route layer can format consistently.
        raise MemoryError(err.code, err.message, status=err.status) from err

    summary, items = parse_extraction(completion.content)

    convo.summary = summary or None
    convo.summarized_at = _utcnow()
    db.session.add(convo)

    created = _replace_conversation_memories(
        user_id=user.id,
        project_id=convo.project_id,
        conversation_id=convo.id,
        items=items,
    )
    db.session.commit()
    db.session.refresh(convo)
    return convo, created


def list_for_project(user: User, project_id: int) -> list[Memory]:
    try:
        project = get_project_for_user(user, project_id)
    except ProjectError as err:
        raise MemoryError(err.code, err.message, status=err.status) from err

    stmt = (
        select(Memory)
        .where(Memory.project_id == project.id, Memory.user_id == user.id)
        .order_by(Memory.created_at.desc(), Memory.id.desc())
    )
    return list(db.session.scalars(stmt).all())


def list_for_conversation(user: User, conversation_id: int) -> list[Memory]:
    convo = get_conversation_for_user(user, conversation_id)
    stmt = (
        select(Memory)
        .where(Memory.conversation_id == convo.id, Memory.user_id == user.id)
        .order_by(Memory.created_at.desc(), Memory.id.desc())
    )
    return list(db.session.scalars(stmt).all())


def get_for_user(user: User, memory_id: int) -> Memory:
    mem = db.session.get(Memory, memory_id)
    if mem is None or mem.user_id != user.id:
        raise MemoryError("not_found", "Memory not found.", status=404)
    return mem


def delete_memory(user: User, memory_id: int) -> None:
    mem = get_for_user(user, memory_id)
    db.session.delete(mem)
    db.session.commit()


# Re-export ChatError for tests/imports that want to compare error semantics.
__all__ = [
    "CONTENT_MAX",
    "ChatError",
    "MEMORIES_PER_RUN",
    "MemoryError",
    "SYSTEM_PROMPT",
    "delete_memory",
    "get_for_user",
    "list_for_conversation",
    "list_for_project",
    "parse_extraction",
    "summarize_conversation",
]
