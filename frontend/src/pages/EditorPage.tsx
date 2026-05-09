import { useState } from 'react';
import { Map } from 'lucide-react';
import { useAppStore } from '@/stores/app-store';
import {
  useAnalyzeFloorplan,
  useDeleteSceneDraft,
  useDraftsForFloor,
} from '@/hooks/use-scene-draft';
import { useFloorVersions, usePromoteDraft } from '@/hooks/use-scene-version';
import { UploadCard } from '@/features/editor/UploadCard';
import { ReviewCard } from '@/features/editor/ReviewCard';
import { PromotedCard } from '@/features/editor/PromotedCard';
import { BusyCard } from '@/features/editor/BusyCard';
import type { HttpError } from '@/api/client';
import type { SceneVersion } from '@/types/scene';

export default function EditorPage() {
  const projectId = useAppStore((s) => s.selectedProjectId);
  const floorId = useAppStore((s) => s.selectedFloorId);

  const draftsQuery = useDraftsForFloor(projectId, floorId);
  const versionsQuery = useFloorVersions(floorId);

  const analyze = useAnalyzeFloorplan();
  const promote = usePromoteDraft();
  const removeDraft = useDeleteSceneDraft();

  const [justPromoted, setJustPromoted] = useState<SceneVersion | null>(null);

  const activeDraft = draftsQuery.data?.items.find((d) => d.status === 'draft') ?? null;

  const versions = versionsQuery.data ?? [];
  const nextVersionNo =
    versions.length > 0 ? Math.max(...versions.map((v) => v.version_no)) + 1 : 1;

  const handleSubmit = (file: File, realWidthM: number) => {
    if (!floorId) return;
    analyze.mutate({
      file,
      real_width_m: realWidthM,
      project_id: projectId ?? undefined,
      floor_id: floorId,
    });
  };

  const handlePromote = () => {
    if (!activeDraft) return;
    promote.mutate(
      {
        draftId: activeDraft.id,
        body: { version_no: nextVersionNo, is_current: true },
      },
      { onSuccess: setJustPromoted },
    );
  };

  const handleResetDraft = () => {
    if (!activeDraft) return;
    removeDraft.mutate(activeDraft.id);
  };

  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">공간 편집</h1>
        <p className="text-sm text-muted-foreground">
          도면을 업로드하고 분석 결과를 검토·확정하세요.
        </p>
      </header>

      {!floorId ? (
        <NoFloorState hasProject={!!projectId} />
      ) : justPromoted ? (
        <PromotedCard
          version={justPromoted}
          onReupload={() => setJustPromoted(null)}
        />
      ) : analyze.isPending ? (
        <BusyCard title="도면 분석 중..." subtitle="이미지 분석은 수십 초 정도 걸릴 수 있습니다." />
      ) : draftsQuery.isLoading ? (
        <BusyCard title="Draft 확인 중..." />
      ) : activeDraft ? (
        <ReviewCard
          draft={activeDraft}
          nextVersionNo={nextVersionNo}
          isPromoting={promote.isPending}
          isResetting={removeDraft.isPending}
          onPromote={handlePromote}
          onReset={handleResetDraft}
          errorMessage={readError(promote.error) ?? readError(removeDraft.error) ?? undefined}
        />
      ) : (
        <UploadCard
          isPending={analyze.isPending}
          errorMessage={readError(analyze.error) ?? undefined}
          onSubmit={handleSubmit}
        />
      )}
    </div>
  );
}

function readError(err: unknown): string | null {
  if (!err) return null;
  const e = err as HttpError;
  if (e.code === 'INVALID_FILE_EXTENSION') return '지원하지 않는 파일 형식입니다.';
  if (e.code === 'FILE_SAVE_FAILED') return '파일 저장에 실패했습니다. 다시 시도해주세요.';
  if (e.code === 'INVALID_PROJECT_FLOOR_PAIR') return '프로젝트와 층의 매핑이 올바르지 않습니다.';
  if (e.code === 'SCENE_DRAFT_SAVE_FAILED') return '분석 결과 저장에 실패했습니다.';
  if (e.code === 'DRAFT_ALREADY_PROMOTED') return '이미 확정된 Draft 입니다. 다시 업로드 후 진행해주세요.';
  return e.message ?? '요청 처리 중 오류가 발생했습니다.';
}

function NoFloorState({ hasProject }: { hasProject: boolean }) {
  return (
    <div className="flex h-72 flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-card text-center">
      <Map className="h-8 w-8 text-muted-foreground/60" />
      <p className="text-sm font-medium">
        {hasProject ? '층을 선택해주세요' : '프로젝트를 먼저 선택해주세요'}
      </p>
      <p className="text-xs text-muted-foreground">상단 셀렉터에서 작업할 도면(층) 을 선택할 수 있습니다.</p>
    </div>
  );
}
