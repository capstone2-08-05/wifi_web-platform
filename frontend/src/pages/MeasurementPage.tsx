import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  Clock,
  MapPin,
  Smartphone,
  TrendingUp,
  Wifi,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { HelpFab } from '@/components/HelpFab';
import { MobileConnectModal } from '@/features/mobile/MobileConnectModal';
import { Popover } from '@/components/ui/Popover';
import { useAppStore } from '@/stores/app-store';
import type {
  DetectedAp,
  MeasurementPoint as ApiPoint,
  MeasurementSession,
} from '@/types/measurement-session';
import type { ApLayout } from '@/types/ap-layout';
import type { RfMap } from '@/types/rf';
import { useFloorVersions, useSceneVersion } from '@/hooks/use-scene-version';
import {
  useDetectedAps,
  useEstimatedCoverage,
  useFloorMeasurementSessions,
  useMeasurementPoints,
} from '@/hooks/use-measurement-session';
import { useFloorRfRuns, useRfMaps } from '@/hooks/use-rf-run';
import { useApLayouts } from '@/hooks/use-ap-layouts';
import { useFloorAssets, useAssetDownloadUrl } from '@/hooks/use-assets';
import { useLocalFloorplanImage } from '@/hooks/use-local-floorplan-image';
import { versionToDraftShape } from '@/features/editor/version-as-draft';
import {
  useCalibrationParameterUpdates,
  useCalibrationRun,
  useCreateCalibrationRun,
} from '@/hooks/use-calibration-run';
import { CalibrationCard } from '@/features/calibration/CalibrationCard';
import { parseGeometry } from '@/features/editor/geometry-utils';
import {
  MeasurementCanvas,
  type MeasurementPoint as CanvasPoint,
  type MeasurementPointQuality,
  type MeasurementViewMode,
  type PlacedApSimple,
} from '@/features/measurement/MeasurementCanvas';

