"""Context Pack endpoints (R11).

* ``GET    /api/context-packs``                            — list recent packs across projects.
* ``GET    /api/context-packs/<id>``                       — fetch a single pack with its body.
* ``PATCH  /api/context-packs/<id>``                       — edit title/body inline.
* ``DELETE /api/context-packs/<id>``                       — remove a pack.

Project-scoped routes live on the ``projects_bp`` blueprint and are
registered there (list + generate).

Anything not owned by the caller surfaces as 404.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.context_pack_service import (
    MAX_LIST_LIMIT,
    ContextPackError,
    count_for_user,
    delete_pack,
    get_for_user,
    list_recent_for_user,
    update_pack,
)
from app.utils.auth import get_current_user, login_required

context_packs_bp = Blueprint("context_packs", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(err: ContextPackError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@context_packs_bp.get("")
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

    packs = list_recent_for_user(user, limit=limit)
    return jsonify(
        {
            "context_packs": [
                p.to_dict(include_body=False, include_project=True, body_preview=240)
                for p in packs
            ],
            "total": count_for_user(user),
            "limit": limit,
        }
    )


@context_packs_bp.get("/<int:pack_id>")
@login_required
def show(pack_id: int):
    user = get_current_user()
    try:
        pack = get_for_user(user, pack_id)
    except ContextPackError as err:
        return _error(err)
    return jsonify({"context_pack": pack.to_dict(include_project=True)})


@context_packs_bp.patch("/<int:pack_id>")
@login_required
def update(pack_id: int):
    user = get_current_user()
    data = _payload()
    try:
        pack = update_pack(
            user,
            pack_id,
            title=data.get("title"),
            body=data.get("body"),
            title_provided="title" in data,
            body_provided="body" in data,
        )
    except ContextPackError as err:
        return _error(err)
    return jsonify({"context_pack": pack.to_dict(include_project=True)})


@context_packs_bp.delete("/<int:pack_id>")
@login_required
def destroy(pack_id: int):
    user = get_current_user()
    try:
        delete_pack(user, pack_id)
    except ContextPackError as err:
        return _error(err)
    return jsonify({"status": "ok"})
