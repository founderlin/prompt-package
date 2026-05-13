"""Project memory stats — Phase 6.

Walks the wraps directory for a project and reports the three (and
only three) metrics that the dashboard needs:

* ``wrap_count``        — number of Markdown files saved
* ``memory_size_bytes`` — sum of their byte sizes
* ``last_wrapped_at``   — newest mtime across the files

Deliberately tiny and disk-bound. We do **not** open or parse the
files (no token counts, no health score, no duplicate detection —
all explicitly out of scope for Phase 6). Walking a per-project
directory keeps the cost O(wraps-of-this-project) instead of
O(all-wraps-this-user-ever-saved).

The module is the only place in ``wrap_memory`` that talks to the
filesystem *for reads*. ``service.save_wrap_draft`` writes; this
counterpart reads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.models import Project, User

from .service import WrapServiceError
from .storage import get_wraps_dir
from .types import ProjectMemoryStats


WRAP_FILE_SUFFIX = ".md"


def get_project_memory_stats(
    *,
    user: User,
    project: Project,
    base_dir: Path | str | None = None,
) -> ProjectMemoryStats:
    """Return the wrap-memory stats for one project.

    Behavior:

    * Missing wraps directory → returns 0/0/None (no error). New
      projects don't have a folder until the first save; the
      dashboard treats that as "0 wraps" rather than failing.
    * Empty wraps directory → also 0/0/None.
    * Non-``.md`` files are ignored (avoids inflating counts when
      a future feature drops sidecar JSON next to the Markdown).
    * Subdirectories are ignored.

    Raises :class:`WrapServiceError` only on the cross-user safety
    check; filesystem errors during the walk are swallowed and
    treated as "zero" so a transient I/O hiccup never breaks the
    dashboard.
    """
    if project.user_id != user.id:
        raise WrapServiceError("not_found", "Project not found.", status=404)

    project_dir = get_wraps_dir(project.id, base_dir=base_dir)
    counts = _walk_project_dir(project_dir)

    return ProjectMemoryStats(
        project_id=project.id,
        project_name=project.name or "Untitled project",
        wrap_count=counts.wrap_count,
        memory_size_bytes=counts.memory_size_bytes,
        last_wrapped_at=counts.last_wrapped_at,
    )


def get_all_project_memory_stats(
    *,
    user: User,
    projects: list[Project],
    base_dir: Path | str | None = None,
) -> list[ProjectMemoryStats]:
    """Batch version of :func:`get_project_memory_stats`.

    Walks each project's wraps directory in sequence. The list is
    returned in the same order as ``projects`` so the frontend can
    zip it with its existing project list without re-sorting.

    Projects not owned by ``user`` are silently skipped — the caller
    is expected to pass an already-filtered list, but we double-check
    here so a route handler can't accidentally leak across users.
    """
    out: list[ProjectMemoryStats] = []
    for project in projects:
        if project.user_id != user.id:
            continue
        out.append(
            get_project_memory_stats(
                user=user, project=project, base_dir=base_dir
            )
        )
    return out


# ---------------------------------------------------------------------------
# Internals.


class _Counts:
    __slots__ = ("wrap_count", "memory_size_bytes", "last_wrapped_at")

    def __init__(self) -> None:
        self.wrap_count: int = 0
        self.memory_size_bytes: int = 0
        self.last_wrapped_at: datetime | None = None


def _walk_project_dir(project_dir: Path) -> _Counts:
    """Single-directory walk returning the three metrics.

    Resilient by design: missing dir → empty counts; per-file ``stat``
    errors → that file is skipped (logged via a warning only when
    ``current_app`` is available, otherwise silently). Phase 6 does
    not need a "files that failed to read" surface.
    """
    counts = _Counts()
    if not project_dir.exists() or not project_dir.is_dir():
        return counts

    try:
        entries = list(project_dir.iterdir())
    except OSError:
        # Unreadable directory — treat as zero rather than 500.
        return counts

    for entry in entries:
        try:
            if not entry.is_file():
                continue
            if entry.suffix.lower() != WRAP_FILE_SUFFIX:
                continue
            stat = entry.stat()
        except OSError:
            continue

        counts.wrap_count += 1
        counts.memory_size_bytes += stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        if counts.last_wrapped_at is None or mtime > counts.last_wrapped_at:
            counts.last_wrapped_at = mtime

    return counts


__all__ = [
    "WRAP_FILE_SUFFIX",
    "get_all_project_memory_stats",
    "get_project_memory_stats",
]
