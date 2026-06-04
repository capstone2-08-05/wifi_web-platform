import { api } from './client';
import type { Paginated, UUID } from '@/types/common';
import type {
  CoverageEstimationMethod,
  DetectedAp,
  EstimatedCoverage,
  MeasurementPoint,
  MeasurementSession,
} from '@/types/measurement-session';

// §10.4 / §10.5 — 백엔드 PR #77 (commit fc7977d) 로 구현 완료.

export interface ListSessionsParams {
  status?: 'in_progress' | 'completed' | string;
  page?: number;
  page_size?: number;
}

export const measurementSessionApi = {
  // GET /floors/{floor_id}/measurement-sessions — 층의 세션 목록 (페이지네이션 + status 필터).
  listByFloor: (floorId: UUID, params?: ListSessionsParams) =>
    api
      .get<Paginated<MeasurementSession>>(`/floors/${floorId}/measurement-sessions`, {
        params,
      })
      .then((r) => r.data),

  // GET /measurement-sessions/{session_id}
  get: (sessionId: UUID) =>
    api.get<MeasurementSession>(`/measurement-sessions/${sessionId}`).then((r) => r.data),

  // GET /measurement-sessions/{session_id}/points (페이지네이션, default page_size=100, max 500)
  listPoints: (
    sessionId: UUID,
    params?: { page?: number; page_size?: number; ap_bssid?: string | null },
  ) =>
    api
      .get<Paginated<MeasurementPoint>>(`/measurement-sessions/${sessionId}/points`, {
        params,
      })
      .then((r) => r.data),

  // GET /measurement-sessions/{session_id}/detected-aps — list 직접 반환 (envelope 없음).
  listDetectedAps: (sessionId: UUID) =>
    api
      .get<DetectedAp[]>(`/measurement-sessions/${sessionId}/detected-aps`)
      .then((r) => r.data),

  // GET /measurement-sessions/{session_id}/estimated-coverage — dense RSSI 맵 추정 (#81).
  // method: 'gp_only' = 측정값만 GP (실측 의미), 'residual_kriging' = sim prior + residual GP (통합 의미),
  // 'auto' (생략 시) = sim 있으면 residual, 없으면 gp_only.
  getEstimatedCoverage: (
    sessionId: UUID,
    params?: {
      resolution_m?: number;
      method?: CoverageEstimationMethod | 'auto';
      ap_bssid?: string | null;
    },
  ) =>
    api
      .get<EstimatedCoverage>(
        `/measurement-sessions/${sessionId}/estimated-coverage`,
        { params },
      )
      .then((r) => r.data),
};
