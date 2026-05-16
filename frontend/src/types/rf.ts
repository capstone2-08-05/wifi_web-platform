import type { ISODateString, UUID } from './common';

// 백엔드 §13 RF Run / RF Map DTO 와 매칭 (app/schemas/rf_run.py, rf_map.py).

export type RfRunStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | string;

/** §13.1 RF 시뮬레이션 access point. 1~8 개. */
export interface AccessPointDTO {
  id: string;
  x_m: number;
  y_m: number;
  z_m: number;
}

/** §13.1 RF 시뮬레이션 파라미터. SageMaker 입력. */
export interface RfSimulationParams {
  frequency_hz: number;
  tx_power_dbm: number;
  resolution_m?: number;
  measurement_plane_z_m?: number;
  max_depth?: number;
  samples_per_tx?: number;
  seed?: number;
}

export interface RfRunCreate {
  scene_version_id: UUID;
  run_type?: string;
  /** access_points + simulation 둘 다 있으면 SageMaker 실제 호출. */
  access_points?: AccessPointDTO[];
  simulation?: RfSimulationParams;
  metadata?: Record<string, unknown>;
  /** Legacy 호환 (deprecated). */
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
  /** storage_url 이 s3:// 면 백엔드가 발급한 presigned GET URL. <img src> 로 바로 사용. */
  url?: string | null;
  bounds_json: Record<string, unknown>;
  metrics_json: Record<string, unknown>;
  created_at: ISODateString;
}
