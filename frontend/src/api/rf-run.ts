import { api } from './client';
import type { UUID } from '@/types/common';
import type { RfMap, RfRun, RfRunCreate, RfRunCreated } from '@/types/rf';

export const rfRunApi = {
  // §13.1 POST /rf-runs — 비동기 시뮬레이션 큐 등록 (HTTP 202)
  create: (body: RfRunCreate) =>
    api.post<RfRunCreated>('/rf-runs', body).then((r) => r.data),

  // §13.2 GET /rf-runs/{rf_run_id} — 상태/메트릭 폴링
  get: (id: UUID) => api.get<RfRun>(`/rf-runs/${id}`).then((r) => r.data),

  // §13.3 GET /rf-runs/{rf_run_id}/maps — 완료 후 RF 맵 목록
  listMaps: (id: UUID) =>
    api.get<RfMap[]>(`/rf-runs/${id}/maps`).then((r) => r.data),
};
