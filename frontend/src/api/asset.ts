import { api } from './client';
import type { UUID } from '@/types/common';
import type { Asset, AssetListResponse, AssetType, UploadAssetParams } from '@/types/asset';

export const assetApi = {
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

  listByFloor: (floorId: UUID, params?: { asset_type?: AssetType }) =>
    api
      .get<AssetListResponse>(`/floors/${floorId}/assets`, { params })
      .then((r) => r.data.items),

  get: (assetId: UUID) => api.get<Asset>(`/assets/${assetId}`).then((r) => r.data),

  remove: (assetId: UUID) => api.delete<void>(`/assets/${assetId}`).then((r) => r.data),
};
