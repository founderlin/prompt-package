"""Tests for streaming chat (SSE) — Phase X polish.

Covers:

* :func:`chat_completion_stream` parsing of OpenAI-compatible SSE deltas.
* :func:`send_user_message_stream` persistence semantics (user msg
  committed before LLM, assistant msg + usage committed after).
* The ``POST /api/conversations/<id>/messages/stream`` route emitting
  ordered SSE events with a final assistant_message + conversation
  pair.
* Error events when the upstream LLM fails mid-stream.

LLM calls are mocked end-to-end via :mod:`unittest.mock` — no network.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "stream-secret")
os.environ.setdefault("JWT_SECRET_KEY", "stream-jwt")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Conversation, Message, Project, User  # noqa: E402
from app.services.chat_service import (  # noqa: E402
    regenerate_last_assistant_stream,
    send_user_message_stream,
)
from app.services.llm_service import (  # noqa: E402
    ChatCompletion,
    LLMError,
    chat_completion_stream,
)
from app.utils.auth import issue_token  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers


class _FakeStreamResponse:
    """Minimal stand-in for a ``requests.Response`` in streaming mode.

    The real chat_completion_stream pulls raw bytes via
    ``iter_content`` and does its own line/codepoint splitting.  This
    fake yields one chunk per provided "line" (encoded to bytes) plus
    a trailing newline so the parser sees deterministic record
    boundaries.  We optionally let callers split a long string across
    a multi-byte boundary by passing their own bytes via
    ``raw_chunks``.
    """

    def __init__(
        self,
        lines: list[str] | None = None,
        status_code: int = 200,
        raw_chunks: list[bytes] | None = None,
    ) -> None:
        if raw_chunks is not None:
            self._chunks = list(raw_chunks)
        else:
            self._chunks = [
                (line + "\n").encode("utf-8") for line in (lines or [])
            ]
        self.status_code = status_code

    def iter_content(self, chunk_size=None, decode_unicode: bool = False):
        for chunk in self._chunks:
            yield chunk

    def json(self):  # pragma: no cover - only used on error paths
        return {}

    def close(self) -> None:
        return None


def _sse(payload: str) -> str:
    return f"data: {payload}"


# ---------------------------------------------------------------------------
# llm_service.chat_completion_stream — pure parser behavior.


class ChatCompletionStreamParserTest(unittest.TestCase):
    """The provider-facing streaming helper.

    Pure SSE parsing — we mock ``requests.post`` so no real network
    happens. We still need a Flask application context because
    :mod:`llm_service` reads ``current_app.config`` to build the
    ``User-Agent`` header.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = create_app()
        cls._ctx = cls._app.app_context()
        cls._ctx.push()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._ctx.pop()

    def _mock_request(self, lines: list[str]):
        fake = _FakeStreamResponse(lines)
        return patch(
            "app.services.llm_service.requests.post",
            return_value=fake,
        )

    def test_assembles_text_from_delta_chunks(self) -> None:
        lines = [
            _sse('{"id":"x","model":"m","choices":[{"delta":{"content":"Hel"}}]}'),
            "",  # blank line between SSE records — must be tolerated
            _sse('{"choices":[{"delta":{"content":"lo "}}]}'),
            _sse('{"choices":[{"delta":{"content":"world"},"finish_reason":"stop"}],'
                 '"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}'),
            "data: [DONE]",
        ]
        with self._mock_request(lines):
            events = list(
                chat_completion_stream(
                    "k", model="m", messages=[{"role": "user", "content": "hi"}],
                    provider="openai",
                )
            )

        deltas = [v for k, v in events if k == "delta"]
        dones = [v for k, v in events if k == "done"]
        self.assertEqual(deltas, ["Hel", "lo ", "world"])
        self.assertEqual(len(dones), 1)
        completion = dones[0]
        self.assertIsInstance(completion, ChatCompletion)
        self.assertEqual(completion.content, "Hello world")
        self.assertEqual(completion.prompt_tokens, 3)
        self.assertEqual(completion.completion_tokens, 2)
        self.assertEqual(completion.finish_reason, "stop")

    def test_skips_comment_lines_and_bad_json(self) -> None:
        lines = [
            ":heartbeat",
            _sse('not-json'),  # parser silently skips malformed records
            _sse('{"choices":[{"delta":{"content":"ok"}}]}'),
            "data: [DONE]",
        ]
        with self._mock_request(lines):
            events = list(
                chat_completion_stream(
                    "k", model="m", messages=[{"role": "user", "content": "x"}],
                    provider="openai",
                )
            )
        deltas = [v for k, v in events if k == "delta"]
        self.assertEqual(deltas, ["ok"])

    def test_raises_on_empty_stream(self) -> None:
        # 200 OK, but no content fragments anywhere — counted as an
        # upstream failure to match the non-streaming version.
        lines = ["data: [DONE]"]
        with self._mock_request(lines):
            with self.assertRaises(LLMError) as ctx:
                list(
                    chat_completion_stream(
                        "k", model="m",
                        messages=[{"role": "user", "content": "x"}],
                        provider="openai",
                    )
                )
        self.assertEqual(ctx.exception.code, "llm_empty_content")

    def test_decodes_cjk_across_chunk_boundary(self) -> None:
        """Regression test for the mojibake bug.

        We deliberately split the 3-byte UTF-8 encoding of ``你`` so
        the first chunk ends mid-codepoint. The old implementation
        (``iter_lines(decode_unicode=True)``) would decode each chunk
        separately and corrupt the character; the new
        ``iter_content`` + byte-level buffering must reassemble it
        cleanly.
        """
        line = 'data: {"choices":[{"delta":{"content":"你好"}}]}'
        line_bytes = (line + "\n").encode("utf-8")
        # Find the byte index in the middle of the encoding of ``你``
        # (its first byte sits at position ``i``; we cut at i+1 so
        # the first chunk contains a partial codepoint).
        you_byte = "你".encode("utf-8")[0]
        cut = line_bytes.index(bytes([you_byte])) + 1
        raw_chunks = [
            line_bytes[:cut],
            line_bytes[cut:],
            b"data: [DONE]\n",
        ]
        fake = _FakeStreamResponse(raw_chunks=raw_chunks)
        with patch(
            "app.services.llm_service.requests.post",
            return_value=fake,
        ):
            events = list(
                chat_completion_stream(
                    "k", model="m",
                    messages=[{"role": "user", "content": "x"}],
                    provider="openai",
                )
            )
        deltas = [v for k, v in events if k == "delta"]
        self.assertEqual(deltas, ["你好"])

    def test_rejects_blank_api_key(self) -> None:
        with self.assertRaises(LLMError) as ctx:
            list(
                chat_completion_stream(
                    "", model="m",
                    messages=[{"role": "user", "content": "x"}],
                    provider="openai",
                )
            )
        self.assertEqual(ctx.exception.code, "invalid_api_key")


