import type { ISODateString, UUID } from './common';

// 백엔드 §13 RF Run / RF Map DTO 와 매칭 (app/schemas/rf_run.py, rf_map.py).

export type RfRunStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | string;

export interface RfRunCreate {
  scene_version_id: UUID;
  run_type?: string;
  request_json?: Record<string, unknown>;
}

export interface RfRun {
  id: UUID;
  project_id: UUID;
  floor_id: UUID;
  scene_version_id: UUID;
  run_type: string;
  status: RfRunStatus;
  request_json: Record<string, unknown>;
  metrics_json: Record<string, unknown>;
  created_at: ISODateString;
}

/** POST /rf-runs 응답 — RfRun + job_id. */
export interface RfRunCreated extends RfRun {
  job_id: UUID;
}

export interface RfMap {
  id: UUID;
  rf_run_id: UUID;
  map_type: string;
  resolution_cm: number;
  storage_url: string;
  bounds_json: Record<string, unknown>;
  metrics_json: Record<string, unknown>;
  created_at: ISODateString;
}
