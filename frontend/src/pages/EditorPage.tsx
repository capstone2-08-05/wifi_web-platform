import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Loader2, Map as MapIcon, Undo2 } from 'lucide-react';
import { useAppStore } from '@/stores/app-store';
import { useEditorStore } from '@/stores/editor-store';
import {
  useAnalyzeFloorplan,
  useCreateEmptyDraft,
  useDeleteSceneDraft,
  useDraftsForFloor,
  useRescaleSceneDraft,
  useSceneDraft,
} from '@/hooks/use-scene-draft';
import { useFloorplanJob } from '@/hooks/use-floorplan-job';
import {
  useFloorVersions,
  usePromoteDraft,
  useRescaleSceneVersion,
  useSceneVersion,
} from '@/hooks/use-scene-version';
import { useAssetDownloadUrl, useFloorAssets } from '@/hooks/use-assets';
import {
  linkFloorImageToAsset,
  saveLocalFloorplanImage,
  useLocalFloorplanImage,
} from '@/hooks/use-local-floorplan-image';
import {
  useCreateDraftEntity,
  useDeleteDraftEntity,
  usePatchDraftEntity,
} from '@/hooks/use-draft-mutations';
import {
  useCreateVersionEntity,
  useDeleteVersionEntity,
  usePatchVersionEntity,
} from '@/hooks/use-version-mutations';
import { CanvasToolbar } from '@/features/editor/CanvasToolbar';
import { CanvasArea } from '@/features/editor/CanvasArea';
import { DraftSceneCanvas } from '@/features/editor/DraftSceneCanvas';
import { PropertiesPanel } from '@/features/editor/PropertiesPanel';
import { ReviewCard } from '@/features/editor/ReviewCard';
import { PromotedCard } from '@/features/editor/PromotedCard';
import {
  parseGeometry,
  rotateGeometry90Cw,
  type GeoJsonGeometry,
} from '@/features/editor/geometry-utils';
import { versionToDraftShape } from '@/features/editor/version-as-draft';
import {
  loadCachedScaleRatio,
  saveCachedScaleRatio,
  loadCachedRealWidth,
  saveCachedRealWidth,
} from '@/features/editor/floorplan-image-extent';
import { toast } from '@/stores/toast-store';
import type { DraftEntityKind } from '@/types/scene';
import type { HttpError } from '@/api/client';
import type {
  SceneDraft,
  SceneVersion,
  SelectedEntityRef,
  SelectedEntityResolved,
} from '@/types/scene';

