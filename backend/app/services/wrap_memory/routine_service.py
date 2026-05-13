"""Routine Wrap — DB-backed service layer (Phase 5).

Wraps :mod:`wrap_memory.routine` (pure) and
:class:`app.models.routine_wrap_config.RoutineWrapConfig` (DB row)
into a small set of operations the HTTP routes call directly:

* :func:`load_or_default` — read config, return defaults when no row.
* :func:`save_config` — upsert from a raw JSON payload.
* :func:`mark_run` — set ``last_run_at`` after a successful save.
* :func:`mark_dismissed` — set ``dismissed_at`` (no cadence reset).
* :func:`compute_status` — combined "is due + has new activity" probe
  used by the frontend banner.
* :func:`build_routine_request` — assemble a :class:`WrapRequest` for
  the Routine draft endpoint, applying scope-based message filtering.

This module touches the DB and is the only place where SQLAlchemy
sessions interact with routine configs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.extensions import db
from app.models import (
    Conversation,
    Message,
    Project,
    RoutineWrapConfig as RoutineWrapConfigModel,
    User,
)

from .routine import (
    AUTO_SAVE_ALLOWED,
    DEFAULT_DAY_OF_WEEK,
    DEFAULT_FREQUENCY,
    DEFAULT_ROUTINE_MODEL,
    DEFAULT_SCOPE,
    REVIEW_REQUIRED,
    RoutineDayOfWeek,
    RoutineFrequency,
    RoutineModel,
    RoutineScope,
    RoutineWrapConfig,
    coerce_invariants,
    is_routine_wrap_due,
    resolve_routine_model,
)
from .service import WrapServiceError, build_request_from_conversation
from .settings import DEFAULT_FILTERS
from .types import WrapMessage, WrapMode, WrapRequest


# ---------------------------------------------------------------------------
# Row ↔ dataclass.


def _row_to_config(row: RoutineWrapConfigModel) -> RoutineWrapConfig:
    """Convert a DB row to the pure dataclass. Invariants are re-clamped."""
    return coerce_invariants(
        RoutineWrapConfig(
            enabled=bool(row.enabled),
            frequency=RoutineFrequency(row.frequency),
            day_of_week=RoutineDayOfWeek(row.day_of_week),
            model=RoutineModel(row.model_choice),
            scope=RoutineScope(row.scope),
            review_required=bool(row.review_required),
            auto_save=bool(row.auto_save),
            last_run_at=row.last_run_at,
            dismissed_at=row.dismissed_at,
        )
    )


def _get_row(user: User, project: Project) -> Optional[RoutineWrapConfigModel]:
    return RoutineWrapConfigModel.query.filter_by(
        user_id=user.id, project_id=project.id
    ).first()


def _assert_owns_project(user: User, project: Project) -> None:
    if project.user_id != user.id:
        raise WrapServiceError(
            "not_found", "Project not found.", status=404
        )


# ---------------------------------------------------------------------------
# Public service API.


def load_or_default(user: User, project: Project) -> RoutineWrapConfig:
    """Return the project's routine config — defaults when no row.

    The default config has ``enabled=False`` so a fresh project
    never surprises the user with a banner. Defaults still come
    with sensible cadence/model/scope picks so the settings dialog
    has something pre-filled.
    """
    _assert_owns_project(user, project)

    row = _get_row(user, project)
    if row is None:
        return RoutineWrapConfig.default()
    return _row_to_config(row)


def save_config(user: User, project: Project, payload: dict) -> RoutineWrapConfig:
    """Validate + upsert the routine config from a wire payload.

    Unknown enum values become :class:`WrapServiceError` so the route
    layer can return a 400 with a useful message. ``review_required``
    and ``auto_save`` are always coerced to the Phase 5 invariants —
    a clever caller can't sneak ``auto_save=true`` past the API.

    ``last_run_at`` and ``dismissed_at`` are not writable via this
    endpoint (they're owned by :func:`mark_run` / :func:`mark_dismissed`).
    """
    _assert_owns_project(user, project)

    if not isinstance(payload, dict):
        raise WrapServiceError(
            "validation_error", "Request body must be JSON.", status=400
        )

    enabled = bool(payload.get("enabled", False))
    frequency = _parse_enum(
        payload.get("frequency", DEFAULT_FREQUENCY.value),
        RoutineFrequency,
        "frequency",
    )
    day_of_week = _parse_enum(
        payload.get("dayOfWeek", DEFAULT_DAY_OF_WEEK.value),
        RoutineDayOfWeek,
        "dayOfWeek",
    )
    model_choice = _parse_enum(
        payload.get("model", DEFAULT_ROUTINE_MODEL.value),
        RoutineModel,
        "model",
    )
    scope = _parse_enum(
        payload.get("scope", DEFAULT_SCOPE.value), RoutineScope, "scope"
    )

    row = _get_row(user, project)
    if row is None:
        row = RoutineWrapConfigModel(
            user_id=user.id,
            project_id=project.id,
        )
        db.session.add(row)

    row.enabled = enabled
    row.frequency = frequency.value
    row.day_of_week = day_of_week.value
    row.model_choice = model_choice.value
    row.scope = scope.value
    row.review_required = REVIEW_REQUIRED
    row.auto_save = AUTO_SAVE_ALLOWED
    db.session.commit()

    return _row_to_config(row)


def mark_run(
    user: User, project: Project, *, when: datetime | None = None
) -> RoutineWrapConfig:
    """Stamp ``last_run_at = when`` after a successful Routine save.

    Also clears ``dismissed_at`` — once the user actually wraps,
    the "I dismissed it 2 hours ago" mute is no longer relevant.
    """
    _assert_owns_project(user, project)
    row = _get_row(user, project)
    if row is None:
        # Fall through: create a row with default settings so the
        # cadence math has something to anchor on. Enabled stays
        # whatever default is (False today) — Routine save can
        # happen via the manual menu too.
        row = RoutineWrapConfigModel(
            user_id=user.id,
            project_id=project.id,
            enabled=False,
            frequency=DEFAULT_FREQUENCY.value,
            day_of_week=DEFAULT_DAY_OF_WEEK.value,
            model_choice=DEFAULT_ROUTINE_MODEL.value,
            scope=DEFAULT_SCOPE.value,
            review_required=REVIEW_REQUIRED,
            auto_save=AUTO_SAVE_ALLOWED,
        )
        db.session.add(row)
    row.last_run_at = when or datetime.now(timezone.utc)
    row.dismissed_at = None
    db.session.commit()
    return _row_to_config(row)


def mark_dismissed(
    user: User, project: Project, *, when: datetime | None = None
) -> RoutineWrapConfig:
    """Stamp ``dismissed_at = when`` without touching ``last_run_at``.

    Strategy: keep the cadence anchor intact so the user doesn't
    miss a cycle, but mute the reminder for
    :data:`wrap_memory.routine.DISMISS_QUIET_PERIOD` (24h). This
    avoids both "dismissing skips the week" and "every page reload
    re-pops the banner".
    """
    _assert_owns_project(user, project)
    row = _get_row(user, project)
    if row is None:
        # Dismissing without any config row means the banner can't
        # have been firing — silently no-op. Returning the default
        # config keeps the route handler's shape stable.
        return RoutineWrapConfig.default()
    row.dismissed_at = when or datetime.now(timezone.utc)
    db.session.commit()
    return _row_to_config(row)


# ---------------------------------------------------------------------------
# Status probe used by the frontend banner.


def compute_status(
    user: User,
    project: Project,
    *,
    now: datetime | None = None,
) -> dict:
    """Return a JSON-ready snapshot for the frontend banner.

    Combines :func:`is_routine_wrap_due` with a "has the project
    actually moved since ``last_run_at``" check so we don't bother
    the user when there's literally nothing new to wrap. The latter
    is intentionally cheap — one ``EXISTS`` query against messages.
    """
    _assert_owns_project(user, project)
    now = now or datetime.now(timezone.utc)

    config = load_or_default(user, project)
    due = is_routine_wrap_due(config, now)
    has_activity = _has_new_activity(user, project, config, now=now) if due else False
    should_prompt = due and has_activity

    return {
        "config": config.to_dict(),
        "now": now.isoformat(),
        "isDue": due,
        "hasNewActivity": has_activity,
        "shouldPrompt": should_prompt,
    }


def _has_new_activity(
    user: User,
    project: Project,
    config: RoutineWrapConfig,
    *,
    now: datetime,
) -> bool:
    """Cheap probe: did anything happen since the last wrap?

    Definition follows the configured scope:

    * ``since-last-wrap``  — any user/assistant message after
      ``last_run_at``. If ``last_run_at`` is unset, *any* message
      counts (the project has never been wrapped).
    * ``last-7-days``      — any user/assistant message in the
      trailing 7-day window from ``now``.

    Returns False when the project has zero qualifying messages,
    which keeps the banner quiet on dormant projects.
    """
    base = (
        Message.query.join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user.id)
        .filter(Conversation.project_id == project.id)
        .filter(Message.role.in_(("user", "assistant")))
    )

    if config.scope is RoutineScope.LAST_7_DAYS:
        cutoff = now - timedelta(days=7)
        base = base.filter(Message.created_at >= cutoff)
    else:  # SINCE_LAST_WRAP
        if config.last_run_at is not None:
            base = base.filter(Message.created_at > config.last_run_at)

    return db.session.query(base.exists()).scalar() is True


# ---------------------------------------------------------------------------
# Building the WrapRequest for the Routine draft endpoint.


def build_routine_request(
    *,
    user: User,
    project: Project,
    conversation: Conversation,
    config: RoutineWrapConfig | None = None,
    now: datetime | None = None,
) -> WrapRequest:
    """Compose a Routine :class:`WrapRequest` for the LLM call.

    Routine reuses :func:`build_request_from_conversation` but then
    *narrows* the message list based on the configured scope. Phase 5
    keeps wraps conversation-scoped (matches Quick / Advanced), so the
    scope acts as an additional time filter on top of the conversation's
    own transcript.
    """
    cfg = config or load_or_default(user, project)
    now = now or datetime.now(timezone.utc)

    request = build_request_from_conversation(
        user=user,
        project=project,
        conversation=conversation,
        mode=WrapMode.ROUTINE,
        model=resolve_routine_model(cfg.model),
        filters=DEFAULT_FILTERS,
        user_instruction=None,
    )

    request.messages = _narrow_messages_by_scope(request.messages, cfg, now=now)
    if not request.messages:
        raise WrapServiceError(
            "transcript_too_short",
            "No new messages in the routine scope yet.",
            status=400,
        )
    return request


def _narrow_messages_by_scope(
    messages: list[WrapMessage],
    config: RoutineWrapConfig,
    *,
    now: datetime,
) -> list[WrapMessage]:
    """Filter ``messages`` to only those inside the routine scope window.

    Messages without a ``created_at`` (legacy rows) are kept on the
    ``since-last-wrap`` path (we can't prove they're old) but dropped
    on ``last-7-days`` (we can't prove they're recent). This pair of
    defaults errs on the side of preserving content for routine
    drafts that follow a never-wrapped project.
    """
    if config.scope is RoutineScope.LAST_7_DAYS:
        cutoff = now - timedelta(days=7)
        return [m for m in messages if _is_after(m.created_at, cutoff)]

    # SINCE_LAST_WRAP
    if config.last_run_at is None:
        return list(messages)
    return [m for m in messages if _is_after(m.created_at, config.last_run_at)]


def _is_after(ts: datetime | None, cutoff: datetime) -> bool:
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return ts > cutoff


# ---------------------------------------------------------------------------
# Helpers.


def _parse_enum(value, enum_cls, field_name: str):
    try:
        return enum_cls(value)
    except (ValueError, TypeError) as exc:
        allowed = ", ".join(repr(e.value) for e in enum_cls)
        raise WrapServiceError(
            "validation_error",
            f"{field_name}: unknown value {value!r}; expected one of {allowed}.",
            status=400,
        ) from exc


__all__ = [
    "build_routine_request",
    "compute_status",
    "load_or_default",
    "mark_dismissed",
    "mark_run",
    "save_config",
]
