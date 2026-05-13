import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { sceneVersionEntitiesApi } from '@/api/scene-version-entities';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';
import type {
  SceneVersionObject,
  SceneVersionOpening,
  SceneVersionRoom,
  SceneVersionWall,
} from '@/types/scene-version-entities';

// §8 확정본 자식 CRUD 훅 모음.
// 현재 시연 시나리오에선 promote 후 편집을 안 하므로 미사용 — 후속 화면 구현 시 사용.

const ENTITY_LABEL = { wall: '벽', room: '방', opening: '개구부', object: '객체' } as const;

function invalidateVersion(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ['scene-version'] });
  qc.invalidateQueries({ queryKey: ['patch-logs'] });
}

// ── GET 단건 ────────────────────────────────────────────

export function useSceneVersionWall(id: UUID | null) {
  return useQuery({
    queryKey: ['scene-version-wall', id] as const,
    queryFn: () => sceneVersionEntitiesApi.getWall(id as UUID),
    enabled: !!id,
  });
}

export function useSceneVersionRoom(id: UUID | null) {
  return useQuery({
    queryKey: ['scene-version-room', id] as const,
    queryFn: () => sceneVersionEntitiesApi.getRoom(id as UUID),
    enabled: !!id,
  });
}

export function useSceneVersionOpening(id: UUID | null) {
  return useQuery({
    queryKey: ['scene-version-opening', id] as const,
    queryFn: () => sceneVersionEntitiesApi.getOpening(id as UUID),
    enabled: !!id,
  });
}

export function useSceneVersionObject(id: UUID | null) {
  return useQuery({
    queryKey: ['scene-version-object', id] as const,
    queryFn: () => sceneVersionEntitiesApi.getObject(id as UUID),
    enabled: !!id,
  });
}

// ── PATCH ──────────────────────────────────────────────

export function usePatchSceneVersionWall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: UUID; body: Partial<SceneVersionWall> }) =>
      sceneVersionEntitiesApi.patchWall(id, body),
    onSuccess: () => {
      invalidateVersion(qc);
      toast.success(`${ENTITY_LABEL.wall} 수정 완료`);
    },
    onError: (err) => emitErrorToast('wall', err),
  });
}

export function usePatchSceneVersionRoom() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: UUID; body: Partial<SceneVersionRoom> }) =>
      sceneVersionEntitiesApi.patchRoom(id, body),
    onSuccess: () => {
      invalidateVersion(qc);
      toast.success(`${ENTITY_LABEL.room} 수정 완료`);
    },
    onError: (err) => emitErrorToast('room', err),
  });
}

export function usePatchSceneVersionOpening() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: UUID; body: Partial<SceneVersionOpening> }) =>
      sceneVersionEntitiesApi.patchOpening(id, body),
    onSuccess: () => {
      invalidateVersion(qc);
      toast.success(`${ENTITY_LABEL.opening} 수정 완료`);
    },
    onError: (err) => emitErrorToast('opening', err),
  });
}

export function usePatchSceneVersionObject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: UUID; body: Partial<SceneVersionObject> }) =>
      sceneVersionEntitiesApi.patchObject(id, body),
    onSuccess: () => {
      invalidateVersion(qc);
      toast.success(`${ENTITY_LABEL.object} 수정 완료`);
    },
    onError: (err) => emitErrorToast('object', err),
  });
}

// ── DELETE ─────────────────────────────────────────────

export function useDeleteSceneVersionWall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: UUID) => sceneVersionEntitiesApi.deleteWall(id),
    onSuccess: () => {
      invalidateVersion(qc);
      toast.info(`${ENTITY_LABEL.wall} 삭제됨`);
    },
    onError: (err) => emitErrorToast('wall', err),
  });
}

export function useDeleteSceneVersionRoom() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: UUID) => sceneVersionEntitiesApi.deleteRoom(id),
    onSuccess: () => {
      invalidateVersion(qc);
      toast.info(`${ENTITY_LABEL.room} 삭제됨`);
    },
    onError: (err) => emitErrorToast('room', err),
  });
}

export function useDeleteSceneVersionOpening() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: UUID) => sceneVersionEntitiesApi.deleteOpening(id),
    onSuccess: () => {
      invalidateVersion(qc);
      toast.info(`${ENTITY_LABEL.opening} 삭제됨`);
    },
    onError: (err) => emitErrorToast('opening', err),
  });
}

export function useDeleteSceneVersionObject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: UUID) => sceneVersionEntitiesApi.deleteObject(id),
    onSuccess: () => {
      invalidateVersion(qc);
      toast.info(`${ENTITY_LABEL.object} 삭제됨`);
    },
    onError: (err) => emitErrorToast('object', err),
  });
}

function emitErrorToast(kind: keyof typeof ENTITY_LABEL, err: unknown) {
  const e = err as HttpError | null;
  toast.error(
    `${ENTITY_LABEL[kind]} 변경 실패`,
    e?.message ?? '잠시 후 다시 시도해주세요.',
  );
}
