import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CheckCircle2,
  ChevronRight,
  Loader2,
  Map as MapIcon,
  Play,
  RotateCcw,
  Sparkles,
  Trash2,
  Wifi,
} from 'lucide-react';
import { useMemo, useEffect } from 'react';
import { useAppStore } from '@/stores/app-store';
import { useFloorVersions, useSceneVersion } from '@/hooks/use-scene-version';
import { useCreateRfRun, useFloorRfRuns, useRfMaps, useRfRun } from '@/hooks/use-rf-run';
import { useRfMapImageUrl } from '@/hooks/use-rf-map-image-url';
import { useFloorAssets, useAssetDownloadUrl } from '@/hooks/use-assets';
import { useLocalFloorplanImage, linkFloorImageToAsset } from '@/hooks/use-local-floorplan-image';
import { versionToDraftShape } from '@/features/editor/version-as-draft';
import {
  useApCandidates,
  useApLayouts,
  useCreateApLayout,
  useDeleteApLayout,
  useGenerateApCandidates,
} from '@/hooks/use-ap-layouts';
import { HelpFab } from '@/components/HelpFab';
import { SimulationResultCard } from '@/features/simulation/SimulationResultCard';
import {
  SimulationHistory,
  type SimulationHistoryItem,
} from '@/features/simulation/SimulationHistory';
import {
  SimulationCanvas,
  type PlacedAp,
} from '@/features/simulation/SimulationCanvas';
import { extractColorScale } from '@/features/simulation/HeatmapColorLegend';
import { DbmColorBar } from '@/features/simulation/DbmColorBar';
import { FloorSpaceTypeSelector } from '@/features/floor/FloorSpaceTypeSelector';
import { toast } from '@/stores/toast-store';
import type { SceneVersion } from '@/types/scene';
import type { UUID } from '@/types/common';
import type { RfBackend } from '@/types/rf';
import { cn } from '@/lib/utils';
import { nextApSequentialName } from '@/lib/ap-layout-naming';

type SimulationState = 'idle' | 'running' | 'complete';
type FrequencyBand = '2.4' | '5';

const frequencyHzByBand: Record<FrequencyBand, number> = {
  '2.4': 2.4e9,
  '5': 5.0e9,
};

