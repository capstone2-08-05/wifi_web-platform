import type { ISODateString, UUID } from './common';
import type { PhysicalAp, RfBackend, WifiBand } from './rf';

export type RecommendationMode = 'add' | 'replace' | 'relocate_all' | 'relocate_selected';
export type CombinePolicy = 'max' | 'prefer_5g_then_2g' | 'weighted';
export type ResidualMode = 'none' | 'weak' | 'full';

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
  priority_zones?: ApRecommendationZone[];
  excluded_zones?: MeterBBox[];
  default_unzoned_weight?: number;
  step_m?: number;
  existing_aps?: ExistingAp[];
  calibration_run_id?: UUID | null;
  calibration_policy?: 'transfer_only' | 'best_params_only' | 'combined';
  recommendation_mode?: RecommendationMode;
  replace_target_ap_id?: string | null;
  replace_target_ap_ids?: string[];
  fixed_ap_ids?: string[];
  movable_ap_ids?: string[];
  relocate_target_ap_ids?: string[];
  additional_ap_count?: number;
  target_total_aps?: number | null;
  candidate_tx_power_dbm?: number;
  coverage_threshold_dbm?: number;
  weak_zone_threshold_dbm?: number;
  shadow_threshold_dbm?: number;
  shadow_penalty?: number;
  n_recommendations?: number;
  n_aps?: number;
  /** Physical AP 구조. 있으면 existing_aps 보다 우선. */
  physical_aps?: PhysicalAp[];
  recommendation_unit?: 'physical_ap' | 'radio';
  target_bands?: WifiBand[];
  combine_policy?: CombinePolicy;
  residual_mode?: ResidualMode;
  weak_residual_weight?: number;
  verify_with_sionna?: boolean;
  verification_top_k?: number;
  verification_backend?: RfBackend;
}

/** 멀티 AP 세트 내 개별 AP 위치. */
export interface ApRecommendationApPosition {
  ap_index: number;
  x: number;
  y: number;
}

export interface MeterBBox {
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
}

export interface ApRecommendationZone extends MeterBBox {
  label?: string | null;
  weight: number;
}

/** POST /ap-recommendation 응답 내 단일 추천 항목. */
export interface ApRecommendationItem {
  rank: number;
  recommended_x: number;
  recommended_y: number;
  score: number;
  ap_positions?: ApRecommendationApPosition[];
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
  recommended_aps?: PhysicalAp[];
  final_aps?: PhysicalAp[];
  relocation_moves?: RelocationMove[];
  score_breakdown?: ScoreBreakdown;
  verified_score?: number | null;
  verification_status?: string | null;
  verification_job_id?: UUID | null;
}

export interface RelocationMove {
  ap_id: string;
  from_x: number;
  from_y: number;
  to_x: number;
  to_y: number;
}

export interface ScoreBreakdown {
  coverage_score?: number | null;
  coverage_ratio?: number | null;
  weak_zone_improvement?: number | null;
  weak_zone_improvement_score?: number | null;
  weak_zone_improvement_db?: number | null;
  bottom_10_percent?: number | null;
  bottom_10_percent_score?: number | null;
  bottom_10_percent_rssi_dbm?: number | null;
  average_rssi?: number | null;
  average_rssi_score?: number | null;
  average_rssi_dbm?: number | null;
  baseline_improvement?: number | null;
  baseline_improvement_score?: number | null;
  baseline_improvement_db?: number | null;
  overlap_penalty?: number | null;
  too_close_penalty?: number | null;
  transfer_applied?: boolean | null;
  residual_used?: boolean | null;
  [key: string]: unknown;
}

export interface VerificationJob {
  candidate_rank: number;
  candidate_id: string;
  rf_job_id?: UUID | null;
  rf_run_id?: UUID | null;
  fast_score?: number | null;
  verified_score?: number | null;
  status: string;
  candidate_aps?: Array<Record<string, unknown>>;
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
  /** Physical AP 스냅샷 (요청 시 넘긴 physical_aps). */
  physical_aps_snapshot?: PhysicalAp[] | null;
  /** band별 radio 개수 등 메타. */
  band_metadata?: Record<string, unknown> | null;
  band_aware_status?: string | null;
  /** 커버리지 평가 방식 설명. */
  coverage_semantics?: Record<string, unknown> | null;
  recommendation_band?: WifiBand | null;
  /** 사용된 추천 모드. */
  recommendation_mode?: RecommendationMode;
  /** 모드 설명 문자열. */
  mode_explanation?: string;
  /** 이동 전 전체 AP 목록. */
  baseline_aps_snapshot?: Array<{ id: string; x: number; y: number }>;
  /** 고정 AP 목록. */
  fixed_aps_snapshot?: Array<{ id: string; x: number; y: number }>;
  /** 이동 대상 AP 목록 (이동 전 위치). */
  movable_aps_snapshot?: Array<{ id: string; x: number; y: number }>;
  /** 최종 AP 레이아웃 (fixed + 추천). */
  recommended_aps?: PhysicalAp[];
  final_aps?: PhysicalAp[];
  /** AP 이동 기록 {ap_id, from_x, from_y, to_x, to_y}[]. */
  relocation_moves?: RelocationMove[];
  score_breakdown?: ScoreBreakdown;
  residual_metadata?: Record<string, unknown> | null;
  verify_with_sionna?: boolean;
  verification_status?: string | null;
  verification_jobs?: VerificationJob[];
  baseline_ap_count?: number | null;
  fixed_ap_count?: number | null;
  relocated_ap_count?: number | null;
  added_ap_count?: number | null;
  target_total_aps?: number | null;
}

/** UI 표시용. */
export interface ApRecommendationResult {
  rank: number;
  recommended_x: number;
  recommended_y: number;
  score: number;
  ap_positions?: ApRecommendationApPosition[];
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
  recommended_aps?: PhysicalAp[];
  final_aps?: PhysicalAp[];
  relocation_moves?: RelocationMove[];
  score_breakdown?: ScoreBreakdown;
  verified_score?: number | null;
  verification_status?: string | null;
  verification_job_id?: UUID | null;
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
    priority_zones?: ApRecommendationZone[];
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
