import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { sceneDraftApi, type AnalyzeFloorplanParams } from '@/api/scene-draft';
import type { UUID } from '@/types/common';

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

export function useAnalyzeFloorplan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: AnalyzeFloorplanParams) => sceneDraftApi.analyzeFloorplan(params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
    },
  });
}

export function useDeleteSceneDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draftId: UUID) => sceneDraftApi.remove(draftId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['scene-drafts'] });
    },
  });
}
