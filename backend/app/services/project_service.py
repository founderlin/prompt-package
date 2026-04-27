"""Project domain helpers — kept pure so routes stay thin.

All public functions take a ``user`` so we never accidentally leak
projects across accounts. Anything not owned by ``user`` is treated as
"not found" (we never return 403 — fewer enumeration vectors).
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select

from app.extensions import db
from app.models import Project, User
from app.models.context_pack import ContextPack
from app.models.conversation import Conversation
from app.models.memory import Memory

NAME_MIN = 1
NAME_MAX = 120
DESCRIPTION_MAX = 2000


class ProjectError(Exception):
    """Predictable, user-facing project failures."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _normalize_name(raw: str | None) -> str:
    if raw is None:
        raise ProjectError("validation_error", "Project name is required.")
    cleaned = raw.strip()
    if len(cleaned) < NAME_MIN:
        raise ProjectError("validation_error", "Project name is required.")
    if len(cleaned) > NAME_MAX:
        raise ProjectError(
            "validation_error",
            f"Project name must be at most {NAME_MAX} characters.",
        )
    return cleaned


def _normalize_description(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if len(cleaned) > DESCRIPTION_MAX:
        raise ProjectError(
            "validation_error",
            f"Description must be at most {DESCRIPTION_MAX} characters.",
        )
    return cleaned


def list_for_user(user: User) -> Iterable[Project]:
    stmt = (
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.updated_at.desc(), Project.id.desc())
    )
    return db.session.scalars(stmt).all()


def count_for_user(user: User) -> int:
    return db.session.query(Project).filter(Project.user_id == user.id).count()


def get_for_user(user: User, project_id: int) -> Project:
    project = db.session.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise ProjectError("not_found", "Project not found.", status=404)
    return project


def create_for_user(user: User, *, name: str | None, description: str | None) -> Project:
    cleaned_name = _normalize_name(name)
    cleaned_description = _normalize_description(description)

    project = Project(
        user_id=user.id,
        name=cleaned_name,
        description=cleaned_description,
    )
    db.session.add(project)
    db.session.commit()
    return project


def update_for_user(
    user: User,
    project_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    name_provided: bool = True,
    description_provided: bool = True,
) -> Project:
    project = get_for_user(user, project_id)

    if name_provided:
        project.name = _normalize_name(name)
    if description_provided:
        project.description = _normalize_description(description)

    db.session.add(project)
    db.session.commit()
    return project


def delete_for_user(user: User, project_id: int) -> None:
    project = get_for_user(user, project_id)

    # Explicitly clean up child records before deleting the project itself.
    # SQLite doesn't enforce ON DELETE CASCADE by default (requires
    # `PRAGMA foreign_keys=ON`), and SQLAlchemy's ORM-side default cascade
    # for these backrefs would try to NULL out foreign key columns that
    # are declared NOT NULL (e.g. context_packs.project_id), raising an
    # IntegrityError. Deleting children first keeps the unit of work
    # simple, DB-agnostic, and correct.
    #
    # Order matters: memories reference conversations, and conversations
    # reference context_packs via a nullable context_pack_id (SET NULL on
    # delete). Delete memories first, then context_packs, then
    # conversations (Message rows are cleaned up via the Conversation
    # ORM cascade="all, delete-orphan"), then the project itself.
    Memory.query.filter_by(project_id=project.id).delete(synchronize_session=False)
    ContextPack.query.filter_by(project_id=project.id).delete(
        synchronize_session=False
    )
    for convo in Conversation.query.filter_by(project_id=project.id).all():
        db.session.delete(convo)

    db.session.delete(project)
    db.session.commit()


__all__ = [
    "ProjectError",
    "count_for_user",
    "create_for_user",
    "delete_for_user",
    "get_for_user",
    "list_for_user",
    "update_for_user",
]
