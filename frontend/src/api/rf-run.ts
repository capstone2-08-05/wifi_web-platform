import { api } from './client';
import type { Paginated, UUID } from '@/types/common';
import type { RfJob, RfMap, RfRun, RfRunCreate, RfRunCreated, RfRunStatus } from '@/types/rf';

export interface ListRfRunsParams {
  status?: RfRunStatus;
  page?: number;
  page_size?: number;
}

export const rfRunApi = {
  // §13.1 POST /rf-runs — 비동기 시뮬레이션 큐 등록 (HTTP 202)
  create: (body: RfRunCreate) =>
    api.post<RfRunCreated>('/rf-runs', body).then((r) => r.data),

  // §13.2 GET /rf-runs/{rf_run_id} — 상태/메트릭 폴링
  get: (id: UUID) => api.get<RfRun>(`/rf-runs/${id}`).then((r) => r.data),

  // §13.3 GET /rf-runs/{rf_run_id}/maps — 완료 후 RF 맵 목록 (storage_url 은 s3:// URI)
  listMaps: (id: UUID) =>
    api.get<RfMap[]>(`/rf-runs/${id}/maps`).then((r) => r.data),

  // GET /floors/{floor_id}/rf-runs — 층의 RF Run 목록 (created_at desc, 페이지네이션 + status 필터)
  listByFloor: (floorId: UUID, params?: ListRfRunsParams) =>
    api
      .get<Paginated<RfRun>>(`/floors/${floorId}/rf-runs`, { params })
      .then((r) => r.data),

  // DELETE /rf-runs/{rf_run_id}
  delete: (id: UUID) => api.delete(`/rf-runs/${id}`),
};

export const rfJobApi = {
  // §13.4 GET /rf-jobs/{job_id} — Job 상태 + presigned heatmap/radio_map URL
  get: (jobId: UUID) => api.get<RfJob>(`/rf-jobs/${jobId}`).then((r) => r.data),
};
