"""Parse model output (raw JSON-ish text) into a :class:`WrapAnalysisResult`.

LLMs are loose about output shape:

* Some wrap their JSON in ```` ```json ... ``` ```` fences despite the
  system prompt forbidding it.
* Some emit ``<|im_start|>``-style preambles.
* Some swap ``true`` for ``"true"`` or omit optional fields entirely.

This parser is the **only** place in the wrap pipeline that touches
raw model output. Downstream code (UI, file writer) consumes a
:class:`WrapAnalysisResult` it can trust by construction.

Strategy:

1. Strip Markdown code fences (``json`` / no-language) if present.
2. Locate the outermost JSON object — anything before the first ``{``
   or after the matching ``}`` is discarded.
3. ``json.loads`` the candidate. Failure raises :class:`WrapParseError`.
4. Normalize each field with sane defaults so callers never need
   ``getattr(result, "x", default)`` patterns.

The parser never raises on missing/typo'd fields — that turns minor
model wobbles into hard 5xx responses. It *does* raise on outright
unparseable content, because at that point we have no data to render
and the UI should show the error.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .types import WrapAnalysisResult, WrapSplitSuggestion


class WrapParseError(ValueError):
    """Raised when raw model output can't be coerced into JSON."""

    def __init__(self, message: str, *, raw: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        # Only keep a short preview of the raw output so error messages
        # never inadvertently leak whole transcripts in server logs.
        self.raw_preview = (raw[:200] + "…") if raw and len(raw) > 200 else raw


# Matches a ```...``` fence with an optional language tag (json / JSON / etc.)
_FENCE_RE = re.compile(
    r"^\s*```(?:[a-zA-Z0-9_+-]+)?\s*\n(?P<body>.*?)\n```\s*$",
    re.DOTALL,
)


def _strip_code_fences(raw: str) -> str:
    """Remove a single surrounding ``` fence if present."""
    match = _FENCE_RE.match(raw)
    if match:
        return match.group("body")
    return raw


def _extract_outermost_json_object(text: str) -> str:
    """Return the substring spanning the first balanced ``{...}`` block.

    Tolerates leading apologies, trailing commentary, etc. Returns the
    full text when the brace structure is unbalanced — the caller will
    let ``json.loads`` raise for the real diagnostic.
    """
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text  # unbalanced — let json.loads complain


# ---------------------------------------------------------------------------
# Field normalizers.
#
# Each one accepts whatever the LLM emitted and either coerces it into
# the expected shape or substitutes a safe default. Lists of strings get
# the most lenient treatment: a missing list becomes [], a string-typed
# list element gets stringified, and ``null`` is treated as missing.


def _as_str(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return default
    return str(value).strip() or default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        cleaned = _as_str(item)
        if cleaned:
            out.append(cleaned)
    return out


def _as_int_list(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _as_split_suggestions(value: Any) -> list[WrapSplitSuggestion]:
    if not isinstance(value, list):
        return []
    out: list[WrapSplitSuggestion] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _as_str(item.get("title"))
        summary = _as_str(item.get("summary"))
        if not title and not summary:
            continue
        message_ids = _as_int_list(item.get("messageIds"))
        out.append(
            WrapSplitSuggestion(
                title=title or "Untitled split",
                summary=summary,
                message_ids=message_ids,
            )
        )
    return out


def parse_wrap_analysis_result(raw: Any) -> WrapAnalysisResult:
    """Parse raw model output into a normalized :class:`WrapAnalysisResult`.

    Accepts either:
    * a string (typical LLM completion content), OR
    * a dict (when a caller has already JSON-decoded).

    Raises :class:`WrapParseError` on unparseable input. Missing fields
    inside an otherwise valid JSON object are silently filled with
    safe defaults.
    """
    if isinstance(raw, dict):
        data: dict = raw
    elif isinstance(raw, str):
        cleaned = _strip_code_fences(raw.strip())
        if not cleaned:
            raise WrapParseError(
                "Model output did not contain a JSON object.", raw=raw
            )

        # Two-pass strategy:
        #   1. Try the whole cleaned blob first — this is the strict path
        #      that lets us reject top-level arrays / scalars cleanly.
        #   2. If that fails (LLM emitted leading prose, trailing text,
        #      etc.), fall back to the brace-balanced extractor and try
        #      again. This second pass is allowed to find an object that
        #      was wrapped in surrounding noise, but we still re-check
        #      the result is a dict.
        decoded: Any
        try:
            decoded = json.loads(cleaned)
        except json.JSONDecodeError:
            candidate = _extract_outermost_json_object(cleaned)
            if not candidate or candidate == cleaned:
                raise WrapParseError(
                    "Model output is not valid JSON.", raw=raw
                )
            try:
                decoded = json.loads(candidate)
            except json.JSONDecodeError as exc:
                raise WrapParseError(
                    f"Model output is not valid JSON ({exc.msg}).", raw=raw
                ) from exc

        if not isinstance(decoded, dict):
            raise WrapParseError(
                f"Top-level JSON value must be an object, got {type(decoded).__name__}.",
                raw=raw,
            )
        data = decoded
    else:
        raise WrapParseError(
            f"Model output must be str or dict, got {type(raw).__name__}."
        )

    risks_raw = data.get("risks")
    risks = _as_str_list(risks_raw) if risks_raw is not None else None

    return WrapAnalysisResult(
        title=_as_str(data.get("title")) or "Untitled Wrap",
        topic=_as_str(data.get("topic")),
        topic_drift=_as_bool(data.get("topicDrift")),
        should_split=_as_bool(data.get("shouldSplit")),
        split_suggestions=_as_split_suggestions(data.get("splitSuggestions")),
        summary=_as_str(data.get("summary")),
        key_decisions=_as_str_list(data.get("keyDecisions")),
        requirements=_as_str_list(data.get("requirements")),
        todos=_as_str_list(data.get("todos")),
        risks=risks if risks else None,
        filtering_summary=_as_str(data.get("filteringSummary")),
        tags=_as_str_list(data.get("tags")),
        markdown=_as_str(data.get("markdown")),
    )


__all__ = ["WrapParseError", "parse_wrap_analysis_result"]
