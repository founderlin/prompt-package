"""Default configuration for the Wrap (project memory) feature.

Keeping defaults centralized here means:

* Tests have one place to assert against.
* Routes / services can fall back to a sensible baseline when the
  frontend omits a field.
* When we eventually let users persist their own defaults, this module
  becomes the *fallback* — the override layer slots above it.

Intentionally free of Flask globals so it imports cleanly from any
context (incl. unit tests that don't spin up an app).
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import FilterAction, WrapFilters, WrapMode, WrapModel

# Fast/cheap model picked as the wrap default. Aligns with the product
# spec: wraps should be near-free to run on every session.
DEFAULT_MODEL: WrapModel = WrapModel.DEEPSEEK_V4_FLASH

# Sensible content-type filters for a "first useful wrap" out of the box:
# * code/prompts/logs get *summarized* (kept but compressed) so the
#   wrap stays readable while preserving intent;
# * images and off-topic chatter are *excluded* — they rarely belong
#   in a project-memory artifact.
DEFAULT_FILTERS: WrapFilters = WrapFilters(
    code_blocks=FilterAction.SUMMARIZE,
    images=FilterAction.EXCLUDE,
    prompt_text=FilterAction.SUMMARIZE,
    logs=FilterAction.SUMMARIZE,
    off_topic=FilterAction.EXCLUDE,
)

# Routine cadence — Phase 3 will let users override this per project.
DEFAULT_ROUTINE_INTERVAL_DAYS: int = 7

# Default wrap mode when the frontend doesn't specify one. Mostly used
# by the upcoming "one-click" entry point.
DEFAULT_MODE: WrapMode = WrapMode.QUICK


@dataclass(frozen=True)
class WrapDefaults:
    """Single object bundling every default. Useful in tests + Phase 2 routes."""

    model: WrapModel = DEFAULT_MODEL
    filters: WrapFilters = DEFAULT_FILTERS
    routine_interval_days: int = DEFAULT_ROUTINE_INTERVAL_DAYS
    mode: WrapMode = DEFAULT_MODE

    def to_dict(self) -> dict:
        return {
            "model": self.model.value,
            "filters": self.filters.to_dict(),
            "routineIntervalDays": self.routine_interval_days,
            "mode": self.mode.value,
        }


def default_settings() -> WrapDefaults:
    """Convenience accessor — returns a fresh defaults bundle.

    Returning a new instance each call (instead of a module-level
    singleton) keeps tests trivially independent: nobody can mutate
    a shared object behind your back.
    """
    return WrapDefaults()


__all__ = [
    "DEFAULT_FILTERS",
    "DEFAULT_MODE",
    "DEFAULT_MODEL",
    "DEFAULT_ROUTINE_INTERVAL_DAYS",
    "WrapDefaults",
    "default_settings",
]
