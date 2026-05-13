import type { ISODateString, UUID } from './common';

export interface PatchLog {
  id: UUID;
  scene_version_id: UUID;
  created_by: UUID | null;
  patch_type: string;
  target_type: 'room' | 'wall' | 'opening' | 'object' | string;
  target_id: UUID;
  patch_json: Record<string, unknown>;
  created_at: ISODateString;
}
