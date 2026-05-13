import { api } from './client';
import type { UUID } from '@/types/common';
import type { MaterialHypothesis } from '@/types/material-hypothesis';

export const materialHypothesisApi = {
  // §12.3 GET /walls/{wall_id}/material-hypotheses — 벽의 재질 후보 목록
  listForWall: (wallId: UUID) =>
    api
      .get<MaterialHypothesis[]>(`/walls/${wallId}/material-hypotheses`)
      .then((r) => r.data),

  // §12.3 POST /material-hypotheses/{id}/select — 후보 확정
  select: (hypothesisId: UUID) =>
    api
      .post<MaterialHypothesis>(`/material-hypotheses/${hypothesisId}/select`)
      .then((r) => r.data),
};
