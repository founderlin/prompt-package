"""Context Pack generator — pluggable summary / keywords / body producer.

This service is the **only** place that knows how to turn a list of
conversation transcripts into the structured artifacts a
:class:`~app.models.ContextPack` expects:

* ``summary``      — short structured brief (<= MAX_SUMMARY_LENGTH chars)
* ``keywords``     — a small list of extracted topical keywords
* ``description``  — optional one-liner (derived from goal / summary)
* ``body``         — the full pack Markdown body (same format as the
  legacy ``context_pack_service.generate``)

Two execution paths are wired up:

1. **LLM path** (preferred): reuses the provider-agnostic
   :func:`app.services.llm_service.chat_completion` wrapper and the
   user's stored API key. Prompts live as module-level constants so
   the route layer never sees prompt text.

2. **Rule-based fallback**: used when the user has no LLM key
   configured, or when the caller explicitly asks for
   ``use_llm=False``. It produces a best-effort summary (first
   sentences of the freshest turns) and frequency-ranked keywords.
   This is intentionally cheap so the wrap-up flow still returns a
   valid Context Pack even without any credentials.

The public surface is deliberately narrow. Callers feed structured
"source bundles" in and receive a :class:`GenerationResult` out; they
don't know which path produced it.

Future hooks:

- Swapping in an Agent-style multi-step generator is a matter of
  adding a new ``_generate_agent()`` function and a strategy switch.
- Vector DB / Graph augmentation would slot in either before
  ``_generate_llm`` (to enrich the prompt) or after (to persist
  embeddings alongside the pack).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from app.models import Conversation, Message, User
from app.providers import get_provider, normalize_provider
from app.services.credentials_service import (
    CredentialsError,
    first_configured_provider,
    get_decrypted_key_for,
)
from app.services.llm_service import LLMError, chat_completion

# -----------------------------------------------------------------------------
# Limits & tunables. Exported so route/service layers can validate input.

SUMMARY_MIN_LENGTH = 200
SUMMARY_MAX_LENGTH_DEFAULT_CONVO = 3_000
SUMMARY_MAX_LENGTH_DEFAULT_PROJECT = 5_000
SUMMARY_HARD_CEILING = 8_000

KEYWORDS_MIN = 3
KEYWORDS_MAX = 12

GOAL_MAX = 1_000
TITLE_MAX = 160
DESCRIPTION_MAX = 500

BODY_HARD_CEILING = 12_000
MESSAGE_CHAR_LIMIT = 4_000
TRANSCRIPT_CHAR_LIMIT = 24_000
MAX_CONVERSATIONS_IN_PROMPT = 20


# -----------------------------------------------------------------------------
# Error + result types.


class GeneratorError(Exception):
    """Predictable, user-facing generator failures."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class ConversationSource:
    """One conversation's slice of context being fed into the generator.

    ``messages`` is *already* filtered to non-empty user/assistant turns
    the caller wants in the pack. The generator does not re-filter —
    it only clamps for prompt-size control.
    """

    conversation: Conversation
    messages: list[Message] = field(default_factory=list)


@dataclass
class GenerationOptions:
    """Tunables the caller (wrap_up_service) passes down."""

    max_summary_length: int = SUMMARY_MAX_LENGTH_DEFAULT_PROJECT
    # When False, the generator skips the LLM and returns rule-based
    # output. The same result shape is returned.
    use_llm: bool = True
    # Title to seed into the H1 of the generated body. Optional.
    title: str | None = None
    # User-provided goal ("整理本次技术方案讨论", etc). Optional.
    goal: str | None = None


@dataclass
class GenerationResult:
    """Everything the caller needs to persist a ContextPack row."""

    summary: str
    keywords: list[str]
    description: str | None
    body: str
    model: str | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    used_llm: bool = False


# -----------------------------------------------------------------------------
# Prompts — keep in one place, never inline them in routes / wrap_up_service.

