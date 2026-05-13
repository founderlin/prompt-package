"""Integration tests for Phase 3 wrap_memory service + routes.

Spins up the Flask factory against in-memory SQLite. Provides a thin
``WrapFlaskTestCase`` base class that handles user / project /
conversation / message fixtures; each test then exercises either the
service layer directly or hits the HTTP endpoints through the Flask
test client.

LLM calls are short-circuited by setting ``allow_network=False`` in
the relevant calls — every test runs offline using the Phase 2 mock
provider. We never reach for the network.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Point the app at an in-memory SQLite so we don't pollute the dev DB.
# These vars must be set *before* the app factory imports config.py.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "phase3-secret")
os.environ.setdefault("JWT_SECRET_KEY", "phase3-jwt")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Conversation, Message, Project, User  # noqa: E402
from app.services.wrap_memory import (  # noqa: E402
    WrapServiceError,
    build_request_from_conversation,
    quick_wrap_draft,
    save_wrap_draft,
)
from app.utils.auth import issue_token  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers.


def _make_user(email: str = "alice@example.com") -> User:
    user = User(email=email)
    user.set_password("Password!1")
    db.session.add(user)
    db.session.commit()
    return user


def _make_project(user: User, name: str = "Demo") -> Project:
    project = Project(user_id=user.id, name=name, description="")
    db.session.add(project)
    db.session.commit()
    return project


def _make_conversation(
    user: User,
    project: Project,
    *,
    messages: list[tuple[str, str]] | None = None,
) -> Conversation:
    convo = Conversation(
        user_id=user.id,
        project_id=project.id,
        title="Test convo",
        model="openai/gpt-4o-mini",
        provider="openrouter",
    )
    db.session.add(convo)
    db.session.commit()
    if messages:
        for role, content in messages:
            db.session.add(
                Message(
                    conversation_id=convo.id,
                    role=role,
                    content=content,
                )
            )
        db.session.commit()
    return convo


# ---------------------------------------------------------------------------
# Base test case.


class WrapFlaskTestCase(unittest.TestCase):
    """Shared boilerplate: fresh app + DB per test, throwaway wraps dir."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        self.app = create_app()
        # Pin the wrap-memory storage root inside the temp dir so every
        # filesystem write is sandboxed and self-cleaning.
        self.app.config["WRAP_MEMORY_DIR"] = self.tmp.name

        self.app_ctx = self.app.app_context()
        self.app_ctx.push()
        self.addCleanup(self.app_ctx.pop)

        # Ensure a clean schema for each test (in-memory DB is per-engine,
        # but the factory may have shared state across tests in the same
        # process).
        db.drop_all()
        db.create_all()

        self.client = self.app.test_client()

        self.alice = _make_user("alice@example.com")
        self.bob = _make_user("bob@example.com")
        self.project = _make_project(self.alice, "Auth Service")
        self.convo = _make_conversation(
            self.alice,
            self.project,
            messages=[
                ("user", "Let's design the auth flow."),
                ("assistant", "Sure — token-based with refresh rotation?"),
                ("user", "Yes, JWT with 30d refresh."),
            ],
        )

    def auth_headers(self, user: User) -> dict:
        token = issue_token(user)
        return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Service layer.


