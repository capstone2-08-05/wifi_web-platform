import { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  Clock,
  Loader2,
  MapPin,
  Smartphone,
  TrendingUp,
  Wifi,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { RSSI_HEATMAP_GRADIENT_CSS } from '@/lib/rssi-colormap';
import { HelpFab } from '@/components/HelpFab';
import { MobileConnectModal } from '@/features/mobile/MobileConnectModal';
import { Popover } from '@/components/ui/Popover';
import { useAppStore } from '@/stores/app-store';
import { useFloors } from '@/hooks/use-floors';
import { FloorSpaceTypeSelector } from '@/features/floor/FloorSpaceTypeSelector';
import { DbmColorBar } from '@/features/simulation/DbmColorBar';
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
import { useEvaluateCalibrationRun } from '@/hooks/use-calibration-run';
import { CalibrationCard, type CalibrationGate } from '@/features/calibration/CalibrationCard';
import type { CalibrationEvaluationResponse, SpaceType } from '@/types/calibration-run';
import { parseGeometry } from '@/features/editor/geometry-utils';
import {
  MeasurementCanvas,
  type MeasurementPoint as CanvasPoint,
  type MeasurementPointQuality,
  type MeasurementViewMode,
  type PlacedApSimple,
} from '@/features/measurement/MeasurementCanvas';

const EMPTY_MEASUREMENT_SESSIONS: MeasurementSession[] = [];
const EMPTY_MEASUREMENT_POINTS: ApiPoint[] = [];

export default function MeasurementPage() {
  const queryClient = useQueryClient();
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

  // calibration soft prior — Floor.space_type 이 source of truth (헤더 FloorSpaceTypeSelector).
  const projectIdForFloors = useAppStore((s) => s.selectedProjectId);
  const floorsList = useFloors(projectIdForFloors);
  const currentFloor = floorsList.data?.find((f) => f.id === floorId) ?? null;
  const spaceType: SpaceType = currentFloor?.space_type ?? 'unknown';

  // 측정 세션. 기본은 최근 세션 자동 선택, 사용자가 '이력 보기' 로 다른 세션 선택 가능.
  // 모바일 측정 완료 후 웹에 세션이 늦게 반영되는 경우가 있어 주기적으로 목록 갱신.
  const sessionsQuery = useFloorMeasurementSessions(floorId, { refetchInterval: 5_000 });
  const allSessions = sessionsQuery.data?.items ?? EMPTY_MEASUREMENT_SESSIONS;
  // 현재 도면 버전이 생성된 이후에 측정된 세션만 표시.
  // 도면을 수정하고 재시뮬레이션하면 이전 버전의 측정 기록은 자동으로 숨겨진다.
  const sessions = useMemo(() => {
    if (!currentVersion?.created_at) return allSessions;
    return allSessions.filter((s) => s.created_at >= currentVersion.created_at);
  }, [allSessions, currentVersion?.created_at]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const activeSession =
    sessions.find((s) => s.id === selectedSessionId) ?? sessions[0] ?? null;
  const pointsQuery = useMeasurementPoints(activeSession?.id ?? null);
  const points = pointsQuery.data?.items ?? EMPTY_MEASUREMENT_POINTS;

  const canvasPoints = useMemo(() => apiPointsToCanvas(points), [points]);
  // 캔버스 dbm color mode 에서 점 색 계산용 — id → 실측 RSSI 매핑.
  const pointRssiByOrder = useMemo(() => {
    const map = new Map<string, number>();
    for (const p of points) {
      if (p.rssi_dbm != null) map.set(p.id, p.rssi_dbm);
    }
    return map;
  }, [points]);

  // 가장 최근 succeeded RF Run → AP layouts + RF Map metrics.
  const rfRunsQuery = useFloorRfRuns(floorId, { status: 'succeeded', page_size: 5 });
  const latestRfRun = rfRunsQuery.data?.items?.[0] ?? null;
  const latestRfRunId = latestRfRun?.id ?? null;
  const apLayoutsQuery = useApLayouts(latestRfRunId);
  // AP 마커 우선순위: ap_layouts 테이블 > rf_run.request_json.access_points fallback.
  // 시뮬 페이지에서 찍은 AP 는 request_json 에만 들어가고 ap_layouts 엔 자동 동기화 안 돼서,
  // 그것만 보면 측정 캔버스에 AP 가 안 뜸 → 이 fallback 으로 메우기.
  const canvasAps = useMemo(() => {
    const fromLayouts = apLayoutsToCanvas(apLayoutsQuery.data ?? []);
    if (fromLayouts.length > 0) return fromLayouts;
    return apsFromRfRunRequest(latestRfRun?.request_json);
  }, [apLayoutsQuery.data, latestRfRun]);
  const rfMapsQuery = useRfMaps(latestRfRunId, !!latestRfRunId);
  const predictedAvgDbm = useMemo(
    () => extractPredictedAvgDbm(rfMapsQuery.data ?? []),
    [rfMapsQuery.data],
  );
  const measuredAvgDbm = useMemo(() => computeMeasuredAvg(points), [points]);

  // §10.5 발견된 AP 목록.
  const detectedApsQuery = useDetectedAps(activeSession?.id ?? null);
  const detectedAps = detectedApsQuery.data ?? [];

  // #81 RSSI 맵 추정 — 탭별로 다른 method 호출 (의미 분리):
  //   '실측 히트맵' (heatmap mode) → gp_only: 측정값만 GP 보간. sim 안 섞임.
  //   '예측·실측 통합' (both mode)  → residual_kriging: sim prior + residual GP.
  // 같은 sessionId 라도 method 다르면 cache 분리 → 탭 전환시 재요청 없이 즉시 표시.
  const coverageGpOnlyQuery = useEstimatedCoverage(activeSession?.id ?? null, { method: 'gp_only' });
  const coverageResidualQuery = useEstimatedCoverage(activeSession?.id ?? null, { method: 'residual_kriging' });

  const [mode, setMode] = useState<MeasurementViewMode>('route');

  const activeCoverage = useMemo(() => {
    // mode 에 맞는 데이터 우선, 없으면 다른 method 데이터로 일시 fallback —
    // 탭 전환 시 한쪽 query 가 아직 loading 이어도 heatmap 깜빡임 없이 유지.
    if (mode === 'both') {
      return coverageResidualQuery.data ?? coverageGpOnlyQuery.data;
    }
    return coverageGpOnlyQuery.data ?? coverageResidualQuery.data;
  }, [mode, coverageGpOnlyQuery.data, coverageResidualQuery.data]);
  const estimatedHeatmap = useMemo(() => {
    // route 모드는 heatmap 안 그림 → null. heatmap/both 는 mode 에 맞는 데이터 사용.
    if (!activeCoverage) return null;
    return { url: activeCoverage.heatmap_url, bounds: activeCoverage.bounds };
  }, [activeCoverage]);
  // 점 색 dbm 모드일 때 사용할 범위 — heatmap 의 rssi_range 와 동일하게 맞춰서 시각 통일.
  const pointColorRange = useMemo(
    () =>
      activeCoverage
        ? { min: activeCoverage.rssi_range.min, max: activeCoverage.rssi_range.max }
        : undefined,
    [activeCoverage],
  );
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobilePurpose, setMobilePurpose] = useState<'calibration' | 'reference'>('calibration');
  const [actionGuideOpen, setActionGuideOpen] = useState(false);

  const hasVersion = versions.length > 0;
  const hasMeasurement = points.length > 0;
  const isLoadingMeasurement =
    sessionsQuery.isFetching || (!!activeSession && pointsQuery.isFetching);

  const prevMobileOpen = useRef(false);
  useEffect(() => {
    if (prevMobileOpen.current && !mobileOpen && floorId) {
      void queryClient.invalidateQueries({ queryKey: ['measurement-sessions', floorId] });
    }
    prevMobileOpen.current = mobileOpen;
  }, [mobileOpen, floorId, queryClient]);

  // §11 캘리브레이션 — 현재 측정 세션 + 최근 RF Run + 현재 버전을 입력으로 사용.
  // 측정 페이지에 둠: 진단 카드에서 차이를 발견한 직후 보정 가능.
  const evaluateCalibration = useEvaluateCalibrationRun();
  const [calibrationEvaluation, setCalibrationEvaluation] =
    useState<CalibrationEvaluationResponse | null>(null);
  // Affine RSSI transfer + residual IDW는 적은 측정점으로도 계산은 가능하지만,
  // 화면에서 바로 신뢰 가능한 보정맵처럼 보이지 않도록 프론트에서는 더 보수적으로 8점부터 허용한다.
  // 백엔드 평가는 기존 데이터 호환을 위해 최소 5점 guard를 별도로 유지한다.
  const MIN_MEASUREMENTS_FOR_CALIBRATION = 8;
  const hasEnoughMeasurements = points.length >= MIN_MEASUREMENTS_FOR_CALIBRATION;
  const radioMapBounds = useMemo(
    () => extractRadioMapBounds(latestRfRun?.metrics_json),
    [latestRfRun?.metrics_json],
  );
  const pointsInsideSim = useMemo(
    () => countPointsInsideBounds(points, radioMapBounds),
    [points, radioMapBounds],
  );
  const hasEnoughPointsInSim = pointsInsideSim >= MIN_MEASUREMENTS_FOR_CALIBRATION;
  const canCalibrate =
    !!activeSession?.id &&
    !!latestRfRunId &&
    !!currentVersion?.id &&
    hasEnoughMeasurements &&
    hasEnoughPointsInSim;
  const evaluationSessionIds = useMemo(() => {
    const ids = new Set<string>();
    for (const session of sessions) {
      if (
        session.measurement_purpose === 'calibration' ||
        session.measurement_purpose === 'reference' ||
        session.measurement_purpose === 'validation'
      ) {
        ids.add(session.id);
      }
    }
    if (activeSession?.id) ids.add(activeSession.id);
    return [...ids];
  }, [activeSession, sessions]);
  const calibrationGate: CalibrationGate = !hasMeasurement
    ? 'no_measurement'
    : !hasEnoughMeasurements
      ? 'insufficient_points'
      : !latestRfRunId
        ? 'no_simulation'
        : !hasEnoughPointsInSim
          ? 'outside_sim_area'
          : 'ready';
  const calibrationDisabledReason = !hasMeasurement
    ? null
    : !hasEnoughMeasurements
      ? `보정을 위해 측정점 ${MIN_MEASUREMENTS_FOR_CALIBRATION}개 이상이 필요합니다 (현재 ${points.length}개). 도면 곳곳을 더 측정해주세요.`
      : !latestRfRunId
        ? null
        : !hasEnoughPointsInSim
          ? `측정점 ${points.length}개 중 ${pointsInsideSim}개만 시뮬레이션 영역 안에 있습니다. 모바일 앱에서 도면 벽 안쪽의 시작 위치를 지정하고 건물 안을 따라 다시 측정해주세요.`
          : null;
  const handleCalibrate = () => {
    if (!canCalibrate || !activeSession || !latestRfRunId || !currentVersion) return;
    evaluateCalibration.mutate(
      {
        floor_id: activeSession.floor_id,
        rf_run_id: latestRfRunId,
        scene_version_id: currentVersion.id,
        measurement_session_ids: evaluationSessionIds.length > 0 ? evaluationSessionIds : [activeSession.id],
        method: 'affine_rssi_transfer',
        split: { strategy: 'purpose_or_random', holdout_ratio: 0.3, seed: 42 },
        visualization: {
          include_reference_map: true,
          reference_map_method: 'idw',
          rssi_min_dbm: -90,
          rssi_max_dbm: -30,
        },
      },
      {
        onSuccess: (result) => {
          setCalibrationEvaluation(result);
        },
      },
    );
  };

  const lastAutoCalibrationKey = useRef<string | null>(null);
  useEffect(() => {
    if (mode !== 'both') return;
    if (!canCalibrate || !activeSession || !latestRfRunId || !currentVersion) return;
    const sessionIds = evaluationSessionIds.length > 0 ? evaluationSessionIds : [activeSession.id];
    const key = [
      activeSession.floor_id,
      currentVersion.id,
      latestRfRunId,
      sessionIds.join(','),
      points.length,
    ].join('|');
    if (lastAutoCalibrationKey.current === key) return;
    lastAutoCalibrationKey.current = key;
    evaluateCalibration.mutate(
      {
        floor_id: activeSession.floor_id,
        rf_run_id: latestRfRunId,
        scene_version_id: currentVersion.id,
        measurement_session_ids: sessionIds,
        method: 'affine_rssi_transfer',
        split: { strategy: 'purpose_or_random', holdout_ratio: 0.3, seed: 42 },
        visualization: {
          include_reference_map: true,
          reference_map_method: 'idw',
          rssi_min_dbm: -90,
          rssi_max_dbm: -30,
        },
      },
      {
        onSuccess: (result) => {
          setCalibrationEvaluation(result);
        },
      },
    );
  }, [
    mode,
    canCalibrate,
    activeSession,
    latestRfRunId,
    currentVersion,
    evaluationSessionIds,
    points.length,
    evaluateCalibration,
  ]);

  const calibratedMainHeatmap = useMemo(() => {
    const map = calibrationEvaluation?.maps.calibrated;
    if (!map) return null;
    return {
      valuesDbm: map.values_dbm,
      bounds: map.bounds_m,
      rssiRange: {
        min: calibrationEvaluation.color_scale.min_dbm,
        max: calibrationEvaluation.color_scale.max_dbm,
      },
    };
  }, [calibrationEvaluation]);

  const displayedHeatmap =
    mode === 'both' && calibratedMainHeatmap ? calibratedMainHeatmap : estimatedHeatmap;
  const displayedRange =
    mode === 'both' && calibratedMainHeatmap
      ? calibratedMainHeatmap.rssiRange
      : pointColorRange;


  return (
    <div className="relative flex h-full flex-col gap-5 p-6">
      <PageHeader
        sessions={sessions}
        activeSession={activeSession}
        floorId={floorId ?? null}
        projectId={projectIdForFloors}
        onSelectSession={(id) => setSelectedSessionId(id)}
        onStartMeasurement={() => {
          setMobilePurpose('calibration');
          setMobileOpen(true);
        }}
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
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1fr_350px]">
          <section className="flex min-h-0 flex-col gap-3">
            <TabBar mode={mode} onChange={setMode} />
            <div className="relative min-h-0 flex-1 overflow-hidden rounded-2xl border bg-background shadow-sm">
              {/* route 모드 범례/측정 방식 뱃지는 캔버스 위에 올려 도면 크기를 시뮬레이션과 맞춘다. */}
              <div className="pointer-events-none absolute left-3 top-3 z-10 flex flex-wrap items-center gap-2">
                {mode === 'route' && <Legend colorMode="quality" range={pointColorRange} />}
                {mode === 'both' && calibratedMainHeatmap ? (
                  <span className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/5 px-2 py-1 text-xs font-medium text-primary">
                    RSSI transfer 보정맵
                  </span>
                ) : mode !== 'route' && activeCoverage?.method && (
                  <MethodBadge
                    method={activeCoverage.method}
                    expected={mode === 'both' ? 'residual_kriging' : 'gp_only'}
                  />
                )}
              </div>
              <div className="relative h-full min-h-112">
                <MeasurementCanvas
                  sceneVersion={sceneVersion}
                  backgroundImageUrl={backgroundImageUrl}
                  points={canvasPoints}
                  pointRssiByOrder={pointRssiByOrder}
                  pointColorRange={displayedRange}
                  aps={canvasAps}
                  mode={mode}
                  estimatedHeatmap={displayedHeatmap}
                />
                {!hasMeasurement && <CanvasEmptyOverlay loading={isLoadingMeasurement} />}
                {/* dbm 모드 colorbar — 도면 좌상단. gradient + tick 값 수직 정렬로 "이 색=이 dBm" 직관. */}
                {mode !== 'route' && displayedRange && (
                  <div className="pointer-events-none absolute left-3 top-3 z-10 w-70">
                    <DbmColorBar
                      vmin={displayedRange.min}
                      vmax={displayedRange.max}
                      label="실측 RSSI"
                    />
                  </div>
                )}
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
              run={null}
              isPolling={false}
              isStarting={evaluateCalibration.isPending}
              canCalibrate={canCalibrate}
              disabledReason={calibrationDisabledReason}
              calibrationGate={calibrationGate}
              spaceType={spaceType}
              showSpaceTypeField={false}
              onCalibrate={handleCalibrate}
              showCalibrateButton
              showMeasurementLink={false}
              onAddReferenceMeasurement={() => {
                setMobilePurpose('reference');
                setMobileOpen(true);
              }}
              parameterUpdates={[]}
              evaluation={calibrationEvaluation}
              backgroundImageUrl={backgroundImageUrl}
            />
            <CauseAnalysisCard
              hasData={hasMeasurement}
              onOpenGuide={() => setActionGuideOpen(true)}
            />
            {detectedAps.length > 0 && <DetectedApsCard aps={detectedAps} />}
          </aside>
        </div>
      )}

      <MobileConnectModal
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        recommendedPurpose={mobilePurpose}
      />
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

