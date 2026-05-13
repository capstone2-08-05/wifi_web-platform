import { api } from './client';
import type { Paginated, UUID } from '@/types/common';
import type { Job, JobStatus } from '@/types/job';

export const jobApi = {
  // §15.2 GET /jobs — paginated, filters: job_type / status
  list: (params?: {
    job_type?: string;
    status?: JobStatus;
    page?: number;
    page_size?: number;
  }) => api.get<Paginated<Job>>('/jobs', { params }).then((r) => r.data),

  // §15.1 GET /jobs/{job_id}
  get: (id: UUID) => api.get<Job>(`/jobs/${id}`).then((r) => r.data),
};
