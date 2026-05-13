import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Loader2, Map as MapIcon } from 'lucide-react';
import { useAppStore } from '@/stores/app-store';
import { useEditorStore } from '@/stores/editor-store';
import {
  useAnalyzeFloorplan,
  useDeleteSceneDraft,
  useDraftsForFloor,
  useSceneDraft,
} from '@/hooks/use-scene-draft';
import { useFloorplanJob } from '@/hooks/use-floorplan-job';
import { useFloorVersions, usePromoteDraft } from '@/hooks/use-scene-version';
import {
  useCreateDraftEntity,
  useDeleteDraftEntity,
  usePatchDraftEntity,
} from '@/hooks/use-draft-mutations';
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
  const promote = usePromoteDraft();
  const removeDraft = useDeleteSceneDraft();
  const patchEntity = usePatchDraftEntity();
  const deleteEntity = useDeleteDraftEntity();
  const createEntity = useCreateDraftEntity();

  const [justPromoted, setJustPromoted] = useState<SceneVersion | null>(null);
  const [pendingFileName, setPendingFileName] = useState<string | null>(null);
  const [selectedRef, setSelectedRef] = useState<SelectedEntityRef | null>(null);

  // 분석 Job 추적 — POST /upload/floorplan/analyze 가 즉시 202 + job_id 만 반환.
  // 실제 완료 여부는 useFloorplanJob 폴링으로 확인.
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const jobPoll = useFloorplanJob(activeJobId);

  // list 응답은 summary (자식 배열 없음). 상세는 별도 GET 으로 가져와야 함.
  const activeDraftSummary =
    draftsQuery.data?.items.find((d) => d.status === 'draft') ?? null;
  const activeDraftQuery = useSceneDraft(activeDraftSummary?.id ?? null);
  const activeDraft = activeDraftQuery.data ?? null;

  // selectedRef → activeDraft 의 실제 엔티티로 해소
  const resolvedSelected = useMemo<SelectedEntityResolved | null>(() => {
    if (!activeDraft || !selectedRef) return null;
    switch (selectedRef.kind) {
      case 'wall': {
        const data = activeDraft.walls.find((w) => w.id === selectedRef.id);
        return data ? { kind: 'wall', data } : null;
      }
      case 'room': {
        const data = activeDraft.rooms.find((r) => r.id === selectedRef.id);
        return data ? { kind: 'room', data } : null;
      }
      case 'opening': {
        const data = activeDraft.openings.find((o) => o.id === selectedRef.id);
        return data ? { kind: 'opening', data } : null;
      }
      case 'object': {
        const data = activeDraft.objects.find((o) => o.id === selectedRef.id);
        return data ? { kind: 'object', data } : null;
      }
    }
  }, [activeDraft, selectedRef]);

  // draft 가 바뀌면 (재분석 / 삭제 / promote) 선택 해제.
  // props 변화에 따른 state 조정 — render 중 비교 → setState 로 cascading render 회피.
  const [prevDraftId, setPrevDraftId] = useState<string | null>(activeDraft?.id ?? null);
  const currentDraftId = activeDraft?.id ?? null;
  if (prevDraftId !== currentDraftId) {
    setPrevDraftId(currentDraftId);
    setSelectedRef(null);
  }

  // 드래그 (shape 평행이동 / vertex 개별 이동) 종료 시 새 geometry 로 PATCH.
  // canvas 가 이미 새 GeoJSON 까지 만들어 넘겨주므로, 여기선 적절한 *_geom 필드로 매핑만.
  const handleDragEnd = (
    ref: SelectedEntityRef,
    geometry: GeoJsonGeometry,
  ) => {
    const body = geomFieldFor(ref.kind, geometry);
    if (!body) return;
    patchEntity.mutate({ kind: ref.kind, id: ref.id, body, silent: true });
  };

  // 선택된 엔티티 삭제
  const handleDeleteSelected = () => {
    if (!selectedRef) return;
    deleteEntity.mutate(
      { kind: selectedRef.kind, id: selectedRef.id },
      { onSuccess: () => setSelectedRef(null) },
    );
  };

  // 벽 재질 변경
  const handleUpdateMaterial = (material: string) => {
    if (!selectedRef || selectedRef.kind !== 'wall') return;
    patchEntity.mutate({
      kind: 'wall',
      id: selectedRef.id,
      body: { material_label: material },
    });
  };

  // 90° 시계방향 회전 (벽 / 개구부 / 방). 객체는 의미 없음.
  const handleRotateSelected = () => {
    if (!activeDraft || !selectedRef || selectedRef.kind === 'object') return;
    const g = readGeometryOf(selectedRef, activeDraft);
    if (!g) return;
    const rotated = rotateGeometry90Cw(g);
    const body = geomFieldFor(selectedRef.kind, rotated);
    if (!body) return;
    patchEntity.mutate({ kind: selectedRef.kind, id: selectedRef.id, body });
  };

  // 좌측 도구바로 새 도형 추가
  const handleCreate = (kind: DraftEntityKind, body: Record<string, unknown>) => {
    if (!activeDraft) return;
    createEntity.mutate({ draftId: activeDraft.id, kind, body });
  };

  const versions = versionsQuery.data ?? [];
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

  const handleFile = (file: File, realWidthM: number) => {
    setPendingFileName(file.name);
    if (!floorId) return;
    analyze.mutate(
      {
        file,
        real_width_m: realWidthM,
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

  const handleResetDraft = () => {
    const draftId = activeDraftSummary?.id ?? activeDraft?.id;
    if (!draftId) return;
    removeDraft.mutate(draftId);
  };

  const openFilePicker = () => fileInputRef.current?.click();

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

  const showOverlay =
    !floorId || !!justPromoted || isAnalyzing || !!activeDraftSummary;

  return (
    <div className="flex h-full">
      <CanvasToolbar
        tool={tool}
        onChangeTool={setTool}
        onUploadClick={openFilePicker}
      />

      <div className="relative flex flex-1 overflow-hidden">
        {floorId ? (
          <>
            {activeDraft ? (
              <DraftSceneCanvas
                draft={activeDraft}
                selectedRef={selectedRef}
                onSelect={setSelectedRef}
                onDragEnd={handleDragEnd}
                tool={tool}
                onCreate={handleCreate}
              />
            ) : (
              <CanvasArea
                fileInputRef={fileInputRef}
                isPending={isAnalyzing}
                errorMessage={readError(analyze.error) ?? undefined}
                selectedFileName={pendingFileName}
                onFile={handleFile}
              />
            )}

            {showOverlay && (
              <OverlayLayer>
                {justPromoted ? (
                  <PromotedCard
                    version={justPromoted}
                    onReupload={() => {
                      setJustPromoted(null);
                      setPendingFileName(null);
                    }}
                  />
                ) : isAnalyzing ? (
                  <BusyOverlay
                    title={analyzingTitle(jobPoll.job?.status)}
                    subtitle={analyzingSubtitle(jobPoll.job?.status)}
                  />
                ) : activeDraft ? (
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
                ) : activeDraftSummary ? (
                  <BusyOverlay title="Draft 불러오는 중..." />
                ) : null}
              </OverlayLayer>
            )}
          </>
        ) : (
          <NoFloorScreen hasProject={!!projectId} />
        )}
      </div>

      <PropertiesPanel
        selected={resolvedSelected}
        onDelete={handleDeleteSelected}
        onRotate={handleRotateSelected}
        onUpdateMaterial={handleUpdateMaterial}
        isSaving={patchEntity.isPending}
        isDeleting={deleteEntity.isPending}
      />
    </div>
  );
}

function OverlayLayer({ children }: { children: React.ReactNode }) {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-10">
      <div className="pointer-events-auto w-full max-w-xl">{children}</div>
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
