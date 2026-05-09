import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { floorApi } from '@/api/floor';
import type { UUID } from '@/types/common';
import type { CreateFloorRequest } from '@/types/floor';

const floorsKey = (projectId: UUID) => ['floors', projectId] as const;

export function useFloors(projectId: UUID | null) {
  return useQuery({
    queryKey: ['floors', projectId ?? null] as const,
    queryFn: () => floorApi.listByProject(projectId as UUID),
    enabled: !!projectId,
    staleTime: 60_000,
  });
}

export function useCreateFloor(projectId: UUID | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateFloorRequest) => {
      if (!projectId) throw new Error('projectId is required');
      return floorApi.create(projectId, body);
    },
    onSuccess: () => {
      if (projectId) qc.invalidateQueries({ queryKey: floorsKey(projectId) });
    },
  });
}
