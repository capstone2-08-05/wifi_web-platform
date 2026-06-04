import { api } from './client';
import type { Paginated, UUID } from '@/types/common';
import type {
  ApRecommendationRequest,
  ApRecommendationResponse,
  ApRecommendationRun,
} from '@/types/ap-recommendation';

export const apRecommendationApi = {
  /** POST /ap-recommendation — Grid Search 기반 AP 최적 위치 추천. */
  recommend: (body: ApRecommendationRequest) =>
    api.post<ApRecommendationResponse>('/ap-recommendation', body).then((r) => r.data),

  listRuns: (sceneVersionId: UUID, params?: { page?: number; page_size?: number }) =>
    api
      .get<Paginated<ApRecommendationRun>>('/ap-recommendation', {
        params: {
          scene_version_id: sceneVersionId,
          page: params?.page,
          page_size: params?.page_size,
        },
      })
      .then((r) => r.data),

  getRun: (runId: UUID) =>
    api.get<ApRecommendationRun>(`/ap-recommendation/${runId}`).then((r) => r.data),
};
