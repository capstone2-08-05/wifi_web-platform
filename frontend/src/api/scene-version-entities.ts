import { api } from './client';
import type { UUID } from '@/types/common';
import type {
  SceneVersionObject,
  SceneVersionOpening,
  SceneVersionRoom,
  SceneVersionWall,
} from '@/types/scene-version-entities';

// 백엔드 §8 확정본 자식 리소스 CRUD.
// SceneVersion 의 rooms/walls/openings/objects 단건/수정/삭제.
// 변경 시 patch_log 자동 기록됨 (§9).

export const sceneVersionEntitiesApi = {
  // Walls
  getWall: (id: UUID) =>
    api.get<SceneVersionWall>(`/walls/${id}`).then((r) => r.data),
  patchWall: (id: UUID, body: Partial<SceneVersionWall>) =>
    api.patch<SceneVersionWall>(`/walls/${id}`, body).then((r) => r.data),
  deleteWall: (id: UUID) => api.delete<void>(`/walls/${id}`).then((r) => r.data),
  // §8 명세에 POST 가 명시되진 않았지만 RESTful 관례로 시도. 미지원이면 백엔드가 404/405 반환.
  addWall: (versionId: UUID, body: Partial<SceneVersionWall>) =>
    api
      .post<SceneVersionWall>(`/scene-versions/${versionId}/walls`, body)
      .then((r) => r.data),

  // Rooms
  getRoom: (id: UUID) =>
    api.get<SceneVersionRoom>(`/rooms/${id}`).then((r) => r.data),
  patchRoom: (id: UUID, body: Partial<SceneVersionRoom>) =>
    api.patch<SceneVersionRoom>(`/rooms/${id}`, body).then((r) => r.data),
  deleteRoom: (id: UUID) => api.delete<void>(`/rooms/${id}`).then((r) => r.data),
  addRoom: (versionId: UUID, body: Partial<SceneVersionRoom>) =>
    api
      .post<SceneVersionRoom>(`/scene-versions/${versionId}/rooms`, body)
      .then((r) => r.data),

  // Openings
  getOpening: (id: UUID) =>
    api.get<SceneVersionOpening>(`/openings/${id}`).then((r) => r.data),
  patchOpening: (id: UUID, body: Partial<SceneVersionOpening>) =>
    api.patch<SceneVersionOpening>(`/openings/${id}`, body).then((r) => r.data),
  deleteOpening: (id: UUID) =>
    api.delete<void>(`/openings/${id}`).then((r) => r.data),
  addOpening: (versionId: UUID, body: Partial<SceneVersionOpening>) =>
    api
      .post<SceneVersionOpening>(`/scene-versions/${versionId}/openings`, body)
      .then((r) => r.data),

  // Objects
  getObject: (id: UUID) =>
    api.get<SceneVersionObject>(`/objects/${id}`).then((r) => r.data),
  patchObject: (id: UUID, body: Partial<SceneVersionObject>) =>
    api.patch<SceneVersionObject>(`/objects/${id}`, body).then((r) => r.data),
  deleteObject: (id: UUID) =>
    api.delete<void>(`/objects/${id}`).then((r) => r.data),
  addObject: (versionId: UUID, body: Partial<SceneVersionObject>) =>
    api
      .post<SceneVersionObject>(`/scene-versions/${versionId}/objects`, body)
      .then((r) => r.data),
};
