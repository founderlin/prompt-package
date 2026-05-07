"""Wrap Up service.

High-level orchestration for conversation-level and project-level
"Wrap Up". Given a user + a target (conversation or project) + user
options, it:

1. Validates permissions / resolves the target.
2. Collects the underlying user+assistant messages.
3. Filters empty/system noise.
4. Delegates to :mod:`app.services.context_pack_generator` to produce
   a structured GenerationResult (summary / keywords / description /
   body).
5. Persists a new :class:`~app.models.ContextPack` row plus one or
   more :class:`~app.models.ContextPackSource` rows recording
   provenance.
6. Mirrors progress into a :class:`~app.models.ContextPackJob` row so
   the frontend can poll status and so we can swap execution for a
   real queue later without breaking the API.

The MVP runs synchronously inside the HTTP request — each stage
transition commits before the next begins so a failure always leaves
a useful job row behind. When we move to background execution, the
only change is where :func:`_execute` gets called from (a worker
instead of the request thread).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select

from app.extensions import db
from app.models import (
    ContextPack,
    ContextPackJob,
    ContextPackSource,
    Conversation,
    JOB_STAGE_ANALYZING,
    JOB_STAGE_COLLECTING,
    JOB_STAGE_COMPLETED,
    JOB_STAGE_CREATING,
    JOB_STAGE_FAILED,
    JOB_STAGE_PREPARING,
    JOB_STAGE_SUMMARIZING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_RUNNING,
    Message,
    SOURCE_TYPE_CONVERSATION,
    SOURCE_TYPE_MESSAGE,
    SOURCE_TYPE_PROJECT,
    User,
)
from app.services.chat_service import (
    ChatError,
    get_conversation_for_user,
)
from app.services.context_pack_generator import (
    BODY_HARD_CEILING,
    ConversationSource,
    DESCRIPTION_MAX,
    GOAL_MAX,
    GenerationOptions,
    GenerationResult,
    GeneratorError,
    SUMMARY_MAX_LENGTH_DEFAULT_CONVO,
    SUMMARY_MAX_LENGTH_DEFAULT_PROJECT,
    TITLE_MAX,
    generate as run_generator,
)
from app.services.project_service import (
    ProjectError,
    get_for_user as get_project_for_user,
)


# ---------------------------------------------------------------------------
# Errors + shared types.


class WrapUpError(Exception):
    """Predictable, user-facing wrap-up failures."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class WrapUpOptions:
    """Options accepted from the request payload, normalized."""

    title: str | None = None
    goal: str | None = None
    include_raw_references: bool = False
    max_summary_length: int = SUMMARY_MAX_LENGTH_DEFAULT_PROJECT
    # Project-level only: caller-provided subset of conversation ids.
    conversation_ids: list[int] | None = None


# Scope string stored on the job row.
SCOPE_CONVERSATION = "conversation"
SCOPE_PROJECT = "project"


# ---------------------------------------------------------------------------
# Input normalization.


def _normalize_options(
    raw: dict | None,
    *,
    default_max_summary: int,
    accept_conversation_ids: bool,
) -> WrapUpOptions:
    data = raw or {}
    if not isinstance(data, dict):
        raise WrapUpError("validation_error", "Request body must be a JSON object.")

    title = data.get("title")
    if title is not None:
        if not isinstance(title, str):
            raise WrapUpError("validation_error", "'title' must be a string.")
        title = title.strip() or None
        if title and len(title) > TITLE_MAX:
            raise WrapUpError(
                "validation_error",
                f"Title must be at most {TITLE_MAX} characters.",
            )

    goal = data.get("goal")
    if goal is not None:
        if not isinstance(goal, str):
            raise WrapUpError("validation_error", "'goal' must be a string.")
        goal = goal.strip() or None
        if goal and len(goal) > GOAL_MAX:
            raise WrapUpError(
                "validation_error",
                f"Goal must be at most {GOAL_MAX} characters.",
            )

    opts = data.get("options") or {}
    if not isinstance(opts, dict):
        raise WrapUpError("validation_error", "'options' must be an object.")

    include_raw_references = bool(opts.get("includeRawReferences", False))

    raw_max = opts.get("maxSummaryLength", default_max_summary)
    try:
        max_summary = int(raw_max)
    except (TypeError, ValueError):
        raise WrapUpError(
            "validation_error",
            "'options.maxSummaryLength' must be an integer.",
        )
    if max_summary < 200:
        max_summary = 200

    conversation_ids: list[int] | None = None
    if accept_conversation_ids:
        raw_ids = data.get("conversationIds")
        if raw_ids is not None:
            if not isinstance(raw_ids, list):
                raise WrapUpError(
                    "validation_error",
                    "'conversationIds' must be a list of integers.",
                )
            cleaned: list[int] = []
            for item in raw_ids:
                try:
                    cleaned.append(int(item))
                except (TypeError, ValueError):
                    raise WrapUpError(
                        "validation_error",
                        "'conversationIds' must contain integers only.",
                    )
            # Dedupe but preserve order.
            seen: set[int] = set()
            ordered: list[int] = []
            for cid in cleaned:
                if cid in seen:
                    continue
                seen.add(cid)
                ordered.append(cid)
            conversation_ids = ordered

    return WrapUpOptions(
        title=title,
        goal=goal,
        include_raw_references=include_raw_references,
        max_summary_length=max_summary,
        conversation_ids=conversation_ids,
    )


