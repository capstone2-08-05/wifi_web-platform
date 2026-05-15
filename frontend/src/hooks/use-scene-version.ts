import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['scene-versions'] });
      qc.invalidateQueries({ queryKey: ['scene-version', data.id] });
      toast.success(`버전 #${data.version_no} 으로 전환됨`, '이 버전을 기준으로 작업합니다.');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('버전 전환 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
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
