import type { ISODateString, UUID } from './common';

// 백엔드 §15 Job DTO (app/schemas/job.py 의 JobResponse 와 매칭)
// 도면 분석은 비동기로 큐잉되어 이 모델로 상태 추적됨.

export type JobStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | string;

export interface Job {
  id: UUID;
  project_id: UUID;
  floor_id: UUID | null;
  job_type: string;
  status: JobStatus;
  input_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  error_message: string | null;
  started_at: ISODateString | null;
  finished_at: ISODateString | null;
  created_at: ISODateString;
}

/** 도면 분석 완료(succeeded) 후 result_json 에서 추출되는 값들. */
export interface FloorplanJobResult {
  scene_draft_id?: UUID;
}
