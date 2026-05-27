import type { ISODateString, UUID } from './common';
import type { SpaceType } from './calibration-run';

export interface Floor {
  id: UUID;
  project_id: UUID;
  floor_name: string;
  floor_order: number;
  height_m: number;
  /** 공간 유형 — calibration BO prior + 향후 sim defaults 의 source of truth. */
  space_type: SpaceType;
  created_at: ISODateString;
}

export interface CreateFloorRequest {
  floor_name: string;
  floor_order: number;
  height_m: number;
  space_type?: SpaceType;
}

export interface UpdateFloorRequest {
  floor_name?: string;
  floor_order?: number;
  height_m?: number;
  space_type?: SpaceType;
}

/** Floor list response is a plain `{ items }` envelope (not paginated). */
export interface FloorListResponse {
  items: Floor[];
}
