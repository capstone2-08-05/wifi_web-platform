"""raw AI outputs → SceneDraft (SceneSchema) 변환.

데이터 획득은 [sagemaker_inference_service.py] 에 위임:
  - 호출자는 image_bytes + project_id/floor_id 만 넘기면 됨
  - 이 서비스는 SageMaker invoke 결과 (raw outputs in temp dir + detections list) 를 받아
    기존 wall_extraction / geometry / topology 파이프라인으로 SceneSchema 빌드
  - temp 파일은 처리 후 cleanup

기존 동기 HTTP 흐름은 제거됨 (ai_client.py 삭제, 2026-05-13). 로컬 AI 서버 띄울 필요 없음.
"""
from __future__ import annotations

import logging
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.schemas.ai_response import (
    DetectionDTO,
    MetaDTO,
    MlOutputDTO,
    WallSegmentationDTO,
)
from app.schemas.scene import Opening, Room, SceneSchema, Wall
from app.services.geometry_service import GeometryService
from app.services.sagemaker_inference_service import (
    InferenceResult,
    SageMakerInferenceFailure,
    map_failure_to_app_error,
    sagemaker_inference_service,
)
from app.services.topology_service import TopologyService
from app.services.wall_extraction import wall_extractor

logger = logging.getLogger(__name__)


class FusionService:
    def __init__(self) -> None:
        self.inference_service = sagemaker_inference_service

    async def process_image_to_scene_async(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        real_width_m: float,
        project_id: str,
        floor_id: str,
        content_type: str = "application/octet-stream",
    ) -> SceneSchema:
        """end-to-end: SageMaker invoke → 변환 → SceneSchema 반환.

        예외:
            - SageMakerInferenceFailure → AppError 로 매핑
            - 기타 예외는 원본 그대로 raise (router 가 INTERNAL_SERVER_ERROR 로 감쌈)
        """
        try:
            result = await self.inference_service.invoke_and_wait(
                image_bytes=image_bytes,
                filename=filename,
                project_id=project_id,
                floor_id=floor_id,
                content_type=content_type,
            )
        except SageMakerInferenceFailure as failure:
            logger.warning(
                "SageMaker inference failed code=%s stage=%s message=%s",
                failure.code,
                failure.stage,
                failure.message,
            )
            raise map_failure_to_app_error(failure) from failure

        try:
            ml_output = _build_ml_output_from_inference(result, filename)
            scene = await run_in_threadpool(
                self._run_wi_twin_pipeline, ml_output, real_width_m, result.prob_map_local_path
            )
            scene.inference_metadata = _build_inference_metadata(result, real_width_m)
            return scene
        finally:
            result.cleanup()

    def _run_wi_twin_pipeline(
        self,
        ml_output: MlOutputDTO,
        real_width_m: float,
        prob_map_local_path,
    ) -> SceneSchema:
        geo_service = GeometryService(
            pixel_width=ml_output.meta.original_width,
            pixel_height=ml_output.meta.original_height,
            real_width_m=real_width_m,
        )
        topo_service = TopologyService()

        # wall_extraction 은 .npy 파일 경로를 받아 prob_map 로딩
        raw_coords = wall_extractor.execute_from_prob_map(
            prob_map_local_path, threshold=None, detections=ml_output.detections
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
        extracted_rooms: list[Room] = geo_service.extract_rooms(calibrated_walls)
        topology_result = topo_service.analyze(extracted_rooms, ml_output.detections)

        openings: list[Opening] = []
        furniture_objects: list[DetectionDTO] = []
        for i, det in enumerate(ml_output.detections):
            if det.class_name in {"door", "window"}:
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
            else:
                det.id = f"furniture_{len(furniture_objects)}"
                furniture_objects.append(det)

        return SceneSchema(
            scale_ratio=geo_service.scale_ratio,
            walls=[w.model_dump() for w in calibrated_walls],
            openings=[o.model_dump() for o in openings],
            rooms=[r.model_dump() for r in extracted_rooms],
            topology=topology_result.model_dump(),
            objects=[obj.model_dump() for obj in furniture_objects],
        )


def _build_inference_metadata(result: InferenceResult, real_width_m: float) -> dict:
    """summary_json 으로 영속될 SageMaker 실행 메타데이터."""
    runtime = (result.result_payload.get("runtime") or {}) if result.result_payload else {}
    outputs = (result.result_payload.get("outputs") or {}) if result.result_payload else {}
    stages = (result.result_payload.get("stages") or {}) if result.result_payload else {}

    width_px = result.image_width_px or 1
    scale_ratio_m_per_px = real_width_m / width_px if width_px else 0.0

    return {
        "provider": "sagemaker_async",
        "job_id": result.job_id,
        "image": {
            "width_px": result.image_width_px,
            "height_px": result.image_height_px,
            "real_width_m": real_width_m,
            "scale_ratio_m_per_px": scale_ratio_m_per_px,
        },
        "runtime": runtime,
        "outputs": outputs,
        "stages": stages,
        "counts": {
            "raw_detections": len(result.detections),
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
