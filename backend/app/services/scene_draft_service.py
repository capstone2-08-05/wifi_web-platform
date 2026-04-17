from __future__ import annotations

from uuid import UUID
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.settings import (
    DEFAULT_DRAFT_ANALYSIS_METHOD,
    DEFAULT_DRAFT_FLOOR_NAME,
    DEFAULT_DRAFT_PROJECT_NAME,
    DEFAULT_DRAFT_SOURCE,
    DEFAULT_DRAFT_SOURCE_MODE,
)
from app.models import (
    DraftObject,
    DraftOpening,
    DraftRoom,
    DraftWall,
    Floor,
    Project,
    SceneDraft,
)
from app.schemas.scene_draft import SaveSceneDraftRequestDTO, SaveSceneDraftResultDTO


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _positive(value: float | None, fallback: float) -> float:
    if value is None or value <= 0:
        return fallback
    return value


def _resolve_project_floor(
    db: Session, project_id: str | None, floor_id: str | None
) -> tuple[str, str]:
    if bool(project_id) ^ bool(floor_id):
        raise AppError(
            ErrorCode.INVALID_PROJECT_FLOOR_INPUT,
            "project_id and floor_id must be provided together.",
            400,
        )

    if project_id and floor_id:
        try:
            UUID(project_id)
            UUID(floor_id)
        except ValueError as exc:
            raise AppError(
                ErrorCode.INVALID_UUID_FORMAT,
                "project_id and floor_id must be valid UUID strings.",
                400,
            ) from exc

        floor = db.get(Floor, floor_id)
        if floor is None:
            raise AppError(
                ErrorCode.INVALID_FLOOR_ID, "Invalid floor_id: floor not found", 400
            )
        if floor.project_id != project_id:
            raise AppError(
                ErrorCode.INVALID_PROJECT_FLOOR_PAIR,
                "Invalid project_id/floor_id pair",
                400,
            )
        if db.get(Project, project_id) is None:
            raise AppError(
                ErrorCode.INVALID_PROJECT_ID, "Invalid project_id: project not found", 400
            )
        return project_id, floor_id

    project = db.scalar(
        select(Project).where(Project.name == DEFAULT_DRAFT_PROJECT_NAME)
    )
    if project is None:
        project = Project(
            name=DEFAULT_DRAFT_PROJECT_NAME,
            description="Auto-created project for local upload analysis flow",
        )
        db.add(project)
        db.flush()

    floor = db.scalar(
        select(Floor).where(
            Floor.project_id == project.id,
            Floor.name == DEFAULT_DRAFT_FLOOR_NAME,
        )
    )
    if floor is None:
        floor = Floor(
            project_id=project.id,
            name=DEFAULT_DRAFT_FLOOR_NAME,
            floor_index=0,
        )
        db.add(floor)
        db.flush()

    return project.id, floor.id


def save_scene_draft(db: Session, request_dto: SaveSceneDraftRequestDTO) -> SaveSceneDraftResultDTO:
    resolved_project_id, resolved_floor_id = _resolve_project_floor(
        db, request_dto.project_id, request_dto.floor_id
    )

    summary_json = {
        "source": DEFAULT_DRAFT_SOURCE,
        "analysis_method": DEFAULT_DRAFT_ANALYSIS_METHOD,
        "raw_result_version": request_dto.scene.scene_version,
        "storage": request_dto.upload.model_dump(),
    }

    scene_draft = SceneDraft(
        project_id=resolved_project_id,
        floor_id=resolved_floor_id,
        source_mode=DEFAULT_DRAFT_SOURCE_MODE,
        source_asset_id=None,
        source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
        summary_json=summary_json,
        status="draft",
        created_by=request_dto.created_by,
    )

    try:
        db.add(scene_draft)
        db.flush()

        for room in request_dto.scene.rooms:
            db.add(
                DraftRoom(
                    scene_draft_id=scene_draft.id,
                    room_name=str(room.get("id")) if room.get("id") is not None else None,
                    room_type=room.get("type"),
                    source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
                    metadata_json={"raw": room},
                )
            )

        wall_id_map: dict[str, str] = {}
        for wall in request_dto.scene.walls:
            draft_wall = DraftWall(
                scene_draft_id=scene_draft.id,
                wall_role=wall.get("role", "inner"),
                thickness_m=_positive(_to_float(wall.get("thickness"), 0.18), 0.18),
                height_m=_to_float(wall.get("height")),
                material_label=wall.get("material"),
                source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
                metadata_json={"raw": wall},
            )
            db.add(draft_wall)
            db.flush()

            if wall.get("id") is not None:
                wall_id_map[str(wall["id"])] = draft_wall.id

        for opening in request_dto.scene.openings:
            width = _to_float(opening.get("width_m"))
            if width is None:
                width = abs(_to_float(opening.get("x2"), 0.0) - _to_float(opening.get("x1"), 0.0))

            height = _to_float(opening.get("height_m"))
            if height is None:
                height = abs(_to_float(opening.get("y2"), 0.0) - _to_float(opening.get("y1"), 0.0))

            wall_ref = opening.get("wall_ref")
            db.add(
                DraftOpening(
                    scene_draft_id=scene_draft.id,
                    wall_id=wall_id_map.get(str(wall_ref)) if wall_ref is not None else None,
                    opening_type=opening.get("type", "opening"),
                    width_m=_positive(width, 0.8),
                    height_m=_positive(height, 1.2),
                    source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
                    metadata_json={"raw": opening},
                )
            )

        for obj in request_dto.scene.objects:
            obj_type = obj.get("class_name") or obj.get("type") or "unknown"
            db.add(
                DraftObject(
                    scene_draft_id=scene_draft.id,
                    object_type=obj_type,
                    confidence=_to_float(obj.get("score") or obj.get("confidence")),
                    source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
                    metadata_json={"raw": obj},
                )
            )

        db.commit()
        return SaveSceneDraftResultDTO(scene_draft_id=scene_draft.id)
    except Exception:
        db.rollback()
        raise AppError(
            ErrorCode.SCENE_DRAFT_SAVE_FAILED,
            "Failed to persist scene draft and draft entities",
            500,
        )