# ---------------------------------------------------------------------------
# Service + route streaming end-to-end (mocked LLM).


def _make_user(email: str = "a@b.c") -> User:
    user = User(email=email)
    user.set_password("Password!1")
    db.session.add(user)
    db.session.commit()
    return user


def _make_project(user: User) -> Project:
    p = Project(user_id=user.id, name="Stream Demo", description="")
    db.session.add(p)
    db.session.commit()
    return p


def _make_convo(user: User, project: Project) -> Conversation:
    convo = Conversation(
        user_id=user.id, project_id=project.id,
        title="t", model="openai/gpt-4o-mini", provider="openrouter",
    )
    db.session.add(convo)
    db.session.commit()
    return convo


class StreamFlaskTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()
        self.alice = _make_user("alice@example.com")
        self.project = _make_project(self.alice)
        self.convo = _make_convo(self.alice, self.project)

    def auth(self) -> dict:
        return {"Authorization": f"Bearer {issue_token(self.alice)}"}


class SendUserMessageStreamServiceTest(StreamFlaskTestCase):
    def test_yields_events_and_persists_messages(self) -> None:
        def fake_stream(*_args, **_kwargs):
            yield ("delta", "Hi ")
            yield ("delta", "there")
            yield (
                "done",
                ChatCompletion(
                    content="Hi there",
                    model="openrouter/m",
                    prompt_tokens=5,
                    completion_tokens=2,
                    total_tokens=7,
                    finish_reason="stop",
                    raw_id="r1",
                    provider="openrouter",
                ),
            )

        with patch(
            "app.services.chat_service.chat_completion_stream",
            side_effect=fake_stream,
        ), patch(
            "app.services.chat_service.get_decrypted_key_for",
            return_value="sk-key",
        ):
            events = list(
                send_user_message_stream(
                    self.alice, self.convo.id, content="Hello?",
                )
            )

        kinds = [k for k, _ in events]
        self.assertEqual(
            kinds,
            ["user_message", "delta", "delta", "assistant_message", "conversation"],
        )

        # The assistant message landed in the DB with the right content
        # and the usage metrics from the synthesized ``done`` event.
        msgs = (
            db.session.query(Message)
            .filter(Message.conversation_id == self.convo.id)
            .order_by(Message.id.asc())
            .all()
        )
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "user")
        self.assertEqual(msgs[1].role, "assistant")
        self.assertEqual(msgs[1].content, "Hi there")
        self.assertEqual(msgs[1].prompt_tokens, 5)
        self.assertEqual(msgs[1].completion_tokens, 2)