SYSTEM_PROMPT_WRAPUP = """You are turning one or more project chat transcripts into a "Context Pack" — a reusable bundle the user will drop into a fresh AI session so the next model picks up where the project left off.

You MUST return VALID JSON only. No commentary. No code fences. No text before or after the JSON.

Schema:

{
  "summary": "Short structured brief (3-8 sentences). Plain prose, no markdown headings.",
  "keywords": ["3-12 short topical tags in kebab or camel case, lowercase. Skip filler words."],
  "description": "Optional one-liner (<= 200 chars) tying the pack to its goal/purpose. May be null.",
  "body": "Full Markdown pack. See body format below."
}

Body format requirements:
- Start with a single `#` H1 line containing the pack title exactly as provided.
- Then ONE short paragraph (1-3 sentences) summarizing the project state.
- Then these `##` sections IN THIS ORDER. Skip any section whose content would be empty; NEVER emit empty headings:
  - `## Decisions` — bullets of decisions already made.
  - `## Open Todos` — bullets of still-to-do items.
  - `## Key Facts` — bullets of stable facts about the project / system / constraints.
  - `## Open Questions` — bullets of questions worth revisiting.
  - `## Notes for the next session` — 1-3 short bullets orienting whoever picks this up next.
- Use concise single-sentence bullets. De-duplicate. Drop pleasantries.
- Stay under ~600 words in the body.

Summary length: aim for under {max_summary_length} characters.

If the user provides extra `goal`, let it shape what to emphasize (e.g. "focus on architecture decisions only") but never break the format above.
"""


# -----------------------------------------------------------------------------
# Public entry point.


def generate(
    user: User,
    sources: list[ConversationSource],
    options: GenerationOptions,
    *,
    project_name: str | None = None,
    project_description: str | None = None,
) -> GenerationResult:
    """Produce a GenerationResult from ``sources``.

    Dispatches to the LLM path when the user has a configured provider
    and ``options.use_llm`` is true, else falls back to rule-based
    generation. Either path returns the same shape.
    """
    if not sources:
        raise GeneratorError(
            "no_sources",
            "Nothing to wrap up — at least one conversation with content is required.",
        )

    cleaned_sources = [s for s in sources if s.messages]
    if not cleaned_sources:
        raise GeneratorError(
            "empty_sources",
            "Selected conversations have no user/assistant messages to summarize.",
        )

    max_summary = _clamp_summary_limit(options.max_summary_length)

    # Always attempt LLM first when asked; on missing key we transparently
    # degrade to the rule-based fallback — callers shouldn't have to decide.
    if options.use_llm:
        provider = first_configured_provider(user)
        if provider:
            try:
                return _generate_llm(
                    user,
                    cleaned_sources,
                    options,
                    provider=provider,
                    max_summary_length=max_summary,
                    project_name=project_name,
                    project_description=project_description,
                )
            except GeneratorError:
                # Hard errors from the LLM path stay — we don't silently
                # swallow e.g. upstream 401s into a rule fallback, because
                # users deserve a clear "fix your key" message.
                raise

    # Either the caller opted out of LLM, or the user has no key at all.
    return _generate_rules(
        cleaned_sources,
        options,
        max_summary_length=max_summary,
        project_name=project_name,
    )


# -----------------------------------------------------------------------------
# LLM path.


