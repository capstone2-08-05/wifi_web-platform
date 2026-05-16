"""raw AI outputs → SceneSchema 변환 (순수 후처리, SageMaker 호출 없음).

흐름:
  - 호출자가 SageMaker invocation 결과 (`InferenceResult`) 를 미리 받아옴
  - 이 서비스는 그 raw outputs 를 wall_extraction/geometry/topology 파이프라인으로
    SceneSchema 로 변환만 함
  - SageMaker 통신과 DB 영속화는 floorplan_job_service 의 책임

기존 동기 HTTP 흐름은 제거됨 (ai_client.py 삭제, 2026-05-13). Job 비동기 패턴으로 전환됨.
"""
from __future__ import annotations

import logging
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.geometry import (
    assign_wall_refs,
    bridge_collinear_walls,
    nms_filter_indices,
    project_openings_onto_walls,
    snap_wall_endpoints,
)
from app.schemas.ai_response import (
    DetectionDTO,
    MetaDTO,
    MlOutputDTO,
    WallSegmentationDTO,
)
from app.schemas.scene import Opening, Room, SceneSchema, Wall
from app.services.geometry_service import GeometryService
from app.services.sagemaker_inference_service import InferenceResult
from app.services.topology_service import TopologyService
from app.services.wall_extraction import wall_extractor

logger = logging.getLogger(__name__)


class FusionService:
    async def build_scene_from_inference(
        self,
        *,
        result: InferenceResult,
        filename: str,
        real_width_m: float,
    ) -> SceneSchema:
        """SageMaker raw outputs (download 완료된 상태) → SceneSchema.

        CPU 후처리가 무거우므로 thread pool 에서 실행.
        호출자가 `result.cleanup()` 책임.
        """
        ml_output = _build_ml_output_from_inference(result, filename)
        sagemaker_meta = _build_sagemaker_meta(result)
        scene = await run_in_threadpool(
            self._run_wi_twin_pipeline,
            ml_output,
            real_width_m,
            result.prob_map_local_path,
            sagemaker_meta,
            result.source_image_local_path,
        )
        return scene

    def _run_wi_twin_pipeline(
        self,
        ml_output: MlOutputDTO,
        real_width_m: float,
        prob_map_local_path,
        sagemaker_meta: dict[str, Any] | None = None,
        source_image_local_path=None,
    ) -> SceneSchema:
        geo_service = GeometryService(
            pixel_width=ml_output.meta.original_width,
            pixel_height=ml_output.meta.original_height,
            real_width_m=real_width_m,
        )
        topo_service = TopologyService()
        scale_ratio = geo_service.scale_ratio

        # wall_extraction 은 .npy 파일 경로를 받아 prob_map 로딩.
        # source_image 있으면 §69 multi-threshold + OCR scoring 흐름 활성화.
        raw_coords = wall_extractor.execute_from_prob_map(
            prob_map_local_path,
            threshold=None,
            detections=ml_output.detections,
            image_path=source_image_local_path,
        )

        raw_walls: list[Wall] = []
        for i, coord in enumerate(raw_coords):
            x1, y1, x2, y2 = coord
            raw_walls.append(
                Wall(
                    id=str(i),
                    x1=float(x1),
                    y1=float(y1),
                    x2=float(x2),
                    y2=float(y2),
                    thickness=0.2,
                )
            )

        calibrated_walls = geo_service.calibrate_walls(raw_walls, ml_output.detections)

        # 후-후처리: wall_extraction 결과를 다시 보고 정합성 보정.
        #   collinear 끊김 잇기 → 코너 끝점 스냅 → 닫힌 루프 형성 가능성 ↑ (방 추출 살아남).
        n_walls_before = len(calibrated_walls)
        calibrated_walls = bridge_collinear_walls(calibrated_walls)
        calibrated_walls = snap_wall_endpoints(calibrated_walls)
        if len(calibrated_walls) != n_walls_before:
            logger.info(
                "wall reconciliation: %d → %d walls (collinear bridged)",
                n_walls_before, len(calibrated_walls),
            )

        extracted_rooms: list[Room] = geo_service.extract_rooms(calibrated_walls)
        topology_result = topo_service.analyze(extracted_rooms, ml_output.detections)

        # door/window 와 가구 detection 분리
        opening_dets: list[DetectionDTO] = []
        furniture_objects: list[DetectionDTO] = []
        for det in ml_output.detections:
            if det.class_name in {"door", "window"}:
                opening_dets.append(det)
            else:
                det.id = f"furniture_{len(furniture_objects)}"
                furniture_objects.append(det)

        # 같은 문/창을 여러 번 탐지한 중복 제거 (NMS). score 높은 박스 유지.
        # type 별로 따로 NMS — 가까이 겹친 door 와 window 가 서로를 제거하지 않도록.
        if opening_dets:
            before = len(opening_dets)
            kept_set: set[int] = set()
            for cls in ("door", "window"):
                group = [i for i, d in enumerate(opening_dets) if d.class_name == cls]
                if not group:
                    continue
                g_boxes = [
                    tuple(float(v) for v in opening_dets[i].bbox_xyxy) for i in group
                ]
                g_scores = [float(opening_dets[i].score) for i in group]
                for k in nms_filter_indices(g_boxes, g_scores):
                    kept_set.add(group[k])
            opening_dets = [d for i, d in enumerate(opening_dets) if i in kept_set]
            if len(opening_dets) < before:
                logger.info(
                    "opening NMS (per-type): %d → %d (removed %d duplicates)",
                    before, len(opening_dets), before - len(opening_dets),
                )

        # opening 의 물리 치수(width_m/height_m)는 fusion 에서 정하지 않는다.
        # save_scene_draft 가 line_geom 길이 + type 별 표준값으로 결정론적으로 계산.
        openings: list[Opening] = []
        for i, det in enumerate(opening_dets):
            bx1, by1, bx2, by2 = det.bbox_xyxy
            openings.append(
                Opening(
                    id=f"opening_{i}",
                    type=det.class_name,
                    x1=float(bx1),
                    y1=float(by1),
                    x2=float(bx2),
                    y2=float(by2),
                )
            )

        # Phase 2.5: 각 opening 의 bbox 방향과 일치하는 가장 가까운 wall 의 id 를 wall_ref 로.
        matched_count = assign_wall_refs(openings, calibrated_walls)
        # 매칭된 opening 을 wall 중심선 위로 투영 → 문/창이 벽에 정확히 박힘.
        projected = project_openings_onto_walls(openings, calibrated_walls)
        if openings:
            logger.info(
                "wall-opening match: %d/%d linked, %d projected onto walls",
                matched_count, len(openings), projected,
            )

        return SceneSchema(
            scale_ratio=scale_ratio,
            walls=[w.model_dump() for w in calibrated_walls],
            openings=[o.model_dump() for o in openings],
            rooms=[r.model_dump() for r in extracted_rooms],
            topology=topology_result.model_dump(),
            objects=[obj.model_dump() for obj in furniture_objects],
            inference_metadata=sagemaker_meta,
        )


