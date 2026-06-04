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
  x_min?: number;
  x_max?: number;
  y_min?: number;
  y_max?: number;
  target_bboxes?: MeterBBox[];
  candidate_bboxes?: MeterBBox[];
  priority_zones?: Array<MeterBBox & { label?: string | null; weight?: number }>;
  excluded_zones?: MeterBBox[];
  step_m?: number;
  existing_aps?: ExistingAp[];
  calibration_run_id?: UUID | null;
  recommendation_mode?: 'add' | 'replace';
  coverage_threshold_dbm?: number;
  weak_zone_threshold_dbm?: number;
  shadow_threshold_dbm?: number;
  shadow_penalty?: number;
}

export interface MeterBBox {
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
}

/** POST /ap-recommendation 응답 내 단일 추천 항목. */
export interface ApRecommendationItem {
  rank: number;
  recommended_x: number;
  recommended_y: number;
  score: number;
  coverage_score?: number | null;
  coverage_ratio?: number | null;
  weak_zone_improvement_score?: number | null;
  weak_zone_improvement_db?: number | null;
  bottom_10_percent_score?: number | null;
  bottom_10_percent_rssi_dbm?: number | null;
  average_rssi_score?: number | null;
  average_rssi_dbm?: number | null;
  baseline_improvement_score?: number | null;
  baseline_improvement_db?: number | null;
}

export interface ApRecommendationCalibrationInfo {
  method: string;
  slope: number;
  intercept_db: number;
  residual_used: boolean;
  calibration_run_id?: UUID | null;
}

/** POST /ap-recommendation 응답 (backend ApRecommendationResponse). */
export interface ApRecommendationResponse {
  recommendations: ApRecommendationItem[];
  status: string;
  candidates_evaluated: number;
  eval_points_count?: number | null;
  weighted_eval_points_count?: number | null;
  calibration_applied?: boolean;
  calibration?: ApRecommendationCalibrationInfo | null;
  score_weights?: Record<string, number>;
}

/** UI 표시용. */
export interface ApRecommendationResult {
  rank: number;
  recommended_x: number;
  recommended_y: number;
  score: number;
  candidates_evaluated: number;
  coverage_score?: number | null;
  coverage_ratio?: number | null;
  weak_zone_improvement_score?: number | null;
  weak_zone_improvement_db?: number | null;
  bottom_10_percent_score?: number | null;
  bottom_10_percent_rssi_dbm?: number | null;
  average_rssi_score?: number | null;
  average_rssi_dbm?: number | null;
  baseline_improvement_score?: number | null;
  baseline_improvement_db?: number | null;
}
