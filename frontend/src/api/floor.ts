import { api } from './client';
import type { UUID } from '@/types/common';
import type {
  CreateFloorRequest,
  Floor,
  FloorListResponse,
  UpdateFloorRequest,
} from '@/types/floor';

export const floorApi = {
  listByProject: (projectId: UUID) =>
    api.get<FloorListResponse>(`/projects/${projectId}/floors`).then((r) => r.data.items),

  create: (projectId: UUID, body: CreateFloorRequest) =>
    api.post<Floor>(`/projects/${projectId}/floors`, body).then((r) => r.data),

  get: (floorId: UUID) => api.get<Floor>(`/floors/${floorId}`).then((r) => r.data),

  update: (floorId: UUID, body: UpdateFloorRequest) =>
    api.patch<Floor>(`/floors/${floorId}`, body).then((r) => r.data),

  remove: (floorId: UUID) => api.delete<void>(`/floors/${floorId}`).then((r) => r.data),
};
