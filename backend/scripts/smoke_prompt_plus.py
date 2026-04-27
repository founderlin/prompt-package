"""Smoke-test R13: Context Pack as Prompt Plus.

Run from ``backend/`` with the venv active:

    python scripts/smoke_prompt_plus.py

Verifies:
- ``create_conversation`` can attach a Context Pack at creation time.
- ``set_context_pack`` can attach / detach / swap packs after the fact.
- Cross-user pack lookups are blocked (404).
- ``send_user_message`` injects the pack body as a leading system message
  on every OpenRouter call (and persists none of it in messages).
- Detaching a pack removes that system injection on subsequent calls.

The script prints PASS/FAIL and exits non-zero on any assertion error.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "smoke-secret")
os.environ.setdefault("JWT_SECRET_KEY", "smoke-jwt")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import ContextPack, Project, User  # noqa: E402
from app.services import chat_service  # noqa: E402
from app.services.openrouter_service import ChatCompletion  # noqa: E402
from app.services.settings_service import save_openrouter_key  # noqa: E402


PASS = "[PASS]"
FAIL = "[FAIL]"


PACK_BODY = """# Smoke Test Pack

The project is in MVP mode and ships incrementally.

## Decisions
- Use SQLite for now.

## Open Todos
- Wire Prompt Plus into chat.

