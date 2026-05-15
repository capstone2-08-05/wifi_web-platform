import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
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
    // 버전 전환 시 새 detail 이 도착하기 전까지 이전 데이터를 유지 — 캔버스가 잠깐
    // 비어 보이고 업로드 화면으로 떨어지는 현상 방지.
    placeholderData: keepPreviousData,
  });
}

/** DELETE /scene-versions/{id} — 버전 삭제 (백엔드 §7 명세에 없지만 관례적으로 시도). */
export function useDeleteSceneVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: UUID) => sceneVersionApi.remove(versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['scene-versions'] });
      qc.invalidateQueries({ queryKey: ['scene-version'] });
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
      // 전체 scene-version 관련 캐시 + 드래프트/패치로그도 같이 새로 고침.
      qc.invalidateQueries({ queryKey: ['scene-versions'] });
      qc.invalidateQueries({ queryKey: ['scene-version'] });
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      qc.invalidateQueries({ queryKey: ['patch-logs'] });
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
