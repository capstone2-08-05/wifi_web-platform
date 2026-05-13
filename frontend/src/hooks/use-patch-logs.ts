import { useQuery } from '@tanstack/react-query';
import { patchLogApi } from '@/api/patch-log';
import type { UUID } from '@/types/common';

/**
 * §9.1 — Scene Version 의 수정 이력.
 * Draft 단계 변경은 안 쌓이고, 확정본 Room/Wall/Opening/Object PATCH 시 자동 기록됨.
 */
export function useVersionPatchLogs(
  versionId: UUID | null,
  params?: {
    target_type?: 'room' | 'wall' | 'opening' | 'object';
    page?: number;
    page_size?: number;
  },
) {
  return useQuery({
    queryKey: ['patch-logs', versionId, params ?? {}] as const,
    queryFn: () => patchLogApi.listByVersion(versionId as UUID, params),
    enabled: !!versionId,
    staleTime: 30_000,
  });
}