export default function EditorPage() {
  const projectId = useAppStore((s) => s.selectedProjectId);
  const floorId = useAppStore((s) => s.selectedFloorId);

  const tool = useEditorStore((s) => s.tool);
  const setTool = useEditorStore((s) => s.setTool);
  const registerActions = useEditorStore((s) => s.registerActions);
  const clearActions = useEditorStore((s) => s.clearActions);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const draftsQuery = useDraftsForFloor(projectId, floorId);
  const versionsQuery = useFloorVersions(floorId);

  const analyze = useAnalyzeFloorplan();
  const createEmptyDraft = useCreateEmptyDraft();
  const promote = usePromoteDraft();
  const removeDraft = useDeleteSceneDraft();
  const rescaleSceneDraft = useRescaleSceneDraft();
  const rescaleSceneVersion = useRescaleSceneVersion();
  const patchEntity = usePatchDraftEntity();
  const deleteEntity = useDeleteDraftEntity();
  const createEntity = useCreateDraftEntity();
  const patchVersionEntity = usePatchVersionEntity();
  const deleteVersionEntity = useDeleteVersionEntity();
  const createVersionEntity = useCreateVersionEntity();

  const [justPromoted, setJustPromoted] = useState<SceneVersion | null>(null);
  const [pendingFileName, setPendingFileName] = useState<string | null>(null);
  // 다중 선택 지원 — selectedRef 는 primary (length 1 일 때만 유효).
  const [selectedRefs, setSelectedRefs] = useState<SelectedEntityRef[]>([]);
  const selectedRef: SelectedEntityRef | null =
    selectedRefs.length === 1 ? selectedRefs[0] : null;
  const setSelectedRef = (ref: SelectedEntityRef | null) =>
    setSelectedRefs(ref ? [ref] : []);
  /** 도형 클릭/Shift+클릭 핸들러. additive=true 면 토글, false 면 단일 교체. */
  const handleSelect = (
    ref: SelectedEntityRef | null,
    options?: { additive?: boolean },
  ) => {
    if (!ref) {
      setSelectedRefs([]);
      return;
    }
    if (options?.additive) {
      setSelectedRefs((prev) => {
        const exists = prev.some((r) => r.kind === ref.kind && r.id === ref.id);
        return exists
          ? prev.filter((r) => !(r.kind === ref.kind && r.id === ref.id))
          : [...prev, ref];
      });
      return;
    }
    setSelectedRefs([ref]);
  };

  /** Marquee 드래그 종료 시 영역 내부 도형들을 한꺼번에 선택. */
  const handleSelectMany = (
    refs: SelectedEntityRef[],
    options?: { additive?: boolean },
  ) => {
    if (!options?.additive) {
      setSelectedRefs(refs);
      return;
    }
    setSelectedRefs((prev) => {
      const merged = [...prev];
      for (const r of refs) {
        const exists = merged.some((m) => m.kind === r.kind && m.id === r.id);
        if (!exists) merged.push(r);
      }
      return merged;
    });
  };

  // 분석 Job 추적 — POST /upload/floorplan/analyze 가 즉시 202 + job_id 만 반환.
  // 실제 완료 여부는 useFloorplanJob 폴링으로 확인.
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const jobPoll = useFloorplanJob(activeJobId);

  // list 응답은 summary (자식 배열 없음). 상세는 별도 GET 으로 가져와야 함.
  // 백엔드가 promote 후에도 draft 상태로 응답하는 케이스 회피:
  // 이미 어떤 scene_version 의 source_draft_id 로 사용된 draft 는 제외.
  const promotedDraftIds = useMemo(
    () =>
      new Set((versionsQuery.data ?? []).map((v) => v.source_draft_id).filter(Boolean)),
    [versionsQuery.data],
  );
  const activeDraftSummary =
    draftsQuery.data?.items.find(
      (d) => d.status === 'draft' && !promotedDraftIds.has(d.id),
    ) ?? null;
  const activeDraftQuery = useSceneDraft(activeDraftSummary?.id ?? null);
  const activeDraft = activeDraftQuery.data ?? null;

  // 현재 활성 버전 (없으면 가장 최근 버전) — draft 가 없을 때 캔버스에 표시.
  const versions = versionsQuery.data ?? [];
  const currentVersion =
    versions.find((v) => v.is_current) ?? versions[0] ?? null;
  // 활성 draft 가 없으면 현재 버전의 도형 detail 을 가져와 캔버스에 노출.
  const versionDetailQuery = useSceneVersion(
    !activeDraftSummary && currentVersion ? currentVersion.id : null,
  );
  const versionAsDraft: SceneDraft | null =
    !activeDraftSummary && versionDetailQuery.data
      ? versionToDraftShape(versionDetailQuery.data)
      : null;

  // selectedRef → 현재 편집 중인 SceneDraft (draft or version-as-draft) 에서 해소.
  const baseScene: SceneDraft | null = activeDraft ?? versionAsDraft;
  // 원본 도면 이미지(asset) — 캔버스 배경에 연하게 깔기 위해 가져옴.
  // 1순위: scene 의 source_asset_id (백엔드가 null 로 응답하는 경우 많음)
  // 2순위: 층의 floorplan 자산 중 가장 최근 것 (fallback).
  // Asset.storage_url 이 s3:// URI 라서 직접 못 쓰고, /download-url 로 presigned 받음.
  const sourceAssetId = baseScene?.source_asset_id ?? null;
  const allowUnversionedImageFallback = !!activeDraftSummary;
  const floorAssetsQuery = useFloorAssets(floorId, 'floorplan_image');
  const fallbackAsset = useMemo(() => {
    const list = floorAssetsQuery.data ?? [];
    if (list.length === 0) return null;
    // created_at 내림차순 정렬 후 첫 항목.
    return [...list].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  }, [floorAssetsQuery.data]);
  const effectiveAssetId =
    sourceAssetId ?? (allowUnversionedImageFallback ? fallbackAsset?.id : null) ?? null;
  const assetUrlQuery = useAssetDownloadUrl(effectiveAssetId);
  // 3순위: 사용자가 업로드한 파일을 base64 로 캐시해둔 로컬 이미지 (백엔드 미지원 우회).
  // sourceAssetId 알면 자산별 키 우선, 없으면 floor 키 fallback — 히스토리 버전 클릭 시
  // 그 당시 업로드 이미지가 별도 키로 보존돼 있어 정확히 복원됨.
  const localImage = useLocalFloorplanImage({
    floorId,
    sourceAssetId,
    allowFloorFallback: allowUnversionedImageFallback,
  });
  // 업로드 직후엔 floor 키에만 임시 저장돼있음 → draft.source_asset_id 알게 되는 순간
  // asset 키로 복사해 보존 (덮어쓰진 않음). 새 업로드가 floor 키를 덮어써도 이전 자산은
  // 자기 자산 키에 그대로 남음.
  useEffect(() => {
    if (floorId && sourceAssetId) linkFloorImageToAsset(floorId, sourceAssetId);
  }, [floorId, sourceAssetId]);
  // 자산 URL 은 <image href> 에서 직접 로드 가능한 절대 http(s) 만 사용.
  // local 모드의 `/assets/{id}/raw` 같은 상대경로는 (a) 프론트 origin 기준이라 백엔드를
  // 못 가리키고 (b) JWT 인증 헤더를 못 실어서 못 씀 → localStorage 캐시(base64) 로 fallback.
  const assetUrl = assetUrlQuery.data?.url ?? null;
  const usableAssetUrl =
    assetUrl && /^https?:\/\//i.test(assetUrl) ? assetUrl : null;
  const backgroundImageUrl = usableAssetUrl ?? localImage ?? null;
  const editingScene: SceneDraft | null = baseScene;
  const resolvedSelected = useMemo<SelectedEntityResolved | null>(() => {
    const scene = editingScene;
    if (!scene || !selectedRef) return null;
    switch (selectedRef.kind) {
      case 'wall': {
        const data = scene.walls.find((w) => w.id === selectedRef.id);
        return data ? { kind: 'wall', data } : null;
      }
      case 'room': {
        const data = scene.rooms.find((r) => r.id === selectedRef.id);
        return data ? { kind: 'room', data } : null;
      }
      case 'opening': {
        const data = scene.openings.find((o) => o.id === selectedRef.id);
        return data ? { kind: 'opening', data } : null;
      }
      case 'object': {
        const data = scene.objects.find((o) => o.id === selectedRef.id);
        return data ? { kind: 'object', data } : null;
      }
    }
  }, [editingScene, selectedRef]);

  // draft 가 바뀌면 (재분석 / 삭제 / promote) 선택 해제.
  // props 변화에 따른 state 조정 — render 중 비교 → setState 로 cascading render 회피.
  const [prevDraftId, setPrevDraftId] = useState<string | null>(activeDraft?.id ?? null);
  const currentDraftId = activeDraft?.id ?? null;
  if (prevDraftId !== currentDraftId) {
    setPrevDraftId(currentDraftId);
    setSelectedRef(null);
  }

  // 현재 편집 모드: draft (활성 draft 존재) 또는 version (확정된 버전만 존재).
  const isVersionEditing = !activeDraft;

  // ─ Undo 스택 ──────────────────────────────────────────────
  // PATCH / CREATE 추적. Delete 는 §8 명세상 복원이 까다로워 추적 안 함.
  // - PATCH undo → 이전 값으로 다시 PATCH
  // - CREATE undo → 생성된 엔티티 DELETE
  type HistoryEntry =
    | {
        action: 'patch';
        kind: DraftEntityKind;
        id: string;
        mode: 'draft' | 'version';
        beforeBody: Record<string, unknown>;
      }
    | {
        action: 'create';
        kind: DraftEntityKind;
        id: string;
        mode: 'draft' | 'version';
      };
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const HISTORY_MAX = 30;
  const pushHistory = (entry: HistoryEntry) => {
    setHistory((h) => [...h.slice(-(HISTORY_MAX - 1)), entry]);
  };

  /** 엔티티에서 body 키 목록에 해당하는 필드의 현재 값을 추출 (undo 용). */
  const captureBefore = (
    kind: DraftEntityKind,
    id: string,
    body: Record<string, unknown>,
  ): Record<string, unknown> | null => {
    if (!baseScene) return null;
    const list =
      kind === 'wall'
        ? baseScene.walls
        : kind === 'room'
        ? baseScene.rooms
        : kind === 'opening'
        ? baseScene.openings
        : baseScene.objects;
    const entity = (list as Array<{ id: string }>).find((e) => e.id === id) as
      | Record<string, unknown>
      | undefined;
    if (!entity) return null;
    const before: Record<string, unknown> = {};
    for (const key of Object.keys(body)) {
      before[key] = entity[key] ?? null;
    }
    return before;
  };

  /** PATCH 실행 + history 에 이전 값 push. silent 옵션 같이 전달. */
  const runPatch = (
    kind: DraftEntityKind,
    id: string,
    body: Record<string, unknown>,
    options?: { silent?: boolean; skipHistory?: boolean },
  ) => {
    if (!options?.skipHistory) {
      const beforeBody = captureBefore(kind, id, body);
      if (beforeBody) {
        pushHistory({
          action: 'patch',
          kind,
          id,
          mode: isVersionEditing ? 'version' : 'draft',
          beforeBody,
        });
      }
    }
    // opening 이면 현재 엔티티의 opening_type 으로 토스트 레이블 결정.
    let label: string | undefined;
    if (kind === 'opening') {
      const op = baseScene?.openings.find((o) => o.id === id);
      const ot = op?.opening_type;
      label = ot === 'door' ? '문' : ot === 'window' ? '창문' : '문·창';
    }
    const vars = { kind, id, body, silent: options?.silent, label };
    if (isVersionEditing) patchVersionEntity.mutate(vars);
    else patchEntity.mutate(vars);
  };

  /** Ctrl+Z — history pop. */
  const undo = () => {
    if (history.length === 0) {
      toast.info('되돌릴 변경이 없습니다');
      return;
    }
    const entry = history[history.length - 1];
    setHistory((h) => h.slice(0, -1));

    if (entry.action === 'patch') {
      const vars = {
        kind: entry.kind,
        id: entry.id,
        body: entry.beforeBody,
        silent: true,
      };
      if (entry.mode === 'version') patchVersionEntity.mutate(vars);
      else patchEntity.mutate(vars);
      toast.info('변경을 되돌렸습니다');
      return;
    }

    // action === 'create' → 삭제로 되돌림
    const dvars = { kind: entry.kind, id: entry.id };
    if (entry.mode === 'version') deleteVersionEntity.mutate(dvars);
    else deleteEntity.mutate(dvars);
    if (selectedRef?.id === entry.id) setSelectedRef(null);
    toast.info('생성을 되돌렸습니다');
  };

  const canUndo = history.length > 0;

  // 캔버스 단축키: Ctrl/Cmd+Z (undo), Ctrl/Cmd+A (전체 선택), Delete/Backspace (선택 삭제).
  // 입력 필드에 포커스된 경우 브라우저 기본 동작 유지.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inInput =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.getAttribute('contenteditable') === 'true';
      if (inInput) return;

      const isUndo = (e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z';
      if (isUndo) {
        e.preventDefault();
        undo();
        return;
      }

      const isSelectAll = (e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'a';
      if (isSelectAll) {
        if (!editingScene) return;
        const all: SelectedEntityRef[] = [
          ...editingScene.walls.map((w) => ({ kind: 'wall' as const, id: w.id })),
          // [room 비활성화] 전체 선택에서 room 제외. 다시 켜려면 아래 줄 주석 해제.
          // ...editingScene.rooms.map((r) => ({ kind: 'room' as const, id: r.id })),
          ...editingScene.openings.map((o) => ({ kind: 'opening' as const, id: o.id })),
          // [object 비활성화] 공간 편집 화면 전체 선택에서 가구/공간성 객체 제외.
          // ...editingScene.objects.map((o) => ({ kind: 'object' as const, id: o.id })),
        ];
        if (all.length === 0) return;
        e.preventDefault();
        setSelectedRefs(all);
        return;
      }

      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedRefs.length === 0) return;
        e.preventDefault();
        // handleDeleteSelected() 와 동일 로직. 후자가 useEffect 보다 뒤에 선언돼
        // TDZ 회피 위해 인라인.
        const onSuccess = () => setSelectedRefs([]);
        selectedRefs.forEach((r, idx) => {
          const last = idx === selectedRefs.length - 1;
          const vars = { kind: r.kind, id: r.id };
          if (isVersionEditing) {
            deleteVersionEntity.mutate(vars, last ? { onSuccess } : undefined);
          } else {
            deleteEntity.mutate(vars, last ? { onSuccess } : undefined);
          }
        });
        return;
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history, isVersionEditing, editingScene, selectedRefs]);

  // 드래그 (shape 평행이동 / vertex 개별 이동) 종료 시 새 geometry 로 PATCH.
  // 다중 선택 + shape 모드 → 같은 변위(delta) 를 모든 선택 도형에 적용 (그룹 이동).
  const handleDragEnd = (
    ref: SelectedEntityRef,
    geometry: GeoJsonGeometry,
  ) => {
    const body = geomFieldFor(ref.kind, geometry);
    if (!body) return;

    // 다중 선택 + 이동된 도형이 선택군 안에 있으면 → 그룹 이동.
    const isMulti =
      selectedRefs.length > 1 &&
      selectedRefs.some((r) => r.kind === ref.kind && r.id === ref.id);
    if (isMulti && baseScene) {
      const delta = computeDragDelta(ref, geometry, baseScene);
      if (delta) {
        const [dx, dy] = delta;
        for (const other of selectedRefs) {
          if (other.kind === ref.kind && other.id === ref.id) {
            runPatch(ref.kind, ref.id, body, { silent: true });
          } else {
            translateAndPatch(other, dx, dy);
          }
        }
        return;
      }
    }

    runPatch(ref.kind, ref.id, body, { silent: true });
  };

  /** 엔티티의 geometry 를 dx,dy 만큼 평행이동시킨 새 geometry 로 PATCH. */
  const translateAndPatch = (ref: SelectedEntityRef, dx: number, dy: number) => {
    if (!baseScene) return;
    const list =
      ref.kind === 'wall'
        ? baseScene.walls
        : ref.kind === 'room'
        ? baseScene.rooms
        : ref.kind === 'opening'
        ? baseScene.openings
        : baseScene.objects;
    const entity = (list as Array<{ id: string }>).find((e) => e.id === ref.id) as
      | Record<string, unknown>
      | undefined;
    if (!entity) return;
    const geomFieldName =
      ref.kind === 'wall'
        ? 'centerline_geom'
        : ref.kind === 'room'
        ? 'polygon_geom'
        : ref.kind === 'opening'
        ? 'line_geom'
        : 'point_geom';
    const g = parseGeometry(entity[geomFieldName] as Record<string, unknown> | null | undefined);
    if (!g) return;
    const moved = (() => {
      if (g.type === 'Point') {
        return {
          type: 'Point' as const,
          coordinates: [g.coordinates[0] + dx, g.coordinates[1] + dy] as [number, number],
        };
      }
      if (g.type === 'LineString') {
        return {
          type: 'LineString' as const,
          coordinates: g.coordinates.map(([x, y]) => [x + dx, y + dy] as [number, number]),
        };
      }
      return {
        type: 'Polygon' as const,
        coordinates: g.coordinates.map((ring) =>
          ring.map(([x, y]) => [x + dx, y + dy] as [number, number]),
        ),
      };
    })();
    const body = geomFieldFor(ref.kind, moved);
    if (body) runPatch(ref.kind, ref.id, body, { silent: true });
  };

  /** 그룹 리사이즈 종료 — 각 선택 도형 좌표 / 객체 W·H 를 같은 비율로 변환해 PATCH. */
  const handleGroupResizeEnd = ({
    fixed,
    sx,
    sy,
    refs,
  }: {
    fixed: [number, number];
    sx: number;
    sy: number;
    refs: SelectedEntityRef[];
  }) => {
    if (!baseScene) return;
    const scale = (x: number, y: number): [number, number] => [
      fixed[0] + (x - fixed[0]) * sx,
      fixed[1] + (y - fixed[1]) * sy,
    ];
    for (const ref of refs) {
      if (ref.kind === 'wall' || ref.kind === 'opening') {
        const list = ref.kind === 'wall' ? baseScene.walls : baseScene.openings;
        const field = ref.kind === 'wall' ? 'centerline_geom' : 'line_geom';
        const entity = (list as unknown as Array<{ id: string } & Record<string, unknown>>).find(
          (e) => e.id === ref.id,
        );
        const g = parseGeometry(entity?.[field] as Record<string, unknown> | null | undefined);
        if (g?.type !== 'LineString') continue;
        const scaled = {
          type: 'LineString' as const,
          coordinates: g.coordinates.map(([x, y]) => scale(x, y)),
        };
        const body = geomFieldFor(ref.kind, scaled);
        if (body) runPatch(ref.kind, ref.id, body, { silent: true });
      } else if (ref.kind === 'room') {
        const room = baseScene.rooms.find((r) => r.id === ref.id);
        const g = parseGeometry(room?.polygon_geom);
        if (g?.type !== 'Polygon') continue;
        const scaled = {
          type: 'Polygon' as const,
          coordinates: g.coordinates.map((ring) => ring.map(([x, y]) => scale(x, y))),
        };
        const body = geomFieldFor('room', scaled);
        if (body) runPatch('room', ref.id, body, { silent: true });
      } else {
        const obj = baseScene.objects.find((o) => o.id === ref.id);
        const g = parseGeometry(obj?.point_geom);
        if (g?.type !== 'Point') continue;
        const [cx, cy] = g.coordinates;
        const [nx, ny] = scale(cx, cy);
        const meta = (obj?.metadata_json ?? {}) as Record<string, unknown>;
        const curW =
          typeof meta.width_m === 'number' && meta.width_m > 0 ? meta.width_m : 1.6;
        const curH =
          typeof meta.height_m === 'number' && meta.height_m > 0 ? meta.height_m : 1.6;
        const newW = Math.max(0.2, curW * Math.abs(sx));
        const newH = Math.max(0.2, curH * Math.abs(sy));
        runPatch(
          'object',
          ref.id,
          {
            point_geom: { type: 'Point', coordinates: [nx, ny] },
            metadata_json: { ...meta, width_m: newW, height_m: newH },
          },
          { silent: true },
        );
      }
    }
  };

  // 선택된 엔티티들 삭제 (다중 선택 지원)
  const handleDeleteSelected = () => {
    if (selectedRefs.length === 0) return;
    const onSuccess = () => setSelectedRefs([]);
    selectedRefs.forEach((r, idx) => {
      const last = idx === selectedRefs.length - 1;
      const vars = { kind: r.kind, id: r.id };
      if (isVersionEditing) {
        deleteVersionEntity.mutate(vars, last ? { onSuccess } : undefined);
      } else {
        deleteEntity.mutate(vars, last ? { onSuccess } : undefined);
      }
    });
  };

  // 재질 변경 (벽/개구부/기둥 객체)
  const handleUpdateMaterial = (material: string) => {
    if (!selectedRef) return;
    if (selectedRef.kind === 'wall') {
      runPatch('wall', selectedRef.id, { material_label: material });
      return;
    }
    if (selectedRef.kind === 'opening' && baseScene) {
      const opening = baseScene.openings.find((o) => o.id === selectedRef.id);
      const meta = (opening?.metadata_json ?? {}) as Record<string, unknown>;
      // "material" 키 사용 — scene_version_export.py 가 metadata_json["material"] 을 읽음
      runPatch('opening', selectedRef.id, {
        metadata_json: { ...meta, material },
      });
      return;
    }
    if (selectedRef.kind === 'object' && baseScene) {
      const obj = baseScene.objects.find((o) => o.id === selectedRef.id);
      if (obj?.object_type !== 'column') return;
      const meta = (obj.metadata_json ?? {}) as Record<string, unknown>;
      runPatch('object', selectedRef.id, {
        metadata_json: { ...meta, material_label: material },
      });
    }
  };

  // 모든 문 재질 일괄 변경
  const handleBulkUpdateDoorMaterial = (material: string) => {
    if (!baseScene) return;
    const doors = baseScene.openings.filter((o) => o.opening_type === 'door');
    doors.forEach((op, i) => {
      const meta = (op.metadata_json ?? {}) as Record<string, unknown>;
      runPatch('opening', op.id, { metadata_json: { ...meta, material } }, {
        skipHistory: i > 0,
        silent: i < doors.length - 1,
      });
    });
  };

  // 모든 창문 재질 일괄 변경
  const handleBulkUpdateWindowMaterial = (material: string) => {
    if (!baseScene) return;
    const windows = baseScene.openings.filter((o) => o.opening_type === 'window');
    windows.forEach((op, i) => {
      const meta = (op.metadata_json ?? {}) as Record<string, unknown>;
      runPatch('opening', op.id, { metadata_json: { ...meta, material } }, {
        skipHistory: i > 0,
        silent: i < windows.length - 1,
      });
    });
  };

  // 벽 실측 길이 (m) 갱신 — metadata_json.dimension_match.user_meters 에 저장.
  // null 이면 사용자 override 해제 (OCR 추정값으로 fallback).
  const handleUpdateWallDimension = (meters: number | null) => {
    if (!selectedRef || selectedRef.kind !== 'wall') return;
    const wall = activeDraft?.walls.find((w) => w.id === selectedRef.id);
    if (!wall) return;
    const meta = (wall.metadata_json ?? {}) as Record<string, unknown>;
    const dim = (meta.dimension_match ?? {}) as Record<string, unknown>;
    const nextDim = { ...dim, user_meters: meters };
    const nextMeta = { ...meta, dimension_match: nextDim };
    runPatch('wall', selectedRef.id, { metadata_json: nextMeta });
  };

  /**
   * 선택된 벽/문/창의 실측값(m)을 기준으로 도면 전체를 비례 스케일.
   * draft 모드: POST /scene-drafts/{id}/rescale
   * version 모드: POST /scene-versions/{id}/rescale (동일 로직, 다른 엔드포인트)
   */
  const handleScaleAll = (targetMeters: number) => {
    if (!selectedRef || (selectedRef.kind !== 'wall' && selectedRef.kind !== 'opening')) return;
    if (!Number.isFinite(targetMeters) || targetMeters <= 0) return;

    const geomLength = (g: GeoJsonGeometry): number => {
      if (g.type !== 'LineString') return 0;
      let len = 0;
      for (let i = 1; i < g.coordinates.length; i++) {
        const [x0, y0] = g.coordinates[i - 1];
        const [x1, y1] = g.coordinates[i];
        len += Math.hypot(x1 - x0, y1 - y0);
      }
      return len;
    };

    // 소스 엔티티의 현재 길이로 factor 계산 — draft/version 공통으로 baseScene 사용.
    let currentLength: number | null = null;
    if (selectedRef.kind === 'wall') {
      const wall = baseScene?.walls.find((w) => w.id === selectedRef.id);
      const g = parseGeometry(wall?.centerline_geom);
      if (g?.type === 'LineString' && g.coordinates.length >= 2) currentLength = geomLength(g);
    } else {
      const op = baseScene?.openings.find((o) => o.id === selectedRef.id);
      const g = parseGeometry(op?.line_geom);
      if (g?.type === 'LineString' && g.coordinates.length >= 2) {
        currentLength = geomLength(g);
      } else if (op?.width_m) {
        const w = Number(op.width_m);
        if (Number.isFinite(w) && w > 0) currentLength = w;
      }
    }
    if (currentLength == null || currentLength <= 0) {
      toast.error('현재 길이를 구할 수 없어 scale 을 계산할 수 없습니다');
      return;
    }
    const factor = targetMeters / currentLength;
    if (!Number.isFinite(factor) || factor < 0.001 || factor > 1000) {
      toast.error('scale factor 가 비정상 범위(0.001~1000)입니다', `계산값 ${factor}`);
      return;
    }
    if (Math.abs(factor - 1) < 1e-4) {
      toast.info('이미 입력값과 같은 길이입니다');
      return;
    }

    const kindLabel = selectedRef.kind === 'wall' ? '벽' : '문/창';
    const ok = window.confirm(
      `도면 전체를 ${factor.toFixed(3)}× 로 재스케일합니다.\n` +
        `선택한 ${kindLabel} 길이: ${currentLength.toFixed(2)} m → ${targetMeters.toFixed(2)} m\n\n` +
        `※ Undo 한 번으로 되돌릴 수 없습니다. 진행할까요?`,
    );
    if (!ok) return;

    const successMsg = () =>
      toast.info(
        '도면 전체를 재스케일했습니다',
        `${factor.toFixed(3)}× — ${currentLength!.toFixed(2)} m → ${targetMeters.toFixed(2)} m`,
      );

    if (isVersionEditing) {
      const versionId = versionDetailQuery.data?.id;
      if (!versionId) return;
      const vFloorId = versionDetailQuery.data?.floor_id ?? null;
      const vAssetId = versionDetailQuery.data?.source_asset_id ?? null;
      rescaleSceneVersion.mutate(
        { id: versionId, factor, scaleSource: 'manual_rescale' },
        {
          onSuccess: () => {
            // versionToDraftShape 가 summary_json:{} 를 반환하므로 imageExtent 계산이
            // localStorage 캐시에 의존한다. 캐시 갱신 없이는 배경 이미지 크기가 구 scale
            // 로 고정돼 벡터와 어긋남 → factor 를 곱해 직접 갱신.
            for (const key of [vAssetId, vFloorId]) {
              if (!key) continue;
              const oldRatio = loadCachedScaleRatio(key);
              if (oldRatio != null) saveCachedScaleRatio(key, oldRatio * factor);
              const oldW = loadCachedRealWidth(key);
              if (oldW != null) saveCachedRealWidth(key, oldW * factor);
            }
            successMsg();
          },
        },
      );
    } else {
      if (!activeDraft) return;
      rescaleSceneDraft.mutate(
        { id: activeDraft.id, factor, scaleSource: 'manual_rescale' },
        { onSuccess: successMsg },
      );
    }
  };

  // 객체 종류 변경
  const handleUpdateObjectType = (objectType: string) => {
    if (!selectedRef || selectedRef.kind !== 'object') return;
    const vars = {
      kind: 'object' as const,
      id: selectedRef.id,
      body: { object_type: objectType },
    };
    if (isVersionEditing) {
      patchVersionEntity.mutate(vars);
    } else {
      patchEntity.mutate(vars);
    }
  };

  // 90° 시계방향 회전 (벽 / 개구부 / 방). 객체는 의미 없음.
  const handleRotateSelected = () => {
    if (!editingScene || !selectedRef || selectedRef.kind === 'object') return;
    const g = readGeometryOf(selectedRef, editingScene);
    if (!g) return;
    const rotated = rotateGeometry90Cw(g);
    const body = geomFieldFor(selectedRef.kind, rotated);
    if (!body) return;
    runPatch(selectedRef.kind, selectedRef.id, body);
  };

  // 좌측 도구바로 새 도형 추가 — Draft / Version 모드에 따라 dispatch.
  // 확정 버전은 §8 명세에 POST 가 명시되지 않아 백엔드 미지원 가능성 있음 (그 경우 토스트로 안내).
  /** 도구별 sticky/auto-reset 정책. 벽·방은 연속 작성이 자연스러우니 유지, 개구부·객체는 한 개씩 → 선택 모드로. */
  const shouldAutoResetToolAfterCreate = (kind: DraftEntityKind): boolean =>
    kind === 'opening' || kind === 'object';

  const handleCreate = (kind: DraftEntityKind, body: Record<string, unknown>) => {
    const afterCreate = (createdId: string, mode: 'draft' | 'version') => {
      pushHistory({ action: 'create', kind, id: createdId, mode });
      if (shouldAutoResetToolAfterCreate(kind)) {
        setTool('select');
      }
    };
    if (activeDraft) {
      createEntity.mutate(
        { draftId: activeDraft.id, kind, body },
        { onSuccess: (created) => afterCreate(created.id, 'draft') },
      );
      return;
    }
    if (currentVersion) {
      createVersionEntity.mutate(
        { versionId: currentVersion.id, kind, body },
        { onSuccess: (created) => afterCreate(created.id, 'version') },
      );
      return;
    }
    toast.info('편집할 도면이 없습니다', '먼저 도면을 업로드해주세요.');
  };

  // 객체 박스 리사이즈/위치 변경 → 즉시 PATCH (저장 버튼 없이 자동 저장).
  const handleResizeObject = (
    ref: SelectedEntityRef,
    widthM: number,
    heightM: number,
  ) => {
    if (ref.kind !== 'object' || !baseScene) return;
    const obj = baseScene.objects.find((o) => o.id === ref.id);
    if (!obj) return;
    const body = {
      metadata_json: { ...(obj.metadata_json ?? {}), width_m: widthM, height_m: heightM },
    };
    runPatch('object', ref.id, body, { silent: true });
  };

  const handleUpdateObjectPosition = (
    ref: SelectedEntityRef,
    x: number,
    y: number,
  ) => {
    if (ref.kind !== 'object') return;
    const body = { point_geom: { type: 'Point', coordinates: [x, y] } };
    runPatch('object', ref.id, body, { silent: true });
  };

  const nextVersionNo =
    versions.length > 0 ? Math.max(...versions.map((v) => v.version_no)) + 1 : 1;

  // Job 이 성공/실패로 정착되면 추적 종료
  useEffect(() => {
    if (jobPoll.isSucceeded || jobPoll.isFailed) {
      // 약간의 지연 후 클리어 (refetch invalidate + draft fetch 가 끝나도록)
      const t = window.setTimeout(() => setActiveJobId(null), 1000);
      return () => window.clearTimeout(t);
    }
  }, [jobPoll.isSucceeded, jobPoll.isFailed]);

  const handleFile = (file: File) => {
    setPendingFileName(file.name);
    if (!floorId) return;
    // 캔버스 배경용 로컬 캐시 — 백엔드가 source_asset_id 안 채워도 시각화 가능.
    saveLocalFloorplanImage(floorId, file);
    // scale_ratio 는 백엔드의 OCR 치수 자동 추정으로 결정됨. 사용자 입력 m 없음.
    analyze.mutate(
      {
        file,
        project_id: projectId ?? undefined,
        floor_id: floorId,
      },
      {
        onSuccess: (data) => {
          setActiveJobId(data.job_id);
        },
      },
    );
  };

  const handlePromote = () => {
    const draftId = activeDraftSummary?.id ?? activeDraft?.id;
    if (!draftId) return;
    promote.mutate(
      {
        draftId,
        body: { version_no: nextVersionNo, is_current: true },
      },
      { onSuccess: setJustPromoted },
    );
  };

  const handleStartBlankDraft = () => {
    if (!floorId) return;
    setPendingFileName(null);
    createEmptyDraft.mutate(floorId);
  };

  const handleResetDraft = () => {
    const draftId = activeDraftSummary?.id ?? activeDraft?.id;
    if (!draftId) return;
    // 삭제 성공 후 편집/업로드 UI 상태도 초기화 — 다시 업로드 흐름이 깨끗하게 시작되도록.
    removeDraft.mutate(draftId, {
      onSuccess: () => {
        setSelectedRef(null);
        setPendingFileName(null);
        setActiveJobId(null);
      },
    });
  };

  // 글로벌(헤더/PromotedCard) 업로드용 hidden input — CanvasArea 안 떠있을 때도 동작.
  const globalFileInputRef = useRef<HTMLInputElement>(null);
  const openFilePicker = () => {
    // CanvasArea 떠있으면 그쪽 입력으로, 아니면 글로벌.
    if (fileInputRef.current) {
      fileInputRef.current.click();
    } else {
      globalFileInputRef.current?.click();
    }
  };
  const handleGlobalFilePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    handleFile(f);
    toast.info(
      '도면 분석 시작',
      'AI 가 도면 치수를 읽어 자동으로 scale 을 추정합니다. 분석 후 벽별 실측값으로 보정할 수 있습니다.',
    );
  };
  // handleFile 안에서 saveLocalFloorplanImage 이미 호출됨.

  // Wire global header buttons (도면 불러오기 / 도면 저장하기) to this page.
  // 불러오기: 층이 선택돼있고 분석이 안 도는 중이고, 아직 활성 draft 가 없을 때만.
  //   (이미 draft 가 있는데 또 업로드하면 헷갈리므로 막음 — "다시 업로드" 는 리뷰 카드에서.)
  // 저장하기: 활성 draft 가 있고 다른 mutation 이 안 돌고 있을 때만.
  const isAnalyzing = analyze.isPending || jobPoll.isPolling;
  const canLoad =
    !!floorId && !isAnalyzing && !activeDraftSummary && !justPromoted;
  const canSave =
    !!activeDraftSummary && !isAnalyzing && !promote.isPending && !removeDraft.isPending;
  useEffect(() => {
    registerActions({
      onLoadFloorplan: canLoad ? openFilePicker : undefined,
      onSaveFloorplan: canSave ? handlePromote : undefined,
    });
    return () => clearActions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDraftSummary?.id, nextVersionNo, canLoad, canSave]);

  // draft 가 없고 확정된 버전만 있으면 PromotedCard 노출.
  const showCurrentVersionCard =
    !activeDraftSummary && !isAnalyzing && !justPromoted && !!currentVersion;
  const showOverlay =
    !floorId ||
    !!justPromoted ||
    isAnalyzing ||
    !!activeDraftSummary ||
    showCurrentVersionCard;

  return (
    <div className="flex h-full">
      <input
        ref={globalFileInputRef}
        type="file"
        accept="image/png,image/jpeg,application/pdf"
        className="hidden"
        onChange={handleGlobalFilePick}
      />
      <CanvasToolbar
        tool={tool}
        onChangeTool={setTool}
        onUploadClick={openFilePicker}
      />

      <div className="relative flex flex-1 overflow-hidden">
        {floorId && editingScene && (
          <button
            type="button"
            onClick={undo}
            disabled={!canUndo}
            title="되돌리기 (Ctrl+Z)"
            aria-label="되돌리기"
            className="absolute left-4 top-4 z-10 inline-flex items-center gap-1.5 rounded-full border bg-card/95 px-3 py-1.5 text-xs font-medium shadow-md backdrop-blur transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-card/95"
          >
            <Undo2 className="h-3.5 w-3.5" />
            되돌리기
            <kbd className="hidden rounded bg-muted px-1 text-[10px] font-mono text-muted-foreground sm:inline">
              Ctrl+Z
            </kbd>
          </button>
        )}
        {floorId ? (
          <>
            {editingScene ? (
              <DraftSceneCanvas
                draft={editingScene}
                selectedRefs={selectedRefs}
                onSelect={handleSelect}
                onSelectMany={handleSelectMany}
                onGroupResizeEnd={handleGroupResizeEnd}
                onDragEnd={handleDragEnd}
                onResizeObject={handleResizeObject}
                tool={tool}
                onCreate={handleCreate}
                backgroundImageUrl={backgroundImageUrl}
              />
            ) : currentVersion ? (
              // 버전이 선택돼있고 detail 로딩 중 — 파일 업로드 화면 대신 스피너.
              <div className="flex flex-1 items-center justify-center bg-muted/30">
                <div className="flex flex-col items-center gap-2 text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin" />
                  <p className="text-sm">버전 #{currentVersion.version_no} 도면 불러오는 중…</p>
                </div>
              </div>
            ) : (
              <CanvasArea
                fileInputRef={fileInputRef}
                isPending={isAnalyzing}
                errorMessage={
                  readError(analyze.error) ??
                  readError(createEmptyDraft.error) ??
                  undefined
                }
                selectedFileName={pendingFileName}
                onFile={handleFile}
                onStartBlank={floorId ? handleStartBlankDraft : undefined}
                isStartingBlank={createEmptyDraft.isPending}
              />
            )}

            {showOverlay &&
              (justPromoted ? (
                <OverlayLayer placement="center">
                  <PromotedCard
                    version={justPromoted}
                    versions={versions}
                    onEdit={() => toast.info('확정본 수정은 자동 저장됩니다')}
                    onReupload={() => {
                      setJustPromoted(null);
                      setPendingFileName(null);
                      openFilePicker();
                    }}
                    onStartBlank={
                      floorId
                        ? () => {
                            setJustPromoted(null);
                            setPendingFileName(null);
                            handleStartBlankDraft();
                          }
                        : undefined
                    }
                    isStartingBlank={createEmptyDraft.isPending}
                  />
                </OverlayLayer>
              ) : isAnalyzing ? (
                <OverlayLayer placement="center">
                  <BusyOverlay
                    title={analyzingTitle(jobPoll.job?.status)}
                    subtitle={analyzingSubtitle(jobPoll.job?.status)}
                  />
                </OverlayLayer>
              ) : activeDraft ? (
                // 분석 완료 후엔 캔버스가 보여야 하므로 카드를 우측 상단 코너로.
                <OverlayLayer placement="top-right">
                  <ReviewCard
                    draft={activeDraft}
                    nextVersionNo={nextVersionNo}
                    isPromoting={promote.isPending}
                    isResetting={removeDraft.isPending}
                    onPromote={handlePromote}
                    onReset={handleResetDraft}
                    errorMessage={
                      readError(promote.error) ?? readError(removeDraft.error) ?? undefined
                    }
                  />
                </OverlayLayer>
              ) : activeDraftSummary ? (
                <OverlayLayer placement="center">
                  <BusyOverlay title="Draft 불러오는 중..." />
                </OverlayLayer>
              ) : showCurrentVersionCard && currentVersion ? (
                <OverlayLayer placement="center">
                  <PromotedCard
                    version={currentVersion}
                    versions={versions}
                    onEdit={() => toast.info('확정본 수정은 자동 저장됩니다')}
                    onReupload={() => {
                      setPendingFileName(null);
                      openFilePicker();
                    }}
                    onStartBlank={
                      floorId
                        ? () => {
                            setPendingFileName(null);
                            handleStartBlankDraft();
                          }
                        : undefined
                    }
                    isStartingBlank={createEmptyDraft.isPending}
                  />
                </OverlayLayer>
              ) : null)}
          </>
        ) : (
          <NoFloorScreen hasProject={!!projectId} />
        )}
      </div>

      <PropertiesPanel
        selected={resolvedSelected}
        selectedCount={selectedRefs.length}
        onUpdateObjectType={handleUpdateObjectType}
        onDelete={handleDeleteSelected}
        onRotate={handleRotateSelected}
        onUpdateMaterial={handleUpdateMaterial}
        onUpdateWallDimension={handleUpdateWallDimension}
        onScaleAll={handleScaleAll}
        onUpdateObjectPosition={handleUpdateObjectPosition}
        onUpdateObjectSize={handleResizeObject}
        onBulkUpdateDoorMaterial={baseScene ? handleBulkUpdateDoorMaterial : undefined}
        onBulkUpdateWindowMaterial={baseScene ? handleBulkUpdateWindowMaterial : undefined}
        doorCount={baseScene?.openings.filter((o) => o.opening_type === 'door').length ?? 0}
        windowCount={baseScene?.openings.filter((o) => o.opening_type === 'window').length ?? 0}
        isSaving={patchEntity.isPending || patchVersionEntity.isPending}
        isDeleting={deleteEntity.isPending || deleteVersionEntity.isPending}
      />
    </div>
  );
}

