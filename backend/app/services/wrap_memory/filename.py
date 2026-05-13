"""File-name helpers for wrap Markdown files.

A wrap file lives at::

    <wraps_dir>/YYYY-MM-DD_HH-mm_<slug-or-hash>.md

Rules:

* If the title produces a stable ASCII slug (e.g. "Auth design review"
  → ``auth-design-review``), use it verbatim.
* If the slug is empty (e.g. CJK-only titles, emoji titles), fall back
  to a deterministic short hash: ``wrap-a8f3``. This keeps filenames
  POSIX-safe on every filesystem we care about (incl. case-insensitive
  macOS / Windows) while still being unique-enough at the project scope.
* Length cap on the slug portion (60 chars) so a verbose title doesn't
  generate a 250-char filename and trip Windows' MAX_PATH.

Everything in this module is pure / deterministic given a fixed clock —
no global state, no Flask context, safe to call from tests.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

# Public knobs — exported so tests + advanced callers can tune.
SLUG_MAX_LENGTH: int = 60
HASH_LENGTH: int = 4
HASH_PREFIX: str = "wrap-"

# Compiled once; matches anything that isn't [a-z0-9].
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(text: str | None) -> str:
    """Return a lowercase ASCII slug derived from ``text``.

    Empty / fully non-ASCII input returns ``""`` — callers should fall
    back to :func:`short_hash`. This function deliberately doesn't try
    to romanize CJK characters: pinyin-style conversion is locale-
    sensitive and a moving target, and the hash fallback is good
    enough to keep filenames stable.
    """
    if not text:
        return ""

    # NFKD splits accented letters into base + combining mark, then we
    # drop the marks so "café" → "cafe". Anything non-ASCII (CJK, emoji,
    # etc.) is just discarded by the ``ascii`` encode step below.
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")

    # Lowercase + collapse every run of non-alphanumeric into a single dash.
    lowered = ascii_only.lower()
    candidate = _NON_SLUG_CHARS.sub("-", lowered).strip("-")
    if not candidate:
        return ""

    if len(candidate) > SLUG_MAX_LENGTH:
        # Cut on a dash boundary if one exists in the last few chars so
        # we don't slice a word in half. Falls back to a hard cut.
        snippet = candidate[:SLUG_MAX_LENGTH]
        last_dash = snippet.rfind("-")
        if last_dash >= SLUG_MAX_LENGTH - 10:
            snippet = snippet[:last_dash]
        candidate = snippet.strip("-") or candidate[:SLUG_MAX_LENGTH]

    return candidate


def short_hash(text: str | None, length: int = HASH_LENGTH) -> str:
    """Deterministic short hash for slug fallback.

    Uses SHA-1 → hex prefix. Not for cryptographic uniqueness — just
    for filesystem-friendly disambiguation. ``length`` is clamped to a
    safe range so callers can't accidentally generate a 1-char hash.
    """
    safe_length = max(2, min(length, 16))
    seed = (text or "").strip() or "wrap"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return digest[:safe_length]


def _to_naive_utc(dt: datetime | None) -> datetime:
    """Normalize a datetime to a naive-UTC value for filename rendering."""
    base = dt if dt is not None else datetime.now(timezone.utc)
    if base.tzinfo is not None:
        base = base.astimezone(timezone.utc).replace(tzinfo=None)
    return base


def build_wrap_file_name(title: str | None, created_at: datetime | None = None) -> str:
    """Build a wrap filename: ``YYYY-MM-DD_HH-mm_<slug-or-hash>.md``.

    ``title``    — the wrap's display title. If unslugifiable, we use
                   a short hash derived from the title (or from the
                   timestamp as a last resort).
    ``created_at`` — the wrap's creation time. Defaults to ``now()``
                   in UTC; non-UTC datetimes are converted.
    """
    ts = _to_naive_utc(created_at)
    timestamp = ts.strftime("%Y-%m-%d_%H-%M")

    slug = slugify(title)
    if slug:
        return f"{timestamp}_{slug}.md"

    # Hash falls back to title text first; if that's empty too, hash
    # the timestamp so two empty-title wraps in the same minute still
    # collide rather than overwrite each other silently.
    seed = title if (title and title.strip()) else timestamp
    return f"{timestamp}_{HASH_PREFIX}{short_hash(seed)}.md"


__all__ = [
    "HASH_LENGTH",
    "HASH_PREFIX",
    "SLUG_MAX_LENGTH",
    "build_wrap_file_name",
    "short_hash",
    "slugify",
]
