import type { ISODateString, UUID } from './common';

// 백엔드 §8 확정본 (rooms/walls/openings/objects) 도메인.
// Draft 구조와 거의 동일하지만 scene_draft_id 대신 scene_version_id 를 가진다.
// 변경 시 자동으로 patch_log 기록됨 (§9).

export interface SceneVersionWall {
  id: UUID;
  scene_version_id: UUID;
  wall_role: string;
  thickness_m: string;
  height_m: string | null;
  material_label: string | null;
  confidence: string | null;
  source_method: string | null;
  centerline_geom?: Record<string, unknown> | null;
  polygon_geom?: Record<string, unknown> | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}

export interface SceneVersionRoom {
  id: UUID;
  scene_version_id: UUID;
  room_name: string | null;
  room_type: string | null;
  confidence: string | null;
  source_method: string | null;
  polygon_geom?: Record<string, unknown> | null;
  centroid_geom?: Record<string, unknown> | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}

export interface SceneVersionOpening {
  id: UUID;
  scene_version_id: UUID;
  wall_id: UUID | null;
  opening_type: string;
  width_m: string;
  height_m: string;
  sill_height_m: string | null;
  confidence: string | null;
  source_method: string | null;
  line_geom?: Record<string, unknown> | null;
  polygon_geom?: Record<string, unknown> | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}

export interface SceneVersionObject {
  id: UUID;
  scene_version_id: UUID;
  object_type: string;
  confidence: string | null;
  source_method: string | null;
  point_geom?: Record<string, unknown> | null;
  z_m: string | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}
