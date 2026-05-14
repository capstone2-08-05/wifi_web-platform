import type { ISODateString, UUID } from './common';

// 백엔드 §15 Job DTO (app/schemas/job.py 의 JobResponse 와 매칭)
// 도면 분석은 비동기로 큐잉되어 이 모델로 상태 추적됨.

export type JobStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'done'
  | 'failed'
  | string;

/** 백엔드 응답의 상태값 중 "완료" 로 간주되는 것들 (명세는 succeeded, 실제 응답은 done). */
const TERMINAL_SUCCESS = new Set(['succeeded', 'done']);
const TERMINAL_FAILURE = new Set(['failed', 'error']);

export function isJobSucceeded(status: string | null | undefined): boolean {
  return !!status && TERMINAL_SUCCESS.has(status);
}

export function isJobFailed(status: string | null | undefined): boolean {
  return !!status && TERMINAL_FAILURE.has(status);
}

export function isJobTerminal(status: string | null | undefined): boolean {
  return isJobSucceeded(status) || isJobFailed(status);
}

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
