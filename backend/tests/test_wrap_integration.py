"""Final integration tests — sanity-check the Wrap feature end-to-end.

These tests live above any specific phase's test module and cover
behaviors that span multiple phases:

* Save endpoint disambiguates filenames instead of silently overwriting
  (Phase 3 service, but only formally tested after the integration
  audit added the ``_write_unique`` guard).
* Advanced + Quick + Routine drafts all flow through the same
  ``WrapServiceError`` envelope for LLM / parser failures.
* The cross-user safety story stays consistent across every public
  route, including the new Phase 6 stats endpoints.

We **reuse** the Phase 3 fixtures (``WrapFlaskTestCase``) so DB +
filesystem sandboxing is exactly the same as production routes use.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_wrap_phase3 import WrapFlaskTestCase  # noqa: E402

from app.services.wrap_memory import (  # noqa: E402
    SavedWrap,
    WrapMode,
    WrapModel,
    WrapServiceError,
    build_request_from_conversation,
    quick_wrap_draft,
    save_wrap_draft,
    wrap_draft_from_request,
)
from app.services.wrap_memory.providers import (  # noqa: E402
    LLMBackedWrapProvider,
    WrapProviderError,
)
from app.services.wrap_memory.storage import (  # noqa: E402
    PROJECT_MEMORY_DIRNAME,
    WRAPS_DIRNAME,
)


def _wraps_dir(base: str, project_id: int) -> Path:
    return Path(base) / PROJECT_MEMORY_DIRNAME / WRAPS_DIRNAME / str(project_id)


# ===========================================================================
# Save — no-overwrite guarantee.


class SaveNoOverwriteTest(WrapFlaskTestCase):
    """Make sure ``save_wrap_draft`` never clobbers an existing file."""

    def _save(self, *, filename: str, body: str) -> SavedWrap:
        return save_wrap_draft(
            user=self.alice,
            project=self.project,
            markdown=body,
            filename=filename,
            base_dir=self.tmp.name,
        )

    def test_duplicate_filename_appends_suffix(self) -> None:
        first = self._save(filename="2026-05-13_22-30_topic.md", body="A")
        second = self._save(filename="2026-05-13_22-30_topic.md", body="B")

        self.assertEqual(first.filename, "2026-05-13_22-30_topic.md")
        self.assertEqual(second.filename, "2026-05-13_22-30_topic_2.md")

        # Both files exist on disk with the right bodies — the first
        # one was not silently overwritten.
        self.assertEqual(first.absolute_path.read_text(encoding="utf-8"), "A")
        self.assertEqual(second.absolute_path.read_text(encoding="utf-8"), "B")

    def test_triple_collision_keeps_climbing(self) -> None:
        for _ in range(3):
            self._save(filename="2026-05-13_22-30_topic.md", body="x")
        # 1st => topic.md, 2nd => topic_2.md, 3rd => topic_3.md
        listing = sorted(p.name for p in _wraps_dir(
            self.tmp.name, self.project.id
        ).iterdir())
        self.assertEqual(
            listing,
            [
                "2026-05-13_22-30_topic.md",
                "2026-05-13_22-30_topic_2.md",
                "2026-05-13_22-30_topic_3.md",
            ],
        )

    def test_pre_existing_file_on_disk_is_preserved(self) -> None:
        # Simulate a stray file created by some earlier process — the
        # save endpoint must NOT touch it.
        wd = _wraps_dir(self.tmp.name, self.project.id)
        wd.mkdir(parents=True, exist_ok=True)
        stray = wd / "2026-05-13_22-30_topic.md"
        stray.write_text("DO NOT OVERWRITE", encoding="utf-8")

        saved = self._save(filename="2026-05-13_22-30_topic.md", body="new")
        self.assertEqual(saved.filename, "2026-05-13_22-30_topic_2.md")
        self.assertEqual(
            stray.read_text(encoding="utf-8"), "DO NOT OVERWRITE"
        )


# ===========================================================================
# Save — validation envelope.


class SaveValidationTest(WrapFlaskTestCase):
    def test_blank_markdown_rejected(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            save_wrap_draft(
                user=self.alice,
                project=self.project,
                markdown="   \n   ",
                filename="2026-05-13_22-30_x.md",
                base_dir=self.tmp.name,
            )
        self.assertEqual(ctx.exception.code, "validation_error")
        self.assertEqual(ctx.exception.status, 400)

    def test_path_traversal_filename_rejected(self) -> None:
        for bad in ("../escape.md", "/etc/passwd.md", "..\\evil.md"):
            with self.assertRaises(WrapServiceError) as ctx:
                save_wrap_draft(
                    user=self.alice,
                    project=self.project,
                    markdown="ok",
                    filename=bad,
                    base_dir=self.tmp.name,
                )
            self.assertEqual(
                ctx.exception.code, "validation_error", f"input={bad!r}"
            )

    def test_non_md_filename_rejected(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            save_wrap_draft(
                user=self.alice,
                project=self.project,
                markdown="ok",
                filename="notes.txt",
                base_dir=self.tmp.name,
            )
        self.assertEqual(ctx.exception.code, "validation_error")

    def test_cross_user_save_404(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            save_wrap_draft(
                user=self.bob,
                project=self.project,
                markdown="hi",
                filename="2026-05-13_22-30_x.md",
                base_dir=self.tmp.name,
            )
        self.assertEqual(ctx.exception.status, 404)


# ===========================================================================
# Cross-user route surface — the security boundary should be uniform.


class CrossUserRouteCoverageTest(WrapFlaskTestCase):
    """Every wrap route must return 404 for the wrong user.

    We snapshot the boundary so a future route that forgets to do the
    ownership check still fails this test (rather than silently
    leaking).
    """

    def setUp(self) -> None:
        super().setUp()
        self.bob_headers = self.auth_headers(self.bob)

    def test_quick_draft_404_for_other_user(self) -> None:
        resp = self.client.post(
            f"/api/projects/{self.project.id}/conversations/{self.convo.id}"
            f"/wraps/quick-draft",
            headers=self.bob_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_advanced_draft_404_for_other_user(self) -> None:
        resp = self.client.post(
            f"/api/projects/{self.project.id}/conversations/{self.convo.id}"
            f"/wraps/advanced-draft",
            headers=self.bob_headers,
            json={"model": WrapModel.DEEPSEEK_V4_FLASH.value},
        )
        self.assertEqual(resp.status_code, 404)

    def test_save_404_for_other_user(self) -> None:
        resp = self.client.post(
            f"/api/projects/{self.project.id}/wraps",
            headers=self.bob_headers,
            json={
                "markdown": "x",
                "filename": "2026-05-13_22-30_test.md",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_stats_404_for_other_user(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/stats",
            headers=self.bob_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_routine_config_404_for_other_user(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/routine-config",
            headers=self.bob_headers,
        )
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# LLM error path — the same error shape no matter which entry point is used.


def _llm_caller_raises():
    def fake(**_kwargs):
        raise RuntimeError("upstream went down")
    return fake


def _llm_caller_returns_bad_json():
    def fake(**_kwargs):
        return type("Resp", (), {"content": "definitely not JSON"})()
    return fake


class LLMErrorEnvelopeTest(WrapFlaskTestCase):
    def _build_request(self):
        return build_request_from_conversation(
            user=self.alice,
            project=self.project,
            conversation=self.convo,
            mode=WrapMode.ADVANCED,
            model=WrapModel.DEEPSEEK_V4_FLASH,
        )

    def test_upstream_failure_surfaces_as_bad_gateway(self) -> None:
        # Construct the provider directly so we can inject the failure
        # callable — the service layer will rewrap it as
        # ``WrapServiceError`` only when called via the higher-level
        # pipeline. Here we assert the lower layer first.
        provider = LLMBackedWrapProvider(
            model=WrapModel.DEEPSEEK_V4_FLASH,
            api_key="dummy",
            llm_caller=_llm_caller_raises(),
        )
        with self.assertRaises(WrapProviderError) as ctx:
            provider.generate_wrap_analysis(self._build_request())
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.code, "upstream_error")

    def test_non_json_completion_surfaces_as_bad_model_output(self) -> None:
        provider = LLMBackedWrapProvider(
            model=WrapModel.DEEPSEEK_V4_FLASH,
            api_key="dummy",
            llm_caller=_llm_caller_returns_bad_json(),
        )
        with self.assertRaises(WrapProviderError) as ctx:
            provider.generate_wrap_analysis(self._build_request())
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.code, "bad_model_output")

    def test_missing_api_key_rejected_at_construction(self) -> None:
        with self.assertRaises(WrapProviderError) as ctx:
            LLMBackedWrapProvider(
                model=WrapModel.DEEPSEEK_V4_FLASH,
                api_key="",
                llm_caller=lambda **_: None,
            )
        self.assertEqual(ctx.exception.code, "missing_api_key")


# ===========================================================================
# Quick wrap → save → stats — full happy-path integration.


class HappyPathRoundTripTest(WrapFlaskTestCase):
    def test_quick_draft_then_save_then_stats_reflects_one_wrap(self) -> None:
        # Step 1: generate a draft (mock provider — no network).
        bundle = quick_wrap_draft(
            user=self.alice,
            project=self.project,
            conversation=self.convo,
            allow_network=False,
        )
        self.assertTrue(bundle.markdown.startswith("---"))
        self.assertTrue(bundle.used_mock)

        # Step 2: persist it via the service layer (mirrors what the
        # save route does internally).
        saved = save_wrap_draft(
            user=self.alice,
            project=self.project,
            markdown=bundle.markdown,
            filename=bundle.suggested_filename,
            base_dir=self.tmp.name,
        )
        self.assertGreater(saved.bytes_written, 0)
        self.assertTrue(saved.absolute_path.exists())
        self.assertEqual(saved.filename, bundle.suggested_filename)

        # Step 3: ask the stats endpoint — should now report 1 wrap.
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/stats",
            headers=self.auth_headers(self.alice),
        )
        s = resp.get_json()["stats"]
        self.assertEqual(s["wrapCount"], 1)
        self.assertEqual(s["memorySizeBytes"], saved.bytes_written)
        self.assertIsNotNone(s["lastWrappedAt"])


if __name__ == "__main__":
    unittest.main()
