"""Material Hypothesis 조회/선택 서비스"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.material_hypothesis import MaterialHypothesis
from app.models.project import Project
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.models.wall import Wall
from app.schemas.material_hypothesis import MaterialHypothesisResponse


def _get_owned_wall(db: Session, wall_id: UUID, user: User) -> Wall:
    stmt = (
        select(Wall)
        .join(SceneVersion, Wall.scene_version_id == SceneVersion.id)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            Wall.id == str(wall_id),
            Project.owner_user_id == user.id,
        )
    )
    w = db.execute(stmt).scalar_one_or_none()
    if w is None:
        raise AppError(
            ErrorCode.WALL_NOT_FOUND,
            "Wall not found.",
            status_code=404,
        )
    return w


def _get_owned_hypothesis(
    db: Session, hypothesis_id: UUID, user: User
) -> MaterialHypothesis:
    stmt = (
        select(MaterialHypothesis)
        .join(SceneVersion, MaterialHypothesis.scene_version_id == SceneVersion.id)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            MaterialHypothesis.id == str(hypothesis_id),
            Project.owner_user_id == user.id,
        )
    )
    h = db.execute(stmt).scalar_one_or_none()
    if h is None:
        raise AppError(
            ErrorCode.MATERIAL_HYPOTHESIS_NOT_FOUND,
            "Material hypothesis not found.",
            status_code=404,
        )
    return h


def list_hypotheses_for_wall(
    db: Session, wall_id: UUID, user: User
) -> list[MaterialHypothesisResponse]:
    wall = _get_owned_wall(db, wall_id, user)
    stmt = (
        select(MaterialHypothesis)
        .where(
            MaterialHypothesis.scene_version_id == wall.scene_version_id,
            MaterialHypothesis.target_type == "wall",
            MaterialHypothesis.target_id == wall.id,
        )
        .order_by(MaterialHypothesis.confidence.desc().nullslast())
    )
    rows = db.execute(stmt).scalars().all()
    return [
        MaterialHypothesisResponse.model_validate(h, from_attributes=True)
        for h in rows
    ]


def select_hypothesis(
    db: Session, hypothesis_id: UUID, user: User
) -> MaterialHypothesisResponse:
    hypothesis = _get_owned_hypothesis(db, hypothesis_id, user)

    db.execute(
        update(MaterialHypothesis)
        .where(
            MaterialHypothesis.scene_version_id == hypothesis.scene_version_id,
            MaterialHypothesis.target_type == hypothesis.target_type,
            MaterialHypothesis.target_id == hypothesis.target_id,
            MaterialHypothesis.id != hypothesis.id,
            MaterialHypothesis.is_selected.is_(True),
        )
        .values(is_selected=False)
    )
    hypothesis.is_selected = True

    try:
        db.commit()
        db.refresh(hypothesis)
    except Exception:
        db.rollback()
        raise
    return MaterialHypothesisResponse.model_validate(
        hypothesis, from_attributes=True
    )
