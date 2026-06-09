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

/**
 * GET /assets/{id}/download-url — S3 presigned HTTPS URL.
 *
 * Asset.storage_url 이 s3:// URI 로 바뀐 뒤로 <img src>·SVG <image href> 에
 * 직접 못 박음. 이 훅이 presigned URL 을 받아온다.
 *
 * 캐싱: 백엔드 기본 TTL = 3600s (RF_PRESIGNED_URL_EXPIRES_SECONDS).
 * staleTime 을 그보다 5분 짧게 잡아 만료 직전 자동 재발급.
 */
const PRESIGN_STALE_MS = 55 * 60_000; // 55분
const PRESIGN_GC_MS = 60 * 60_000; // 60분

export function useAssetDownloadUrl(assetId: UUID | null) {
  return useQuery({
    queryKey: ['asset-download-url', assetId] as const,
    queryFn: () => assetApi.getDownloadUrl(assetId as UUID),
    enabled: !!assetId,
    staleTime: PRESIGN_STALE_MS,
    gcTime: PRESIGN_GC_MS,
  });
}
