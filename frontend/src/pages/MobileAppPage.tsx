import { useEffect, useMemo, useState } from 'react';
import { Ban, CheckCircle2, Loader2, MapPin, Sparkles, Target } from 'lucide-react';
import type { HttpError } from '@/api/client';
import { useAppStore } from '@/stores/app-store';
import {
  useApRecommendationStore,
  type ApRecommendationSession,
} from '@/stores/ap-recommendation-store';
import { useFloorVersions, useSceneVersion } from '@/hooks/use-scene-version';
import { useFloorRfRuns, useRfMaps } from '@/hooks/use-rf-run';
import { useApLayouts, useCreateApLayout } from '@/hooks/use-ap-layouts';
import { useAssetDownloadUrl } from '@/hooks/use-assets';
import { useLocalFloorplanImage } from '@/hooks/use-local-floorplan-image';
import { useApRecommendation } from '@/hooks/use-ap-recommendation';
import { useEstimatedCoverage, useFloorMeasurementSessions } from '@/hooks/use-measurement-session';
import { useRfMapImageUrl } from '@/hooks/use-rf-map-image-url';
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
  normalizeRecommendations,
  validRecommendationAreas,
  type ApRecommendationArea,
  type ApRecommendationAreaType,
} from '@/features/ap-recommendation/recommendation-utils';
import type { ApRecommendationResult } from '@/types/ap-recommendation';
import { cn } from '@/lib/utils';

type PageStatus = 'idle' | 'areaSelected' | 'loading' | 'success' | 'error';

const PROGRESS_STEPS = [
  { id: 1, label: '설치할 수 있는 곳 선택' },
  { id: 2, label: '와이파이 위치 계산' },
  { id: 3, label: '추천 위치 선택' },
] as const;

const CARD_BORDER = 'border-[#E5EAF2]';