# ---------------------------------------------------------------------------
# Public entry points.


def wrap_up_conversation(
    user: User,
    conversation_id: int,
    *,
    payload: dict | None = None,
) -> tuple[ContextPack, ContextPackJob]:
    """Wrap up a single conversation into a Context Pack.

    Returns ``(pack, job)``. The job row will be ``completed`` (or
    ``failed`` — in which case this raises before returning).
    """
    options = _normalize_options(
        payload,
        default_max_summary=SUMMARY_MAX_LENGTH_DEFAULT_CONVO,
        accept_conversation_ids=False,
    )

    # Resolve + authorize target early so validation errors never spawn
    # a job row that's immediately orphaned.
    try:
        convo = get_conversation_for_user(user, conversation_id)
    except ChatError as err:
        raise WrapUpError(err.code, err.message, status=err.status) from err

    job = _create_job(
        user=user,
        scope=SCOPE_CONVERSATION,
        project_id=convo.project_id,
        conversation_id=convo.id,
        options=options,
    )
    pack = _execute_with_job(
        job,
        lambda: _run_conversation(user, convo, options, job),
    )
    return pack, job


def wrap_up_project(
    user: User,
    project_id: int,
    *,
    payload: dict | None = None,
) -> tuple[ContextPack, ContextPackJob]:
    """Wrap up a whole project (or a caller-chosen subset of its conversations)."""
    options = _normalize_options(
        payload,
        default_max_summary=SUMMARY_MAX_LENGTH_DEFAULT_PROJECT,
        accept_conversation_ids=True,
    )

    try:
        project = get_project_for_user(user, project_id)
    except ProjectError as err:
        raise WrapUpError(err.code, err.message, status=err.status) from err

    job = _create_job(
        user=user,
        scope=SCOPE_PROJECT,
        project_id=project.id,
        conversation_id=None,
        options=options,
    )
    pack = _execute_with_job(
        job,
        lambda: _run_project(user, project.id, options, job),
    )
    return pack, job


def get_job_for_user(user: User, job_id: int) -> ContextPackJob:
    job = db.session.get(ContextPackJob, job_id)
    if job is None or job.user_id != user.id:
        raise WrapUpError("not_found", "Wrap-up job not found.", status=404)
    return job


# ---------------------------------------------------------------------------
# Job lifecycle helpers.


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _create_job(
    *,
    user: User,
    scope: str,
    project_id: int | None,
    conversation_id: int | None,
    options: WrapUpOptions,
) -> ContextPackJob:
    job = ContextPackJob(
        user_id=user.id,
        scope=scope,
        project_id=project_id,
        conversation_id=conversation_id,
        status=JOB_STATUS_RUNNING,
        stage=JOB_STAGE_PREPARING,
        progress=5,
    )
    job.set_params(
        {
            "title": options.title,
            "goal": options.goal,
            "include_raw_references": options.include_raw_references,
            "max_summary_length": options.max_summary_length,
            "conversation_ids": options.conversation_ids,
        }
    )
    db.session.add(job)
    db.session.commit()
    db.session.refresh(job)
    return job


def _advance(job: ContextPackJob, stage: str, progress: int) -> None:
    job.stage = stage
    job.progress = max(0, min(100, progress))
    db.session.add(job)
    db.session.commit()


def _finish_success(job: ContextPackJob, pack: ContextPack) -> None:
    job.status = JOB_STATUS_COMPLETED
    job.stage = JOB_STAGE_COMPLETED
    job.progress = 100
    job.context_pack_id = pack.id
    job.completed_at = _utcnow()
    db.session.add(job)
    db.session.commit()


def _finish_failure(job: ContextPackJob, code: str, message: str) -> None:
    job.status = JOB_STATUS_FAILED
    job.stage = JOB_STAGE_FAILED
    job.error_code = code
    job.error_message = message
    job.completed_at = _utcnow()
    db.session.add(job)
    db.session.commit()


