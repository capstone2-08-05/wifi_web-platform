import type { ISODateString, UUID } from './common';

// §10 실측 세션 / 포인트 — 백엔드 schemas/measurement.py 응답과 정합.

export type MeasurementSessionStatus = 'in_progress' | 'completed' | string;

export interface MeasurementSession {
  id: UUID;
  project_id: UUID;
  floor_id: UUID;
  scene_version_id: UUID | null;
  asset_id: UUID | null;
  measurement_type: string;
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