def _generate_llm(
    user: User,
    sources: list[ConversationSource],
    options: GenerationOptions,
    *,
    provider: str,
    max_summary_length: int,
    project_name: str | None,
    project_description: str | None,
) -> GenerationResult:
    provider = normalize_provider(provider)
    try:
        api_key = get_decrypted_key_for(user, provider)
    except CredentialsError as err:
        raise GeneratorError(err.code, err.message, status=err.status) from err
    if not api_key:
        raise GeneratorError(
            "no_api_key",
            "Add an LLM API key in Settings before wrapping up.",
        )

    cfg = get_provider(provider)
    chosen_model = cfg.summary_model

    system_prompt = SYSTEM_PROMPT_WRAPUP.format(
        max_summary_length=max_summary_length
    )
    user_content = _build_user_prompt(
        sources,
        options=options,
        project_name=project_name,
        project_description=project_description,
    )
    payload = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        completion = chat_completion(
            api_key,
            model=chosen_model,
            messages=payload,
            provider=provider,
            temperature=0.2,
            extra={"response_format": {"type": "json_object"}},
        )
    except LLMError as err:
        raise GeneratorError(err.code, err.message, status=err.status) from err

    data = _parse_llm_response(completion.content or "")

    summary = _clip(data.get("summary") or "", max_summary_length)
    raw_keywords = data.get("keywords") or []
    if not isinstance(raw_keywords, list):
        raw_keywords = []
    keywords = _normalize_keywords(raw_keywords)

    description_raw = data.get("description")
    description: str | None
    if isinstance(description_raw, str) and description_raw.strip():
        description = _clip(description_raw.strip(), DESCRIPTION_MAX)
    else:
        description = None

    body = _strip_code_fences(data.get("body") or "")
    if not body.strip():
        # The LLM returned valid JSON but an empty body — build a best-
        # effort body from summary + keywords so the pack is usable.
        body = _fallback_body(
            title=(options.title or "Context Pack"),
            summary=summary,
            keywords=keywords,
            sources=sources,
        )
    body = body[:BODY_HARD_CEILING]

    if not summary.strip():
        summary = _rule_summary(sources, max_summary_length)

    return GenerationResult(
        summary=summary,
        keywords=keywords,
        description=description,
        body=body,
        model=completion.model or chosen_model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        total_tokens=completion.total_tokens,
        used_llm=True,
    )


def _build_user_prompt(
    sources: list[ConversationSource],
    *,
    options: GenerationOptions,
    project_name: str | None,
    project_description: str | None,
) -> str:
    parts: list[str] = []
    if project_name:
        parts.append(f"Project name: {project_name!r}.")
    if project_description:
        desc = project_description.strip()
        if desc:
            parts.append(f"Project description: {desc}")
    if options.title:
        parts.append(f"Pack title to use as the H1: {options.title!r}.")
    if options.goal:
        parts.append(f"User's wrap-up goal (follow this): {options.goal.strip()}")
    parts.append(
        f"Target summary length: aim for ~{_clamp_summary_limit(options.max_summary_length)} characters, "
        f"and definitely under {SUMMARY_HARD_CEILING}."
    )

    # Clamp transcript size so the prompt stays under provider limits.
    bundles = sources[:MAX_CONVERSATIONS_IN_PROMPT]
    total_chars = 0
    rendered_blocks: list[str] = []
    for idx, src in enumerate(bundles, start=1):
        header = _conversation_header(src.conversation, idx)
        transcript_lines: list[str] = []
        for msg in src.messages:
            if msg.role not in ("user", "assistant"):
                continue
            body = (msg.content or "").strip()
            if not body:
                continue
            body = _clip(body, MESSAGE_CHAR_LIMIT)
            speaker = "User" if msg.role == "user" else "Assistant"
            line = f"{speaker}: {body}"
            total_chars += len(line)
            if total_chars > TRANSCRIPT_CHAR_LIMIT and transcript_lines:
                transcript_lines.append("[... transcript truncated for prompt size ...]")
                break
            transcript_lines.append(line)
        if transcript_lines:
            rendered_blocks.append(
                f"{header}\n" + "\n\n".join(transcript_lines)
            )
        if total_chars > TRANSCRIPT_CHAR_LIMIT:
            break

    parts.append("===== TRANSCRIPTS =====")
    parts.extend(rendered_blocks)
    parts.append("===== END TRANSCRIPTS =====")
    return "\n\n".join(parts)


def _conversation_header(convo: Conversation, index: int) -> str:
    title = convo.title or "Untitled"
    return f"--- Conversation #{index} (id={convo.id}): {title!r} ---"


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _parse_llm_response(raw: str) -> dict:
    if not raw or not raw.strip():
        raise GeneratorError(
            "generation_failed",
            "The model returned an empty response.",
            status=502,
        )
    candidate = _strip_code_fences(raw)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(candidate)
        if not match:
            raise GeneratorError(
                "generation_failed",
                "The model did not return parseable JSON.",
                status=502,
            )
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as err:
            raise GeneratorError(
                "generation_failed",
                f"The model returned malformed JSON: {err.msg}.",
                status=502,
            ) from err
    if not isinstance(data, dict):
        raise GeneratorError(
            "generation_failed",
            "The model response was not a JSON object.",
            status=502,
        )
    return data


