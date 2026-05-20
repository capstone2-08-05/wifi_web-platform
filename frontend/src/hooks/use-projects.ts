import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { projectApi, type ProjectListParams } from '@/api/project';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';
import type { CreateProjectRequest, UpdateProjectRequest } from '@/types/project';

const KEY = ['projects'] as const;

export function useProjects(params?: ProjectListParams) {
  return useQuery({
    queryKey: [...KEY, 'list', params ?? {}] as const,
    queryFn: () => projectApi.list(params),
    staleTime: 60_000,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateProjectRequest) => projectApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: UUID; body: UpdateProjectRequest }) =>
      projectApi.update(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      toast.info('프로젝트가 수정되었습니다');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('프로젝트 수정 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: UUID) => projectApi.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      toast.info('프로젝트가 삭제되었습니다');
    },
    onError: (err) => {
      const e = err as HttpError | null;
      toast.error('프로젝트 삭제 실패', e?.message ?? '잠시 후 다시 시도해주세요.');
    },
  });
}
