import { useEffect, useRef, useState } from 'react';
import { Loader2, Map as MapIcon } from 'lucide-react';
import { useAppStore } from '@/stores/app-store';
import { useEditorStore } from '@/stores/editor-store';
import {
  useAnalyzeFloorplan,
  useDeleteSceneDraft,
  useDraftsForFloor,
  useSceneDraft,
} from '@/hooks/use-scene-draft';
import { useFloorVersions, usePromoteDraft } from '@/hooks/use-scene-version';
import { CanvasToolbar } from '@/features/editor/CanvasToolbar';
import { CanvasArea } from '@/features/editor/CanvasArea';
import {
  PropertiesPanel,
  type SelectedObject,
} from '@/features/editor/PropertiesPanel';
import { ReviewCard } from '@/features/editor/ReviewCard';
import { PromotedCard } from '@/features/editor/PromotedCard';
import type { HttpError } from '@/api/client';
import type { SceneVersion } from '@/types/scene';

// Figma 디자인의 우측 패널 mock 데이터. 실제 캔버스 선택과 연동되기 전까지 사용.
const DEMO_SELECTED: SelectedObject = {
  typeLabel: '가구 (테이블)',
  scanned: true,
  width: 120,
  height: 40,
  x: 350,
  y: 200,
  material: '목재 테이블 (신호 감쇠 보통)',
};

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

  const [justPromoted, setJustPromoted] = useState<SceneVersion | null>(null);
  const [pendingFileName, setPendingFileName] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedObject | null>(DEMO_SELECTED);

  // list 응답은 summary (자식 배열 없음). 상세는 별도 GET 으로 가져와야 함.
  const activeDraftSummary =
    draftsQuery.data?.items.find((d) => d.status === 'draft') ?? null;
  const activeDraftQuery = useSceneDraft(activeDraftSummary?.id ?? null);
  const activeDraft = activeDraftQuery.data ?? null;

  const versions = versionsQuery.data ?? [];
  const nextVersionNo =
    versions.length > 0 ? Math.max(...versions.map((v) => v.version_no)) + 1 : 1;

  const handleFile = (file: File) => {
    setPendingFileName(file.name);
    if (!floorId) return;
    analyze.mutate({
      file,
      real_width_m: 10,
      project_id: projectId ?? undefined,
      floor_id: floorId,
    });
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
  useEffect(() => {
    registerActions({
      onLoadFloorplan: openFilePicker,
      onSaveFloorplan: handlePromote,
    });
    return () => clearActions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDraftSummary?.id, nextVersionNo]);

  const isBusy = analyze.isPending;
  const showOverlay =
    !floorId || !!justPromoted || isBusy || !!activeDraftSummary;

  return (
    <div className="flex h-full">
      <CanvasToolbar
        tool={tool}
        onChangeTool={setTool}
        onUploadClick={openFilePicker}
      />

      <div className="relative flex flex-1 overflow-hidden">
        <CanvasArea
          fileInputRef={fileInputRef}
          isPending={isBusy}
          errorMessage={readError(analyze.error) ?? undefined}
          selectedFileName={pendingFileName}
          onFile={handleFile}
        />

        {showOverlay && (
          <OverlayLayer>
            {!floorId ? (
              <NoFloorCard hasProject={!!projectId} />
            ) : justPromoted ? (
              <PromotedCard
                version={justPromoted}
                onReupload={() => {
                  setJustPromoted(null);
                  setPendingFileName(null);
                }}
              />
            ) : analyze.isPending ? (
              <BusyOverlay
                title="도면 분석 중..."
                subtitle="이미지 분석은 수십 초 정도 걸릴 수 있습니다."
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
      </div>

      <PropertiesPanel
        selected={selected}
        onChange={setSelected}
        onDelete={() => setSelected(null)}
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

function NoFloorCard({ hasProject }: { hasProject: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-card p-10 text-center shadow-sm">
      <MapIcon className="h-8 w-8 text-muted-foreground/60" />
      <p className="text-sm font-medium">
        {hasProject ? '층을 선택해주세요' : '프로젝트를 먼저 선택해주세요'}
      </p>
      <p className="text-xs text-muted-foreground">
        대시보드에서 작업할 도면(층)을 선택하면 편집을 시작할 수 있습니다.
      </p>
    </div>
  );
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
