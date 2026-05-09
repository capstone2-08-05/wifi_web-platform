import type { ISODateString, UUID } from './common';

export type ProjectStatus = 'active' | 'archived';

export interface Project {
  id: UUID;
  owner_user_id: UUID;
  name: string;
  description?: string | null;
  status: ProjectStatus;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface CreateProjectRequest {
  name: string;
  description?: string;
}

export interface UpdateProjectRequest {
  name?: string;
  description?: string;
  status?: ProjectStatus;
}
