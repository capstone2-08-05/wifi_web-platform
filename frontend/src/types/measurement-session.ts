import type { ISODateString, UUID } from './common';

// §10 실측 세션 / 포인트 — 백엔드 schemas/measurement.py 응답과 정합.

export type MeasurementSessionStatus = 'in_progress' | 'completed' | string;
export type MeasurementPurpose = 'calibration' | 'validation' | 'reference' | 'unknown';

export interface MeasurementSession {
  id: UUID;
  project_id: UUID;
  floor_id: UUID;
  scene_version_id: UUID | null;
  asset_id: UUID | null;
  measurement_type: string;
  measurement_purpose: MeasurementPurpose;
  status: MeasurementSessionStatus;
  created_at: ISODateString;
}

export interface FloorPosition {
  x: number;
  y: number;
  z: number;
}

export interface MeasurementPoint {
  id: UUID;
  session_id: UUID;
  client_point_id: string | null;
  batch_id: string | null;
  floor_position: FloorPosition;
  rssi_dbm: number | null;
  measurement_purpose: MeasurementPurpose | null;
  ap_bssid: string | null;
  ap_ssid: string | null;
  channel: number | null;
  frequency_mhz: number | null;
  timestamp_at_point: ISODateString | null;
  ar_tracking_state: string | null;
  ar_confidence: number | null;
  step_index: number | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateString;
}

export interface DetectedAp {
  ap_bssid: string;
  ap_ssid: string | null;
  channel: number | null;
  frequency_mhz: number | null;
  point_count: number;
  rssi_avg: number | null;
  rssi_min: number | null;
  rssi_max: number | null;
}

// §10.X (#81) — GP regression 으로 측정점 → 도면 전체 dense RSSI 추정.
// 백엔드 EstimatedCoverageResponseDTO 와 정합.

export interface FloorBounds {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

export interface EstimatedRssiRange {
  min: number;
  max: number;
  mean: number;
}

/** 'gp_only': 측정점만으로 GP — sparse 면 prior mean 으로 단조롭게 깔림.
 *  'residual_kriging': 최근 시뮬 grid 를 prior, GP 는 residual 만 보간 — 더 현실적. */
export type CoverageEstimationMethod = 'gp_only' | 'residual_kriging';

export interface EstimatedCoverage {
  heatmap_url: string;
  uncertainty_url: string;
  bounds: FloorBounds;
  grid_shape: [number, number]; // [H, W]
  grid_resolution_m: number;
  rssi_range: EstimatedRssiRange;
  uncertainty_max_db: number;
  input_point_count: number;
  kernel_repr: string;
  /** 추정 방식 — UI 가 "시뮬 기반 보정" vs "단순 GP" 구분 표시. */
  method?: CoverageEstimationMethod;
}
