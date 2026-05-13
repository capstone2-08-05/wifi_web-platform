from __future__ import annotations

from uuid import UUID
from typing import Any

from geoalchemy2 import WKTElement
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from app.schemas.pagination import PaginatedResponse

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
    User,
)
from app.schemas.scene_draft import (
    AnalyzeFromAssetResponse,
    SaveSceneDraftRequestDTO,
    SaveSceneDraftResultDTO,
    SceneDraftDetailResponse,
    SceneDraftSummaryResponse,
    UploadStorageMetadataDTO,
)


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
    db: Session,
    project_id: str | None,
    floor_id: str | None,
    current_user: User,
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
        project = db.get(Project, project_id)
        if project is None:
            raise AppError(
                ErrorCode.INVALID_PROJECT_ID, "Invalid project_id: project not found", 400
            )
        # 본인 소유 권한 체크
        if project.owner_user_id != current_user.id:
            raise AppError(
                ErrorCode.PROJECT_NOT_FOUND,
                "Project not found.",
                404,
            )
        return project_id, floor_id

    # default 프로젝트: 유저별로 분리해서 찾거나 생성
    project = db.scalar(
        select(Project).where(
            Project.name == DEFAULT_DRAFT_PROJECT_NAME,
            Project.owner_user_id == current_user.id,
        )
    )
    if project is None:
        project = Project(
            name=DEFAULT_DRAFT_PROJECT_NAME,
            description="Auto-created project for local upload analysis flow",
            owner_user_id=current_user.id,
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


def save_scene_draft(
    db: Session,
    request_dto: SaveSceneDraftRequestDTO,
    current_user: User,
    source_asset_id: str | None = None,
) -> SaveSceneDraftResultDTO:
    resolved_project_id, resolved_floor_id = _resolve_project_floor(
        db, request_dto.project_id, request_dto.floor_id, current_user,
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
        source_asset_id=source_asset_id,
        source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
        summary_json=summary_json,
        status="draft",
        created_by=request_dto.created_by or current_user.email,
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
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.SCENE_DRAFT_SAVE_FAILED,
            f"Failed to persist scene draft and draft entities: {exc}",
            500,
        ) from exc


async def analyze_from_asset(
    db: Session,
    asset_id: UUID,
    real_width_m: float,
    current_user: User,
) -> AnalyzeFromAssetResponse:
    """이미 등록된 Asset 도면을 분석해서 비동기 Job 등록.

    /upload/floorplan/analyze 와 동일하게 Job 패턴 사용 → 202 응답 + job_id.
    완료 조회는 GET /floorplan-jobs/{job_id}.
    """
    from pathlib import Path

    from app.services.asset_service import _get_owned_asset_or_404
    from app.services.floorplan_job_service import submit_floorplan_analysis

    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, current_user)

    storage_path = Path(asset.storage_url)
    if not storage_path.exists():
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            f"Asset file not found on storage: {asset.storage_url}",
            status_code=500,
        )

    try:
        content = storage_path.read_bytes()
    except OSError as exc:
        raise AppError(
            ErrorCode.FILE_SAVE_FAILED,
            f"Failed to read asset file: {exc}",
            status_code=500,
        ) from exc

    upload_metadata = UploadStorageMetadataDTO(
        provider="local",
        original_filename=storage_path.name,
        content_type=asset.mime_type,
        size_bytes=asset.file_size_bytes,
        local_saved_path=str(storage_path),
    )

    job = await submit_floorplan_analysis(
        db,
        image_bytes=content,
        filename=storage_path.name,
        content_type=asset.mime_type or "application/octet-stream",
        real_width_m=real_width_m,
        project_id=asset.project_id,
        floor_id=asset.floor_id,
        current_user=current_user,
        upload_metadata=upload_metadata,
        created_by=current_user.email,
    )

    return AnalyzeFromAssetResponse(
        job_id=str(job.id),
        asset_id=str(asset.id),
        project_id=str(job.project_id) if job.project_id else None,
        floor_id=str(job.floor_id) if job.floor_id else None,
        job_status=job.status,
        sagemaker_inference_id=(job.input_json or {}).get("sagemaker", {}).get("inference_id"),
        poll_url=f"/floorplan-jobs/{job.id}",
    )


def get_scene_draft(
    db: Session, scene_draft_id: str, current_user: User
) -> SceneDraftDetailResponse:
    scene_draft = (
        db.query(SceneDraft)
        .join(Project, SceneDraft.project_id == Project.id)
        .filter(
            SceneDraft.id == scene_draft_id,
            Project.owner_user_id == current_user.id,
        )
        .options(
            selectinload(SceneDraft.draft_rooms),
            selectinload(SceneDraft.draft_walls),
            selectinload(SceneDraft.draft_openings),
            selectinload(SceneDraft.draft_objects),
        )
        .first()
    )

    if scene_draft is None:
        raise AppError(
            ErrorCode.SCENE_DRAFT_NOT_FOUND,
            "Scene draft not found.",
            status_code=404,
        )

    return SceneDraftDetailResponse(
        id=scene_draft.id,
        project_id=scene_draft.project_id,
        floor_id=scene_draft.floor_id,
        source_mode=scene_draft.source_mode,
        source_asset_id=scene_draft.source_asset_id,
        source_method=scene_draft.source_method,
        summary_json=scene_draft.summary_json,
        status=scene_draft.status,
        rooms=scene_draft.draft_rooms,
        walls=scene_draft.draft_walls,
        openings=scene_draft.draft_openings,
        objects=scene_draft.draft_objects,
        created_at=scene_draft.created_at,
        updated_at=scene_draft.updated_at,
    )

def delete_scene_draft(
    db: Session, scene_draft_id: str, current_user: User
) -> None:
    scene_draft = (
        db.query(SceneDraft)
        .join(Project, SceneDraft.project_id == Project.id)
        .filter(
            SceneDraft.id == scene_draft_id,
            Project.owner_user_id == current_user.id,
        )
        .first()
    )

    if scene_draft is None:
        raise AppError(
            ErrorCode.SCENE_DRAFT_NOT_FOUND,
            "Scene draft not found.",
            status_code=404,
        )

    try:
        db.delete(scene_draft)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.SCENE_DRAFT_SAVE_FAILED,
            f"Failed to delete scene draft: {exc}",
            500,
        ) from exc


def list_scene_drafts(
    db: Session,
    current_user: User,
    page: int,
    page_size: int,
    project_id: str | None = None,
    floor_id: str | None = None,
    status: str | None = None,
) -> PaginatedResponse[SceneDraftSummaryResponse]:
    
    base_query = (
        db.query(SceneDraft)
        .join(Project, SceneDraft.project_id == Project.id)
        .filter(Project.owner_user_id == current_user.id)
    )

    if project_id is not None:
        base_query = base_query.filter(SceneDraft.project_id == project_id)
    if floor_id is not None:
        base_query = base_query.filter(SceneDraft.floor_id == floor_id)
    if status is not None:
        base_query = base_query.filter(SceneDraft.status == status)

    total = base_query.with_entities(func.count(SceneDraft.id)).scalar() or 0

    items = (
        base_query.order_by(SceneDraft.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedResponse[SceneDraftSummaryResponse](
        items=[SceneDraftSummaryResponse.model_validate(d) for d in items],
        page=page,
        page_size=page_size,
        total=total,
    )