export default function MeasurementPage() {
  const floorId = useAppStore((s) => s.selectedFloorId);

  // 확정된 도면 (캔버스 배경).
  const versionsQuery = useFloorVersions(floorId);
  const versions = versionsQuery.data ?? [];
  const currentVersion = versions.find((v) => v.is_current) ?? versions[0] ?? null;
  const versionDetailQuery = useSceneVersion(currentVersion?.id ?? null);
  const sceneVersion = versionDetailQuery.data ?? null;

  // 배경 원본 도면 이미지 — 공간편집/시뮬과 동일한 방식.
  const versionAsDraft = sceneVersion ? versionToDraftShape(sceneVersion) : null;
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

  // 측정 세션. 기본은 최근 세션 자동 선택, 사용자가 '이력 보기' 로 다른 세션 선택 가능.
  const sessionsQuery = useFloorMeasurementSessions(floorId);
  const sessions = sessionsQuery.data?.items ?? [];
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const activeSession =
    sessions.find((s) => s.id === selectedSessionId) ?? sessions[0] ?? null;
  const pointsQuery = useMeasurementPoints(activeSession?.id ?? null);
  const points = pointsQuery.data?.items ?? [];

  const canvasPoints = useMemo(() => apiPointsToCanvas(points), [points]);

  // 가장 최근 succeeded RF Run → AP layouts + RF Map metrics.
  const rfRunsQuery = useFloorRfRuns(floorId, { status: 'succeeded', page_size: 5 });
  const latestRfRunId = rfRunsQuery.data?.items?.[0]?.id ?? null;
  const apLayoutsQuery = useApLayouts(latestRfRunId);
  const canvasAps = useMemo(
    () => apLayoutsToCanvas(apLayoutsQuery.data ?? []),
    [apLayoutsQuery.data],
  );
  const rfMapsQuery = useRfMaps(latestRfRunId, !!latestRfRunId);
  const predictedAvgDbm = useMemo(
    () => extractPredictedAvgDbm(rfMapsQuery.data ?? []),
    [rfMapsQuery.data],
  );
  const measuredAvgDbm = useMemo(() => computeMeasuredAvg(points), [points]);

  // §10.5 발견된 AP 목록.
  const detectedApsQuery = useDetectedAps(activeSession?.id ?? null);
  const detectedAps = detectedApsQuery.data ?? [];

  // #81 GP regression dense RSSI heatmap — 측정점 → 도면 전체 추정.
  const coverageQuery = useEstimatedCoverage(activeSession?.id ?? null);
  const estimatedHeatmap = useMemo(() => {
    const c = coverageQuery.data;
    if (!c) return null;
    return { url: c.heatmap_url, bounds: c.bounds };
  }, [coverageQuery.data]);

  const [mode, setMode] = useState<MeasurementViewMode>('route');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [actionGuideOpen, setActionGuideOpen] = useState(false);

  const hasVersion = versions.length > 0;
  const hasMeasurement = points.length > 0;

  // §11 캘리브레이션 — 현재 측정 세션 + 최근 RF Run + 현재 버전을 입력으로 사용.
  // 측정 페이지에 둠: 진단 카드에서 차이를 발견한 직후 보정 가능.
  const createCalibration = useCreateCalibrationRun();
  const [activeCalibrationId, setActiveCalibrationId] = useState<string | null>(null);
  const calibrationPoll = useCalibrationRun(activeCalibrationId);
  const paramUpdatesQuery = useCalibrationParameterUpdates(
    activeCalibrationId,
    calibrationPoll.isSucceeded,
  );
  const canCalibrate =
    !!activeSession?.id &&
    !!latestRfRunId &&
    !!currentVersion?.id &&
    hasMeasurement;
  const calibrationDisabledReason = !hasMeasurement
    ? '먼저 측정을 진행해주세요.'
    : !latestRfRunId
    ? '비교할 시뮬레이션 결과가 없습니다. 시뮬레이션 페이지에서 실행해주세요.'
    : null;
  const handleCalibrate = () => {
    if (!canCalibrate || !activeSession || !latestRfRunId || !currentVersion) return;
    createCalibration.mutate(
      {
        session_id: activeSession.id,
        rf_run_id: latestRfRunId,
        version_id: currentVersion.id,
      },
      { onSuccess: (run) => setActiveCalibrationId(run.id) },
    );
  };

  return (
    <div className="relative flex h-full flex-col gap-5 p-6">
      <PageHeader
        sessions={sessions}
        activeSession={activeSession}
        onSelectSession={(id) => setSelectedSessionId(id)}
        onStartMeasurement={() => setMobileOpen(true)}
      />

      {!floorId ? (
        <EmptyState
          title="층을 먼저 선택해주세요"
          subtitle="상단 셀렉터에서 작업할 도면(층)을 선택하면 측정 시작 흐름이 표시됩니다."
        />
      ) : !hasVersion ? (
        <EmptyState
          title="확정된 도면이 필요합니다"
          subtitle="공간 편집에서 도면을 분석·확정한 후 모바일 앱으로 실측을 진행할 수 있습니다."
        />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 xl:grid-cols-[1fr_22rem]">
          <section className="flex min-h-0 flex-col gap-3">
            <TabBar mode={mode} onChange={setMode} />
            <div className="relative flex min-h-0 flex-1 flex-col gap-2 rounded-xl border bg-card p-4 shadow-sm">
              <Legend />
              <div className="relative min-h-112 flex-1">
                <MeasurementCanvas
                  sceneVersion={sceneVersion}
                  backgroundImageUrl={backgroundImageUrl}
                  points={canvasPoints}
                  aps={canvasAps}
                  mode={mode}
                  estimatedHeatmap={estimatedHeatmap}
                />
                {!hasMeasurement && <CanvasEmptyOverlay loading={pointsQuery.isFetching} />}
              </div>
            </div>
          </section>

          <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto">
            <DiagnosticCard
              points={canvasPoints}
              predictedAvgDbm={predictedAvgDbm}
              measuredAvgDbm={measuredAvgDbm}
            />
            <CalibrationCard
              run={calibrationPoll.run}
              isPolling={calibrationPoll.isPolling}
              isStarting={createCalibration.isPending}
              canCalibrate={canCalibrate}
              disabledReason={calibrationDisabledReason}
              onCalibrate={handleCalibrate}
              parameterUpdates={paramUpdatesQuery.data ?? []}
            />
            <CauseAnalysisCard
              hasData={hasMeasurement}
              onOpenGuide={() => setActionGuideOpen(true)}
            />
            {detectedAps.length > 0 && <DetectedApsCard aps={detectedAps} />}
          </aside>
        </div>
      )}

      <MobileConnectModal open={mobileOpen} onClose={() => setMobileOpen(false)} />
      <ActionGuideModal open={actionGuideOpen} onClose={() => setActionGuideOpen(false)} />
      <HelpFab />
    </div>
  );
}

