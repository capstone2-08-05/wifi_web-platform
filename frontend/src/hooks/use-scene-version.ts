import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { sceneDraftApi } from '@/api/scene-draft';
import { sceneVersionApi } from '@/api/scene-version';
import type { UUID } from '@/types/common';
import type { PromoteRequest } from '@/types/scene';
import { toast } from '@/stores/toast-store';
import type { HttpError } from '@/api/client';

export function useFloorVersions(floorId: UUID | null, params?: { is_current?: boolean }) {
  return useQuery({
    queryKey: ['scene-versions', floorId, params ?? {}] as const,
    queryFn: () => sceneVersionApi.listByFloor(floorId as UUID, params),
    enabled: !!floorId,
    staleTime: 30_000,
  });
}

export function useSceneVersion(versionId: UUID | null) {
  return useQuery({
    queryKey: ['scene-version', versionId] as const,
    queryFn: () => sceneVersionApi.get(versionId as UUID),
    enabled: !!versionId,
    // 한 번 방문한 버전은 5분간 캐시 활용 → 다음 전환 시 즉시 표시.
    staleTime: 5 * 60_000,
    // 전환 중엔 이전 버전 데이터를 그대로 유지 → 캔버스가 빈 화면으로 떨어지지 않음.
    // 삭제된 버전이 stale 데이터로 남는 부작용은 useDeleteSceneVersion 의 removeQueries 로 차단.
    placeholderData: keepPreviousData,
  });
}

/**
 * DELETE /scene-versions/{id} — 버전 삭제.
 *
 * 추가로: 백엔드는 scene_versions.scene_draft_id 에 ON DELETE SET NULL 이 걸려있어
 * 버전이 지워져도 source draft 는 status='draft' 인 채 DB 에 남는다. 그 결과
 * 프론트의 activeDraftSummary 필터가 그 orphan draft 를 잡아 ReviewCard("확정 #N")
 * 가 다시 떠버리는 부작용이 있음. 사용자 입장에선 "버전 지웠더니 확정 창이 뜬다" 라
 * 혼란스러움 — 그래서 버전 삭제 직후 연결된 draft 도 같이 삭제한다.
 */
export interface DeleteSceneVersionVars {
  versionId: UUID;
  sourceDraftId?: UUID | null;
}

export function useDeleteSceneVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ versionId, sourceDraftId }: DeleteSceneVersionVars) => {
      await sceneVersionApi.remove(versionId);
      // orphan draft cleanup — 실패해도 버전 삭제는 이미 성공이라 무시 (404 등).
      if (sourceDraftId) {
        try {
          await sceneDraftApi.remove(sourceDraftId);
        } catch {
          /* draft 가 이미 없거나 권한 문제 — 무시. */
        }
      }
    },
    onSuccess: (_data, { versionId }) => {
      qc.removeQueries({ queryKey: ['scene-version', versionId], exact: true });
      qc.invalidateQueries({ queryKey: ['scene-versions'] });
      qc.invalidateQueries({ queryKey: ['scene-version'] });
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      qc.invalidateQueries({ queryKey: ['rf-runs'] });
      qc.invalidateQueries({ queryKey: ['patch-logs'] });
      toast.info('버전 삭제됨');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('버전 삭제 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}

/** §7.3 PATCH /scene-versions/{id}/set-current — 활성 버전 전환. */
export function useSetCurrentVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: UUID) => sceneVersionApi.setCurrent(versionId),
    // 낙관적 업데이트 — 리스트 캐시의 is_current 를 즉시 새 버전 쪽으로 옮긴다.
    // refetch 가 끝나기 전에도 캔버스가 새 버전 상세를 가리키도록.
    onMutate: async (versionId) => {
      await qc.cancelQueries({ queryKey: ['scene-versions'] });
      const snapshot = qc.getQueriesData<unknown>({ queryKey: ['scene-versions'] });
      qc.setQueriesData<unknown>({ queryKey: ['scene-versions'] }, (old) => {
        if (!Array.isArray(old)) return old;
        return (old as Array<{ id: UUID; is_current: boolean }>).map((v) => ({
          ...v,
          is_current: v.id === versionId,
        }));
      });
      return { snapshot };
    },
    onError: (err, _vars, ctx) => {
      // 롤백.
      if (ctx?.snapshot) {
        for (const [key, data] of ctx.snapshot) qc.setQueryData(key, data);
      }
      const e = err as HttpError | null;
      toast.error('버전 전환 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
    onSuccess: (data) => {
      toast.success(`버전 #${data.version_no} 으로 전환됨`, '이 버전을 기준으로 작업합니다.');
    },
    onSettled: () => {
      // 리스트만 새로 받아오고 detail 캐시는 staleTime 안이면 그대로 활용.
      // (set-current 는 detail 내용엔 영향 없고 is_current 플래그만 바꾸므로
      // 굳이 무거운 detail 을 다시 fetch 할 필요 없음.)
      qc.invalidateQueries({ queryKey: ['scene-versions'] });
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
    },
  });
}

export function usePromoteDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ draftId, body }: { draftId: UUID; body: PromoteRequest }) =>
      sceneVersionApi.promote(draftId, body),
    onSuccess: (data, variables) => {
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      qc.invalidateQueries({ queryKey: ['scene-versions'] });
      qc.invalidateQueries({ queryKey: ['scene-draft', variables.draftId] });
      toast.success(`버전 #${data.version_no} 확정 완료`, '이 버전 위에서 이어서 작업할 수 있습니다.');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      // 이미 확정된 draft 인데 프론트 캐시가 stale 인 케이스 — 캐시 강제 갱신.
      if (e?.code === 'DRAFT_ALREADY_PROMOTED') {
        qc.invalidateQueries({ queryKey: ['scene-drafts'] });
        qc.invalidateQueries({ queryKey: ['scene-versions'] });
      }
      const message =
        e?.code === 'DRAFT_ALREADY_PROMOTED'
          ? '이미 확정된 Draft 입니다. 잠시 후 화면이 갱신됩니다.'
          : e?.code === 'SCENE_VERSION_CONFLICT'
          ? '같은 층에 동일한 버전 번호가 이미 존재합니다.'
          : e?.message ?? '확정에 실패했습니다.';
      toast.error('확정 실패', message);
    },
  });
}
