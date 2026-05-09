import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { sceneVersionApi } from '@/api/scene-version';
import type { UUID } from '@/types/common';
import type { PromoteRequest } from '@/types/scene';

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
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
      qc.invalidateQueries({ queryKey: ['scene-versions'] });
      qc.invalidateQueries({ queryKey: ['scene-draft', variables.draftId] });
    },
  });
}