const AREA_TYPE_OPTIONS: Array<{
  type: ApRecommendationAreaType;
  label: string;
  hint: string;
  className: string;
  icon: typeof MapPin;
}> = [
  {
    type: 'candidate',
    label: '설치 가능한 곳',
    hint: '공유기를 둘 수 있는 범위',
    className: 'border-blue-200 bg-blue-50 text-blue-700',
    icon: MapPin,
  },
  {
    type: 'priority',
    label: '집중구간',
    hint: '신호를 집중해서 볼 영역',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    icon: Target,
  },
  {
    type: 'excluded',
    label: '계산에서 뺄 곳',
    hint: '추천 계산에서 제외',
    className: 'border-red-200 bg-red-50 text-red-700',
    icon: Ban,
  },
];

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
  const effectiveAssetId = sourceAssetId;
  const assetUrlQuery = useAssetDownloadUrl(effectiveAssetId);
  const localImage = useLocalFloorplanImage({
    floorId,
    sourceAssetId,
    allowFloorFallback: false,
  });
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
  const rfMapsQuery = useRfMaps(latestRfRunId, !!latestRfRunId);
  const simulationHeatmapMap = useMemo(() => {
    const maps = rfMapsQuery.data ?? [];
    return maps.find((m) => m.map_type === 'heatmap') ?? maps[0] ?? null;
  }, [rfMapsQuery.data]);
  const simulationHeatmapSourceUrl = useMemo(() => {
    if (!simulationHeatmapMap) return null;
    if (simulationHeatmapMap.url) return simulationHeatmapMap.url;
    const raw = simulationHeatmapMap.storage_url;
    if (raw && /^https?:\/\//i.test(raw)) return raw;
    return null;
  }, [simulationHeatmapMap]);
  const simulationHeatmapUrl = useRfMapImageUrl(simulationHeatmapSourceUrl);
  const simulationHeatmapBounds = useMemo(
    () => parseRfHeatmapBounds(simulationHeatmapMap?.bounds_json),
    [simulationHeatmapMap],
  );

  const existingAps = useMemo(() => {
    const layouts = apLayoutsQuery.data ?? [];
    if (layouts.length > 0) return apLayoutsToCanvas(layouts);
    return apsFromRfRunRequest(latestRfRun?.request_json as Record<string, unknown> | undefined);
  }, [apLayoutsQuery.data, latestRfRun?.request_json]);

  const patchRecommendationScene = useApRecommendationStore((s) => s.patchScene);
  const clearRecommendationScene = useApRecommendationStore((s) => s.clearScene);
  const [selectedAreas, setSelectedAreas] = useState<ApRecommendationArea[]>([]);
  const [activeAreaType, setActiveAreaType] = useState<ApRecommendationAreaType>('candidate');
  const [recommendations, setRecommendations] = useState<ApRecommendationResult[]>([]);
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [savedRank, setSavedRank] = useState<number | null>(null);
  const [compareWithMeasurement, setCompareWithMeasurement] = useState(false);
  const [recommendationUpdatedAt, setRecommendationUpdatedAt] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  const recommendMutation = useApRecommendation();
  const createLayout = useCreateApLayout();
  const measurementSessionsQuery = useFloorMeasurementSessions(floorId);
  const comparisonSession = useMemo(() => {
    const sessions = measurementSessionsQuery.data?.items ?? [];
    if (!sceneVersionId) return null;
    return (
      sessions.find(
        (session) =>
          session.scene_version_id === sceneVersionId &&
          session.status === 'completed',
      ) ?? null
    );
  }, [measurementSessionsQuery.data, sceneVersionId]);
  const comparisonCoverageQuery = useEstimatedCoverage(comparisonSession?.id ?? null, {
    method: 'gp_only',
  });
  const measurementHeatmap = useMemo(() => {
    const coverage = comparisonCoverageQuery.data;
    if (!coverage) return null;
    return {
      url: coverage.heatmap_url,
      bounds: coverage.bounds,
      rssiRange: { min: coverage.rssi_range.min, max: coverage.rssi_range.max },
      source: 'measurement' as const,
    };
  }, [comparisonCoverageQuery.data]);
  const simulationHeatmap = useMemo(() => {
    if (!simulationHeatmapUrl || !simulationHeatmapBounds) return null;
    return {
      url: simulationHeatmapUrl,
      bounds: {
        min_x: simulationHeatmapBounds.minX,
        min_y: simulationHeatmapBounds.minY,
        max_x: simulationHeatmapBounds.maxX,
        max_y: simulationHeatmapBounds.maxY,
      },
      source: 'simulation' as const,
    };
  }, [simulationHeatmapBounds, simulationHeatmapUrl]);
  const comparisonHeatmap = measurementHeatmap ?? simulationHeatmap;
  const showComparisonHeatmap = compareWithMeasurement && !!comparisonHeatmap;

  const persistRecommendationSession = (patch: Partial<ApRecommendationSession>) => {
    if (!sceneVersionId) return;
    const updatedAt = new Date().toISOString();
    setRecommendationUpdatedAt(updatedAt);
    patchRecommendationScene(sceneVersionId, {
      sceneVersionId,
      updatedAt,
      ...patch,
    });
  };

  useEffect(() => {
    recommendMutation.reset();
    setPageError(null);

    if (!sceneVersionId) {
      setSelectedAreas([]);
      setRecommendations([]);
      setSelectedRank(null);
      setSavedRank(null);
      setCompareWithMeasurement(false);
      setRecommendationUpdatedAt(null);
      return;
    }

    const stored = useApRecommendationStore.getState().byScene[sceneVersionId];
    if (!stored) {
      setSelectedAreas([]);
      setRecommendations([]);
      setSelectedRank(null);
      setSavedRank(null);
      setCompareWithMeasurement(false);
      setRecommendationUpdatedAt(null);
      return;
    }

    const storedAreas = validRecommendationAreas(stored.areas);
    const storedRecommendations = stored.recommendations ?? [];
    setSelectedAreas(storedAreas);
    setRecommendations(storedRecommendations);
    setSelectedRank(stored.selectedRank ?? storedRecommendations[0]?.rank ?? null);
    setSavedRank(stored.savedRank);
    setCompareWithMeasurement(stored.compareWithMeasurement);
    setRecommendationUpdatedAt(stored.updatedAt);
  }, [sceneVersionId]);

  const pageStatus: PageStatus = useMemo(() => {
    if (recommendMutation.isPending) return 'loading';
    if (recommendMutation.isError) return 'error';
    if (recommendations.length > 0) return 'success';
    if (validRecommendationAreas(selectedAreas).length > 0) return 'areaSelected';
    return 'idle';
  }, [
    recommendMutation.isPending,
    recommendMutation.isError,
    recommendations.length,
    selectedAreas,
  ]);

  const activeStep = useMemo(() => {
    if (savedRank != null || selectedRank != null) return 3;
    if (pageStatus === 'success') return 3;
    if (pageStatus === 'loading') return 2;
    if (pageStatus === 'areaSelected') return 1;
    return 1;
  }, [pageStatus, selectedRank, savedRank]);

  const handleAreasChange = (areas: ApRecommendationArea[]) => {
    const validAreas = validRecommendationAreas(areas);
    setSelectedAreas(validAreas);
    setRecommendations([]);
    setSelectedRank(null);
    setSavedRank(null);
    setCompareWithMeasurement(false);
    if (sceneVersionId && validAreas.length > 0) {
      persistRecommendationSession({
        areas: validAreas,
        recommendations: [],
        selectedRank: null,
        savedRank: null,
        compareWithMeasurement: false,
      });
    } else if (sceneVersionId) {
      clearRecommendationScene(sceneVersionId);
      setRecommendationUpdatedAt(null);
    }
    setPageError(null);
    recommendMutation.reset();
  };

  const handleRecommend = () => {
    if (!sceneVersionId) {
      setPageError('도면 정보를 불러올 수 없습니다.');
      return;
    }
    const validAreas = validRecommendationAreas(selectedAreas);
    const candidateAreas = validAreas.filter((area) => area.type === 'candidate');
    if (candidateAreas.length === 0) {
      setPageError('공유기를 설치할 수 있는 곳을 먼저 선택해 주세요.');
      return;
    }

    const payload = buildApRecommendationPayload({
      sceneVersionId,
      areas: validAreas,
      existingAps,
      txPowerDbm: DEFAULT_TX_POWER_DBM,
    });

    if (import.meta.env.DEV) {
      console.debug('[AP Recommendation] request payload:', payload);
    }

    setPageError(null);
    setSavedRank(null);
    persistRecommendationSession({
      areas: validAreas,
      savedRank: null,
      compareWithMeasurement: false,
    });
    recommendMutation.mutate(payload, {
      onSuccess: (data) => {
        const normalized = normalizeRecommendations(data);
        setRecommendations(normalized);
        setSelectedRank(normalized[0]?.rank ?? null);
        setCompareWithMeasurement(false);
        persistRecommendationSession({
          areas: validAreas,
          recommendations: normalized,
          selectedRank: normalized[0]?.rank ?? null,
          savedRank: null,
          compareWithMeasurement: false,
        });
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
      setPageError('와이파이 위치를 저장하려면 먼저 시뮬레이션을 실행해 주세요.');
      return;
    }

    setSelectedRank(rec.rank);
    setPageError(null);
    persistRecommendationSession({ selectedRank: rec.rank });

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
          persistRecommendationSession({ selectedRank: rec.rank, savedRank: rec.rank });
        },
        onError: (err) => {
          const e = err as HttpError | null;
          setPageError(e?.message ?? '와이파이 위치 저장에 실패했습니다.');
          setSelectedRank(null);
          persistRecommendationSession({ selectedRank: null });
        },
      },
    );
  };

  const handlePreviewRecommendation = (rec: ApRecommendationResult) => {
    setSelectedRank(rec.rank);
    setCompareWithMeasurement(false);
    setPageError(null);
    persistRecommendationSession({
      selectedRank: rec.rank,
      compareWithMeasurement: false,
    });
  };

  const handleToggleComparison = () => {
    const next = !compareWithMeasurement;
    setCompareWithMeasurement(next);
    persistRecommendationSession({ compareWithMeasurement: next });
  };

  const canRecommend =
    !!sceneVersionId &&
    validRecommendationAreas(selectedAreas).some((area) => area.type === 'candidate') &&
    !recommendMutation.isPending;

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
              와이파이 설치 위치 추천
            </h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              공유기를 둘 수 있는 곳과 집중구간을 표시하면 좋은 설치 위치를 추천합니다.
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
                  추천 위치 찾기
                </>
              )}
            </button>
            {!latestRfRunId && sceneVersionId && (
              <p className="text-[11px] text-amber-600 sm:text-right">
                와이파이 위치 저장은 시뮬레이션 실행 후 가능합니다.
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
              'relative flex min-h-[min(72vh,46rem)] flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm lg:min-h-[min(78vh,54rem)]',
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
                selectedAreas={selectedAreas}
                activeAreaType={activeAreaType}
                onAreasChange={handleAreasChange}
                recommendations={recommendations}
                selectedRecommendationRank={selectedRank}
                heatmapMode={showComparisonHeatmap ? 'measurement' : 'prediction'}
                measurementHeatmap={comparisonHeatmap}
                disabled={recommendMutation.isPending || createLayout.isPending}
              />
            )}
          </div>

          {sceneVersionId && statusHint && pageStatus !== 'loading' && (
            <p className="rounded-lg border border-[#E5EAF2] bg-white px-4 py-2.5 text-center text-xs text-muted-foreground shadow-sm">
              {statusHint}
            </p>
          )}

          {/* 진행 단계 카드 — 캔버스 아래 */}
          <div
            className={cn(
              'shrink-0 rounded-2xl bg-white px-6 py-5 shadow-sm',
              CARD_BORDER,
              'border',
            )}
          >
            <AreaControls
              activeAreaType={activeAreaType}
              areas={selectedAreas}
              onTypeChange={setActiveAreaType}
              onRemoveArea={(id) =>
                handleAreasChange(selectedAreas.filter((area) => area.id !== id))
              }
            />
            <div className="mt-5 border-t border-[#E5EAF2] pt-5">
              <ProgressStepper activeStep={activeStep} pageStatus={pageStatus} />
            </div>
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
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-base font-bold text-foreground">추천 위치</h2>
              {recommendations.length > 0 && (
                <button
                  type="button"
                  onClick={handleToggleComparison}
                  disabled={!comparisonHeatmap}
                  className={cn(
                    'rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors',
                    showComparisonHeatmap
                      ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                      : 'border-[#E5EAF2] bg-white text-foreground hover:bg-muted/60',
                    !comparisonHeatmap && 'cursor-not-allowed opacity-50',
                  )}
                >
                  {measurementHeatmap ? '실측과 비교' : '시뮬맵 보기'}
                </button>
              )}
            </div>
            {recommendations.length > 0 && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                {showComparisonHeatmap
                  ? comparisonHeatmap?.source === 'measurement'
                    ? '현재 도면의 최신 실측 히트맵을 보고 있습니다.'
                    : comparisonHeatmap?.source === 'simulation'
                    ? '실측값이 없어 보정 전 시뮬레이션맵을 보고 있습니다.'
                    : '현재 도면에 비교할 실측 또는 시뮬레이션맵이 없습니다.'
                  : '추천 후보를 클릭하면 해당 위치의 예측 신호 지도가 표시됩니다.'}
              </p>
            )}
            {recommendationUpdatedAt && recommendations.length > 0 && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                저장된 추천 기록: {formatHistoryTime(recommendationUpdatedAt)}
              </p>
            )}
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
                  도면에서 공유기를 설치할 수 있는 곳을 먼저 지정한 뒤 추천을 실행해 주세요.
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
                    onPreview={() => handlePreviewRecommendation(rec)}
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
      return '도면 위에서 공유기를 설치할 수 있는 곳을 먼저 드래그해 주세요.';
    case 'areaSelected':
      return '필요하면 집중구간이나 계산에서 뺄 곳을 추가한 뒤 추천을 실행하세요.';
    case 'success':
      return savedRank != null
        ? '추천 위치가 와이파이 설치 위치로 저장되었습니다.'
        : '추천 위치를 확인하고 우측 패널에서 선택하세요.';
    case 'error':
      return pageError ?? '추천 계산에 실패했습니다. 다시 시도해 주세요.';
    default:
      return null;
  }
}

