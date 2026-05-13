import { useQuery } from '@tanstack/react-query';
import { jobApi } from '@/api/job';
import type { UUID } from '@/types/common';
import type { JobStatus } from '@/types/job';

/** §15.2 — Job 목록 (job_type/status 필터, 페이지네이션). */
export function useJobs(params?: {
  job_type?: string;
  status?: JobStatus;
  page?: number;
  page_size?: number;
}) {
  return useQuery({
    queryKey: ['jobs', params ?? {}] as const,
    queryFn: () => jobApi.list(params),
    staleTime: 10_000,
  });
}

/** §15.1 — Job 단건. (분석 Job 폴링은 useFloorplanJob 사용) */
export function useJob(jobId: UUID | null) {
  return useQuery({
    queryKey: ['job', jobId] as const,
    queryFn: () => jobApi.get(jobId as UUID),
    enabled: !!jobId,
  });
}
