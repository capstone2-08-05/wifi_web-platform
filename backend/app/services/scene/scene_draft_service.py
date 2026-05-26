from __future__ import annotations

from uuid import UUID
from typing import Any

from geoalchemy2 import WKTElement
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from app.schemas.pagination import PaginatedResponse

from app.core.errors import AppError, ErrorCode
from app.core.geom import scale_wkb, wkb_to_geojson
from app.core.settings import (
    DEFAULT_DRAFT_ANALYSIS_METHOD,
    DEFAULT_DRAFT_FLOOR_NAME,
    DEFAULT_DRAFT_PROJECT_NAME,
    DEFAULT_DRAFT_SOURCE,
    DEFAULT_DRAFT_SOURCE_MODE,
)
from app.geometry import (
    line_geom_length_m,
    object_point_geom,
    opening_line_geom,
    opening_type_dims,
    room_centroid_geom,
    room_polygon_geom,
    wall_centerline_geom,
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
from app.schemas.scene.scene_draft import (
    AnalyzeFromAssetResponse,
    DraftObjectResponse,
    DraftOpeningResponse,
    DraftRoomResponse,
    DraftWallResponse,
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


def _build_wall_dimension_match_map(
    walls: list[dict],
    postprocess_metadata: dict | None,
) -> dict[int, dict]:
    """SceneSchema.walls (픽셀 좌표) 와 postprocess dimension_matches 를 다시 매칭.

    fusion 후처리(bridge/snap)로 wall idx 가 바뀌었을 수 있어, postprocess 단계의
    `matched_wall_idx` 를 그대로 못 씀. 대신 OCR entries 와 wall 픽셀 좌표를 받아
    동일 `match_dimensions_to_walls` 알고리즘으로 재매칭.

    반환: `{wall_index_in_scene: dimension_match_dict}`. 매칭 안 된 wall 은 키 없음.
    """
    if not postprocess_metadata or not walls:
        return {}

    raw_matches = postprocess_metadata.get("dimension_matches") or []
    if not raw_matches:
        return {}

    # dimension_matches 자체에 OCR 결과 (bbox + parsed meters) 가 있으므로 OCR 호출
    # 다시 안 해도 됨. dimension_matching 의 매칭 알고리즘만 재사용.
    try:
        from app.services.floorplan.wall_extraction_helpers import dimension_matching
        from app.services.floorplan.wall_extraction_helpers.ocr import OCREntry
    except Exception:
        return {}

    # 픽셀 좌표 추출. SceneSchema.Wall 은 model_dump 됐으므로 x1/y1/x2/y2 직접 접근.
    wall_pixel_coords: list[list[float]] = []
    for w in walls:
        try:
            wall_pixel_coords.append([
                float(w["x1"]), float(w["y1"]),
                float(w["x2"]), float(w["y2"]),
            ])
        except (KeyError, TypeError, ValueError):
            wall_pixel_coords.append([0.0, 0.0, 0.0, 0.0])

    # 각 dimension_match → OCREntry 로 복원 (text/bbox 가 필요한 최소 필드).
    entries = []
    for m in raw_matches:
        try:
            bbox = tuple(int(v) for v in m.get("bbox", []))
            if len(bbox) != 4:
                continue
            entries.append(
                OCREntry(
                    bbox=bbox,  # type: ignore[arg-type]
                    text=str(m.get("text", "")),
                    confidence=float(m.get("ocr_confidence", 0.0)),
                )
            )
        except Exception:
            continue

    if not entries:
        return {}

    rematched = dimension_matching.match_dimensions_to_walls(entries, wall_pixel_coords)
    result: dict[int, dict] = {}
    for m in rematched:
        if m.matched_wall_idx is None:
            continue
        # 같은 wall 에 여러 매칭이 잡히면 가장 높은 ocr_confidence 만 유지.
        existing = result.get(m.matched_wall_idx)
        if existing and existing.get("ocr_confidence", 0) >= m.ocr_confidence:
            continue
        result[m.matched_wall_idx] = m.to_dict()
    return result


def _build_span_maps(
    walls: list[dict],
    rooms: list[dict],
    postprocess_metadata: dict | None,
    scale_ratio: float,
) -> tuple[dict[int, dict], dict[int, dict]]:
    """치수선 세그먼트를 구간(span) 으로 해석해 (벽 길이 맵, 방 가로/세로 맵) 반환.

    벽: 평행 치수(세로벽↔세로치수, 가로벽↔가로치수) 를 IoU 로 매칭한 '도면 길이'.
    방: 가로/세로 범위에 맞는 치수.
    치수 텍스트가 벽에서 멀어 직접 매칭(`match_dimensions_to_walls`) 이 실패해도,
    scale 로 세그먼트 픽셀 길이를 복원하므로 동작한다 (OCR/fallback scale 무관).
    """
    empty: tuple[dict, dict] = ({}, {})
    if not postprocess_metadata or not walls:
        return empty
    raw_matches = postprocess_metadata.get("dimension_matches") or []
    if not raw_matches:
        return empty

    # scale: OCR 추정값 우선, 없으면 geom 변환에 쓴 scale_ratio.
    scale_est = postprocess_metadata.get("scale_estimate") or {}
    scale = scale_est.get("scale_m_per_px") or scale_ratio
    if not scale or scale <= 0:
        return empty

    try:
        from app.services.floorplan.wall_extraction_helpers import dimension_matching
        from app.services.floorplan.wall_extraction_helpers.ocr import OCREntry
    except Exception:
        return empty

    wall_px: list[list[float]] = []
    for w in walls:
        try:
            wall_px.append([float(w["x1"]), float(w["y1"]), float(w["x2"]), float(w["y2"])])
        except (KeyError, TypeError, ValueError):
            wall_px.append([0.0, 0.0, 0.0, 0.0])

    entries = []
    for m in raw_matches:
        try:
            bbox = tuple(int(v) for v in m.get("bbox", []))
            if len(bbox) != 4:
                continue
            entries.append(
                OCREntry(
                    bbox=bbox,  # type: ignore[arg-type]
                    text=str(m.get("text", "")),
                    confidence=float(m.get("ocr_confidence", 0.0)),
                )
            )
        except Exception:
            continue
    if not entries:
        return empty

    spans = dimension_matching.build_dimension_spans(entries, float(scale), wall_px)
    if not spans:
        return empty
    # 벽: 평행 치수(자기 길이) 매칭 + scale 로 실제 길이 검증. 방: 가로/세로 치수.
    wall_len_map = dimension_matching.attach_wall_lengths_parallel(
        spans, wall_px, float(scale)
    )
    room_span_map = dimension_matching.attach_spans_to_rooms(spans, rooms or [])
    return wall_len_map, room_span_map


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

    scale_ratio = float(request_dto.scene.scale_ratio or 1.0)

    summary_json: dict[str, Any] = {
        "source": DEFAULT_DRAFT_SOURCE,
        "analysis_method": DEFAULT_DRAFT_ANALYSIS_METHOD,
        "raw_result_version": request_dto.scene.scene_version,
        "storage": request_dto.upload.model_dump(),
        # geom 변환에 쓴 최종 scale (m/px). OCR 추정/기본 fallback 무관하게 항상 기록.
        # 프론트가 배경 도면 이미지를 미터 좌표에 정렬할 때 사용 (imageDims_px × scale).
        "scale_ratio_m_per_px": scale_ratio,
    }
    if request_dto.scene.inference_metadata:
        summary_json["inference_metadata"] = request_dto.scene.inference_metadata
    if request_dto.scene.postprocess_metadata:
        summary_json["wall_postprocess"] = request_dto.scene.postprocess_metadata

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

        # 치수선 세그먼트를 구간(span) 으로 해석 → 벽 평행 길이 + 방 가로/세로 치수.
        # (치수선이 벽에서 멀어 직접 매칭이 안 되는 도면도 scale 로 복원해 부착)
        wall_len_map, room_span_map = _build_span_maps(
            request_dto.scene.walls,
            request_dto.scene.rooms,
            request_dto.scene.postprocess_metadata,
            scale_ratio,
        )

        for room_idx, room in enumerate(request_dto.scene.rooms):
            room_meta: dict[str, Any] = {"raw": room}
            room_span = room_span_map.get(room_idx)
            if room_span:
                room_meta["dimension_spans"] = room_span
            db.add(
                DraftRoom(
                    # 표시용 이름은 의미있는 name(예: "화장실")만. 없으면 None
                    # (room_0 같은 내부 id 를 라벨로 노출하지 않음).
                    scene_draft_id=scene_draft.id,
                    room_name=(str(room["name"]) if room.get("name") else None),
                    room_type=room.get("type"),
                    source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
                    polygon_geom=room_polygon_geom(room, scale_ratio),
                    centroid_geom=room_centroid_geom(room, scale_ratio),
                    metadata_json=room_meta,
                )
            )

        # wall 픽셀 좌표 기준으로 OCR 치수 매칭 재실행 (fusion 후처리로 wall idx 바뀌었을
        # 가능성 대비). dimension_match 결과는 각 DraftWall.metadata_json 에 첨부.
        wall_dim_matches = _build_wall_dimension_match_map(
            request_dto.scene.walls,
            request_dto.scene.postprocess_metadata,
        )

        wall_id_map: dict[str, str] = {}
        for idx, wall in enumerate(request_dto.scene.walls):
            wall_meta: dict[str, Any] = {"raw": wall}
            dim_match = wall_dim_matches.get(idx)
            if dim_match is not None:
                wall_meta["dimension_match"] = dim_match
            wall_len = wall_len_map.get(idx)
            if wall_len:
                wall_meta["dimension_length"] = wall_len

            draft_wall = DraftWall(
                scene_draft_id=scene_draft.id,
                wall_role=wall.get("role", "inner"),
                thickness_m=_positive(_to_float(wall.get("thickness"), 0.18), 0.18),
                height_m=_to_float(wall.get("height")),
                material_label=wall.get("material"),
                source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
                centerline_geom=wall_centerline_geom(wall, scale_ratio),
                metadata_json=wall_meta,
            )
            db.add(draft_wall)
            db.flush()

            if wall.get("id") is not None:
                wall_id_map[str(wall["id"])] = draft_wall.id

        for opening in request_dto.scene.openings:
            # line_geom 을 먼저 만들고 width_m 은 그 길이에서 파생 — 단일 source of truth.
            # (project_openings_onto_walls 등으로 bbox 가 재배치돼도 line_geom 과 항상 일치.)
            # height_m / sill_height_m 은 opening_type 별 표준값. raw 픽셀 bbox 는
            # metadata_json.raw 에만 보관 (단위 혼입 방지).
            line_geom = opening_line_geom(opening, scale_ratio)
            width_m = line_geom_length_m(line_geom)
            height_m, sill_height_m = opening_type_dims(
                opening.get("type") or opening.get("opening_type")
            )

            wall_ref = opening.get("wall_ref")
            db.add(
                DraftOpening(
                    scene_draft_id=scene_draft.id,
                    wall_id=wall_id_map.get(str(wall_ref)) if wall_ref is not None else None,
                    opening_type=opening.get("type", "opening"),
                    width_m=_positive(width_m, 0.8),
                    height_m=_positive(height_m, 1.2),
                    sill_height_m=sill_height_m,
                    source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
                    line_geom=line_geom,
                    metadata_json={"raw": opening},
                )
            )

        for obj in request_dto.scene.objects:
            obj_type = obj.get("class_name") or obj.get("type") or "unknown"
            # width_m/height_m 를 metadata_json 최상위에 둠 → 프론트 readObjectSize 가
            # 이 값으로 실제 크기 렌더 (없으면 1.6m 기본). bbox×scale 로 fusion 이 채움.
            obj_meta: dict[str, Any] = {"raw": obj}
            if obj.get("width_m") is not None:
                obj_meta["width_m"] = obj.get("width_m")
            if obj.get("height_m") is not None:
                obj_meta["height_m"] = obj.get("height_m")
            db.add(
                DraftObject(
                    scene_draft_id=scene_draft.id,
                    object_type=obj_type,
                    confidence=_to_float(obj.get("score") or obj.get("confidence")),
                    source_method=DEFAULT_DRAFT_ANALYSIS_METHOD,
                    point_geom=object_point_geom(obj, scale_ratio),
                    metadata_json=obj_meta,
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
    current_user: User,
    inference_mode: str = "sagemaker",
) -> AnalyzeFromAssetResponse:
    """이미 등록된 Asset 도면을 분석해서 비동기 Job 등록.

    /upload/floorplan/analyze 와 동일하게 Job 패턴 사용 → 202 응답 + job_id.
    완료 조회는 GET /floorplan-jobs/{job_id}.
    """
    from app.services import _s3
    from app.services.asset_service import _get_owned_asset_or_404
    from app.services.inference.floorplan_job_service import submit_floorplan_analysis

    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, current_user)

    if not asset.storage_url or not asset.storage_url.startswith("s3://"):
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            f"Asset is not on S3: {asset.storage_url}",
            status_code=500,
        )

    # S3 에서 본문 다운로드. 이후 submit_floorplan_analysis 가 SageMaker 입력용으로
    # 다시 S3 에 올린다 (현재 흐름 유지). 추후 source_s3_uri 직접 전달로 최적화 가능.
    content = _s3.download_bytes(asset.storage_url)

    filename = asset.storage_url.rsplit("/", 1)[-1] or f"{asset.id}.{asset.source_format or 'bin'}"
    s3_bucket, s3_key = _s3.split_s3_uri(asset.storage_url)
    upload_metadata = UploadStorageMetadataDTO(
        provider="s3",
        original_filename=filename,
        content_type=asset.mime_type,
        size_bytes=asset.file_size_bytes,
        s3_uri=asset.storage_url,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
    )

    job = await submit_floorplan_analysis(
        db,
        image_bytes=content,
        filename=filename,
        content_type=asset.mime_type or "application/octet-stream",
        project_id=asset.project_id,
        floor_id=asset.floor_id,
        current_user=current_user,
        upload_metadata=upload_metadata,
        created_by=current_user.email,
        source_asset_id=str(asset.id),
        inference_mode=inference_mode,
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
        rooms=[_draft_room_to_response(r) for r in scene_draft.draft_rooms],
        walls=[_draft_wall_to_response(w) for w in scene_draft.draft_walls],
        openings=[_draft_opening_to_response(o) for o in scene_draft.draft_openings],
        objects=[_draft_object_to_response(o) for o in scene_draft.draft_objects],
        created_at=scene_draft.created_at,
        updated_at=scene_draft.updated_at,
    )


def update_scene_draft_summary(
    db: Session,
    scene_draft_id: str,
    current_user: User,
    *,
    scale_ratio_m_per_px: float | None,
    scale_source: str | None,
) -> SceneDraftDetailResponse:
    """summary_json 일부 필드 갱신 (현재는 scale 관련만).

    좌표 PATCH(/draft-walls, /draft-openings, ...) 와 묶여 호출되는 흐름이라
    summary 갱신 외 자식 엔티티는 건드리지 않는다 (반환은 GET 과 동일 detail).
    JSONB 변경은 dict 새로 할당 → SQLAlchemy 가 자동 감지.
    """
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

    summary = dict(scene_draft.summary_json or {})
    if scale_ratio_m_per_px is not None:
        if scale_ratio_m_per_px <= 0:
            raise AppError(
                ErrorCode.INVALID_REQUEST_BODY,
                "scale_ratio_m_per_px must be positive.",
                status_code=400,
            )
        summary["scale_ratio_m_per_px"] = float(scale_ratio_m_per_px)
    if scale_source is not None:
        # scale_source 는 wall_postprocess 하위에 기록됨 (fusion 흐름과 일치).
        wp = dict(summary.get("wall_postprocess") or {})
        wp["scale_source"] = scale_source
        summary["wall_postprocess"] = wp

    scene_draft.summary_json = summary
    db.commit()
    db.refresh(scene_draft)
    return get_scene_draft(db, scene_draft_id, current_user)


def rescale_scene_draft(
    db: Session,
    scene_draft_id: str,
    current_user: User,
    *,
    factor: float,
    scale_source: str | None = None,
) -> SceneDraftDetailResponse:
    """한 트랜잭션 안에서 SceneDraft 전체를 비례 재스케일 (한 벽/문 실측 기반).

    프론트에서 entity 별 PATCH 를 N 번 보내던 흐름을 단일 요청으로 통합:
      - walls.centerline_geom / polygon_geom × factor
        + metadata.dimension_length.meters / dimension_match.parsed_meters / user_meters × factor
        (matched_wall_px_len 은 픽셀이라 안 건드림)
      - openings.line_geom / polygon_geom × factor, width_m × factor
        (height_m 은 수직 방향이라 안 건드림)
      - rooms.polygon_geom / centroid_geom × factor
      - objects.point_geom × factor, metadata.width_m / height_m × factor
      - summary_json.scale_ratio_m_per_px × factor (있을 때),
        summary_json.wall_postprocess.scale_source = scale_source (있을 때)

    factor 범위: 0.001 ≤ factor ≤ 1000. 1.0 근처면 no-op 으로 현재 상태만 반환.
    """
    # DTO Field 가 이미 [0.001, 1000] 막지만 서비스 단에서도 한 번 더 — 내부 호출 안전망.
    if not (0.001 <= factor <= 1000.0):
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            f"factor must be in [0.001, 1000], got {factor}",
            status_code=400,
        )

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

    if abs(factor - 1.0) < 1e-9:
        # no-op (입력 = 현재 길이) — summary 만 갱신 (사용자가 source 만 바꾸려는 경우 대비).
        if scale_source is not None:
            summary = dict(scene_draft.summary_json or {})
            wp = dict(summary.get("wall_postprocess") or {})
            wp["scale_source"] = scale_source
            summary["wall_postprocess"] = wp
            scene_draft.summary_json = summary
            try:
                db.commit()
            except SQLAlchemyError as exc:
                db.rollback()
                raise AppError(
                    ErrorCode.SCENE_DRAFT_SAVE_FAILED,
                    f"Failed to update scene draft summary: {exc}",
                    500,
                ) from exc
        return get_scene_draft(db, scene_draft_id, current_user)

    f = float(factor)

    # 1) walls
    for w in scene_draft.draft_walls:
        if w.centerline_geom is not None:
            w.centerline_geom = scale_wkb(w.centerline_geom, f)
        if w.polygon_geom is not None:
            w.polygon_geom = scale_wkb(w.polygon_geom, f)
        # metadata 의 표시용 길이 — 옛 도면 길이가 패널에 그대로 보이지 않도록 같이 갱신.
        meta = dict(w.metadata_json or {})
        dl = meta.get("dimension_length")
        if isinstance(dl, dict):
            dl = dict(dl)
            if isinstance(dl.get("meters"), (int, float)):
                dl["meters"] = float(dl["meters"]) * f
            meta["dimension_length"] = dl
        dm = meta.get("dimension_match")
        if isinstance(dm, dict):
            dm = dict(dm)
            for k in ("parsed_meters", "user_meters"):
                v = dm.get(k)
                if isinstance(v, (int, float)):
                    dm[k] = float(v) * f
            meta["dimension_match"] = dm
        w.metadata_json = meta

    # 2) openings — width_m 은 Numeric(Decimal). height_m 은 안 건드림 (수직).
    from decimal import Decimal
    for o in scene_draft.draft_openings:
        if o.line_geom is not None:
            o.line_geom = scale_wkb(o.line_geom, f)
        if o.polygon_geom is not None:
            o.polygon_geom = scale_wkb(o.polygon_geom, f)
        if o.width_m is not None:
            o.width_m = (Decimal(o.width_m) * Decimal(str(f))).quantize(Decimal("0.001"))

    # 3) rooms
    for r in scene_draft.draft_rooms:
        if r.polygon_geom is not None:
            r.polygon_geom = scale_wkb(r.polygon_geom, f)
        if r.centroid_geom is not None:
            r.centroid_geom = scale_wkb(r.centroid_geom, f)

    # 4) objects — metadata.width_m / height_m 은 floor-plane 박스 크기 → 같이 곱.
    for ob in scene_draft.draft_objects:
        if ob.point_geom is not None:
            ob.point_geom = scale_wkb(ob.point_geom, f)
        meta = dict(ob.metadata_json or {})
        for k in ("width_m", "height_m"):
            v = meta.get(k)
            if isinstance(v, (int, float)):
                meta[k] = float(v) * f
        ob.metadata_json = meta

    # 5) summary scale_ratio + scale_source
    summary = dict(scene_draft.summary_json or {})
    old_scale = summary.get("scale_ratio_m_per_px")
    if isinstance(old_scale, (int, float)) and old_scale > 0:
        summary["scale_ratio_m_per_px"] = float(old_scale) * f
    if scale_source is not None:
        wp = dict(summary.get("wall_postprocess") or {})
        wp["scale_source"] = scale_source
        summary["wall_postprocess"] = wp
    scene_draft.summary_json = summary

    # 1~5 모든 mutation 은 in-memory ORM 상태만 변경 — commit 에서 한 트랜잭션으로 flush.
    # 실패 시 좌표·metadata·summary 가 부분 적용되지 않게 전체 rollback (save_scene_draft 와 동일 패턴).
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.SCENE_DRAFT_SAVE_FAILED,
            f"Failed to persist scene draft rescale: {exc}",
            500,
        ) from exc
    return get_scene_draft(db, scene_draft_id, current_user)


