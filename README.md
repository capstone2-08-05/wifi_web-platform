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

## 2) 환경 변수 (backend)

루트 `.env`:

```env
DATABASE_URL=postgresql://appuser:apppass@localhost:5432/appdb
BACKEND_PORT=8000
FRONTEND_PORT=5173
AI_SERVICE_URL=http://localhost:9000
RF_SERVER_URL=
OPENAI_API_KEY=
```

---

## 3) 서비스별 실행

### A. DB (PostgreSQL + PostGIS)

```powershell
cd docker
docker compose up -d
docker compose ps
```

### B. Backend

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

### C. Frontend

```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

### D. AI 서비스 (별도 레포/서비스)

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

## 4) AI API 계약 (multipart)

AI 서버는 파일 경로가 아니라 **파일 자체**를 받습니다.

- `POST /wall/unet`
  - form-data: `file_id`, `file`
- `POST /objects/yolo`
  - form-data: `file_id`, `file`

이 방식이라 backend와 ai 서버가 다른 머신이어도 경로 문제 없이 동작합니다.

---

## 5) 스모크 테스트

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

## 6) 참고 문서

- `docs/EXPERIMENT_SETUP.md`
- `docs/DB_SETUP.md`
- `shared/api-contracts/ai-service-contract.json`
- `shared/api-contracts/rf-service-contract.json`

