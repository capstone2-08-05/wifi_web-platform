# wifang — Frontend

Wi-Fi Management SaaS의 React 프론트엔드. 도면 분석 → Draft 편집 → Scene Version 승격 흐름과 시뮬레이션·실측 진단 UI를 제공한다.

## Stack

- **빌드**: Vite + React 19 + TypeScript
- **스타일**: Tailwind CSS v4 (+ shadcn/ui 호환 토큰)
- **서버 상태**: TanStack Query
- **클라이언트 상태**: Zustand (with `persist`)
- **라우팅**: React Router v6
- **HTTP**: axios (인터셉터로 토큰 주입 + 401/TOKEN_EXPIRED 처리)
- **폼**: React Hook Form + Zod
- **캔버스**: react-konva (편집·시뮬·진단 화면에서 사용 예정)
- **아이콘**: lucide-react

## 시작하기

```bash
npm install
cp .env.example .env  # 필요 시 base URL 수정
npm run dev           # http://localhost:5173
```

빌드 / 타입체크:

```bash
npm run build    # tsc -b + vite build
npm run lint
npm run preview  # 빌드 결과 미리보기
```

## 환경 변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | 백엔드 base URL |

## 폴더 구조

```
src/
├── api/                # 도메인별 axios 호출 (auth, scene-draft, scene-version, project)
├── components/ui/      # 공용 UI 프리미티브 (Card 등)
├── config/env.ts       # import.meta.env 래퍼
├── hooks/              # 도메인 hook (use-auth 등)
├── layouts/AppLayout   # 사이드바 + 상단바 + 프로젝트/층 셀렉터
├── lib/utils.ts        # cn() 등
├── pages/              # 페이지 컴포넌트 (라우트 단위)
│   └── auth/           # 로그인/회원가입
├── providers/          # QueryProvider 등 앱 단 Provider
├── routes/             # AppRouter, ProtectedRoute
├── stores/             # Zustand (auth-store, app-store)
└── types/              # 도메인 타입 (auth, scene, project, common)
```

## 인증 흐름

1. `/auth/login` → `POST /auth/login` → `access_token` 저장 (Zustand persist → localStorage)
2. axios 요청 인터셉터가 `Authorization: Bearer <token>` 자동 주입
3. 401 응답 + `code === 'TOKEN_EXPIRED' | 'UNAUTHORIZED'` 시 토큰 정리 후 `/auth/login?next=<original-path>` 로 리다이렉트
4. 토큰 만료(`expires_in: 3600s`) 는 클라이언트에서 사전 검사 (`isAuthenticated()`) — refresh token 미지원

## Scene Draft → Scene Version 승격 ("draft 신 버전 연결")

```ts
sceneVersionApi.promote(draftId, { version_no, is_current: true });
```

- `POST /scene-drafts/{draftId}/promote` 의 request body 가 `is_current` 를 받음
- `is_current: true` 로 호출하면 그 한 번으로 새 version 이 곧바로 현재 버전이 됨 → 사용자가 이어서 작업 가능
- `setCurrent(versionId)` 는 기존 version 으로 되돌리거나 다른 version 을 활성화할 때 사용

## 라우트

| 경로 | 설명 | 보호 |
| --- | --- | --- |
| `/auth/login` | 로그인 | 공개 |
| `/auth/signup` | 회원가입 | 공개 |
| `/dashboard` | 대시보드 | 🔒 |
| `/editor` | 공간 편집 | 🔒 |
| `/simulation` | 시뮬레이션 | 🔒 |
| `/measurement` | 실측·진단 | 🔒 |
| `/mobile` | 모바일 앱 | 🔒 |
| `/settings` | 설정 | 🔒 |

## API 에러 표준화

axios 인터셉터가 모든 에러 응답을 `HttpError { status, code, message, details }` 로 변환한다.
페이지/훅에서는 `error.code` 로 분기:

- `INVALID_CREDENTIALS` → 로그인 실패 안내
- `EMAIL_ALREADY_EXISTS`, `INVALID_PASSWORD_FORMAT` → 회원가입 안내
- `TOKEN_EXPIRED` → 인터셉터에서 자동 로그아웃
- `DRAFT_ALREADY_PROMOTED` → 저장 버튼 비활성화 등

## 아직 미구현 (백엔드 스펙 수신 후 추가 예정)

- 시뮬레이션 화면 (`POST /rf-runs`, `GET /rf-runs/{id}/maps`, AP 후보 생성, AP 배치)
- 실측·진단 화면 (실측, 캘리브레이션 도메인)
- Job 폴링 (RF/AP/캘리브레이션 비동기 작업, `GET /jobs/{id}`)
- 모바일 앱 연결 흐름 (QR 스캔)
- 재질, 자료(assets) 관리 화면
- Floor CRUD, 헤더 셀렉터 데이터 연결 (`POST /floors`, `GET /floors` 스펙 미수신)
