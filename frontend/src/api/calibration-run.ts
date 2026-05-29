import { api } from './client';
import type { UUID } from '@/types/common';
import type {
  CalibrationRun,
  CalibrationRunCreateRequest,
  CalibrationEvaluationRequest,
  CalibrationEvaluationResponse,
  ParameterUpdate,
} from '@/types/calibration-run';

export const calibrationRunApi = {
  // §11.1 POST /calibration-runs — Job 큐 등록 (HTTP 202).
  create: (body: CalibrationRunCreateRequest) =>
    api.post<CalibrationRun>('/calibration-runs', body).then((r) => r.data),

  evaluate: (body: CalibrationEvaluationRequest) =>
    api.post<CalibrationEvaluationResponse>('/calibration-runs/evaluate', body).then((r) => r.data),

  // §11.2 GET /calibration-runs/{id} — 결과/상태 조회.
  get: (id: UUID) =>
    api.get<CalibrationRun>(`/calibration-runs/${id}`).then((r) => r.data),

  // §11.3 GET /calibration-runs/{id}/parameter-updates — 변경 이력 (list 직접 반환).
  listParameterUpdates: (id: UUID) =>
    api
      .get<ParameterUpdate[]>(`/calibration-runs/${id}/parameter-updates`)
      .then((r) => r.data),
};
