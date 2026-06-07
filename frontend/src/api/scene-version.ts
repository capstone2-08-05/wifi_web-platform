import { api } from './client';
import type { UUID } from '@/types/common';
import type { PromoteRequest, SceneVersion } from '@/types/scene';

export const sceneVersionApi = {
  promote: (draftId: UUID, body: PromoteRequest) =>
    api.post<SceneVersion>(`/scene-drafts/${draftId}/promote`, body).then((r) => r.data),

  get: (versionId: UUID) =>
    api.get<SceneVersion>(`/scene-versions/${versionId}`).then((r) => r.data),

  listByFloor: (floorId: UUID, params?: { is_current?: boolean }) =>
    api
      .get<SceneVersion[]>(`/floors/${floorId}/scene-versions`, { params })
      .then((r) => r.data),

  setCurrent: (versionId: UUID) =>
    api
      .patch<SceneVersion>(`/scene-versions/${versionId}/set-current`)
      .then((r) => r.data),

  remove: (versionId: UUID) =>
    api.delete<void>(`/scene-versions/${versionId}`).then((r) => r.data),

  rescale: (versionId: UUID, body: { factor: number; scale_source?: string }) =>
    api.post<SceneVersion>(`/scene-versions/${versionId}/rescale`, body).then((r) => r.data),
};
