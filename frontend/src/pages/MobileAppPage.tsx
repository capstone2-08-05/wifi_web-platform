import { useMemo, useState } from 'react';
import { CheckCircle2, Loader2, Sparkles } from 'lucide-react';
import type { HttpError } from '@/api/client';
import { useAppStore } from '@/stores/app-store';
import { useFloorVersions, useSceneVersion } from '@/hooks/use-scene-version';
import { useFloorRfRuns } from '@/hooks/use-rf-run';
import { useApLayouts, useCreateApLayout } from '@/hooks/use-ap-layouts';
import { useFloorAssets, useAssetDownloadUrl } from '@/hooks/use-assets';
import { useLocalFloorplanImage } from '@/hooks/use-local-floorplan-image';
import { useApRecommendation } from '@/hooks/use-ap-recommendation';
import { versionToDraftShape } from '@/features/editor/version-as-draft';
import { DEFAULT_TX_POWER_DBM } from '@/features/simulation/SimulationCanvas';
import {
  apLayoutsToCanvas,
  apsFromRfRunRequest,
  nextApLayoutName,
} from '@/features/ap-recommendation/ap-canvas-mappers';
import { ApRecommendationCanvas } from '@/features/ap-recommendation/ApRecommendationCanvas';
import {
  AP_DEFAULT_Z_M,
  buildApRecommendationPayload,
  isValidSelectionBBox,
  normalizeRecommendations,
  type MeterBBox,
} from '@/features/ap-recommendation/recommendation-utils';
import type { ApRecommendationResult } from '@/types/ap-recommendation';
import { cn } from '@/lib/utils';

type PageStatus = 'idle' | 'areaSelected' | 'loading' | 'success' | 'error';

const PROGRESS_STEPS = [
  { id: 1, label: '우선 개선 영역 선택' },
  { id: 2, label: '최적 위치 계산' },
  { id: 3, label: '추천 위치 선택' },
] as const;

const CARD_BORDER = 'border-[#E5EAF2]';