export default function SimulationPage() {
  const floorId = useAppStore((s) => s.selectedFloorId);
  const selectedProjectId = useAppStore((s) => s.selectedProjectId);
  const versionsQuery = useFloorVersions(floorId);
  // 현재 활성 버전 (없으면 가장 최근 버전)
  const currentVersion =
    versionsQuery.data?.find((v) => v.is_current) ?? versionsQuery.data?.[0] ?? null;

  // 사용자가 명시적으로 선택한 run (또는 새로 실행한 run). null 이면 "최신 succeeded 자동" 모드.
  const [pickedRunId, setPickedRunId] = useState<string | null>(null);
  // "다시 실행" 으로 idle 로 돌아간 상태를 추적 — 새로 실행하기 전까지 자동복원 OFF.
  const [resetCleared, setResetCleared] = useState(false);

  // 사용자가 배치한 AP 목록 + 추가 모드(true 면 다음 클릭이 새 AP 추가).
  const [aps, setAps] = useState<PlacedAp[]>([]);
  const [pendingAdd, setPendingAdd] = useState(false);

  // 시뮬 실행 백엔드 토글 — local(기본, 로컬 ai_api) | sagemaker(클라우드).
  // 로컬에서 분 단위로 결과 보는 게 dev 흐름이라 기본값을 local 로.
  const [backend, setBackend] = useState<RfBackend>('local');
  const [frequencyBand, setFrequencyBand] = useState<FrequencyBand>('5');
  const [txPowerDbm, setTxPowerDbm] = useState(20);

  // 층의 과거 RF Run 목록 (이력 카드 + 자동 복원용).
  const pastRunsQuery = useFloorRfRuns(floorId, { page_size: 20 });
  const pastRuns = useMemo(() => pastRunsQuery.data?.items ?? [], [pastRunsQuery.data]);

  // 활성 run = 사용자가 명시 선택한 것 ?? 현재 scene_version 으로 돌린 최근 succeeded.
  const activeRunId = useMemo(() => {
    if (resetCleared) return null;
    if (pickedRunId) return pickedRunId;
    if (!currentVersion) return null;
    return (
      pastRuns.find(
        (r) => r.status === 'succeeded' && r.scene_version_id === currentVersion.id,
      )?.id ?? null
    );
  }, [resetCleared, pickedRunId, pastRuns, currentVersion]);
  const setActiveRunId = (id: string | null) => {
    setResetCleared(false);
    setPickedRunId(id);
  };

  const createRfRun = useCreateRfRun();
  const rfRunPoll = useRfRun(activeRunId);
  const rfMapsQuery = useRfMaps(activeRunId, rfRunPoll.isSucceeded);
  const activeRunSceneVersionId = rfRunPoll.rfRun?.scene_version_id ?? null;

  const state: SimulationState = (() => {
    if (!activeRunId) return 'idle';
    if (rfRunPoll.isSucceeded) return 'complete';
    if (rfRunPoll.isFailed) return 'idle';
    return 'running';
  })();

  /** complete 상태에선 run 당시 scene_version, idle/running 은 현재 도면. */
  const canvasSceneVersionId = useMemo(() => {
    if (state === 'complete' && activeRunSceneVersionId) {
      return activeRunSceneVersionId;
    }
    return currentVersion?.id ?? null;
  }, [state, activeRunSceneVersionId, currentVersion?.id]);

  const canvasVersionQuery = useSceneVersion(canvasSceneVersionId);
  const backgroundImageUrl = useSceneFloorplanBackground(
    floorId,
    canvasVersionQuery.data,
  );

  const isViewingHistoricalRun =
    state === 'complete' &&
    !!currentVersion &&
    !!activeRunSceneVersionId &&
    activeRunSceneVersionId !== currentVersion.id;

  // 활성 run(과거/자동복원 포함)의 AP 를 캔버스에 복원 — 결과 화면에 AP 마커가 보이도록.
  // (aps state 는 사용자가 직접 찍은 것만 담기는데, 과거 run 을 불러올 땐 비어 있어 마커가 안 떴음)
  useEffect(() => {
    if (!activeRunId || !rfRunPoll.rfRun) return;
    const aps_raw = (rfRunPoll.rfRun.request_json?.['access_points'] ?? []) as Array<
      Record<string, unknown>
    >;
    if (!Array.isArray(aps_raw) || aps_raw.length === 0) return;
    const restored: PlacedAp[] = aps_raw.map((a, i) => ({
      id: String(a['id'] ?? `ap${i + 1}`),
      x_m: Number(a['x_m'] ?? a['x'] ?? 0),
      y_m: Number(a['y_m'] ?? a['y'] ?? 0),
      z_m: Number(a['z_m'] ?? a['z'] ?? 2.5),
    }));
    setAps(restored);
  }, [activeRunId, rfRunPoll.rfRun]);

  const heatmapMap = useMemo(() => {
    const maps = rfMapsQuery.data ?? [];
    return maps.find((m) => m.map_type === 'heatmap') ?? maps[0] ?? null;
  }, [rfMapsQuery.data]);
  const heatmapSourceUrl = useMemo(() => {
    if (!heatmapMap) return null;
    if (heatmapMap.url) return heatmapMap.url;
    const raw = heatmapMap.storage_url;
    if (raw && /^https?:\/\//i.test(raw)) return raw;
    return null;
  }, [heatmapMap]);
  const heatmapUrl = useRfMapImageUrl(heatmapSourceUrl);
  const heatmapColorScale = useMemo(
    () =>
      extractColorScale(
        (heatmapMap?.metrics_json as Record<string, unknown> | undefined)?.['color_scale'],
      ),
    [heatmapMap],
  );
  const heatmapBounds = useMemo(
    () => parseHeatmapBounds(heatmapMap?.bounds_json),
    [heatmapMap],
  );

  const handleStart = () => {
    if (!currentVersion) return;
    if (aps.length === 0) {
      toast.info('AP 를 1개 이상 배치해주세요', '캔버스 우측의 "AP 추가하기" 에서 종류를 선택하고 클릭하세요.');
      return;
    }
    createRfRun.mutate(
      {
        scene_version_id: currentVersion.id,
        run_type: 'forward',
        access_points: aps.map((ap) => ({
          id: ap.id,
          x_m: ap.x_m,
          y_m: ap.y_m,
          z_m: ap.z_m,
        })),
        // 모든 시뮬 파라미터는 backend `app/core/rf_defaults.py` 의 디폴트 사용 —
        // 5GHz / 20dBm / max_depth=3 / samples=100k 등. UI 에서 사용자가 직접 정하는
        // 값이 생기면 여기 채워 보내면 backend 가 우선 적용. 빈 `{}` 는 "new flow" 트리거.
        simulation: {
          frequency_hz: frequencyHzByBand[frequencyBand],
          tx_power_dbm: txPowerDbm,
        },
        metadata: {
          rf_physical_ui: {
            frequency_band: frequencyBand,
            frequency_hz: frequencyHzByBand[frequencyBand],
            tx_power_dbm: txPowerDbm,
          },
        },
        apply_calibration: false,
        backend,
      },
      { onSuccess: (data) => setActiveRunId(data.id) },
    );
  };

  const handleReset = () => {
    const wasHistorical =
      state === 'complete' &&
      !!activeRunSceneVersionId &&
      activeRunSceneVersionId !== currentVersion?.id;
    setPickedRunId(null);
    setResetCleared(true);
    if (wasHistorical) setAps([]);
  };

  const handleAddAp = (ap: PlacedAp) => setAps((prev) => [...prev, ap]);
  const handleMoveAp = (id: string, x: number, y: number) =>
    setAps((prev) => prev.map((a) => (a.id === id ? { ...a, x_m: x, y_m: y } : a)));
  const handleRemoveAp = (id: string) =>
    setAps((prev) => prev.filter((a) => a.id !== id));

  // 메트릭 추출 (백엔드가 metrics_json 안에 다양한 키로 넣을 수 있어 유연하게)
  const metrics = parseMetrics(
    rfRunPoll.rfRun?.metrics_json,
    rfMapsQuery.data?.[0]?.metrics_json,
  );

  // 시뮬레이션 기록 — 백엔드의 RF Run 목록을 표시. 클릭하면 해당 run 으로 전환.
  // 실제 메트릭(rss_dbm.mean, coverage_summary)은 RfRun 이 아닌 RfMap 에 들어있어서
  // 활성 run 한정으로 rfMapsQuery 데이터를 머지. 나머지는 null → "—" 로 표시.
  const activeMapMetrics = rfMapsQuery.data?.[0]?.metrics_json;
  const history: SimulationHistoryItem[] = useMemo(
    () =>
      pastRuns
        .filter((r) => r.status === 'succeeded')
        .map((r) => {
          // rf_run.metrics_json 은 `{ radio_map: { rss_dbm, coverage_summary, ... }, ... }` 형태로
          // 한 단계 nested. parseMetrics 는 top-level 키만 찾으므로 radio_map 도 같이 풀어 넘김.
          // active 일 땐 RfMap.metrics_json (flat) 도 함께 — 그쪽이 더 풍부할 수 있음.
          const radioMap = (r.metrics_json?.['radio_map'] ?? null) as
            | Record<string, unknown>
            | null;
          const sources: Array<Record<string, unknown> | undefined> = [r.metrics_json];
          if (radioMap) sources.push(radioMap);
          if (r.id === activeRunId && activeMapMetrics) sources.push(activeMapMetrics);
          const m = parseMetrics(...sources);
          return {
            id: r.id,
            createdAt: r.created_at,
            avgRssiDbm: m.avgRssiDbm,
            coveragePercent: m.coveragePercent,
            active: r.id === activeRunId,
          };
        }),
    [pastRuns, activeRunId, activeMapMetrics],
  );

  return (
    <div className="relative flex h-full flex-col p-5 lg:p-6">
      <PageHeader
        state={state}
        hasVersion={!!currentVersion}
        isStarting={createRfRun.isPending}
        apsCount={aps.length}
        backend={backend}
        onBackendChange={setBackend}
        frequencyBand={frequencyBand}
        onFrequencyBandChange={setFrequencyBand}
        txPowerDbm={txPowerDbm}
        onTxPowerDbmChange={setTxPowerDbm}
        floorId={floorId ?? null}
        projectId={selectedProjectId}
        onStart={handleStart}
        onReset={handleReset}
      />

      {!floorId ? (
        <EmptyState
          title="층을 선택해주세요"
          subtitle="대시보드에서 층을 선택하면 시뮬레이션을 시작할 수 있습니다."
        />
      ) : versionsQuery.isLoading ? (
        <EmptyState title="버전 정보를 불러오는 중..." />
      ) : !currentVersion ? (
        <EmptyState
          title="확정된 도면 버전이 없습니다"
          subtitle="공간 편집에서 도면을 분석·확정한 후 시뮬레이션을 실행할 수 있습니다."
          ctaLabel="공간 편집으로 이동"
          ctaTo="/editor"
        />
      ) : (
        <div className="mt-4 grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
          <div className="relative min-h-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
            {state === 'idle' ? (
              <>
                <CanvasModeBar apsCount={aps.length} />
                <SimulationCanvas
                  sceneVersion={canvasVersionQuery.data}
                  backgroundImageUrl={backgroundImageUrl}
                  aps={aps}
                  onAdd={handleAddAp}
                  onMove={handleMoveAp}
                  onRemove={handleRemoveAp}
                  pending={pendingAdd}
                  onClearPending={() => setPendingAdd(false)}
                />
                <ApAddPanel
                  active={pendingAdd}
                  onToggle={() => setPendingAdd((v) => !v)}
                  disabled={aps.length >= 8}
                />
              </>
            ) : state === 'running' ? (
              <div className="h-full p-4">
                <SimulationVisualization state={state} />
              </div>
            ) : (
              // 'complete' — 도형/AP + 히트맵 오버레이를 한 SVG 안에 겹쳐 표시 (read-only).
              <>
                {isViewingHistoricalRun && <HistoricalRunBubble />}
                <SimulationCanvas
                  sceneVersion={canvasVersionQuery.data}
                  backgroundImageUrl={backgroundImageUrl}
                  aps={aps}
                  onAdd={handleAddAp}
                  onMove={handleMoveAp}
                  onRemove={handleRemoveAp}
                  pending={false}
                  onClearPending={() => {}}
                  heatmapUrl={heatmapUrl}
                  heatmapBounds={heatmapBounds}
                  readOnly
                />
                {heatmapUrl && (
                  <div className="pointer-events-none absolute left-3 top-3 z-10 w-70">
                    <DbmColorBar
                      vmin={heatmapColorScale?.vminDbm ?? -85}
                      vmax={heatmapColorScale?.vmaxDbm ?? -30}
                      label="예측 RSSI (시뮬)"
                    />
                  </div>
                )}
              </>
            )}
          </div>

          <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto">
            {state === 'complete' && (
              <SimulationResultCard
                avgRssiDbm={metrics.avgRssiDbm}
                coveragePercent={metrics.coveragePercent}
                staleReason={null}
              />
            )}
            {/* AP 배치 (§14) 카드 — 백엔드 ap-candidates 미구현 상태라 임시로 숨김.
                백엔드 붙으면 다시 노출.
            {state === 'complete' && activeRunId && (
              <ApPlacementPanel rfRunId={activeRunId} />
            )}
            */}
            <SimulationHistory
              items={history}
              isLoading={pastRunsQuery.isLoading}
              showCompareButton={false}
              onSelect={(id) => setActiveRunId(id)}
            />
          </aside>
        </div>
      )}

      <HelpFab />
    </div>
  );
}

/** 설정 바 segmented control 공통 스타일. */
function simSegmentBtn(active: boolean, disabled?: boolean) {
  return cn(
    'inline-flex h-7 items-center rounded-md px-2.5 text-xs transition-colors',
    disabled && 'cursor-not-allowed opacity-50',
    active
      ? 'bg-blue-50 font-medium text-blue-700'
      : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
  );
}

/** 캔버스 상단 — 과거 run 도면/히트맵 열람 안내 말풍선. */
function HistoricalRunBubble() {
  return (
    <div className="pointer-events-none absolute right-3 top-3 z-10 max-w-[calc(100%-1.5rem)]">
      <div className="relative w-max max-w-none animate-bubble-rise rounded-xl border border-sky-200 bg-sky-50/95 px-3.5 py-2.5 shadow-sm backdrop-blur-sm">
        <p className="text-xs leading-relaxed text-sky-900/90 sm:whitespace-nowrap">
          시뮬레이션 당시 도면과 히트맵을 보고 있습니다. 「다시 실행」을 누르면 현재 공간 편집 도면으로 돌아갑니다.
        </p>
        <span
          className="absolute -bottom-1 right-5 h-2 w-2 rotate-45 border-b border-r border-sky-200 bg-sky-50/95"
          aria-hidden="true"
        />
      </div>
    </div>
  );
}

/** 캔버스 좌상단 모드 안내. */
function CanvasModeBar({ apsCount }: { apsCount: number }) {
  return (
    <div className="pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded-md border border-slate-200/80 bg-white/90 px-2.5 py-1 text-[11px] text-slate-600 backdrop-blur-sm">
      <span className="font-medium text-slate-700">AP 배치 모드</span>
      <span className="text-slate-400">·</span>
      <span className="text-slate-500">
        AP 추가 후 도면 클릭 ({apsCount}/8)
      </span>
    </div>
  );
}

/** 캔버스 우상단 "AP 추가하기" 토글 패널.
 *  active=true (배치 모드) 이면 작은 칩으로 축소돼서 우상단 모서리 클릭 가능하게 함.
 */
function ApAddPanel({
  active,
  onToggle,
  disabled,
}: {
  active: boolean;
  onToggle: () => void;
  disabled: boolean;
}) {
  if (active) {
    return (
      <button
        type="button"
        onClick={onToggle}
        title="클릭하여 배치 모드 취소"
        className="absolute right-3 top-3 z-10 inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50/80 px-2.5 py-1 text-[11px] font-medium text-blue-700 backdrop-blur-sm hover:bg-blue-50"
      >
        <Wifi className="h-3.5 w-3.5" />
        배치 중 · 취소
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      title={disabled ? 'AP는 최대 8개까지 배치할 수 있습니다' : 'AP 추가 모드 시작'}
      aria-label="AP 추가"
      className={cn(
        'absolute right-3 top-3 z-10 flex w-[5.5rem] flex-col items-center gap-2 rounded-lg border border-slate-200 bg-white/95 p-2 backdrop-blur-sm transition-colors',
        !disabled && 'cursor-pointer hover:border-slate-300 hover:bg-slate-50/95',
        disabled && 'cursor-not-allowed opacity-50',
      )}
    >
      <span className="w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-700">
        AP 추가
      </span>
      <span
        className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-500 text-white shadow-sm shadow-blue-500/20"
        aria-hidden
      >
        <Wifi className="h-4 w-4" strokeWidth={2.5} />
      </span>
      {disabled && (
        <span className="text-center text-[10px] leading-tight text-slate-400">최대 8개</span>
      )}
    </button>
  );
}

function PageHeader({
  state,
  hasVersion,
  isStarting,
  apsCount,
  backend,
  onBackendChange,
  frequencyBand,
  onFrequencyBandChange,
  txPowerDbm,
  onTxPowerDbmChange,
  floorId,
  projectId,
  onStart,
  onReset,
}: {
  state: SimulationState;
  hasVersion: boolean;
  isStarting: boolean;
  apsCount: number;
  backend: RfBackend;
  onBackendChange: (b: RfBackend) => void;
  frequencyBand: FrequencyBand;
  onFrequencyBandChange: (band: FrequencyBand) => void;
  txPowerDbm: number;
  onTxPowerDbmChange: (value: number) => void;
  floorId: string | null;
  projectId: string | null;
  onStart: () => void;
  onReset: () => void;
}) {
  return (
    <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">시뮬레이션</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          저장된 도면을 불러와 가구와 AP를 자유롭게 배치하고 예상 품질을 비교합니다.
        </p>
      </div>

      <div className="flex shrink-0 flex-wrap items-center justify-end">
        {state === 'idle' ? (
          <div className="inline-flex flex-wrap items-center rounded-lg border border-slate-200 bg-white p-1">
            <div className="border-b border-slate-100 px-1.5 py-0.5 sm:border-b-0 sm:border-r">
              <div className="inline-flex h-8 items-center rounded-md bg-slate-50 p-0.5">
                <FloorSpaceTypeSelector
                  floorId={floorId}
                  projectId={projectId}
                  showLabel={false}
                  className="h-8"
                  selectClassName="inline-flex h-7 min-w-[6.5rem] cursor-pointer appearance-none rounded-md border-0 bg-blue-50 py-0 pl-2.5 pr-6 text-xs font-medium text-blue-700 shadow-none focus:outline-none focus:ring-0 disabled:opacity-50"
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1 border-b border-slate-100 px-1.5 py-0.5 sm:border-b-0 sm:border-r">
              <RfPhysicalControls
                frequencyBand={frequencyBand}
                onFrequencyBandChange={onFrequencyBandChange}
                txPowerDbm={txPowerDbm}
                onTxPowerDbmChange={onTxPowerDbmChange}
                disabled={isStarting}
              />
            </div>
            <div className="border-b border-slate-100 px-1.5 py-0.5 sm:border-b-0 sm:border-r">
              <BackendToggle value={backend} onChange={onBackendChange} disabled={isStarting} />
            </div>
            <div className="px-1.5 py-0.5">
              <button
                type="button"
                onClick={onStart}
                disabled={!hasVersion || isStarting || apsCount === 0}
                title={
                  apsCount === 0
                    ? 'AP 를 1개 이상 배치해주세요'
                    : '시뮬레이션 실행'
                }
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-blue-500 px-3 text-xs font-medium text-white shadow-sm shadow-blue-500/20 transition-colors hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Play className="h-3 w-3 fill-current" />
                {isStarting ? '요청 중...' : '시뮬레이션 실행'}
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={onReset}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            다시 실행
          </button>
        )}
      </div>
    </header>
  );
}

/** Wi-Fi 대역 · AP 출력 — idle 시 설정 바에 노출. */
function RfPhysicalControls({
  frequencyBand,
  onFrequencyBandChange,
  txPowerDbm,
  onTxPowerDbmChange,
  disabled,
}: {
  frequencyBand: FrequencyBand;
  onFrequencyBandChange: (band: FrequencyBand) => void;
  txPowerDbm: number;
  onTxPowerDbmChange: (value: number) => void;
  disabled?: boolean;
}) {
  const bands: Array<{ key: FrequencyBand; label: string; hint: string }> = [
    { key: '2.4', label: '2.4GHz', hint: 'Use this when Android measurements are on 2.4GHz Wi-Fi.' },
    { key: '5', label: '5GHz', hint: 'Use this when Android measurements are on 5GHz Wi-Fi.' },
  ];
  const handleTxPowerChange = (value: string) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    onTxPowerDbmChange(Math.min(30, Math.max(0, parsed)));
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        role="group"
        aria-label="Wi-Fi 대역"
        className="inline-flex h-8 items-center rounded-md bg-slate-50 p-0.5"
      >
        {bands.map((band) => {
          const active = frequencyBand === band.key;
          return (
            <button
              key={band.key}
              type="button"
              onClick={() => onFrequencyBandChange(band.key)}
              disabled={disabled}
              title={band.hint}
              className={simSegmentBtn(active, disabled)}
            >
              {band.label}
            </button>
          );
        })}
      </div>
      <label className="inline-flex h-8 items-center gap-1.5 px-1 text-xs">
        <span className="text-slate-500">출력</span>
        <input
          type="number"
          min={0}
          max={30}
          step={1}
          value={txPowerDbm}
          onChange={(event) => handleTxPowerChange(event.target.value)}
          disabled={disabled}
          aria-label="AP 출력 (dBm)"
          className="h-6 min-w-11 w-11 rounded border border-slate-200 bg-white px-1.5 text-center text-xs font-medium tabular-nums text-slate-800 [appearance:textfield] focus:border-blue-300 focus:outline-none focus:ring-1 focus:ring-blue-200 disabled:cursor-not-allowed disabled:opacity-50 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        />
        <span className="text-[10px] text-slate-400">dBm</span>
      </label>
    </div>
  );
}

function BackendToggle({
  value,
  onChange,
  disabled,
}: {
  value: RfBackend;
  onChange: (b: RfBackend) => void;
  disabled?: boolean;
}) {
  const options: Array<{ key: RfBackend; label: string; hint: string }> = [
    { key: 'sagemaker', label: 'Cloud', hint: 'SageMaker async (운영 기본)' },
    { key: 'local', label: 'Local', hint: '로컬 ai_api 직접 호출 (테스트용)' },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="시뮬 실행 백엔드"
      className="inline-flex h-8 items-center rounded-md bg-slate-50 p-0.5"
    >
      {options.map((opt) => {
        const active = value === opt.key;
        return (
          <button
            key={opt.key}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.key)}
            disabled={disabled}
            title={opt.hint}
            className={simSegmentBtn(active, disabled)}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** running 상태일 때만 스피너 표시. idle/complete 는 SimulationCanvas 가 직접 렌더. */
function SimulationVisualization({ state }: { state: SimulationState }) {
  if (state === 'running') {
    return (
      <div className="flex h-full min-h-80 flex-col items-center justify-center gap-2 p-4 text-center">
        <Loader2 className="h-7 w-7 animate-spin text-blue-600" />
        <p className="text-sm font-medium text-slate-800">RF 시뮬레이션 진행 중</p>
        <p className="max-w-sm text-xs leading-relaxed text-slate-500">
          서버에서 결과를 계산하는 동안 잠시만 기다려주세요. 최대 약 15분이 소요될 수 있습니다.
        </p>
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-80 flex-col items-center justify-center gap-2 p-4 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50">
        <Play className="h-4 w-4 text-blue-600" />
      </div>
      <p className="text-sm font-medium text-slate-800">시뮬레이션 실행 대기 중</p>
      <p className="max-w-sm text-xs leading-relaxed text-slate-500">
        상단의 시뮬레이션 실행 버튼을 누르면 확정된 도면 기준으로 RF 시뮬레이션이 시작됩니다.
      </p>
    </div>
  );
}

function EmptyState({
  title,
  subtitle,
  ctaLabel,
  ctaTo,
}: {
  title: string;
  subtitle?: string;
  ctaLabel?: string;
  ctaTo?: string;
}) {
  return (
    <div className="mt-5 flex flex-1 items-center justify-center">
      <div className="flex max-w-md flex-col items-center gap-3 rounded-xl border border-dashed bg-background p-10 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
          <MapIcon className="h-6 w-6 text-primary" strokeWidth={1.8} />
        </div>
        <p className="text-base font-semibold">{title}</p>
        {subtitle && (
          <p className="text-xs leading-relaxed text-muted-foreground">{subtitle}</p>
        )}
        {ctaLabel && ctaTo && (
          <Link
            to={ctaTo}
            className="mt-2 inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            {ctaLabel}
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        )}
      </div>
    </div>
  );
}

/**
 * §14 AP 후보/배치 패널.
 * RF Run 이 succeeded 된 후에만 표시되고, 후보 생성 + 후보 선택 → 배치 저장 흐름.
 * 백엔드 ap-candidates 미구현으로 시연 동안 사용처에서만 주석 처리됨 (정의 유지).
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function ApPlacementPanel({ rfRunId }: { rfRunId: string }) {
  const generate = useGenerateApCandidates();
  const candidatesQuery = useApCandidates(rfRunId);
  const layoutsQuery = useApLayouts(rfRunId);
  const createLayout = useCreateApLayout();
  const deleteLayout = useDeleteApLayout(rfRunId);

  const candidates = candidatesQuery.data ?? [];
  const layouts = layoutsQuery.data ?? [];

  const handleGenerate = () => generate.mutate({ rf_run_id: rfRunId, candidate_type: 'auto' });

  const handleConfirmCandidate = (c: ApCandidate) => {
    if (!c.point_geom) return;
    createLayout.mutate({
      rf_run_id: rfRunId,
      ap_name: nextApSequentialName(layouts.map((l) => l.ap_name)),
      point_geom: c.point_geom,
      z_m: c.z_m ?? 2.5,
    });
  };

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <Wifi className="h-4 w-4 text-primary" />
          AP 배치 (§14)
        </h3>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={generate.isPending}
          className="inline-flex items-center gap-1 rounded-md border bg-background px-2.5 py-1 text-xs font-medium hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {generate.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          {candidates.length > 0 ? '재생성' : '후보 생성'}
        </button>
      </div>

      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        시뮬레이션 결과 기반 추천 위치를 확인하고, 마음에 드는 후보를 확정해 배치를 저장하세요.
      </p>

      <section className="mt-3">
        <p className="mb-1.5 text-[11px] font-semibold text-muted-foreground">후보 ({candidates.length})</p>
        {candidatesQuery.isLoading ? (
          <p className="py-2 text-[11px] text-muted-foreground">불러오는 중...</p>
        ) : candidates.length === 0 ? (
          <p className="py-2 text-[11px] text-muted-foreground">
            아직 생성된 후보가 없습니다. 위 버튼으로 생성하세요.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {candidates.map((c) => (
              <li
                key={c.id}
                className="flex items-center justify-between gap-2 rounded-md border bg-background px-2.5 py-1.5 text-xs"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium">
                      {c.score != null ? `점수 ${c.score.toFixed(2)}` : '점수 N/A'}
                    </span>
                    <span className="rounded bg-muted px-1.5 text-[10px] uppercase text-muted-foreground">
                      {c.candidate_type}
                    </span>
                  </div>
                  <p className="truncate text-[10px] text-muted-foreground">
                    {formatPoint(c.point_geom)} · z={c.z_m ?? '?'} m
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => handleConfirmCandidate(c)}
                  disabled={createLayout.isPending}
                  className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                >
                  <CheckCircle2 className="h-3 w-3" />
                  배치
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-3">
        <p className="mb-1.5 text-[11px] font-semibold text-muted-foreground">확정된 배치 ({layouts.length})</p>
        {layoutsQuery.isLoading ? (
          <p className="py-2 text-[11px] text-muted-foreground">불러오는 중...</p>
        ) : layouts.length === 0 ? (
          <p className="py-2 text-[11px] text-muted-foreground">
            아직 확정된 AP 배치가 없습니다.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {layouts.map((l) => (
              <ApLayoutRow
                key={l.id}
                layout={l}
                onDelete={() => deleteLayout.mutate(l.id)}
                disabled={deleteLayout.isPending}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ApLayoutRow({
  layout,
  onDelete,
  disabled,
}: {
  layout: ApLayout;
  onDelete: () => void;
  disabled: boolean;
}) {
  return (
    <li className="flex items-center justify-between gap-2 rounded-md border bg-background px-2.5 py-1.5 text-xs">
      <div className="min-w-0">
        <div className="font-medium">{layout.ap_name}</div>
        <p className="truncate text-[10px] text-muted-foreground">
          {formatPoint(layout.point_geom)} · z={layout.z_m ?? '?'} m
        </p>
      </div>
      <button
        type="button"
        onClick={onDelete}
        disabled={disabled}
        aria-label="삭제"
        className="rounded-md p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </li>
  );
}

/**
 * RfMap.bounds_json → 히트맵 이미지의 실제 미터 좌표 영역.
 * 백엔드 응답 예: { z: 1, min_x, min_y, max_x, max_y }.
 * 4개 좌표 중 하나라도 유효하지 않으면 null → 히트맵 오버레이 생략.
 */
function useSceneFloorplanBackground(
  floorId: string | null,
  sceneVersion: SceneVersion | null | undefined,
): string | null {
  const versionAsDraft = sceneVersion ? versionToDraftShape(sceneVersion) : null;
  const sourceAssetId = versionAsDraft?.source_asset_id ?? null;
  const floorAssetsQuery = useFloorAssets(floorId, 'floorplan_image');
  const fallbackAsset = useMemo(() => {
    const list = floorAssetsQuery.data ?? [];
    if (list.length === 0) return null;
    return [...list].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  }, [floorAssetsQuery.data]);
  const effectiveAssetId = sourceAssetId ?? fallbackAsset?.id ?? null;
  const assetUrlQuery = useAssetDownloadUrl(effectiveAssetId);
  const localImage = useLocalFloorplanImage({ floorId, sourceAssetId });
  useEffect(() => {
    if (floorId && sourceAssetId) linkFloorImageToAsset(floorId, sourceAssetId);
  }, [floorId, sourceAssetId]);
  const assetUrl = assetUrlQuery.data?.url ?? null;
  const usableAssetUrl =
    assetUrl && /^https?:\/\//i.test(assetUrl) ? assetUrl : null;
  return usableAssetUrl ?? localImage ?? null;
}

function parseHeatmapBounds(
  bounds: Record<string, unknown> | null | undefined,
): { minX: number; minY: number; maxX: number; maxY: number } | null {
  if (!bounds) return null;
  const minX = Number(bounds['min_x']);
  const minY = Number(bounds['min_y']);
  const maxX = Number(bounds['max_x']);
  const maxY = Number(bounds['max_y']);
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

function formatPoint(geom: Record<string, unknown> | null): string {
  if (!geom) return '좌표 없음';
  const coords = (geom as { coordinates?: unknown }).coordinates;
  if (Array.isArray(coords) && coords.length >= 2) {
    const x = Number(coords[0]);
    const y = Number(coords[1]);
    if (Number.isFinite(x) && Number.isFinite(y)) {
      return `(${x.toFixed(2)}, ${y.toFixed(2)})`;
    }
  }
  return '좌표 형식 오류';
}

/**
 * 백엔드 metrics_json 에서 표시용 값 추출.
 *
 * 실측 응답 구조 (heatmap / radio_map_dbm 둘 다 동일):
 *   {
 *     rss_dbm: { max, min, mean },                       ← 평균 dBm = mean
 *     coverage_summary: {
 *       "ge_-67": 0~1,   ← RSSI ≥ -67 dBm 인 셀 비율 (양호 임계값)
 *       "ge_-70": 0~1, "ge_-75": 0~1,
 *       total_cell_count, valid_cell_count
 *     },
 *     valid_ratio: 0~1
 *   }
 *
 * 옛 키 이름 (avg_rssi_dbm / coverage_percent 등) 도 fallback 으로 유지.
 */
function parseMetrics(
  ...sources: Array<Record<string, unknown> | undefined>
): { avgRssiDbm: number | null; coveragePercent: number | null } {
  const merged: Record<string, unknown> = {};
  for (const s of sources) {
    if (s) Object.assign(merged, s);
  }
  const toNum = (v: unknown): number | null => {
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) {
      return Number(v);
    }
    return null;
  };
  const pickNumber = (...keys: string[]): number | null => {
    for (const k of keys) {
      const n = toNum(merged[k]);
      if (n !== null) return n;
    }
    return null;
  };

  // 평균 RSSI: 신규 구조 rss_dbm.mean 우선, 없으면 옛 키들.
  const rssDbm = merged['rss_dbm'] as Record<string, unknown> | undefined;
  const avgRssiDbm =
    toNum(rssDbm?.['mean']) ??
    pickNumber('avg_rssi_dbm', 'avg_dbm', 'rssi_avg', 'avg_rssi');

  // 면적 커버리지: 전체 셀 중 양호 (≥-67dBm) 신호가 잡힌 비율.
  //   coverage_summary["ge_-67"]      = 데이터 있는 셀 중 양호 비율 (분모: valid_cell_count)
  //   coverage_summary["valid_cell_ratio"] = 전체 셀 중 데이터 있는 비율 (분모: total_cell_count)
  // → 둘을 곱해야 "전체 면적 중 양호 비율" 이 됨.
  const coverage = merged['coverage_summary'] as Record<string, unknown> | undefined;
  const ge67 = toNum(coverage?.['ge_-67']);
  const validRatio = toNum(coverage?.['valid_cell_ratio']);
  const coveragePercent =
    ge67 !== null && validRatio !== null
      ? ge67 * validRatio * 100
      : ge67 !== null
        ? ge67 * 100 // valid_cell_ratio 없으면 옛 동작 (단순 양호 셀 비율)
        : pickNumber('coverage_percent', 'coverage', 'coverage_pct');

  return { avgRssiDbm, coveragePercent };
}
