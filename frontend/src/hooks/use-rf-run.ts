import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { rfJobApi, rfRunApi, type ListRfRunsParams } from '@/api/rf-run';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { Paginated, UUID } from '@/types/common';
import type { RfJob, RfRun, RfRunCreate } from '@/types/rf';
import { isJobFailed, isJobSucceeded, isJobTerminal } from '@/types/job';

const POLL_INTERVAL_MS = 3_000;

/** run id 별 완료/실패 토스트 1회만 (Strict Mode·리마운트 중복 방지). */
const notifiedRfRunIds = new Set<string>();

function rfRunsQueryKey(floorId: UUID, params?: ListRfRunsParams) {
  return ['rf-runs', floorId, params ?? null] as const;
}

function prependRfRunToCache(
  queryClient: ReturnType<typeof useQueryClient>,
  floorId: UUID,
  run: RfRun,
  listParams?: ListRfRunsParams,
) {
  queryClient.setQueriesData<Paginated<RfRun>>(
    { queryKey: ['rf-runs', floorId] },
    (old) => {
      if (!old) {
        return {
          items: [run],
          total: 1,
          page: 1,
          page_size: listParams?.page_size ?? 20,
        };
      }
      const items = [run, ...old.items.filter((r) => r.id !== run.id)];
      return { ...old, items, total: Math.max(old.total, items.length) };
    },
  );
}

function invalidateFloorRfRuns(
  queryClient: ReturnType<typeof useQueryClient>,
  floorId: UUID,
) {
  void queryClient.invalidateQueries({ queryKey: ['rf-runs', floorId] });
}

/** POST /rf-runs — 시뮬레이션 큐 등록. */
export function useCreateRfRun(floorId: UUID | null, listParams?: ListRfRunsParams) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RfRunCreate) => rfRunApi.create(body),
    onSuccess: (data) => {
      if (floorId) {
        prependRfRunToCache(queryClient, floorId, data, listParams);
        invalidateFloorRfRuns(queryClient, floorId);
      }
      toast.info('RF 시뮬레이션 시작', '분석이 완료되면 결과를 알려드릴게요.');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error(
        'RF 시뮬레이션 요청 실패',
        e?.message ?? '잠시 후 다시 시도해주세요.',
      );
    },
  });
}

/**
 * RF Run 진행 상태 폴링.
 * succeeded/failed 시 자동 중지 + 토스트 (중복 발화 방지).
 */
export function useRfRun(rfRunId: UUID | null) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['rf-run', rfRunId] as const,
    queryFn: () => rfRunApi.get(rfRunId as UUID),
    enabled: !!rfRunId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (isJobTerminal(s)) return false;
      return POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    const data = query.data;
    if (!data || !rfRunId) return;

    // 목록 캐시에 최신 status 반영 — 기록 패널이 새로고침 없이 갱신되도록.
    queryClient.setQueriesData<Paginated<RfRun>>(
      { queryKey: ['rf-runs', data.floor_id] },
      (old) => {
        if (!old) return old;
        const idx = old.items.findIndex((r) => r.id === data.id);
        if (idx < 0) return old;
        const items = [...old.items];
        items[idx] = data;
        return { ...old, items };
      },
    );

    if (notifiedRfRunIds.has(rfRunId)) return;
    if (isJobSucceeded(data.status)) {
      notifiedRfRunIds.add(rfRunId);
      invalidateFloorRfRuns(queryClient, data.floor_id);
      toast.success('RF 시뮬레이션 완료', '결과를 확인해주세요.');
    } else if (isJobFailed(data.status)) {
      notifiedRfRunIds.add(rfRunId);
      invalidateFloorRfRuns(queryClient, data.floor_id);
      const err = (data.metrics_json?.['error_message'] as string | undefined) ?? undefined;
      toast.error('RF 시뮬레이션 실패', err ?? '잠시 후 다시 시도해주세요.');
    }
  }, [query.data, rfRunId, queryClient]);

  const rfRun: RfRun | null = query.data ?? null;
  const status = rfRun?.status;
  return {
    rfRun,
    isPolling: !!rfRunId && !isJobTerminal(status),
    isSucceeded: isJobSucceeded(status),
    isFailed: isJobFailed(status),
  };
}

/**
 * GET /floors/{floor_id}/rf-runs — 층의 RF Run 목록 (최신순).
 * 기본 status 필터 없음 — 호출 측에서 'succeeded' 등으로 좁힐 수 있음.
 */
export function useFloorRfRuns(floorId: UUID | null, params?: ListRfRunsParams) {
  return useQuery({
    queryKey: rfRunsQueryKey(floorId as UUID, params),
    queryFn: () => rfRunApi.listByFloor(floorId as UUID, params),
    enabled: !!floorId,
    staleTime: 5_000,
    refetchInterval: (q) => {
      const hasActive = q.state.data?.items.some(
        (r) => r.status === 'pending' || r.status === 'running',
      );
      return hasActive ? POLL_INTERVAL_MS : false;
    },
  });
}

/** GET /rf-runs/{id}/maps — RF Run 이 succeeded 된 후에만 활성화 */
export function useRfMaps(rfRunId: UUID | null, enabled: boolean) {
  return useQuery({
    queryKey: ['rf-maps', rfRunId] as const,
    queryFn: () => rfRunApi.listMaps(rfRunId as UUID),
    enabled: !!rfRunId && enabled,
  });
}

/**
 * GET /rf-jobs/{job_id} — Job 폴링.
 * RfMap.storage_url 이 s3:// 라서 직접 못 박는 대신, 이 응답의
 * heatmap.url / radio_map.url (이미 presigned) 을 사용한다.
 *
 * useRfRun 과 동일하게 succeeded/failed 까지 폴링하되, 완료 후엔 폴링 중단.
 */
export function useRfJob(jobId: UUID | null) {
  const query = useQuery({
    queryKey: ['rf-job', jobId] as const,
    queryFn: () => rfJobApi.get(jobId as UUID),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (isJobTerminal(s)) return false;
      return POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: false,
  });

  const rfJob: RfJob | null = query.data ?? null;
  const status = rfJob?.status;
  return {
    rfJob,
    isPolling: !!jobId && !isJobTerminal(status),
    isSucceeded: isJobSucceeded(status),
    isFailed: isJobFailed(status),
  };
}
