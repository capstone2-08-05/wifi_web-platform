import type { UUID } from './common';

/** POST /ap-recommendation — existing_aps 항목. */
export interface ExistingAp {
  id: string;
  x_m: number;
  y_m: number;
  tx_power_dbm?: number;
}

/** POST /ap-recommendation 요청 본문 (backend ApRecommendationRequest). */
export interface ApRecommendationRequest {
  scene_version_id: UUID;
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
  step_m?: number;
  existing_aps?: ExistingAp[];
  calibration_run_id?: UUID | null;
  shadow_threshold_dbm?: number;
  shadow_penalty?: number;
}

/** POST /ap-recommendation 응답 (backend ApRecommendationResponse). */
export interface ApRecommendationResponse {
  recommended_x: number;
  recommended_y: number;
  score: number;
  status: string;
  candidates_evaluated: number;
}

/** UI 표시용 — 단일/복수 응답 모두 배열로 normalize. */
export interface ApRecommendationResult {
  rank: number;
  recommended_x: number;
  recommended_y: number;
  score: number;
  status: string;
  candidates_evaluated: number;
}