# -----------------------------------------------------------------------------
# Rule-based fallback.


# Very small English+Chinese stop-word list; good enough for keyword
# extraction on MVP chat transcripts. We can swap for a proper NLP lib
# the day we care about quality.
_STOP_WORDS = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "can",
        "could", "should", "may", "might", "must", "shall", "to", "of",
        "and", "or", "but", "if", "then", "else", "for", "with", "without",
        "about", "into", "onto", "from", "as", "at", "by", "in", "on",
        "this", "that", "these", "those", "it", "its", "it's", "they",
        "them", "their", "we", "our", "ours", "you", "your", "yours", "i",
        "me", "my", "mine", "he", "she", "his", "her", "hers", "not", "no",
        "so", "too", "very", "just", "more", "most", "any", "some", "all",
        "one", "two", "three", "also", "only", "than", "because", "how",
        "what", "when", "where", "why", "which", "who", "whom", "there",
        "here", "now", "ok", "okay", "yes", "yeah", "please", "thanks",
        "thank", "let", "lets", "make", "made", "get", "got", "go", "going",
        "want", "need", "use", "using", "used", "way", "something",
        "anything", "nothing", "everything", "think", "know", "like",
        "really", "much", "many", "sure", "hey", "hello", "好的", "嗯",
        "然后", "因为", "所以", "这个", "那个", "我们", "你们", "他们",
        "可以", "应该", "需要", "没有", "就是", "什么", "怎么", "这样",
        "那样", "这里", "那里",
    }
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}")


def _generate_rules(
    sources: list[ConversationSource],
    options: GenerationOptions,
    *,
    max_summary_length: int,
    project_name: str | None,
) -> GenerationResult:
    summary = _rule_summary(sources, max_summary_length)
    keywords = _rule_keywords(sources)
    description = None
    if options.goal:
        description = _clip(options.goal.strip(), DESCRIPTION_MAX)
    body = _fallback_body(
        title=(options.title or (project_name + " · Context Pack" if project_name else "Context Pack")),
        summary=summary,
        keywords=keywords,
        sources=sources,
        goal=options.goal,
    )[:BODY_HARD_CEILING]

    return GenerationResult(
        summary=summary,
        keywords=keywords,
        description=description,
        body=body,
        model=None,
        used_llm=False,
    )


def _rule_summary(
    sources: list[ConversationSource], max_summary_length: int
) -> str:
    """Pick the freshest user turns + assistant replies and stitch them."""
    sentences: list[str] = []
    # Walk conversations in reverse chronological order of their last message.
    ordered = sorted(
        sources,
        key=lambda s: s.messages[-1].created_at if s.messages else datetime.now(timezone.utc),
        reverse=True,
    )
    for src in ordered:
        title = src.conversation.title or "Untitled conversation"
        sentences.append(f"[{title}]")
        # Earliest user turn: establishes the topic.
        first_user = next((m for m in src.messages if m.role == "user"), None)
        if first_user and first_user.content:
            sentences.append(_first_sentences(first_user.content, limit=260))
        # Latest assistant turn: tends to contain the conclusion.
        last_assistant = next(
            (m for m in reversed(src.messages) if m.role == "assistant"), None
        )
        if last_assistant and last_assistant.content:
            sentences.append(_first_sentences(last_assistant.content, limit=320))
        if sum(len(s) for s in sentences) >= max_summary_length:
            break
    joined = " ".join(s.strip() for s in sentences if s and s.strip())
    return _clip(joined, max_summary_length) if joined else "(no content)"


