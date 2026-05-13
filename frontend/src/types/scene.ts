import type { ISODateString, UUID } from './common';

export type SceneDraftStatus = 'draft' | 'promoted' | 'archived';
export type SceneSourceMode = 'floorplan_image' | 'manual' | string;

// ============================================
// Draft child entities (GET /scene-drafts/{id})
// 백엔드 SceneDraftDetailResponse 의 nested 응답 모양과 일치.
// Decimal 필드는 pydantic v2 가 JSON 직렬화 시 문자열로 내려보냄.
// 도형은 현재 응답에 직접 노출되지 않음 — metadata_json.raw 에 보존 (백엔드 합의 사항).
// ============================================

export interface DraftRoom {
  id: UUID;
  scene_draft_id: UUID;
  room_name: string | null;
  room_type: string | null;
  confidence: string | null;
  source_method: string | null;
  polygon_geom?: Record<string, unknown> | null;
  centroid_geom?: Record<string, unknown> | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}

export interface DraftWall {
  id: UUID;
  scene_draft_id: UUID;
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

export interface DraftOpening {
  id: UUID;
  scene_draft_id: UUID;
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

export interface DraftObject {
  id: UUID;
  scene_draft_id: UUID;
  object_type: string;
  confidence: string | null;
  source_method: string | null;
  point_geom?: Record<string, unknown> | null;
  z_m: string | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}

// ============================================
// Scene Draft  §6
// 목록(§6.3)과 단건(§6.2) 응답 모양이 다름:
//  - SceneDraftSummary: 메타만 (rooms/walls/openings/objects 없음)
//  - SceneDraft (detail): 자식 배열 포함
// ============================================

export interface SceneDraftSummary {
  id: UUID;
  project_id: UUID;
  floor_id: UUID;
  source_mode: SceneSourceMode;
  source_asset_id: UUID | null;
  source_method: string | null;
  status: SceneDraftStatus;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface SceneDraft extends SceneDraftSummary {
  summary_json: Record<string, unknown>;
  rooms: DraftRoom[];
  walls: DraftWall[];
  openings: DraftOpening[];
  objects: DraftObject[];
}

// ============================================
// Raw scene returned by analyze endpoints (immediate response)
// fusion_service 가 내려주는 픽셀 좌표 모양 (DB 저장 전 원본).
// §6.1 POST /upload/floorplan/analyze, §6.1.1 POST /assets/{id}/analyze
// ============================================

export interface SceneWall {
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  thickness?: number;
  height?: number;
  role?: string;
  material?: string;
}

export interface SceneOpening {
  id: string;
  type: 'door' | 'window' | string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  wall_ref?: string | null;
}

export interface SceneRoom {
  id: string;
  points: Array<[number, number]>;
  center: [number, number];
  area: number;
}

export interface SceneObjectRaw {
  id: string;
  class_name?: string;
  score?: number;
  bbox_xyxy?: [number, number, number, number];
  [key: string]: unknown;
}

export interface AnalyzedScene {
  scale_ratio: number;
  walls: SceneWall[];
  openings: SceneOpening[];
  rooms: SceneRoom[];
  topology: Record<string, unknown>;
  objects: SceneObjectRaw[];
  scene_draft_id?: string | null;
  scene_version?: string;
  units?: string;
  sourceType?: string;
}

// ============================================
// 분석 호출 응답 (비동기 Job)
// 백엔드가 동기 → 비동기 Job 으로 전환됨. POST 즉시 202 + job_id 반환.
// 결과는 GET /floorplan-jobs/{job_id} 로 폴링.
// ============================================

import type { JobStatus } from './job';

export interface SubmitFloorplanJobResponse {
  status: 'submitted' | string;
  job_id: UUID;
  project_id: UUID | null;
  floor_id: UUID | null;
  job_status: JobStatus;
  sagemaker_inference_id: string | null;
  poll_url: string;
}

// §6.1 POST /upload/floorplan/analyze
export interface AnalyzeFloorplanResponse extends SubmitFloorplanJobResponse {
  fileId: string;
  savedPath: string;
}

// §6.1.1 POST /assets/{asset_id}/analyze
export interface AnalyzeFromAssetResponse extends SubmitFloorplanJobResponse {
  asset_id: UUID;
}

// ============================================
// Scene Version  §7  (v0.2 명세 반영)
// preview_3d_url / parametric_scene_url 제거됨.
// preview_2d_url → render_scene_url 로 명칭 통일.
// rf_scene_url, artifacts_json 추가.
// ============================================

export interface SceneVersion {
  id: UUID;
  project_id: UUID;
  floor_id: UUID;
  source_draft_id: UUID;
  version_no: number;
  is_current: boolean;
  source_mode: SceneSourceMode;
  source_method: string | null;
  source_asset_id: UUID | null;
  render_scene_url: string | null;
  rf_scene_url: string | null;
  artifacts_json: Record<string, unknown>;
  created_by: string | null;
  created_at: ISODateString;
  // §7.2 detail 응답에서만 포함
  rooms?: DraftRoom[];
  walls?: DraftWall[];
  openings?: DraftOpening[];
  objects?: DraftObject[];
}

export interface PromoteRequest {
  version_no: number;
  is_current: boolean;
}

// ============================================
// 캔버스 선택 상태 (UI 전용)
// ============================================

export type DraftEntityKind = 'wall' | 'room' | 'opening' | 'object';

export interface SelectedEntityRef {
  kind: DraftEntityKind;
  id: UUID;
}

export type SelectedEntityResolved =
  | { kind: 'wall'; data: DraftWall }
  | { kind: 'room'; data: DraftRoom }
  | { kind: 'opening'; data: DraftOpening }
  | { kind: 'object'; data: DraftObject };