export default function MobileAppPage() {
  const floorId = useAppStore((s) => s.selectedFloorId);
  const versionsQuery = useFloorVersions(floorId);
  const currentVersion =
    versionsQuery.data?.find((v) => v.is_current) ?? versionsQuery.data?.[0] ?? null;
  const sceneVersionId = currentVersion?.id ?? null;

  const versionDetailQuery = useSceneVersion(sceneVersionId);
  const versionDetail = versionDetailQuery.data ?? null;

  const versionAsDraft = versionDetail ? versionToDraftShape(versionDetail) : null;
  const sourceAssetId = versionAsDraft?.source_asset_id ?? null;
  const floorAssetsQuery = useFloorAssets(floorId, 'floorplan_image');
  const fallbackAsset = (floorAssetsQuery.data ?? [])
    .slice()
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  const effectiveAssetId = sourceAssetId ?? fallbackAsset?.id ?? null;
  const assetUrlQuery = useAssetDownloadUrl(effectiveAssetId);
  const localImage = useLocalFloorplanImage({ floorId, sourceAssetId });
  const assetUrl = assetUrlQuery.data?.url ?? null;
  const usableAssetUrl =
    assetUrl && /^https?:\/\//i.test(assetUrl) ? assetUrl : null;
  const backgroundImageUrl = usableAssetUrl ?? localImage ?? null;

  const rfRunsQuery = useFloorRfRuns(floorId, { status: 'succeeded', page_size: 5 });
  const latestRfRun = useMemo(() => {
    const items = rfRunsQuery.data?.items ?? [];
    if (!sceneVersionId) return items[0] ?? null;
    return (
      items.find((r) => r.scene_version_id === sceneVersionId) ?? items[0] ?? null
    );
  }, [rfRunsQuery.data, sceneVersionId]);
  const latestRfRunId = latestRfRun?.id ?? null;
  const apLayoutsQuery = useApLayouts(latestRfRunId);

  const existingAps = useMemo(() => {
    const layouts = apLayoutsQuery.data ?? [];
    if (layouts.length > 0) return apLayoutsToCanvas(layouts);
    return apsFromRfRunRequest(latestRfRun?.request_json as Record<string, unknown> | undefined);
  }, [apLayoutsQuery.data, latestRfRun?.request_json]);

  const [selectionBBox, setSelectionBBox] = useState<MeterBBox | null>(null);
  const [recommendations, setRecommendations] = useState<ApRecommendationResult[]>([]);
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [savedRank, setSavedRank] = useState<number | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  const recommendMutation = useApRecommendation();
  const createLayout = useCreateApLayout();

  const pageStatus: PageStatus = useMemo(() => {
    if (recommendMutation.isPending) return 'loading';
    if (recommendMutation.isError) return 'error';
    if (recommendations.length > 0) return 'success';
    if (isValidSelectionBBox(selectionBBox)) return 'areaSelected';
    return 'idle';
  }, [
    recommendMutation.isPending,
    recommendMutation.isError,
    recommendations.length,
    selectionBBox,
  ]);

  const activeStep = useMemo(() => {
    if (savedRank != null || selectedRank != null) return 3;
    if (pageStatus === 'success') return 3;
    if (pageStatus === 'loading') return 2;
    if (pageStatus === 'areaSelected') return 1;
    return 1;
  }, [pageStatus, selectedRank, savedRank]);

  const handleSelectionChange = (bbox: MeterBBox | null) => {
    setSelectionBBox(bbox);
    setRecommendations([]);
    setSelectedRank(null);
    setSavedRank(null);
    setPageError(null);
    recommendMutation.reset();
  };

  const handleRecommend = () => {
    if (!sceneVersionId) {
      setPageError('도면 정보를 불러올 수 없습니다.');
      return;
    }
    if (!isValidSelectionBBox(selectionBBox)) return;

    const payload = buildApRecommendationPayload({
      sceneVersionId,
      bbox: selectionBBox,
      existingAps,
      txPowerDbm: DEFAULT_TX_POWER_DBM,
    });

    if (import.meta.env.DEV) {
      console.debug('[AP Recommendation] request payload:', payload);
    }

    setPageError(null);
    setSavedRank(null);
    recommendMutation.mutate(payload, {
      onSuccess: (data) => {
        const normalized = normalizeRecommendations(data);
        setRecommendations(normalized);
        if (import.meta.env.DEV) {
          console.debug('[AP Recommendation] response:', data, 'normalized:', normalized);
        }
      },
      onError: (err) => {
        const e = err as HttpError | null;
        setPageError(e?.message ?? '추천 계산에 실패했습니다.');
      },
    });
  };

  const handleSelectRecommendation = (rec: ApRecommendationResult) => {
    if (!latestRfRunId) {
      setPageError('AP 배치를 저장하려면 먼저 시뮬레이션을 실행해 주세요.');
      return;
    }

    setSelectedRank(rec.rank);
    setPageError(null);

    const apName = nextApLayoutName(apLayoutsQuery.data ?? [], existingAps);

    createLayout.mutate(
      {
        rf_run_id: latestRfRunId,
        ap_name: apName,
        point_geom: {
          type: 'Point',
          coordinates: [rec.recommended_x, rec.recommended_y],
        },
        z_m: AP_DEFAULT_Z_M,
        power_dbm: DEFAULT_TX_POWER_DBM,
      },
      {
        onSuccess: () => {
          setSavedRank(rec.rank);
        },
        onError: (err) => {
          const e = err as HttpError | null;
          setPageError(e?.message ?? 'AP 배치 저장에 실패했습니다.');
          setSelectedRank(null);
        },
      },
    );
  };

  const canRecommend =
    !!sceneVersionId && isValidSelectionBBox(selectionBBox) && !recommendMutation.isPending;

  const sceneLoading =
    versionsQuery.isLoading ||
    versionDetailQuery.isLoading ||
    (floorId != null && !sceneVersionId && !versionsQuery.isError);

  const statusHint = getStatusHint(pageStatus, pageError, savedRank);

  return (
    <div className="flex h-full flex-col overflow-auto bg-[#F8FAFC]">
      {/* 본문 헤더 — Figma: 제목 + 설명 + 우측 CTA */}
      <header className="shrink-0 px-6 pb-4 pt-6 lg:px-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              AP 배치 추천
            </h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              개선이 필요한 영역을 드래그하면 최적의 AP 설치 위치를 추천합니다.
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-stretch gap-1.5 sm:items-end">
            <button
              type="button"
              onClick={handleRecommend}
              disabled={!canRecommend}
              className={cn(
                'inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold shadow-sm transition-colors',
                canRecommend
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'cursor-not-allowed bg-muted text-muted-foreground',
              )}
            >
              {recommendMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  최적 위치 계산 중…
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  최적 배치 추천
                </>
              )}
            </button>
            {!latestRfRunId && sceneVersionId && (
              <p className="text-[11px] text-amber-600 sm:text-right">
                AP 저장은 시뮬레이션 실행 후 가능합니다.
              </p>
            )}
          </div>
        </div>
      </header>

      {/* 본문 — lg: 캔버스(좌) + 추천 패널(우), md↓ 단일 컬럼 */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 px-6 pb-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-6 lg:px-8">
        {/* 좌측: 캔버스 + 진행 단계 */}
        <div className="flex min-h-0 flex-col gap-4">
          <div
            className={cn(
              'relative flex min-h-[min(52vh,32rem)] flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm',
              CARD_BORDER,
              'border',
            )}
          >
            {!floorId ? (
              <EmptyState message="층을 선택해 주세요." />
            ) : sceneLoading ? (
              <div className="flex h-full min-h-[320px] items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                도면 불러오는 중…
              </div>
            ) : !sceneVersionId ? (
              <EmptyState message="도면 정보를 불러올 수 없습니다." />
            ) : (
              <ApRecommendationCanvas
                sceneVersion={versionDetail}
                backgroundImageUrl={backgroundImageUrl}
                existingAps={existingAps}
                selectionBBox={selectionBBox}
                onSelectionChange={handleSelectionChange}
                recommendations={recommendations}
                selectedRecommendationRank={selectedRank}
                disabled={recommendMutation.isPending || createLayout.isPending}
              />
            )}

            {sceneVersionId && statusHint && pageStatus !== 'loading' && (
              <div className="pointer-events-none absolute bottom-4 left-4 right-4">
                <p className="rounded-lg border border-[#E5EAF2] bg-white/95 px-4 py-2.5 text-center text-xs text-muted-foreground shadow-sm backdrop-blur">
                  {statusHint}
                </p>
              </div>
            )}
          </div>

          {/* 진행 단계 카드 — 캔버스 아래 */}
          <div
            className={cn(
              'shrink-0 rounded-2xl bg-white px-6 py-5 shadow-sm',
              CARD_BORDER,
              'border',
            )}
          >
            <ProgressStepper activeStep={activeStep} pageStatus={pageStatus} />
          </div>
        </div>

        {/* 우측: 추천 결과 패널 (모바일에서는 하단 카드) */}
        <aside
          className={cn(
            'flex min-h-[280px] flex-col overflow-hidden rounded-2xl bg-white shadow-sm lg:min-h-0 lg:self-stretch',
            CARD_BORDER,
            'border',
          )}
        >
          <div className="border-b border-[#E5EAF2] px-5 py-4">
            <h2 className="text-base font-bold text-foreground">최적 배치 추천</h2>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {recommendations.length === 0 ? (
              <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2 px-4 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
                  <Sparkles className="h-5 w-5 text-muted-foreground" />
                </div>
                <p className="text-sm font-medium text-foreground/80">
                  {pageStatus === 'loading'
                    ? '최적 위치를 계산하고 있습니다…'
                    : '추천 결과가 여기에 표시됩니다'}
                </p>
                <p className="text-xs text-muted-foreground">
                  도면에서 우선 개선 영역을 드래그한 뒤 「최적 배치 추천」을 눌러주세요.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {recommendations.map((rec) => (
                  <RecommendationCard
                    key={rec.rank}
                    rec={rec}
                    selected={selectedRank === rec.rank}
                    saved={savedRank === rec.rank}
                    saving={createLayout.isPending && selectedRank === rec.rank}
                    saveDisabled={!latestRfRunId || createLayout.isPending}
                    onSelect={() => handleSelectRecommendation(rec)}
                  />
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function getStatusHint(
  pageStatus: PageStatus,
  pageError: string | null,
  savedRank: number | null,
): string | null {
  switch (pageStatus) {
    case 'idle':
      return '도면 위에서 우선 개선할 영역을 드래그하여 선택하세요.';
    case 'areaSelected':
      return '영역이 선택되었습니다. 우측 상단 「최적 배치 추천」 버튼을 눌러주세요.';
    case 'success':
      return savedRank != null
        ? '추천 위치가 AP 배치로 저장되었습니다.'
        : '추천 위치를 확인하고 우측 패널에서 선택하세요.';
    case 'error':
      return pageError ?? '추천 계산에 실패했습니다. 다시 시도해 주세요.';
    default:
      return null;
  }
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-full min-h-[320px] items-center justify-center px-6 text-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}

function RecommendationCard({
  rec,
  selected,
  saved,
  saving,
  saveDisabled,
  onSelect,
}: {
  rec: ApRecommendationResult;
  selected: boolean;
  saved: boolean;
  saving: boolean;
  saveDisabled: boolean;
  onSelect: () => void;
}) {
  return (
    <article
      className={cn(
        'rounded-xl border bg-white p-4 transition-colors',
        saved || selected ? 'border-emerald-300 shadow-sm' : 'border-[#E5EAF2]',
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-sm font-bold text-white">
          {rec.rank}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-bold text-foreground">{rec.rank}순위 추천</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            위치 X {rec.recommended_x.toFixed(0)}m / Y {rec.recommended_y.toFixed(0)}m
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
            우선 개선 영역 커버리지 가장 높음
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            후보 점수{' '}
            <span className="font-semibold text-foreground">{rec.score.toFixed(1)}</span>
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            탐색 후보 수 {rec.candidates_evaluated}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={onSelect}
        disabled={saveDisabled && !saved}
        className={cn(
          'mt-4 w-full rounded-lg border py-2.5 text-sm font-medium transition-colors',
          saved
            ? 'border-emerald-500 bg-emerald-500 text-white'
            : 'border-[#E5EAF2] bg-[#F8FAFC] text-foreground hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        {saving ? (
          <span className="inline-flex items-center justify-center gap-1.5">
            <Loader2 className="h-4 w-4 animate-spin" />
            저장 중…
          </span>
        ) : saved ? (
          <span className="inline-flex items-center justify-center gap-1.5">
            <CheckCircle2 className="h-4 w-4" />
            저장됨
          </span>
        ) : (
          '이 위치 선택'
        )}
      </button>
    </article>
  );
}

function ProgressStepper({
  activeStep,
  pageStatus,
}: {
  activeStep: number;
  pageStatus: PageStatus;
}) {
  return (
    <ol className="flex items-start">
      {PROGRESS_STEPS.map((step, index) => {
        const done =
          step.id < activeStep ||
          (step.id === 1 && pageStatus !== 'idle') ||
          (step.id === 2 && (pageStatus === 'success' || pageStatus === 'loading')) ||
          (step.id === 3 && activeStep >= 3);
        const current = step.id === activeStep && pageStatus !== 'error';
        const isLast = index === PROGRESS_STEPS.length - 1;

        return (
          <li key={step.id} className="flex min-w-0 flex-1 items-start">
            <div className="flex min-w-0 flex-1 flex-col items-center gap-2">
              <div
                className={cn(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold',
                  done && !current && 'bg-emerald-500 text-white',
                  current && 'bg-blue-600 text-white',
                  !done && !current && 'bg-muted text-muted-foreground',
                )}
              >
                {done && !current ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  step.id
                )}
              </div>
              <span
                className={cn(
                  'max-w-28 text-center text-xs leading-tight',
                  current ? 'font-semibold text-foreground' : 'text-muted-foreground',
                )}
              >
                {step.label}
              </span>
            </div>
            {!isLast && (
              <div
                className={cn(
                  'mt-4 h-0.5 min-w-4 flex-1',
                  step.id < activeStep ? 'bg-emerald-400' : 'bg-[#E5EAF2]',
                )}
                aria-hidden="true"
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
