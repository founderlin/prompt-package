"""Smoke-test the Context Pack service end-to-end against an in-memory SQLite.

Run from ``backend/`` with the venv active:

    python scripts/smoke_context_packs.py

It creates two users, gives one of them a project + a couple of memories,
monkeypatches OpenRouter, generates a pack, then verifies cross-user
isolation, the ``no_memories`` guard, and the inline title/body update path.

The script prints PASS/FAIL lines and exits non-zero on any assertion error.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Use an in-memory SQLite to avoid touching the dev DB.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "smoke-secret")
os.environ.setdefault("JWT_SECRET_KEY", "smoke-jwt")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import ContextPack, Memory, Project, User  # noqa: E402
from app.services import context_pack_service  # noqa: E402
from app.services.openrouter_service import ChatCompletion  # noqa: E402
from app.services.settings_service import save_openrouter_key  # noqa: E402


PASS = "[PASS]"
FAIL = "[FAIL]"

SAMPLE_BODY = """# Test Pack

A short summary of where the project stands.

## Decisions
- Use SQLite for MVP.

## Open Todos
- Wire up Context Packs in the UI.

## Key Facts
- Backend runs on Flask + SQLAlchemy.

## Open Questions
- When to migrate to Postgres?

## Notes for the next session
- Start with the project detail page.
"""


def make_user(email: str, password: str = "Password!1") -> User:
    user = User(email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def add_memory(user: User, project: Project, *, kind: str, content: str) -> Memory:
    mem = Memory(
        user_id=user.id,
        project_id=project.id,
        conversation_id=None,
        kind=kind,
        content=content,
    )
    db.session.add(mem)
    db.session.commit()
    return mem


def fake_completion(*_args, **_kwargs) -> ChatCompletion:
    return ChatCompletion(
        content=SAMPLE_BODY,
        model="openai/gpt-4o-mini",
        prompt_tokens=120,
        completion_tokens=80,
        total_tokens=200,
        finish_reason="stop",
        raw_id="cmpl-smoke",
    )


def main() -> int:
    app = create_app()
    failures: list[str] = []

    with app.app_context():
        try:
            db.drop_all()
            db.create_all()

            alice = make_user("alice@example.com")
            bob = make_user("bob@example.com")

            # Both users get an OpenRouter API key on file (encrypted).
            # We pass verify=False so the smoke test never hits the network.
            save_openrouter_key(alice, "sk-or-v1-aaaaaaaaaaaaaaaaaa", verify=False)
            save_openrouter_key(bob, "sk-or-v1-bbbbbbbbbbbbbbbbbb", verify=False)

            project = Project(user_id=alice.id, name="Demo project", description="Demo")
            db.session.add(project)
            db.session.commit()

            mem1 = add_memory(alice, project, kind="decision", content="Pick Vue 3.")
            mem2 = add_memory(alice, project, kind="todo", content="Ship Context Packs.")
            mem3 = add_memory(alice, project, kind="fact", content="Backend on Flask.")

            empty_project = Project(user_id=alice.id, name="Empty project")
            db.session.add(empty_project)
            db.session.commit()

            # --- 1. happy path ---
            with patch(
                "app.services.context_pack_service.chat_completion",
                side_effect=fake_completion,
            ):
                pack = context_pack_service.generate(
                    alice,
                    project.id,
                    title="My pack",
                    instructions="Keep it short.",
                )
            assert pack.id is not None, "pack should be persisted"
            assert pack.project_id == project.id
            assert pack.user_id == alice.id
            assert pack.memory_count == 3
            assert pack.body.startswith("# Test Pack")
            assert pack.title == "My pack"
            assert pack.instructions == "Keep it short."
            assert pack.total_tokens == 200
            assert sorted(pack.get_source_memory_ids()) == sorted(
                [mem1.id, mem2.id, mem3.id]
            )
            print(PASS, "generate(): persists pack with title/body/source_memory_ids")

            # --- 2. selecting only some memories works ---
            with patch(
                "app.services.context_pack_service.chat_completion",
                side_effect=fake_completion,
            ):
                pack2 = context_pack_service.generate(
                    alice,
                    project.id,
                    memory_ids=[mem1.id, mem2.id, "999"],  # 999 doesn't belong to alice
                )
            assert pack2.memory_count == 2, "should only count actually-found memories"
            assert sorted(pack2.get_source_memory_ids()) == sorted([mem1.id, mem2.id])
            assert pack2.title.startswith("Demo project · Context Pack")
            print(PASS, "generate(memory_ids=...): trims to owned memories + auto title")

            # --- 3. no_memories on empty project ---
            try:
                with patch(
                    "app.services.context_pack_service.chat_completion",
                    side_effect=fake_completion,
                ):
                    context_pack_service.generate(alice, empty_project.id)
            except context_pack_service.ContextPackError as err:
                assert err.code == "no_memories", err.code
                print(PASS, "generate() on empty project raises no_memories")
            else:
                raise AssertionError("expected ContextPackError(no_memories)")

            # --- 4. cross-user isolation: bob sees nothing for alice's pack ---
            try:
                context_pack_service.get_for_user(bob, pack.id)
            except context_pack_service.ContextPackError as err:
                assert err.code == "not_found" and err.status == 404
                print(PASS, "get_for_user() blocks cross-user access (404)")
            else:
                raise AssertionError("bob should not see alice's pack")

            try:
                context_pack_service.delete_pack(bob, pack.id)
            except context_pack_service.ContextPackError as err:
                assert err.code == "not_found"
                print(PASS, "delete_pack() blocks cross-user access (404)")
            else:
                raise AssertionError("bob should not delete alice's pack")

            # --- 5. list_for_project / list_recent_for_user ---
            packs_for_project = context_pack_service.list_for_project(alice, project.id)
            assert len(packs_for_project) == 2
            recent = context_pack_service.list_recent_for_user(alice, limit=10)
            assert len(recent) == 2
            assert context_pack_service.list_recent_for_user(bob, limit=10) == []
            assert context_pack_service.count_for_user(alice) == 2
            assert context_pack_service.count_for_user(bob) == 0
            print(PASS, "list/count helpers respect ownership")

            # --- 6. update_pack: title/body, validation ---
            updated = context_pack_service.update_pack(
                alice,
                pack.id,
                title="New title",
                body="# Edited\n\nfine.",
                title_provided=True,
                body_provided=True,
            )
            assert updated.title == "New title"
            assert updated.body.startswith("# Edited")
            print(PASS, "update_pack(): edits title + body")

            try:
                context_pack_service.update_pack(
                    alice,
                    pack.id,
                    title="   ",
                    title_provided=True,
                )
            except context_pack_service.ContextPackError as err:
                assert err.code == "validation_error"
                print(PASS, "update_pack(): rejects empty title")
            else:
                raise AssertionError("expected validation_error for empty title")

            # --- 7. memory_ids that pick zero alice-owned rows raise no_memories_selected ---
            try:
                with patch(
                    "app.services.context_pack_service.chat_completion",
                    side_effect=fake_completion,
                ):
                    context_pack_service.generate(
                        alice, project.id, memory_ids=[999_999]
                    )
            except context_pack_service.ContextPackError as err:
                assert err.code in ("no_memories_selected", "no_memories"), err.code
                print(PASS, "generate(memory_ids=[bogus]) raises no_memories_selected")
            else:
                raise AssertionError("expected ContextPackError for bogus memory ids")

            # --- 8. tofdict shapes ---
            shape = pack.to_dict(include_body=False, body_preview=20)
            assert "body" not in shape
            assert "body_preview" in shape
            assert isinstance(shape["source_memory_ids"], list)
            print(PASS, "to_dict() respects include_body / body_preview")

            # Sanity-check ContextPack rows really hit the DB.
            count = db.session.query(ContextPack).count()
            assert count == 2
            print(PASS, f"DB has {count} packs total")

        except AssertionError as err:
            failures.append(f"AssertionError: {err}")
            traceback.print_exc()
        except Exception as err:  # noqa: BLE001
            failures.append(f"{type(err).__name__}: {err}")
            traceback.print_exc()

    if failures:
        print()
        for f in failures:
            print(FAIL, f)
        return 1
    print()
    print("All Context Pack smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
