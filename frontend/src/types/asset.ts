import type { ISODateString, UUID } from './common';

export type AssetType = 'floorplan' | 'photo' | 'document' | string;

export interface Asset {
  id: UUID;
  floor_id: UUID;
  uploaded_by: UUID | null;
  asset_type: AssetType;
  source_format: string;
  storage_url: string;
  mime_type: string;
  file_size_bytes: number;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}

export interface UploadAssetParams {
  file: File;
  asset_type: AssetType;
}

/** Asset list response is a plain `{ items }` envelope (not paginated). */
export interface AssetListResponse {
  items: Asset[];
}
