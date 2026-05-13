import type { ISODateString, UUID } from './common';

export type AssetType = 'floorplan' | 'photo' | 'document' | string;

// §5.1 응답 (POST /floors/{floor_id}/assets) 및 §5.3 GET /assets/{id}
export interface Asset {
  id: UUID;
  floor_id: UUID | null;
  uploaded_by: UUID | null;
  asset_type: AssetType;
  source_format: string | null;
  storage_url: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}

export interface UploadAssetParams {
  file: File;
  asset_type: AssetType;
}
