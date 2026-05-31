import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Loader2, RotateCcw, Sparkles } from 'lucide-react';
import type { HttpError } from '@/api/client';
import { useAppStore } from '@/stores/app-store';
import { useFloorVersions, useSceneVersion } from '@/hooks/use-scene-version';
import { useFloorRfRuns } from '@/hooks/use-rf-run';
import { useApLayouts, useCreateApLayout } from '@/hooks/use-ap-layouts';
import { useFloorAssets, useAssetDownloadUrl } from '@/hooks/use-assets';
import { useLocalFloorplanImage } from '@/hooks/use-local-floorplan-image';
import { useApRecommendation } from '@/hooks/use-ap-recommendation';
import { useApRecommendationSession } from '@/hooks/use-ap-recommendation-session';
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
  getRecommendationRankUi,
  getRecommendationReason,
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

const CARD_BORDER = 'border-slate-200';

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

  const [pageError, setPageError] = useState<string | null>(null);
  const [hoveredRank, setHoveredRank] = useState<number | null>(null);

  const {
    selectionBBox,
    recommendations,
    selectedRank,
    savedRank,
    setSelectionBBox,
    setRecommendations,
    setSelectedRank,
    setSavedRank,
    persistSavedSession,
    resetSession,
  } = useApRecommendationSession(floorId, sceneVersionId);

  const highlightedRank = selectedRank ?? hoveredRank;

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
    if (savedRank != null) return 4;
    if (selectedRank != null) return 3;
    if (pageStatus === 'success') return 3;
    if (pageStatus === 'loading') return 2;
    if (pageStatus === 'areaSelected') return 1;
    return 1;
  }, [pageStatus, selectedRank, savedRank]);

  /** 저장 완료 후 — 선택한 순위 AP만 캔버스에 표시, 나머지 추천 마커 숨김 */
  const canvasRecommendations = useMemo(() => {
    if (savedRank == null) return recommendations;
    return recommendations.filter((r) => r.rank === savedRank);
  }, [recommendations, savedRank]);

  const handleSelectionChange = (bbox: MeterBBox | null) => {
    setSelectionBBox(bbox);
    setRecommendations([]);
    setSelectedRank(null);
    setSavedRank(null);
    setHoveredRank(null);
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
    setHoveredRank(null);
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

  const handleResetRecommendation = () => {
    resetSession();
    setPageError(null);
    setHoveredRank(null);
    recommendMutation.reset();
  };

  const handleHeaderAction = () => {
    if (recommendations.length > 0) {
      handleResetRecommendation();
      return;
    }
    handleRecommend();
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
          persistSavedSession({
            sceneVersionId,
            selectionBBox,
            recommendations,
            selectedRank: rec.rank,
            savedRank: rec.rank,
          });
        },
        onError: (err) => {
          const e = err as HttpError | null;
          setPageError(e?.message ?? 'AP 배치 저장에 실패했습니다.');
          setSelectedRank(null);
        },
      },
    );
  };

  const hasRecommendation = recommendations.length > 0;
  const isRecommendPending = recommendMutation.isPending;

  const canRecommend =
    !hasRecommendation &&
    !!sceneVersionId &&
    isValidSelectionBBox(selectionBBox) &&
    !isRecommendPending;

  const headerButtonDisabled =
    isRecommendPending || (!hasRecommendation && !canRecommend);

  const sceneLoading =
    versionsQuery.isLoading ||
    versionDetailQuery.isLoading ||
    (floorId != null && !sceneVersionId && !versionsQuery.isError);

  const statusHint = getStatusHint(pageStatus, pageError, savedRank);
  const hintStepId = useMemo(
    () => getHintStepId(pageStatus, activeStep),
    [pageStatus, activeStep],
  );

  const canvasAreaRef = useRef<HTMLDivElement>(null);
  const stepIconRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [bubbleLeftPx, setBubbleLeftPx] = useState<number | null>(null);

  const registerStepIconRef = useCallback((index: number, el: HTMLDivElement | null) => {
    stepIconRefs.current[index] = el;
  }, []);

  useLayoutEffect(() => {
    const syncBubblePosition = () => {
      const canvas = canvasAreaRef.current;
      const icon = stepIconRefs.current[hintStepId - 1];
      if (!canvas || !icon) {
        setBubbleLeftPx(null);
        return;
      }
      const canvasRect = canvas.getBoundingClientRect();
      const iconRect = icon.getBoundingClientRect();
      setBubbleLeftPx(iconRect.left + iconRect.width / 2 - canvasRect.left);
    };

    syncBubblePosition();
    window.addEventListener('resize', syncBubblePosition);
    return () => window.removeEventListener('resize', syncBubblePosition);
  }, [hintStepId, statusHint, sceneVersionId, pageStatus]);

  return (
    <div className="flex h-full flex-col overflow-auto bg-background">
      <header className="shrink-0 px-6 pb-3 pt-5 lg:px-8">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              AP 배치 추천
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              개선이 필요한 영역을 드래그하면 최적의 AP 설치 위치를 추천합니다.
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-stretch gap-1 sm:items-end">
            <button
              type="button"
              onClick={handleHeaderAction}
              disabled={headerButtonDisabled}
              className={cn(
                'inline-flex h-9 items-center justify-center gap-1.5 rounded-md px-4 text-sm font-medium transition-colors',
                isRecommendPending && 'cursor-not-allowed bg-slate-100 text-slate-400',
                !isRecommendPending &&
                  hasRecommendation &&
                  'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50',
                !isRecommendPending &&
                  !hasRecommendation &&
                  canRecommend &&
                  'bg-blue-500 text-white shadow-sm shadow-blue-500/20 hover:bg-blue-600',
                !isRecommendPending &&
                  !hasRecommendation &&
                  !canRecommend &&
                  'cursor-not-allowed bg-slate-100 text-slate-400',
              )}
            >
              {isRecommendPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  최적 위치 계산 중…
                </>
              ) : hasRecommendation ? (
                <>
                  <RotateCcw className="h-4 w-4" />
                  다시 생성하기
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

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 px-6 pb-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-5 lg:px-8">
        <div className="flex min-h-0 flex-col gap-3">
          <div
            ref={canvasAreaRef}
            className={cn(
              'relative flex min-h-[min(52vh,32rem)] flex-1 flex-col overflow-hidden rounded-xl border bg-white shadow-sm',
              CARD_BORDER,
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
                recommendations={canvasRecommendations}
                selectedRecommendationRank={selectedRank}
                highlightedRank={highlightedRank}
                onMarkerHover={setHoveredRank}
                disabled={isRecommendPending || createLayout.isPending}
                dragDisabled={isRecommendPending || hasRecommendation}
              />
            )}

            {sceneVersionId && statusHint && bubbleLeftPx != null && (
              <CanvasStatusBubble message={statusHint} leftPx={bubbleLeftPx} />
            )}
          </div>

          <div
            className={cn(
              'shrink-0 rounded-lg border bg-white px-3 py-2.5',
              CARD_BORDER,
            )}
          >
            <ProgressStepper
              activeStep={activeStep}
              pageStatus={pageStatus}
              registerStepIconRef={registerStepIconRef}
            />
          </div>
        </div>

        <aside
          className={cn(
            'flex min-h-[260px] flex-col overflow-hidden rounded-xl border bg-white shadow-sm lg:min-h-0 lg:self-stretch',
            CARD_BORDER,
          )}
        >
          <div className="border-b border-slate-200 px-5 py-4">
            <h2 className="text-base font-semibold text-slate-900">최적 배치 추천</h2>
            {recommendations.length > 0 && (
              <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
                선택한 우선 개선 영역과 기존 AP 위치를 함께 고려해 추천했습니다.
                {recommendations[0]?.candidates_evaluated > 0 && (
                  <>
                    {' '}
                    (총 {recommendations[0].candidates_evaluated}개 후보 비교)
                  </>
                )}
              </p>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {recommendations.length === 0 ? (
              <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2 px-4 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100">
                  <Sparkles className="h-5 w-5 text-slate-400" />
                </div>
                <p className="text-sm font-medium text-slate-700">
                  {pageStatus === 'loading'
                    ? '최적 위치를 계산하고 있습니다…'
                    : '추천 결과가 아직 없습니다'}
                </p>
                {pageStatus !== 'loading' && (
                  <p className="text-xs leading-relaxed text-slate-500">
                    도면에서 개선이 필요한 영역을 드래그한 뒤, 최적 배치 추천을 실행하세요.
                  </p>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                {recommendations.map((rec) => (
                  <RecommendationCard
                    key={rec.rank}
                    rec={rec}
                    reason={getRecommendationReason(rec, recommendations, selectionBBox)}
                    highlighted={highlightedRank === rec.rank}
                    saved={savedRank === rec.rank}
                    saving={createLayout.isPending && selectedRank === rec.rank}
                    saveDisabled={!latestRfRunId || createLayout.isPending}
                    onSelect={() => handleSelectRecommendation(rec)}
                    onHover={(active) => setHoveredRank(active ? rec.rank : null)}
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

function CanvasStatusBubble({
  message,
  leftPx,
}: {
  message: string;
  leftPx: number;
}) {
  return (
    <div
      className="pointer-events-none absolute bottom-3 z-10 -translate-x-1/2"
      style={{ left: leftPx }}
    >
      <div
        key={message}
        className="relative w-max max-w-md animate-bubble-rise rounded-xl border border-sky-200 bg-sky-50/95 px-4 py-2.5 shadow-sm backdrop-blur-sm"
      >
        <p className="text-center text-xs leading-relaxed text-sky-900/90">{message}</p>
        <span
          className="absolute -bottom-1 left-1/2 h-2 w-2 -translate-x-1/2 rotate-45 border-b border-r border-sky-200 bg-sky-50/95"
          aria-hidden="true"
        />
      </div>
    </div>
  );
}

function getHintStepId(pageStatus: PageStatus, activeStep: number): number {
  if (pageStatus === 'idle') return 1;
  if (pageStatus === 'areaSelected') return 2;
  if (pageStatus === 'loading') return 2;
  if (pageStatus === 'success') return 3;
  return Math.min(activeStep, 3);
}

function getStatusHint(
  pageStatus: PageStatus,
  pageError: string | null,
  savedRank: number | null,
): string | null {
  switch (pageStatus) {
    case 'idle':
      return '개선이 필요한 영역을 드래그해 선택하세요.';
    case 'areaSelected':
      return '영역이 선택되었습니다. 우측 상단 「최적 배치 추천」을 실행하세요.';
    case 'loading':
      return null;
    case 'success':
      return savedRank != null
        ? 'AP 배치가 저장되었습니다. 다른 영역은 다시 생성하기로 선택하세요.'
        : '추천 위치를 확인한 뒤 우측 패널에서 저장할 수 있습니다.';
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
  reason,
  highlighted,
  saved,
  saving,
  saveDisabled,
  onSelect,
  onHover,
}: {
  rec: ApRecommendationResult;
  reason: string;
  highlighted: boolean;
  saved: boolean;
  saving: boolean;
  saveDisabled: boolean;
  onSelect: () => void;
  onHover: (active: boolean) => void;
}) {
  const ui = getRecommendationRankUi(rec.rank);
  const isPrimary = rec.rank === 1;

  return (
    <article
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      className={cn(
        'rounded-xl border border-l-4 border-slate-200 bg-white p-4 transition-colors',
        ui.cardAccentClass,
        isPrimary && !saved && ui.cardEmphasisClass,
        highlighted && !saved && 'shadow-sm',
        saved && 'border-l-emerald-500 ring-1 ring-emerald-100',
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold',
            saved ? 'bg-emerald-500 text-white' : ui.badgeClass,
          )}
        >
          {rec.rank}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold leading-snug text-slate-900">{ui.title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-slate-600">{reason}</p>
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2.5 text-xs">
        <p className="text-slate-500">도면 기준 위치</p>
        <p className="mt-0.5 font-medium tabular-nums text-slate-900">
          가로 {rec.recommended_x.toFixed(1)}m · 세로 {rec.recommended_y.toFixed(1)}m
        </p>
      </div>

      {saved ? (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
          <p className="text-sm font-medium text-emerald-900">AP 배치로 저장됨</p>
        </div>
      ) : (
        <button
          type="button"
          onClick={onSelect}
          disabled={saveDisabled}
          className={cn(
            'mt-3 w-full rounded-lg border border-slate-200 bg-white py-2.5 text-sm font-medium text-slate-900 transition-colors',
            'hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50',
          )}
        >
          {saving ? (
            <span className="inline-flex items-center justify-center gap-1.5">
              <Loader2 className="h-4 w-4 animate-spin" />
              저장 중…
            </span>
          ) : (
            '이 위치에 AP 배치하기'
          )}
        </button>
      )}
    </article>
  );
}

function ProgressStepper({
  activeStep,
  pageStatus,
  registerStepIconRef,
}: {
  activeStep: number;
  pageStatus: PageStatus;
  registerStepIconRef?: (index: number, el: HTMLDivElement | null) => void;
}) {
  return (
    <div className="flex justify-center">
      <ol className="flex items-center">
        {PROGRESS_STEPS.map((step, index) => {
          const done =
            step.id < activeStep ||
            (step.id === 1 && pageStatus !== 'idle') ||
            (step.id === 2 && (pageStatus === 'success' || pageStatus === 'loading'));
          const current = step.id === activeStep && pageStatus !== 'error';
          const isLast = index === PROGRESS_STEPS.length - 1;

          return (
            <li key={step.id} className="flex items-center">
              <div className="flex flex-col items-center gap-1.5">
                <div
                  ref={(el) => registerStepIconRef?.(index, el)}
                  className={cn(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                    done &&
                      !current &&
                      'bg-emerald-500 text-white ring-1 ring-emerald-200/80',
                    current &&
                      'bg-blue-500 text-white ring-4 ring-blue-100 shadow-sm shadow-blue-500/20',
                    !done && !current && 'bg-slate-200 text-slate-500',
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
                    'w-[7.5rem] text-center text-xs leading-snug',
                    current
                      ? 'font-medium text-slate-900'
                      : done
                        ? 'text-slate-600'
                        : 'text-slate-500',
                  )}
                >
                  {step.label}
                </span>
              </div>
              {!isLast && (
                <div
                  className={cn(
                    'mx-3 mb-[1.625rem] h-0.5 w-20 sm:w-28',
                    step.id < activeStep ? 'bg-emerald-200' : 'bg-slate-200',
                  )}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
