# Capstone2 Service Deployment Guide

- `frontend`: 사용자 UI + three.js 렌더
- `backend`: API 오케스트레이션(업로드/DB/AI-RF 호출)
- `capstone2-ai`: GPU 추론 서버(U-Net/YOLO)
- `capstone2-rf`(별도 레포 권장): Sionna RT 서버

---

## 1) 빠른 아키텍처

`Frontend -> Backend -> AI/RF`

- 프론트는 파일 업로드와 결과 시각화만 담당
- 백엔드는 업로드 파일 저장 후 AI/RF로 전달
- AI 서버는 모델 추론만 담당
- RF 서버는 scene 변환/시뮬레이션만 담당

---

## 2) 환경 변수

`web-platform` 루트의 `.env` (예시는 `.env.example`). Alembic은 `backend/migrations/env.py`에서 이 파일을 읽습니다.

```env
POSTGRES_DB=appdb
POSTGRES_USER=appuser
POSTGRES_PASSWORD=apppass
POSTGRES_PORT=5432

DATABASE_URL=postgresql://appuser:apppass@localhost:5432/appdb
BACKEND_PORT=8000
FRONTEND_PORT=5173
AI_SERVICE_URL=http://localhost:9000
RF_SERVER_URL=http://localhost:9100
OPENAI_API_KEY=
```

---

## 3) DB 세팅 (PostgreSQL + PostGIS)

**전제:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)이 설치되어 있고 **실행 중**이어야 합니다.  
`docker_engine` 파이프 오류는 데몬이 꺼져 있을 때 납니다.

### 3.1 컨테이너 기동

`web-platform` 루트에서:

```powershell
docker compose up -d
docker compose ps
```

구성 파일: 루트 `docker-compose.yml` (동일 내용: `docker/docker-compose.yml`).

### 3.2 스키마 적용 (Alembic)

`web-platform/backend`에서:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
alembic current
```

Windows에서 Python 버전이 여러 개면 `alembic`이 다른 인터프리터를 쓸 수 있으니, 아래처럼 **같은 버전으로 고정**하는 것을 권장합니다.

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 -m alembic upgrade head
py -3.12 -m alembic current
```

성공 시 `alembic current`에 `20260330_0001 (head)`가 보입니다.

### 3.3 DB 완전 초기화 후 다시 올리기

```powershell
cd ..
docker compose down -v
docker compose up -d
cd backend
alembic upgrade head
```

### 3.4 데이터가 비어 있는 이유

마이그레이션은 **테이블·인덱스·제약만** 만듭니다. `projects` 등 **행(row)은 앱이 저장하거나 시드를 넣기 전까지 0건**이 정상입니다.

### 3.5 GUI (DataGrip 등)

호스트 `localhost`, 포트 `POSTGRES_PORT`(기본 5432), DB `appdb`, 사용자/비밀번호는 `.env`의 `POSTGRES_*`와 동일하게 맞춥니다. 스키마는 주로 `public`.

---

## 4) 서비스별 실행

### A. Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

핵심 엔드포인트:
- `POST /upload/floorplan`
- `POST /experiments/wall/rule-based/{fileId}`
- `POST /experiments/wall/unet/{fileId}` (AI로 파일 직접 전송)
- `POST /experiments/objects/yolo/{fileId}` (AI로 파일 직접 전송)
- `POST /experiments/rf/sionna/smoke`

### B. Frontend

```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

### C. AI 서비스 (별도 레포/서비스)

```powershell
cd ..\rf-service\service\ai-inference
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --host 0.0.0.0 --port 9000 --reload
```

`rf-service/service/ai-inference/.env` 예시:

```env
YOLO_MODEL_PATH=/models/yolo.pt
UNET_CHECKPOINT_PATH=/models/unet.pt
YOLO_CONF_THRESHOLD=0.25
YOLO_DEVICE=cuda:0
```

---

## 5) AI API 계약 (multipart)

AI 서버는 파일 경로가 아니라 **파일 자체**를 받습니다.

- `POST /wall/unet`
  - form-data: `file_id`, `file`
- `POST /objects/yolo`
  - form-data: `file_id`, `file`

이 방식이라 backend와 ai 서버가 다른 머신이어도 경로 문제 없이 동작합니다.

---

## 6) 스모크 테스트

1. Backend health

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test/smoke_backend.ps1
```

2. 업로드

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test/smoke_upload.ps1 -FilePath "C:\path\to\plan.png"
```

3. AI 직접 테스트

```powershell
powershell -ExecutionPolicy Bypass -File ..\rf-service\service\ai-inference\scripts\smoke_test.ps1 -ImagePath "C:\path\to\plan.png"
```

---

## 7) 참고 문서

- `docs/EXPERIMENT_SETUP.md`
- `docs/DB_SETUP.md`
- `shared/api-contracts/ai-service-contract.json`
- `shared/api-contracts/rf-service-contract.json`

