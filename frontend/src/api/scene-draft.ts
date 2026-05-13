import { api } from './client';
import type { Paginated, UUID } from '@/types/common';
import type {
  AnalyzeFloorplanResponse,
  AnalyzeFromAssetResponse,
  DraftObject,
  DraftOpening,
  DraftRoom,
  DraftWall,
  SceneDraft,
  SceneDraftStatus,
  SceneDraftSummary,
} from '@/types/scene';

// AI 분석:
//  - 콜드 스타트 (SageMaker 컨테이너 새로 띄울 때) 약 10분
//  - 웜 상태에서는 추론 ~3초
// 글로벌 30s 로는 콜드 스타트는 물론, 일반 분석도 부족함.
// 백엔드 비동기 전환 (Job 큐 + 폴링) 끝나면 이 override 가 사라질 예정.
const ANALYZE_TIMEOUT_MS = 900_000; // 15분

export interface AnalyzeFloorplanParams {
  file: File;
  real_width_m?: number;
  project_id?: UUID;
  floor_id?: UUID;
  created_by?: string;
}

export interface AnalyzeFromAssetParams {
  asset_id: UUID;
  real_width_m: number;
}

export interface SceneDraftListParams {
  project_id?: UUID;
  floor_id?: UUID;
  status?: SceneDraftStatus;
  page?: number;
  page_size?: number;
}

export const sceneDraftApi = {
  // §6.1 POST /upload/floorplan/analyze
  analyzeFloorplan: ({ file, ...rest }: AnalyzeFloorplanParams) => {
    const fd = new FormData();
    fd.append('file', file);
    if (rest.real_width_m != null) fd.append('real_width_m', String(rest.real_width_m));
    if (rest.project_id) fd.append('project_id', rest.project_id);
    if (rest.floor_id) fd.append('floor_id', rest.floor_id);
    if (rest.created_by) fd.append('created_by', rest.created_by);
    return api
      .post<AnalyzeFloorplanResponse>('/upload/floorplan/analyze', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: ANALYZE_TIMEOUT_MS,
      })
      .then((r) => r.data);
  },

  // §6.1.1 POST /assets/{asset_id}/analyze
  analyzeFromAsset: ({ asset_id, real_width_m }: AnalyzeFromAssetParams) =>
    api
      .post<AnalyzeFromAssetResponse>(
        `/assets/${asset_id}/analyze`,
        { real_width_m },
        { timeout: ANALYZE_TIMEOUT_MS },
      )
      .then((r) => r.data),

  // §6.3 GET /scene-drafts  — 자식 배열 없는 summary 응답
  list: (params?: SceneDraftListParams) =>
    api.get<Paginated<SceneDraftSummary>>('/scene-drafts', { params }).then((r) => r.data),

  // §6.2 GET /scene-drafts/{id}
  get: (id: UUID) => api.get<SceneDraft>(`/scene-drafts/${id}`).then((r) => r.data),

  // §6.5 DELETE /scene-drafts/{id}
  remove: (id: UUID) => api.delete<void>(`/scene-drafts/${id}`).then((r) => r.data),

  // §6.4 Draft 자식 리소스 CRUD ----------------------------------------------

  // Rooms
  patchRoom: (roomId: UUID, body: Partial<DraftRoom>) =>
    api.patch<DraftRoom>(`/draft-rooms/${roomId}`, body).then((r) => r.data),
  deleteRoom: (roomId: UUID) => api.delete<void>(`/draft-rooms/${roomId}`).then((r) => r.data),
  addRoom: (draftId: UUID, body: Partial<DraftRoom>) =>
    api.post<DraftRoom>(`/scene-drafts/${draftId}/draft-rooms`, body).then((r) => r.data),

  // Walls
  patchWall: (wallId: UUID, body: Partial<DraftWall>) =>
    api.patch<DraftWall>(`/draft-walls/${wallId}`, body).then((r) => r.data),
  deleteWall: (wallId: UUID) => api.delete<void>(`/draft-walls/${wallId}`).then((r) => r.data),
  addWall: (draftId: UUID, body: Partial<DraftWall>) =>
    api.post<DraftWall>(`/scene-drafts/${draftId}/draft-walls`, body).then((r) => r.data),

  // Openings
  patchOpening: (openingId: UUID, body: Partial<DraftOpening>) =>
    api.patch<DraftOpening>(`/draft-openings/${openingId}`, body).then((r) => r.data),
  deleteOpening: (openingId: UUID) =>
    api.delete<void>(`/draft-openings/${openingId}`).then((r) => r.data),
  addOpening: (draftId: UUID, body: Partial<DraftOpening>) =>
    api.post<DraftOpening>(`/scene-drafts/${draftId}/draft-openings`, body).then((r) => r.data),

  // Objects
  patchObject: (objectId: UUID, body: Partial<DraftObject>) =>
    api.patch<DraftObject>(`/draft-objects/${objectId}`, body).then((r) => r.data),
  deleteObject: (objectId: UUID) =>
    api.delete<void>(`/draft-objects/${objectId}`).then((r) => r.data),
  addObject: (draftId: UUID, body: Partial<DraftObject>) =>
    api.post<DraftObject>(`/scene-drafts/${draftId}/draft-objects`, body).then((r) => r.data),
};
