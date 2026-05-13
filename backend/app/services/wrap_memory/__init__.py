"""Wrap (project memory) service package.

Phase 1 (shipped):
    * types, default settings, filename + Markdown writer, storage paths.

Phase 2 (shipped):
    * LLM provider adapter (mock + LLM-backed).
    * Prompt builders + JSON parser.
    * ``create_wrap_draft`` orchestration entry point.

Phase 3 (shipped):
    * DB-aware ``service.py`` glue (build_request_from_conversation,
      quick_wrap_draft, save_wrap_draft) used by the HTTP routes.

Phase 4 (shipped):
    * ``wrap_draft`` — unified entry that lets the Advanced UI thread
      model + filters + user instruction into the same pipeline.

Phase 5 (this milestone):
    * Routine Wrap config (per-project), due-date math, and a
      DB-aware ``routine_service`` for read/update/dismiss/mark-run.

Nothing here talks to Flask globals at import time, so tests can
exercise the whole module without spinning up an app context.
"""

from __future__ import annotations

from .draft_service import create_wrap_draft
from .filename import (
    HASH_LENGTH,
    HASH_PREFIX,
    SLUG_MAX_LENGTH,
    build_wrap_file_name,
    short_hash,
    slugify,
)
from .llm_adapter import MODEL_ROUTES, ModelRoute, route_for_model
from .markdown_builder import (
    WrapMarkdownMeta,
    build_frontmatter,
    build_markdown_with_frontmatter,
    format_bytes,
)
from .parser import WrapParseError, parse_wrap_analysis_result
from .routine import (
    AUTO_SAVE_ALLOWED,
    DEFAULT_DAY_OF_WEEK,
    DEFAULT_FREQUENCY,
    DEFAULT_ROUTINE_MODEL,
    DEFAULT_SCOPE,
    DISMISS_QUIET_PERIOD,
    FREQUENCY_INTERVALS,
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
from .prompts import (
    MAX_MESSAGES_IN_PROMPT,
    MESSAGE_CHAR_LIMIT,
    TRANSCRIPT_CHAR_LIMIT,
    build_wrap_system_prompt,
    build_wrap_user_prompt,
)
from .providers import (
    LLMBackedWrapProvider,
    LLMCallable,
    MockWrapProvider,
    WrapProvider,
    WrapProviderError,
    get_wrap_provider,
)
from .routine_service import (
    build_routine_request,
    compute_status as compute_routine_status,
    load_or_default as load_routine_config,
    mark_dismissed as mark_routine_dismissed,
    mark_run as mark_routine_run,
    save_config as save_routine_config,
)
from .stats_service import (
    WRAP_FILE_SUFFIX,
    get_all_project_memory_stats,
    get_project_memory_stats,
)
from .service import (
    SavedWrap,
    WrapDraftBundle,
    WrapServiceError,
    build_request_from_conversation,
    quick_wrap_draft,
    save_wrap_draft,
    wrap_draft,
    wrap_draft_from_request,
)
from .settings import (
    DEFAULT_FILTERS,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_ROUTINE_INTERVAL_DAYS,
    WrapDefaults,
    default_settings,
)
from .storage import (
    PROJECT_MEMORY_DIRNAME,
    WRAPS_DIRNAME,
    ensure_wraps_dir,
    get_project_memory_dir,
    get_wraps_dir,
)
from .types import (
    FilterAction,
    ProjectMemoryStats,
    WrapAnalysisResult,
    WrapFilters,
    WrapMessage,
    WrapMode,
    WrapModel,
    WrapRequest,
    WrapScope,
    WrapSplitSuggestion,
)

__all__ = [
    "AUTO_SAVE_ALLOWED",
    "DEFAULT_DAY_OF_WEEK",
    "DEFAULT_FILTERS",
    "DEFAULT_FREQUENCY",
    "DEFAULT_MODE",
    "DEFAULT_MODEL",
    "DEFAULT_ROUTINE_INTERVAL_DAYS",
    "DEFAULT_ROUTINE_MODEL",
    "DEFAULT_SCOPE",
    "DISMISS_QUIET_PERIOD",
    "FREQUENCY_INTERVALS",
    "FilterAction",
    "REVIEW_REQUIRED",
    "RoutineDayOfWeek",
    "RoutineFrequency",
    "RoutineModel",
    "RoutineScope",
    "RoutineWrapConfig",
    "HASH_LENGTH",
    "HASH_PREFIX",
    "LLMBackedWrapProvider",
    "LLMCallable",
    "MAX_MESSAGES_IN_PROMPT",
    "MESSAGE_CHAR_LIMIT",
    "MODEL_ROUTES",
    "MockWrapProvider",
    "ModelRoute",
    "PROJECT_MEMORY_DIRNAME",
    "ProjectMemoryStats",
    "SLUG_MAX_LENGTH",
    "SavedWrap",
    "TRANSCRIPT_CHAR_LIMIT",
    "WRAPS_DIRNAME",
    "WRAP_FILE_SUFFIX",
    "WrapAnalysisResult",
    "WrapDefaults",
    "WrapDraftBundle",
    "WrapFilters",
    "WrapMarkdownMeta",
    "WrapMessage",
    "WrapMode",
    "WrapModel",
    "WrapParseError",
    "WrapProvider",
    "WrapProviderError",
    "WrapRequest",
    "WrapScope",
    "WrapServiceError",
    "WrapSplitSuggestion",
    "build_frontmatter",
    "build_markdown_with_frontmatter",
    "build_request_from_conversation",
    "build_routine_request",
    "build_wrap_file_name",
    "build_wrap_system_prompt",
    "build_wrap_user_prompt",
    "coerce_invariants",
    "compute_routine_status",
    "create_wrap_draft",
    "default_settings",
    "ensure_wraps_dir",
    "format_bytes",
    "get_all_project_memory_stats",
    "get_project_memory_dir",
    "get_project_memory_stats",
    "get_wrap_provider",
    "get_wraps_dir",
    "is_routine_wrap_due",
    "load_routine_config",
    "mark_routine_dismissed",
    "mark_routine_run",
    "parse_wrap_analysis_result",
    "quick_wrap_draft",
    "resolve_routine_model",
    "route_for_model",
    "save_routine_config",
    "save_wrap_draft",
    "short_hash",
    "slugify",
    "wrap_draft",
    "wrap_draft_from_request",
]
