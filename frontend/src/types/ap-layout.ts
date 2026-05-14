import type { ISODateString, UUID } from './common';

// §14 AP 후보/배치 도메인.

export type ApCandidateType = 'auto' | 'manual' | string;

export interface ApCandidate {
  id: UUID;
  room_id: UUID | null;
  candidate_type: ApCandidateType;
  point_geom: Record<string, unknown> | null;
  z_m: number | null;
  score: number | null;
}

export interface ApCandidateGenerateRequest {
  rf_run_id: UUID;
  candidate_type?: ApCandidateType;
}

/** §14.1 POST /ap-candidates/generate Response (202 — job 큐). */
export interface ApCandidateGenerateResponse {
  job_id: UUID;
}

export interface ApLayout {
  id: UUID;
  rf_run_id: UUID;
  ap_name: string;
  vendor_model: string | null;
  point_geom: Record<string, unknown> | null;
  z_m: number | null;
  azimuth_deg: number | null;
  tilt_deg: number | null;
  power_dbm: number | null;
  channel_info_json: Record<string, unknown>;
  created_at: ISODateString;
}

export interface ApLayoutCreate {
  rf_run_id: UUID;
  ap_name: string;
  vendor_model?: string;
  point_geom: Record<string, unknown>;
  z_m?: number;
  azimuth_deg?: number;
  tilt_deg?: number;
  power_dbm?: number;
  channel_info_json?: Record<string, unknown>;
}
