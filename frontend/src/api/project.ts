import { api } from './client';
import type { Paginated, UUID } from '@/types/common';
import type {
  CreateProjectRequest,
  Project,
  ProjectStatus,
  UpdateProjectRequest,
} from '@/types/project';

export interface ProjectListParams {
  page?: number;
  page_size?: number;
  status?: ProjectStatus;
}

export const projectApi = {
  list: (params?: ProjectListParams) =>
    api.get<Paginated<Project>>('/projects', { params }).then((r) => r.data),
  create: (body: CreateProjectRequest) =>
    api.post<Project>('/projects', body).then((r) => r.data),
  get: (id: UUID) => api.get<Project>(`/projects/${id}`).then((r) => r.data),
  update: (id: UUID, body: UpdateProjectRequest) =>
    api.patch<Project>(`/projects/${id}`, body).then((r) => r.data),
  remove: (id: UUID) => api.delete<void>(`/projects/${id}`).then((r) => r.data),
};
