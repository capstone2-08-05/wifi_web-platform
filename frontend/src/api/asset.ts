import { api } from './client';
import type { UUID } from '@/types/common';
import type { Asset, AssetType, UploadAssetParams } from '@/types/asset';

export const assetApi = {
  // §5.1 POST /floors/{floor_id}/assets (multipart)
  upload: (floorId: UUID, { file, asset_type }: UploadAssetParams) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('asset_type', asset_type);
    return api
      .post<Asset>(`/floors/${floorId}/assets`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data);
  },

  // §5.2 GET /floors/{floor_id}/assets  — 백엔드가 plain array 반환
  listByFloor: (floorId: UUID, params?: { asset_type?: AssetType }) =>
    api.get<Asset[]>(`/floors/${floorId}/assets`, { params }).then((r) => r.data),

  // §5.3 GET /assets/{asset_id}
  get: (assetId: UUID) => api.get<Asset>(`/assets/${assetId}`).then((r) => r.data),

  // §5.3 DELETE /assets/{asset_id}
  remove: (assetId: UUID) => api.delete<void>(`/assets/${assetId}`).then((r) => r.data),
};