## Notes for the next session
- The chat layer should inject this body as a system message.
"""


def _make_user(email: str) -> User:
    user = User(email=email, password_hash="x")
    db.session.add(user)
    db.session.commit()
    save_openrouter_key(user, "sk-or-test-key", verify=False)
    return user


def _make_project(user: User, name: str) -> Project:
    p = Project(user_id=user.id, name=name, description="smoke")
    db.session.add(p)
    db.session.commit()
    return p


def _make_pack(user: User, project: Project, *, title: str = "Smoke Pack", body: str = PACK_BODY) -> ContextPack:
    pack = ContextPack(
        user_id=user.id,
        project_id=project.id,
        title=title,
        body=body,
        model="openai/gpt-4o-mini",
        memory_count=3,
    )
    pack.set_source_memory_ids([1, 2, 3])
    db.session.add(pack)
    db.session.commit()
    db.session.refresh(pack)
    return pack


def _fake_completion(content: str = "Sure thing.") -> ChatCompletion:
    return ChatCompletion(
        content=content,
        model="openai/gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=4,
        total_tokens=14,
        finish_reason="stop",
        raw_id="fake-id",
    )


def run() -> int:
    app = create_app()
    failures: list[str] = []

    with app.app_context():
        db.drop_all()
        db.create_all()

        alice = _make_user("alice@example.com")
        bob = _make_user("bob@example.com")

        proj = _make_project(alice, "MVP")
        other_proj = _make_project(alice, "Other")

        pack = _make_pack(alice, proj, title="Pack A")
        cross_pack = _make_pack(alice, other_proj, title="Pack B (other project)")
        bobs_pack = _make_pack(bob, _make_project(bob, "Bob's"), title="Bob's Pack")

        try:
            convo = chat_service.create_conversation(
                alice, proj.id, model="openai/gpt-4o-mini", context_pack_id=pack.id
            )
            assert convo.context_pack_id == pack.id
            assert convo.context_pack is not None
            assert convo.context_pack.title == "Pack A"
            print(f"{PASS} create_conversation attaches pack at creation")
        except AssertionError as e:
            failures.append(f"create_conversation w/ pack: {e}")
            print(f"{FAIL} create_conversation w/ pack: {e}")

        try:
            chat_service.create_conversation(
                alice, proj.id, model="openai/gpt-4o-mini", context_pack_id=bobs_pack.id
            )
            failures.append("create_conversation should reject another user's pack")
            print(f"{FAIL} create_conversation should reject another user's pack")
        except chat_service.ChatError as e:
            assert e.code == "context_pack_not_found", e.code
            assert e.status == 404
            print(f"{PASS} create_conversation blocks foreign pack with 404")

        try:
            convo2 = chat_service.create_conversation(alice, proj.id)
            assert convo2.context_pack_id is None
            updated = chat_service.set_context_pack(alice, convo2.id, cross_pack.id)
            assert updated.context_pack_id == cross_pack.id
            assert updated.context_pack.project_id == other_proj.id
            print(f"{PASS} set_context_pack supports cross-project pack reuse")
        except (AssertionError, chat_service.ChatError) as e:
            failures.append(f"cross-project attach: {e}")
            print(f"{FAIL} cross-project attach: {e}")

        try:
            cleared = chat_service.set_context_pack(alice, convo2.id, None)
            assert cleared.context_pack_id is None
            assert cleared.context_pack is None
            print(f"{PASS} set_context_pack(None) detaches the pack")
        except (AssertionError, chat_service.ChatError) as e:
            failures.append(f"detach: {e}")
            print(f"{FAIL} detach: {e}")

        try:
            chat_service.set_context_pack(alice, convo.id, bobs_pack.id)
            failures.append("set_context_pack should reject foreign pack")
            print(f"{FAIL} set_context_pack should reject foreign pack")
        except chat_service.ChatError as e:
            assert e.code == "context_pack_not_found"
            print(f"{PASS} set_context_pack blocks foreign pack with 404")

        # send_user_message — pack body should appear in the OpenRouter payload
        # as a leading system message, but never persist into the messages table.
        captured_payloads: list[list[dict]] = []

        def fake_chat_completion(_api_key, *, model, messages, **_kwargs):
            captured_payloads.append(list(messages))
            return _fake_completion("ack")

        try:
            with patch(
                "app.services.chat_service.chat_completion",
                side_effect=fake_chat_completion,
            ):
                user_msg, assistant_msg, refreshed = chat_service.send_user_message(
                    alice, convo.id, content="hello", model="openai/gpt-4o-mini"
                )
            assert captured_payloads, "OpenRouter never called"
            payload = captured_payloads[-1]
            assert payload[0]["role"] == "system", payload[0]
            assert "PROJECT CONTEXT PACK" in payload[0]["content"]
            assert pack.body.strip() in payload[0]["content"]
            assert payload[-1] == {"role": "user", "content": "hello"}
            # Pack body is NOT persisted as a message.
            stored = list(refreshed.messages.all())
            assert all("PROJECT CONTEXT PACK" not in (m.content or "") for m in stored)
            assert any(m.role == "user" and m.content == "hello" for m in stored)
            assert any(m.role == "assistant" and m.content == "ack" for m in stored)
            print(f"{PASS} send_user_message injects pack as system + omits from history")
        except (AssertionError, chat_service.ChatError) as e:
            failures.append(f"system injection: {e}")
            print(f"{FAIL} system injection: {e}")

        # Detach and verify the next call has NO system message.
        try:
            chat_service.set_context_pack(alice, convo.id, None)
            captured_payloads.clear()
            with patch(
                "app.services.chat_service.chat_completion",
                side_effect=fake_chat_completion,
            ):
                chat_service.send_user_message(
                    alice, convo.id, content="round 2", model="openai/gpt-4o-mini"
                )
            payload = captured_payloads[-1]
            assert all(m["role"] != "system" for m in payload[:1]), payload[:1]
            print(f"{PASS} detached conversation no longer prepends pack")
        except (AssertionError, chat_service.ChatError) as e:
            failures.append(f"detach injection: {e}")
            print(f"{FAIL} detach injection: {e}")

        # Pack survival: deleting the pack out from under a bound conversation
        # should not crash send_user_message; we just skip the injection.
        try:
            new_pack = _make_pack(alice, proj, title="Soon to be deleted")
            chat_service.set_context_pack(alice, convo.id, new_pack.id)
            db.session.delete(new_pack)
            db.session.commit()
            db.session.refresh(convo)
            captured_payloads.clear()
            with patch(
                "app.services.chat_service.chat_completion",
                side_effect=fake_chat_completion,
            ):
                chat_service.send_user_message(
                    alice, convo.id, content="round 3", model="openai/gpt-4o-mini"
                )
            payload = captured_payloads[-1]
            # No system injection because pack is gone (FK SET NULL behaviour
            # in app code falls back to "no pack").
            assert all(m["role"] != "system" for m in payload[:1])
            print(f"{PASS} deleted pack does not break a bound conversation")
        except Exception as e:  # noqa: BLE001
            failures.append(f"deleted pack survival: {e}")
            print(f"{FAIL} deleted pack survival: {e}")

    if failures:
        print()
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print()
    print("All R13 Prompt Plus smoke checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
