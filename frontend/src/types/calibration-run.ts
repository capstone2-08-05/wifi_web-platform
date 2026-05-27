import type { ISODateString, UUID } from './common';

// §11 캘리브레이션 — 백엔드 schemas/calibration_run.py 와 정합.

export type CalibrationRunStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | string;

/** 공간 유형 — calibration 의 soft prior 로 사용. 백엔드 SpaceTypeLiteral 과 정합. */
export type SpaceType =
  | 'cafe'
  | 'study_room'
  | 'classroom'
  | 'office'
  | 'residential'
  | 'unknown';

export interface CalibrationRun {
  id: UUID;
  status: CalibrationRunStatus;
  session_id: UUID | null;
  rf_run_id: UUID | null;
  version_id: UUID;
  /** RMSE, MAE 등 보정 결과 메트릭. 백엔드 service 가 채워 넣음. */
  error_metrics_json: Record<string, unknown>;
  /** 보정 전후 차이 시각화 heatmap (presigned URL). 없을 수 있음. */
  error_heatmap_url: string | null;
  created_at: ISODateString;
  finished_at: ISODateString | null;
}

export interface CalibrationRunCreateRequest {
  session_id: UUID;
  rf_run_id: UUID;
  version_id: UUID;
  /** 공간 유형 soft prior. 미지정 시 백엔드가 'unknown' 으로 fallback. */
  space_type?: SpaceType;
}

/** §11.3 파라미터 변경 이력 — 어떤 wall/object 의 무슨 파라미터가 어떤 값으로 바뀌었는지. */
export interface ParameterUpdate {
  id: UUID;
  calibration_run_id: UUID;
  target_type: string; // 'wall' | 'object' 등
  target_id: UUID;
  param_name: string;
  old_value_json: unknown;
  new_value_json: unknown;
  created_at: ISODateString;
}
