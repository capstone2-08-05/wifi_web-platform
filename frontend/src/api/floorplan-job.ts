import { api } from './client';
import type { UUID } from '@/types/common';
import type { Job } from '@/types/job';

export const floorplanJobApi = {
  /** §6.1 / §6.1.1 분석 호출 후 받은 job_id 로 진행 상태 폴링. */
  get: (jobId: UUID) =>
    api.get<Job>(`/floorplan-jobs/${jobId}`).then((r) => r.data),
};
