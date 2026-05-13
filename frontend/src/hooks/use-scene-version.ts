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
      const message =
        e?.code === 'DRAFT_ALREADY_PROMOTED'
          ? '이미 확정된 Draft 입니다.'
          : e?.code === 'SCENE_VERSION_CONFLICT'
          ? '같은 층에 동일한 버전 번호가 이미 존재합니다.'
          : e?.message ?? '확정에 실패했습니다.';
      toast.error('확정 실패', message);
    },
  });
}
