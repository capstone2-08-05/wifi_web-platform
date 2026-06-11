import { api } from './client';
import type { Paginated, UUID } from '@/types/common';
import type {
  ApRecommendationRequest,
  ApRecommendationResponse,
  ApRecommendationRun,
  ApRecommendationVerifyCandidateRequest,
  ApRecommendationVerifyCandidateResponse,
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

  /** POST /ap-recommendation/{run_id}/verify-candidate — 선택 후보 1개 Sionna 검증. */
  verifyCandidate: (runId: UUID, body: ApRecommendationVerifyCandidateRequest) =>
    api
      .post<ApRecommendationVerifyCandidateResponse>(
        `/ap-recommendation/${runId}/verify-candidate`,
        body,
      )
      .then((r) => r.data),
};
