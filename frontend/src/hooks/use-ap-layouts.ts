import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apLayoutApi } from '@/api/ap-layout';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';
import type {
  ApCandidateGenerateRequest,
  ApLayoutCreate,
} from '@/types/ap-layout';

const apCandidatesKey = (rfRunId: UUID | null) => ['ap-candidates', rfRunId] as const;
const apLayoutsKey = (rfRunId: UUID | null) => ['ap-layouts', rfRunId] as const;

/** §14.1 POST /ap-candidates/generate — 후보 생성 Job 등록. */
export function useGenerateApCandidates() {
  return useMutation({
    mutationFn: (body: ApCandidateGenerateRequest) => apLayoutApi.generateCandidates(body),
    onSuccess: () => {
      toast.info('AP 후보 생성 시작', '완료되면 후보 목록이 업데이트됩니다.');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('AP 후보 생성 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}

/** §14.2 GET /rf-runs/{rf_run_id}/ap-candidates — 후보 목록. */
export function useApCandidates(rfRunId: UUID | null) {
  return useQuery({
    queryKey: apCandidatesKey(rfRunId),
    queryFn: () => apLayoutApi.listCandidates(rfRunId as UUID),
    enabled: !!rfRunId,
  });
}

/** §14.4 GET /rf-runs/{rf_run_id}/ap-layouts — 확정된 AP 배치 목록. */
export function useApLayouts(rfRunId: UUID | null) {
  return useQuery({
    queryKey: apLayoutsKey(rfRunId),
    queryFn: () => apLayoutApi.listLayouts(rfRunId as UUID),
    enabled: !!rfRunId,
  });
}

/** §14.3 POST /ap-layouts — AP 배치 확정. */
export function useCreateApLayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ApLayoutCreate) => apLayoutApi.createLayout(body),
    onSuccess: (layout) => {
      qc.invalidateQueries({ queryKey: apLayoutsKey(layout.rf_run_id) });
      toast.success('AP 배치 저장 완료', `${layout.ap_name} 위치가 확정되었습니다.`);
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('AP 배치 저장 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}

/** §14.4 DELETE /ap-layouts/{layout_id} — AP 배치 삭제. */
export function useDeleteApLayout(rfRunId: UUID | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (layoutId: UUID) => apLayoutApi.deleteLayout(layoutId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: apLayoutsKey(rfRunId) });
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('AP 배치 삭제 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}
