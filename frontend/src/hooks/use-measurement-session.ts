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
