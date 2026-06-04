import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apRecommendationApi } from '@/api/ap-recommendation';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';
import type { ApRecommendationRequest } from '@/types/ap-recommendation';

/** POST /ap-recommendation — AP 최적 배치 추천. */
export function useApRecommendation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ApRecommendationRequest) => apRecommendationApi.recommend(body),
    onSuccess: (result, body) => {
      qc.invalidateQueries({
        queryKey: ['ap-recommendation-runs', body.scene_version_id],
      });
      if (result.run_id) {
        qc.invalidateQueries({ queryKey: ['ap-recommendation-run', result.run_id] });
      }
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error(
        'AP 배치 추천 실패',
        e?.message ?? '잠시 후 다시 시도해주세요.',
      );
    },
  });
}

export function useApRecommendationRuns(sceneVersionId: UUID | null, pageSize = 20) {
  return useQuery({
    queryKey: ['ap-recommendation-runs', sceneVersionId, pageSize] as const,
    queryFn: () =>
      apRecommendationApi.listRuns(sceneVersionId as UUID, {
        page: 1,
        page_size: pageSize,
      }),
    enabled: !!sceneVersionId,
    retry: false,
  });
}

export function useApRecommendationRun(runId: UUID | null) {
  return useQuery({
    queryKey: ['ap-recommendation-run', runId] as const,
    queryFn: () => apRecommendationApi.getRun(runId as UUID),
    enabled: !!runId,
    retry: false,
  });
}
