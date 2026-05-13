import { api } from './client';
import type { Paginated, UUID } from '@/types/common';
import type { PatchLog } from '@/types/patch-log';

export const patchLogApi = {
  // §9.1 GET /scene-versions/{version_id}/patch-logs
  listByVersion: (
    versionId: UUID,
    params?: {
      target_type?: 'room' | 'wall' | 'opening' | 'object';
      page?: number;
      page_size?: number;
    },
  ) =>
    api
      .get<Paginated<PatchLog>>(`/scene-versions/${versionId}/patch-logs`, { params })
      .then((r) => r.data),
};