# ---------------------------------------------------------------------------
# ORM → DTO 변환 (WKB → GeoJSON 변환 포함)
# ---------------------------------------------------------------------------
def _draft_room_to_response(r: DraftRoom) -> DraftRoomResponse:
    return DraftRoomResponse(
        id=r.id,
        scene_draft_id=r.scene_draft_id,
        room_name=r.room_name,
        room_type=r.room_type,
        confidence=r.confidence,
        source_method=r.source_method,
        polygon_geom=wkb_to_geojson(r.polygon_geom),
        centroid_geom=wkb_to_geojson(r.centroid_geom),
        metadata_json=r.metadata_json or {},
        created_at=r.created_at,
    )


def _draft_wall_to_response(w: DraftWall) -> DraftWallResponse:
    return DraftWallResponse(
        id=w.id,
        scene_draft_id=w.scene_draft_id,
        wall_role=w.wall_role,
        thickness_m=w.thickness_m,
        height_m=w.height_m,
        material_label=w.material_label,
        confidence=w.confidence,
        source_method=w.source_method,
        centerline_geom=wkb_to_geojson(w.centerline_geom),
        polygon_geom=wkb_to_geojson(w.polygon_geom),
        metadata_json=w.metadata_json or {},
        created_at=w.created_at,
    )


