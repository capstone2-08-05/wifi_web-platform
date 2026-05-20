import { useQuery } from '@tanstack/react-query';
import { measurementSessionApi } from '@/api/measurement-session';
import type { UUID } from '@/types/common';

// §10.4 — 백엔드 GET 엔드포인트 구현 완료 (PR #77).

export function useFloorMeasurementSessions(floorId: UUID | null) {
  return useQuery({
    queryKey: ['measurement-sessions', floorId] as const,
    queryFn: () => measurementSessionApi.listByFloor(floorId as UUID),
    enabled: !!floorId,
    staleTime: 30_000,
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

/** 세션의 측정 포인트 — 페이지 1개로 한 번에 가져옴 (시각화는 보통 전체 포인트 필요). */
export function useMeasurementPoints(sessionId: UUID | null, pageSize = 500) {
  return useQuery({
    queryKey: ['measurement-points', sessionId, pageSize] as const,
    queryFn: () =>
      measurementSessionApi.listPoints(sessionId as UUID, { page: 1, page_size: pageSize }),
    enabled: !!sessionId,
    retry: false,
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
export function useEstimatedCoverage(sessionId: UUID | null, resolutionM = 0.5) {
  return useQuery({
    queryKey: ['estimated-coverage', sessionId, resolutionM] as const,
    queryFn: () =>
      measurementSessionApi.getEstimatedCoverage(sessionId as UUID, {
        resolution_m: resolutionM,
      }),
    enabled: !!sessionId,
    retry: false,
    staleTime: 5 * 60_000,
  });
}