/** rf_run.request_json.access_points → 캔버스 AP 마커.
 *  시뮬 페이지가 찍은 AP 는 ap_layouts 에 자동 동기화 안 되고 이쪽에만 있음 → fallback.
 *  request_json 은 unknown 이라 방어적으로 파싱.
 */
function apsFromRfRunRequest(requestJson: Record<string, unknown> | undefined): PlacedApSimple[] {
  if (!requestJson) return [];
  const raw = (requestJson as { access_points?: unknown }).access_points;
  if (!Array.isArray(raw)) return [];
  const out: PlacedApSimple[] = [];
  raw.forEach((entry, i) => {
    if (!entry || typeof entry !== 'object') return;
    const r = entry as Record<string, unknown>;
    const x = Number(r['x_m'] ?? r['x']);
    const y = Number(r['y_m'] ?? r['y']);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const id = typeof r['id'] === 'string' ? r['id'] : `ap${i + 1}`;
    out.push({ id, x_m: x, y_m: y, label: id.toUpperCase() });
  });
  return out;
}

/** RfRun.metrics_json.radio_map.bounds_m 추출. */
function extractRadioMapBounds(
  metrics: Record<string, unknown> | undefined,
): { min_x: number; min_y: number; max_x: number; max_y: number } | null {
  const radioMap = metrics?.['radio_map'];
  if (!radioMap || typeof radioMap !== 'object') return null;
  const bounds = (radioMap as Record<string, unknown>)['bounds_m'];
  if (!bounds || typeof bounds !== 'object') return null;
  const b = bounds as Record<string, unknown>;
  const min_x = Number(b['min_x']);
  const min_y = Number(b['min_y']);
  const max_x = Number(b['max_x']);
  const max_y = Number(b['max_y']);
  if (![min_x, min_y, max_x, max_y].every(Number.isFinite)) return null;
  if (max_x <= min_x || max_y <= min_y) return null;
  return { min_x, min_y, max_x, max_y };
}

