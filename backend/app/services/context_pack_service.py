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

from sqlalchemy import select

from app.extensions import db
from app.models import ContextPack, Memory, Project, User
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
INSTRUCTIONS_MAX = 1_000
BODY_MAX = 12_000
MEMORY_CONTENT_LIMIT = 600
MEMORIES_PER_PACK = 200
MAX_LIST_LIMIT = 100


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
    title: str | None = None,
    body: str | None = None,
    title_provided: bool = False,
    body_provided: bool = False,
) -> ContextPack:
    pack = get_for_user(user, pack_id)

    if title_provided:
        cleaned = (title or "").strip()
        if not cleaned:
            raise ContextPackError(
                "validation_error",
                "Title cannot be empty.",
            )
        pack.title = _clamp(cleaned, TITLE_MAX)

    if body_provided:
        new_body = body if isinstance(body, str) else ""
        if len(new_body) > BODY_MAX:
            raise ContextPackError(
                "validation_error",
                f"Body must be at most {BODY_MAX} characters.",
            )
        pack.body = new_body

    db.session.add(pack)
    db.session.commit()
    db.session.refresh(pack)
    return pack


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
    "BODY_MAX",
    "ContextPackError",
    "INSTRUCTIONS_MAX",
    "MAX_LIST_LIMIT",
    "MEMORIES_PER_PACK",
    "TITLE_MAX",
    "count_for_user",
    "delete_pack",
    "generate",
    "get_for_user",
    "list_for_project",
    "list_recent_for_user",
    "update_pack",
]
