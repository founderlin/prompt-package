"""Conversation + message endpoints (R7 + R8 + R9 + R13).

* ``GET    /api/conversations``                — list all conversations for the user (R8).
* ``GET    /api/conversations/<id>``           — fetch a conversation with full message history.
* ``PATCH  /api/conversations/<id>``           — update mutable fields (currently: ``context_pack_id``) (R13).
* ``DELETE /api/conversations/<id>``           — remove a conversation (and its messages).
* ``GET    /api/conversations/<id>/messages``  — list messages.
* ``POST   /api/conversations/<id>/messages``  — append a user message and call OpenRouter.
* ``POST   /api/conversations/<id>/summarize`` — run wrap-up + memory extraction (R9).
* ``GET    /api/conversations/<id>/memories``  — list memories extracted from this conversation (R9).

Anything not owned by the caller surfaces as 404.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.chat_service import (
    MAX_LIST_LIMIT,
    ChatError,
    count_for_user,
    delete_conversation,
    get_conversation_for_user,
    list_messages,
    list_recent_for_user,
    send_user_message,
    set_context_pack,
)
from app.services.memory_service import (
    MemoryError,
    list_for_conversation as list_memories_for_conversation,
    summarize_conversation,
)
from app.utils.auth import get_current_user, login_required

conversations_bp = Blueprint("conversations", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(err: ChatError):
    return jsonify({"error": err.code, "message": err.message}), err.status


def _memory_error(err: MemoryError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@conversations_bp.get("")
@login_required
def index():
    user = get_current_user()
    raw_limit = request.args.get("limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else 20
    except (TypeError, ValueError):
        limit = 20
    if limit < 1:
        limit = 1
    if limit > MAX_LIST_LIMIT:
        limit = MAX_LIST_LIMIT

    conversations = list_recent_for_user(user, limit=limit)
    return jsonify(
        {
            "conversations": [
                c.to_dict(include_message_count=True, include_project=True)
                for c in conversations
            ],
            "total": count_for_user(user),
            "limit": limit,
        }
    )


@conversations_bp.get("/<int:conversation_id>")
@login_required
def show(conversation_id: int):
    user = get_current_user()
    try:
        convo = get_conversation_for_user(user, conversation_id)
    except ChatError as err:
        return _error(err)
    return jsonify({"conversation": convo.to_dict(include_messages=True)})


@conversations_bp.patch("/<int:conversation_id>")
@login_required
def update(conversation_id: int):
    """Patch mutable fields on a conversation. Currently: ``context_pack_id``."""
    user = get_current_user()
    data = _payload()
    if "context_pack_id" not in data:
        return jsonify({"error": "validation_error", "message": "Nothing to update."}), 400
    raw = data.get("context_pack_id")
    pack_id: int | None
    if raw is None:
        pack_id = None
    else:
        try:
            pack_id = int(raw)
        except (TypeError, ValueError):
            return (
                jsonify({"error": "validation_error", "message": "context_pack_id must be an integer or null."}),
                400,
            )
    try:
        convo = set_context_pack(user, conversation_id, pack_id)
    except ChatError as err:
        return _error(err)
    return jsonify({"conversation": convo.to_dict(include_project=True)})


@conversations_bp.delete("/<int:conversation_id>")
@login_required
def destroy(conversation_id: int):
    user = get_current_user()
    try:
        delete_conversation(user, conversation_id)
    except ChatError as err:
        return _error(err)
    return jsonify({"status": "ok"})


@conversations_bp.get("/<int:conversation_id>/messages")
@login_required
def index_messages(conversation_id: int):
    user = get_current_user()
    try:
        messages = list_messages(user, conversation_id)
    except ChatError as err:
        return _error(err)
    return jsonify({"messages": [m.to_dict() for m in messages]})


@conversations_bp.post("/<int:conversation_id>/messages")
@login_required
def create_message(conversation_id: int):
    user = get_current_user()
    data = _payload()
    try:
        user_msg, assistant_msg, convo = send_user_message(
            user,
            conversation_id,
            content=data.get("content"),
            model=data.get("model"),
            provider=data.get("provider"),
        )
    except ChatError as err:
        return _error(err)
    return (
        jsonify(
            {
                "conversation": convo.to_dict(),
                "user_message": user_msg.to_dict(),
                "assistant_message": assistant_msg.to_dict(),
            }
        ),
        201,
    )


@conversations_bp.post("/<int:conversation_id>/summarize")
@login_required
def summarize(conversation_id: int):
    user = get_current_user()
    data = _payload()
    try:
        convo, memories = summarize_conversation(
            user,
            conversation_id,
            model=data.get("model"),
        )
    except MemoryError as err:
        return _memory_error(err)
    return (
        jsonify(
            {
                "conversation": convo.to_dict(),
                "memories": [m.to_dict() for m in memories],
            }
        ),
        200,
    )


@conversations_bp.get("/<int:conversation_id>/memories")
@login_required
def index_memories(conversation_id: int):
    user = get_current_user()
    try:
        memories = list_memories_for_conversation(user, conversation_id)
    except MemoryError as err:
        return _memory_error(err)
    return jsonify({"memories": [m.to_dict() for m in memories]})