def _rule_keywords(sources: list[ConversationSource]) -> list[str]:
    counts: dict[str, int] = {}
    seen_original: dict[str, str] = {}
    for src in sources:
        if src.conversation.title:
            for tok in _tokenize(src.conversation.title):
                counts[tok.lower()] = counts.get(tok.lower(), 0) + 3  # title boost
                seen_original.setdefault(tok.lower(), tok)
        for msg in src.messages:
            for tok in _tokenize(msg.content or ""):
                key = tok.lower()
                if key in _STOP_WORDS or len(key) < 3:
                    continue
                counts[key] = counts.get(key, 0) + 1
                seen_original.setdefault(key, tok)
    if not counts:
        return []
    # Top-N by frequency, tie-break alphabetical for stability.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [seen_original.get(k, k) for k, _v in ranked[:KEYWORDS_MAX]]
    # Make sure we return at least KEYWORDS_MIN when we have them.
    return _normalize_keywords(top)


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _normalize_keywords(words) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in words:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().strip(".,;:!?").lower()
        if not cleaned or cleaned in _STOP_WORDS or len(cleaned) < 2:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
        if len(out) >= KEYWORDS_MAX:
            break
    return out


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s+")


def _first_sentences(text: str, *, limit: int = 300) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    pieces = _SENTENCE_SPLIT_RE.split(cleaned)
    out = ""
    for s in pieces:
        candidate = (out + " " + s).strip() if out else s
        if len(candidate) > limit:
            if out:
                return out
            return _clip(s, limit)
        out = candidate
    return out or _clip(cleaned, limit)


def _fallback_body(
    *,
    title: str,
    summary: str,
    keywords: list[str],
    sources: list[ConversationSource],
    goal: str | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# {title.strip() or 'Context Pack'}")
    lines.append("")
    if summary.strip():
        lines.append(summary.strip())
    else:
        lines.append(_ellipsis(_describe_sources(sources), 400))
    lines.append("")
    if goal:
        lines.append("## Goal")
        lines.append(goal.strip())
        lines.append("")
    lines.append("## Conversations covered")
    for src in sources:
        convo = src.conversation
        title_ = convo.title or "Untitled conversation"
        count = len(src.messages)
        lines.append(
            f"- **{title_}** (id `{convo.id}`) — {count} message{'s' if count != 1 else ''}"
        )
    if keywords:
        lines.append("")
        lines.append("## Keywords")
        lines.append(", ".join(keywords))
    lines.append("")
    lines.append("## Notes for the next session")
    lines.append(
        "- This pack was generated without an LLM summary "
        "(no provider key configured, or the LLM run failed). "
        "Re-run Wrap Up after adding a key for a richer summary."
    )
    return "\n".join(lines).strip()


def _describe_sources(sources: list[ConversationSource]) -> str:
    titles = [s.conversation.title or "Untitled" for s in sources]
    return "Covers " + ", ".join(titles) + "."


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _ellipsis(text: str, limit: int) -> str:
    return _clip(text, limit)


def _clamp_summary_limit(raw: int | None) -> int:
    try:
        value = int(raw) if raw is not None else SUMMARY_MAX_LENGTH_DEFAULT_PROJECT
    except (TypeError, ValueError):
        value = SUMMARY_MAX_LENGTH_DEFAULT_PROJECT
    if value < SUMMARY_MIN_LENGTH:
        return SUMMARY_MIN_LENGTH
    if value > SUMMARY_HARD_CEILING:
        return SUMMARY_HARD_CEILING
    return value


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\s*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    return stripped


__all__ = [
    "BODY_HARD_CEILING",
    "ConversationSource",
    "DESCRIPTION_MAX",
    "GOAL_MAX",
    "GenerationOptions",
    "GenerationResult",
    "GeneratorError",
    "KEYWORDS_MAX",
    "KEYWORDS_MIN",
    "SUMMARY_HARD_CEILING",
    "SUMMARY_MAX_LENGTH_DEFAULT_CONVO",
    "SUMMARY_MAX_LENGTH_DEFAULT_PROJECT",
    "SUMMARY_MIN_LENGTH",
    "TITLE_MAX",
    "generate",
]