class BuildRequestFromConversationTest(WrapFlaskTestCase):
    def test_builds_with_default_filters_and_model(self) -> None:
        req = build_request_from_conversation(
            user=self.alice,
            project=self.project,
            conversation=self.convo,
        )
        self.assertEqual(req.project_id, self.project.id)
        self.assertEqual(req.project_name, "Auth Service")
        self.assertEqual(len(req.messages), 3)
        # System messages would have been filtered out; here we have
        # only user + assistant which is what we passed in.
        self.assertEqual(req.messages[0].role, "user")

    def test_rejects_cross_user_conversation(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            build_request_from_conversation(
                user=self.bob,
                project=self.project,
                conversation=self.convo,
            )
        self.assertEqual(ctx.exception.status, 404)

    def test_rejects_empty_transcript(self) -> None:
        empty = _make_conversation(self.alice, self.project, messages=[])
        with self.assertRaises(WrapServiceError) as ctx:
            build_request_from_conversation(
                user=self.alice,
                project=self.project,
                conversation=empty,
            )
        self.assertEqual(ctx.exception.code, "transcript_too_short")


class QuickWrapDraftServiceTest(WrapFlaskTestCase):
    def test_returns_bundle_with_markdown_and_filename(self) -> None:
        bundle = quick_wrap_draft(
            user=self.alice,
            project=self.project,
            conversation=self.convo,
            allow_network=False,  # force mock provider for determinism
        )
        # Bundle fields all populated.
        self.assertTrue(bundle.analysis.title)
        self.assertTrue(bundle.markdown.startswith("---\n"))
        self.assertIn("project_id: ", bundle.markdown)
        self.assertTrue(bundle.suggested_filename.endswith(".md"))
        self.assertTrue(
            bundle.save_path_relative.startswith(
                f"project-memory/wraps/{self.project.id}/"
            )
        )
        self.assertTrue(bundle.used_mock)


class SaveWrapDraftServiceTest(WrapFlaskTestCase):
    def test_writes_file_inside_temp_wraps_dir(self) -> None:
        markdown = "---\ntitle: \"x\"\n---\n\n# body\n"
        saved = save_wrap_draft(
            user=self.alice,
            project=self.project,
            markdown=markdown,
            filename="2026-05-13_16-41_hello.md",
            base_dir=self.tmp.name,
        )
        self.assertTrue(saved.absolute_path.exists())
        self.assertEqual(
            saved.absolute_path.read_text(encoding="utf-8"), markdown
        )
        # Must land under our sandbox.
        self.assertTrue(
            str(saved.absolute_path).startswith(self.tmp.name),
            msg=str(saved.absolute_path),
        )

    def test_rejects_empty_markdown(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            save_wrap_draft(
                user=self.alice,
                project=self.project,
                markdown="   ",
                filename="x.md",
                base_dir=self.tmp.name,
            )
        self.assertEqual(ctx.exception.code, "validation_error")

    def test_rejects_path_traversal_filename(self) -> None:
        with self.assertRaises(WrapServiceError):
            save_wrap_draft(
                user=self.alice,
                project=self.project,
                markdown="ok",
                filename="../escape.md",
                base_dir=self.tmp.name,
            )

    def test_rejects_non_md_extension(self) -> None:
        with self.assertRaises(WrapServiceError):
            save_wrap_draft(
                user=self.alice,
                project=self.project,
                markdown="ok",
                filename="hello.txt",
                base_dir=self.tmp.name,
            )

    def test_rejects_cross_user_project(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            save_wrap_draft(
                user=self.bob,
                project=self.project,
                markdown="ok",
                filename="x.md",
                base_dir=self.tmp.name,
            )
        self.assertEqual(ctx.exception.status, 404)


# ---------------------------------------------------------------------------
# HTTP routes.


class QuickDraftRouteTest(WrapFlaskTestCase):
    def _url(self) -> str:
        return (
            f"/api/projects/{self.project.id}"
            f"/conversations/{self.convo.id}/wraps/quick-draft"
        )

    def test_authenticated_request_returns_draft(self) -> None:
        resp = self.client.post(
            self._url(), headers=self.auth_headers(self.alice)
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        draft = body["draft"]
        self.assertIn("analysis", draft)
        self.assertIn("markdown", draft)
        self.assertIn("suggestedFilename", draft)
        self.assertEqual(draft["mode"], "quick")
        self.assertEqual(draft["model"], "deepseek-v4-flash")
        self.assertTrue(draft["markdown"].startswith("---\n"))

    def test_unauthenticated_request_is_rejected(self) -> None:
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 401)

    def test_other_user_gets_404(self) -> None:
        # Bob can authenticate but the project isn't his.
        resp = self.client.post(
            self._url(), headers=self.auth_headers(self.bob)
        )
        self.assertEqual(resp.status_code, 404)

    def test_empty_conversation_returns_400(self) -> None:
        empty = _make_conversation(self.alice, self.project, messages=[])
        url = (
            f"/api/projects/{self.project.id}"
            f"/conversations/{empty.id}/wraps/quick-draft"
        )
        resp = self.client.post(url, headers=self.auth_headers(self.alice))
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["error"], "transcript_too_short")

    def test_accepts_user_preferred_model(self) -> None:
        # The Settings → Wrap model preference flows in as a ``model``
        # body field. A valid value should round-trip into the draft;
        # anything else gets a 400.
        resp = self.client.post(
            self._url(),
            json={"model": "gpt-5.4-nano"},
            headers=self.auth_headers(self.alice),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["draft"]["model"], "gpt-5.4-nano")

    def test_rejects_unknown_model(self) -> None:
        resp = self.client.post(
            self._url(),
            json={"model": "ghost-model"},
            headers=self.auth_headers(self.alice),
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["error"], "validation_error")


class SaveRouteTest(WrapFlaskTestCase):
    def _url(self) -> str:
        return f"/api/projects/{self.project.id}/wraps"

    def _draft_markdown(self) -> dict:
        # Get a draft from the service to ensure realistic shape.
        bundle = quick_wrap_draft(
            user=self.alice,
            project=self.project,
            conversation=self.convo,
            allow_network=False,
        )
        return {
            "markdown": bundle.markdown,
            "filename": bundle.suggested_filename,
        }

    def test_save_writes_file(self) -> None:
        payload = self._draft_markdown()
        resp = self.client.post(
            self._url(),
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                **self.auth_headers(self.alice),
            },
        )
        self.assertEqual(resp.status_code, 201, msg=resp.get_data(as_text=True))
        body = resp.get_json()
        wrap = body["wrap"]
        self.assertEqual(wrap["projectId"], self.project.id)
        self.assertEqual(wrap["filename"], payload["filename"])
        # File actually exists on disk inside the sandbox.
        abs_path = Path(wrap["absolutePath"])
        self.assertTrue(abs_path.exists())
        self.assertTrue(str(abs_path).startswith(self.tmp.name))
        # Same bytes-written count as len(markdown bytes).
        self.assertEqual(
            wrap["bytesWritten"],
            len(payload["markdown"].encode("utf-8")),
        )

    def test_save_rejects_missing_markdown(self) -> None:
        resp = self.client.post(
            self._url(),
            data=json.dumps({"filename": "x.md"}),
            headers={
                "Content-Type": "application/json",
                **self.auth_headers(self.alice),
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_save_rejects_path_traversal(self) -> None:
        resp = self.client.post(
            self._url(),
            data=json.dumps({"markdown": "ok", "filename": "../boom.md"}),
            headers={
                "Content-Type": "application/json",
                **self.auth_headers(self.alice),
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_save_rejects_other_user(self) -> None:
        resp = self.client.post(
            self._url(),
            data=json.dumps({"markdown": "ok", "filename": "x.md"}),
            headers={
                "Content-Type": "application/json",
                **self.auth_headers(self.bob),
            },
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
