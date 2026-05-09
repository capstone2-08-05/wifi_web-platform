import type { ISODateString, UUID } from './common';

export type SceneDraftStatus = 'draft' | 'promoted' | 'archived';
export type SceneSourceMode = 'floorplan_image' | 'manual' | string;

export interface DraftWall {
  id: UUID;
  scene_draft_id: UUID;
  start: { x: number; y: number };
  end: { x: number; y: number };
  thickness?: number;
  material_id?: UUID | null;
  metadata_json?: Record<string, unknown>;
}

export interface DraftOpening {
  id: UUID;
  scene_draft_id: UUID;
  wall_id?: UUID | null;
  type?: 'door' | 'window' | string;
  position?: { x: number; y: number };
  width?: number;
  metadata_json?: Record<string, unknown>;
}

export interface DraftRoom {
  id: UUID;
  scene_draft_id: UUID;
  room_type?: string;
  polygon?: Array<{ x: number; y: number }>;
  metadata_json?: Record<string, unknown>;
}

export interface DraftObject {
  id: UUID;
  scene_draft_id: UUID;
  object_type?: string;
  bbox?: { x: number; y: number; w: number; h: number; rotation?: number };
  material_id?: UUID | null;
  metadata_json?: Record<string, unknown>;
}

export interface SceneDraft {
  id: UUID;
  project_id: UUID;
  floor_id: UUID;
  source_mode: SceneSourceMode;
  source_asset_id: UUID | null;
  source_method: string;
  summary_json: Record<string, unknown>;
  status: SceneDraftStatus;
  rooms: DraftRoom[];
  walls: DraftWall[];
  openings: DraftOpening[];
  objects: DraftObject[];
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface AnalyzeFloorplanResponse {
  status: 'ok' | string;
  scene_draft_id: UUID;
  fileId: UUID;
  savedPath: string;
  scene: {
    scale_ratio: number;
    walls: DraftWall[];
    openings: DraftOpening[];
    rooms: DraftRoom[];
    topology: Record<string, unknown>;
    objects: DraftObject[];
  };
}

export interface SceneVersion {
  id: UUID;
  floor_id: UUID;
  source_draft_id: UUID;
  created_by: UUID | null;
  version_no: number;
  is_current: boolean;
  preview_2d_url: string | null;
  preview_3d_url: string | null;
  parametric_scene_url: string | null;
  created_at: ISODateString;
  rooms?: DraftRoom[];
  walls?: DraftWall[];
  openings?: DraftOpening[];
  objects?: DraftObject[];
}

export interface PromoteRequest {
  version_no: number;
  is_current: boolean;
}
