import { api } from './client';
import type { UUID } from '@/types/common';
import type {
  ApCandidate,
  ApCandidateGenerateRequest,
  ApCandidateGenerateResponse,
  ApLayout,
  ApLayoutCreate,
} from '@/types/ap-layout';

type ItemsResponse<T> = T[] | { items?: T[] };

function itemsFromResponse<T>(data: ItemsResponse<T>): T[] {
  return Array.isArray(data) ? data : data.items ?? [];
}

export const apLayoutApi = {
  // §14.1 POST /ap-candidates/generate — Job 큐 등록, 202 + job_id
  generateCandidates: (body: ApCandidateGenerateRequest) =>
    api
      .post<ApCandidateGenerateResponse>('/ap-candidates/generate', body)
      .then((r) => r.data),

  // §14.2 GET /rf-runs/{rf_run_id}/ap-candidates
  listCandidates: (rfRunId: UUID) =>
    api
      .get<ItemsResponse<ApCandidate>>(`/rf-runs/${rfRunId}/ap-candidates`)
      .then((r) => itemsFromResponse(r.data)),

  // §14.3 POST /ap-layouts
  createLayout: (body: ApLayoutCreate) =>
    api.post<ApLayout>('/ap-layouts', body).then((r) => r.data),

  // §14.4 GET /rf-runs/{rf_run_id}/ap-layouts
  listLayouts: (rfRunId: UUID) =>
    api
      .get<ItemsResponse<ApLayout>>(`/rf-runs/${rfRunId}/ap-layouts`)
      .then((r) => itemsFromResponse(r.data)),

  // §14.4 GET /ap-layouts/{layout_id}
  getLayout: (layoutId: UUID) =>
    api.get<ApLayout>(`/ap-layouts/${layoutId}`).then((r) => r.data),

  // §14.4 PATCH /ap-layouts/{layout_id}
  patchLayout: (layoutId: UUID, body: Partial<ApLayoutCreate>) =>
    api.patch<ApLayout>(`/ap-layouts/${layoutId}`, body).then((r) => r.data),

  // §14.4 DELETE /ap-layouts/{layout_id}
  deleteLayout: (layoutId: UUID) =>
    api.delete<void>(`/ap-layouts/${layoutId}`).then((r) => r.data),
};
