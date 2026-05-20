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

from app.core.settings import MASK_DIR
from app.geometry import (
    assign_wall_refs,
    bridge_collinear_walls,
    nms_filter_indices,
    project_openings_onto_walls,
    snap_wall_endpoints,
    synthesize_opening_wall_segments,
    synthesize_partition_walls_from_ticks,
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
    ) -> SceneSchema:
        """SageMaker raw outputs (download 완료된 상태) → SceneSchema.

        CPU 후처리가 무거우므로 thread pool 에서 실행.
        호출자가 `result.cleanup()` 책임.
        """
        ml_output = _build_ml_output_from_inference(result, filename)
        sagemaker_meta = _build_sagemaker_meta(result)
        # per-job 디버그 이미지 격리 (멀티잡 동시 실행 시 덮어쓰기 방지).
        debug_dir = MASK_DIR / "wall_postprocess" / str(result.job_id)
        scene = await run_in_threadpool(
            self._run_wi_twin_pipeline,
            ml_output,
            result.prob_map_local_path,
            sagemaker_meta,
            result.source_image_local_path,
            debug_dir,
            result.ocr_priors,
            result.line_priors,
            result.roi_transform,
        )
        return scene

    @staticmethod
    def _recover_partitions_from_dimension_ticks(
        postprocess, walls, scale_ratio: float
    ) -> list[tuple[float, float, float, float]]:
        """치수선 그리드 tick(벽 없는 경계) + 직교벽 끝점 → 누락 칸막이 조각.

        best-effort: 입력이 없거나 실패하면 빈 리스트 (방 추출에 영향 없음).
        """
        try:
            dim_matches = getattr(postprocess, "dimension_matches", None) or []
            if not dim_matches or not walls or not scale_ratio or scale_ratio <= 0:
                return []
            from app.services.wall_extraction_helpers import dimension_matching as _dm
            from app.services.wall_extraction_helpers.ocr import OCREntry

            entries = []
            for m in dim_matches:
                bb = m.get("bbox") or []
                if len(bb) != 4:
                    continue
                entries.append(
                    OCREntry(
                        bbox=tuple(int(v) for v in bb),  # type: ignore[arg-type]
                        text=str(m.get("text", "")),
                        confidence=float(m.get("ocr_confidence", 0.0)),
                    )
                )
            if not entries:
                return []

            wall_px = [[w.x1, w.y1, w.x2, w.y2] for w in walls]
            spans = _dm.build_dimension_spans(entries, float(scale_ratio), wall_px)
            if not spans:
                return []

            # 벽이 안 붙은(boundary None) tick 만 칸막이 후보로.
            vtick_xs: list[float] = []
            htick_ys: list[float] = []
            for s in spans:
                if s.orientation == "horizontal":
                    if s.boundary_lo_wall is None:
                        vtick_xs.append(s.axis_lo)
                    if s.boundary_hi_wall is None:
                        vtick_xs.append(s.axis_hi)
                else:
                    if s.boundary_lo_wall is None:
                        htick_ys.append(s.axis_lo)
                    if s.boundary_hi_wall is None:
                        htick_ys.append(s.axis_hi)

            return synthesize_partition_walls_from_ticks(vtick_xs, htick_ys, walls)
        except Exception:
            logger.warning("치수 tick 칸막이 복구 skip", exc_info=True)
            return []

    def _run_wi_twin_pipeline(
        self,
        ml_output: MlOutputDTO,
        prob_map_local_path,
        sagemaker_meta: dict[str, Any] | None = None,
        source_image_local_path=None,
        debug_dir=None,
        ocr_priors: list[dict] | None = None,
        line_priors: list[dict] | None = None,
        roi_transform: dict | None = None,
    ) -> SceneSchema:
        # wall_extraction 은 .npy 파일 경로를 받아 prob_map 로딩.
        # priors (AI 서버 사전 분석 결과) 가 있으면 wall_extraction 이 그걸 사용,
        # 없으면 source_image_local_path 기반으로 자체 OCR/line 추출.
        wall_result = wall_extractor.execute_from_prob_map(
            prob_map_local_path,
            threshold=None,
            detections=ml_output.detections,
            image_path=source_image_local_path,
            debug_dir=debug_dir,
            ocr_priors=ocr_priors,
            line_priors=line_priors,
        )
        raw_coords = wall_result.walls
        postprocess_meta_dict = wall_result.postprocess.to_dict()
        # AI 서버가 같이 내려준 RoiTransform 도 영속화 (디버깅/프론트 표시용).
        if roi_transform is not None:
            postprocess_meta_dict["roi_transform"] = roi_transform

        # OCR 치수 추정 scale 이 있으면 그걸로, 없으면 default fallback (사용자가
        # PropertiesPanel 에서 벽별 실측 입력해 후속 보정).
        scale_ratio_override: float | None = None
        scale_source = "default_fallback"
        scale_est = wall_result.postprocess.scale_estimate
        if scale_est and scale_est.get("scale_m_per_px", 0) > 0:
            scale_ratio_override = float(scale_est["scale_m_per_px"])
            scale_source = "ocr_dimension"
            logger.info(
                "scale source: OCR dimension matching (%.6f m/px, %d pairs)",
                scale_ratio_override, scale_est.get("pair_count", 0),
            )
        else:
            logger.info(
                "scale source: default fallback — OCR dim 매칭 부족, 사용자 보정 필요"
            )
        postprocess_meta_dict["scale_source"] = scale_source

        geo_service = GeometryService(
            pixel_width=ml_output.meta.original_width,
            pixel_height=ml_output.meta.original_height,
            scale_ratio=scale_ratio_override,
        )
        topo_service = TopologyService()
        scale_ratio = geo_service.scale_ratio

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

        # 개구부(문/창) 를 벽 증거로 활용 — U-Net 이 개구부에서 벽을 끊는 경우가 많아
        # 그 자리에 중심선 조각을 끼워 끊긴 벽을 잇는다 → 방 폐합률 ↑ (도면별 편차 ↓).
        # ⚠️ 합성 조각은 방 추출 입력에만 더하고 영속 wall 에는 넣지 않는다 (문 위 벽 중복 방지).
        opening_bboxes = [
            tuple(float(v) for v in det.bbox_xyxy)
            for det in ml_output.detections
            if det.class_name in {"door", "window"}
        ]
        opening_segments = synthesize_opening_wall_segments(
            opening_bboxes, calibrated_walls
        )

        # 치수선 그리드 tick → 누락 칸막이 복구 (게이팅: 직교벽 끝점 + tick 두 증거).
        # 개구부 신호와 상보적. 실패해도 방 추출엔 영향 없게 best-effort.
        partition_segments = self._recover_partitions_from_dimension_ticks(
            wall_result.postprocess, calibrated_walls, scale_ratio
        )

        # 합성 조각(개구부 + 칸막이)은 방 추출 입력에만 더하고 영속 wall 에는 안 넣음.
        synth_segments = list(opening_segments) + list(partition_segments)
        walls_for_rooms: list[Wall] = calibrated_walls
        if synth_segments:
            walls_for_rooms = list(calibrated_walls) + [
                Wall(
                    id=f"synth_seg_{i}",
                    x1=sx1, y1=sy1, x2=sx2, y2=sy2,
                    thickness=0.0,  # 추정 두께 median 에서 제외되도록 0 (extract_rooms 가 >0 만 사용)
                )
                for i, (sx1, sy1, sx2, sy2) in enumerate(synth_segments)
            ]
            logger.info(
                "wall completion: 방 추출용 합성 조각 +%d개 (개구부 %d, 치수 tick %d)",
                len(synth_segments), len(opening_segments), len(partition_segments),
            )

        extracted_rooms: list[Room] = geo_service.extract_rooms(walls_for_rooms)
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

        # 중복 detection 제거 (NMS) — type 무관 단일 pass.
        # 같은 위치에 door 와 window 가 동시 감지되면 score 1 등만 유지.
        # (이전엔 type 별로 따로 NMS 였지만 사용자가 한 개만 보이길 원해 변경.)
        if opening_dets:
            before = len(opening_dets)
            all_boxes = [
                tuple(float(v) for v in d.bbox_xyxy) for d in opening_dets
            ]
            all_scores = [float(d.score) for d in opening_dets]
            kept_indices = nms_filter_indices(all_boxes, all_scores)
            opening_dets = [opening_dets[i] for i in kept_indices]
            if len(opening_dets) < before:
                logger.info(
                    "opening NMS (cross-type): %d → %d (removed %d duplicates)",
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
            postprocess_metadata=postprocess_meta_dict,
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