def _draft_opening_to_response(o: DraftOpening) -> DraftOpeningResponse:
    return DraftOpeningResponse(
        id=o.id,
        scene_draft_id=o.scene_draft_id,
        wall_id=o.wall_id,
        opening_type=o.opening_type,
        width_m=o.width_m,
        height_m=o.height_m,
        sill_height_m=o.sill_height_m,
        confidence=o.confidence,
        source_method=o.source_method,
        line_geom=wkb_to_geojson(o.line_geom),
        polygon_geom=wkb_to_geojson(o.polygon_geom),
        metadata_json=o.metadata_json or {},
        created_at=o.created_at,
    )


def _draft_object_to_response(o: DraftObject) -> DraftObjectResponse:
    return DraftObjectResponse(
        id=o.id,
        scene_draft_id=o.scene_draft_id,
        object_type=o.object_type,
        confidence=o.confidence,
        source_method=o.source_method,
        point_geom=wkb_to_geojson(o.point_geom),
        z_m=o.z_m,
        metadata_json=o.metadata_json or {},
        created_at=o.created_at,
    )

def create_empty_draft(
    db: Session,
    floor_id: UUID,
    source_mode: str,
    current_user: User,
) -> SceneDraftDetailResponse:
    """이미지/AI 분석 없이 빈 SceneDraft 생성. 사용자가 직접 도면 그릴 때 사용."""
    floor = (
        db.query(Floor)
        .join(Project, Floor.project_id == Project.id)
        .filter(
            Floor.id == str(floor_id),
            Project.owner_user_id == current_user.id,
        )
        .first()
    )
    if floor is None:
        raise AppError(
            ErrorCode.FLOOR_NOT_FOUND,
            "Floor not found.",
            status_code=404,
        )

    scene_draft = SceneDraft(
        project_id=floor.project_id,
        floor_id=floor.id,
        source_mode=source_mode,
        source_method=source_mode,
        summary_json={},
        status="draft",
        created_by=current_user.email,
    )
    try:
        db.add(scene_draft)
        db.commit()
        db.refresh(scene_draft)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.SCENE_DRAFT_SAVE_FAILED,
            f"Failed to create empty scene draft: {exc}",
            500,
        ) from exc

    return SceneDraftDetailResponse(
        id=scene_draft.id,
        project_id=scene_draft.project_id,
        floor_id=scene_draft.floor_id,
        source_mode=scene_draft.source_mode,
        source_asset_id=scene_draft.source_asset_id,
        source_method=scene_draft.source_method,
        summary_json=scene_draft.summary_json,
        status=scene_draft.status,
        rooms=[],
        walls=[],
        openings=[],
        objects=[],
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