"""Context Pack endpoints (R11 + R-PACK-CORE).

Routes:

* ``GET    /api/context-packs``            — list the caller's packs.
  Query params: ``keyword``, ``projectId``, ``sourceType``,
  ``visibility``, ``limit``, ``offset``.
* ``POST   /api/context-packs``            — create a pack from a
  user-supplied payload (manual entry / external import path; the
  wrap-up flow continues to use its dedicated routes).
* ``GET    /api/context-packs/<id>``       — fetch a single pack.
* ``PATCH  /api/context-packs/<id>``       — edit any mutable field.
* ``DELETE /api/context-packs/<id>``       — remove a pack (and its
  ``context_pack_sources`` rows via ORM cascade).
* ``GET    /api/context-packs/<id>/sources`` — list the pack's
  provenance rows.

Project-scoped routes (list + generate) still live on the
``projects_bp`` blueprint and aren't duplicated here.

Anything not owned by the caller surfaces as 404 (never 403) so we
don't leak existence.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.context_pack_service import (
    MAX_LIST_LIMIT,
    ContextPackError,
    count_for_user,
    create_for_user,
    delete_pack,
    get_for_user,
    list_for_user,
    list_sources_for_pack,
    register_usage,
    update_pack,
)
from app.utils.auth import get_current_user, login_required

context_packs_bp = Blueprint("context_packs", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(err: ContextPackError):
    return jsonify({"error": err.code, "message": err.message}), err.status


def _parse_int(value: str | None, field: str) -> int | None:
    """Parse an int query param, None on absent, raise ContextPackError on bad."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ContextPackError(
            "validation_error", f"{field} must be an integer."
        )


@context_packs_bp.get("")
@login_required
def index():
    """List + filter the caller's Context Packs.

    Supported filters (all optional, camelCase):

    * ``keyword``     — substring match on title/description/summary/keywords.
    * ``projectId``   — restrict to a single project.
    * ``sourceType``  — ``project``/``conversation``/``note``/``attachment``/``mixed``.
    * ``visibility``  — ``private`` (default: no filter).
    * ``limit``       — page size (1..100, default 20).
    * ``offset``      — starting offset (default 0).

    Response includes ``{items, total, limit, offset}``. ``total`` is
    the count **after** filtering; for the user's grand total, the
    response also includes ``grand_total`` to help dashboards.
    """
    user = get_current_user()

    try:
        limit = _parse_int(request.args.get("limit"), "limit") or 20
        offset = _parse_int(request.args.get("offset"), "offset") or 0
        project_id = _parse_int(request.args.get("projectId"), "projectId")
    except ContextPackError as err:
        return _error(err)

    keyword = request.args.get("keyword")
    source_type = request.args.get("sourceType")
    visibility = request.args.get("visibility")

    try:
        packs, total = list_for_user(
            user,
            keyword=keyword,
            project_id=project_id,
            source_type=source_type,
            visibility=visibility,
            limit=limit,
            offset=offset,
        )
    except ContextPackError as err:
        return _error(err)

    return jsonify(
        {
            "items": [
                p.to_dict(
                    include_body=False,
                    include_structured_content=False,
                    include_project=True,
                    body_preview=240,
                )
                for p in packs
            ],
            "total": total,
            "grand_total": count_for_user(user),
            "limit": min(limit, MAX_LIST_LIMIT),
            "offset": offset,
            # Keep the legacy key so existing frontend callers that read
            # ``context_packs`` don't break mid-deploy.
            "context_packs": [
                p.to_dict(
                    include_body=False,
                    include_structured_content=False,
                    include_project=True,
                    body_preview=240,
                )
                for p in packs
            ],
        }
    )


