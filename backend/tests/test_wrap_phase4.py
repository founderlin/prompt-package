"""Phase 4 — Advanced Wrap service + HTTP route tests.

Reuses the in-memory Flask + SQLite scaffolding from
:mod:`tests.test_wrap_phase3` so we can focus on the behavior unique
to Advanced Wrap:

* The shared ``wrap_draft`` service correctly threads ``model`` /
  ``filters`` / ``user_instruction`` into the underlying
  :class:`WrapRequest`.
* The ``/wraps/advanced-draft`` route validates the body, returns
  ``mode == "advanced"`` and ``model == <chosen model>`` in the bundle,
  and rejects unknown enums with a 400.
* The save endpoint persists *user-edited* Markdown verbatim — i.e.
  edits made in the Advanced dialog survive the round-trip to disk.

LLM calls go through the Phase 2 mock provider (``allow_network=False``).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.test_wrap_phase3 import (  # noqa: E402  (Flask config in helper)
    WrapFlaskTestCase,
    _make_conversation,
)

from app.services.wrap_memory import (  # noqa: E402
    WrapFilters,
    WrapMode,
    WrapModel,
    WrapServiceError,
    quick_wrap_draft,
    wrap_draft,
)
from app.services.wrap_memory.types import FilterAction  # noqa: E402


# ---------------------------------------------------------------------------
# Service layer — wrap_draft (Advanced).


class WrapDraftServiceAdvancedTest(WrapFlaskTestCase):
    def test_advanced_mode_propagates_model_and_filters(self) -> None:
        custom_filters = WrapFilters(
            code_blocks=FilterAction.KEEP,
            images=FilterAction.KEEP,
            prompt_text=FilterAction.EXCLUDE,
            logs=FilterAction.EXCLUDE,
            off_topic=FilterAction.KEEP,
        )

        bundle = wrap_draft(
            user=self.alice,
            project=self.project,
            conversation=self.convo,
            mode=WrapMode.ADVANCED,
            model=WrapModel.GEMINI_31_FLASH,
            filters=custom_filters,
            user_instruction="Emphasize the JWT decisions.",
            allow_network=False,
        )

        self.assertEqual(bundle.request.mode, WrapMode.ADVANCED)
        self.assertEqual(bundle.request.model, WrapModel.GEMINI_31_FLASH)
        # The custom filters survive into the request unchanged.
        self.assertEqual(bundle.request.filters, custom_filters)
        self.assertEqual(
            bundle.request.user_instruction, "Emphasize the JWT decisions."
        )
        # The model is reflected in the Markdown frontmatter.
        self.assertIn("model: \"gemini-3.1-flash\"", bundle.markdown)
        self.assertIn("wrap_type: \"advanced\"", bundle.markdown)

    def test_advanced_falls_back_to_default_when_filters_missing(self) -> None:
        bundle = wrap_draft(
            user=self.alice,
            project=self.project,
            conversation=self.convo,
            mode=WrapMode.ADVANCED,
            model=WrapModel.GPT_54_NANO,
            filters=None,
            allow_network=False,
        )
        # No explicit filters → defaults from settings.DEFAULT_FILTERS apply.
        from app.services.wrap_memory.settings import DEFAULT_FILTERS

        self.assertEqual(bundle.request.filters, DEFAULT_FILTERS)


# ---------------------------------------------------------------------------
# HTTP route — POST /wraps/advanced-draft.


class AdvancedDraftRouteTest(WrapFlaskTestCase):
    def _url(self, conversation_id: int | None = None) -> str:
        cid = conversation_id if conversation_id is not None else self.convo.id
        return (
            f"/api/projects/{self.project.id}"
            f"/conversations/{cid}/wraps/advanced-draft"
        )

    def _post(self, payload: dict, *, user=None) -> tuple[int, dict]:
        resp = self.client.post(
            self._url(),
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                **self.auth_headers(user or self.alice),
            },
        )
        return resp.status_code, resp.get_json() or {}

    def test_advanced_draft_with_explicit_model_and_filters(self) -> None:
        payload = {
            "model": "gpt-5.4-nano",
            "filters": {
                "codeBlocks": "keep",
                "images": "exclude",
                "promptText": "summarize",
                "logs": "exclude",
                "offTopic": "summarize",
            },
            "userInstruction": "Focus on the auth flow trade-offs.",
        }
        status, body = self._post(payload)

        self.assertEqual(status, 200, msg=body)
        draft = body["draft"]
        self.assertEqual(draft["mode"], "advanced")
        self.assertEqual(draft["model"], "gpt-5.4-nano")
        self.assertIn("markdown", draft)
        self.assertTrue(draft["markdown"].startswith("---\n"))
        # The model + mode end up in the rendered frontmatter.
        self.assertIn("model: \"gpt-5.4-nano\"", draft["markdown"])
        self.assertIn("wrap_type: \"advanced\"", draft["markdown"])

    def test_advanced_draft_rejects_unknown_model(self) -> None:
        status, body = self._post(
            {"model": "claude-99-magic", "filters": {}}
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "validation_error")
        self.assertIn("model", body["message"].lower())

    def test_advanced_draft_rejects_unknown_filter_action(self) -> None:
        status, body = self._post(
            {
                "model": "deepseek-v4-flash",
                "filters": {"codeBlocks": "obliterate"},
            }
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "validation_error")
        # The error message points at the offending key.
        self.assertIn("codeBlocks", body["message"])

    def test_advanced_draft_rejects_non_object_filters(self) -> None:
        status, body = self._post(
            {"model": "deepseek-v4-flash", "filters": "all-defaults"}
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "validation_error")

    def test_advanced_draft_rejects_non_string_user_instruction(self) -> None:
        status, body = self._post(
            {
                "model": "deepseek-v4-flash",
                "filters": {},
                "userInstruction": ["not", "a", "string"],
            }
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "validation_error")

    def test_advanced_draft_defaults_model_when_omitted(self) -> None:
        # Omitting model is allowed (defensive default) — useful for curl
        # smoke tests. The UI always sends one explicitly.
        status, body = self._post({"filters": {}})
        self.assertEqual(status, 200, msg=body)
        self.assertEqual(body["draft"]["model"], "deepseek-v4-flash")
        self.assertEqual(body["draft"]["mode"], "advanced")

    def test_advanced_draft_requires_auth(self) -> None:
        resp = self.client.post(
            self._url(),
            data=json.dumps({"model": "deepseek-v4-flash", "filters": {}}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_advanced_draft_other_user_gets_404(self) -> None:
        status, _ = self._post(
            {"model": "deepseek-v4-flash", "filters": {}}, user=self.bob
        )
        self.assertEqual(status, 404)

    def test_advanced_draft_empty_conversation_returns_400(self) -> None:
        empty = _make_conversation(self.alice, self.project, messages=[])
        resp = self.client.post(
            self._url(conversation_id=empty.id),
            data=json.dumps({"model": "deepseek-v4-flash", "filters": {}}),
            headers={
                "Content-Type": "application/json",
                **self.auth_headers(self.alice),
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["error"], "transcript_too_short")


# ---------------------------------------------------------------------------
# End-to-end: Advanced draft → user-edits Markdown → save.


class AdvancedDraftThenSaveTest(WrapFlaskTestCase):
    def test_user_edited_markdown_is_persisted_verbatim(self) -> None:
        # 1) Draft via Advanced route.
        draft_resp = self.client.post(
            f"/api/projects/{self.project.id}"
            f"/conversations/{self.convo.id}/wraps/advanced-draft",
            data=json.dumps(
                {
                    "model": "gemini-3.1-flash",
                    "filters": {
                        "codeBlocks": "keep",
                        "images": "exclude",
                        "promptText": "summarize",
                        "logs": "summarize",
                        "offTopic": "exclude",
                    },
                }
            ),
            headers={
                "Content-Type": "application/json",
                **self.auth_headers(self.alice),
            },
        )
        self.assertEqual(draft_resp.status_code, 200)
        draft = draft_resp.get_json()["draft"]

        # 2) User edits Markdown in the dialog before saving.
        edited = draft["markdown"] + "\n\n## My hand-written addendum\n\nKeep this!\n"

        # 3) Save endpoint (Phase 3) — verifies edits survive.
        save_resp = self.client.post(
            f"/api/projects/{self.project.id}/wraps",
            data=json.dumps(
                {
                    "markdown": edited,
                    "filename": draft["suggestedFilename"],
                }
            ),
            headers={
                "Content-Type": "application/json",
                **self.auth_headers(self.alice),
            },
        )
        self.assertEqual(save_resp.status_code, 201, msg=save_resp.get_data(as_text=True))
        saved = save_resp.get_json()["wrap"]

        on_disk = Path(saved["absolutePath"]).read_text(encoding="utf-8")
        self.assertEqual(on_disk, edited)
        self.assertIn("## My hand-written addendum", on_disk)


if __name__ == "__main__":
    unittest.main()
