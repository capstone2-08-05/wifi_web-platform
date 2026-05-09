import type { ISODateString, UUID } from './common';

export interface Floor {
  id: UUID;
  project_id: UUID;
  floor_name: string;
  floor_order: number;
  height_m: number;
  created_at: ISODateString;
}

export interface CreateFloorRequest {
  floor_name: string;
  floor_order: number;
  height_m: number;
}

export interface UpdateFloorRequest {
  floor_name?: string;
  floor_order?: number;
  height_m?: number;
}

/** Floor list response is a plain `{ items }` envelope (not paginated). */
export interface FloorListResponse {
  items: Floor[];
}
