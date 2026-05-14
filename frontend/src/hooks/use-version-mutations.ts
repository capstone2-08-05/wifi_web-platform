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
  opening: '개구부',
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
      toast.error(
        `${ENTITY_LABEL[vars.kind]} 수정 실패`,
        e?.message ?? '잠시 후 다시 시도해주세요.',
      );
    },
    onSuccess: (_data, vars) => {
      if (!vars.silent) {
        toast.success(`${ENTITY_LABEL[vars.kind]} 수정 완료`);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['scene-version'] });
      qc.invalidateQueries({ queryKey: ['patch-logs'] });
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
