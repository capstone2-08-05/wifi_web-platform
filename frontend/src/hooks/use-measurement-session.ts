import { useQuery } from '@tanstack/react-query';
import { measurementSessionApi } from '@/api/measurement-session';
import type { UUID } from '@/types/common';

// §10.4 — 백엔드 GET 엔드포인트 구현 완료 (PR #77).

export function useFloorMeasurementSessions(
  floorId: UUID | null,
  options?: { refetchInterval?: number | false },
) {
  return useQuery({
    queryKey: ['measurement-sessions', floorId] as const,
    queryFn: () => measurementSessionApi.listByFloor(floorId as UUID),
    enabled: !!floorId,
    staleTime: 30_000,
    refetchInterval: options?.refetchInterval ?? false,
    refetchIntervalInBackground: false,
  });
}

export function useMeasurementSession(sessionId: UUID | null) {
  return useQuery({
    queryKey: ['measurement-session', sessionId] as const,
    queryFn: () => measurementSessionApi.get(sessionId as UUID),
    enabled: !!sessionId,
    retry: false,
  });
}

/** 세션의 측정 포인트 — 페이지 1개로 한 번에 가져옴 (시각화는 보통 전체 포인트 필요).
 *
 * 모바일이 실시간으로 포인트를 올리는 동안 웹이 자동 반영되도록 5초 polling.
 * 탭 백그라운드일 땐 안 돎 (`refetchIntervalInBackground: false`) — 불필요한 트래픽 차단.
 * 세션 완료 후엔 새 포인트가 안 들어오지만 단순함 위해 polling 유지 (트래픽 미미).
 */
export function useMeasurementPoints(sessionId: UUID | null, pageSize = 500) {
  return useQuery({
    queryKey: ['measurement-points', sessionId, pageSize] as const,
    queryFn: () =>
      measurementSessionApi.listPoints(sessionId as UUID, { page: 1, page_size: pageSize }),
    enabled: !!sessionId,
    retry: false,
    refetchInterval: sessionId ? 5_000 : false,
    refetchIntervalInBackground: false,
  });
}

/** §10.5 — 세션에서 발견된 고유 AP 목록 (envelope 없이 list 직접 반환). */
export function useDetectedAps(sessionId: UUID | null) {
  return useQuery({
    queryKey: ['detected-aps', sessionId] as const,
    queryFn: () => measurementSessionApi.listDetectedAps(sessionId as UUID),
    enabled: !!sessionId,
    retry: false,
  });
}

/**
 * GP regression 으로 측정점 → 도면 전체 dense RSSI 히트맵 추정 (#81).
 * 측정점이 충분치 않거나 백엔드가 추정 실패하면 404/422 → 빈 상태로 fallback.
 * resolution_m: 0.1~2.0. 기본 0.5 (백엔드 기본값과 동일).
 */
/** method:
 *  - 'gp_only': "실측 히트맵" 의미 — 측정값만 GP 보간
 *  - 'residual_kriging': "통합 분석" 의미 — sim prior + residual GP
 *  - 'auto' (생략): backend 가 알아서 (sim 있으면 residual, 없으면 gp_only)
 *
 *  같은 sessionId 라도 method 가 다르면 queryKey 분리 → 병렬 fetch + 독립 cache.
 */
export function useEstimatedCoverage(
  sessionId: UUID | null,
  options?: { resolutionM?: number; method?: 'gp_only' | 'residual_kriging' | 'auto' },
) {
  const resolutionM = options?.resolutionM ?? 0.5;
  const method = options?.method ?? 'auto';
  return useQuery({
    queryKey: ['estimated-coverage', sessionId, resolutionM, method] as const,
    queryFn: () =>
      measurementSessionApi.getEstimatedCoverage(sessionId as UUID, {
        resolution_m: resolutionM,
        method,
      }),
    enabled: !!sessionId,
    retry: false,
    staleTime: 5 * 60_000,
  });
}
