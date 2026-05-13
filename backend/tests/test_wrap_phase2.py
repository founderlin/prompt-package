"""Unit tests for Phase 2 of the Wrap feature.

Coverage:
* ``llm_adapter.route_for_model`` returns the right (provider, model)
  triple for every WrapModel enum value.
* ``build_wrap_user_prompt`` includes the model-agnostic info the
  parser will need to anchor its output (project name, scope, filter
  rules, transcript markers).
* ``parse_wrap_analysis_result`` parses well-formed JSON, tolerates
  Markdown code fences + prefix noise, and raises ``WrapParseError``
  on unparseable input.
* ``MockWrapProvider`` returns a stable, useful result.
* ``LLMBackedWrapProvider`` works end-to-end against an injected fake
  LLM caller (no network, no Flask app context).
* ``create_wrap_draft`` routes through ``get_wrap_provider`` correctly
  and normalizes its output.

Same style as ``test_wrap_memory.py`` — stdlib ``unittest``, no extra
deps.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.wrap_memory import (  # noqa: E402
    DEFAULT_FILTERS,
    LLMBackedWrapProvider,
    MODEL_ROUTES,
    MockWrapProvider,
    WrapAnalysisResult,
    WrapMessage,
    WrapMode,
    WrapModel,
    WrapParseError,
    WrapProvider,
    WrapProviderError,
    WrapRequest,
    WrapScope,
    build_wrap_system_prompt,
    build_wrap_user_prompt,
    create_wrap_draft,
    get_wrap_provider,
    parse_wrap_analysis_result,
    route_for_model,
)
from app.services.wrap_memory.llm_adapter import ModelRoute  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures.


def _make_request(
    *,
    model: WrapModel = WrapModel.DEEPSEEK_V4_FLASH,
    mode: WrapMode = WrapMode.QUICK,
    scope: WrapScope = WrapScope.CONVERSATION,
    project_name: str = "Demo Project",
    project_id: int = 7,
    user_instruction: str | None = None,
    messages: list[WrapMessage] | None = None,
) -> WrapRequest:
    # ``messages or [...]`` would silently swap an empty list for the
    # default — tests that pass ``messages=[]`` mean it.
    if messages is not None:
        msgs = messages
    else:
        msgs = [
            WrapMessage(
                role="user",
                content="Let's design the auth flow.",
                message_id=1,
            ),
            WrapMessage(
                role="assistant",
                content="Sure — token-based with refresh rotation?",
                message_id=2,
            ),
            WrapMessage(
                role="user",
                content="Yes, JWT with 30d refresh.",
                message_id=3,
            ),
        ]
    return WrapRequest(
        project_id=project_id,
        project_name=project_name,
        mode=mode,
        model=model,
        scope=scope,
        messages=msgs,
        filters=DEFAULT_FILTERS,
        user_instruction=user_instruction,
    )


_GOOD_PAYLOAD: dict = {
    "title": "Auth design",
    "topic": "Authentication",
    "topicDrift": False,
    "shouldSplit": False,
    "splitSuggestions": [],
    "summary": "Token-based auth with rotation.",
    "keyDecisions": ["Use JWT", "Rotate refresh every 30 days"],
    "requirements": ["Support password + OAuth"],
    "todos": ["Wire login endpoint"],
    "risks": ["Token theft via XSS"],
    "tags": ["auth", "design"],
    "filteringSummary": "Logs summarized; off-topic excluded.",
    "markdown": "# Auth design\n\n## Summary\nToken-based auth...",
}


# ---------------------------------------------------------------------------
# Model routing.


class ModelRoutingTest(unittest.TestCase):
    def test_every_wrap_model_has_a_route(self) -> None:
        for model in WrapModel:
            with self.subTest(model=model.value):
                route = route_for_model(model)
                self.assertEqual(route.wrap_model, model)
                self.assertTrue(route.provider_id)
                self.assertTrue(route.backend_model)

    def test_deepseek_v4_flash_maps_to_deepseek_backend(self) -> None:
        route = route_for_model(WrapModel.DEEPSEEK_V4_FLASH)
        self.assertEqual(route.provider_id, "deepseek")
        self.assertTrue(
            route.backend_model.startswith("deepseek-"),
            msg=f"expected a deepseek-* backend model, got {route.backend_model!r}",
        )

    def test_gemini_31_flash_maps_to_openrouter_gemini(self) -> None:
        route = route_for_model(WrapModel.GEMINI_31_FLASH)
        self.assertEqual(route.provider_id, "openrouter")
        self.assertIn("gemini", route.backend_model.lower())

    def test_gpt_54_nano_maps_to_openai_backend(self) -> None:
        route = route_for_model(WrapModel.GPT_54_NANO)
        self.assertEqual(route.provider_id, "openai")
        self.assertIn("gpt", route.backend_model.lower())

    def test_model_routes_table_matches_enum(self) -> None:
        # Catch a future enum addition that forgot to add a row.
        self.assertEqual(set(MODEL_ROUTES.keys()), set(WrapModel))

    def test_route_for_model_raises_on_unmapped(self) -> None:
        # Synthetic case: a fake enum value that isn't in MODEL_ROUTES.
        class FakeModel:
            value = "x"

        with self.assertRaises(KeyError):
            route_for_model(FakeModel())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Prompt builders.


class PromptBuilderTest(unittest.TestCase):
    def test_system_prompt_is_constant_and_mentions_json(self) -> None:
        a = build_wrap_system_prompt()
        b = build_wrap_system_prompt()
        self.assertEqual(a, b)
        # Mandatory contract details.
        self.assertIn("JSON", a)
        self.assertIn("topicDrift", a)
        self.assertIn("shouldSplit", a)
        self.assertIn("filteringSummary", a)
        self.assertIn("markdown", a)

    def test_user_prompt_contains_project_metadata(self) -> None:
        prompt = build_wrap_user_prompt(
            _make_request(project_id=42, project_name="Atlas")
        )
        self.assertIn("Project ID:   42", prompt)
        self.assertIn("Atlas", prompt)

    def test_user_prompt_reflects_scope(self) -> None:
        prompt = build_wrap_user_prompt(_make_request(scope=WrapScope.PROJECT))
        self.assertIn("Multiple conversations", prompt)
        prompt2 = build_wrap_user_prompt(_make_request(scope=WrapScope.CONVERSATION))
        self.assertIn("Single conversation", prompt2)

    def test_user_prompt_includes_all_five_filter_rows(self) -> None:
        prompt = build_wrap_user_prompt(_make_request())
        for label in ("codeBlocks", "images", "promptText", "logs", "offTopic"):
            self.assertIn(label, prompt)

    def test_user_prompt_includes_filter_legend(self) -> None:
        prompt = build_wrap_user_prompt(_make_request())
        for action in ("keep", "summarize", "exclude"):
            self.assertIn(action, prompt)

    def test_user_prompt_renders_messages_in_order(self) -> None:
        prompt = build_wrap_user_prompt(_make_request())
        self.assertIn("[USER", prompt)
        self.assertIn("[ASSISTANT", prompt)
        # First message marker comes before the last one in the string.
        first_pos = prompt.find("#1 [USER")
        last_pos = prompt.find("#3 [USER")
        self.assertGreater(first_pos, -1)
        self.assertGreater(last_pos, first_pos)

    def test_user_prompt_includes_user_instruction_when_set(self) -> None:
        prompt = build_wrap_user_prompt(
            _make_request(user_instruction="focus on backend decisions")
        )
        self.assertIn("focus on backend decisions", prompt)
        self.assertIn("User instruction", prompt)

    def test_user_prompt_omits_user_instruction_section_when_blank(self) -> None:
        prompt = build_wrap_user_prompt(_make_request(user_instruction=None))
        self.assertNotIn("User instruction", prompt)

    def test_user_prompt_handles_empty_transcript_gracefully(self) -> None:
        prompt = build_wrap_user_prompt(_make_request(messages=[]))
        self.assertIn("(no messages provided)", prompt)

    def test_user_prompt_truncates_long_message_with_ellipsis(self) -> None:
        long_msg = WrapMessage(role="user", content="x" * 5000, message_id=1)
        prompt = build_wrap_user_prompt(_make_request(messages=[long_msg]))
        # Body should be capped; we don't pin the exact length but the
        # transcript must not include the full 5000 'x' run.
        self.assertNotIn("x" * 3000, prompt)
        self.assertIn("…", prompt)


# ---------------------------------------------------------------------------
# Parser.


class ParserHappyPathTest(unittest.TestCase):
    def test_clean_json_object_parses(self) -> None:
        result = parse_wrap_analysis_result(json.dumps(_GOOD_PAYLOAD))
        self.assertIsInstance(result, WrapAnalysisResult)
        self.assertEqual(result.title, "Auth design")
        self.assertEqual(result.topic, "Authentication")
        self.assertFalse(result.topic_drift)
        self.assertFalse(result.should_split)
        self.assertEqual(result.summary, "Token-based auth with rotation.")
        self.assertEqual(result.key_decisions, ["Use JWT", "Rotate refresh every 30 days"])
        self.assertEqual(result.tags, ["auth", "design"])
        self.assertEqual(result.risks, ["Token theft via XSS"])
        self.assertIn("# Auth design", result.markdown)

    def test_dict_input_is_accepted(self) -> None:
        result = parse_wrap_analysis_result(_GOOD_PAYLOAD)
        self.assertEqual(result.title, "Auth design")

    def test_json_in_markdown_code_fence_parses(self) -> None:
        raw = "```json\n" + json.dumps(_GOOD_PAYLOAD) + "\n```"
        result = parse_wrap_analysis_result(raw)
        self.assertEqual(result.title, "Auth design")

    def test_json_in_unlabeled_code_fence_parses(self) -> None:
        raw = "```\n" + json.dumps(_GOOD_PAYLOAD) + "\n```"
        result = parse_wrap_analysis_result(raw)
        self.assertEqual(result.title, "Auth design")

    def test_leading_prose_is_tolerated(self) -> None:
        raw = "Sure! Here's the wrap:\n" + json.dumps(_GOOD_PAYLOAD) + "\nThanks!"
        result = parse_wrap_analysis_result(raw)
        self.assertEqual(result.title, "Auth design")

    def test_missing_optional_fields_get_safe_defaults(self) -> None:
        partial = {"title": "Only title"}
        result = parse_wrap_analysis_result(partial)
        self.assertEqual(result.title, "Only title")
        self.assertEqual(result.topic, "")
        self.assertFalse(result.topic_drift)
        self.assertEqual(result.key_decisions, [])
        self.assertEqual(result.requirements, [])
        self.assertEqual(result.todos, [])
        self.assertEqual(result.tags, [])
        self.assertEqual(result.split_suggestions, [])
        self.assertIsNone(result.risks)

    def test_missing_title_gets_placeholder(self) -> None:
        result = parse_wrap_analysis_result({})
        self.assertEqual(result.title, "Untitled Wrap")

    def test_split_suggestions_parse(self) -> None:
        payload = dict(_GOOD_PAYLOAD)
        payload["shouldSplit"] = True
        payload["splitSuggestions"] = [
            {"title": "Part 1", "summary": "Foo", "messageIds": [1, 2]},
            {"title": "Part 2", "summary": "Bar", "messageIds": [3]},
        ]
        result = parse_wrap_analysis_result(payload)
        self.assertTrue(result.should_split)
        self.assertEqual(len(result.split_suggestions), 2)
        self.assertEqual(result.split_suggestions[0].title, "Part 1")
        self.assertEqual(result.split_suggestions[0].message_ids, (1, 2))

    def test_string_boolean_is_coerced(self) -> None:
        payload = dict(_GOOD_PAYLOAD, topicDrift="true", shouldSplit="false")
        result = parse_wrap_analysis_result(payload)
        self.assertTrue(result.topic_drift)
        self.assertFalse(result.should_split)

    def test_non_string_list_items_are_stringified(self) -> None:
        payload = dict(_GOOD_PAYLOAD, keyDecisions=["valid", 42, None, ""])
        result = parse_wrap_analysis_result(payload)
        self.assertEqual(result.key_decisions, ["valid", "42"])


class ParserFailurePathTest(unittest.TestCase):
    def test_empty_string_raises(self) -> None:
        with self.assertRaises(WrapParseError):
            parse_wrap_analysis_result("")

    def test_no_json_object_raises(self) -> None:
        with self.assertRaises(WrapParseError):
            parse_wrap_analysis_result("just some prose, no json here")

    def test_malformed_json_raises(self) -> None:
        with self.assertRaises(WrapParseError):
            parse_wrap_analysis_result('{"title": "Auth", "tags": [oops]}')

    def test_top_level_array_raises(self) -> None:
        # We require an object at the root.
        with self.assertRaises(WrapParseError):
            parse_wrap_analysis_result('[{"title": "x"}]')

    def test_non_string_non_dict_input_raises(self) -> None:
        with self.assertRaises(WrapParseError):
            parse_wrap_analysis_result(42)  # type: ignore[arg-type]

    def test_error_preview_is_truncated(self) -> None:
        big = "garbage " * 200
        try:
            parse_wrap_analysis_result(big)
        except WrapParseError as exc:
            self.assertIsNotNone(exc.raw_preview)
            self.assertLessEqual(len(exc.raw_preview or ""), 201)


# ---------------------------------------------------------------------------
# Mock provider.


class MockProviderTest(unittest.TestCase):
    def test_mock_provider_returns_wrap_analysis_result(self) -> None:
        provider = MockWrapProvider(model=WrapModel.DEEPSEEK_V4_FLASH)
        result = provider.generate_wrap_analysis(_make_request())
        self.assertIsInstance(result, WrapAnalysisResult)

    def test_mock_provider_is_deterministic(self) -> None:
        provider = MockWrapProvider(model=WrapModel.DEEPSEEK_V4_FLASH)
        req = _make_request()
        a = provider.generate_wrap_analysis(req)
        b = provider.generate_wrap_analysis(req)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_mock_provider_derives_title_from_first_user_message(self) -> None:
        provider = MockWrapProvider(model=WrapModel.DEEPSEEK_V4_FLASH)
        result = provider.generate_wrap_analysis(
            _make_request(
                messages=[WrapMessage(role="user", content="Refactor billing module")]
            )
        )
        self.assertIn("Refactor billing module", result.title)

    def test_mock_provider_includes_mode_tag(self) -> None:
        provider = MockWrapProvider(model=WrapModel.DEEPSEEK_V4_FLASH)
        result = provider.generate_wrap_analysis(
            _make_request(mode=WrapMode.ADVANCED)
        )
        self.assertIn("advanced", result.tags)

    def test_mock_provider_handles_empty_transcript(self) -> None:
        provider = MockWrapProvider(model=WrapModel.GEMINI_31_FLASH)
        result = provider.generate_wrap_analysis(_make_request(messages=[]))
        # Doesn't crash; returns a valid (empty-ish) result.
        self.assertIsInstance(result, WrapAnalysisResult)
        self.assertTrue(result.title)

    def test_mock_provider_describes_filtering(self) -> None:
        provider = MockWrapProvider(model=WrapModel.DEEPSEEK_V4_FLASH)
        result = provider.generate_wrap_analysis(_make_request())
        self.assertIn("Mock filtering", result.filtering_summary)

    def test_mock_provider_renders_markdown_body(self) -> None:
        provider = MockWrapProvider(model=WrapModel.DEEPSEEK_V4_FLASH)
        result = provider.generate_wrap_analysis(_make_request())
        self.assertTrue(result.markdown.startswith("# "))
        self.assertIn("## Summary", result.markdown)


# ---------------------------------------------------------------------------
# LLMBackedWrapProvider with an injected fake caller.


class _FakeCompletion:
    """Lightweight stand-in for ``ChatCompletion`` — only ``.content``."""

    def __init__(self, content: str) -> None:
        self.content = content


class LLMBackedProviderTest(unittest.TestCase):
    def test_pipeline_returns_parsed_result(self) -> None:
        captured: dict[str, Any] = {}

        def fake_caller(**kwargs):
            captured.update(kwargs)
            return _FakeCompletion(json.dumps(_GOOD_PAYLOAD))

        provider = LLMBackedWrapProvider(
            model=WrapModel.DEEPSEEK_V4_FLASH,
            api_key="fake-key",
            llm_caller=fake_caller,
        )
        result = provider.generate_wrap_analysis(_make_request())

        # Forwarded routing.
        self.assertEqual(captured["provider"], "deepseek")
        self.assertEqual(captured["model"], "deepseek-chat")
        self.assertEqual(captured["api_key"], "fake-key")

        # System + user prompt both shipped.
        sent_messages = captured["messages"]
        self.assertEqual(len(sent_messages), 2)
        self.assertEqual(sent_messages[0]["role"], "system")
        self.assertEqual(sent_messages[1]["role"], "user")
        self.assertIn("Demo Project", sent_messages[1]["content"])

        # Parser output came through.
        self.assertEqual(result.title, "Auth design")

    def test_provider_falls_back_to_string_completion(self) -> None:
        def fake_caller(**kwargs):
            return json.dumps(_GOOD_PAYLOAD)  # raw string, not a ChatCompletion

        provider = LLMBackedWrapProvider(
            model=WrapModel.GPT_54_NANO,
            api_key="fake-key",
            llm_caller=fake_caller,
        )
        result = provider.generate_wrap_analysis(_make_request())
        self.assertEqual(result.title, "Auth design")

    def test_missing_api_key_raises_at_construction(self) -> None:
        with self.assertRaises(WrapProviderError) as ctx:
            LLMBackedWrapProvider(
                model=WrapModel.DEEPSEEK_V4_FLASH,
                api_key="",
                llm_caller=lambda **_: _FakeCompletion("{}"),
            )
        self.assertEqual(ctx.exception.code, "missing_api_key")

    def test_unparseable_model_output_raises_provider_error(self) -> None:
        provider = LLMBackedWrapProvider(
            model=WrapModel.DEEPSEEK_V4_FLASH,
            api_key="fake-key",
            llm_caller=lambda **_: _FakeCompletion("garbage with no json"),
        )
        with self.assertRaises(WrapProviderError) as ctx:
            provider.generate_wrap_analysis(_make_request())
        self.assertEqual(ctx.exception.code, "bad_model_output")

    def test_upstream_exception_becomes_provider_error(self) -> None:
        def boom(**_):
            raise RuntimeError("network exploded")

        provider = LLMBackedWrapProvider(
            model=WrapModel.GEMINI_31_FLASH,
            api_key="fake-key",
            llm_caller=boom,
        )
        with self.assertRaises(WrapProviderError) as ctx:
            provider.generate_wrap_analysis(_make_request())
        self.assertEqual(ctx.exception.code, "upstream_error")

    def test_provider_uses_routed_backend_for_each_model(self) -> None:
        seen_models: list[str] = []

        def fake_caller(**kwargs):
            seen_models.append(kwargs["model"])
            return _FakeCompletion(json.dumps(_GOOD_PAYLOAD))

        for wrap_model in WrapModel:
            provider = LLMBackedWrapProvider(
                model=wrap_model,
                api_key="fake-key",
                llm_caller=fake_caller,
            )
            provider.generate_wrap_analysis(_make_request(model=wrap_model))

        expected = [MODEL_ROUTES[m].backend_model for m in WrapModel]
        self.assertEqual(seen_models, expected)


# ---------------------------------------------------------------------------
# get_wrap_provider factory.


class GetWrapProviderTest(unittest.TestCase):
    def test_defaults_to_mock_provider(self) -> None:
        provider = get_wrap_provider(WrapModel.DEEPSEEK_V4_FLASH)
        self.assertIsInstance(provider, MockWrapProvider)
        self.assertEqual(provider.model, WrapModel.DEEPSEEK_V4_FLASH)

    def test_returns_mock_when_allow_network_but_no_key(self) -> None:
        provider = get_wrap_provider(
            WrapModel.GEMINI_31_FLASH,
            allow_network=True,
        )
        self.assertIsInstance(provider, MockWrapProvider)

    def test_returns_llm_backed_when_caller_injected(self) -> None:
        provider = get_wrap_provider(
            WrapModel.GPT_54_NANO,
            llm_caller=lambda **_: _FakeCompletion("{}"),
        )
        self.assertIsInstance(provider, LLMBackedWrapProvider)

    def test_returns_llm_backed_when_key_supplied_and_allow_network(self) -> None:
        provider = get_wrap_provider(
            WrapModel.DEEPSEEK_V4_FLASH,
            api_key="user-supplied-key",
            allow_network=True,
        )
        self.assertIsInstance(provider, LLMBackedWrapProvider)
        self.assertEqual(provider.api_key, "user-supplied-key")


# ---------------------------------------------------------------------------
# create_wrap_draft orchestration.


class CreateWrapDraftTest(unittest.TestCase):
    def test_draft_via_mock_provider(self) -> None:
        draft = create_wrap_draft(_make_request())
        self.assertIsInstance(draft, WrapAnalysisResult)
        self.assertTrue(draft.title)
        self.assertTrue(draft.markdown)

    def test_draft_via_explicit_provider(self) -> None:
        # Test the `provider=` injection branch.
        provider = MagicMock(spec=WrapProvider)
        provider.generate_wrap_analysis.return_value = WrapAnalysisResult(
            title="Stub",
            topic="x",
            topic_drift=False,
            should_split=False,
            split_suggestions=[],
            summary="",
            key_decisions=[],
            requirements=[],
            todos=[],
            filtering_summary="",
            tags=["DUPE", "dupe", " keep "],
            markdown="",
        )

        draft = create_wrap_draft(_make_request(), provider=provider)
        provider.generate_wrap_analysis.assert_called_once()

        # Normalization happened: tags lowercased + deduped + trimmed.
        self.assertEqual(draft.tags, ["dupe", "keep"])

    def test_draft_via_injected_llm_caller(self) -> None:
        captured: dict[str, Any] = {}

        def fake_caller(**kwargs):
            captured.update(kwargs)
            return _FakeCompletion(json.dumps(_GOOD_PAYLOAD))

        draft = create_wrap_draft(_make_request(), llm_caller=fake_caller)
        self.assertEqual(draft.title, "Auth design")
        # Caller was actually invoked with the deepseek route.
        self.assertEqual(captured["provider"], "deepseek")

    def test_normalization_supplies_fallback_title(self) -> None:
        provider = MagicMock(spec=WrapProvider)
        provider.generate_wrap_analysis.return_value = WrapAnalysisResult(
            title="",
            topic="",
            topic_drift=False,
            should_split=False,
            split_suggestions=[],
            summary="",
            key_decisions=[],
            requirements=[],
            todos=[],
            filtering_summary="",
            tags=[],
            markdown="",
        )
        draft = create_wrap_draft(
            _make_request(project_name="Atlas"), provider=provider
        )
        self.assertEqual(draft.title, "Atlas Wrap")
        self.assertEqual(draft.topic, "Atlas")

    def test_normalization_caps_tags_at_eight(self) -> None:
        provider = MagicMock(spec=WrapProvider)
        provider.generate_wrap_analysis.return_value = WrapAnalysisResult(
            title="x",
            topic="x",
            topic_drift=False,
            should_split=False,
            split_suggestions=[],
            summary="",
            key_decisions=[],
            requirements=[],
            todos=[],
            filtering_summary="",
            tags=[f"tag{i}" for i in range(20)],
            markdown="",
        )
        draft = create_wrap_draft(_make_request(), provider=provider)
        self.assertEqual(len(draft.tags), 8)


# ---------------------------------------------------------------------------
# Smoke test — full path via the public factory + create_wrap_draft, no
# Flask, no network. This is the closest unit test gets to "production".


class EndToEndMockSmokeTest(unittest.TestCase):
    def test_quick_wrap_full_pipeline(self) -> None:
        draft = create_wrap_draft(
            _make_request(
                model=WrapModel.DEEPSEEK_V4_FLASH,
                mode=WrapMode.QUICK,
                project_name="Auth Service",
            )
        )

        # Every required UI/Markdown writer field is populated.
        self.assertTrue(draft.title)
        self.assertTrue(draft.topic)
        self.assertTrue(draft.summary)
        self.assertTrue(draft.filtering_summary)
        self.assertTrue(draft.markdown)
        # Sane defaults for booleans.
        self.assertIs(draft.topic_drift, False)
        self.assertIs(draft.should_split, False)
        # Tags include the wrap mode.
        self.assertIn("quick", draft.tags)


if __name__ == "__main__":
    unittest.main()
