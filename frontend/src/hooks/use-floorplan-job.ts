import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { floorplanJobApi } from '@/api/floorplan-job';
import type { UUID } from '@/types/common';
import type { Job } from '@/types/job';
import { toast } from '@/stores/toast-store';

const POLL_INTERVAL_MS = 3_000;

/**
 * 비동기 분석 Job 진행 상태 폴링.
 *
 * - jobId 가 truthy 인 동안 3초 간격으로 GET /floorplan-jobs/{id}.
 * - status 가 succeeded / failed 면 자동 폴링 중지.
 * - succeeded 시 scene-drafts 캐시 무효화 + 토스트.
 * - failed 시 에러 토스트.
 */
export function useFloorplanJob(jobId: UUID | null) {
  const qc = useQueryClient();
  // 같은 jobId 에 대해 success/error 토스트가 중복 발화되지 않도록 가드.
  const settledRef = useRef<string | null>(null);

  const query = useQuery({
    queryKey: ['floorplan-job', jobId] as const,
    queryFn: () => floorplanJobApi.get(jobId as UUID),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      if (status === 'succeeded' || status === 'failed') return false;
      return POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: false,
  });

  // 상태 변화 부수효과 (토스트, 캐시 무효화)
  useEffect(() => {
    const data = query.data;
    if (!data || !jobId) return;
    if (settledRef.current === jobId) return;

    if (data.status === 'succeeded') {
      settledRef.current = jobId;
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      toast.success('도면 분석 완료', '결과를 확인하고 확정해주세요.');
    } else if (data.status === 'failed') {
      settledRef.current = jobId;
      toast.error('도면 분석 실패', data.error_message ?? '잠시 후 다시 시도해주세요.');
    }
  }, [query.data, jobId, qc]);

  // jobId 가 바뀌면 가드 초기화
  useEffect(() => {
    settledRef.current = null;
  }, [jobId]);

  const job: Job | null = query.data ?? null;
  const isPolling = !!jobId && job?.status !== 'succeeded' && job?.status !== 'failed';
  const sceneDraftId =
    job?.status === 'succeeded'
      ? (job.result_json?.scene_draft_id as string | undefined) ?? null
      : null;

  return {
    job,
    isPolling,
    isLoading: query.isLoading,
    isSucceeded: job?.status === 'succeeded',
    isFailed: job?.status === 'failed',
    sceneDraftId,
    errorMessage: job?.status === 'failed' ? job.error_message : null,
  };
}