def _build_sagemaker_meta(result: InferenceResult) -> dict[str, Any]:
    """InferenceResult 에서 감사/디버깅용 메타만 추려서 dict 로.

    summary_json.sagemaker 에 저장될 형태.
    """
    payload = result.result_payload or {}
    return {
        "job_id": result.job_id,
        "inference_id": payload.get("inference_id"),
        "endpoint_name": payload.get("endpoint_name"),
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at"),
        "stages": payload.get("stages") or {},
        "runtime": payload.get("runtime") or {},
        "outputs": payload.get("outputs") or {},
        "image": payload.get("image") or {
            "width_px": result.image_width_px,
            "height_px": result.image_height_px,
        },
    }


def _build_ml_output_from_inference(
    result: InferenceResult, filename: str
) -> MlOutputDTO:
    """InferenceResult (S3 다운로드 결과) → 기존 MlOutputDTO 로 변환."""
    detections = [
        DetectionDTO.model_validate(
            {
                "id": f"det_{i}",
                "class": det.get("class_name") or str(det.get("class_id", "unknown")),
                "score": float(det.get("confidence", 0.0)),
                "bbox_xyxy": [float(v) for v in det.get("bbox", [0, 0, 0, 0])],
            }
        )
        for i, det in enumerate(result.detections)
    ]

    return MlOutputDTO(
        meta=MetaDTO(
            sample_id=result.job_id,
            image_name=filename,
            original_width=result.image_width_px or 1,
            original_height=result.image_height_px or 1,
        ),
        wall_segmentation=WallSegmentationDTO(
            mask_path=str(result.mask_local_path),
            prob_map_path=str(result.prob_map_local_path),
        ),
        detections=detections,
    )


fusion_service = FusionService()
