"""Bla Note endpoints.

Flat single-resource routes only; the project-scoped *list* and
*create* endpoints live on the ``projects_bp`` blueprint (see
``routes/projects.py``), mirroring how Memories are split between
``/api/projects/<pid>/memories`` (on projects_bp) and
``/api/memories/<id>`` (on memories_bp).

Anything not owned by the caller surfaces as 404 so we don't leak
existence — consistent with the rest of the API.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.bla_note_service import (
    BlaNoteError,
    delete_for_user,
    get_for_user,
    update_for_user,
)
from app.utils.auth import get_current_user, login_required

bla_notes_bp = Blueprint("bla_notes", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(err: BlaNoteError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@bla_notes_bp.get("/<int:note_id>")
@login_required
def show(note_id: int):
    user = get_current_user()
    try:
        note = get_for_user(user, note_id)
    except BlaNoteError as err:
        return _error(err)
    return jsonify(
        {
            "note": note.to_dict(
                include_attachments=True, include_project=True
            )
        }
    )


@bla_notes_bp.patch("/<int:note_id>")
@login_required
def update(note_id: int):
    """Patch a note's mutable fields.

    Absent keys are untouched. Explicit ``null`` on ``content`` / ``tags``
    resets the field. ``title`` can't be empty (service rejects).
    """
    user = get_current_user()
    data = _payload()
    if not isinstance(data, dict) or not data:
        return (
            jsonify({"error": "validation_error", "message": "Nothing to update."}),
            400,
        )
    try:
        note = update_for_user(user, note_id, patch=data)
    except BlaNoteError as err:
        return _error(err)
    return jsonify(
        {
            "note": note.to_dict(
                include_attachments=True, include_project=True
            )
        }
    )


@bla_notes_bp.delete("/<int:note_id>")
@login_required
def destroy(note_id: int):
    user = get_current_user()
    try:
        delete_for_user(user, note_id)
    except BlaNoteError as err:
        return _error(err)
    return jsonify({"status": "ok"})
