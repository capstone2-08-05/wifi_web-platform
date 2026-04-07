import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.schemas.ai_output import MlOutputDTO
from app.services.fusion_service import fusion_service
from app.services.geometry_service import GeometryService

def test_wi_twin_logic():
    print(" Wi-Twin 백엔드 통합 로직 테스트 시작")
    print("=" * 60)

    # 1. ai가 보낸 데이터가 MlOutputDTO 규격에 맞는지 검사 (지금은 일단 mock 데이터)
    mock_ai_json = {
        "meta": {
            "sample_id": "floor_001",
            "image_name": "sample_drawing.png",
            "original_width": 2000,
            "original_height": 1500,
            "coord_system": "pixel",
            "origin": "top-left"
        },
        "wall_segmentation": {
            "mask_path": "outputs/masks/floor_001_mask.png",
            "threshold": 0.5
        },
        "detections": [
            {
                "id": "det_001",
                "class": "door",
                "score": 0.98,
                "bbox_xyxy": [800, 1200, 950, 1220]
            },
            {
                "id": "det_002",
                "class": "bed",
                "score": 0.85,
                "bbox_xyxy": [300, 500, 600, 900]
            }
        ]
    }

    print("\n[STEP 1] JSON 데이터 검증 (MlOutputDTO 변환)")
    try:
        ai_output = MlOutputDTO(**mock_ai_json)
        print(f"✅ 데이터 검증 완료: 이미지 크기 {ai_output.meta.original_width}x{ai_output.meta.original_height}")
    except Exception as e:
        print(f"❌ 데이터가 규격에 맞지 않습니다: {e}")
        return

    # 2. GeometryService 단독 테스트 (좌표 변환 확인)
    print("\n[STEP 2] GeometryService 변환 테스트 (2000px -> 10m 가정)")
    geo_service = GeometryService(
        pixel_width=ai_output.meta.original_width, 
        pixel_height=ai_output.meta.original_height, 
        real_width_m=10.0
    )
    
    # 문(door)의 중심점 좌표 하나만 변환해보기
    px, py = 800, 1200
    mx, my = geo_service.convert_pixel_to_meter(px, py)
    print(f"✅ 변환 확인: 픽셀({px}, {py}) -> 실제({mx}, {my})m (계산된 비율: {geo_service.scale_ratio})")

    # 3. FusionService 전체 파이프라인 테스트 
    print("\n[STEP 3] FusionService 전체 파이프라인 가동")
    try:
        
        final_scene = fusion_service.run_wi_twin_pipeline(ml_output=ai_output)
        
        print(f"✅ 파이프라인 실행 성공!")
        print(f"✅ 최종 결과 요약: 벽 {len(final_scene.walls)}개, 문 {len(final_scene.openings)}개")

        # 4. 최종 JSON 
        print("\n[STEP 4] RF에게 전달될 최종 JSON 데이터")
        print("-" * 50)
        print(final_scene.model_dump_json(indent=2))
        print("-" * 50)

    except Exception as e:
        import traceback
        print(f"❌ 파이프라인 실행 중 에러 발생: {e}")
        traceback.print_exc() 

if __name__ == "__main__":
    test_wi_twin_logic()