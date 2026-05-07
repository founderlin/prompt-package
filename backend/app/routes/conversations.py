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

from flask import Blueprint, abort, jsonify, request, send_file

from app.services.attachment_service import (
    AttachmentError,
    delete as delete_attachment,
    get_for_user as get_attachment_for_user,
    list_for_conversation as list_attachments_for_conversation,
    read_bytes as read_attachment_bytes,
    upload as upload_attachment,
)
from app.services.chat_service import (
    MAX_LIST_LIMIT,
    ChatError,
    count_for_user,
    delete_conversation,
    delete_message_cascade,
    get_conversation_for_user,
    list_messages,
    list_recent_for_user,
    regenerate_last_assistant,
    send_user_message,
    set_context_pack,
)
from app.services.memory_service import (
    MemoryError,
    list_for_conversation as list_memories_for_conversation,
    summarize_conversation,
)
from app.services.wrap_up_service import (
    WrapUpError,
    wrap_up_conversation,
)
from app.utils.auth import get_current_user, login_required

conversations_bp = Blueprint("conversations", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(err: ChatError):
    return jsonify({"error": err.code, "message": err.message}), err.status


def _memory_error(err: MemoryError):
    return jsonify({"error": err.code, "message": err.message}), err.status


def _wrap_up_error(err: WrapUpError):
    return jsonify({"error": err.code, "message": err.message}), err.status


def _attachment_error(err: AttachmentError):
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
    raw_ids = data.get("attachment_ids") or []
    if not isinstance(raw_ids, list):
        return (
            jsonify(
                {
                    "error": "validation_error",
                    "message": "attachment_ids must be a list.",
                }
            ),
            400,
        )
    # ``context_items`` is optional. Accept both the canonical camelCase
    # shape used by the frontend (``contextItems``) and snake_case for
    # hand-rolled API calls. Service-layer validation enforces the
    # per-item schema.
    raw_context_items = (
        data.get("context_items")
        if "context_items" in data
        else data.get("contextItems")
    )
    try:
        user_msg, assistant_msg, convo = send_user_message(
            user,
            conversation_id,
            content=data.get("content"),
            model=data.get("model"),
            provider=data.get("provider"),
            attachment_ids=raw_ids,
            context_items=raw_context_items,
        )
    except ChatError as err:
        return _error(err)
    except AttachmentError as err:
        return _attachment_error(err)
    return (
        jsonify(
            {
                "conversation": convo.to_dict(),
                "user_message": user_msg.to_dict(include_attachments=True),
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


@conversations_bp.post("/<int:conversation_id>/wrap-up")
@login_required
def wrap_up(conversation_id: int):
    """Wrap the conversation up into a Context Pack.

    Body (all optional):
        title, goal,
        options: { includeRawReferences: bool, maxSummaryLength: int }

    Returns the new Context Pack + the job record used to drive
    progress in the UI. The job is always ``completed`` on the happy
    path of this MVP because execution is synchronous.
    """
    user = get_current_user()
    data = _payload()
    try:
        pack, job = wrap_up_conversation(
            get_current_user(),
            conversation_id,
            payload=data,
        )
    except WrapUpError as err:
        return _wrap_up_error(err)
    return (
        jsonify(
            {
                "context_pack": pack.to_dict(
                    include_project=True,
                    include_sources=True,
                ),
                "job": job.to_dict(),
            }
        ),
        201,
    )


@conversations_bp.post("/<int:conversation_id>/regenerate")
@login_required
def regenerate(conversation_id: int):
    """Regenerate an assistant reply. Optionally pin it to a specific
    message (``message_id``) and/or edit the user turn's content first.

    Body fields (all optional):
        model, provider            — override the default for this call
        message_id                 — pivot point; defaults to latest assistant
        content                    — new user content; only honored when
                                     message_id refers to a user message
        attachment_ids             — new attachment set for the pivot user
                                     message; ``None`` leaves attachments
                                     alone, ``[]`` clears them all
    """
    user = get_current_user()
    data = _payload()
    raw_pivot = data.get("message_id")
    pivot_id: int | None
    if raw_pivot in (None, ""):
        pivot_id = None
    else:
        try:
            pivot_id = int(raw_pivot)
        except (TypeError, ValueError):
            return (
                jsonify(
                    {
                        "error": "validation_error",
                        "message": "message_id must be an integer.",
                    }
                ),
                400,
            )

    # Attachment ids are optional; a missing key means "don't touch the
    # existing set", an empty list means "remove everything".
    new_attachment_ids: list[int] | None
    if "attachment_ids" in data:
        raw_ids = data.get("attachment_ids")
        if not isinstance(raw_ids, list):
            return (
                jsonify(
                    {
                        "error": "validation_error",
                        "message": "attachment_ids must be a list.",
                    }
                ),
                400,
            )
        new_attachment_ids = raw_ids
    else:
        new_attachment_ids = None

    try:
        assistant_msg, convo = regenerate_last_assistant(
            user,
            conversation_id,
            model=data.get("model"),
            provider=data.get("provider"),
            pivot_message_id=pivot_id,
            new_user_content=data.get("content"),
            new_attachment_ids=new_attachment_ids,
        )
    except ChatError as err:
        return _error(err)
    except AttachmentError as err:
        return _attachment_error(err)
    return (
        jsonify(
            {
                "conversation": convo.to_dict(),
                "assistant_message": assistant_msg.to_dict(),
            }
        ),
        201,
    )


@conversations_bp.delete("/<int:conversation_id>/messages/<int:message_id>")
@login_required
def destroy_message(conversation_id: int, message_id: int):
    """Delete a message and every message that came after it in this convo.

    This matches the "edit/delete from here down" semantics that ChatGPT
    and OpenRouter use — trimming a turn in the middle would otherwise
    leave the rest of the thread with broken prompt continuity.
    """
    user = get_current_user()
    try:
        removed = delete_message_cascade(user, conversation_id, message_id)
    except ChatError as err:
        return _error(err)
    return jsonify({"status": "ok", "removed": removed})


@conversations_bp.get("/<int:conversation_id>/memories")
@login_required
def index_memories(conversation_id: int):
    user = get_current_user()
    try:
        memories = list_memories_for_conversation(user, conversation_id)
    except MemoryError as err:
        return _memory_error(err)
    return jsonify({"memories": [m.to_dict() for m in memories]})


# ---------- Attachments ------------------------------------------------------
#
# Attachments are scoped to a conversation. Upload first (multipart/form-data)
# to get an id, then reference ids in the next `create_message` call. Until a
# message is sent, attachments are "detached" and can be removed freely.


@conversations_bp.post("/<int:conversation_id>/attachments")
@login_required
def upload_conversation_attachment(conversation_id: int):
    user = get_current_user()
    file = request.files.get("file")
    if file is None or not getattr(file, "filename", None):
        return (
            jsonify(
                {
                    "error": "validation_error",
                    "message": "Missing uploaded file (field name: 'file').",
                }
            ),
            400,
        )
    try:
        data = file.read()
    except Exception:
        return (
            jsonify({"error": "io_error", "message": "Could not read the upload stream."}),
            400,
        )
    try:
        att = upload_attachment(
            user,
            conversation_id,
            filename=file.filename,
            mime_type=file.mimetype,
            data=data,
        )
    except AttachmentError as err:
        return _attachment_error(err)
    return jsonify({"attachment": att.to_dict()}), 201


@conversations_bp.get("/<int:conversation_id>/attachments")
@login_required
def list_conversation_attachments(conversation_id: int):
    user = get_current_user()
    try:
        rows = list_attachments_for_conversation(user, conversation_id)
    except AttachmentError as err:
        return _attachment_error(err)
    return jsonify({"attachments": [a.to_dict() for a in rows]})


@conversations_bp.delete("/<int:conversation_id>/attachments/<int:attachment_id>")
@login_required
def delete_conversation_attachment(conversation_id: int, attachment_id: int):
    user = get_current_user()
    try:
        att = get_attachment_for_user(user, attachment_id)
        if att.conversation_id != conversation_id:
            abort(404)
        delete_attachment(user, attachment_id)
    except AttachmentError as err:
        return _attachment_error(err)
    return jsonify({"status": "ok"})


@conversations_bp.get(
    "/<int:conversation_id>/attachments/<int:attachment_id>/download"
)
@login_required
def download_conversation_attachment(conversation_id: int, attachment_id: int):
    user = get_current_user()
    try:
        att = get_attachment_for_user(user, attachment_id)
    except AttachmentError as err:
        return _attachment_error(err)
    if att.conversation_id != conversation_id:
        abort(404)
    try:
        data = read_attachment_bytes(att)
    except AttachmentError as err:
        return _attachment_error(err)
    return send_file(
        # send_file wants a path-like or file-like; BytesIO keeps things simple.
        __import__("io").BytesIO(data),
        mimetype=att.mime_type,
        as_attachment=False,
        download_name=att.filename,
        max_age=0,
    )
