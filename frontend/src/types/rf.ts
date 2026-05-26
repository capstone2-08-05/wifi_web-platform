import type { ISODateString, UUID } from './common';

// 백엔드 §13 RF Run / RF Map DTO 와 매칭 (app/schemas/rf/rf_run.py, app/schemas/rf/rf_map.py).

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
  /**
   * 해당 scene_version 의 최신 완료된 CalibrationRun 보정값을 시뮬에 반영할지 (#88).
   * 미지정 시 백엔드 default=true (보정 자동 적용). false 면 raw 시뮬 (비교용).
   */
  apply_calibration?: boolean;
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
  /** s3:// URI (raw). 프론트에서 직접 사용 X — `url` (백엔드가 자동 발급한 presigned) 사용. */
  storage_url: string;
  /** storage_url 이 s3:// 면 백엔드가 발급한 presigned GET URL. <img src> 로 바로 사용. */
  url?: string | null;
  bounds_json: Record<string, unknown>;
  metrics_json: Record<string, unknown>;
  created_at: ISODateString;
}

// ============================================
// §13.4 GET /rf-jobs/{job_id} — Job 폴링 응답.
// heatmap/radio_map URI 는 presigned HTTPS URL (TTL 적용) 로 함께 반환.
// ============================================

export interface RfJobError {
  backend_code: string;
  container_code: string | null;
  stage: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
}

export interface RfJobOutputUri {
  s3_uri: string;
  /** presigned HTTPS URL — 만료되면 null 일 수 있음. */
  url: string | null;
}

export interface RfJob {
  job_id: UUID;
  rf_run_id: UUID | null;
  status: RfRunStatus;
  started_at: ISODateString | null;
  finished_at: ISODateString | null;
  output_prefix: string | null;
  result: Record<string, unknown> | null;
  heatmap: RfJobOutputUri | null;
  radio_map: RfJobOutputUri | null;
  error: RfJobError | null;
}
