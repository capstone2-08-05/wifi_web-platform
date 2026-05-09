import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { projectApi, type ProjectListParams } from '@/api/project';
import type { CreateProjectRequest } from '@/types/project';

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
