import sys
import cv2
import numpy as np
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.geometry_service import GeometryService

# 일단 테스트용으로 마스크 이미지 만들어봄
def create_test_mask(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    mask = np.zeros((1000, 1000), dtype=np.uint8)
    
    cv2.line(mask, (200, 200), (200, 700), 255, 10)
    cv2.line(mask, (200, 200), (800, 200), 255, 10)
    
    cv2.imwrite(str(path), mask)
    print(f"✅ 테스트 이미지 생성됨: {path}")

def run_opencv_unit_test():
    print("\n" + "="*50)
    print("🔍 [Unit Test] OpenCV 벽 벡터화 로직 정밀 검사")
    print("="*50)

    test_mask_path = backend_dir / "outputs" / "test_wall_mask.png"
    create_test_mask(test_mask_path)
    
    service = GeometryService(pixel_width=1000, pixel_height=1000, real_width_m=10.0)

    print("\n[단계 1] 이미지 읽기 및 좌표 추출 중...")
    try:
        walls = service.process_image_to_walls(test_mask_path)
        
        print(f"\n[단계 2] 결과 분석")
        print(f"📊 발견된 벽 개수: {len(walls)}개")

        for i, w in enumerate(walls):
            print(f"   🧱 벽 {i+1} ({w.id})")
            print(f"      - 시작: ({w.x1}m, {w.y1}m)")
            print(f"      - 끝:   ({w.x2}m, {w.y2}m)")
            
        if len(walls) >= 2:
            print("\n✅ 성공: 벽이 정상적으로 벡터화되었습니다.")
        else:
            print("\n⚠️ 경고: 예상보다 벽이 적게 발견되었습니다. 파라미터를 확인하세요.")

    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_opencv_unit_test()