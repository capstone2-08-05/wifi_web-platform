# DB Setup (PostgreSQL + PostGIS)

이 문서는 Alembic 마이그레이션 기반 DB 스키마 적용 방법을 설명합니다.

## 1) 적용된 핵심 수정 포인트

- `floors.height_m` -> `floors.default_ceiling_height_m`로 변경
- `jobs.started_at`, `jobs.finished_at` 실제 컬럼 추가
- `rooms/walls/openings/objects`에 `confidence`, `source_method` 추가
- `scene_versions.parametric_scene_url` 단일 컬럼 대신
  - `render_scene_url`
  - `rf_scene_url`
  - `artifacts_json`
- `measurement_sessions.measurement_type` 유지 + 기본값 `smartphone_app`
- `scene_drafts`, `scene_versions`에 입력 출처 추적 필드 추가
  - `source_mode`, `source_asset_id`, `source_method`
- geometry는 실내 로컬 좌표계(2D XY + 별도 z/height) 기준
  - PostGIS `geometry(..., 0)` + `z_m`, `height_m`

## 2) 마이그레이션 파일

- `backend/migrations/versions/20260330_0001_initial_schema.py`
- Alembic 설정:
  - `backend/alembic.ini`
  - `backend/migrations/env.py`

## 3) 최초 실행

```powershell
cd docker
docker compose up -d
```

```powershell
cd ..\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
```

## 4) 재생성(완전 초기화) 필요 시

```powershell
cd ..\docker
docker compose down -v
docker compose up -d
```

그 다음 다시:

```powershell
cd ..\backend
alembic upgrade head
```

## 5) 확인 쿼리

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

```sql
SELECT f.id, f.name, f.default_ceiling_height_m
FROM floors f
LIMIT 10;
```

## 6) 다음 단계 권장

- 새 변경은 SQL 파일이 아니라 Alembic revision으로만 반영
- geometry 검증 쿼리(자기교차/닫힘 여부)를 테스트 스크립트로 분리
