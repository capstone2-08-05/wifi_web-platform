from app.services.geometry_service import GeometryService

# 1. 테스트 설정: 이미지 가로 1000px, 세로 800px / 실제 가로 길이는 10미터라고 가정
test_service = GeometryService(pixel_width=1000, pixel_height=800, real_width_m=10.0)

# 2. 가짜 AI 데이터 (벽 좌표: [x1, y1, x2, y2])
mock_ai_walls = [
    [0, 0, 500, 400],  # 정중앙까지 가는 벽
    [100, 100, 100, 300] # 수직 벽
]

# 3. 변환 실행
results = test_service.process_ai_walls(mock_ai_walls)

# 4. 결과 출력
print("--- 변환 결과 ---")
for wall in results:
    print(f"벽 ID {wall['id']}: 시작{wall['start_pos']}m -> 끝{wall['end_pos']}m")