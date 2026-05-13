"""Unit tests for the Wrap (project memory) service package.

Phase 1 scope:
* default configuration is what the spec asks for
* filename generation handles ASCII / CJK / pure-symbol titles
* Markdown frontmatter renders the expected fields in the expected order
* ``format_bytes`` produces human-readable strings across every unit
* Storage paths point at the right place + optional override works

These tests are pure-Python and don't need Flask or the DB; running
them is just ``python -m unittest`` from ``backend/`` with no env
setup required.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

# Make ``backend/`` importable when this file is run directly via
# ``python tests/test_wrap_memory.py`` (the discovery path
# ``python -m unittest`` also benefits from this — it lets the test
# work whether cwd is ``backend/`` or the repo root).
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.wrap_memory import (  # noqa: E402
    DEFAULT_FILTERS,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_ROUTINE_INTERVAL_DAYS,
    FilterAction,
    HASH_PREFIX,
    SLUG_MAX_LENGTH,
    WrapAnalysisResult,
    WrapFilters,
    WrapMarkdownMeta,
    WrapMode,
    WrapModel,
    WrapRequest,
    WrapScope,
    build_frontmatter,
    build_markdown_with_frontmatter,
    build_wrap_file_name,
    default_settings,
    ensure_wraps_dir,
    format_bytes,
    get_project_memory_dir,
    get_wraps_dir,
    short_hash,
    slugify,
)


# ---------------------------------------------------------------------------
# Defaults.


class DefaultSettingsTest(unittest.TestCase):
    """The values the product spec calls out by name."""

    def test_default_model_is_deepseek_v4_flash(self) -> None:
        self.assertEqual(DEFAULT_MODEL, WrapModel.DEEPSEEK_V4_FLASH)
        self.assertEqual(DEFAULT_MODEL.value, "deepseek-v4-flash")

    def test_default_filters_match_spec(self) -> None:
        # Spec: codeBlocks=summarize, images=exclude, promptText=summarize,
        # logs=summarize, offTopic=exclude.
        self.assertEqual(DEFAULT_FILTERS.code_blocks, FilterAction.SUMMARIZE)
        self.assertEqual(DEFAULT_FILTERS.images, FilterAction.EXCLUDE)
        self.assertEqual(DEFAULT_FILTERS.prompt_text, FilterAction.SUMMARIZE)
        self.assertEqual(DEFAULT_FILTERS.logs, FilterAction.SUMMARIZE)
        self.assertEqual(DEFAULT_FILTERS.off_topic, FilterAction.EXCLUDE)

    def test_default_filters_to_dict_uses_camelcase_keys(self) -> None:
        # Wire format is camelCase; assert so the frontend contract is locked.
        self.assertEqual(
            DEFAULT_FILTERS.to_dict(),
            {
                "codeBlocks": "summarize",
                "images": "exclude",
                "promptText": "summarize",
                "logs": "summarize",
                "offTopic": "exclude",
            },
        )

    def test_default_routine_interval_is_weekly(self) -> None:
        self.assertEqual(DEFAULT_ROUTINE_INTERVAL_DAYS, 7)

    def test_default_mode_is_quick(self) -> None:
        self.assertEqual(DEFAULT_MODE, WrapMode.QUICK)

    def test_default_settings_returns_fresh_bundle(self) -> None:
        a = default_settings()
        b = default_settings()
        self.assertEqual(a, b)  # equal by value
        self.assertEqual(a.to_dict()["model"], "deepseek-v4-flash")

    def test_filters_from_dict_merges_with_defaults(self) -> None:
        merged = WrapFilters.from_dict({"images": "keep"})
        self.assertEqual(merged.images, FilterAction.KEEP)
        # Untouched buckets still reflect defaults.
        self.assertEqual(merged.code_blocks, DEFAULT_FILTERS.code_blocks)
        self.assertEqual(merged.off_topic, DEFAULT_FILTERS.off_topic)

    def test_filters_from_dict_rejects_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            WrapFilters.from_dict({"images": "maybe"})


# ---------------------------------------------------------------------------
# Filename generation.


class FilenameTest(unittest.TestCase):
    """``build_wrap_file_name`` is the spec the dashboard reader will rely on."""

    REF_TIME = datetime(2026, 5, 13, 16, 41, tzinfo=timezone.utc)
    REF_TIMESTAMP = "2026-05-13_16-41"

    def test_ascii_title_produces_slug(self) -> None:
        name = build_wrap_file_name("Auth Design Review", self.REF_TIME)
        self.assertEqual(name, f"{self.REF_TIMESTAMP}_auth-design-review.md")

    def test_ascii_title_collapses_punctuation(self) -> None:
        name = build_wrap_file_name("Wrap #1: Big-O & friends!", self.REF_TIME)
        self.assertEqual(name, f"{self.REF_TIMESTAMP}_wrap-1-big-o-friends.md")

    def test_accented_letters_are_folded_to_ascii(self) -> None:
        name = build_wrap_file_name("Café déjà vu", self.REF_TIME)
        self.assertEqual(name, f"{self.REF_TIMESTAMP}_cafe-deja-vu.md")

    def test_chinese_title_falls_back_to_hash(self) -> None:
        # Spec example: ``YYYY-MM-DD_HH-mm_wrap-a8f3.md`` for CJK titles.
        name = build_wrap_file_name("中文记忆 整理", self.REF_TIME)
        self.assertTrue(
            name.startswith(f"{self.REF_TIMESTAMP}_{HASH_PREFIX}"),
            msg=f"expected hash-fallback filename, got {name!r}",
        )
        self.assertTrue(name.endswith(".md"))
        # Hash is deterministic for stable titles.
        again = build_wrap_file_name("中文记忆 整理", self.REF_TIME)
        self.assertEqual(name, again)

    def test_emoji_title_falls_back_to_hash(self) -> None:
        name = build_wrap_file_name("🚀🚀🚀", self.REF_TIME)
        self.assertRegex(
            name,
            rf"^{re.escape(self.REF_TIMESTAMP)}_{re.escape(HASH_PREFIX)}[0-9a-f]+\.md$",
        )

    def test_empty_title_still_returns_unique_filename(self) -> None:
        name = build_wrap_file_name("", self.REF_TIME)
        # Two empty titles in the same minute should collide on hash
        # (deterministic) but still produce a valid filename.
        again = build_wrap_file_name("", self.REF_TIME)
        self.assertEqual(name, again)
        self.assertTrue(name.endswith(".md"))

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime(2026, 5, 13, 16, 41)
        name = build_wrap_file_name("Hello", naive)
        self.assertEqual(name, f"{self.REF_TIMESTAMP}_hello.md")

    def test_no_datetime_falls_back_to_now(self) -> None:
        # Smoke check only — we don't want a flaky time-sensitive test,
        # just that the function doesn't blow up.
        name = build_wrap_file_name("Auth", None)
        self.assertRegex(
            name, r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_auth\.md$"
        )

    def test_very_long_title_is_capped(self) -> None:
        long_title = "word " * 80  # 400 chars
        name = build_wrap_file_name(long_title, self.REF_TIME)
        slug = name.removeprefix(f"{self.REF_TIMESTAMP}_").removesuffix(".md")
        self.assertLessEqual(len(slug), SLUG_MAX_LENGTH)

    def test_slugify_returns_empty_on_cjk_only_input(self) -> None:
        self.assertEqual(slugify("仅中文"), "")

    def test_short_hash_is_deterministic_and_length_bounded(self) -> None:
        self.assertEqual(short_hash("foo"), short_hash("foo"))
        self.assertNotEqual(short_hash("foo"), short_hash("bar"))
        # Length clamp: even length=0 produces something usable.
        clamped = short_hash("anything", length=0)
        self.assertGreaterEqual(len(clamped), 2)


# ---------------------------------------------------------------------------
# Markdown / frontmatter rendering.


def _sample_result(markdown: str | None = None) -> WrapAnalysisResult:
    return WrapAnalysisResult(
        title="Auth Design Review",
        topic="Authentication",
        topic_drift=False,
        should_split=False,
        split_suggestions=[],
        summary="Discussion of token formats and refresh flow.",
        key_decisions=["Use JWT", "Rotate refresh tokens every 30d"],
        requirements=["Support password + OAuth"],
        todos=["Wire login endpoint"],
        filtering_summary="Code blocks summarized; off-topic excluded.",
        tags=["auth", "design"],
        markdown=markdown if markdown is not None else "",
    )


class FrontmatterTest(unittest.TestCase):
    REF_TIME = datetime(2026, 5, 13, 16, 41, tzinfo=timezone.utc)

    def _make_meta(self, **overrides) -> WrapMarkdownMeta:
        kwargs = dict(
            project_id=42,
            wrap_mode=WrapMode.ADVANCED,
            model=WrapModel.DEEPSEEK_V4_FLASH,
            created_at=self.REF_TIME,
        )
        kwargs.update(overrides)
        return WrapMarkdownMeta(**kwargs)

    def test_frontmatter_contains_all_required_keys_in_order(self) -> None:
        block = build_frontmatter(self._make_meta(), _sample_result())
        lines = block.splitlines()

        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[-1], "---")

        # Spec: title → created_at → project_id → wrap_type → model → tags.
        keys_in_order = [line.split(":", 1)[0] for line in lines[1:-1]]
        self.assertEqual(
            keys_in_order,
            ["title", "created_at", "project_id", "wrap_type", "model", "tags"],
        )

    def test_frontmatter_values_are_quoted_strings_where_appropriate(self) -> None:
        block = build_frontmatter(self._make_meta(), _sample_result())
        self.assertIn('title: "Auth Design Review"', block)
        self.assertIn('wrap_type: "advanced"', block)
        self.assertIn('model: "deepseek-v4-flash"', block)
        self.assertIn('project_id: 42', block)  # int stays unquoted
        self.assertIn('tags: ["auth", "design"]', block)
        self.assertIn('created_at: "2026-05-13T16:41:00+00:00"', block)

    def test_frontmatter_escapes_double_quotes_and_newlines(self) -> None:
        meta = self._make_meta(title_override='Bad "title"\nwith newline')
        block = build_frontmatter(meta, _sample_result())
        self.assertIn(r'title: "Bad \"title\" with newline"', block)
        self.assertNotIn("\n  ", block)  # no stray indentation

    def test_extra_tags_are_merged_without_duplicates(self) -> None:
        meta = self._make_meta(extra_tags=("auth", "review"))
        block = build_frontmatter(meta, _sample_result())
        self.assertIn('tags: ["auth", "design", "review"]', block)

    def test_build_markdown_emits_body_when_result_has_markdown(self) -> None:
        result = _sample_result(markdown="# Custom\n\nbody here")
        out = build_markdown_with_frontmatter(result, self._make_meta())
        self.assertTrue(out.startswith("---\n"))
        self.assertIn("# Custom", out)
        self.assertTrue(out.endswith("\n"))

    def test_build_markdown_generates_fallback_body_when_empty(self) -> None:
        result = _sample_result(markdown="")
        out = build_markdown_with_frontmatter(result, self._make_meta())
        # Frontmatter + non-empty body.
        head, _, body = out.partition("\n---\n")
        self.assertTrue(head.startswith("---\n"))
        self.assertIn("# Auth Design Review", body)
        self.assertIn("## Summary", body)
        self.assertIn("- Use JWT", body)
        self.assertIn("## Filtering", body)

    def test_build_markdown_uses_title_override(self) -> None:
        meta = self._make_meta(title_override="Custom Title")
        out = build_markdown_with_frontmatter(_sample_result(), meta)
        self.assertIn('title: "Custom Title"', out)

    def test_build_markdown_works_with_chinese_title(self) -> None:
        result = _sample_result()
        result.title = "鉴权设计评审"
        meta = self._make_meta()
        out = build_markdown_with_frontmatter(result, meta)
        self.assertIn('title: "鉴权设计评审"', out)
        # Filename for the same title falls back to a hash.
        fname = build_wrap_file_name(result.title, self.REF_TIME)
        self.assertTrue(fname.endswith(".md"))
        self.assertIn(HASH_PREFIX, fname)


# ---------------------------------------------------------------------------
# format_bytes.


class FormatBytesTest(unittest.TestCase):
    def test_zero(self) -> None:
        self.assertEqual(format_bytes(0), "0 B")

    def test_bytes_below_kb(self) -> None:
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1023), "1023 B")

    def test_kilobytes(self) -> None:
        self.assertEqual(format_bytes(1024), "1 KB")
        # 1.5 KB
        self.assertEqual(format_bytes(1024 + 512), "1.5 KB")

    def test_megabytes(self) -> None:
        self.assertEqual(format_bytes(1024 * 1024), "1 MB")
        self.assertEqual(format_bytes(int(1.5 * 1024 * 1024)), "1.5 MB")

    def test_gigabytes(self) -> None:
        self.assertEqual(format_bytes(2 * 1024 ** 3), "2 GB")

    def test_terabytes(self) -> None:
        self.assertEqual(format_bytes(3 * 1024 ** 4), "3 TB")

    def test_huge_value_clamps_to_largest_unit(self) -> None:
        out = format_bytes(10 ** 20)
        # Largest supported unit is TB; the number gets very big but
        # the suffix stays "TB" rather than crashing.
        self.assertTrue(out.endswith(" TB"), msg=out)

    def test_negative_treated_as_zero(self) -> None:
        self.assertEqual(format_bytes(-50), "0 B")

    def test_non_numeric_returns_zero_bytes(self) -> None:
        self.assertEqual(format_bytes("not a number"), "0 B")  # type: ignore[arg-type]

    def test_float_input_supported(self) -> None:
        # 1.5 KB worth of bytes as a float.
        self.assertEqual(format_bytes(1024 * 1.5), "1.5 KB")


# ---------------------------------------------------------------------------
# Storage paths.


class StoragePathTest(unittest.TestCase):
    def test_get_project_memory_dir_uses_supplied_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = get_project_memory_dir(base_dir=tmp)
            self.assertEqual(path, Path(tmp) / "project-memory")

    def test_get_wraps_dir_appends_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                get_wraps_dir(base_dir=tmp),
                Path(tmp) / "project-memory" / "wraps",
            )
            self.assertEqual(
                get_wraps_dir(7, base_dir=tmp),
                Path(tmp) / "project-memory" / "wraps" / "7",
            )

    def test_get_wraps_dir_rejects_negative_project_id(self) -> None:
        with self.assertRaises(ValueError):
            get_wraps_dir(-1, base_dir="/tmp")

    def test_ensure_wraps_dir_creates_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_wraps_dir(42, base_dir=tmp)
            self.assertTrue(created.exists() and created.is_dir())

    def test_default_base_dir_points_at_backend_instance(self) -> None:
        # Doesn't create anything on disk — just checks the resolution
        # heuristic lands inside backend/instance/. We can't assert
        # exact equality (tests might be run from anywhere), so check
        # the suffix.
        path = get_project_memory_dir()
        parts = path.parts
        self.assertIn("instance", parts)
        self.assertEqual(path.name, "project-memory")


# ---------------------------------------------------------------------------
# Enum strictness — pins down what the spec calls "only these values allowed".


class EnumStrictnessTest(unittest.TestCase):
    """Negative assertions: typos and stale model ids must blow up."""

    def test_wrap_model_has_exactly_three_values(self) -> None:
        # If someone adds a 4th model without bumping the spec, this fails
        # loudly. Spec: deepseek-v4-flash / gemini-3.1-flash / gpt-5.4-nano.
        self.assertEqual(
            {m.value for m in WrapModel},
            {"deepseek-v4-flash", "gemini-3.1-flash", "gpt-5.4-nano"},
        )

    def test_wrap_model_rejects_unknown_value(self) -> None:
        for bad in ["gpt-4", "deepseek-chat", "", "DEEPSEEK-V4-FLASH", None]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    WrapModel(bad)  # type: ignore[arg-type]

    def test_wrap_mode_has_exactly_three_values(self) -> None:
        self.assertEqual(
            {m.value for m in WrapMode},
            {"quick", "advanced", "routine"},
        )

    def test_wrap_mode_rejects_unknown_value(self) -> None:
        for bad in ["instant", "manual", "", "QUICK"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    WrapMode(bad)

    def test_filter_action_has_exactly_three_values(self) -> None:
        self.assertEqual(
            {a.value for a in FilterAction},
            {"keep", "summarize", "exclude"},
        )

    def test_filter_action_rejects_unknown_value(self) -> None:
        with self.assertRaises(ValueError):
            FilterAction("strip")

    def test_wrap_scope_has_two_values(self) -> None:
        self.assertEqual(
            {s.value for s in WrapScope},
            {"conversation", "project"},
        )

    def test_wrap_filters_is_immutable(self) -> None:
        # Frozen dataclass → catching a typo at assignment time means we
        # never silently mutate the module-level DEFAULT_FILTERS singleton.
        with self.assertRaises(FrozenInstanceError):
            DEFAULT_FILTERS.code_blocks = FilterAction.KEEP  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Frontmatter round-trip — write with our hand-rolled YAML, parse back with
# a minimal stdlib-only reader. Pins down the field values *and* their types.


def _parse_simple_yaml_frontmatter(block: str) -> dict:
    """Mini YAML reader: handles the exact subset our writer emits.

    We never depend on PyYAML at runtime, so the test parser is also
    PyYAML-free — using anything else would mask a writer regression
    behind a forgiving parser.
    """
    out: dict = {}
    lines = [ln for ln in block.splitlines() if ln and ln != "---"]
    for line in lines:
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            if not inner:
                out[key] = []
            else:
                items: list[str] = []
                # naive but adequate: split on ", " between quoted strings
                for chunk in re.findall(r'"((?:[^"\\]|\\.)*)"', inner):
                    items.append(chunk.replace('\\"', '"').replace("\\\\", "\\"))
                out[key] = items
        elif raw.startswith('"') and raw.endswith('"'):
            out[key] = (
                raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            )
        elif raw in {"true", "false"}:
            out[key] = raw == "true"
        else:
            try:
                out[key] = int(raw)
            except ValueError:
                out[key] = raw
    return out


class FrontmatterRoundTripTest(unittest.TestCase):
    """Write → parse → assert. Catches escaping / ordering / typing bugs."""

    REF_TIME = datetime(2026, 5, 13, 16, 41, tzinfo=timezone.utc)

    def _build(self, **overrides) -> str:
        meta_kwargs = dict(
            project_id=42,
            wrap_mode=WrapMode.ADVANCED,
            model=WrapModel.GEMINI_31_FLASH,
            created_at=self.REF_TIME,
        )
        meta_kwargs.update(overrides.pop("meta", {}))
        meta = WrapMarkdownMeta(**meta_kwargs)
        result = _sample_result()
        for k, v in overrides.items():
            setattr(result, k, v)
        return build_frontmatter(meta, result)

    def test_all_six_required_fields_present(self) -> None:
        parsed = _parse_simple_yaml_frontmatter(self._build())
        self.assertEqual(
            set(parsed.keys()),
            {"title", "created_at", "project_id", "wrap_type", "model", "tags"},
        )

    def test_field_types_after_round_trip(self) -> None:
        parsed = _parse_simple_yaml_frontmatter(self._build())
        self.assertIsInstance(parsed["title"], str)
        self.assertIsInstance(parsed["created_at"], str)
        self.assertIsInstance(parsed["project_id"], int)
        self.assertIsInstance(parsed["wrap_type"], str)
        self.assertIsInstance(parsed["model"], str)
        self.assertIsInstance(parsed["tags"], list)

    def test_field_values_after_round_trip(self) -> None:
        parsed = _parse_simple_yaml_frontmatter(self._build())
        self.assertEqual(parsed["title"], "Auth Design Review")
        self.assertEqual(parsed["created_at"], "2026-05-13T16:41:00+00:00")
        self.assertEqual(parsed["project_id"], 42)
        self.assertEqual(parsed["wrap_type"], "advanced")
        self.assertEqual(parsed["model"], "gemini-3.1-flash")
        self.assertEqual(parsed["tags"], ["auth", "design"])

    def test_chinese_title_survives_round_trip(self) -> None:
        parsed = _parse_simple_yaml_frontmatter(
            self._build(title="鉴权设计评审")
        )
        self.assertEqual(parsed["title"], "鉴权设计评审")

    def test_quotes_in_title_survive_round_trip(self) -> None:
        parsed = _parse_simple_yaml_frontmatter(
            self._build(title='Talk about "JWT vs Cookies"')
        )
        self.assertEqual(parsed["title"], 'Talk about "JWT vs Cookies"')

    def test_newlines_in_title_are_collapsed(self) -> None:
        # Newlines inside the title would break the frontmatter block;
        # the writer must collapse them silently.
        block = self._build(title="line one\nline two\rline three")
        # Sanity: still a parseable, exactly-one-line title.
        title_lines = [ln for ln in block.splitlines() if ln.startswith("title:")]
        self.assertEqual(len(title_lines), 1)


# ---------------------------------------------------------------------------
# Strict filename shape — checked against a single regex so the dashboard
# scanner in Phase 3 can rely on the exact format.


FILENAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"_(?P<time>\d{2}-\d{2})"
    r"_(?P<tail>[a-z0-9-]+)"
    r"\.md$"
)


class FilenameShapeTest(unittest.TestCase):
    REF_TIME = datetime(2026, 5, 13, 16, 41, tzinfo=timezone.utc)

    def _assert_shape(self, name: str) -> re.Match:
        match = FILENAME_RE.fullmatch(name)
        self.assertIsNotNone(
            match, msg=f"filename {name!r} does not match {FILENAME_RE.pattern!r}"
        )
        return match  # type: ignore[return-value]

    def test_ascii_title_matches_strict_pattern(self) -> None:
        match = self._assert_shape(
            build_wrap_file_name("Auth Design Review", self.REF_TIME)
        )
        self.assertEqual(match["date"], "2026-05-13")
        self.assertEqual(match["time"], "16-41")
        self.assertEqual(match["tail"], "auth-design-review")

    def test_chinese_title_matches_strict_pattern_with_hash_tail(self) -> None:
        match = self._assert_shape(
            build_wrap_file_name("鉴权设计评审", self.REF_TIME)
        )
        self.assertTrue(match["tail"].startswith(HASH_PREFIX))

    def test_empty_title_matches_strict_pattern(self) -> None:
        self._assert_shape(build_wrap_file_name("", self.REF_TIME))

    def test_long_title_matches_strict_pattern(self) -> None:
        match = self._assert_shape(
            build_wrap_file_name("word " * 80, self.REF_TIME)
        )
        self.assertLessEqual(len(match["tail"]), SLUG_MAX_LENGTH)

    def test_mixed_chinese_english_title_keeps_ascii_part(self) -> None:
        # "Backend 鉴权 design" → ASCII portion still slugifies usefully,
        # CJK characters are dropped (not transliterated). This is the
        # documented behavior.
        name = build_wrap_file_name("Backend 鉴权 design", self.REF_TIME)
        match = self._assert_shape(name)
        self.assertEqual(match["tail"], "backend-design")

    def test_pure_punctuation_title_falls_back_to_hash(self) -> None:
        name = build_wrap_file_name("!!! ???", self.REF_TIME)
        match = self._assert_shape(name)
        self.assertTrue(match["tail"].startswith(HASH_PREFIX))

    def test_control_characters_are_stripped(self) -> None:
        # Control chars must never make it into the filename or the
        # filesystem will reject the write on Windows / NTFS.
        name = build_wrap_file_name("foo\x00\x07bar", self.REF_TIME)
        match = self._assert_shape(name)
        self.assertEqual(match["tail"], "foo-bar")

    def test_filename_is_lowercase_only(self) -> None:
        # Case-insensitive filesystems (macOS APFS default, NTFS) would
        # collide two wraps that only differ in case.
        name = build_wrap_file_name("MiXeD CASE Title", self.REF_TIME)
        match = self._assert_shape(name)
        self.assertEqual(match["tail"], match["tail"].lower())


# ---------------------------------------------------------------------------
# format_bytes boundary values — pin the unit-switch points.


class FormatBytesBoundaryTest(unittest.TestCase):
    def test_one_byte(self) -> None:
        self.assertEqual(format_bytes(1), "1 B")

    def test_just_below_kb(self) -> None:
        self.assertEqual(format_bytes(1023), "1023 B")

    def test_exact_kb_boundary(self) -> None:
        # 1024 B is the moment we flip to KB.
        self.assertEqual(format_bytes(1024), "1 KB")

    def test_just_below_mb(self) -> None:
        # 1 MB - 1 B. 1023.999… KB should round-trip to "1024 KB" in our
        # one-decimal output (not flip to MB until the full 1024^2).
        out = format_bytes(1024 ** 2 - 1)
        self.assertTrue(out.endswith(" KB"), msg=out)

    def test_exact_mb_boundary(self) -> None:
        self.assertEqual(format_bytes(1024 ** 2), "1 MB")

    def test_two_and_a_half_mb(self) -> None:
        self.assertEqual(format_bytes(int(2.5 * 1024 ** 2)), "2.5 MB")

    def test_one_decimal_place_never_shows_trailing_zero(self) -> None:
        # 2 KB exactly should be "2 KB", not "2.0 KB".
        self.assertEqual(format_bytes(2 * 1024), "2 KB")


# ---------------------------------------------------------------------------
# WrapRequest input validation — locks down the Phase 2 HTTP contract.


class WrapRequestParsingTest(unittest.TestCase):
    def _minimal_payload(self, **overrides) -> dict:
        base = {
            "projectId": 7,
            "projectName": "Demo",
            "mode": "quick",
            "model": "deepseek-v4-flash",
            "scope": "conversation",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            "filters": {"images": "keep"},
        }
        base.update(overrides)
        return base

    def test_minimal_valid_payload_parses(self) -> None:
        req = WrapRequest.from_dict(self._minimal_payload())
        self.assertEqual(req.project_id, 7)
        self.assertEqual(req.project_name, "Demo")
        self.assertEqual(req.mode, WrapMode.QUICK)
        self.assertEqual(req.model, WrapModel.DEEPSEEK_V4_FLASH)
        self.assertEqual(req.scope, WrapScope.CONVERSATION)
        self.assertEqual(len(req.messages), 2)
        # Untouched filter keys fall back to DEFAULT_FILTERS.
        self.assertEqual(req.filters.images, FilterAction.KEEP)
        self.assertEqual(req.filters.code_blocks, DEFAULT_FILTERS.code_blocks)

    def test_missing_project_id_raises(self) -> None:
        payload = self._minimal_payload()
        payload.pop("projectId")
        with self.assertRaises(ValueError):
            WrapRequest.from_dict(payload)

    def test_string_project_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            WrapRequest.from_dict(self._minimal_payload(projectId="42"))

    def test_blank_project_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            WrapRequest.from_dict(self._minimal_payload(projectName="   "))

    def test_unknown_model_raises(self) -> None:
        # The whole point of WrapModel being narrow: typos at the API
        # boundary surface as 400s, not silent fallbacks.
        with self.assertRaises(ValueError):
            WrapRequest.from_dict(self._minimal_payload(model="gpt-4"))

    def test_unknown_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            WrapRequest.from_dict(self._minimal_payload(mode="manual"))

    def test_bad_role_raises(self) -> None:
        payload = self._minimal_payload()
        payload["messages"] = [{"role": "robot", "content": "hi"}]
        with self.assertRaises(ValueError):
            WrapRequest.from_dict(payload)

    def test_non_string_content_raises(self) -> None:
        payload = self._minimal_payload()
        payload["messages"] = [{"role": "user", "content": 42}]
        with self.assertRaises(ValueError):
            WrapRequest.from_dict(payload)

    def test_user_instruction_is_normalized(self) -> None:
        req = WrapRequest.from_dict(
            self._minimal_payload(userInstruction="   focus on auth   ")
        )
        self.assertEqual(req.user_instruction, "focus on auth")

    def test_user_instruction_omitted_is_none(self) -> None:
        req = WrapRequest.from_dict(self._minimal_payload())
        self.assertIsNone(req.user_instruction)


if __name__ == "__main__":
    unittest.main()
