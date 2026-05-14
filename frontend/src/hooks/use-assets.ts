import { useQuery } from '@tanstack/react-query';
import { assetApi } from '@/api/asset';
import type { UUID } from '@/types/common';
import type { AssetType } from '@/types/asset';

/** §11 GET /assets/{id} — 단건 (도면 원본 이미지 등). */
export function useAsset(assetId: UUID | null) {
  return useQuery({
    queryKey: ['asset', assetId] as const,
    queryFn: () => assetApi.get(assetId as UUID),
    enabled: !!assetId,
    staleTime: 5 * 60_000,
  });
}

/** §11 GET /floors/{id}/assets — 층의 자산 목록. */
export function useFloorAssets(floorId: UUID | null, assetType?: AssetType) {
  return useQuery({
    queryKey: ['floor-assets', floorId, assetType ?? null] as const,
    queryFn: () => assetApi.listByFloor(floorId as UUID, assetType ? { asset_type: assetType } : undefined),
    enabled: !!floorId,
    staleTime: 60_000,
  });
}
