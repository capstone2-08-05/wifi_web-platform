import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sceneDraftApi } from '@/api/scene-draft';
import type { HttpError } from '@/api/client';
import { toast } from '@/stores/toast-store';
import type { UUID } from '@/types/common';
import type {
  DraftEntityKind,
  DraftObject,
  DraftOpening,
  DraftRoom,
  DraftWall,
  SceneDraft,
} from '@/types/scene';

const ENTITY_LABEL: Record<DraftEntityKind, string> = {
  wall: '벽',
  room: '방',
  opening: '문·창',
  object: '객체',
};

/** SceneDraft 의 어느 배열에 속하는지. */
const ENTITY_ARRAY: Record<
  DraftEntityKind,
  'walls' | 'rooms' | 'openings' | 'objects'
> = {
  wall: 'walls',
  room: 'rooms',
  opening: 'openings',
  object: 'objects',
};

type AnyDraftEntity = DraftWall | DraftRoom | DraftOpening | DraftObject;
type AnyDraftEntityPatch =
  | Partial<DraftWall>
  | Partial<DraftRoom>
  | Partial<DraftOpening>
  | Partial<DraftObject>;

interface PatchVars {
  kind: DraftEntityKind;
  id: UUID;
  body: AnyDraftEntityPatch;
  /** 토스트 옵션 — 자동 저장(드래그/입력)에선 토스트 노이즈 줄이려고 false */
  silent?: boolean;
  /** 토스트에 표시할 엔티티 이름 override. opening 의 경우 '문' / '창문' 으로 세분화. */
  label?: string;
}

interface DeleteVars {
  kind: DraftEntityKind;
  id: UUID;
}

interface CreateVars {
  draftId: UUID;
  kind: DraftEntityKind;
  body: AnyDraftEntityPatch;
}

type AnyPatchResult = DraftWall | DraftRoom | DraftOpening | DraftObject;

async function patchByKind(vars: PatchVars): Promise<AnyPatchResult> {
  switch (vars.kind) {
    case 'wall':
      return sceneDraftApi.patchWall(vars.id, vars.body as Partial<DraftWall>);
    case 'room':
      return sceneDraftApi.patchRoom(vars.id, vars.body as Partial<DraftRoom>);
    case 'opening':
      return sceneDraftApi.patchOpening(vars.id, vars.body as Partial<DraftOpening>);
    case 'object':
      return sceneDraftApi.patchObject(vars.id, vars.body as Partial<DraftObject>);
  }
}

async function deleteByKind(vars: DeleteVars): Promise<void> {
  switch (vars.kind) {
    case 'wall':
      return sceneDraftApi.deleteWall(vars.id);
    case 'room':
      return sceneDraftApi.deleteRoom(vars.id);
    case 'opening':
      return sceneDraftApi.deleteOpening(vars.id);
    case 'object':
      return sceneDraftApi.deleteObject(vars.id);
  }
}

async function addByKind(vars: CreateVars): Promise<AnyPatchResult> {
  switch (vars.kind) {
    case 'wall':
      return sceneDraftApi.addWall(vars.draftId, vars.body as Partial<DraftWall>);
    case 'room':
      return sceneDraftApi.addRoom(vars.draftId, vars.body as Partial<DraftRoom>);
    case 'opening':
      return sceneDraftApi.addOpening(vars.draftId, vars.body as Partial<DraftOpening>);
    case 'object':
      return sceneDraftApi.addObject(vars.draftId, vars.body as Partial<DraftObject>);
  }
}

// ============================================
// 캐시 조작 헬퍼 (optimistic update)
// ============================================

type SceneDraftSnapshot = ReturnType<
  ReturnType<typeof useQueryClient>['getQueriesData']
>;

function snapshotDrafts(qc: ReturnType<typeof useQueryClient>): SceneDraftSnapshot {
  return qc.getQueriesData({ queryKey: ['scene-draft'] });
}

function restoreDrafts(
  qc: ReturnType<typeof useQueryClient>,
  snap: SceneDraftSnapshot,
) {
  for (const [key, data] of snap) {
    qc.setQueryData(key, data);
  }
}

function patchDraftInCache(draft: SceneDraft | undefined, vars: PatchVars): SceneDraft | undefined {
  if (!draft) return draft;
  const arrKey = ENTITY_ARRAY[vars.kind];
  const arr = draft[arrKey] as AnyDraftEntity[] | undefined;
  if (!Array.isArray(arr)) return draft;
  return {
    ...draft,
    [arrKey]: arr.map((e) =>
      e.id === vars.id ? ({ ...e, ...vars.body } as AnyDraftEntity) : e,
    ),
  };
}

function deleteFromDraftCache(
  draft: SceneDraft | undefined,
  vars: DeleteVars,
): SceneDraft | undefined {
  if (!draft) return draft;
  const arrKey = ENTITY_ARRAY[vars.kind];
  const arr = draft[arrKey] as AnyDraftEntity[] | undefined;
  if (!Array.isArray(arr)) return draft;
  return { ...draft, [arrKey]: arr.filter((e) => e.id !== vars.id) };
}

// ============================================
// 훅
// ============================================

/**
 * Draft 자식 엔티티 PATCH (모든 kind 공통).
 * onMutate 로 캐시에 즉시 반영(optimistic) → 서버 응답 후 invalidate 로 정합화.
 */
export function usePatchDraftEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: PatchVars) => patchByKind(vars),
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: ['scene-draft'] });
      const snapshot = snapshotDrafts(qc);
      qc.setQueriesData<SceneDraft | undefined>(
        { queryKey: ['scene-draft'] },
        (old) => patchDraftInCache(old, vars),
      );
      return { snapshot };
    },
    onError: (err, vars, context) => {
      if (context?.snapshot) restoreDrafts(qc, context.snapshot);
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
      qc.invalidateQueries({ queryKey: ['scene-draft'] });
    },
  });
}

/**
 * Draft 자식 엔티티 DELETE.
 * onMutate 로 캐시에서 즉시 제거(optimistic).
 */
export function useDeleteDraftEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: DeleteVars) => deleteByKind(vars),
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: ['scene-draft'] });
      const snapshot = snapshotDrafts(qc);
      qc.setQueriesData<SceneDraft | undefined>(
        { queryKey: ['scene-draft'] },
        (old) => deleteFromDraftCache(old, vars),
      );
      return { snapshot };
    },
    onError: (err, vars, context) => {
      if (context?.snapshot) restoreDrafts(qc, context.snapshot);
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
      qc.invalidateQueries({ queryKey: ['scene-draft'] });
    },
  });
}

/**
 * Draft 자식 엔티티 CREATE.
 * 서버가 새 id 를 발급하므로 optimistic 은 생략 — refetch 로 최신 상태 받음.
 */
export function useCreateDraftEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: CreateVars) => addByKind(vars),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['scene-draft'] });
      toast.success(`${ENTITY_LABEL[vars.kind]} 추가 완료`);
    },
    onError: (err, vars) => {
      const e = err as HttpError | null;
      toast.error(
        `${ENTITY_LABEL[vars.kind]} 추가 실패`,
        e?.message ?? '잠시 후 다시 시도해주세요.',
      );
    },
  });
}
