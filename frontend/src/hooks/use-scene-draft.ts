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

/**
 * §6.1 — 신규 도면 업로드 + 분석 Job 등록.
 *
 * 백엔드가 비동기로 전환되어 mutation 은 즉시 job_id 만 반환함.
 * 실제 완료 여부는 useFloorplanJob(jobId) 폴링으로 확인하고,
 * 완료/실패 토스트도 그 훅에서 발화함.
 */
export function useAnalyzeFloorplan() {
  return useMutation({
    mutationFn: (params: AnalyzeFloorplanParams) => sceneDraftApi.analyzeFloorplan(params),
    onSuccess: () => {
      toast.info('도면 분석 시작', '분석이 완료되면 결과를 알려드릴게요.');
    },
    onError: (err) => {
      toast.error('도면 분석 요청 실패', analyzeErrorMessage(err));
    },
  });
}

/** §6.1.1 — 이미 등록된 Asset 도면을 재분석. 권장 흐름. (동일하게 비동기 Job) */
export function useAnalyzeFromAsset() {
  return useMutation({
    mutationFn: (params: AnalyzeFromAssetParams) => sceneDraftApi.analyzeFromAsset(params),
    onSuccess: () => {
      toast.info('도면 분석 시작', '분석이 완료되면 결과를 알려드릴게요.');
    },
    onError: (err) => {
      toast.error('도면 분석 요청 실패', analyzeErrorMessage(err));
    },
  });
}

/**
 * 빈 SceneDraft 생성 — 이미지·AI 분석 없이 사용자가 처음부터 그릴 때.
 * 성공하면 해당 floor 의 draft 목록을 무효화 → useDraftsForFloor 가 즉시 새 draft 인식.
 */
export function useCreateEmptyDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (floorId: UUID) => sceneDraftApi.createEmpty(floorId),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      // 새로 만든 draft detail 도 미리 캐시에 채워둠 → 이어지는 useSceneDraft 즉시 hit.
      qc.setQueryData(['scene-draft', created.id], created);
      toast.info('빈 도면을 만들었어요', '이제 좌측 도구로 도면을 그려보세요.');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('빈 도면 생성 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}

export function useDeleteSceneDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draftId: UUID) => sceneDraftApi.remove(draftId),
    onSuccess: (_data, draftId) => {
      // list 무효화 + 삭제된 draft 의 detail 캐시도 제거 (stale 잔존 방지).
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      qc.removeQueries({ queryKey: ['scene-draft', draftId] });
      toast.info('Draft 가 삭제되었습니다');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('Draft 삭제 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}
