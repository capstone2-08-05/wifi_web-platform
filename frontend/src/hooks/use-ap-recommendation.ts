import { useMutation } from '@tanstack/react-query';
import { apRecommendationApi } from '@/api/ap-recommendation';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { ApRecommendationRequest } from '@/types/ap-recommendation';

/** POST /ap-recommendation — AP 최적 배치 추천. */
export function useApRecommendation() {
  return useMutation({
    mutationFn: (body: ApRecommendationRequest) => apRecommendationApi.recommend(body),
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error(
        'AP 배치 추천 실패',
        e?.message ?? '잠시 후 다시 시도해주세요.',
      );
    },
  });
}
