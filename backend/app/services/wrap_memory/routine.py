"""Routine Wrap — Phase 5 pure types + due-date math.

The Routine Wrap feature schedules a *reminder* to wrap a project's
recent activity on a fixed cadence (weekly / biweekly / monthly).
Phase 5 is deliberately scoped down:

* No background scheduler — "due" is checked on demand (app boot,
  project page open) and we surface a banner the user must dismiss
  or click-through.
* Review is **always required**: when the user opts in, the routine
  draft must be inspected before saving. There is no silent
  auto-save path in this milestone.
* No file-splitting. No memory health score.

This module is intentionally pure stdlib (datetime + enum + dataclass)
so it imports cleanly from any layer — same convention as
:mod:`wrap_memory.types`. The DB-bound side lives in
:mod:`wrap_memory.routine_service`; the HTTP side in
:mod:`app.routes.wraps`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from .types import WrapModel


# ---------------------------------------------------------------------------
# Enums.


class RoutineFrequency(str, Enum):
    """How often a routine wrap fires."""

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class RoutineDayOfWeek(str, Enum):
    """Preferred day of the week for the reminder to surface.

    We use this only for *cosmetic* timing today — Phase 5 doesn't
    actually wait for the exact day, just for the cadence interval
    to elapse. The field is still persisted so a future scheduler
    can honor it without a schema change.
    """

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class RoutineModel(str, Enum):
    """Which model the routine reminder will use when the user clicks Review.

    ``USE_GLOBAL_DEFAULT`` defers to :data:`wrap_memory.settings.DEFAULT_MODEL`.
    The other three mirror :class:`WrapModel` exactly so the UI can
    surface one consolidated dropdown.
    """

    USE_GLOBAL_DEFAULT = "use-global-default"
    DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
    GEMINI_31_FLASH = "gemini-3.1-flash"
    GPT_54_NANO = "gpt-5.4-nano"


class RoutineScope(str, Enum):
    """How much history the routine wrap reads when drafting."""

    SINCE_LAST_WRAP = "since-last-wrap"
    LAST_7_DAYS = "last-7-days"


# ---------------------------------------------------------------------------
# Defaults & invariants.


DEFAULT_FREQUENCY: RoutineFrequency = RoutineFrequency.WEEKLY
DEFAULT_DAY_OF_WEEK: RoutineDayOfWeek = RoutineDayOfWeek.FRIDAY
DEFAULT_ROUTINE_MODEL: RoutineModel = RoutineModel.USE_GLOBAL_DEFAULT
DEFAULT_SCOPE: RoutineScope = RoutineScope.SINCE_LAST_WRAP

# Phase 5 invariants — surfaced as constants so route + service +
# tests can all assert the same source of truth.
REVIEW_REQUIRED: bool = True
AUTO_SAVE_ALLOWED: bool = False

# Interval per frequency. ``monthly`` is approximated as 30 days for
# the MVP — switching to "same day next month" would require a
# calendar-aware helper, which is explicitly out of scope.
FREQUENCY_INTERVALS: dict[RoutineFrequency, timedelta] = {
    RoutineFrequency.WEEKLY: timedelta(days=7),
    RoutineFrequency.BIWEEKLY: timedelta(days=14),
    RoutineFrequency.MONTHLY: timedelta(days=30),
}

# How long a "Dismiss" silences the reminder. We don't touch
# ``last_run_at`` on dismiss (so the user doesn't lose their cadence
# entirely), but we *do* suppress nagging for a day. See
# :func:`is_routine_wrap_due` for how this interacts.
DISMISS_QUIET_PERIOD: timedelta = timedelta(hours=24)


# ---------------------------------------------------------------------------
# In-memory config shape.


@dataclass
class RoutineWrapConfig:
    """A snapshot of one project's routine wrap configuration.

    Mirrors :class:`app.models.routine_wrap_config.RoutineWrapConfig`
    one-for-one. Splitting model row ↔ pure dataclass keeps the due
    math testable without a DB session, and keeps the route layer
    from having to import SQLAlchemy types.

    ``review_required`` and ``auto_save`` are present as fields for
    forward compatibility, but they're *frozen* in Phase 5 to the
    invariants above — :func:`coerce_invariants` re-clamps them on
    every write.
    """

    enabled: bool
    frequency: RoutineFrequency
    day_of_week: RoutineDayOfWeek
    model: RoutineModel
    scope: RoutineScope
    review_required: bool = REVIEW_REQUIRED
    auto_save: bool = AUTO_SAVE_ALLOWED
    last_run_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "frequency": self.frequency.value,
            "dayOfWeek": self.day_of_week.value,
            "model": self.model.value,
            "scope": self.scope.value,
            "reviewRequired": self.review_required,
            "autoSave": self.auto_save,
            "lastRunAt": _isoformat(self.last_run_at),
            "dismissedAt": _isoformat(self.dismissed_at),
        }

    @classmethod
    def default(cls) -> "RoutineWrapConfig":
        return cls(
            enabled=False,
            frequency=DEFAULT_FREQUENCY,
            day_of_week=DEFAULT_DAY_OF_WEEK,
            model=DEFAULT_ROUTINE_MODEL,
            scope=DEFAULT_SCOPE,
        )


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def coerce_invariants(cfg: RoutineWrapConfig) -> RoutineWrapConfig:
    """Force ``review_required=True`` and ``auto_save=False``.

    Called on every config write. The frontend dialog never exposes
    these knobs in Phase 5, but a curl-fan that overrides them via
    the raw API still ends up with the safe values. Returns a new
    instance so callers can keep the original (audit log etc.).
    """
    if cfg.review_required is REVIEW_REQUIRED and cfg.auto_save is AUTO_SAVE_ALLOWED:
        return cfg
    return RoutineWrapConfig(
        enabled=cfg.enabled,
        frequency=cfg.frequency,
        day_of_week=cfg.day_of_week,
        model=cfg.model,
        scope=cfg.scope,
        review_required=REVIEW_REQUIRED,
        auto_save=AUTO_SAVE_ALLOWED,
        last_run_at=cfg.last_run_at,
        dismissed_at=cfg.dismissed_at,
    )


# ---------------------------------------------------------------------------
# Due-date math.


def is_routine_wrap_due(
    config: RoutineWrapConfig,
    now: datetime,
    *,
    respect_dismiss_quiet_period: bool = True,
) -> bool:
    """Return ``True`` iff the routine reminder should fire.

    Rules (all must hold):

    1. ``config.enabled`` is True.
    2. Either ``last_run_at`` is unset (never wrapped) **or** the
       elapsed time since ``last_run_at`` is at least the configured
       frequency interval (7 / 14 / 30 days).
    3. If ``dismissed_at`` is set and is younger than
       :data:`DISMISS_QUIET_PERIOD`, the reminder is muted. This is
       what stops a "Dismiss" from re-popping the banner on every
       page navigation. Pass ``respect_dismiss_quiet_period=False``
       to bypass the mute (used by the "open settings" path).

    The function is pure: same inputs → same output, no DB or clock
    access. ``now`` must be timezone-aware (the rest of the codebase
    standardizes on UTC).
    """
    if not config.enabled:
        return False

    interval = FREQUENCY_INTERVALS[config.frequency]
    last = _ensure_utc(config.last_run_at)
    now = _ensure_utc(now)

    if last is not None and (now - last) < interval:
        return False

    if respect_dismiss_quiet_period:
        dismissed = _ensure_utc(config.dismissed_at)
        if dismissed is not None and (now - dismissed) < DISMISS_QUIET_PERIOD:
            return False

    return True


def _ensure_utc(value: datetime | None) -> datetime | None:
    """Normalize a possibly-naive datetime to UTC.

    Naive values are assumed to already be in UTC (matches how
    SQLAlchemy returns rows on SQLite where the timezone gets
    stripped). Aware values are converted to UTC so subtraction
    against ``now`` is meaningful.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Model resolution.


