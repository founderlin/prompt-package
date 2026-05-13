"""Type definitions for the Wrap (project memory) feature.

The Wrap feature turns a chat session into a *Markdown project-memory
file on disk* (distinct from the legacy "Wrap Up" flow which writes a
DB-backed Context Pack). This module is the single source of truth for
all the data shapes that flow through:

    UI form  →  service layer  →  LLM adapter  →  Markdown writer

Everything here is pure stdlib (dataclasses + enum), so it imports
cleanly from any layer (tests, routes, services) without dragging
Flask context in.

Naming convention:

* Enum *values* are short kebab-style strings that double as wire
  identifiers — the frontend sends them, we accept them verbatim.
* All dataclasses are immutable when it makes sense (``frozen=True``)
  except :class:`WrapRequest`, which the service layer mutates in
  place to normalize messages / fill defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums.
#
# We use ``str, Enum`` (i.e. StrEnum-equivalent) so ``WrapMode.QUICK == "quick"``
# is True. That keeps JSON (de)serialization trivial: ``json.dumps(mode)``
# would still need ``mode.value`` but equality comparisons against the
# raw wire string just work, which is what every route/service caller
# actually needs.


class WrapMode(str, Enum):
    """How a wrap was triggered. Stored verbatim in the Markdown frontmatter."""

    QUICK = "quick"
    ADVANCED = "advanced"
    ROUTINE = "routine"


class WrapModel(str, Enum):
    """Curated fast/cheap models eligible for wrap generation.

    Mapped to concrete provider+model ids by ``wrap_memory.llm_adapter``
    in Phase 2. Keeping the catalog narrow on purpose — wraps should be
    cheap. Users still customize their *chat* model via existing
    UserModelSelection; this list is wrap-specific.
    """

    DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
    GEMINI_31_FLASH = "gemini-3.1-flash"
    GPT_54_NANO = "gpt-5.4-nano"


class FilterAction(str, Enum):
    """Per-content-type filter knob.

    ``keep``      — inline verbatim in the wrap.
    ``summarize`` — let the LLM compress to a short paraphrase.
    ``exclude``   — drop entirely, no trace in output.
    """

    KEEP = "keep"
    SUMMARIZE = "summarize"
    EXCLUDE = "exclude"


class WrapScope(str, Enum):
    """What slice of memory the wrap is being computed over."""

    CONVERSATION = "conversation"
    PROJECT = "project"


# ---------------------------------------------------------------------------
# Filter rules.


@dataclass(frozen=True)
class WrapFilters:
    """Content-type filter map applied during wrap generation.

    Five buckets, each independently configurable. Defaults live in
    :mod:`wrap_memory.settings` so callers can grab a sensible baseline
    without hard-coding values here.
    """

    code_blocks: FilterAction
    images: FilterAction
    prompt_text: FilterAction
    logs: FilterAction
    off_topic: FilterAction

    def to_dict(self) -> dict:
        return {
            "codeBlocks": self.code_blocks.value,
            "images": self.images.value,
            "promptText": self.prompt_text.value,
            "logs": self.logs.value,
            "offTopic": self.off_topic.value,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "WrapFilters":
        """Build filters from a (possibly partial) wire payload.

        Missing keys fall back to the global defaults so the frontend
        only ever has to send overrides. Unknown values raise
        ``ValueError`` so typos surface early.
        """
        from .settings import DEFAULT_FILTERS

        data = data or {}
        if not isinstance(data, dict):
            raise ValueError("filters must be a JSON object")

        def pick(key: str, fallback: FilterAction) -> FilterAction:
            raw = data.get(key)
            if raw is None:
                return fallback
            try:
                return FilterAction(raw)
            except ValueError as exc:
                allowed = ", ".join(a.value for a in FilterAction)
                raise ValueError(
                    f"filters.{key}: unknown action {raw!r}; expected one of {allowed}"
                ) from exc

        return cls(
            code_blocks=pick("codeBlocks", DEFAULT_FILTERS.code_blocks),
            images=pick("images", DEFAULT_FILTERS.images),
            prompt_text=pick("promptText", DEFAULT_FILTERS.prompt_text),
            logs=pick("logs", DEFAULT_FILTERS.logs),
            off_topic=pick("offTopic", DEFAULT_FILTERS.off_topic),
        )


# ---------------------------------------------------------------------------
# Request / message shapes.


@dataclass
class WrapMessage:
    """Normalized chat message fed into the wrap pipeline.

    Source-of-truth lives in the DB (Message rows), but the wrap
    pipeline accepts plain dicts too so smoke scripts / tests don't
    need a real DB row to exercise the Markdown writer.
    """

    role: str
    content: str
    created_at: Optional[datetime] = None
    message_id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "WrapMessage":
        if not isinstance(data, dict):
            raise ValueError("message must be an object with role + content")
        role = (data.get("role") or "").strip().lower()
        if role not in {"user", "assistant", "system"}:
            raise ValueError(
                f"message.role must be one of user/assistant/system, got {role!r}"
            )
        content = data.get("content")
        if not isinstance(content, str):
            raise ValueError("message.content must be a string")
        return cls(
            role=role,
            content=content,
            created_at=data.get("created_at"),
            message_id=data.get("message_id"),
        )


@dataclass
class WrapRequest:
    """Everything the service layer needs to produce one wrap."""

    project_id: int
    project_name: str
    mode: WrapMode
    model: WrapModel
    scope: WrapScope
    messages: list[WrapMessage]
    filters: WrapFilters
    user_instruction: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "WrapRequest":
        from .settings import DEFAULT_MODEL

        if not isinstance(data, dict):
            raise ValueError("request payload must be a JSON object")

        project_id = data.get("projectId")
        if not isinstance(project_id, int):
            raise ValueError("projectId must be an integer")

        project_name = data.get("projectName")
        if not isinstance(project_name, str) or not project_name.strip():
            raise ValueError("projectName must be a non-empty string")

        mode = WrapMode(data.get("mode") or WrapMode.QUICK.value)
        model = WrapModel(data.get("model") or DEFAULT_MODEL.value)
        scope = WrapScope(data.get("scope") or WrapScope.CONVERSATION.value)

        raw_messages = data.get("messages") or []
        if not isinstance(raw_messages, list):
            raise ValueError("messages must be a list")
        messages = [WrapMessage.from_dict(m) for m in raw_messages]

        filters = WrapFilters.from_dict(data.get("filters"))

        user_instruction = data.get("userInstruction")
        if user_instruction is not None and not isinstance(user_instruction, str):
            raise ValueError("userInstruction must be a string when provided")

        return cls(
            project_id=project_id,
            project_name=project_name.strip(),
            mode=mode,
            model=model,
            scope=scope,
            messages=messages,
            filters=filters,
            user_instruction=user_instruction.strip() if user_instruction else None,
        )


# ---------------------------------------------------------------------------
# Analysis results & stats.


@dataclass(frozen=True)
class WrapSplitSuggestion:
    """One proposed sub-wrap when the topic drift detector wants a split."""

    title: str
    summary: str
    message_ids: tuple[int, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "messageIds": list(self.message_ids),
        }


@dataclass
class WrapAnalysisResult:
    """Structured output of the LLM/heuristic analysis step.

    Everything the Markdown writer needs to render a wrap file is here.
    Optional fields use ``None`` / empty lists so the frontmatter writer
    can safely skip them without conditional logic at every callsite.
    """

    title: str
    topic: str
    topic_drift: bool
    should_split: bool
    split_suggestions: list[WrapSplitSuggestion]
    summary: str
    key_decisions: list[str]
    requirements: list[str]
    todos: list[str]
    filtering_summary: str
    tags: list[str]
    markdown: str
    risks: Optional[list[str]] = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "topic": self.topic,
            "topicDrift": self.topic_drift,
            "shouldSplit": self.should_split,
            "splitSuggestions": [s.to_dict() for s in self.split_suggestions],
            "summary": self.summary,
            "keyDecisions": list(self.key_decisions),
            "requirements": list(self.requirements),
            "todos": list(self.todos),
            "risks": list(self.risks) if self.risks else None,
            "filteringSummary": self.filtering_summary,
            "tags": list(self.tags),
            "markdown": self.markdown,
        }


@dataclass
class ProjectMemoryStats:
    """Dashboard summary for one project's wrap directory."""

    project_id: int
    project_name: str
    wrap_count: int
    memory_size_bytes: int
    last_wrapped_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "projectName": self.project_name,
            "wrapCount": self.wrap_count,
            "memorySizeBytes": self.memory_size_bytes,
            "lastWrappedAt": (
                self.last_wrapped_at.isoformat() if self.last_wrapped_at else None
            ),
        }


__all__ = [
    "FilterAction",
    "ProjectMemoryStats",
    "WrapAnalysisResult",
    "WrapFilters",
    "WrapMessage",
    "WrapMode",
    "WrapModel",
    "WrapRequest",
    "WrapScope",
    "WrapSplitSuggestion",
]