/**
 * 캔버스 위 떠 있는 카드 컨테이너.
 * - center: 로딩 / 확정 완료 — 화면 정중앙, 넓게.
 * - top-right: 분석 결과 리뷰 — 우측 상단 코너, 좁게 (뒤의 도면이 보이도록).
 */
function OverlayLayer({
  children,
  placement = 'center',
}: {
  children: React.ReactNode;
  placement?: 'center' | 'top-right';
}) {
  const isCorner = placement === 'top-right';
  return (
    <div
      className={
        'pointer-events-none absolute inset-0 flex ' +
        (isCorner ? 'items-start justify-end p-3' : 'items-center justify-center p-10')
      }
    >
      <div
        className={
          'pointer-events-auto ' + (isCorner ? 'w-auto max-w-sm' : 'w-full max-w-xl')
        }
      >
        {children}
      </div>
    </div>
  );
}

function BusyOverlay({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border bg-card p-8 shadow-lg">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="text-sm font-medium">{title}</p>
      {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
    </div>
  );
}

function NoFloorScreen({ hasProject }: { hasProject: boolean }) {
  return (
    <div className="flex flex-1 items-center justify-center bg-muted/30 p-10">
      <div className="flex max-w-md flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-background p-10 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
          <MapIcon className="h-6 w-6 text-primary" strokeWidth={1.8} />
        </div>
        <p className="text-base font-semibold">
          {hasProject ? '층을 선택해주세요' : '프로젝트를 먼저 선택해주세요'}
        </p>
        <p className="text-xs leading-relaxed text-muted-foreground">
          대시보드에서 프로젝트와 도면(층)을 선택하면
          <br />
          편집을 시작할 수 있습니다.
        </p>
        <Link
          to="/dashboard"
          className="mt-2 inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
        >
          대시보드로 이동
          <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}

/** 엔티티 kind 에 따라 PATCH body 의 적절한 *_geom 필드명을 채워 반환. */
function geomFieldFor(
  kind: DraftEntityKind,
  geometry: GeoJsonGeometry,
): Record<string, unknown> | null {
  if (kind === 'wall' && geometry.type === 'LineString')
    return { centerline_geom: geometry };
  if (kind === 'opening' && geometry.type === 'LineString')
    return { line_geom: geometry };
  if (kind === 'room' && geometry.type === 'Polygon')
    return { polygon_geom: geometry };
  if (kind === 'object' && geometry.type === 'Point')
    return { point_geom: geometry };
  return null;
}

/**
 * 드래그된 엔티티의 변위(dx, dy) 계산.
 * 새 geometry 의 첫 좌표 - 이전 geometry 의 첫 좌표. 그룹 이동 시 다른 도형들에 같은 변위 적용.
 */
function computeDragDelta(
  ref: SelectedEntityRef,
  newGeom: GeoJsonGeometry,
  scene: SceneDraft,
): [number, number] | null {
  const oldGeom = readGeometryOf(ref, scene);
  if (!oldGeom) return null;
  const oldFirst = firstCoord(oldGeom);
  const newFirst = firstCoord(newGeom);
  if (!oldFirst || !newFirst) return null;
  return [newFirst[0] - oldFirst[0], newFirst[1] - oldFirst[1]];
}

function firstCoord(g: GeoJsonGeometry): [number, number] | null {
  if (g.type === 'Point') return g.coordinates as [number, number];
  if (g.type === 'LineString') return g.coordinates[0] ?? null;
  if (g.type === 'Polygon') return g.coordinates[0]?.[0] ?? null;
  return null;
}

/** 선택된 엔티티의 현재 geometry 를 읽어옴. */
function readGeometryOf(
  ref: SelectedEntityRef,
  draft: SceneDraft,
): GeoJsonGeometry | null {
  switch (ref.kind) {
    case 'wall':
      return parseGeometry(draft.walls.find((w) => w.id === ref.id)?.centerline_geom);
    case 'opening':
      return parseGeometry(draft.openings.find((o) => o.id === ref.id)?.line_geom);
    case 'room':
      return parseGeometry(draft.rooms.find((r) => r.id === ref.id)?.polygon_geom);
    case 'object':
      return parseGeometry(draft.objects.find((o) => o.id === ref.id)?.point_geom);
  }
}

function analyzingTitle(status: string | undefined): string {
  if (!status || status === 'pending') return '분석 Job 등록 중...';
  if (status === 'running') return '도면 분석 중...';
  return '도면 분석 중...';
}

function analyzingSubtitle(status: string | undefined): string {
  if (!status || status === 'pending') return '큐에 등록되어 곧 분석이 시작됩니다.';
  if (status === 'running')
    return '콜드 스타트는 최대 10분, 웜 상태에서는 수 초가 걸립니다.';
  return '잠시만 기다려주세요.';
}

function readError(err: unknown): string | null {
  if (!err) return null;
  const e = err as HttpError;
  if (e.code === 'INVALID_FILE_EXTENSION') return '지원하지 않는 파일 형식입니다.';
  if (e.code === 'FILE_SAVE_FAILED') return '파일 저장에 실패했습니다. 다시 시도해주세요.';
  if (e.code === 'INVALID_PROJECT_FLOOR_PAIR')
    return '프로젝트와 층의 매핑이 올바르지 않습니다.';
  if (e.code === 'SCENE_DRAFT_SAVE_FAILED') return '분석 결과 저장에 실패했습니다.';
  if (e.code === 'DRAFT_ALREADY_PROMOTED')
    return '이미 확정된 Draft 입니다. 다시 업로드 후 진행해주세요.';
  return e.message ?? '요청 처리 중 오류가 발생했습니다.';
}
