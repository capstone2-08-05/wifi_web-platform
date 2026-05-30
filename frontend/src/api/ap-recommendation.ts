import { api } from './client';
import type {
  ApRecommendationRequest,
  ApRecommendationResponse,
} from '@/types/ap-recommendation';

export const apRecommendationApi = {
  /** POST /ap-recommendation — Grid Search 기반 AP 최적 위치 추천. */
  recommend: (body: ApRecommendationRequest) =>
    api.post<ApRecommendationResponse>('/ap-recommendation', body).then((r) => r.data),
};
