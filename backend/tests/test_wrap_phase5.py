"""Phase 5 — Routine Wrap tests.

Split into three layers:

* Pure tests on :func:`is_routine_wrap_due` + :func:`resolve_routine_model`
  + :func:`coerce_invariants` — no DB or Flask context needed.

* Service + DB tests via :class:`WrapFlaskTestCase` (reuses the
  in-memory SQLite scaffolding from ``test_wrap_phase3``).

* HTTP route tests through the Flask test client.

The mock provider keeps the LLM offline; the storage sandbox keeps
file writes inside a temp dir. No network, no real disk pollution.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from tests.test_wrap_phase3 import (  # noqa: E402
    WrapFlaskTestCase,
    _make_conversation,
)

from app.extensions import db  # noqa: E402
from app.models import Message, RoutineWrapConfig as RoutineWrapConfigModel  # noqa: E402
from app.services.wrap_memory import (  # noqa: E402
    AUTO_SAVE_ALLOWED,
    DEFAULT_DAY_OF_WEEK,
    DEFAULT_FREQUENCY,
    DEFAULT_ROUTINE_MODEL,
    DEFAULT_SCOPE,
    DISMISS_QUIET_PERIOD,
    REVIEW_REQUIRED,
    RoutineDayOfWeek,
    RoutineFrequency,
    RoutineModel,
    RoutineScope,
    RoutineWrapConfig,
    WrapModel,
    WrapServiceError,
    build_routine_request,
    coerce_invariants,
    compute_routine_status,
    is_routine_wrap_due,
    load_routine_config,
    mark_routine_dismissed,
    mark_routine_run,
    resolve_routine_model,
    save_routine_config,
    wrap_draft_from_request,
)


# ===========================================================================
# Pure tests — no DB.


class IsRoutineWrapDueTest(unittest.TestCase):
    """Phase 5 acceptance: due-date logic per frequency + dismiss."""

    def _cfg(
        self,
        *,
        enabled: bool = True,
        frequency: RoutineFrequency = RoutineFrequency.WEEKLY,
        last_run_at: datetime | None = None,
        dismissed_at: datetime | None = None,
    ) -> RoutineWrapConfig:
        return RoutineWrapConfig(
            enabled=enabled,
            frequency=frequency,
            day_of_week=DEFAULT_DAY_OF_WEEK,
            model=DEFAULT_ROUTINE_MODEL,
            scope=DEFAULT_SCOPE,
            last_run_at=last_run_at,
            dismissed_at=dismissed_at,
        )

    def test_disabled_never_due(self) -> None:
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        cfg = self._cfg(enabled=False, last_run_at=None)
        self.assertFalse(is_routine_wrap_due(cfg, now))

    def test_never_run_is_due(self) -> None:
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        cfg = self._cfg(last_run_at=None)
        self.assertTrue(is_routine_wrap_due(cfg, now))

    def test_weekly_due_after_7_days(self) -> None:
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        cfg_pending = self._cfg(
            frequency=RoutineFrequency.WEEKLY,
            last_run_at=now - timedelta(days=6, hours=23),
        )
        cfg_due = self._cfg(
            frequency=RoutineFrequency.WEEKLY,
            last_run_at=now - timedelta(days=7),
        )
        self.assertFalse(is_routine_wrap_due(cfg_pending, now))
        self.assertTrue(is_routine_wrap_due(cfg_due, now))

    def test_biweekly_due_after_14_days(self) -> None:
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        cfg_pending = self._cfg(
            frequency=RoutineFrequency.BIWEEKLY,
            last_run_at=now - timedelta(days=13),
        )
        cfg_due = self._cfg(
            frequency=RoutineFrequency.BIWEEKLY,
            last_run_at=now - timedelta(days=14, minutes=1),
        )
        self.assertFalse(is_routine_wrap_due(cfg_pending, now))
        self.assertTrue(is_routine_wrap_due(cfg_due, now))

    def test_monthly_due_after_30_days(self) -> None:
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        cfg_pending = self._cfg(
            frequency=RoutineFrequency.MONTHLY,
            last_run_at=now - timedelta(days=29),
        )
        cfg_due = self._cfg(
            frequency=RoutineFrequency.MONTHLY,
            last_run_at=now - timedelta(days=31),
        )
        self.assertFalse(is_routine_wrap_due(cfg_pending, now))
        self.assertTrue(is_routine_wrap_due(cfg_due, now))

    def test_dismiss_quiet_period_mutes_banner(self) -> None:
        now = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
        cfg = self._cfg(
            last_run_at=now - timedelta(days=10),
            dismissed_at=now - timedelta(hours=12),  # < 24h
        )
        self.assertFalse(is_routine_wrap_due(cfg, now))
        # Bypass the mute to confirm the underlying due-state.
        self.assertTrue(
            is_routine_wrap_due(cfg, now, respect_dismiss_quiet_period=False)
        )

    def test_dismiss_quiet_period_expires(self) -> None:
        now = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
        cfg = self._cfg(
            last_run_at=now - timedelta(days=10),
            dismissed_at=now - DISMISS_QUIET_PERIOD - timedelta(minutes=1),
        )
        self.assertTrue(is_routine_wrap_due(cfg, now))

    def test_naive_timestamps_assumed_utc(self) -> None:
        # last_run_at without tzinfo (SQLite quirk) must still produce a
        # meaningful delta when compared to a tz-aware now.
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        naive_recent = (now - timedelta(days=3)).replace(tzinfo=None)
        cfg = self._cfg(last_run_at=naive_recent)
        self.assertFalse(is_routine_wrap_due(cfg, now))


class ResolveRoutineModelTest(unittest.TestCase):
    def test_use_global_default_resolves_to_settings_default(self) -> None:
        from app.services.wrap_memory.settings import DEFAULT_MODEL

        self.assertIs(
            resolve_routine_model(RoutineModel.USE_GLOBAL_DEFAULT),
            DEFAULT_MODEL,
        )

    def test_concrete_choices_map_one_to_one(self) -> None:
        cases = [
            (RoutineModel.DEEPSEEK_V4_FLASH, WrapModel.DEEPSEEK_V4_FLASH),
            (RoutineModel.GEMINI_31_FLASH, WrapModel.GEMINI_31_FLASH),
            (RoutineModel.GPT_54_NANO, WrapModel.GPT_54_NANO),
        ]
        for routine, expected in cases:
            with self.subTest(routine=routine):
                self.assertIs(resolve_routine_model(routine), expected)


class InvariantsTest(unittest.TestCase):
    """``review_required`` and ``auto_save`` are frozen in Phase 5."""

    def test_review_required_constant_is_true(self) -> None:
        self.assertTrue(REVIEW_REQUIRED)

    def test_auto_save_constant_is_false(self) -> None:
        self.assertFalse(AUTO_SAVE_ALLOWED)

    def test_coerce_clamps_unsafe_values(self) -> None:
        bad = RoutineWrapConfig(
            enabled=True,
            frequency=DEFAULT_FREQUENCY,
            day_of_week=DEFAULT_DAY_OF_WEEK,
            model=DEFAULT_ROUTINE_MODEL,
            scope=DEFAULT_SCOPE,
            review_required=False,
            auto_save=True,
        )
        clamped = coerce_invariants(bad)
        self.assertTrue(clamped.review_required)
        self.assertFalse(clamped.auto_save)

    def test_coerce_returns_same_when_already_safe(self) -> None:
        good = RoutineWrapConfig.default()
        self.assertIs(coerce_invariants(good), good)


# ===========================================================================
# Service + DB tests.


class RoutineConfigServiceTest(WrapFlaskTestCase):
    def test_load_or_default_returns_disabled_default(self) -> None:
        cfg = load_routine_config(self.alice, self.project)
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.frequency, DEFAULT_FREQUENCY)
        self.assertEqual(cfg.day_of_week, RoutineDayOfWeek.FRIDAY)
        self.assertEqual(cfg.model, RoutineModel.USE_GLOBAL_DEFAULT)
        self.assertEqual(cfg.scope, RoutineScope.SINCE_LAST_WRAP)

    def test_save_then_load_round_trip(self) -> None:
        saved = save_routine_config(
            self.alice,
            self.project,
            {
                "enabled": True,
                "frequency": "biweekly",
                "dayOfWeek": "monday",
                "model": "gemini-3.1-flash",
                "scope": "last-7-days",
                # Try to sneak invariants past — should be coerced.
                "reviewRequired": False,
                "autoSave": True,
            },
        )
        self.assertTrue(saved.enabled)
        self.assertEqual(saved.frequency, RoutineFrequency.BIWEEKLY)
        self.assertEqual(saved.day_of_week, RoutineDayOfWeek.MONDAY)
        self.assertEqual(saved.model, RoutineModel.GEMINI_31_FLASH)
        self.assertEqual(saved.scope, RoutineScope.LAST_7_DAYS)
        # Invariants always re-clamped.
        self.assertTrue(saved.review_required)
        self.assertFalse(saved.auto_save)

        loaded = load_routine_config(self.alice, self.project)
        self.assertEqual(loaded.to_dict(), saved.to_dict())

    def test_save_rejects_unknown_frequency(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            save_routine_config(
                self.alice, self.project, {"frequency": "hourly"}
            )
        self.assertEqual(ctx.exception.status, 400)

    def test_save_rejects_cross_user_project(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            save_routine_config(self.bob, self.project, {"enabled": True})
        self.assertEqual(ctx.exception.status, 404)

    def test_mark_run_clears_dismiss_and_stamps_last_run(self) -> None:
        save_routine_config(self.alice, self.project, {"enabled": True})
        mark_routine_dismissed(self.alice, self.project)
        cfg = load_routine_config(self.alice, self.project)
        self.assertIsNotNone(cfg.dismissed_at)

        when = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
        updated = mark_routine_run(self.alice, self.project, when=when)
        self.assertIsNone(updated.dismissed_at)
        self.assertIsNotNone(updated.last_run_at)

    def test_mark_dismiss_keeps_last_run_at(self) -> None:
        when_run = datetime(2026, 5, 6, tzinfo=timezone.utc)
        when_dismiss = datetime(2026, 5, 13, tzinfo=timezone.utc)
        mark_routine_run(self.alice, self.project, when=when_run)
        dismissed = mark_routine_dismissed(
            self.alice, self.project, when=when_dismiss
        )
        self.assertEqual(
            dismissed.last_run_at.replace(tzinfo=timezone.utc)
            if dismissed.last_run_at.tzinfo is None
            else dismissed.last_run_at,
            when_run,
        )
        self.assertIsNotNone(dismissed.dismissed_at)


class RoutineStatusTest(WrapFlaskTestCase):
    def test_status_disabled_never_prompts(self) -> None:
        status = compute_routine_status(self.alice, self.project)
        self.assertFalse(status["isDue"])
        self.assertFalse(status["shouldPrompt"])

    def test_status_prompts_when_enabled_due_and_has_messages(self) -> None:
        save_routine_config(self.alice, self.project, {"enabled": True})
        now = datetime.now(timezone.utc)
        status = compute_routine_status(self.alice, self.project, now=now)
        self.assertTrue(status["isDue"])
        self.assertTrue(status["hasNewActivity"])  # convo has 3 messages
        self.assertTrue(status["shouldPrompt"])

    def test_status_due_but_no_activity_does_not_prompt(self) -> None:
        # Configure routine + record a last_run AFTER the conversation
        # was created so there is nothing newer to wrap.
        save_routine_config(self.alice, self.project, {"enabled": True})
        # Stamp last_run_at in the future so any "after last_run_at"
        # filter excludes the existing messages. Then advance ``now``
        # past the weekly interval so the cadence portion is due.
        future = datetime.now(timezone.utc) + timedelta(days=10)
        mark_routine_run(self.alice, self.project, when=future)
        now = future + timedelta(days=8)
        status = compute_routine_status(self.alice, self.project, now=now)
        self.assertTrue(status["isDue"])
        self.assertFalse(status["hasNewActivity"])
        self.assertFalse(status["shouldPrompt"])


class BuildRoutineRequestTest(WrapFlaskTestCase):
    def test_request_uses_resolved_model_and_routine_mode(self) -> None:
        save_routine_config(
            self.alice,
            self.project,
            {
                "enabled": True,
                "model": "deepseek-v4-flash",
                "scope": "since-last-wrap",
            },
        )
        request = build_routine_request(
            user=self.alice, project=self.project, conversation=self.convo
        )
        self.assertEqual(request.mode.value, "routine")
        self.assertEqual(request.model, WrapModel.DEEPSEEK_V4_FLASH)
        self.assertEqual(len(request.messages), 3)

    def test_use_global_default_model_resolves(self) -> None:
        save_routine_config(
            self.alice,
            self.project,
            {"enabled": True, "model": "use-global-default"},
        )
        request = build_routine_request(
            user=self.alice, project=self.project, conversation=self.convo
        )
        from app.services.wrap_memory.settings import DEFAULT_MODEL

        self.assertEqual(request.model, DEFAULT_MODEL)

    def test_since_last_wrap_narrows_messages(self) -> None:
        # Lock the timestamps explicitly: fixture messages get pushed
        # into the past, the cutoff lands between them and the new
        # message, so the strict-greater-than narrowing leaves only
        # the new one. We can't rely on the SQLAlchemy default clock
        # because SQLite's DATETIME storage can collapse sub-second
        # precision under load.
        save_routine_config(
            self.alice, self.project, {"enabled": True, "scope": "since-last-wrap"}
        )

        old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for m in self.convo.messages.all():
            m.created_at = old_ts
        db.session.commit()

        cutoff = datetime(2026, 5, 1, tzinfo=timezone.utc)
        mark_routine_run(self.alice, self.project, when=cutoff)
        db.session.add(
            Message(
                conversation_id=self.convo.id,
                role="user",
                content="Brand new question after the wrap.",
                created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
            )
        )
        db.session.commit()

        request = build_routine_request(
            user=self.alice, project=self.project, conversation=self.convo
        )
        self.assertEqual(len(request.messages), 1)
        self.assertIn("Brand new question", request.messages[0].content)

    def test_no_new_activity_raises_transcript_too_short(self) -> None:
        save_routine_config(
            self.alice,
            self.project,
            {"enabled": True, "scope": "since-last-wrap"},
        )
        future = datetime.now(timezone.utc) + timedelta(days=1)
        mark_routine_run(self.alice, self.project, when=future)
        with self.assertRaises(WrapServiceError) as ctx:
            build_routine_request(
                user=self.alice, project=self.project, conversation=self.convo
            )
        self.assertEqual(ctx.exception.code, "transcript_too_short")


# ===========================================================================
# End-to-end review + save updates last_run_at.


class RoutineReviewAndSaveTest(WrapFlaskTestCase):
    def test_review_save_mark_run_pipeline(self) -> None:
        # 1) Configure routine.
        save_routine_config(
            self.alice,
            self.project,
            {"enabled": True, "model": "gpt-5.4-nano", "scope": "since-last-wrap"},
        )
        # 2) Generate a draft via build_routine_request + wrap_draft_from_request.
        request = build_routine_request(
            user=self.alice, project=self.project, conversation=self.convo
        )
        bundle = wrap_draft_from_request(
            request, user=self.alice, project=self.project, allow_network=False
        )
        self.assertEqual(bundle.request.model, WrapModel.GPT_54_NANO)
        self.assertEqual(bundle.request.mode.value, "routine")
        self.assertIn('wrap_type: "routine"', bundle.markdown)

        # 3) "User reviews + saves" — drive save via the service helper.
        from app.services.wrap_memory import save_wrap_draft

        saved = save_wrap_draft(
            user=self.alice,
            project=self.project,
            markdown=bundle.markdown,
            filename=bundle.suggested_filename,
            base_dir=self.tmp.name,
        )
        self.assertTrue(saved.absolute_path.exists())

        # 4) Mark the routine as run.
        before = load_routine_config(self.alice, self.project)
        self.assertIsNone(before.last_run_at)
        after = mark_routine_run(self.alice, self.project)
        self.assertIsNotNone(after.last_run_at)


# ===========================================================================
# HTTP routes.


class RoutineHTTPRoutesTest(WrapFlaskTestCase):
    def _auth(self, user=None):
        return {
            "Content-Type": "application/json",
            **self.auth_headers(user or self.alice),
        }

    def test_get_config_returns_defaults_when_no_row(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/routine-config",
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 200)
        cfg = resp.get_json()["config"]
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["frequency"], "weekly")
        self.assertEqual(cfg["dayOfWeek"], "friday")
        self.assertEqual(cfg["model"], "use-global-default")
        self.assertEqual(cfg["scope"], "since-last-wrap")
        self.assertTrue(cfg["reviewRequired"])
        self.assertFalse(cfg["autoSave"])
        self.assertIsNone(cfg["lastRunAt"])

    def test_put_then_get_round_trip(self) -> None:
        put = self.client.put(
            f"/api/projects/{self.project.id}/wraps/routine-config",
            data=json.dumps(
                {
                    "enabled": True,
                    "frequency": "monthly",
                    "dayOfWeek": "wednesday",
                    "model": "gemini-3.1-flash",
                    "scope": "last-7-days",
                    "autoSave": True,  # caller tries; server clamps to False.
                }
            ),
            headers=self._auth(),
        )
        self.assertEqual(put.status_code, 200)
        cfg = put.get_json()["config"]
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["frequency"], "monthly")
        self.assertFalse(cfg["autoSave"])

    def test_put_rejects_unknown_model(self) -> None:
        resp = self.client.put(
            f"/api/projects/{self.project.id}/wraps/routine-config",
            data=json.dumps({"model": "claude-99-magic"}),
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_status_endpoint_shape(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/routine-status",
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        for key in ("config", "now", "isDue", "hasNewActivity", "shouldPrompt"):
            self.assertIn(key, body)
        # Defaults: disabled → not due → no prompt.
        self.assertFalse(body["isDue"])
        self.assertFalse(body["shouldPrompt"])

    def test_status_prompts_when_enabled(self) -> None:
        save_routine_config(self.alice, self.project, {"enabled": True})
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/routine-status",
            headers=self._auth(),
        )
        body = resp.get_json()
        self.assertTrue(body["isDue"])
        self.assertTrue(body["shouldPrompt"])

    def test_dismiss_mutes_status(self) -> None:
        save_routine_config(self.alice, self.project, {"enabled": True})
        dismiss = self.client.post(
            f"/api/projects/{self.project.id}/wraps/routine-dismiss",
            headers=self._auth(),
        )
        self.assertEqual(dismiss.status_code, 200)
        status = self.client.get(
            f"/api/projects/{self.project.id}/wraps/routine-status",
            headers=self._auth(),
        ).get_json()
        # Dismissed within the quiet window → no banner.
        self.assertFalse(status["shouldPrompt"])

    def test_routine_draft_endpoint(self) -> None:
        save_routine_config(
            self.alice,
            self.project,
            {"enabled": True, "model": "gemini-3.1-flash"},
        )
        resp = self.client.post(
            f"/api/projects/{self.project.id}"
            f"/conversations/{self.convo.id}/wraps/routine-draft",
            data=json.dumps({}),
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 200, msg=resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertIn("draft", body)
        self.assertIn("routineConfig", body)
        self.assertEqual(body["draft"]["mode"], "routine")
        self.assertEqual(body["draft"]["model"], "gemini-3.1-flash")
        self.assertIn("wrap_type: \"routine\"", body["draft"]["markdown"])

    def test_routine_draft_requires_auth(self) -> None:
        resp = self.client.post(
            f"/api/projects/{self.project.id}"
            f"/conversations/{self.convo.id}/wraps/routine-draft",
            data=json.dumps({}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_routine_mark_run_stamps_last_run(self) -> None:
        save_routine_config(self.alice, self.project, {"enabled": True})
        mark = self.client.post(
            f"/api/projects/{self.project.id}/wraps/routine-mark-run",
            headers=self._auth(),
        )
        self.assertEqual(mark.status_code, 200)
        cfg = mark.get_json()["config"]
        self.assertIsNotNone(cfg["lastRunAt"])

    def test_cross_user_routes_404(self) -> None:
        for path, method in [
            (
                f"/api/projects/{self.project.id}/wraps/routine-config",
                "get",
            ),
            (
                f"/api/projects/{self.project.id}/wraps/routine-status",
                "get",
            ),
            (
                f"/api/projects/{self.project.id}/wraps/routine-dismiss",
                "post",
            ),
            (
                f"/api/projects/{self.project.id}/wraps/routine-mark-run",
                "post",
            ),
        ]:
            with self.subTest(path=path, method=method):
                client_call = getattr(self.client, method)
                resp = client_call(path, headers=self._auth(self.bob))
                self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
