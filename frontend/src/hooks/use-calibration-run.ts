import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { calibrationRunApi } from '@/api/calibration-run';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';
import type {
  CalibrationRun,
  CalibrationRunCreateRequest,
  CalibrationEvaluationRequest,
} from '@/types/calibration-run';
import { isJobFailed, isJobSucceeded, isJobTerminal } from '@/types/job';

const POLL_INTERVAL_MS = 3_000;

/** §11.1 POST /calibration-runs — 시뮬레이션 보정 Job 등록. */
export function useCreateCalibrationRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CalibrationRunCreateRequest) => calibrationRunApi.create(body),
    onSuccess: (run) => {
      qc.setQueryData(['calibration-run', run.id], run);
      toast.info('시뮬레이션 보정 시작', '완료되면 결과를 알려드릴게요.');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('시뮬레이션 보정 요청 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}

export function useEvaluateCalibrationRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CalibrationEvaluationRequest) => calibrationRunApi.evaluate(body),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['calibration-run'] });
      toast.success('Calibration evaluation complete', 'Validation metrics and 3-way maps are ready.');
      return result;
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('Calibration evaluation failed', e?.message ?? 'Please check RF map and measurement points.');
    },
  });
}

/**
 * §11.2 GET /calibration-runs/{id} — 진행 상태 폴링.
 * succeeded/failed 시 자동 중지 + 토스트 (중복 발화 방지).
 */
export function useCalibrationRun(runId: UUID | null) {
  const settledRef = useRef<string | null>(null);

  const query = useQuery({
    queryKey: ['calibration-run', runId] as const,
    queryFn: () => calibrationRunApi.get(runId as UUID),
    enabled: !!runId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (isJobTerminal(s)) return false;
      return POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: false,
    retry: false,
  });

  useEffect(() => {
    const data = query.data;
    if (!data || !runId) return;
    if (settledRef.current === runId) return;
    if (isJobSucceeded(data.status)) {
      settledRef.current = runId;
      toast.success('시뮬레이션 보정 완료', '결과를 확인해주세요.');
    } else if (isJobFailed(data.status)) {
      settledRef.current = runId;
      toast.error('시뮬레이션 보정 실패', '잠시 후 다시 시도해주세요.');
    }
  }, [query.data, runId]);

  useEffect(() => {
    settledRef.current = null;
  }, [runId]);

  const run: CalibrationRun | null = query.data ?? null;
  const status = run?.status;
  return {
    run,
    isPolling: !!runId && !isJobTerminal(status),
    isSucceeded: isJobSucceeded(status),
    isFailed: isJobFailed(status),
  };
}

/** §11.3 — 파라미터 변경 이력. succeeded 후에만 활성화. */
export function useCalibrationParameterUpdates(runId: UUID | null, enabled: boolean) {
  return useQuery({
    queryKey: ['calibration-parameter-updates', runId] as const,
    queryFn: () => calibrationRunApi.listParameterUpdates(runId as UUID),
    enabled: !!runId && enabled,
    retry: false,
  });
}
