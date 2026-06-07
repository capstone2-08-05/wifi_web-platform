import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sceneVersionEntitiesApi } from '@/api/scene-version-entities';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';
import type { DraftEntityKind, SceneVersion } from '@/types/scene';
import type {
  SceneVersionObject,
  SceneVersionOpening,
  SceneVersionRoom,
  SceneVersionWall,
} from '@/types/scene-version-entities';

// §8 확정본 자식 mutation 통합 훅 — use-draft-mutations 와 동일 인터페이스.
// EditorPage 가 draft / version 모드에 따라 둘 중 하나로 dispatch.

const ENTITY_LABEL: Record<DraftEntityKind, string> = {
  wall: '벽',
  room: '방',
  opening: '문·창',
  object: '객체',
};

const ENTITY_ARRAY: Record<
  DraftEntityKind,
  'walls' | 'rooms' | 'openings' | 'objects'
> = {
  wall: 'walls',
  room: 'rooms',
  opening: 'openings',
  object: 'objects',
};

type AnyVersionEntity =
  | SceneVersionWall
  | SceneVersionRoom
  | SceneVersionOpening
  | SceneVersionObject;
type AnyVersionEntityPatch =
  | Partial<SceneVersionWall>
  | Partial<SceneVersionRoom>
  | Partial<SceneVersionOpening>
  | Partial<SceneVersionObject>;

interface PatchVars {
  kind: DraftEntityKind;
  id: UUID;
  body: AnyVersionEntityPatch;
  silent?: boolean;
  /** 토스트에 표시할 엔티티 이름 override. opening 의 경우 '문' / '창문' 으로 세분화. */
  label?: string;
}

interface DeleteVars {
  kind: DraftEntityKind;
  id: UUID;
}

type AnyPatchResult =
  | SceneVersionWall
  | SceneVersionRoom
  | SceneVersionOpening
  | SceneVersionObject;

async function patchByKind(vars: PatchVars): Promise<AnyPatchResult> {
  switch (vars.kind) {
    case 'wall':
      return sceneVersionEntitiesApi.patchWall(vars.id, vars.body as Partial<SceneVersionWall>);
    case 'room':
      return sceneVersionEntitiesApi.patchRoom(vars.id, vars.body as Partial<SceneVersionRoom>);
    case 'opening':
      return sceneVersionEntitiesApi.patchOpening(vars.id, vars.body as Partial<SceneVersionOpening>);
    case 'object':
      return sceneVersionEntitiesApi.patchObject(vars.id, vars.body as Partial<SceneVersionObject>);
  }
}

async function deleteByKind(vars: DeleteVars): Promise<void> {
  switch (vars.kind) {
    case 'wall':
      return sceneVersionEntitiesApi.deleteWall(vars.id);
    case 'room':
      return sceneVersionEntitiesApi.deleteRoom(vars.id);
    case 'opening':
      return sceneVersionEntitiesApi.deleteOpening(vars.id);
    case 'object':
      return sceneVersionEntitiesApi.deleteObject(vars.id);
  }
}

interface CreateVars {
  versionId: UUID;
  kind: DraftEntityKind;
  body: AnyVersionEntityPatch;
}

async function addByKind(vars: CreateVars): Promise<AnyPatchResult> {
  switch (vars.kind) {
    case 'wall':
      return sceneVersionEntitiesApi.addWall(vars.versionId, vars.body as Partial<SceneVersionWall>);
    case 'room':
      return sceneVersionEntitiesApi.addRoom(vars.versionId, vars.body as Partial<SceneVersionRoom>);
    case 'opening':
      return sceneVersionEntitiesApi.addOpening(vars.versionId, vars.body as Partial<SceneVersionOpening>);
    case 'object':
      return sceneVersionEntitiesApi.addObject(vars.versionId, vars.body as Partial<SceneVersionObject>);
  }
}

type SceneVersionSnapshot = ReturnType<
  ReturnType<typeof useQueryClient>['getQueriesData']
>;

