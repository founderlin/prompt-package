"""Render a :class:`WrapAnalysisResult` to a Markdown file with frontmatter.

A wrap file is just a plain text Markdown file::

    ---
    title: "Auth design review"
    created_at: "2026-05-13T10:30:00+00:00"
    project_id: 42
    wrap_type: "advanced"
    model: "deepseek-v4-flash"
    tags: ["auth", "design"]
    ---

    # Auth design review
    ...body...

We deliberately *don't* pull in PyYAML — the frontmatter schema is
small, deterministic, and we keep full control over escaping. The
trade-off: this writer is **strict** about the values it accepts
(strings + booleans + ints + lists of strings). Anything fancier
(nested objects, datetimes that aren't already serialized) should be
pre-flattened by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .types import WrapAnalysisResult, WrapMode, WrapModel


# Bytes formatting steps. Powers-of-1024 chosen to match the units users
# actually see in Finder / Explorer (most desktop OSes still use
# binary prefixes for file sizes despite "KB" being the displayed label).
_UNIT_STEPS = (
    ("B", 1),
    ("KB", 1024),
    ("MB", 1024 ** 2),
    ("GB", 1024 ** 3),
    ("TB", 1024 ** 4),
)


@dataclass(frozen=True)
class WrapMarkdownMeta:
    """Metadata bundle that goes into the frontmatter block.

    Kept as its own dataclass (rather than passed as kwargs) so future
    fields don't break the signature of every call site.
    """

    project_id: int
    wrap_mode: WrapMode
    model: WrapModel
    created_at: datetime | None = None
    # Optional override for the title written into the frontmatter +
    # H1. Falls back to the analysis result's title when omitted.
    title_override: str | None = None
    # Optional extra tags merged with the analysis result's tags.
    extra_tags: tuple[str, ...] = ()


def _normalize_dt(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _yaml_escape_string(value: str) -> str:
    """Quote a string for YAML frontmatter.

    We always emit double-quoted strings — verbose but predictable, and
    avoids the YAML 1.1 ``no/yes/true/false`` trap where a bare word
    silently becomes a boolean.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    # Newlines inside titles / single-line tags would break the
    # frontmatter; collapse to a single space.
    escaped = escaped.replace("\r", " ").replace("\n", " ")
    return f'"{escaped}"'


def _yaml_list(items: Iterable[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return "[]"
    return "[" + ", ".join(_yaml_escape_string(item) for item in cleaned) + "]"


def _yaml_value(value: Any) -> str:
    """Render a single scalar value for the frontmatter block."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return _yaml_escape_string(_normalize_dt(value).isoformat())
    if isinstance(value, (list, tuple)):
        return _yaml_list(value)
    return _yaml_escape_string(str(value))


def build_frontmatter(meta: WrapMarkdownMeta, result: WrapAnalysisResult) -> str:
    """Render the YAML-style frontmatter block (between ``---`` fences).

    Field order is fixed: title → created_at → project_id → wrap_type →
    model → tags. Frontend parsers + human readers both benefit from a
    predictable layout.
    """
    title = (meta.title_override or result.title or "Untitled Wrap").strip()
    created_at = _normalize_dt(meta.created_at)
    tags: list[str] = list(result.tags or [])
    for extra in meta.extra_tags:
        if extra and extra not in tags:
            tags.append(extra)

    lines = [
        "---",
        f"title: {_yaml_value(title)}",
        f"created_at: {_yaml_value(created_at)}",
        f"project_id: {_yaml_value(meta.project_id)}",
        f"wrap_type: {_yaml_value(meta.wrap_mode.value)}",
        f"model: {_yaml_value(meta.model.value)}",
        f"tags: {_yaml_value(tags)}",
        "---",
    ]
    return "\n".join(lines)


def build_markdown_with_frontmatter(
    result: WrapAnalysisResult,
    meta: WrapMarkdownMeta,
) -> str:
    """Compose the final Markdown file content.

    The frontmatter is *always* prepended; if ``result.markdown`` is
    empty we still produce a useful skeleton from the structured
    fields (title + summary), so the writer never returns a frontmatter-
    only file.
    """
    frontmatter = build_frontmatter(meta, result)
    body = (result.markdown or "").strip()

    if not body:
        body = _fallback_body(result, meta)

    # Ensure a single blank line between frontmatter and body so common
    # Markdown renderers (and hand-eyeballing) reliably separate them.
    return f"{frontmatter}\n\n{body}\n"


def _fallback_body(result: WrapAnalysisResult, meta: WrapMarkdownMeta) -> str:
    """Render a minimal Markdown body when the LLM step didn't return one.

    Mirrors the structure the Phase 2 LLM prompt will eventually
    request, so downstream consumers (UI preview / search index) can
    treat the two outputs identically.
    """
    title = (meta.title_override or result.title or "Untitled Wrap").strip()
    parts: list[str] = [f"# {title}"]

    if result.summary:
        parts.extend(["", "## Summary", result.summary.strip()])

    def _section(heading: str, items: list[str] | None) -> None:
        cleaned = [item.strip() for item in (items or []) if item and item.strip()]
        if not cleaned:
            return
        parts.append("")
        parts.append(f"## {heading}")
        parts.extend(f"- {item}" for item in cleaned)

    _section("Key Decisions", result.key_decisions)
    _section("Requirements", result.requirements)
    _section("Todos", result.todos)
    if result.risks:
        _section("Risks", result.risks)

    if result.filtering_summary:
        parts.extend(["", "## Filtering", result.filtering_summary.strip()])

    return "\n".join(parts)


def format_bytes(size: int | float) -> str:
    """Human-friendly file-size string (e.g. ``"1.5 MB"``).

    * Negative inputs are treated as 0.
    * Non-finite floats fall back to ``"0 B"``.
    * Integer bytes are rendered without a decimal; everything else
      uses one decimal place so the dashboard never shows ``"1.0 KB"``
      where ``"1 KB"`` would do.
    """
    try:
        size_num = float(size)
    except (TypeError, ValueError):
        return "0 B"

    if size_num != size_num or size_num in (float("inf"), float("-inf")):
        return "0 B"
    if size_num < 0:
        size_num = 0.0

    label, factor = _UNIT_STEPS[0]
    for candidate_label, candidate_factor in _UNIT_STEPS:
        if size_num < candidate_factor * 1024 or candidate_label == _UNIT_STEPS[-1][0]:
            label, factor = candidate_label, candidate_factor
            if size_num < candidate_factor * 1024:
                break

    value = size_num / factor
    if factor == 1:
        return f"{int(value)} {label}"
    if abs(value - round(value)) < 0.05:
        return f"{int(round(value))} {label}"
    return f"{value:.1f} {label}"


__all__ = [
    "WrapMarkdownMeta",
    "build_frontmatter",
    "build_markdown_with_frontmatter",
    "format_bytes",
]