function AreaControls({
  activeAreaType,
  areas,
  onTypeChange,
  onRemoveArea,
}: {
  activeAreaType: ApRecommendationAreaType;
  areas: ApRecommendationArea[];
  onTypeChange: (type: ApRecommendationAreaType) => void;
  onRemoveArea: (id: string) => void;
}) {
  const validAreas = validRecommendationAreas(areas);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {AREA_TYPE_OPTIONS.map((option) => {
          const Icon = option.icon;
          const active = activeAreaType === option.type;
          return (
            <button
              key={option.type}
              type="button"
              onClick={() => onTypeChange(option.type)}
              className={cn(
                'flex min-h-16 items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors',
                active
                  ? `${option.className} ring-2 ring-offset-1`
                  : 'border-[#E5EAF2] bg-white text-muted-foreground hover:bg-muted/50',
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="min-w-0">
                <span className="block text-xs font-semibold leading-tight">{option.label}</span>
                <span className="mt-0.5 block text-[11px] leading-tight opacity-80">
                  {option.hint}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        {AREA_TYPE_OPTIONS.map((option) => {
          const items = validAreas.filter((area) => area.type === option.type);
          return (
            <div key={option.type} className="rounded-lg border border-[#E5EAF2] p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-foreground">{option.label}</p>
                <span className="text-[11px] text-muted-foreground">{items.length}</span>
              </div>
              <div className="mt-2 space-y-1.5">
                {items.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">선택 없음</p>
                ) : (
                  items.map((area, index) => (
                    <div
                      key={area.id}
                      className="flex items-center justify-between gap-2 rounded-md bg-muted/40 px-2 py-1.5"
                    >
                      <span className="text-[11px] text-muted-foreground">
                        #{index + 1} {formatBBox(area.bbox)}
                      </span>
                      <button
                        type="button"
                        onClick={() => onRemoveArea(area.id)}
                        className="rounded px-1.5 text-xs font-semibold text-red-600 hover:bg-red-50"
                      >
                        삭제
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatBBox(bbox: ApRecommendationArea['bbox']): string {
  return `${bbox.x_min.toFixed(1)},${bbox.y_min.toFixed(1)}-${bbox.x_max.toFixed(1)},${bbox.y_max.toFixed(1)}`;
}

function formatHistoryTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function parseRfHeatmapBounds(
  bounds: Record<string, unknown> | null | undefined,
): { minX: number; minY: number; maxX: number; maxY: number } | null {
  if (!bounds) return null;
  const minX = Number(bounds.min_x);
  const minY = Number(bounds.min_y);
  const maxX = Number(bounds.max_x);
  const maxY = Number(bounds.max_y);
  if (
    !Number.isFinite(minX) ||
    !Number.isFinite(minY) ||
    !Number.isFinite(maxX) ||
    !Number.isFinite(maxY) ||
    maxX <= minX ||
    maxY <= minY
  ) {
    return null;
  }
  return { minX, minY, maxX, maxY };
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
  onPreview,
  onSelect,
}: {
  rec: ApRecommendationResult;
  selected: boolean;
  saved: boolean;
  saving: boolean;
  saveDisabled: boolean;
  onPreview: () => void;
  onSelect: () => void;
}) {
  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onPreview}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onPreview();
        }
      }}
      className={cn(
        'cursor-pointer rounded-xl border bg-white p-4 transition-colors',
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
            집중구간에 가장 잘 닿는 위치
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
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
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
