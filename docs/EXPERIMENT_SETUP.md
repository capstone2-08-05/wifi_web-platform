# 실험 개발 세팅 가이드

이 문서는 `사진/도면 -> 3D -> Sionna RT` 파이프라인을 단계별로 검증하기 위한 실행 가이드입니다.

## 1. 로컬 앱 레포(현재 레포)에서 가능한 범위

- Backend 업로드 API (`/upload/floorplan`)
- Rule-based 벽 추출 API (`/experiments/wall/rule-based/{fileId}`)
- Frontend three.js 샘플 렌더
- 외부 AI/RF 서버 연동용 API 포인트
  - `/experiments/wall/unet/{fileId}`
  - `/experiments/objects/yolo/{fileId}`
  - `/experiments/rf/sionna/smoke`

## 2. 별도 레포 연동 정책

AI/RF는 GPU 서버 자원과 의존성이 크므로 별도 레포를 권장합니다.

- `project-ai` (U-Net/YOLO/VLM)
- `project-rf` (Sionna RT)
- 로컬 템플릿: `capstone2-ai/` (실험 API 서버)

현재 레포는 오케스트레이션/검증 레이어로 사용합니다.

## 3. 환경 변수

루트 `.env`에 다음 값을 설정합니다.

```env
DATABASE_URL=postgresql://appuser:apppass@localhost:5432/appdb
BACKEND_PORT=8000
FRONTEND_PORT=5173
AI_SERVICE_URL=http://<ai-server>:<port>
RF_SERVER_URL=http://<rf-server>:<port>
OPENAI_API_KEY=
```

`AI_SERVICE_URL`, `RF_SERVER_URL`이 비어 있으면 관련 API는 `pending` 상태를 반환합니다.

## 4. 실행 순서

### 4-1) DB
```powershell
cd docker
docker compose up -d
```

### 4-2) Backend
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4-3) Frontend
```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## 5. 단계별 검증 체크

### 단계 A: Backend/DB
```powershell
powershell -ExecutionPolicy Bypass -File scripts/test/smoke_backend.ps1
```

### 단계 B: Upload
```powershell
powershell -ExecutionPolicy Bypass -File scripts/test/smoke_upload.ps1 -FilePath "C:\path\to\plan.png"
```

### 단계 C: Rule-based 벽 추출
1) 업로드 응답에서 `fileId` 확인  
2) 호출:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/experiments/wall/rule-based/<fileId>" -Method Post
```

### 단계 D: U-Net/YOLO 연동
AI 서버 연동 후 호출:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/experiments/wall/unet/<fileId>" -Method Post
Invoke-RestMethod -Uri "http://127.0.0.1:8000/experiments/objects/yolo/<fileId>" -Method Post
```

AI 서버 빠른 실행:
```powershell
cd capstone2-ai
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 9000 --reload
```

### 단계 E: 3D 렌더
- Frontend에서 `샘플 JSON 로드` 클릭
- 벽 3D 렌더와 카메라 회전 확인

### 단계 F: Sionna RT 연동
RF 서버 연동 후 호출:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/experiments/rf/sionna/smoke" -Method Post
```

## 6. 권장 실험 순서

1. GT JSON -> three.js 렌더 -> RF 변환
2. U-Net 벽 분할 실험
3. YOLO 객체 탐지 실험
4. 의미 추론(GPT/VLM) 실험
5. End-to-end 3종 실험(평면도/사진/하이브리드)