def resolve_routine_model(routine_model: RoutineModel) -> WrapModel:
    """Map a :class:`RoutineModel` choice to a concrete :class:`WrapModel`.

    ``USE_GLOBAL_DEFAULT`` falls back to
    :data:`wrap_memory.settings.DEFAULT_MODEL`. Every other value
    has the same string identity as the corresponding ``WrapModel``,
    so the conversion is a direct ``WrapModel(value)`` lookup.
    """
    from .settings import DEFAULT_MODEL

    if routine_model is RoutineModel.USE_GLOBAL_DEFAULT:
        return DEFAULT_MODEL

    # The enum values were chosen to be identical to WrapModel's, so
    # the lookup never raises in practice. We still wrap it in a try
    # so a future divergence becomes a clear ValueError, not a
    # confusing KeyError further downstream.
    try:
        return WrapModel(routine_model.value)
    except ValueError as exc:  # pragma: no cover — defensive
        raise ValueError(
            f"RoutineModel {routine_model.value!r} has no matching WrapModel."
        ) from exc


__all__ = [
    "AUTO_SAVE_ALLOWED",
    "DEFAULT_DAY_OF_WEEK",
    "DEFAULT_FREQUENCY",
    "DEFAULT_ROUTINE_MODEL",
    "DEFAULT_SCOPE",
    "DISMISS_QUIET_PERIOD",
    "FREQUENCY_INTERVALS",
    "REVIEW_REQUIRED",
    "RoutineDayOfWeek",
    "RoutineFrequency",
    "RoutineModel",
    "RoutineScope",
    "RoutineWrapConfig",
    "coerce_invariants",
    "is_routine_wrap_due",
    "resolve_routine_model",
]