class CreateMessageStreamRouteTest(StreamFlaskTestCase):
    def test_route_emits_sse_events_in_order(self) -> None:
        def fake_stream(*_a, **_k):
            yield ("delta", "Hello")
            yield (
                "done",
                ChatCompletion(
                    content="Hello", model="m",
                    prompt_tokens=1, completion_tokens=1, total_tokens=2,
                    finish_reason="stop", raw_id=None, provider="openrouter",
                ),
            )

        with patch(
            "app.services.chat_service.chat_completion_stream",
            side_effect=fake_stream,
        ), patch(
            "app.services.chat_service.get_decrypted_key_for",
            return_value="sk-key",
        ):
            resp = self.client.post(
                f"/api/conversations/{self.convo.id}/messages/stream",
                json={"content": "hi"},
                headers=self.auth(),
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn(
                "text/event-stream", resp.headers.get("Content-Type", "")
            )
            body = b"".join(resp.response).decode("utf-8")

        # Verify ordering: user_message → delta → assistant_message → conversation.
        # We don't pin exact JSON shapes here; the service-level test
        # above already covered that. Just check the SSE event names.
        self.assertLess(body.index("event: user_message"), body.index("event: delta"))
        self.assertLess(
            body.index("event: delta"), body.index("event: assistant_message")
        )
        self.assertLess(
            body.index("event: assistant_message"),
            body.index("event: conversation"),
        )

    def test_route_emits_error_event_on_llm_failure(self) -> None:
        def fake_stream(*_a, **_k):
            yield ("delta", "partial-")
            raise LLMError(
                "boom", status=502, code="llm_error", provider="openrouter"
            )

        with patch(
            "app.services.chat_service.chat_completion_stream",
            side_effect=fake_stream,
        ), patch(
            "app.services.chat_service.get_decrypted_key_for",
            return_value="sk-key",
        ):
            resp = self.client.post(
                f"/api/conversations/{self.convo.id}/messages/stream",
                json={"content": "hi"},
                headers=self.auth(),
            )
            self.assertEqual(resp.status_code, 200)
            body = b"".join(resp.response).decode("utf-8")

        # The user_message event still fires (LLM call happens after
        # the user row is committed), then the error event terminates.
        self.assertIn("event: user_message", body)
        self.assertIn("event: error", body)
        self.assertIn("\"llm_error\"", body)


class RegenerateStreamInPlaceTest(StreamFlaskTestCase):
    """OpenRouter-style retry semantics — rewrite ONE message in place."""

    def _seed_thread(self):
        """Build A/A1/B/B1/C/C1 so we have a "middle" assistant to retry."""
        from app.models import Message
        rows = []
        for role, content in [
            ("user", "A"),
            ("assistant", "A1"),
            ("user", "B"),
            ("assistant", "B1"),
            ("user", "C"),
            ("assistant", "C1"),
        ]:
            m = Message(conversation_id=self.convo.id, role=role, content=content)
            db.session.add(m)
            rows.append(m)
        db.session.commit()
        return rows

    def _fake_completion(self, content="rewritten"):
        def fake(*_a, **_k):
            yield ("delta", content)
            yield (
                "done",
                ChatCompletion(
                    content=content,
                    model="m",
                    prompt_tokens=1, completion_tokens=1, total_tokens=2,
                    finish_reason="stop", raw_id=None, provider="openrouter",
                ),
            )
        return fake

    def test_retry_middle_assistant_preserves_trailing_messages(self) -> None:
        from app.models import Message
        rows = self._seed_thread()
        # rows = [A=0, A1=1, B=2, B1=3, C=4, C1=5]
        a1 = rows[1]
        a1_id = a1.id
        # Snapshot the trailing rows before retry.
        b_id, b1_id, c_id, c1_id = rows[2].id, rows[3].id, rows[4].id, rows[5].id

        with patch(
            "app.services.chat_service.chat_completion_stream",
            side_effect=self._fake_completion("A1-fresh"),
        ), patch(
            "app.services.chat_service.get_decrypted_key_for",
            return_value="sk-key",
        ):
            list(
                regenerate_last_assistant_stream(
                    self.alice, self.convo.id, pivot_message_id=a1_id,
                )
            )

        # A1 must still exist, with new content, and the same id.
        a1_after = db.session.get(Message, a1_id)
        self.assertIsNotNone(a1_after)
        self.assertEqual(a1_after.content, "A1-fresh")
        self.assertEqual(a1_after.id, a1_id)

        # And every row after A1 must still be there, untouched.
        for mid, expected in [
            (b_id, "B"), (b1_id, "B1"), (c_id, "C"), (c1_id, "C1"),
        ]:
            row = db.session.get(Message, mid)
            self.assertIsNotNone(row, f"row {mid} disappeared after retry")
            self.assertEqual(row.content, expected)

    def test_retry_on_user_rewrites_following_assistant(self) -> None:
        from app.models import Message
        rows = self._seed_thread()
        b = rows[2]  # the "B" user turn
        b1_id = rows[3].id  # the assistant that follows B
        trailing_ids = [rows[4].id, rows[5].id]

        with patch(
            "app.services.chat_service.chat_completion_stream",
            side_effect=self._fake_completion("B1-fresh"),
        ), patch(
            "app.services.chat_service.get_decrypted_key_for",
            return_value="sk-key",
        ):
            list(
                regenerate_last_assistant_stream(
                    self.alice, self.convo.id, pivot_message_id=b.id,
                )
            )

        b1_after = db.session.get(Message, b1_id)
        self.assertEqual(b1_after.content, "B1-fresh")
        for mid in trailing_ids:
            self.assertIsNotNone(
                db.session.get(Message, mid),
                f"trailing row {mid} should survive a user-pivot retry",
            )

    def test_retry_emits_in_place_assistant_id(self) -> None:
        rows = self._seed_thread()
        a1_id = rows[1].id

        with patch(
            "app.services.chat_service.chat_completion_stream",
            side_effect=self._fake_completion("ok"),
        ), patch(
            "app.services.chat_service.get_decrypted_key_for",
            return_value="sk-key",
        ):
            events = list(
                regenerate_last_assistant_stream(
                    self.alice, self.convo.id, pivot_message_id=a1_id,
                )
            )

        # The assistant_message event must carry the original id so
        # the frontend can swap content into the same bubble.
        asm = next(v for k, v in events if k == "assistant_message")
        self.assertEqual(asm["id"], a1_id)


if __name__ == "__main__":
    unittest.main()
