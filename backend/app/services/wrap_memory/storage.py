"""Filesystem layout for wrap Markdown files.

Default layout::

    <base_dir>/project-memory/
        wraps/                      # top-level wrap folder
            <project_id>/           # per-project subfolder
                YYYY-MM-DD_..._slug.md

Why per-project subfolders? The dashboard stats endpoint (Phase 3)
walks a single directory and reports counts + bytes; isolating by
``project_id`` keeps that walk O(wraps-of-this-project) instead of
O(all wraps the user ever made).

Base directory resolution order (first hit wins):

1. Explicit ``base_dir`` argument — used by tests + ad-hoc tools.
2. Flask config key ``WRAP_MEMORY_DIR`` — let prod operators override
   without code changes (also picked up from the env var of the same
   name via ``config.py`` once we wire it in Phase 2).
3. Fallback: ``backend/instance/project-memory/wraps`` — same parent
   folder as the SQLite DB and uploads, so the existing docker
   ``prompt-package-data`` named volume persists wraps for free.

This module is Flask-aware (it *optionally* reads ``current_app.config``)
but degrades gracefully when called outside an app context. That means
tests can pass ``base_dir=`` explicitly and never touch Flask.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Subdirectory names — fixed so the dashboard reader and the writer
# never disagree about layout.
PROJECT_MEMORY_DIRNAME: str = "project-memory"
WRAPS_DIRNAME: str = "wraps"

# Repo-relative fallback root: ``<repo>/backend/instance``. Resolved
# at call time (not import) so test monkey-patching of cwd works.
def _default_base_dir() -> Path:
    # ``Path(__file__)`` →  .../backend/app/services/wrap_memory/storage.py
    # parents[3] climbs to .../backend
    return Path(__file__).resolve().parents[3] / "instance"


def _flask_config_override() -> Optional[Path]:
    """Read ``WRAP_MEMORY_DIR`` from the Flask config, if available."""
    try:
        from flask import current_app, has_app_context
    except ImportError:  # pragma: no cover - Flask is a hard dep, but be safe
        return None
    if not has_app_context():
        return None
    value = current_app.config.get("WRAP_MEMORY_DIR")
    if not value:
        return None
    return Path(value).expanduser()


def get_project_memory_dir(
    *,
    base_dir: Path | str | None = None,
) -> Path:
    """Resolve the top-level ``project-memory/`` directory.

    Returns a :class:`Path` — the directory is *not* created here, so
    callers can compose deeper subpaths cheaply without producing
    empty folders on disk.
    """
    if base_dir is not None:
        root = Path(base_dir).expanduser()
        return root / PROJECT_MEMORY_DIRNAME

    override = _flask_config_override()
    if override is not None:
        # Operators can point ``WRAP_MEMORY_DIR`` at either:
        #   * a "container" path (we still append project-memory/) or
        #   * a directly-rooted path (we use it verbatim).
        # Heuristic: if the path already ends in PROJECT_MEMORY_DIRNAME,
        # trust the operator's choice.
        if override.name == PROJECT_MEMORY_DIRNAME:
            return override
        return override / PROJECT_MEMORY_DIRNAME

    return _default_base_dir() / PROJECT_MEMORY_DIRNAME


def get_wraps_dir(
    project_id: int | None = None,
    *,
    base_dir: Path | str | None = None,
) -> Path:
    """Resolve the directory for wrap files (optionally scoped to a project).

    ``get_wraps_dir()`` returns ``<project-memory>/wraps``.
    ``get_wraps_dir(42)`` returns ``<project-memory>/wraps/42``.
    """
    root = get_project_memory_dir(base_dir=base_dir) / WRAPS_DIRNAME
    if project_id is None:
        return root
    if not isinstance(project_id, int) or project_id < 0:
        raise ValueError(f"project_id must be a non-negative int, got {project_id!r}")
    return root / str(project_id)


def ensure_wraps_dir(
    project_id: int | None = None,
    *,
    base_dir: Path | str | None = None,
) -> Path:
    """Like :func:`get_wraps_dir` but materializes the directory on disk."""
    target = get_wraps_dir(project_id, base_dir=base_dir)
    target.mkdir(parents=True, exist_ok=True)
    return target


__all__ = [
    "PROJECT_MEMORY_DIRNAME",
    "WRAPS_DIRNAME",
    "ensure_wraps_dir",
    "get_project_memory_dir",
    "get_wraps_dir",
]