def _execute_with_job(job: ContextPackJob, runner) -> ContextPack:
    """Run ``runner`` inside the job lifecycle, converting errors to WrapUpError.

    The runner is expected to return the newly-created ContextPack.
    """
    try:
        pack = runner()
    except WrapUpError as err:
        _finish_failure(job, err.code, err.message)
        raise
    except GeneratorError as err:
        _finish_failure(job, err.code, err.message)
        raise WrapUpError(err.code, err.message, status=err.status) from err
    except Exception as err:  # pragma: no cover - last-ditch safety net
        _finish_failure(job, "internal_server_error", str(err) or "Unexpected failure.")
        raise WrapUpError(
            "internal_server_error",
            "Wrap-up failed unexpectedly. Please try again.",
            status=500,
        ) from err
    _finish_success(job, pack)
    return pack


# ---------------------------------------------------------------------------
# Execution paths.


def _run_conversation(
    user: User,
    convo: Conversation,
    options: WrapUpOptions,
    job: ContextPackJob,
) -> ContextPack:
    _advance(job, JOB_STAGE_COLLECTING, 15)

    messages = _collect_messages(convo)
    if len(messages) < 1:
        raise WrapUpError(
            "transcript_too_short",
            "This conversation has no user/assistant messages to wrap up.",
        )

    sources = [ConversationSource(conversation=convo, messages=messages)]

    _advance(job, JOB_STAGE_ANALYZING, 35)

    gen_opts = GenerationOptions(
        max_summary_length=options.max_summary_length,
        use_llm=True,
        title=options.title,
        goal=options.goal,
    )

    _advance(job, JOB_STAGE_SUMMARIZING, 55)

    result = run_generator(
        user,
        sources,
        gen_opts,
        project_name=convo.project.name if convo.project else None,
        project_description=(convo.project.description if convo.project else None),
    )

    _advance(job, JOB_STAGE_CREATING, 85)

    pack = _persist_pack(
        user=user,
        project_id=convo.project_id,
        conversation_id=convo.id,
        source_type=SOURCE_TYPE_CONVERSATION,
        options=options,
        result=result,
        sources=sources,
    )
    return pack


def _run_project(
    user: User,
    project_id: int,
    options: WrapUpOptions,
    job: ContextPackJob,
) -> ContextPack:
    _advance(job, JOB_STAGE_COLLECTING, 15)

    conversations = _load_project_conversations(
        user=user,
        project_id=project_id,
        caller_ids=options.conversation_ids,
    )
    if not conversations:
        raise WrapUpError(
            "no_conversations",
            "No conversations with content were found for this project.",
        )

    sources: list[ConversationSource] = []
    for convo in conversations:
        msgs = _collect_messages(convo)
        if msgs:
            sources.append(ConversationSource(conversation=convo, messages=msgs))
    if not sources:
        raise WrapUpError(
            "no_conversations",
            "The selected conversations don't have any user/assistant messages yet.",
        )

    _advance(job, JOB_STAGE_ANALYZING, 35)

    # Re-derive project for metadata (already validated via get_project_for_user
    # in the public entry point — safe to fetch cheaply here).
    project = sources[0].conversation.project

    gen_opts = GenerationOptions(
        max_summary_length=options.max_summary_length,
        use_llm=True,
        title=options.title,
        goal=options.goal,
    )

    _advance(job, JOB_STAGE_SUMMARIZING, 60)

    result = run_generator(
        user,
        sources,
        gen_opts,
        project_name=project.name if project else None,
        project_description=(project.description if project else None),
    )

    _advance(job, JOB_STAGE_CREATING, 85)

    pack = _persist_pack(
        user=user,
        project_id=project_id,
        conversation_id=None,
        source_type=SOURCE_TYPE_PROJECT,
        options=options,
        result=result,
        sources=sources,
    )
    return pack


# ---------------------------------------------------------------------------
# Data helpers.


def _collect_messages(convo: Conversation) -> list[Message]:
    rows = list(convo.messages.order_by(Message.id.asc()).all())
    return [
        m
        for m in rows
        if m.role in ("user", "assistant") and (m.content or "").strip()
    ]


def _load_project_conversations(
    *,
    user: User,
    project_id: int,
    caller_ids: list[int] | None,
) -> list[Conversation]:
    base = (
        select(Conversation)
        .where(
            Conversation.user_id == user.id,
            Conversation.project_id == project_id,
        )
        .order_by(Conversation.created_at.asc(), Conversation.id.asc())
    )
    if caller_ids is not None:
        base = base.where(Conversation.id.in_(caller_ids))
    rows = list(db.session.scalars(base).all())
    if caller_ids is not None and not rows:
        raise WrapUpError(
            "no_conversations",
            "None of the provided conversationIds belong to this project.",
            status=404,
        )
    return rows