function countPointsInsideBounds(
  points: ApiPoint[],
  bounds: { min_x: number; min_y: number; max_x: number; max_y: number } | null,
): number {
  if (!bounds) return points.length;
  return points.filter((p) => {
    const { x, y } = p.floor_position;
    return (
      x >= bounds.min_x &&
      x <= bounds.max_x &&
      y >= bounds.min_y &&
      y <= bounds.max_y
    );
  }).length;
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
  floorId,
  projectId,
  onSelectSession,
  onStartMeasurement,
}: {
  sessions: MeasurementSession[];
  activeSession: MeasurementSession | null;
  floorId: string | null;
  projectId: string | null;
  onSelectSession: (id: string) => void;
  onStartMeasurement: () => void;
}) {
  const hasSessions = sessions.length > 0;
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">실측 및 진단</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          모바일 기기로 측정한 실제 와이파이 품질 데이터와 시뮬레이션을 통합하여 분석합니다.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <FloorSpaceTypeSelector floorId={floorId} projectId={projectId} showLabel={false} />
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
          className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-blue-500/20 hover:bg-blue-600"
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

/** dbm 모드일 땐 jet 그라데이션 + 양 끝/중간 dBm 표시. quality 모드면 기존 3-tier. */
function Legend({
  colorMode,
  range,
}: {
  colorMode: 'quality' | 'dbm';
  range?: { min: number; max: number };
}) {
  if (colorMode === 'dbm') {
    const min = range?.min ?? -90;
    const max = range?.max ?? -30;
    const mid = (min + max) / 2;
    return (
      <div className="inline-flex w-fit items-center gap-2 rounded-md border bg-background px-3 py-1.5 text-[11px] text-muted-foreground shadow-sm">
        <span className="font-semibold text-foreground">실측 RSSI</span>
        <div
          className="h-2 w-32 rounded-sm border border-border/60"
          style={{ backgroundImage: RSSI_HEATMAP_GRADIENT_CSS }}
        />
        <span className="font-mono tabular-nums text-[10px] text-foreground/70">
          {min.toFixed(0)} · {mid.toFixed(0)} · {max.toFixed(0)} dBm
        </span>
      </div>
    );
  }
  return (
    <div className="inline-flex w-fit items-center gap-3 rounded-md border bg-background px-3 py-1.5 text-[11px] text-muted-foreground shadow-sm">
      <span className="font-semibold text-foreground">실측 포인트 범례</span>
      <LegendDot color="oklch(0.72 0.18 145)" label="양호" />
      <LegendDot color="oklch(0.78 0.15 85)" label="주의" />
      <LegendDot color="oklch(0.62 0.22 25)" label="불량" />
    </div>
  );
}

/** "어떤 추정 방법으로 그려진 heatmap 인지" 사용자에게 명시.
 *  expected ≠ actual 이면 amber 색 + "기대값으로 fallback" 안내 (예: sim 없어서 gp_only 로 떨어진 경우).
 */
function MethodBadge({
  method,
  expected,
}: {
  method: string;
  expected: 'gp_only' | 'residual_kriging';
}) {
  const matched = method === expected;
  const label = method === 'residual_kriging' ? '🔄 시뮬 보정 적용' : '📍 측정값만';
  const tone = matched
    ? 'border-primary/30 bg-primary/5 text-primary'
    : 'border-amber-300 bg-amber-50 text-amber-900';
  const hint = matched
    ? ''
    : ' (시뮬 grid 없음 → 측정값만 사용. 시뮬을 한 번 다시 돌리면 더 정확)';
  return (
    <span
      className={
        'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium ' +
        tone
      }
      title={hint || undefined}
    >
      {label}
      {!matched && <span className="font-normal opacity-80">{hint}</span>}
    </span>
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
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-6 pb-20">
      <div
        className={cn(
          'pointer-events-auto w-full max-w-md -translate-y-6 animate-panel-rise',
          'rounded-2xl border border-sky-200/90 bg-sky-50/95 px-6 py-5 shadow-md backdrop-blur-sm',
        )}
      >
        <div className="flex items-start gap-4">
          <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-600">
            {loading ? (
              <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            ) : (
              <MapPin className="h-5 w-5" aria-hidden />
            )}
          </span>
          <div className="min-w-0 space-y-4 text-left">
            <div className="space-y-2">
              <p className="text-base font-semibold leading-relaxed text-sky-950">
                {loading ? '측정 데이터를 불러오는 중' : '아직 측정 데이터가 없어요'}
              </p>
              <p className="text-xs leading-relaxed text-sky-900/75">
                {loading
                  ? '잠시만 기다려주세요.'
                  : '모바일로 도면 위를 걸으며 측정하면 결과가 이곳에 표시됩니다.'}
              </p>
            </div>
            {!loading && (
              <ol className="space-y-2.5 text-xs leading-relaxed text-sky-900/80">
                <li className="flex items-center gap-2.5">
                  <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[10px] font-bold text-sky-700 ring-1 ring-sky-200">
                    1
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <Smartphone className="h-3.5 w-3.5 shrink-0 opacity-70" aria-hidden />
                    헤더에서 모바일 앱 연결
                  </span>
                </li>
                <li className="flex items-center gap-2.5">
                  <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[10px] font-bold text-sky-700 ring-1 ring-sky-200">
                    2
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <Activity className="h-3.5 w-3.5 shrink-0 opacity-70" aria-hidden />
                    상단에서 새로운 측정 시작
                  </span>
                </li>
              </ol>
            )}
          </div>
        </div>
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
          측정 데이터가 없습니다. 모바일 앱으로 측정을 진행하면 가장
          <br />
          신호가 약한 지점의 진단이 자동으로 표시됩니다.
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
