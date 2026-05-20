import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { floorApi } from '@/api/floor';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';
import type { CreateFloorRequest, UpdateFloorRequest } from '@/types/floor';

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

export function useUpdateFloor(projectId: UUID | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: UUID; body: UpdateFloorRequest }) =>
      floorApi.update(id, body),
    onSuccess: () => {
      if (projectId) qc.invalidateQueries({ queryKey: floorsKey(projectId) });
      toast.info('층 정보가 수정되었습니다');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('층 수정 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}

export function useDeleteFloor(projectId: UUID | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (floorId: UUID) => floorApi.remove(floorId),
    onSuccess: () => {
      if (projectId) qc.invalidateQueries({ queryKey: floorsKey(projectId) });
      toast.info('층이 삭제되었습니다');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('층 삭제 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}
