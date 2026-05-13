"""Wrap prompt builders.

Pure-string functions: no Flask globals, no I/O. That keeps them easy
to unit-test and to inject in alternative providers (mock / future
agent runner) without dragging the rest of the service in.

Design goals:

* The **system prompt** is fixed and never templated with user data —
  user content lives only in the user prompt. This blocks the worst
  prompt-injection shapes ("act as ... ignore previous instructions"
  from the chat transcript can't smuggle role overrides into the
  system message).
* The **user prompt** mirrors the JSON schema the parser expects, so
  the model knows the exact field names + types it must produce.
* Filter rules, scope, and user instruction are surfaced verbatim so
  the model can route them into ``filteringSummary`` + content
  decisions.
* Messages are truncated per-message and as a corpus so a 50k-token
  chat doesn't blow up the request — the budget knobs are exported.
"""

from __future__ import annotations

from typing import Iterable

from .types import FilterAction, WrapFilters, WrapMessage, WrapRequest, WrapScope

# Truncation knobs — exported so tests + advanced callers can tune.
MESSAGE_CHAR_LIMIT: int = 2_000
TRANSCRIPT_CHAR_LIMIT: int = 18_000
MAX_MESSAGES_IN_PROMPT: int = 80


# ---------------------------------------------------------------------------
# System prompt — constant string.


_SYSTEM_PROMPT = """\
You are "Wrap Composer", an assistant that distills an AI chat session
into a single, reusable project-memory Markdown note.

Hard rules:
1. Reply with VALID JSON. No prose before or after. No code fences.
2. The JSON MUST match this schema exactly. Missing fields are not allowed:
   {
     "title": string,
     "topic": string,
     "topicDrift": boolean,
     "shouldSplit": boolean,
     "splitSuggestions": [
       { "title": string, "summary": string, "messageIds": number[] }
     ],
     "summary": string,
     "keyDecisions": string[],
     "requirements": string[],
     "todos": string[],
     "risks": string[],
     "tags": string[],
     "filteringSummary": string,
     "markdown": string
   }
3. Set "topicDrift" true if the conversation clearly shifted to an
   unrelated topic partway through. Set "shouldSplit" true ONLY when
   drift is severe enough that two separate wraps would be more useful;
   in that case populate "splitSuggestions" with one item per proposed
   sub-wrap. Otherwise leave "splitSuggestions" as [].
4. Apply the user's filter rules:
   - keep      → preserve the content verbatim in the Markdown body.
   - summarize → compress into a short, faithful paraphrase.
   - exclude   → drop entirely; do not mention it.
   Record the net effect in "filteringSummary" (one or two sentences).
5. "markdown" must be a self-contained Markdown document with a top-
   level "# <title>" heading and sections for Summary / Key Decisions /
   Requirements / Todos / Risks (omit a section when its list is empty).
6. "tags" are short kebab-case keywords, max 8.
7. Never invent facts that aren't grounded in the transcript. If the
   transcript is too short, return empty lists rather than guesses.
8. Use the same primary language as the transcript for natural-language
   fields (title, summary, etc.).
"""


def build_wrap_system_prompt() -> str:
    """Return the (constant) Wrap Composer system prompt."""
    return _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# User prompt — composed from a normalized request.


def _format_filters(filters: WrapFilters) -> str:
    return "\n".join(
        [
            f"- codeBlocks:  {filters.code_blocks.value}",
            f"- images:      {filters.images.value}",
            f"- promptText:  {filters.prompt_text.value}",
            f"- logs:        {filters.logs.value}",
            f"- offTopic:    {filters.off_topic.value}",
        ]
    )


def _filter_action_legend() -> str:
    return ", ".join(a.value for a in FilterAction)


def _truncate_message(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    # Mark the truncation so the model knows the omission was ours, not
    # a hint that the user's message was actually that short.
    return text[: limit - 1].rstrip() + "…"


def _format_messages(messages: Iterable[WrapMessage]) -> str:
    """Render the transcript with light truncation + a hard total cap.

    Strategy:
    * Cap per-message at MESSAGE_CHAR_LIMIT to stop one runaway turn
      from monopolizing the prompt budget.
    * Cap total at TRANSCRIPT_CHAR_LIMIT and keep the *latest* turns —
      wrap-quality is dominated by recency, not by the first hello.
    * Cap message count at MAX_MESSAGES_IN_PROMPT for the same reason.
    """
    items: list[tuple[int, str]] = []
    for idx, msg in enumerate(messages):
        content = _truncate_message(msg.content or "", MESSAGE_CHAR_LIMIT)
        role = msg.role.upper()
        marker = f"#{idx + 1} [{role}"
        if msg.message_id is not None:
            marker += f" id={msg.message_id}"
        marker += "]"
        items.append((idx, f"{marker}\n{content}".rstrip()))

    # Trim from the *front* until we fit within both caps. Latest
    # messages always win (transcripts are append-only).
    items = items[-MAX_MESSAGES_IN_PROMPT:]
    while items and sum(len(t) for _, t in items) > TRANSCRIPT_CHAR_LIMIT:
        items.pop(0)

    if not items:
        return "(no messages provided)"
    return "\n\n".join(text for _, text in items)


def build_wrap_user_prompt(request: WrapRequest) -> str:
    """Build the user-side prompt that gets paired with the system prompt.

    Always includes:
    * project_id + project_name (so the model can use them in title /
      tags if appropriate);
    * scope (conversation vs. project) so the framing matches;
    * filters in their canonical form;
    * the user's free-text instruction when present;
    * the truncated transcript.
    """
    scope_hint = (
        "Single conversation"
        if request.scope == WrapScope.CONVERSATION
        else "Multiple conversations from the same project"
    )

    parts: list[str] = [
        "## Wrap target",
        f"Project ID:   {request.project_id}",
        f"Project name: {request.project_name}",
        f"Scope:        {scope_hint}",
        f"Wrap mode:    {request.mode.value}",
        "",
        "## Filter rules",
        f"Legend: {_filter_action_legend()}",
        _format_filters(request.filters),
        "",
    ]

    if request.user_instruction:
        parts.extend(
            [
                "## User instruction (verbatim)",
                request.user_instruction.strip(),
                "",
            ]
        )

    parts.extend(
        [
            "## Transcript",
            _format_messages(request.messages),
            "",
            "## Task",
            "Return the wrap as a single JSON object matching the schema "
            "described in the system message. JSON only — no prose, no "
            "code fences.",
        ]
    )

    return "\n".join(parts)


__all__ = [
    "MAX_MESSAGES_IN_PROMPT",
    "MESSAGE_CHAR_LIMIT",
    "TRANSCRIPT_CHAR_LIMIT",
    "build_wrap_system_prompt",
    "build_wrap_user_prompt",
]
