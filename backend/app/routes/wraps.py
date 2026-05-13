"""Wrap (project memory) HTTP routes — Phase 3 + 4 + 5.

Endpoints:

* ``POST /api/projects/<pid>/conversations/<cid>/wraps/quick-draft``
  Generate a Quick Wrap *draft* for a conversation.

* ``POST /api/projects/<pid>/conversations/<cid>/wraps/advanced-draft``
  Like quick-draft but accepts custom model + filters + instruction.

* ``POST /api/projects/<pid>/conversations/<cid>/wraps/routine-draft``
  Routine Wrap draft. Uses the project's stored routine config to
  pick model + scope. Same response shape as the other drafts so the
  frontend's Review dialog can render any of them.

* ``POST /api/projects/<pid>/wraps``
  Persist a (possibly user-edited) wrap to disk under
  ``project-memory/wraps/<project_id>/<filename>.md``.

* ``GET  /api/projects/<pid>/wraps/routine-config``
  Read the project's routine wrap configuration (or the defaults).

* ``PUT  /api/projects/<pid>/wraps/routine-config``
  Upsert routine wrap configuration.

* ``GET  /api/projects/<pid>/wraps/routine-status``
  Combined "is the routine due + is there new activity" probe used by
  the frontend banner.

* ``POST /api/projects/<pid>/wraps/routine-dismiss``
  User dismissed the routine banner. Records ``dismissed_at`` (mutes
  the banner for 24h) but leaves ``last_run_at`` intact so the next
  cadence still fires on schedule.

* ``POST /api/projects/<pid>/wraps/routine-mark-run``
  Stamp ``last_run_at`` after a successful Routine save. Called by
  the frontend right after :func:`save` returns 201.

All routes are scoped to the calling user via ``login_required``
and ownership checks in the service layer.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.models import Conversation, Project
from app.services.chat_service import ChatError, get_conversation_for_user
from app.services.project_service import ProjectError, get_for_user as get_project
from app.services.wrap_memory import (
    WrapFilters,
    WrapModel,
    WrapServiceError,
    build_routine_request,
    compute_routine_status,
    get_all_project_memory_stats,
    get_project_memory_stats,
    load_routine_config,
    mark_routine_dismissed,
    mark_routine_run,
    quick_wrap_draft,
    save_routine_config,
    save_wrap_draft,
    wrap_draft,
    wrap_draft_from_request,
)
from app.services.wrap_memory.types import WrapMode
from app.utils.auth import get_current_user, login_required

wraps_bp = Blueprint("wraps", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(err: WrapServiceError):
    return jsonify({"error": err.code, "message": err.message}), err.status


def _resolve_project_or_404(user, project_id: int):
    try:
        return get_project(user, project_id)
    except ProjectError as err:
        raise WrapServiceError(
            err.code, err.message, status=err.status
        ) from err


def _resolve_conversation_or_404(user, conversation_id: int) -> Conversation:
    try:
        return get_conversation_for_user(user, conversation_id)
    except ChatError as err:
        raise WrapServiceError(
            err.code, err.message, status=err.status
        ) from err


# ---------------------------------------------------------------------------
# Quick draft (conversation-scoped).


@wraps_bp.post(
    "/projects/<int:project_id>/conversations/<int:conversation_id>"
    "/wraps/quick-draft"
)
@login_required
def quick_draft(project_id: int, conversation_id: int):
    user = get_current_user()
    data = _payload() if request.is_json else {}
    # Quick Wrap accepts an optional ``model`` so the frontend's
    # "default wrap model" preference (Settings → Wrap model) can
    # flow through without forcing the user into the Advanced dialog.
    # Anything else in the body is ignored — Quick Wrap is "no knobs".
    raw_model = data.get("model") if isinstance(data, dict) else None
    chosen_model = None
    if raw_model is not None:
        try:
            chosen_model = WrapModel(raw_model)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in WrapModel)
            return _error(
                WrapServiceError(
                    "validation_error",
                    f"Unknown model {raw_model!r}; expected one of {allowed}.",
                    status=400,
                )
            )
    try:
        project = _resolve_project_or_404(user, project_id)
        convo = _resolve_conversation_or_404(user, conversation_id)
        bundle = quick_wrap_draft(
            user=user,
            project=project,
            conversation=convo,
            model=chosen_model,
        )
    except WrapServiceError as err:
        return _error(err)
    return jsonify({"draft": bundle.to_dict()})


# ---------------------------------------------------------------------------
# Advanced draft (conversation-scoped, with model + filters).


def _parse_advanced_body(data: dict) -> tuple[WrapModel, WrapFilters, str | None]:
    """Validate the Advanced Wrap request body.

    Raises :class:`WrapServiceError` with a 400 status when the
    payload is malformed — the route layer maps that to a clean
    JSON error response.
    """
    raw_model = data.get("model")
    if raw_model is None:
        # Allow omitted model: Advanced Wrap UI always sends one, but
        # being defensive here means the curl-fan smoke test still works.
        from app.services.wrap_memory.settings import DEFAULT_MODEL

        model = DEFAULT_MODEL
    else:
        try:
            model = WrapModel(raw_model)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in WrapModel)
            raise WrapServiceError(
                "validation_error",
                f"Unknown model {raw_model!r}; expected one of {allowed}.",
                status=400,
            ) from exc

    raw_filters = data.get("filters")
    if raw_filters is not None and not isinstance(raw_filters, dict):
        raise WrapServiceError(
            "validation_error",
            "filters must be a JSON object when provided.",
            status=400,
        )
    try:
        filters = WrapFilters.from_dict(raw_filters)
    except ValueError as exc:
        raise WrapServiceError(
            "validation_error", str(exc), status=400
        ) from exc

    raw_instruction = data.get("userInstruction")
    if raw_instruction is not None and not isinstance(raw_instruction, str):
        raise WrapServiceError(
            "validation_error",
            "userInstruction must be a string when provided.",
            status=400,
        )
    user_instruction = (raw_instruction or "").strip() or None

    return model, filters, user_instruction


@wraps_bp.post(
    "/projects/<int:project_id>/conversations/<int:conversation_id>"
    "/wraps/advanced-draft"
)
@login_required
def advanced_draft(project_id: int, conversation_id: int):
    user = get_current_user()
    data = _payload()
    if not isinstance(data, dict):
        return (
            jsonify(
                {"error": "validation_error", "message": "Request body must be JSON."}
            ),
            400,
        )

    try:
        model, filters, user_instruction = _parse_advanced_body(data)
        project = _resolve_project_or_404(user, project_id)
        convo = _resolve_conversation_or_404(user, conversation_id)
        bundle = wrap_draft(
            user=user,
            project=project,
            conversation=convo,
            mode=WrapMode.ADVANCED,
            model=model,
            filters=filters,
            user_instruction=user_instruction,
        )
    except WrapServiceError as err:
        return _error(err)
    return jsonify({"draft": bundle.to_dict()})


# ---------------------------------------------------------------------------
# Save.


@wraps_bp.post("/projects/<int:project_id>/wraps")
@login_required
def save(project_id: int):
    user = get_current_user()
    data = _payload()
    if not isinstance(data, dict):
        return (
            jsonify(
                {"error": "validation_error", "message": "Request body must be JSON."}
            ),
            400,
        )

    markdown = data.get("markdown")
    filename = data.get("filename")

    base_dir = current_app.config.get("WRAP_MEMORY_DIR")

    try:
        project = _resolve_project_or_404(user, project_id)
        saved = save_wrap_draft(
            user=user,
            project=project,
            markdown=markdown if isinstance(markdown, str) else "",
            filename=filename if isinstance(filename, str) else None,
            base_dir=base_dir,
        )
    except WrapServiceError as err:
        return _error(err)
    return jsonify({"wrap": saved.to_dict()}), 201


# ---------------------------------------------------------------------------
# Routine Wrap — Phase 5.


@wraps_bp.get("/projects/<int:project_id>/wraps/routine-config")
@login_required
def routine_config_get(project_id: int):
    user = get_current_user()
    try:
        project = _resolve_project_or_404(user, project_id)
        config = load_routine_config(user, project)
    except WrapServiceError as err:
        return _error(err)
    return jsonify({"config": config.to_dict()})


@wraps_bp.put("/projects/<int:project_id>/wraps/routine-config")
@login_required
def routine_config_put(project_id: int):
    user = get_current_user()
    data = _payload()
    if not isinstance(data, dict):
        return (
            jsonify(
                {"error": "validation_error", "message": "Request body must be JSON."}
            ),
            400,
        )
    try:
        project = _resolve_project_or_404(user, project_id)
        config = save_routine_config(user, project, data)
    except WrapServiceError as err:
        return _error(err)
    return jsonify({"config": config.to_dict()})


@wraps_bp.get("/projects/<int:project_id>/wraps/routine-status")
@login_required
def routine_status(project_id: int):
    user = get_current_user()
    try:
        project = _resolve_project_or_404(user, project_id)
        status = compute_routine_status(user, project)
    except WrapServiceError as err:
        return _error(err)
    return jsonify(status)


@wraps_bp.post("/projects/<int:project_id>/wraps/routine-dismiss")
@login_required
def routine_dismiss(project_id: int):
    user = get_current_user()
    try:
        project = _resolve_project_or_404(user, project_id)
        config = mark_routine_dismissed(user, project)
    except WrapServiceError as err:
        return _error(err)
    return jsonify({"config": config.to_dict()})


@wraps_bp.post("/projects/<int:project_id>/wraps/routine-mark-run")
@login_required
def routine_mark_run(project_id: int):
    user = get_current_user()
    try:
        project = _resolve_project_or_404(user, project_id)
        config = mark_routine_run(user, project)
    except WrapServiceError as err:
        return _error(err)
    return jsonify({"config": config.to_dict()})


# ---------------------------------------------------------------------------
# Memory stats — Phase 6.


@wraps_bp.get("/projects/<int:project_id>/wraps/stats")
@login_required
def memory_stats(project_id: int):
    """Per-project wrap memory stats for the dashboard.

    Returns ``{ stats: { projectId, projectName, wrapCount,
    memorySizeBytes, lastWrappedAt } }`` with all-zero / null fields
    when the project has no wraps yet.
    """
    user = get_current_user()
    base_dir = current_app.config.get("WRAP_MEMORY_DIR")
    try:
        project = _resolve_project_or_404(user, project_id)
        stats = get_project_memory_stats(
            user=user, project=project, base_dir=base_dir
        )
    except WrapServiceError as err:
        return _error(err)
    return jsonify({"stats": stats.to_dict()})


@wraps_bp.get("/wraps/stats")
@login_required
def memory_stats_all():
    """Batch endpoint: stats for *every* project this user owns.

    Lets the dashboard render the "Wrap memory per project" list
    with one round-trip instead of N. Order matches
    ``Project.query.order_by(updated_at.desc())`` so the dashboard
    can show "freshly touched first" without re-sorting.
    """
    user = get_current_user()
    base_dir = current_app.config.get("WRAP_MEMORY_DIR")
    projects = (
        Project.query.filter_by(user_id=user.id)
        .order_by(Project.updated_at.desc())
        .all()
    )
    stats = get_all_project_memory_stats(
        user=user, projects=projects, base_dir=base_dir
    )
    return jsonify({"stats": [s.to_dict() for s in stats]})


# ---------------------------------------------------------------------------
# Routine draft (kept below so all routine endpoints stay clustered).


@wraps_bp.post(
    "/projects/<int:project_id>/conversations/<int:conversation_id>"
    "/wraps/routine-draft"
)
@login_required
def routine_draft(project_id: int, conversation_id: int):
    """Build a Routine Wrap preview using the project's stored config.

    Same response shape as quick/advanced draft so the frontend can
    reuse its review dialog. ``review_required=True`` is enforced
    server-side: this endpoint **never** persists the wrap, the
    client has to follow up with :func:`save` + :func:`routine_mark_run`.
    """
    user = get_current_user()
    try:
        project = _resolve_project_or_404(user, project_id)
        convo = _resolve_conversation_or_404(user, conversation_id)
        config = load_routine_config(user, project)
        request_obj = build_routine_request(
            user=user, project=project, conversation=convo, config=config
        )
        bundle = wrap_draft_from_request(
            request_obj, user=user, project=project
        )
    except WrapServiceError as err:
        return _error(err)
    body = bundle.to_dict()
    body_with_meta = {"draft": body, "routineConfig": config.to_dict()}
    return jsonify(body_with_meta)
