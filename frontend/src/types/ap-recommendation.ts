import type { ISODateString, UUID } from './common';

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
  evaluation_bboxes?: MeterBBox[];
  priority_zones?: Array<MeterBBox & { label?: string | null; weight?: number }>;
  excluded_zones?: MeterBBox[];
  default_unzoned_weight?: number;
  step_m?: number;
  existing_aps?: ExistingAp[];
  calibration_run_id?: UUID | null;
  calibration_policy?: 'transfer_only' | 'best_params_only' | 'combined';
  recommendation_mode?: 'add' | 'replace';
  replace_target_ap_id?: string | null;
  candidate_tx_power_dbm?: number;
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
  prediction_points?: ApRecommendationPredictionPoint[];
}

export interface ApRecommendationPredictionPoint {
  x: number;
  y: number;
  rssi_dbm: number;
  baseline_rssi_dbm?: number | null;
  weight?: number;
}

export interface ApRecommendationCalibrationInfo {
  method: string;
  policy: 'transfer_only' | 'best_params_only' | 'combined';
  slope: number;
  intercept_db: number;
  transfer_applied: boolean;
  best_params_applied: boolean;
  residual_used: boolean;
  calibration_run_id?: UUID | null;
}

/** POST /ap-recommendation 응답 (backend ApRecommendationResponse). */
export interface ApRecommendationResponse {
  run_id?: UUID | null;
  recommendations: ApRecommendationItem[];
  status: string;
  candidates_evaluated: number;
  eval_points_count?: number | null;
  weighted_eval_points_count?: number | null;
  calibration_applied?: boolean;
  calibration?: ApRecommendationCalibrationInfo | null;
  score_weights?: Record<string, number>;
  created_at?: ISODateString | null;
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
  prediction_points: ApRecommendationPredictionPoint[];
}

export interface ApRecommendationRun {
  id: UUID;
  project_id: UUID;
  floor_id: UUID;
  scene_version_id: UUID;
  calibration_run_id?: UUID | null;
  status: string;
  request_json: ApRecommendationRequest;
  input_areas_json: {
    candidate_bboxes?: MeterBBox[];
    evaluation_bboxes?: MeterBBox[];
    priority_zones?: Array<MeterBBox & { label?: string | null; weight?: number }>;
    excluded_zones?: MeterBBox[];
    default_unzoned_weight?: number;
  };
  existing_aps_json: ExistingAp[];
  calibration_json: ApRecommendationCalibrationInfo | Record<string, unknown>;
  score_weights_json: Record<string, number>;
  candidates_evaluated: number;
  eval_points_count?: number | null;
  weighted_eval_points_count?: number | null;
  recommendations: ApRecommendationItem[];
  created_at: ISODateString;
}