@context_packs_bp.post("")
@login_required
def create():
    """Create a Context Pack from a user-supplied payload.

    Request body (all fields optional unless noted):

    ```
    {
      "title":            "My pack",
      "description":      "Short explanation (<= 500 chars)",
      "summary":          "Structured summary (<= 2000 chars)",
      "body":             "Full Markdown body (<= 12000 chars)",
      "keywords":         ["tag-a", "tag-b"],
      "structuredContent": {...},         // JSON object / array
      "sourceType":       "project" | "conversation" | "note" | "attachment" | "mixed",
      "projectId":        123,             // nullable
      "conversationId":   456,             // nullable
      "visibility":       "private",       // MVP accepts private only
      "vectorIndexId":    "opaque",        // nullable
      "parentPackId":     789,             // nullable
      "sources": [                         // optional provenance rows
        {"sourceType":"conversation", "conversationId": 456, "sourceTitle":"…"},
        {"sourceType":"attachment",   "attachmentId": 10,   "sourceTitle":"spec.pdf"}
      ]
    }
    ```
    """
    user = get_current_user()
    data = _payload()
    try:
        pack = create_for_user(
            user,
            title=data.get("title"),
            description=data.get("description"),
            summary=data.get("summary"),
            body=data.get("body"),
            keywords=data.get("keywords"),
            structured_content=data.get("structuredContent")
            or data.get("structured_content"),
            source_type=data.get("sourceType") or data.get("source_type"),
            project_id=data.get("projectId", data.get("project_id")),
            conversation_id=data.get(
                "conversationId", data.get("conversation_id")
            ),
            visibility=data.get("visibility"),
            vector_index_id=data.get("vectorIndexId")
            or data.get("vector_index_id"),
            parent_pack_id=data.get("parentPackId")
            or data.get("parent_pack_id"),
            sources=data.get("sources"),
        )
    except ContextPackError as err:
        return _error(err)
    return (
        jsonify(
            {
                "context_pack": pack.to_dict(
                    include_project=True, include_sources=True
                )
            }
        ),
        201,
    )


@context_packs_bp.get("/<int:pack_id>")
@login_required
def show(pack_id: int):
    user = get_current_user()
    try:
        pack = get_for_user(user, pack_id)
    except ContextPackError as err:
        return _error(err)
    return jsonify(
        {
            "context_pack": pack.to_dict(
                include_project=True, include_sources=True
            )
        }
    )


@context_packs_bp.patch("/<int:pack_id>")
@login_required
def update(pack_id: int):
    """Patch a pack's mutable fields.

    The body is treated as a partial JSON — absent keys are left
    untouched, explicit ``null`` values *clear* nullable fields.
    Passing ``title: ""`` is rejected (title can't be empty).
    """
    user = get_current_user()
    data = _payload()

    if not isinstance(data, dict) or not data:
        return (
            jsonify(
                {"error": "validation_error", "message": "Nothing to update."}
            ),
            400,
        )

    # Allow both camelCase (new) and snake_case (legacy) keys. We
    # translate to the service's canonical snake_case payload.
    ALIASES = {
        "structuredContent": "structured_content",
        "sourceType": "source_type",
        "projectId": "project_id",
        "conversationId": "conversation_id",
        "vectorIndexId": "vector_index_id",
        "parentPackId": "parent_pack_id",
        "graphData": "graph_data",
    }
    patch: dict = {}
    for key, value in data.items():
        if key in ALIASES:
            patch[ALIASES[key]] = value
        else:
            patch[key] = value

    try:
        pack = update_pack(user, pack_id, patch=patch)
    except ContextPackError as err:
        return _error(err)
    return jsonify(
        {
            "context_pack": pack.to_dict(
                include_project=True, include_sources=True
            )
        }
    )


@context_packs_bp.delete("/<int:pack_id>")
@login_required
def destroy(pack_id: int):
    """Delete a pack + its source rows.

    Source rows cascade via the ORM ``cascade="all, delete-orphan"``
    declaration on ``ContextPack.sources`` and the
    ``ON DELETE CASCADE`` on ``context_pack_sources.context_pack_id``.
    """
    user = get_current_user()
    try:
        delete_pack(user, pack_id)
    except ContextPackError as err:
        return _error(err)
    return jsonify({"status": "ok"})


@context_packs_bp.get("/<int:pack_id>/sources")
@login_required
def list_sources(pack_id: int):
    """List a pack's provenance rows."""
    user = get_current_user()
    try:
        rows = list_sources_for_pack(user, pack_id)
    except ContextPackError as err:
        return _error(err)
    return jsonify({"sources": [s.to_dict() for s in rows]})


@context_packs_bp.post("/<int:pack_id>/use")
@login_required
def mark_used(pack_id: int):
    """Record that this pack was just "used" (e.g. attached to a chat).

    Bumps ``usage_count`` + ``last_used_at`` in a single place so the
    Context Zoo can surface recency / popularity without any view
    needing to touch these columns directly.

    Idempotent within a single request but intentionally not within a
    session — each call is a real "use" event.
    """
    user = get_current_user()
    try:
        pack = register_usage(user, pack_id)
    except ContextPackError as err:
        return _error(err)
    return jsonify(
        {
            "context_pack": pack.to_dict(
                include_body=False,
                include_structured_content=False,
                include_project=True,
            )
        }
    )