function snapshotVersions(qc: ReturnType<typeof useQueryClient>): SceneVersionSnapshot {
  return qc.getQueriesData({ queryKey: ['scene-version'] });
}

function restoreVersions(
  qc: ReturnType<typeof useQueryClient>,
  snap: SceneVersionSnapshot,
) {
  for (const [key, data] of snap) {
    qc.setQueryData(key, data);
  }
}

function patchVersionInCache(
  version: SceneVersion | undefined,
  vars: PatchVars,
): SceneVersion | undefined {
  if (!version) return version;
  const arrKey = ENTITY_ARRAY[vars.kind];
  const arr = version[arrKey] as AnyVersionEntity[] | undefined;
  if (!Array.isArray(arr)) return version;
  return {
    ...version,
    [arrKey]: arr.map((e) =>
      e.id === vars.id ? ({ ...e, ...vars.body } as AnyVersionEntity) : e,
    ),
  };
}

function deleteFromVersionCache(
  version: SceneVersion | undefined,
  vars: DeleteVars,
): SceneVersion | undefined {
  if (!version) return version;
  const arrKey = ENTITY_ARRAY[vars.kind];
  const arr = version[arrKey] as AnyVersionEntity[] | undefined;
  if (!Array.isArray(arr)) return version;
  return { ...version, [arrKey]: arr.filter((e) => e.id !== vars.id) };
}

export function usePatchVersionEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: PatchVars) => patchByKind(vars),
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: ['scene-version'] });
      const snapshot = snapshotVersions(qc);
      qc.setQueriesData<SceneVersion | undefined>(
        { queryKey: ['scene-version'] },
        (old) => patchVersionInCache(old, vars),
      );
      return { snapshot };
    },
    onError: (err, vars, context) => {
      if (context?.snapshot) restoreVersions(qc, context.snapshot);
      const e = err as HttpError | null;
      const label = vars.label ?? ENTITY_LABEL[vars.kind];
      toast.error(
        `${label} 수정 실패`,
        e?.message ?? '잠시 후 다시 시도해주세요.',
      );
    },
    onSuccess: (_data, vars) => {
      if (!vars.silent) {
        const label = vars.label ?? ENTITY_LABEL[vars.kind];
        toast.success(`${label} 수정 완료`);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['scene-version'] });
      qc.invalidateQueries({ queryKey: ['patch-logs'] });
    },
  });
}

export function useCreateVersionEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: CreateVars) => addByKind(vars),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['scene-version'] });
      qc.invalidateQueries({ queryKey: ['patch-logs'] });
      toast.success(`${ENTITY_LABEL[vars.kind]} 추가 완료`);
    },
    onError: (err, vars) => {
      const e = err as HttpError | null;
      const message =
        e?.status === 404 || e?.status === 405
          ? '백엔드가 확정 버전에 도형 추가를 지원하지 않습니다.'
          : e?.message ?? '잠시 후 다시 시도해주세요.';
      toast.error(`${ENTITY_LABEL[vars.kind]} 추가 실패`, message);
    },
  });
}

export function useDeleteVersionEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: DeleteVars) => deleteByKind(vars),
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: ['scene-version'] });
      const snapshot = snapshotVersions(qc);
      qc.setQueriesData<SceneVersion | undefined>(
        { queryKey: ['scene-version'] },
        (old) => deleteFromVersionCache(old, vars),
      );
      return { snapshot };
    },
    onError: (err, vars, context) => {
      if (context?.snapshot) restoreVersions(qc, context.snapshot);
      const e = err as HttpError | null;
      toast.error(
        `${ENTITY_LABEL[vars.kind]} 삭제 실패`,
        e?.message ?? '잠시 후 다시 시도해주세요.',
      );
    },
    onSuccess: (_data, vars) => {
      toast.info(`${ENTITY_LABEL[vars.kind]} 삭제됨`);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['scene-version'] });
      qc.invalidateQueries({ queryKey: ['patch-logs'] });
    },
  });
}