// ============================================
// API → 캔버스 포인트 변환
// ============================================

/** RSSI(dBm) → 신호 품질 라벨. 일반적인 Wi-Fi 임계값(>-67 양호 / >-75 주의 / 이하 불량). */
function qualityFromRssi(rssi: number | null): MeasurementPointQuality {
  if (rssi == null) return 'warning';
  if (rssi >= -67) return 'good';
  if (rssi >= -75) return 'warning';
  return 'poor';
}

function apiPointsToCanvas(points: ApiPoint[]): CanvasPoint[] {
  return points.map((p, idx) => ({
    id: p.id,
    x_m: p.floor_position.x,
    y_m: p.floor_position.y,
    quality: qualityFromRssi(p.rssi_dbm),
    order: p.step_index ?? idx + 1,
  }));
}

/** ApLayout.point_geom → 캔버스 AP 마커. 파싱 실패한 건 제외. */
function apLayoutsToCanvas(layouts: ApLayout[]): PlacedApSimple[] {
  const result: PlacedApSimple[] = [];
  for (const l of layouts) {
    const g = parseGeometry(l.point_geom);
    if (g?.type !== 'Point') continue;
    const [x, y] = g.coordinates;
    result.push({ id: l.id, x_m: x, y_m: y, label: l.ap_name });
  }
  return result;
}

/** RfMap.metrics_json.rss_dbm.mean 추출 (없으면 옛 avg_rssi_dbm fallback). */
function extractPredictedAvgDbm(maps: RfMap[]): number | null {
  for (const m of maps) {
    const v = readRssMean(m.metrics_json);
    if (v != null) return v;
  }
  return null;
}

function readRssMean(metrics: Record<string, unknown> | null | undefined): number | null {
  if (!metrics) return null;
  const rss = metrics['rss_dbm'];
  if (rss && typeof rss === 'object') {
    const mean = (rss as Record<string, unknown>)['mean'];
    if (typeof mean === 'number' && Number.isFinite(mean)) return mean;
  }
  const legacy = metrics['avg_rssi_dbm'];
  if (typeof legacy === 'number' && Number.isFinite(legacy)) return legacy;
  return null;
}

