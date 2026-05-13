import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  sceneDraftApi,
  type AnalyzeFloorplanParams,
  type AnalyzeFromAssetParams,
} from '@/api/scene-draft';
import type { UUID } from '@/types/common';
import { toast } from '@/stores/toast-store';
import type { HttpError } from '@/api/client';

export function useDraftsForFloor(projectId: UUID | null, floorId: UUID | null) {
  return useQuery({
    queryKey: ['scene-drafts', { projectId, floorId }] as const,
    queryFn: () =>
      sceneDraftApi.list({
        project_id: projectId as UUID,
        floor_id: floorId as UUID,
        status: 'draft',
      }),
    enabled: !!projectId && !!floorId,
    staleTime: 30_000,
  });
}

export function useSceneDraft(draftId: UUID | null) {
  return useQuery({
    queryKey: ['scene-draft', draftId] as const,
    queryFn: () => sceneDraftApi.get(draftId as UUID),
    enabled: !!draftId,
  });
}

function analyzeErrorMessage(err: unknown): string {
  const e = err as HttpError | null;
  if (!e) return '도면 분석에 실패했습니다.';
  if (e.code === 'INVALID_FILE_EXTENSION') return '지원하지 않는 파일 형식입니다.';
  if (e.code === 'FILE_SAVE_FAILED') return '파일 저장에 실패했습니다.';
  if (e.code === 'INVALID_PROJECT_FLOOR_PAIR') return '프로젝트와 층의 매핑이 올바르지 않습니다.';
  if (e.code === 'SCENE_DRAFT_SAVE_FAILED') return '분석 결과 저장에 실패했습니다.';
  return e.message ?? '도면 분석에 실패했습니다.';
}

/** §6.1 — 신규 도면 업로드 + 즉시 분석 */
export function useAnalyzeFloorplan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: AnalyzeFloorplanParams) => sceneDraftApi.analyzeFloorplan(params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      toast.success('도면 분석 완료', '결과를 확인하고 확정해주세요.');
    },
    onError: (err) => {
      toast.error('도면 분석 실패', analyzeErrorMessage(err));
    },
  });
}

/** §6.1.1 — 이미 등록된 Asset 도면을 재분석. 권장 흐름. */
export function useAnalyzeFromAsset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: AnalyzeFromAssetParams) => sceneDraftApi.analyzeFromAsset(params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      toast.success('도면 분석 완료', '결과를 확인하고 확정해주세요.');
    },
    onError: (err) => {
      toast.error('도면 분석 실패', analyzeErrorMessage(err));
    },
  });
}

export function useDeleteSceneDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draftId: UUID) => sceneDraftApi.remove(draftId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      toast.info('Draft 가 삭제되었습니다');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('Draft 삭제 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}
