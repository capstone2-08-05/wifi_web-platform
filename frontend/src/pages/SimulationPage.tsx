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
import { useFloorAssets, useAssetDownloadUrl } from '@/hooks/use-assets';
import { useLocalFloorplanImage } from '@/hooks/use-local-floorplan-image';
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
import type { ApCandidate, ApLayout } from '@/types/ap-layout';
import type { RfBackend } from '@/types/rf';
import { cn } from '@/lib/utils';

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

  // 캔버스 배경으로 보여줄 확정 버전 상세 (rooms/walls/openings/objects 포함).
  const versionDetailQuery = useSceneVersion(currentVersion?.id ?? null);

  // 배경 도면 이미지 — 공간편집/대시보드와 동일한 방식.
  // (a) version 의 source_asset_id 가 있으면 presigned URL, (b) 없으면 floor 의
  // 가장 최근 floorplan_image asset, (c) 백엔드 자산 없으면 localStorage 캐시.
  const versionAsDraft = versionDetailQuery.data
    ? versionToDraftShape(versionDetailQuery.data)
    : null;
  const sourceAssetId = versionAsDraft?.source_asset_id ?? null;
  const floorAssetsQuery = useFloorAssets(floorId, 'floorplan_image');
  const fallbackAsset = (floorAssetsQuery.data ?? [])
    .slice()
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  const effectiveAssetId = sourceAssetId ?? fallbackAsset?.id ?? null;
  const assetUrlQuery = useAssetDownloadUrl(effectiveAssetId);
  // sourceAssetId 우선 — 히스토리 버전 클릭 시 그 자산 이미지로 정확히 복원.
  const localImage = useLocalFloorplanImage({ floorId, sourceAssetId });
  const assetUrl = assetUrlQuery.data?.url ?? null;
  const usableAssetUrl =
    assetUrl && /^https?:\/\//i.test(assetUrl) ? assetUrl : null;
  const backgroundImageUrl = usableAssetUrl ?? localImage ?? null;

  // 층의 과거 RF Run 목록 (이력 카드 + 자동 복원용).
  const pastRunsQuery = useFloorRfRuns(floorId, { page_size: 20 });
  const pastRuns = useMemo(() => pastRunsQuery.data?.items ?? [], [pastRunsQuery.data]);

  // 활성 run = 사용자가 명시 선택한 것 ?? 현재 scene_version 으로 돌린 최근 succeeded.
  // → 새로고침/재진입 시에도 자동 활성, 단 **현재 버전과 일치하는 run** 만 대상.
  //   공간편집으로 새 버전 만든 직후 시뮬 페이지로 오면 옛 run 은 자동복원 안 됨 → idle.
  // 단 사용자가 명시적으로 "다시 실행" 누른 직후엔 idle 유지.
  // 명시 선택(pickedRunId) 은 버전 일치 무관 — 사용자가 기록에서 직접 골랐으니 존중.
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

  // 시뮬레이션 페이지는 배경 도면 이미지를 안 깔음 — 도형만 + 히트맵 오버레이.
  // (배경 이미지는 공간편집/대시보드 한정.)

  const createRfRun = useCreateRfRun();
  const rfRunPoll = useRfRun(activeRunId);
  const rfMapsQuery = useRfMaps(activeRunId, rfRunPoll.isSucceeded);
  // 활성 RfRun 이 현재 버전이 아닌 옛 버전에서 돌린 것이면 → 도면이 바뀌어서 히트맵이 도면과 안 맞음.
  // 사용자 혼란 방지로 그런 경우엔 히트맵 숨김 (메트릭은 그대로 표시).
  const activeRunSceneVersionId = rfRunPoll.rfRun?.scene_version_id ?? null;
  const isRunForCurrentVersion =
    !activeRunSceneVersionId ||
    !currentVersion ||
    activeRunSceneVersionId === currentVersion.id;

  // 활성 run(과거/자동복원 포함)의 AP 를 캔버스에 복원 — 결과 화면에 AP 마커가 보이도록.
  // (aps state 는 사용자가 직접 찍은 것만 담기는데, 과거 run 을 불러올 땐 비어 있어 마커가 안 떴음)
  useEffect(() => {
    const aps_raw = (rfRunPoll.rfRun?.request_json?.['access_points'] ?? []) as Array<
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
  }, [rfRunPoll.rfRun]);
  // 백엔드가 RfMapResponse 에 presigned `url` 을 자동 채워주므로 (PR #70)
  // /rf-jobs 별도 호출 없이 /maps 응답 하나로 heatmap URL + bounds 둘 다 처리.
  const heatmapMap = useMemo(() => {
    if (!isRunForCurrentVersion) return null;
    const maps = rfMapsQuery.data ?? [];
    return maps.find((m) => m.map_type === 'heatmap') ?? maps[0] ?? null;
  }, [rfMapsQuery.data, isRunForCurrentVersion]);
  const heatmapUrl = heatmapMap?.url ?? null;
  // 히트맵 색 스케일 (vmin/vmax dBm) — color legend 가 같은 inferno 그라데이션 +
  // 동일 범위로 표시. local backend / 최신 sagemaker container 가 응답에 채워넣음.
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

  // 백엔드 상태 → UI 상태 매핑
  const state: SimulationState = (() => {
    if (!activeRunId) return 'idle';
    if (rfRunPoll.isSucceeded) return 'complete';
    if (rfRunPoll.isFailed) return 'idle'; // 토스트로 알림 + 다시 시작 가능
    return 'running';
  })();

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
    setPickedRunId(null);
    setResetCleared(true);
    // AP 위치는 유지 — 보정 후 동일 배치로 재시뮬하는 케이스가 많음.
    // 새로 찍고 싶으면 캔버스에서 개별 삭제하면 됨.
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
            label: `시뮬레이션 결과 #${r.id.slice(0, 6)}`,
            timeLabel: formatRunTime(r.created_at),
            avgRssiDbm: m.avgRssiDbm,
            coveragePercent: m.coveragePercent,
            active: r.id === activeRunId,
          };
        }),
    [pastRuns, activeRunId, activeMapMetrics],
  );

  return (
    <div className="relative flex h-full flex-col p-6">
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
        <div className="mt-5 grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
          <div className="relative min-h-0 overflow-hidden rounded-2xl border bg-background shadow-sm">
            {state === 'idle' ? (
              <>
                <CanvasModeBar apsCount={aps.length} />
                <SimulationCanvas
                  sceneVersion={versionDetailQuery.data}
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
              <div className="h-full p-6">
                <SimulationVisualization state={state} />
              </div>
            ) : (
              // 'complete' — 도형/AP + 히트맵 오버레이를 한 SVG 안에 겹쳐 표시 (read-only).
              <>
                {!isRunForCurrentVersion && (
                  <div className="absolute left-3 right-3 top-3 z-10 rounded-md border border-amber-300 bg-amber-50/95 px-3 py-2 text-[11px] leading-relaxed text-amber-900 shadow-sm backdrop-blur">
                    이 시뮬레이션은 이전 버전 도면 기준이라 현재 도면과 다를 수 있어
                    히트맵을 표시하지 않습니다. 새 버전으로 다시 실행해주세요.
                  </div>
                )}
                <SimulationCanvas
                  sceneVersion={versionDetailQuery.data}
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
                {heatmapUrl && isRunForCurrentVersion && (
                  // 좌상단 — gradient + tick 값이 수직 정렬돼 "이 색 = 이 dBm" 직관적.
                  // MeasurementPage 와 동일 위치/크기로 통일.
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

          <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
            {state === 'complete' && (
              <SimulationResultCard
                avgRssiDbm={isRunForCurrentVersion ? metrics.avgRssiDbm : null}
                coveragePercent={isRunForCurrentVersion ? metrics.coveragePercent : null}
                staleReason={
                  isRunForCurrentVersion
                    ? null
                    : '이전 버전 도면에서 돌린 시뮬레이션이라 현재 도면과 비교 가치가 없어 결과를 숨겼습니다.'
                }
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
              showCompareButton={false}
              onSelect={(id) => setActiveRunId(id)}
              emptyMessage="아직 시뮬레이션 기록이 없습니다. AP 를 배치하고 시뮬레이션을 실행해보세요."
            />
          </aside>
        </div>
      )}

      <HelpFab />
    </div>
  );
}

/** 캔버스 좌상단 모드 안내. */
function CanvasModeBar({ apsCount }: { apsCount: number }) {
  return (
    <div className="pointer-events-none absolute left-4 top-4 z-10 flex items-center gap-2 rounded-full border bg-card/95 px-3 py-1.5 text-xs shadow-sm backdrop-blur">
      <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Play className="h-2.5 w-2.5 fill-current" />
      </span>
      <span className="font-semibold">AP 배치 모드</span>
      <span className="text-muted-foreground">
        — 우측 "AP 추가" 누르고 도면을 클릭하세요 ({apsCount}/8)
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
        className="absolute right-4 top-4 z-10 inline-flex items-center gap-1.5 rounded-full border border-primary bg-primary/10 px-3 py-1.5 text-[11px] font-medium text-primary shadow-sm backdrop-blur hover:bg-primary/20"
      >
        <span
          className="flex h-4 w-4 items-center justify-center rounded-full text-white"
          style={{ backgroundColor: 'oklch(0.55 0.22 254)' }}
        >
          <Wifi className="h-2.5 w-2.5" />
        </span>
        도면 클릭으로 배치 · 취소
      </button>
    );
  }

  return (
    <div className="absolute right-4 top-4 z-10 w-32 rounded-xl border bg-card p-3 shadow-md">
      <p className="mb-2 text-center text-xs font-semibold text-muted-foreground">
        AP 추가하기
      </p>
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled}
        className={cn(
          'flex w-full flex-col items-center gap-1.5 rounded-lg border bg-background p-2 text-[11px] font-medium transition-colors hover:bg-accent',
          disabled && 'cursor-not-allowed opacity-50',
        )}
      >
        <span
          className="flex h-9 w-9 items-center justify-center rounded-full text-white"
          style={{ backgroundColor: 'oklch(0.55 0.22 254)' }}
        >
          <Wifi className="h-4 w-4" />
        </span>
        AP 추가
      </button>
      {disabled && (
        <p className="mt-2 text-center text-[10px] text-destructive">최대 8개</p>
      )}
    </div>
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
    <header className="flex items-start justify-between gap-4">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">시뮬레이션</h1>
        <p className="text-sm text-muted-foreground">
          저장된 도면을 불러와 가구와 AP를 자유롭게 배치하고 예상 품질을 비교합니다.
        </p>
      </div>

      <div className="flex shrink-0 flex-wrap items-center justify-end gap-3">
        {state === 'idle' && (
          <>
            {/* 공간 유형 — Floor.space_type 직접 수정. 변경 시 즉시 저장 (다음 calibration 에 자동 반영).
                현재 sim 동작에는 영향 없지만 사용자는 "이 공간을 시뮬한다" 라는 멘탈모델로 여기서 정함. */}
            <FloorSpaceTypeSelector
              floorId={floorId}
              projectId={projectId}
              showLabel={false}
            />
            <RfPhysicalControls
              frequencyBand={frequencyBand}
              onFrequencyBandChange={onFrequencyBandChange}
              txPowerDbm={txPowerDbm}
              onTxPowerDbmChange={onTxPowerDbmChange}
              disabled={isStarting}
            />
            <BackendToggle value={backend} onChange={onBackendChange} disabled={isStarting} />
          </>
        )}
        {state === 'idle' ? (
          <button
            type="button"
            onClick={onStart}
            disabled={!hasVersion || isStarting || apsCount === 0}
            title={
              apsCount === 0
                ? 'AP 를 1개 이상 배치해주세요'
                : '시뮬레이션 실행'
            }
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-4 w-4 fill-current" />
            {isStarting ? '요청 중...' : '시뮬레이션 실행'}
          </button>
        ) : (
          <button
            type="button"
            onClick={onReset}
            className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm font-medium text-foreground/80 shadow-sm hover:bg-accent"
          >
            <RotateCcw className="h-4 w-4" />
            다시 실행
          </button>
        )}
      </div>
    </header>
  );
}

/** SageMaker | Local 백엔드 토글 (idle 일 때만 노출). */
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
    <div className="inline-flex items-center gap-2 rounded-lg border bg-background p-1 shadow-sm">
      <div className="inline-flex items-center gap-0.5 rounded-md bg-muted/50 p-0.5">
        {bands.map((band) => {
          const active = frequencyBand === band.key;
          return (
            <button
              key={band.key}
              type="button"
              onClick={() => onFrequencyBandChange(band.key)}
              disabled={disabled}
              title={band.hint}
              className={cn(
                'rounded px-2 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                active
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {band.label}
            </button>
          );
        })}
      </div>
      <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        Tx
        <input
          type="number"
          min={0}
          max={30}
          step={1}
          value={txPowerDbm}
          onChange={(event) => handleTxPowerChange(event.target.value)}
          disabled={disabled}
          className="h-7 w-14 rounded-md border bg-background px-2 text-right text-xs font-medium text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        />
        dBm
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
      className="inline-flex items-center gap-0.5 rounded-lg border bg-background p-0.5 shadow-sm"
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
            className={cn(
              'rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              active
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
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
      <div className="flex h-full min-h-80 flex-col items-center justify-center gap-2 text-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-sm font-medium">RF 시뮬레이션 진행 중</p>
        <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
          서버에서 결과를 계산하는 동안 잠시만 기다려주세요. 최대 약 15분이 소요될 수 있습니다.
        </p>
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-80 flex-col items-center justify-center gap-2 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
        <Play className="h-5 w-5 text-primary" />
      </div>
      <p className="text-sm font-medium">시뮬레이션 실행 대기 중</p>
      <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
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
    const seq = layouts.length + 1;
    createLayout.mutate({
      rf_run_id: rfRunId,
      ap_name: `AP-${String(seq).padStart(2, '0')}`,
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
/** RF Run.created_at → "방금 전" / "오늘 14:32" / "어제 09:10" / "5/18 14:32". */
function formatRunTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  if (diffMs < 60_000) return '방금 전';
  if (diffMs < 3600_000) return `${Math.floor(diffMs / 60_000)}분 전`;
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (sameDay(d, now)) return `오늘 ${hh}:${mm}`;
  if (sameDay(d, yesterday)) return `어제 ${hh}:${mm}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`;
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