function computeMeasuredAvg(points: ApiPoint[]): number | null {
  const vals = points.map((p) => p.rssi_dbm).filter((v): v is number => v != null);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

// ============================================
// 헤더
// ============================================

function PageHeader({
  sessions,
  activeSession,
  onSelectSession,
  onStartMeasurement,
}: {
  sessions: MeasurementSession[];
  activeSession: MeasurementSession | null;
  onSelectSession: (id: string) => void;
  onStartMeasurement: () => void;
}) {
  const hasSessions = sessions.length > 0;
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">실측 및 진단</h1>
        <p className="text-sm text-muted-foreground">
          모바일 기기로 측정한 실제 와이파이 품질 데이터와 시뮬레이션을 통합하여 분석합니다.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Popover
          align="end"
          contentClassName="w-72 max-h-80 overflow-y-auto"
          trigger={({ toggle }) => (
            <button
              type="button"
              onClick={toggle}
              disabled={!hasSessions}
              className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm font-medium text-foreground shadow-sm hover:bg-accent disabled:opacity-50"
            >
              <Clock className="h-4 w-4 text-muted-foreground" />
              이력 보기
              {activeSession && (
                <span className="text-xs font-normal text-muted-foreground">
                  ({formatRelative(activeSession.created_at)})
                </span>
              )}
            </button>
          )}
        >
          {({ close }) => (
            <div className="py-1">
              <p className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                측정 세션 ({sessions.length})
              </p>
              {sessions.map((s) => {
                const isActive = activeSession?.id === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      onSelectSession(s.id);
                      close();
                    }}
                    className={cn(
                      'flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-xs hover:bg-accent',
                      isActive && 'bg-accent',
                    )}
                  >
                    <span className="flex w-full items-center justify-between">
                      <span className="font-medium text-foreground">
                        {formatRelative(s.created_at)}
                      </span>
                      <SessionStatusBadge status={s.status} />
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {s.measurement_type} · {s.id.slice(0, 8)}…
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </Popover>
        <button
          type="button"
          onClick={onStartMeasurement}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90"
        >
          <Smartphone className="h-4 w-4" />
          새로운 측정 시작
        </button>
      </div>
    </header>
  );
}

function SessionStatusBadge({ status }: { status: string }) {
  const style =
    status === 'completed'
      ? 'bg-emerald-100 text-emerald-700'
      : status === 'in_progress'
      ? 'bg-amber-100 text-amber-700'
      : 'bg-muted text-muted-foreground';
  const label =
    status === 'completed' ? '완료' : status === 'in_progress' ? '진행 중' : status;
  return (
    <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium', style)}>{label}</span>
  );
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  if (sameDay(d, today)) return `오늘 ${hh}:${mm}`;
  if (sameDay(d, yesterday)) return `어제 ${hh}:${mm}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`;
}

function sameDay(a: Date, b: Date) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

// ============================================
// 탭 / 범례
// ============================================

const TABS: { id: MeasurementViewMode; label: string }[] = [
  { id: 'route', label: '측정 경로 보기' },
  { id: 'heatmap', label: '실측 히트맵' },
  { id: 'both', label: '예측·실측 통합 분석' },
];

function TabBar({
  mode,
  onChange,
}: {
  mode: MeasurementViewMode;
  onChange: (m: MeasurementViewMode) => void;
}) {
  return (
    <div role="tablist" className="flex items-center gap-6 border-b">
      {TABS.map((t) => {
        const active = mode === t.id;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={cn(
              '-mb-px border-b-2 px-1 py-2.5 text-sm font-medium transition-colors',
              active
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

function Legend() {
  return (
    <div className="inline-flex w-fit items-center gap-3 rounded-md border bg-background px-3 py-1.5 text-[11px] text-muted-foreground shadow-sm">
      <span className="font-semibold text-foreground">실측 포인트 범례</span>
      <LegendDot color="oklch(0.72 0.18 145)" label="양호" />
      <LegendDot color="oklch(0.78 0.15 85)" label="주의" />
      <LegendDot color="oklch(0.62 0.22 25)" label="불량" />
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="inline-block h-2 w-2 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}

function CanvasEmptyOverlay({ loading }: { loading: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div className="pointer-events-auto max-w-sm rounded-xl border bg-background/95 px-5 py-4 text-center shadow-sm backdrop-blur">
        <p className="text-sm font-semibold">
          {loading ? '측정 데이터 불러오는 중...' : '측정 데이터가 없습니다'}
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          상단의 "새로운 측정 시작" 또는 헤더의 "모바일 앱 연결" 로 측정을 진행하면
          여기에 결과가 표시됩니다.
        </p>
      </div>
    </div>
  );
}

// ============================================
// 우측 진단 카드
// ============================================

function DiagnosticCard({
  points,
  predictedAvgDbm,
  measuredAvgDbm,
}: {
  points: CanvasPoint[];
  predictedAvgDbm: number | null;
  measuredAvgDbm: number | null;
}) {
  // 가장 신호가 약한 (불량 > 주의 > 양호) 포인트를 우선 노출.
  const worst = useMemo(() => (points.length > 0 ? pickWorstPoint(points) : null), [points]);

  if (!worst) {
    return (
      <div className="rounded-xl border bg-card p-4 shadow-sm">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <TrendingUp className="h-4 w-4 text-primary" />
          예측·실측 통합 진단
        </h2>
        <p className="mt-3 text-xs text-muted-foreground">
          측정 데이터가 없습니다. 모바일 앱으로 측정을 진행하면 가장 신호가 약한 지점의
          진단이 자동으로 표시됩니다.
        </p>
      </div>
    );
  }

  const statusLabel =
    worst.quality === 'poor'
      ? '상태 불량'
      : worst.quality === 'warning'
      ? '상태 주의'
      : '상태 양호';
  const statusStyle =
    worst.quality === 'poor'
      ? 'bg-destructive/10 text-destructive'
      : worst.quality === 'warning'
      ? 'bg-amber-100 text-amber-700'
      : 'bg-emerald-100 text-emerald-700';

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold">
        <TrendingUp className="h-4 w-4 text-primary" />
        예측·실측 통합 진단
      </h2>

      <div className="mt-4 flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <MapPin className="h-4 w-4 text-destructive" />
          <p className="text-sm font-semibold">
            측정 포인트{' '}
            <span className="text-muted-foreground">#{worst.order}</span>
          </p>
        </div>
        <span className={cn('rounded-md px-2 py-0.5 text-[11px] font-medium', statusStyle)}>
          {statusLabel}
        </span>
      </div>

      <p className="mt-1 text-[11px] text-muted-foreground">
        좌표 {worst.x_m.toFixed(2)}, {worst.y_m.toFixed(2)} m
      </p>

      {/* 예측 vs 실측 평균 비교. RF Run 결과(예측 평균 dBm) + 측정 평균 RSSI. */}
      <div className="mt-3 grid grid-cols-2 gap-2 rounded-lg border bg-muted/40 p-3">
        <DbmCell label="예측 평균 (시뮬레이션)" value={predictedAvgDbm} tone="muted" />
        <DbmCell
          label="실측 평균"
          value={measuredAvgDbm}
          tone={
            predictedAvgDbm != null && measuredAvgDbm != null && measuredAvgDbm - predictedAvgDbm < -8
              ? 'danger'
              : 'normal'
          }
        />
      </div>

      <DiffNote predicted={predictedAvgDbm} measured={measuredAvgDbm} />
    </div>
  );
}

function DiffNote({
  predicted,
  measured,
}: {
  predicted: number | null;
  measured: number | null;
}) {
  if (predicted == null) {
    return (
      <p className="mt-2 text-[11px] text-muted-foreground">
        비교 가능한 시뮬레이션 결과가 없습니다. 먼저 시뮬레이션을 실행해주세요.
      </p>
    );
  }
  if (measured == null) return null;
  const diff = measured - predicted;
  const tone =
    diff < -8 ? 'text-destructive' : diff < -3 ? 'text-amber-700' : 'text-muted-foreground';
  const tail = diff < -8 ? ' — 예상보다 크게 약합니다.' : diff < -3 ? ' — 일부 약화.' : '';
  return (
    <p className={cn('mt-2 text-[11px]', tone)}>
      예측 대비 실측 {diff >= 0 ? '+' : ''}
      {diff.toFixed(1)} dBm{tail}
    </p>
  );
}

function DbmCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | null;
  tone: 'normal' | 'muted' | 'danger';
}) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          'mt-0.5 text-2xl font-bold tabular-nums',
          tone === 'danger' && 'text-destructive',
          tone !== 'danger' && 'text-foreground',
        )}
      >
        {value == null ? (
          <span className="text-base text-muted-foreground">—</span>
        ) : (
          <>
            {value.toFixed(1)}
            <span className="ml-0.5 text-xs font-medium text-muted-foreground">dBm</span>
          </>
        )}
      </p>
    </div>
  );
}

function pickWorstPoint(points: CanvasPoint[]): CanvasPoint {
  const rank: Record<MeasurementPointQuality, number> = {
    poor: 0,
    warning: 1,
    good: 2,
  };
  return [...points].sort((a, b) => rank[a.quality] - rank[b.quality])[0];
}

function CauseAnalysisCard({
  hasData,
  onOpenGuide,
}: {
  hasData: boolean;
  onOpenGuide: () => void;
}) {
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <AlertTriangle className="h-4 w-4 text-amber-500" />
        원인 분석 및 조치
      </h3>
      {hasData ? (
        <p className="mt-2 rounded-md bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-900">
          캘리브레이션 결과가 도착하면 신호 약화의 원인 후보와 조치가 여기에 표시됩니다.
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          불량 지점이 검출되면 원인 후보와 조치 방안이 여기에 표시됩니다.
        </p>
      )}
      <button
        type="button"
        onClick={onOpenGuide}
        className="mt-3 inline-flex w-full items-center justify-center gap-1 rounded-md border bg-background px-3 py-2 text-xs font-medium text-foreground hover:bg-accent"
      >
        조치 방법 확인하기
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ============================================
// 발견된 AP 목록 카드
// ============================================

function DetectedApsCard({ aps }: { aps: DetectedAp[] }) {
  // RSSI 강한 순(절댓값 작은 순)으로 정렬.
  const sorted = useMemo(
    () =>
      [...aps].sort((a, b) => (b.rssi_avg ?? -200) - (a.rssi_avg ?? -200)),
    [aps],
  );
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <Wifi className="h-4 w-4 text-primary" />
        발견된 AP ({sorted.length})
      </h3>
      <ul className="mt-2 space-y-1.5">
        {sorted.map((ap) => (
          <li
            key={ap.ap_bssid}
            className="flex items-center justify-between gap-2 rounded-md border bg-background px-2.5 py-1.5 text-xs"
          >
            <div className="min-w-0">
              <p className="truncate font-medium">{ap.ap_ssid ?? '(SSID 없음)'}</p>
              <p className="truncate text-[10px] text-muted-foreground">
                {ap.ap_bssid}
                {ap.channel != null && ` · ch ${ap.channel}`}
                {ap.frequency_mhz != null && ` · ${(ap.frequency_mhz / 1000).toFixed(1)}GHz`}
              </p>
            </div>
            <div className="text-right tabular-nums">
              <p className="text-xs font-semibold">
                {ap.rssi_avg != null ? `${ap.rssi_avg.toFixed(0)} dBm` : '—'}
              </p>
              <p className="text-[10px] text-muted-foreground">{ap.point_count}회</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ============================================
// 조치 방법 모달
// ============================================

function ActionGuideModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        className="relative w-full max-w-md rounded-2xl border bg-card p-6 shadow-xl"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="닫기"
          className="absolute right-3 top-3 inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
        <h2 className="flex items-center gap-1.5 text-base font-semibold">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          신호 약화 조치 가이드
        </h2>
        <p className="mt-1.5 text-xs text-muted-foreground">
          예측보다 실측이 크게 낮은 지점에서 시도해볼 수 있는 일반적인 조치들입니다.
        </p>
        <ol className="mt-4 space-y-3">
          <GuideStep n={1} title="AP 위치 재배치" body="해당 지점과 가까운 위치로 AP 를 옮기거나, 벽·금속 구조물에서 떨어뜨려 보세요. 시뮬레이션 페이지에서 후보 위치를 재생성할 수 있습니다." />
          <GuideStep n={2} title="벽 재질 확인" body="콘크리트·금속 가벽은 전파 흡수가 큽니다. 도면 편집에서 해당 벽의 재질을 실제와 맞게 수정하면 시뮬레이션 정확도가 올라갑니다." />
          <GuideStep n={3} title="채널·대역 점검" body="2.4GHz 대역은 간섭이 심합니다. 발견된 AP 목록에서 동일 채널이 많이 잡히면 AP 채널을 변경하거나 5GHz 우선 사용을 검토하세요." />
          <GuideStep n={4} title="송신 출력 조정" body="AP 송신 출력이 너무 낮으면 외곽 커버리지가 부족합니다. 시뮬레이션 파라미터의 tx_power_dbm 을 올려 재시뮬레이션 해보세요." />
        </ol>
        <button
          type="button"
          onClick={onClose}
          className="mt-5 w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          확인
        </button>
      </div>
    </div>
  );
}

function GuideStep({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <li className="flex gap-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
        {n}
      </span>
      <div>
        <p className="text-sm font-semibold">{title}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{body}</p>
      </div>
    </li>
  );
}

// ============================================
// 빈 상태
// ============================================

function EmptyState({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="flex max-w-lg flex-col items-center gap-3 rounded-2xl border border-dashed bg-background p-10 text-center shadow-sm">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
          <Activity className="h-6 w-6 text-primary" strokeWidth={1.8} />
        </div>
        <p className="text-base font-semibold">{title}</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{subtitle}</p>
      </div>
    </div>
  );
}