def _derive_default_title(
    *,
    project_name: str | None,
    conversation_title: str | None,
    source_type: str,
) -> str:
    stamp = _utcnow().strftime("%Y-%m-%d %H:%M")
    if source_type == SOURCE_TYPE_CONVERSATION:
        base = conversation_title or "Conversation"
        return _clip(f"{base} · Wrap Up ({stamp})", TITLE_MAX)
    base = project_name or "Project"
    return _clip(f"{base} · Wrap Up ({stamp})", TITLE_MAX)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _persist_pack(
    *,
    user: User,
    project_id: int,
    conversation_id: int | None,
    source_type: str,
    options: WrapUpOptions,
    result: GenerationResult,
    sources: list[ConversationSource],
) -> ContextPack:
    conversation_title = None
    project_name = None
    if sources:
        first = sources[0].conversation
        conversation_title = first.title
        if first.project:
            project_name = first.project.name

    title = options.title or _derive_default_title(
        project_name=project_name,
        conversation_title=conversation_title,
        source_type=source_type,
    )
    title = _clip(title.strip(), TITLE_MAX) or "Context Pack"

    description = result.description
    if not description and options.goal:
        description = _clip(options.goal.strip(), DESCRIPTION_MAX)

    pack = ContextPack(
        user_id=user.id,
        project_id=project_id,
        conversation_id=conversation_id,
        title=title,
        description=description,
        summary=result.summary,
        body=result.body[:BODY_HARD_CEILING],
        model=result.model,
        instructions=options.goal,  # reuse existing column for goal snapshot
        source_type=source_type,
        memory_count=0,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
    )
    pack.set_keywords(result.keywords)
    # Track the "memories" column as the list of source messages ids when
    # include_raw_references is on — keeps legacy UI code that reads
    # source_memory_ids usable even though these aren't strictly memories.
    message_ids: list[int] = []
    if options.include_raw_references:
        for src in sources:
            for m in src.messages:
                message_ids.append(m.id)
    pack.set_source_memory_ids(message_ids)

    db.session.add(pack)
    db.session.flush()  # need pack.id before writing source rows

    _write_sources(pack, sources, source_type, options)

    db.session.commit()
    db.session.refresh(pack)
    return pack


def _write_sources(
    pack: ContextPack,
    sources: list[ConversationSource],
    source_type: str,
    options: WrapUpOptions,
) -> None:
    # Always record the project row for project-scoped packs.
    if source_type == SOURCE_TYPE_PROJECT and pack.project_id:
        project_name = (
            sources[0].conversation.project.name
            if sources and sources[0].conversation.project is not None
            else None
        )
        project_source = ContextPackSource(
            context_pack_id=pack.id,
            source_type=SOURCE_TYPE_PROJECT,
            source_id=pack.project_id,
            project_id=pack.project_id,
            source_title=project_name,
        )
        project_source.set_metadata({"conversation_count": len(sources)})
        db.session.add(project_source)

    for src in sources:
        convo = src.conversation
        first_id = src.messages[0].id if src.messages else None
        last_id = src.messages[-1].id if src.messages else None
        meta = {
            "message_count": len(src.messages),
            "first_message_id": first_id,
            "last_message_id": last_id,
            "conversation_title": convo.title,
        }
        conv_source = ContextPackSource(
            context_pack_id=pack.id,
            source_type=SOURCE_TYPE_CONVERSATION,
            source_id=convo.id,
            # R-PACK-CORE: also populate the typed FKs + snapshot title.
            project_id=convo.project_id,
            conversation_id=convo.id,
            source_title=convo.title or "Untitled conversation",
        )
        conv_source.set_metadata(meta)
        db.session.add(conv_source)

        if options.include_raw_references:
            for m in src.messages:
                # Snapshot a short preview of the message as source_title
                # so the UI has something to show even if the message
                # is later deleted.
                excerpt = (m.content or "").strip().replace("\n", " ")
                if len(excerpt) > 80:
                    excerpt = excerpt[:79].rstrip() + "…"
                snapshot_title = f"{m.role}: {excerpt}" if excerpt else m.role
                msg_source = ContextPackSource(
                    context_pack_id=pack.id,
                    source_type=SOURCE_TYPE_MESSAGE,
                    source_id=m.id,
                    # R-PACK-CORE: conversation_id FK so message rows
                    # can still be filtered by conversation after the
                    # migration.
                    conversation_id=convo.id,
                    project_id=convo.project_id,
                    source_title=snapshot_title[:240] if snapshot_title else None,
                )
                msg_source.set_metadata(
                    {
                        "role": m.role,
                        "conversation_id": convo.id,
                    }
                )
                db.session.add(msg_source)


__all__ = [
    "SCOPE_CONVERSATION",
    "SCOPE_PROJECT",
    "WrapUpError",
    "WrapUpOptions",
    "get_job_for_user",
    "wrap_up_conversation",
    "wrap_up_project",
]
