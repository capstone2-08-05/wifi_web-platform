import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { materialHypothesisApi } from '@/api/material-hypothesis';
import type { HttpError } from '@/api/client';
import type { UUID } from '@/types/common';
import { toast } from '@/stores/toast-store';

/**
 * §12.3 — 벽의 재질 후보 목록.
 *
 * 백엔드 라우터가 /walls/{wall_id} 기준이라 *확정본 Wall* (§8) 의 id 가 필요할 수 있음.
 * Draft 단계에서 호출하면 빈 배열 또는 404 일 가능성 — 컴포넌트에서 graceful 처리.
 */
export function useWallMaterialHypotheses(wallId: UUID | null) {
  return useQuery({
    queryKey: ['material-hypotheses', 'wall', wallId] as const,
    queryFn: () => materialHypothesisApi.listForWall(wallId as UUID),
    enabled: !!wallId,
    // 404 / 빈 응답은 정상으로 취급
    retry: false,
    staleTime: 30_000,
  });
}

/** §12.3 — 재질 후보 확정. */
export function useSelectMaterialHypothesis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (hypothesisId: UUID) => materialHypothesisApi.select(hypothesisId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['material-hypotheses'] });
      qc.invalidateQueries({ queryKey: ['scene-draft'] });
      qc.invalidateQueries({ queryKey: ['scene-version'] });
      toast.success('재질 후보가 적용되었습니다');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('재질 후보 적용 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}
