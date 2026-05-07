"""Project endpoints (R5).

All routes require a valid bearer token and are scoped to the caller's
own projects. Anything they don't own surfaces as 404.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.chat_service import ChatError, create_conversation, list_for_project
from app.services.bla_note_service import (
    BlaNoteError,
    create_for_project as create_note_for_project,
    list_for_project as list_notes_for_project,
)
from app.services.context_pack_service import (
    ContextPackError,
    generate as generate_context_pack,
    list_for_project as list_packs_for_project,
)
from app.services.memory_service import (
    MemoryError,
    list_for_project as list_memories_for_project,
)
from app.services.project_service import (
    ProjectError,
    count_for_user,
    create_for_user,
    delete_for_user,
    get_for_user,
    list_for_user,
    update_for_user,
)
from app.services.wrap_up_service import (
    WrapUpError,
    wrap_up_project,
)
from app.utils.auth import get_current_user, login_required

projects_bp = Blueprint("projects", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(err: ProjectError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@projects_bp.get("")
@login_required
def index():
    user = get_current_user()
    projects = list_for_user(user)
    return jsonify(
        {
            "projects": [p.to_dict() for p in projects],
            "total": count_for_user(user),
        }
    )


@projects_bp.post("")
@login_required
def create():
    user = get_current_user()
    data = _payload()
    try:
        project = create_for_user(
            user,
            name=data.get("name"),
            description=data.get("description"),
        )
    except ProjectError as err:
        return _error(err)
    return jsonify({"project": project.to_dict()}), 201


@projects_bp.get("/<int:project_id>")
@login_required
def show(project_id: int):
    user = get_current_user()
    try:
        project = get_for_user(user, project_id)
    except ProjectError as err:
        return _error(err)
    return jsonify({"project": project.to_dict()})


@projects_bp.patch("/<int:project_id>")
@login_required
def update(project_id: int):
    user = get_current_user()
    data = _payload()
    try:
        project = update_for_user(
            user,
            project_id,
            name=data.get("name"),
            description=data.get("description"),
            name_provided="name" in data,
            description_provided="description" in data,
        )
    except ProjectError as err:
        return _error(err)
    return jsonify({"project": project.to_dict()})


@projects_bp.delete("/<int:project_id>")
@login_required
def destroy(project_id: int):
    user = get_current_user()
    try:
        delete_for_user(user, project_id)
    except ProjectError as err:
        return _error(err)
    return jsonify({"status": "ok"})


def _chat_error(err: ChatError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@projects_bp.get("/<int:project_id>/conversations")
@login_required
def list_conversations(project_id: int):
    user = get_current_user()
    try:
        conversations = list_for_project(user, project_id)
    except ChatError as err:
        return _chat_error(err)
    return jsonify(
        {
            "conversations": [
                c.to_dict(include_message_count=True) for c in conversations
            ]
        }
    )


@projects_bp.post("/<int:project_id>/conversations")
@login_required
def create_conversation_route(project_id: int):
    user = get_current_user()
    data = _payload()
    raw_pack = data.get("context_pack_id")
    pack_id: int | None
    if raw_pack in (None, ""):
        pack_id = None
    else:
        try:
            pack_id = int(raw_pack)
        except (TypeError, ValueError):
            return (
                jsonify(
                    {
                        "error": "validation_error",
                        "message": "context_pack_id must be an integer or null.",
                    }
                ),
                400,
            )
    try:
        convo = create_conversation(
            user,
            project_id,
            model=data.get("model"),
            provider=data.get("provider"),
            context_pack_id=pack_id,
        )
    except ChatError as err:
        return _chat_error(err)
    return jsonify({"conversation": convo.to_dict(include_messages=True)}), 201


def _memory_error(err: MemoryError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@projects_bp.get("/<int:project_id>/memories")
@login_required
def list_memories(project_id: int):
    user = get_current_user()
    try:
        memories = list_memories_for_project(user, project_id)
    except MemoryError as err:
        return _memory_error(err)
    return jsonify(
        {"memories": [m.to_dict(include_conversation=True) for m in memories]}
    )


# ---- Bla Notes -------------------------------------------------------------
# Mounted on projects_bp (not on the bla_notes blueprint) because list + create
# are inherently project-scoped — same split we use for Memories.


def _note_error(err: BlaNoteError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@projects_bp.get("/<int:project_id>/notes")
@login_required
def list_notes(project_id: int):
    """List Bla Notes in this project.

    Supports the same filter semantics as Context Zoo for symmetry:
    ``keyword`` (title / content / tag substring), ``tag`` (exact tag
    match), ``limit`` (1..200, default 50), ``offset``. Ordered by
    most-recently-edited first.
    """
    user = get_current_user()
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 50
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0

    try:
        notes, total = list_notes_for_project(
            user,
            project_id,
            keyword=request.args.get("keyword"),
            tag=request.args.get("tag"),
            limit=limit,
            offset=offset,
        )
    except BlaNoteError as err:
        return _note_error(err)

    return jsonify(
        {
            "notes": [
                n.to_dict(include_content=False, content_preview=240)
                for n in notes
            ],
            "total": total,
            "limit": min(limit if limit > 0 else 50, 200),
            "offset": max(0, offset),
        }
    )


@projects_bp.post("/<int:project_id>/notes")
@login_required
def create_note(project_id: int):
    """Create a Bla Note in this project."""
    user = get_current_user()
    data = _payload()
    try:
        note = create_note_for_project(
            user,
            project_id,
            title=data.get("title"),
            content=data.get("content"),
            tags=data.get("tags"),
        )
    except BlaNoteError as err:
        return _note_error(err)
    return (
        jsonify({"note": note.to_dict(include_project=True)}),
        201,
    )


def _pack_error(err: ContextPackError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@projects_bp.get("/<int:project_id>/context-packs")
@login_required
def list_context_packs(project_id: int):
    user = get_current_user()
    try:
        packs = list_packs_for_project(user, project_id)
    except ContextPackError as err:
        return _pack_error(err)
    return jsonify(
        {
            "context_packs": [
                p.to_dict(include_body=False, body_preview=240) for p in packs
            ]
        }
    )


@projects_bp.post("/<int:project_id>/context-packs/generate")
@login_required
def generate_context_pack_route(project_id: int):
    user = get_current_user()
    data = _payload()
    try:
        pack = generate_context_pack(
            user,
            project_id,
            title=data.get("title"),
            instructions=data.get("instructions"),
            memory_ids=data.get("memory_ids"),
            model=data.get("model"),
        )
    except ContextPackError as err:
        return _pack_error(err)
    return jsonify({"context_pack": pack.to_dict(include_project=True)}), 201


def _wrap_up_error(err: WrapUpError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@projects_bp.post("/<int:project_id>/wrap-up")
@login_required
def wrap_up_project_route(project_id: int):
    """Wrap the whole project (or a caller-chosen subset of conversations)
    up into a Context Pack.

    Body (all optional):
        title, goal,
        conversationIds: [int, ...],
        options: { includeRawReferences: bool, maxSummaryLength: int }
    """
    user = get_current_user()
    data = _payload()
    try:
        pack, job = wrap_up_project(
            user,
            project_id,
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
