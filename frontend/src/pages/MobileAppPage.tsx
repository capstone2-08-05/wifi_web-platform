import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Ban, CheckCircle2, Info, Loader2, MapPin, MousePointer2, Sparkles, Target } from 'lucide-react';
import type { HttpError } from '@/api/client';
import { calibrationRunApi } from '@/api/calibration-run';
import { useAppStore } from '@/stores/app-store';
import {
  useApRecommendationStore,
  type ApRecommendationSession,
} from '@/stores/ap-recommendation-store';
import { useFloorVersions, useSceneVersion } from '@/hooks/use-scene-version';
import { useFloorRfRuns, useRfMaps, useRfRun } from '@/hooks/use-rf-run';
import { useInferenceMode } from '@/hooks/use-inference-mode';
import { useApLayouts, useCreateApLayout } from '@/hooks/use-ap-layouts';
import { useAssetDownloadUrl } from '@/hooks/use-assets';
import { useLocalFloorplanImage } from '@/hooks/use-local-floorplan-image';
import {
  useApRecommendation,
  useApRecommendationRuns,
  useVerifyApRecommendationCandidate,
} from '@/hooks/use-ap-recommendation';
import { useFloorMeasurementSessions } from '@/hooks/use-measurement-session';
import { versionToDraftShape } from '@/features/editor/version-as-draft';
import { DEFAULT_TX_POWER_DBM } from '@/features/simulation/SimulationCanvas';
import {
  apLayoutsToCanvas,
  apsFromRfRunRequest,
  nextApLayoutName,
} from '@/features/ap-recommendation/ap-canvas-mappers';
import {
  ApRecommendationCanvas,
  type CanvasExistingAp,
} from '@/features/ap-recommendation/ApRecommendationCanvas';
import {
  AP_DEFAULT_Z_M,
  buildApRecommendationPayload,
  normalizeRecommendationRun,
  normalizeRecommendations,
  validRecommendationAreas,
  type ApRecommendationArea,
  type ApRecommendationAreaType,
  type RecommendationMode,
} from '@/features/ap-recommendation/recommendation-utils';
import type {
  ApRecommendationResponse,
  ApRecommendationResult,
  ApRecommendationRun,
} from '@/types/ap-recommendation';
import { cn } from '@/lib/utils';
import type { CalibrationEvaluationResponse } from '@/types/calibration-run';
import type { CombinePolicy, PhysicalAp, RfBackend, RfMap, WifiBand } from '@/types/rf';

type PageStatus = 'idle' | 'areaSelected' | 'loading' | 'success' | 'error';

const MEASUREMENT_VIEW_STORAGE_KEY = 'wifang.measurement-view';
const COVERAGE_THRESHOLD_DBM = -67;

interface StoredMeasurementView {
  sessionId: string | null;
  sceneVersionId: string | null;
  apBssid: string | null;
}

const PROGRESS_STEPS = [
  { id: 1, label: '설치 가능 영역 선택' },
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
    label: '설치 가능 영역',
    hint: '공유기를 실제로 둘 수 있는 후보 영역입니다.',
    className: 'border-blue-200 bg-blue-50 text-blue-700',
    icon: MapPin,
  },
  {
    type: 'priority',
    label: '우선 평가 영역',
    hint: 'Wi-Fi 품질을 중요하게 볼 영역입니다.',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    icon: Target,
  },
  {
    type: 'excluded',
    label: '제외 영역',
    hint: '추천 점수 계산에서 제외할 영역입니다.',
    className: 'border-red-200 bg-red-50 text-red-700',
    icon: Ban,
  },
];

export default function MobileAppPage() {
  const floorId = useAppStore((s) => s.selectedFloorId);
  const { mode: inferenceMode } = useInferenceMode();
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
    const items = (rfRunsQuery.data?.items ?? []).filter(
      (run) => run.run_type !== 'ap_recommendation_verify',
    );
    if (!sceneVersionId) return items[0] ?? null;
    return (
      items.find((r) => r.scene_version_id === sceneVersionId && r.run_type === 'forward') ??
      items.find((r) => r.scene_version_id === sceneVersionId) ??
      items[0] ??
      null
    );
  }, [rfRunsQuery.data, sceneVersionId]);
  const latestRfRunId = latestRfRun?.id ?? null;
  const apLayoutsQuery = useApLayouts(latestRfRunId);

  const existingAps = useMemo(() => {
    const layouts = apLayoutsQuery.data ?? [];
    const fromRfRun = apsFromRfRunRequest(latestRfRun?.request_json as Record<string, unknown> | undefined);
    if (layouts.length > 0) {
      const fromLayouts = apLayoutsToCanvas(layouts);
      // RF run 스냅샷에서 AP UUID로 radio 정보를 보강 (layouts에는 radios 없음)
      const rfRunById = new Map(fromRfRun.map((ap) => [ap.id, ap]));
      return fromLayouts.map((ap) => {
        const rfAp = rfRunById.get(ap.id);
        return rfAp?.radios ? { ...ap, radios: rfAp.radios } : ap;
      });
    }
    return fromRfRun;
  }, [apLayoutsQuery.data, latestRfRun?.request_json]);

  const patchRecommendationScene = useApRecommendationStore((s) => s.patchScene);
  const clearRecommendationScene = useApRecommendationStore((s) => s.clearScene);
  const [selectedAreas, setSelectedAreas] = useState<ApRecommendationArea[]>([]);
  const [activeAreaType, setActiveAreaType] = useState<ApRecommendationAreaType>('candidate');
  const [recommendations, setRecommendations] = useState<ApRecommendationResult[]>([]);
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [savedRank, setSavedRank] = useState<number | null>(null);
  const [nAps, setNAps] = useState(1);
  const [recommendationMode, setRecommendationMode] = useState<RecommendationMode>('add');
  const [replaceTargetApIds, setReplaceTargetApIds] = useState<string[]>([]);
  const [relocateTargetApIds, setRelocateTargetApIds] = useState<string[]>([]);
  const [targetTotalAps, setTargetTotalAps] = useState<number | null>(null);
  const targetBands: WifiBand[] = ['5G'];
  const combinePolicy: CombinePolicy = 'prefer_5g_then_2g';
  const verifyWithSionna = false;
  const physicalAps = useMemo(
    () => existingAps.map((ap) => canvasApToPhysicalAp(ap, targetBands)),
    [existingAps, targetBands],
  );
  const fixedApIds = useMemo(
    () =>
      recommendationMode === 'relocate_selected'
        ? existingAps
            .map((ap) => ap.id)
            .filter((id) => !relocateTargetApIds.includes(id))
        : [],
    [existingAps, relocateTargetApIds, recommendationMode],
  );
  const [verificationRunId, setVerificationRunId] = useState<string | null>(null);
  const [verificationRank, setVerificationRank] = useState<number | null>(null);
  const [calibrationWarning, setCalibrationWarning] = useState<string | null>(null);
  const [recommendationUpdatedAt, setRecommendationUpdatedAt] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [showSimComparison, setShowSimComparison] = useState(false);
  const [simComparisonTab, setSimComparisonTab] = useState<'baseline' | 'verification'>('verification');

  const recommendMutation = useApRecommendation();
  const recommendationRunsQuery = useApRecommendationRuns(sceneVersionId, 10);
  const verifyCandidateMutation = useVerifyApRecommendationCandidate();
  const createLayout = useCreateApLayout();
  const verificationPoll = useRfRun(verificationRunId);
  const verificationMapsQuery = useRfMaps(verificationRunId, verificationPoll.isSucceeded);
  const baselineRunDetail = useRfRun(latestRfRunId);
  const measurementSessionsQuery = useFloorMeasurementSessions(floorId);
  const storedMeasurementView = useMemo(
    () => readStoredMeasurementView(floorId),
    [floorId],
  );
  const comparisonSession = useMemo(() => {
    const sessions = measurementSessionsQuery.data?.items ?? [];
    if (!sceneVersionId) return null;
    const sessionsForScene = sessions.filter((session) => session.scene_version_id === sceneVersionId);
    const storedSession =
      storedMeasurementView?.sessionId
        ? sessionsForScene.find((session) => session.id === storedMeasurementView.sessionId)
        : null;
    return (
      storedSession ??
      sessionsForScene.find((session) => session.status === 'completed') ??
      sessionsForScene.find((session) => session.status === 'in_progress') ??
      sessionsForScene[0] ??
      null
    );
  }, [measurementSessionsQuery.data, sceneVersionId, storedMeasurementView?.sessionId]);
  const comparisonApBssid = storedMeasurementView?.apBssid ?? null;
  const comparisonEvaluationSessionIds = useMemo(() => {
    const sessions = measurementSessionsQuery.data?.items ?? [];
    if (!sceneVersionId) return [];
    const ids = new Set<string>();
    for (const session of sessions) {
      if (session.scene_version_id !== sceneVersionId) continue;
      if (
        session.measurement_purpose === 'calibration' ||
        session.measurement_purpose === 'reference' ||
        session.measurement_purpose === 'validation'
      ) {
        ids.add(session.id);
      }
    }
    if (comparisonSession?.id) ids.add(comparisonSession.id);
    return [...ids];
  }, [comparisonSession?.id, measurementSessionsQuery.data, sceneVersionId]);
  const calibrationComparisonQuery = useQuery({
    queryKey: [
      'ap-recommendation-calibration-comparison',
      floorId,
      sceneVersionId,
      latestRfRunId,
      comparisonEvaluationSessionIds.join(','),
      comparisonApBssid ?? 'all',
    ] as const,
    queryFn: () =>
      calibrationRunApi.evaluate({
        floor_id: floorId as string,
        rf_run_id: latestRfRunId as string,
        scene_version_id: sceneVersionId as string,
        measurement_session_ids: comparisonEvaluationSessionIds,
        ap_bssid: comparisonApBssid,
        method: 'affine_rssi_transfer',
        split: { strategy: 'purpose_or_random', holdout_ratio: 0.3, seed: 42 },
        visualization: {
          include_reference_map: true,
          reference_map_method: 'idw',
          rssi_min_dbm: -90,
          rssi_max_dbm: -30,
        },
      }),
    enabled:
      !!floorId &&
      !!sceneVersionId &&
      !!latestRfRunId &&
      comparisonEvaluationSessionIds.length > 0,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const verificationCalibrationQuery = useQuery({
    queryKey: [
      'ap-recommendation-verification-calibrated-map',
      floorId,
      sceneVersionId,
      verificationRunId,
      verificationRank,
      comparisonEvaluationSessionIds.join(','),
      comparisonApBssid ?? 'all',
    ] as const,
    queryFn: () =>
      calibrationRunApi.evaluate({
        floor_id: floorId as string,
        rf_run_id: verificationRunId as string,
        scene_version_id: sceneVersionId as string,
        measurement_session_ids: comparisonEvaluationSessionIds,
        ap_bssid: comparisonApBssid,
        method: 'affine_rssi_transfer',
        split: { strategy: 'purpose_or_random', holdout_ratio: 0.3, seed: 42 },
        visualization: {
          include_reference_map: true,
          reference_map_method: 'idw',
          rssi_min_dbm: -90,
          rssi_max_dbm: -30,
        },
      }),
    enabled:
      !!floorId &&
      !!sceneVersionId &&
      !!verificationRunId &&
      verificationPoll.isSucceeded &&
      comparisonEvaluationSessionIds.length > 0,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const measurementCoverageMetrics = useMemo(
    () => computeGridCoverageMetrics(calibrationComparisonQuery.data),
    [calibrationComparisonQuery.data],
  );
  const measurementHeatmap = useMemo(() => {
    const evaluation = calibrationComparisonQuery.data;
    const map = evaluation?.maps.calibrated;
    if (!map) return null;
    return {
      valuesDbm: map.values_dbm,
      bounds: map.bounds_m,
      rssiRange: {
        min: evaluation.color_scale.min_dbm,
        max: evaluation.color_scale.max_dbm,
      },
      source: 'measurement' as const,
    };
  }, [calibrationComparisonQuery.data]);
  const baselineHeatmap = useMemo(
    () =>
      extractRadioMapHeatmap(baselineRunDetail.rfRun?.metrics_json) ??
      extractRadioMapHeatmap(latestRfRun?.metrics_json),
    [baselineRunDetail.rfRun?.metrics_json, latestRfRun?.metrics_json],
  );
  const baselineCoverageMetrics = useMemo(
    () => computeGridCoverageMetricsFromValues(baselineHeatmap?.valuesDbm),
    [baselineHeatmap],
  );
  const integratedCoverageMetrics = measurementCoverageMetrics ?? baselineCoverageMetrics;
  const integratedHeatmap = measurementHeatmap ?? baselineHeatmap;
  const verificationCalibratedHeatmap = useMemo(() => {
    const evaluation = verificationCalibrationQuery.data;
    const map = evaluation?.maps.calibrated;
    if (!map) return null;
    return {
      valuesDbm: map.values_dbm,
      bounds: map.bounds_m,
      rssiRange: {
        min: evaluation.color_scale.min_dbm,
        max: evaluation.color_scale.max_dbm,
      },
      source: 'measurement' as const,
    };
  }, [verificationCalibrationQuery.data]);
  const selectedRecommendation = useMemo(
    () => recommendations.find((rec) => rec.rank === selectedRank) ?? recommendations[0] ?? null,
    [recommendations, selectedRank],
  );
  const verificationHeatmap = useMemo(() => {
    const fromRun = extractRadioMapHeatmap(verificationPoll.rfRun?.metrics_json);
    if (fromRun) return fromRun;
    const maps = verificationMapsQuery.data ?? [];
    const map = maps.find((item) => item.map_type === 'heatmap') ?? maps[0] ?? null;
    return extractRfMapHeatmap(map);
  }, [verificationPoll.rfRun?.metrics_json, verificationMapsQuery.data]);
  const verificationCoverageMetrics = useMemo(
    () => computeGridCoverageMetricsFromValues(verificationHeatmap?.valuesDbm),
    [verificationHeatmap],
  );
  const verificationCalibratedCoverageMetrics = useMemo(
    () => computeGridCoverageMetrics(verificationCalibrationQuery.data),
    [verificationCalibrationQuery.data],
  );
  const verificationMatchesSelection =
    selectedRecommendation != null && verificationRank === selectedRecommendation.rank;
  const useComparisonMode = showSimComparison && verificationMatchesSelection;
  const recommendedComparisonHeatmap = verificationCalibratedHeatmap ?? verificationHeatmap;
  const recommendedCoverageForComparison =
    verificationCalibratedCoverageMetrics ??
    verificationCoverageMetrics ??
    extractRunCoverageMetrics(verificationPoll.rfRun?.metrics_json) ??
    recommendationCoverageMetrics(selectedRecommendation);
  const integratedCoverageForComparison =
    integratedCoverageMetrics ??
    extractRunCoverageMetrics(baselineRunDetail.rfRun?.metrics_json) ??
    extractRunCoverageMetrics(latestRfRun?.metrics_json);
  const canvasHeatmapMode: 'prediction' | 'measurement' =
    useComparisonMode && (simComparisonTab === 'baseline' || !!recommendedComparisonHeatmap)
      ? 'measurement'
      : 'prediction';
  const canvasHeatmap = !useComparisonMode
    ? null
    : simComparisonTab === 'baseline'
      ? integratedHeatmap
      : recommendedComparisonHeatmap;

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
      setVerificationRunId(null);
      setVerificationRank(null);
      setRecommendationUpdatedAt(null);
      return;
    }

    const stored = useApRecommendationStore.getState().byScene[sceneVersionId];
    if (!stored) {
      setSelectedAreas([]);
      setRecommendations([]);
      setSelectedRank(null);
      setSavedRank(null);
      setVerificationRunId(null);
      setVerificationRank(null);
      setRecommendationUpdatedAt(null);
      return;
    }

    const storedAreas = validRecommendationAreas(stored.areas);
    const storedRecommendations = stored.recommendations ?? [];
    setSelectedAreas(storedAreas);
    setRecommendations(storedRecommendations);
    setSelectedRank(stored.selectedRank ?? storedRecommendations[0]?.rank ?? null);
    setSavedRank(stored.savedRank);
    setRecommendationUpdatedAt(stored.updatedAt);
  }, [sceneVersionId]);

  useEffect(() => {
    const latestRun = recommendationRunsQuery.data?.items?.[0] ?? null;
    if (!latestRun || latestRun.scene_version_id !== sceneVersionId) return;

    const runAreas = areasFromRecommendationRun(latestRun);
    const runRecommendations = normalizeRecommendationRun(latestRun);
    setSelectedAreas(runAreas);
    setRecommendations(runRecommendations);
    setSelectedRank(runRecommendations[0]?.rank ?? null);
    setSavedRank(null);
    setRecommendationUpdatedAt(latestRun.created_at);
    setPageError(null);
    if (sceneVersionId) {
      patchRecommendationScene(sceneVersionId, {
        sceneVersionId,
        areas: runAreas,
        recommendations: runRecommendations,
        selectedRank: runRecommendations[0]?.rank ?? null,
        savedRank: null,
        updatedAt: latestRun.created_at,
      });
    }
  }, [recommendationRunsQuery.data, sceneVersionId, patchRecommendationScene]);

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
    setVerificationRunId(null);
    setVerificationRank(null);
    if (sceneVersionId && validAreas.length > 0) {
      persistRecommendationSession({
        areas: validAreas,
        recommendations: [],
        selectedRank: null,
        savedRank: null,
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
      setPageError('설치 가능 영역을 먼저 선택해 주세요.');
      return;
    }

    if (modeValidationError) {
      setPageError(modeValidationError);
      return;
    }

    const payload = buildApRecommendationPayload({
      sceneVersionId,
      areas: validAreas,
      existingAps,
      physicalAps,
      txPowerDbm: DEFAULT_TX_POWER_DBM,
      nAps,
      targetBands,
      combinePolicy,
      verifyWithSionna,
      verificationBackend: inferenceMode as RfBackend,
      recommendationMode,
      replaceTargetApIds: recommendationMode === 'replace' ? replaceTargetApIds : undefined,
      fixedApIds: recommendationMode === 'relocate_selected' ? fixedApIds : undefined,
      movableApIds: recommendationMode === 'relocate_selected' ? relocateTargetApIds : undefined,
      relocateTargetApIds: recommendationMode === 'relocate_selected' ? relocateTargetApIds : undefined,
      targetTotalAps:
        recommendationMode === 'relocate_all'
          ? (targetTotalAps ?? Math.max(existingAps.length, 2))
          : undefined,
    });

    if (import.meta.env.DEV) {
      console.debug('[AP Recommendation] request payload:', payload);
    }

    setPageError(null);
    setSavedRank(null);
    setVerificationRunId(null);
    setVerificationRank(null);
    setCalibrationWarning(null);
    setShowSimComparison(false);
    persistRecommendationSession({
      areas: validAreas,
      savedRank: null,
    });
    recommendMutation.mutate(payload, {
      onSuccess: (data) => {
        const normalized = normalizeRecommendations(data);
        setRecommendations(normalized);
        setSelectedRank(normalized[0]?.rank ?? null);
        persistRecommendationSession({
          areas: validAreas,
          recommendations: normalized,
          selectedRank: normalized[0]?.rank ?? null,
          savedRank: null,
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

  const handleSelectRecommendation = async (rec: ApRecommendationResult) => {
    if (!latestRfRunId) {
      setPageError('와이파이 위치를 저장하려면 먼저 시뮬레이션을 실행해 주세요.');
      return;
    }

    setSelectedRank(rec.rank);
    setVerificationRunId(null);
    setVerificationRank(null);
    setShowSimComparison(false);
    setCalibrationWarning(null);
    setPageError(null);
    persistRecommendationSession({ selectedRank: rec.rank });

    if (rec.final_aps && rec.final_aps.length > 0) {
      // relocate_all / relocate_selected: final_aps의 모든 공유기를 한 번에 저장
      const baseLayouts = apLayoutsQuery.data ?? [];
      const fakePrevious: { ap_name: string }[] = [...baseLayouts];
      const entries = rec.final_aps.map((ap) => {
        const apName = ap.name ?? nextApLayoutName(fakePrevious, existingAps);
        fakePrevious.push({ ap_name: apName });
        return { ap, apName };
      });
      try {
        await Promise.all(
          entries.map(({ ap, apName }) =>
            createLayout.mutateAsync({
              rf_run_id: latestRfRunId,
              ap_name: apName,
              point_geom: { type: 'Point', coordinates: [ap.x, ap.y] },
              z_m: ap.z ?? AP_DEFAULT_Z_M,
              power_dbm: DEFAULT_TX_POWER_DBM,
            }),
          ),
        );
        setSavedRank(rec.rank);
        persistRecommendationSession({ selectedRank: rec.rank, savedRank: rec.rank });
      } catch (err) {
        const e = err as HttpError | null;
        setPageError(e?.message ?? '와이파이 위치 저장에 실패했습니다.');
        setSelectedRank(null);
        persistRecommendationSession({ selectedRank: null });
      }
      return;
    }

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
    setVerificationRunId(null);
    setVerificationRank(null);
    setShowSimComparison(false);
    setCalibrationWarning(null);
    setPageError(null);
    persistRecommendationSession({ selectedRank: rec.rank });
  };

  const handleVerifySelectedCandidate = () => {
    const runId = recommendMutation.data?.run_id;
    if (!runId || !selectedRecommendation) return;

    setPageError(null);
    setCalibrationWarning(null);
    verifyCandidateMutation.mutate(
      { runId, body: { candidate_rank: selectedRecommendation.rank } },
      {
        onSuccess: (data) => {
          setVerificationRunId(data.rf_run_id);
          setVerificationRank(data.candidate_rank);
          setCalibrationWarning(data.calibration.warning ?? null);
          setShowSimComparison(true);
          setSimComparisonTab('verification');
        },
        onError: (err) => {
          const e = err as HttpError | null;
          setPageError(e?.message ?? '비교 정보를 불러오는데 실패했습니다.');
        },
      },
    );
  };

  const modeValidationError = getRecommendationModeError({
    mode: recommendationMode,
    existingApIds: existingAps.map((ap) => ap.id),
    additionalApCount: nAps,
    replaceTargetApIds,
    relocateTargetApIds,
    targetTotalAps,
    targetBands,
  });

  const canRecommend =
    !!sceneVersionId &&
    validRecommendationAreas(selectedAreas).some((area) => area.type === 'candidate') &&
    !modeValidationError &&
    !recommendMutation.isPending;

  const sceneLoading =
    versionsQuery.isLoading ||
    versionDetailQuery.isLoading ||
    (floorId != null && !sceneVersionId && !versionsQuery.isError);

  const hasCandidateArea = validRecommendationAreas(selectedAreas).some((a) => a.type === 'candidate');
  const statusHint = hasCandidateArea
    ? getStatusHint(pageStatus, pageError, savedRank)
    : getStatusHint('idle', null, null);

  return (
    <div className="flex h-full flex-col overflow-auto bg-[#F8FAFC]">
      {/* 본문 — lg: 캔버스(좌) + 추천 패널(우), md↓ 단일 컬럼 */}
      <div className="grid min-h-full grid-cols-1 gap-4 px-6 pb-8 pt-4 lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-5 lg:px-8 lg:pt-6">
        {/* 좌측: 제목 + 안내 + 캔버스 + 진행 단계 */}
        <div className="flex min-h-0 flex-col gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">공유기 위치 추천</h1>
            <p className="mt-1 text-sm text-muted-foreground">설치 가능 영역과 우선 평가 영역을 표시하면 신호가 잘 닿는 공유기 위치를 추천합니다.</p>
          </div>
          {sceneVersionId && statusHint && pageStatus !== 'loading' && (
            <div
              key={pageStatus}
              style={{ animation: 'hint-enter 1.5s cubic-bezier(0.16, 1, 0.3, 1) both' }}
              className={cn(
                'flex items-start gap-3 rounded-lg border px-4 py-3',
                statusHint.variant === 'success' && 'border-emerald-200 bg-emerald-50/60',
                statusHint.variant === 'error' && 'border-red-200 bg-red-50/60',
                statusHint.variant === 'info' && 'border-blue-200 bg-blue-50/50',
              )}
            >
              <div className="mt-0.5 shrink-0">
                {statusHint.variant === 'info' && pageStatus === 'idle'
                  ? <MousePointer2 className="h-4 w-4 text-blue-500" />
                  : statusHint.variant === 'success'
                    ? <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    : statusHint.variant === 'error'
                      ? <Ban className="h-4 w-4 text-red-500" />
                      : <Info className="h-4 w-4 text-blue-500" />
                }
              </div>
              <div className="min-w-0">
                <p className={cn(
                  'text-xs font-semibold',
                  statusHint.variant === 'success' && 'text-emerald-700',
                  statusHint.variant === 'error' && 'text-red-700',
                  statusHint.variant === 'info' && 'text-blue-700',
                )}>
                  {statusHint.title}
                </p>
                {statusHint.desc && (
                  <p className="mt-0.5 text-xs text-muted-foreground">{statusHint.desc}</p>
                )}
              </div>
            </div>
          )}

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
              <>
                {useComparisonMode && (
                  <div className="absolute left-1/2 top-2 z-10 flex -translate-x-1/2 overflow-hidden rounded-lg border border-[#D8E3F0] bg-white shadow-sm">
                    <button
                      type="button"
                      onClick={() => setSimComparisonTab('baseline')}
                      className={cn(
                        'px-4 py-1.5 text-xs font-semibold transition-colors',
                        simComparisonTab === 'baseline'
                          ? 'bg-slate-700 text-white'
                          : 'text-slate-500 hover:bg-muted/60',
                      )}
                    >
                      현재 위치
                    </button>
                    <button
                      type="button"
                      onClick={() => setSimComparisonTab('verification')}
                      className={cn(
                        'px-4 py-1.5 text-xs font-semibold transition-colors',
                        simComparisonTab === 'verification'
                          ? 'bg-blue-600 text-white'
                          : 'text-slate-500 hover:bg-muted/60',
                      )}
                    >
                      추천 위치
                    </button>
                  </div>
                )}
                <ApRecommendationCanvas
                  sceneVersion={versionDetail}
                  backgroundImageUrl={backgroundImageUrl}
                  existingAps={existingAps}
                  selectedAreas={selectedAreas}
                  activeAreaType={activeAreaType}
                  onAreasChange={handleAreasChange}
                  recommendations={savedRank != null ? recommendations.filter((r) => r.rank === savedRank) : recommendations}
                  recommendationMode={recommendationMode}
                  selectedReplacementIds={replaceTargetApIds}
                  movableApIds={relocateTargetApIds}
                  selectedRecommendationRank={selectedRank}
                  heatmapMode={canvasHeatmapMode}
                  measurementHeatmap={canvasHeatmap}
                  disabled={recommendMutation.isPending || createLayout.isPending}
                />
              </>
            )}
          </div>

          {/* 진행 단계 카드 — 캔버스 아래 */}
          <div
            className={cn(
              'shrink-0 rounded-2xl bg-white px-6 py-5 shadow-sm mb-6',
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
          <div className="h-1.5 shrink-0" />
        </div>

        {/* 우측: 컨트롤 + 추천 결과 패널 */}
        <div className="flex flex-col gap-4">
          <div className={cn('flex shrink-0 flex-col items-stretch gap-3 rounded-2xl border bg-white px-5 py-5 shadow-sm', CARD_BORDER)}>
            <div className="flex items-center gap-2">
              <span className="text-[12px] text-slate-500">추천 방식</span>
              <div className="inline-flex items-center rounded-lg bg-slate-100 p-0.5">
                {(
                  [
                    { value: 'add', label: '공유기 추가' },
                    { value: 'replace', label: '공유기 교체' },
                    { value: 'relocate_all', label: '전체 재배치' },
                    { value: 'relocate_selected', label: '선택 재배치' },
                  ] as const
                ).map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setRecommendationMode(value)}
                    className={cn(
                      'inline-flex h-6 items-center rounded-md px-2 text-[11px] transition-colors',
                      recommendationMode === value
                        ? 'bg-white font-semibold text-blue-700 shadow-sm'
                        : 'text-slate-500 hover:text-slate-800',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <RecommendationAdvancedControls />
            {recommendationMode === 'replace' && (
              <div className="flex items-center gap-2">
                <span className="text-[12px] text-slate-500">교체할 공유기</span>
                <select
                  multiple
                  value={replaceTargetApIds}
                  onChange={(e) =>
                    setReplaceTargetApIds(
                      Array.from(e.target.selectedOptions, (o) => o.value),
                    )
                  }
                  className="h-20 min-w-[120px] rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-800 focus:border-blue-300 focus:outline-none"
                >
                  {existingAps.map((ap) => (
                    <option key={ap.id} value={ap.id}>{ap.id}</option>
                  ))}
                </select>
              </div>
            )}
            {recommendationMode === 'relocate_selected' && (
              <div className="flex items-center gap-2">
                <span className="text-[12px] text-slate-500">재배치할 공유기</span>
                <select
                  multiple
                  value={relocateTargetApIds}
                  onChange={(e) =>
                    setRelocateTargetApIds(
                      Array.from(e.target.selectedOptions, (o) => o.value),
                    )
                  }
                  className="h-20 min-w-[120px] rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-800 focus:border-blue-300 focus:outline-none"
                >
                  {existingAps.map((ap) => (
                    <option key={ap.id} value={ap.id}>{ap.id}</option>
                  ))}
                </select>
              </div>
            )}
            {recommendationMode === 'relocate_all' && (
              <div className="flex items-center gap-2">
                <span className="text-[12px] text-slate-500">최종 공유기 수</span>
                <div className="flex gap-1">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setTargetTotalAps(n)}
                      className={cn(
                        'h-7 w-7 rounded-md text-[12px] font-semibold transition-colors',
                        (targetTotalAps ?? existingAps.length) === n
                          ? 'bg-blue-600 text-white'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
                      )}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {(recommendationMode === 'add' || recommendationMode === 'replace') && (
              <div className="flex items-center gap-2">
                <span className="text-[12px] text-slate-500">설치할 공유기 수</span>
                <div className="flex gap-1">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setNAps(n)}
                      className={cn(
                        'h-7 w-7 rounded-md text-[12px] font-semibold transition-colors',
                        nAps === n
                          ? 'bg-blue-600 text-white'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
                      )}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <button
              type="button"
              onClick={handleRecommend}
              disabled={!canRecommend}
              className={cn(
                'inline-flex w-full items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold shadow-sm transition-colors',
                canRecommend
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'cursor-not-allowed bg-muted text-muted-foreground',
              )}
            >
              {recommendMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  좋은 위치 계산 중…
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  공유기 위치 찾기
                </>
              )}
            </button>
            {!latestRfRunId && sceneVersionId && (
              <p className="text-[11px] text-amber-600">
                공유기 위치 저장은 시뮬레이션 실행 후 가능합니다.
              </p>
            )}
            {modeValidationError && !recommendMutation.isPending && (
              <p className="text-[11px] text-amber-600">{modeValidationError}</p>
            )}
            {sceneVersionId && !canRecommend && !recommendMutation.isPending && (
              <p className="text-[11px] text-muted-foreground">
                공유기를 둘 수 있는 영역을 먼저 지정하면 추천을 실행할 수 있습니다.
              </p>
            )}
          </div>
          <aside
            className={cn(
              'flex h-[880px] flex-col overflow-hidden rounded-2xl bg-white shadow-sm',
              CARD_BORDER,
            'border',
          )}
        >
          <div className="border-b border-[#E5EAF2] px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-base font-bold text-foreground">추천 위치</h2>
            </div>
            {recommendations.length > 0 && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                추천 후보를 클릭하면 해당 위치만 지도에 표시됩니다.
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
              <div style={{ animation: 'hint-enter 1.5s cubic-bezier(0.16, 1, 0.3, 1) both' }} className="flex h-full min-h-[200px] flex-col items-center justify-center gap-4 px-6 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-50">
                  <Sparkles className="h-5 w-5 text-blue-500" />
                </div>
                <div className="space-y-1.5">
                  <p className="text-sm font-semibold text-slate-800">
                    {pageStatus === 'loading'
                      ? '최적 위치를 계산하고 있습니다…'
                      : '추천 결과가 여기에 표시됩니다'}
                  </p>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {pageStatus === 'loading'
                      ? '잠시만 기다려 주세요.'
                      : <>도면에서 설치 가능 영역을 지정한 뒤,<br />상단의 '추천 위치 찾기'를 실행해 주세요.</>}
                  </p>
                </div>
                {pageStatus !== 'loading' && (
                  <div className="rounded-lg border border-blue-100 bg-blue-50/60 px-3 py-2">
                    <p className="text-[11px] text-blue-600">
                      설치 가능 영역을 먼저 도면에 지정해 주세요
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <RecommendationSummaryCard
                  response={recommendMutation.data ?? null}
                  selectedRecommendation={selectedRecommendation}
                />
                <CoverageComparisonCard
                  recommendation={selectedRecommendation}
                  coverage={integratedCoverageMetrics}
                  usingFallback={!measurementCoverageMetrics && !!baselineCoverageMetrics}
                  loading={calibrationComparisonQuery.isLoading}
                />
                <SionnaVerificationCard
                  recommendation={selectedRecommendation}
                  integratedCoverage={integratedCoverageMetrics}
                  sionnaCoverage={verificationMatchesSelection ? verificationCoverageMetrics : null}
                  calibratedSionnaCoverage={
                    verificationMatchesSelection ? verificationCalibratedCoverageMetrics : null
                  }
                  runStatus={verificationMatchesSelection ? verificationPoll.rfRun?.status ?? null : null}
                  loadingIntegrated={
                    calibrationComparisonQuery.isLoading || verificationCalibrationQuery.isLoading
                  }
                  verifying={verifyCandidateMutation.isPending}
                  polling={verificationMatchesSelection && verificationPoll.isPolling}
                  canCompare={verificationMatchesSelection}
                  verifyDisabled={!recommendMutation.data?.run_id || !selectedRecommendation}
                  calibrationWarning={verificationMatchesSelection ? calibrationWarning : null}
                  showComparison={showSimComparison}
                  onVerify={handleVerifySelectedCandidate}
                  onCompare={() => {
                    setShowSimComparison((v) => !v);
                    setSimComparisonTab('verification');
                  }}
                />
                {useComparisonMode && (
                  <SimComparisonCard
                    integratedCoverage={integratedCoverageForComparison}
                    recommendedCoverage={recommendedCoverageForComparison}
                    hasIntegratedHeatmap={!!integratedHeatmap}
                    hasRecommendedHeatmap={
                      !!recommendedComparisonHeatmap ||
                      (selectedRecommendation?.prediction_points?.length ?? 0) > 0
                    }
                    recommendedIsEstimate={!recommendedComparisonHeatmap}
                    simComparisonTab={simComparisonTab}
                    onTabChange={setSimComparisonTab}
                  />
                )}
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
    </div>
  );
}

function getStatusHint(
  pageStatus: PageStatus,
  pageError: string | null,
  savedRank: number | null,
): { title: string; desc?: string; variant: 'info' | 'success' | 'error' } | null {
  switch (pageStatus) {
    case 'idle':
      return {
        title: '설치 가능 영역을 먼저 지정해 주세요.',
        desc: '도면 위에서 공유기를 설치할 수 있는 범위를 드래그해 선택하세요.',
        variant: 'info',
      };
    case 'areaSelected':
      return {
        title: '영역이 지정되었습니다.',
        desc: '더 정확한 추천이 필요하다면 우선 평가 영역이나 제외 영역도 함께 설정할 수 있습니다.',
        variant: 'info',
      };
    case 'success':
      return {
        title: savedRank != null
          ? '추천 위치가 설치 위치로 저장되었습니다.'
          : '추천이 완료되었습니다.',
        desc: savedRank == null ? '우측 패널에서 추천 위치를 확인하고 선택해 주세요.' : undefined,
        variant: 'success',
      };
    case 'error':
      return {
        title: pageError ?? '추천 계산에 실패했습니다. 다시 시도해 주세요.',
        variant: 'error',
      };
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

function canvasApToPhysicalAp(ap: CanvasExistingAp, targetBands: WifiBand[]): PhysicalAp {
  const enabledRadios = (ap.radios ?? []).filter((radio) => radio.enabled !== false);
  // 기존 AP에 radio 정보가 있으면 그대로 사용 (band 필터 없음)
  // radio 정보가 없을 때만 targetBands로 합성
  const radios =
    enabledRadios.length > 0
      ? enabledRadios
      : targetBands.map((band) => ({
          id: `${ap.id}-${band === '5G' ? '5g' : '2g'}`,
          band,
          enabled: true,
          frequency_mhz: band === '5G' ? 5180 : 2437,
          frequency_ghz: band === '5G' ? 5.18 : 2.437,
          channel: band === '5G' ? 36 : 6,
          tx_power_dbm: DEFAULT_TX_POWER_DBM,
        }));

  return {
    id: ap.id,
    name: ap.label ?? ap.id.toUpperCase(),
    x: ap.x_m,
    y: ap.y_m,
    z: ap.z_m ?? AP_DEFAULT_Z_M,
    movable: ap.movable ?? true,
    radios,
  };
}

function getRecommendationModeError({
  mode,
  existingApIds,
  additionalApCount,
  replaceTargetApIds,
  relocateTargetApIds,
  targetTotalAps,
  targetBands,
}: {
  mode: RecommendationMode;
  existingApIds: string[];
  additionalApCount: number;
  replaceTargetApIds: string[];
  relocateTargetApIds: string[];
  targetTotalAps: number | null;
  targetBands: WifiBand[];
}): string | null {
  if (targetBands.length === 0) return '평가할 주파수를 하나 이상 선택해 주세요.';
  if (mode === 'add' && additionalApCount < 1) {
    return '추가할 공유기 수는 1개 이상이어야 합니다.';
  }
  if (mode === 'replace') {
    if (existingApIds.length === 0) return '교체할 기존 공유기가 필요합니다.';
    if (replaceTargetApIds.length === 0) return '교체할 공유기를 선택해 주세요.';
  }
  if (mode === 'relocate_all') {
    if ((targetTotalAps ?? existingApIds.length) < 1) {
      return '최종 공유기 수는 1개 이상이어야 합니다.';
    }
  }
  if (mode === 'relocate_selected') {
    if (existingApIds.length === 0) return '재배치할 기존 공유기가 필요합니다.';
    if (relocateTargetApIds.length === 0) return '재배치할 공유기를 하나 이상 선택해 주세요.';
    const fixed = existingApIds.filter((id) => !relocateTargetApIds.includes(id));
    if (fixed.some((id) => relocateTargetApIds.includes(id))) {
      return '고정 공유기와 재배치 공유기가 중복될 수 없습니다.';
    }
  }
  return null;
}

function RecommendationAdvancedControls() {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className="inline-flex h-7 items-center rounded-md border border-slate-200 bg-white px-2 text-[11px] font-medium text-slate-700"
        title="실측 데이터가 있으면 시스템이 위치별 오차를 약하게 자동 보정합니다."
      >
        오차 자동 보정
      </span>
    </div>
  );
}

function formatBBox(bbox: ApRecommendationArea['bbox']): string {
  return `${bbox.x_min.toFixed(1)},${bbox.y_min.toFixed(1)}-${bbox.x_max.toFixed(1)},${bbox.y_max.toFixed(1)}`;
}

function areasFromRecommendationRun(run: ApRecommendationRun): ApRecommendationArea[] {
  const areas: ApRecommendationArea[] = [];
  const input = run.input_areas_json ?? {};
  const append = (
    type: ApRecommendationAreaType,
    bboxes: Array<ApRecommendationArea['bbox']> | undefined,
  ) => {
    for (const [index, bbox] of (bboxes ?? []).entries()) {
      areas.push({
        id: `${run.id}-${type}-${index}`,
        type,
        bbox,
      });
    }
  };
  append('candidate', input.candidate_bboxes);
  append(
    'priority',
    input.priority_zones?.map((zone) => ({
      x_min: zone.x_min,
      x_max: zone.x_max,
      y_min: zone.y_min,
      y_max: zone.y_max,
    })),
  );
  append('excluded', input.excluded_zones);
  return validRecommendationAreas(areas);
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

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-full min-h-[320px] items-center justify-center px-6 text-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}

interface GridCoverageMetrics {
  coverage_threshold_dbm: number;
  coverage_ratio: number | null;
  coverage_score: number | null;
  average_rssi_dbm: number | null;
  bottom_10_percent_rssi_dbm: number | null;
}

function computeGridCoverageMetrics(
  evaluation: CalibrationEvaluationResponse | null | undefined,
): GridCoverageMetrics | null {
  return computeGridCoverageMetricsFromValues(evaluation?.maps.calibrated.values_dbm);
}

function extractRunCoverageMetrics(
  metricsJson: Record<string, unknown> | null | undefined,
): GridCoverageMetrics | null {
  if (!metricsJson) return null;
  const radioMap = metricsJson['radio_map'];
  if (!radioMap || typeof radioMap !== 'object') return null;
  const rm = radioMap as Record<string, unknown>;
  // coverage_summary 에서 직접 추출 (values_dbm 불필요)
  const cs = rm['coverage_summary'];
  if (cs && typeof cs === 'object') {
    const obj = cs as Record<string, unknown>;
    const ratio = Number(obj['coverage_ratio'] ?? obj['coverage_fraction']);
    const avg = Number(obj['avg_rssi_dbm'] ?? obj['mean_rssi_dbm'] ?? obj['average_rssi_dbm']);
    const bot = Number(obj['p10_rssi_dbm'] ?? obj['bottom_10_percent_rssi_dbm'] ?? obj['p10_dbm']);
    if (Number.isFinite(ratio)) {
      return {
        coverage_threshold_dbm: COVERAGE_THRESHOLD_DBM,
        coverage_ratio: ratio,
        coverage_score: ratio,
        average_rssi_dbm: Number.isFinite(avg) ? avg : null,
        bottom_10_percent_rssi_dbm: Number.isFinite(bot) ? bot : null,
      };
    }
  }
  // fallback: values_dbm 에서 계산
  return computeGridCoverageMetricsFromValues(coerceNumberGrid(rm['values_dbm']));
}

function computeGridCoverageMetricsFromValues(
  values: number[][] | null | undefined,
): GridCoverageMetrics | null {
  if (!values) return null;
  const valid = values
    .flat()
    .filter((value) => Number.isFinite(value) && value > -120);
  if (valid.length === 0) return null;
  const covered = valid.filter((value) => value >= COVERAGE_THRESHOLD_DBM).length;
  const sorted = [...valid].sort((a, b) => a - b);
  const bottomIndex = Math.max(0, Math.floor((sorted.length - 1) * 0.1));
  const average = valid.reduce((sum, value) => sum + value, 0) / valid.length;
  const coverageRatio = covered / valid.length;
  return {
    coverage_threshold_dbm: COVERAGE_THRESHOLD_DBM,
    coverage_ratio: coverageRatio,
    coverage_score: coverageRatio,
    average_rssi_dbm: average,
    bottom_10_percent_rssi_dbm: sorted[bottomIndex],
  };
}

/** Sionna 검증 전, 추천 후보의 path-loss 예측값으로 비교용 커버리지 지표를 만든다. */
function recommendationCoverageMetrics(
  recommendation: ApRecommendationResult | null,
): GridCoverageMetrics | null {
  if (!recommendation) return null;
  const ratio = recommendation.coverage_ratio ?? recommendation.coverage_score ?? null;
  if (ratio == null) return null;
  return {
    coverage_threshold_dbm: COVERAGE_THRESHOLD_DBM,
    coverage_ratio: ratio,
    coverage_score: ratio,
    average_rssi_dbm: recommendation.average_rssi_dbm ?? null,
    bottom_10_percent_rssi_dbm: recommendation.bottom_10_percent_rssi_dbm ?? null,
  };
}

interface RecommendationHeatmap {
  valuesDbm: number[][];
  bounds: { min_x: number; min_y: number; max_x: number; max_y: number };
  rssiRange?: { min: number; max: number };
  source: 'simulation';
}

function extractRadioMapHeatmap(
  metricsJson: Record<string, unknown> | null | undefined,
  { calibrated = false }: { calibrated?: boolean } = {},
): RecommendationHeatmap | null {
  const radioMap = metricsJson?.['radio_map'];
  if (!radioMap || typeof radioMap !== 'object') return null;
  const map = radioMap as Record<string, unknown>;
  // calibrated=true 면 backend 가 저장한 affine 보정 grid 우선 사용
  const valuesKey = calibrated ? 'calibrated_values_dbm' : 'values_dbm';
  const values = coerceNumberGrid(map[valuesKey]) ?? (calibrated ? coerceNumberGrid(map['values_dbm']) : null);
  const bounds = coerceBounds(map['bounds_m']);
  if (!values || !bounds) return null;
  return {
    valuesDbm: values,
    bounds,
    rssiRange: coerceRssiRange(map['color_scale']),
    source: 'simulation',
  };
}

function extractRfMapHeatmap(map: RfMap | null | undefined): RecommendationHeatmap | null {
  if (!map) return null;
  const values =
    coerceNumberGrid(map.metrics_json?.['values_dbm']) ??
    coerceNumberGrid((map.metrics_json?.['radio_map'] as Record<string, unknown> | undefined)?.['values_dbm']);
  const bounds =
    coerceBounds(map.bounds_json) ??
    coerceBounds((map.metrics_json?.['radio_map'] as Record<string, unknown> | undefined)?.['bounds_m']);
  if (!values || !bounds) return null;
  return {
    valuesDbm: values,
    bounds,
    rssiRange:
      coerceRssiRange(map.metrics_json?.['color_scale']) ??
      coerceRssiRange((map.metrics_json?.['radio_map'] as Record<string, unknown> | undefined)?.['color_scale']),
    source: 'simulation',
  };
}

function coerceNumberGrid(raw: unknown): number[][] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const rows: number[][] = [];
  let width: number | null = null;
  for (const row of raw) {
    if (!Array.isArray(row) || row.length === 0) return null;
    const nums = row.map((value) => Number(value));
    if (nums.some((value) => !Number.isFinite(value))) return null;
    if (width == null) width = nums.length;
    if (nums.length !== width) return null;
    rows.push(nums);
  }
  return rows;
}

function coerceBounds(
  raw: unknown,
): { min_x: number; min_y: number; max_x: number; max_y: number } | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  const minX = Number(obj['min_x']);
  const minY = Number(obj['min_y']);
  const maxX = Number(obj['max_x']);
  const maxY = Number(obj['max_y']);
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
  return { min_x: minX, min_y: minY, max_x: maxX, max_y: maxY };
}

function coerceRssiRange(raw: unknown): { min: number; max: number } | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const obj = raw as Record<string, unknown>;
  const min = Number(obj['min_dbm'] ?? obj['vmin_dbm']);
  const max = Number(obj['max_dbm'] ?? obj['vmax_dbm']);
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return undefined;
  return { min, max };
}

function CoverageComparisonCard({
  recommendation,
  coverage,
  usingFallback,
  loading,
}: {
  recommendation: ApRecommendationResult | null;
  coverage: GridCoverageMetrics | null;
  usingFallback: boolean;
  loading: boolean;
}) {
  const predictionCoverage = recommendation?.coverage_ratio ?? recommendation?.coverage_score ?? null;
  const measuredCoverage = coverage?.coverage_ratio ?? coverage?.coverage_score ?? null;
  const coverageDelta =
    predictionCoverage != null && measuredCoverage != null
      ? measuredCoverage - predictionCoverage
      : null;

  return (
    <section className="rounded-xl border border-[#D8E3F0] bg-[#F8FAFC] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-foreground">예측 · 실측 통합 비교</h3>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            {usingFallback
              ? '실측 통합맵이 없어 최신 시뮬레이션 맵을 기준으로 비교합니다.'
              : '선택한 추천안의 예측맵과 최신 실측 통합 분석값을 같은 기준으로 비교합니다.'}
          </p>
        </div>
        {loading && <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" />}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <MetricTile label="추천 예측 신호 범위" value={formatCoveragePercent(predictionCoverage)} />
        <MetricTile label={usingFallback ? '시뮬레이션 신호 범위' : '통합 분석 신호 범위'} value={formatCoveragePercent(measuredCoverage)} />
        <MetricTile label="신호 범위 차이" value={formatCoverageDelta(coverageDelta)} />
        <MetricTile
          label="기준 신호"
          value={coverage?.coverage_threshold_dbm != null ? `${coverage.coverage_threshold_dbm.toFixed(0)} dBm` : '-67 dBm'}
        />
        <MetricTile
          label="예측 평균 신호"
          value={formatDbm(recommendation?.average_rssi_dbm)}
        />
        <MetricTile label={usingFallback ? '시뮬레이션 평균 신호' : '통합 평균 신호'} value={formatDbm(coverage?.average_rssi_dbm)} />
        <MetricTile
          label="예측 하위 10%"
          value={formatDbm(recommendation?.bottom_10_percent_rssi_dbm)}
        />
        <MetricTile
          label={usingFallback ? '시뮬레이션 하위 10%' : '통합 하위 10%'}
          value={formatDbm(coverage?.bottom_10_percent_rssi_dbm)}
        />
      </div>
    </section>
  );
}

function RecommendationSummaryCard({
  response,
  selectedRecommendation,
}: {
  response: ApRecommendationResponse | null;
  selectedRecommendation: ApRecommendationResult | null;
}) {
  const score = selectedRecommendation?.score_breakdown ?? response?.score_breakdown ?? {};
  const bandScores = (score['band_scores'] ?? {}) as Record<string, Record<string, unknown>>;
  const bandMeta = response?.band_metadata as Record<string, unknown> | null | undefined;
  const coverageSemantics = response?.coverage_semantics;
  const targetBands = Array.isArray(bandMeta?.['requested_bands'])
    ? (bandMeta?.['requested_bands'] as unknown[]).map(formatBandLabel).join(', ')
    : Array.isArray(response?.physical_aps_snapshot)
      ? '공유기 설정값'
      : '-';
  const combinePolicy =
    typeof bandMeta?.['combine_policy'] === 'string' ? bandMeta['combine_policy'] : '-';
  const mode = formatRecommendationModeLabel(response?.recommendation_mode);

  return (
    <section className="rounded-xl border border-[#D8E3F0] bg-[#F8FAFC] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-foreground">추천 결과 요약</h3>
          {response?.mode_explanation && (
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              {response.mode_explanation}
            </p>
          )}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <MetricTile label="추천 방식" value={mode} />
        <MetricTile label="평가 주파수" value={targetBands} />
        <MetricTile label="통합 방식" value={formatCombinePolicyLabel(String(combinePolicy))} />
        <MetricTile label="빠른 평가 점수" value={selectedRecommendation ? selectedRecommendation.score.toFixed(3) : '-'} />
        <MetricTile label="정밀 평가 점수" value={selectedRecommendation?.verified_score != null ? selectedRecommendation.verified_score.toFixed(3) : '-'} />
        <MetricTile label="커버리지" value={formatCoveragePercent(pickScoreNumber(score, 'coverage_ratio', 'coverage_score'))} />
        <MetricTile label="평균 신호" value={formatDbm(pickScoreNumber(score, 'average_rssi_dbm', 'average_rssi'))} />
        <MetricTile label="약한 구역 개선" value={formatDbm(pickScoreNumber(score, 'weak_zone_improvement_db', 'weak_zone_improvement'))} />
        <MetricTile label="하위 10% 신호" value={formatDbm(pickScoreNumber(score, 'bottom_10_percent_rssi_dbm', 'bottom_10_percent'))} />
      </div>
      {coverageSemantics?.rssi_is_not_summed === true && (
        <p className="mt-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-[11px] leading-relaxed text-blue-700">
          여러 공유기의 신호는 단순히 더하지 않고, 각 위치에서 가장 잘 잡히는 공유기 신호를 기준으로 커버리지를 평가합니다.
        </p>
      )}
      {Object.keys(bandScores).length > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-2">
          {(['5G', '2.4G', 'overall'] as const).map((band) => {
            const data = bandScores[band];
            if (!data) return null;
            return (
              <MetricTile
                key={band}
                label={`${formatBandLabel(band)} 커버리지`}
                value={formatCoveragePercent(numberFromRecord(data, 'coverage_ratio'))}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}

function formatBandLabel(value: unknown): string {
  if (value === '5G') return '5GHz';
  if (value === '2.4G') return '2.4GHz';
  if (value === 'overall') return '전체';
  return String(value ?? '-');
}

function formatCombinePolicyLabel(value: string): string {
  if (value === 'prefer_5g_then_2g') return '5GHz 우선, 2.4GHz 보완';
  if (value === 'max') return '더 강한 신호 기준';
  if (value === 'weighted') return '가중 평균';
  return value === '-' ? '-' : value;
}

function formatRecommendationModeLabel(value: unknown): string {
  if (value === 'add') return '공유기 추가';
  if (value === 'replace') return '공유기 교체';
  if (value === 'relocate_all') return '전체 재배치';
  if (value === 'relocate_selected') return '선택 재배치';
  return String(value ?? '-');
}

function numberFromRecord(source: Record<string, unknown>, key: string): number | null {
  const value = source[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function pickScoreNumber(source: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function SionnaVerificationCard({
  recommendation,
  integratedCoverage,
  sionnaCoverage,
  calibratedSionnaCoverage,
  runStatus,
  loadingIntegrated,
  verifying,
  polling,
  canCompare,
  verifyDisabled,
  calibrationWarning,
  showComparison,
  onVerify,
  onCompare,
}: {
  recommendation: ApRecommendationResult | null;
  integratedCoverage: GridCoverageMetrics | null;
  sionnaCoverage: GridCoverageMetrics | null;
  calibratedSionnaCoverage: GridCoverageMetrics | null;
  runStatus: string | null;
  loadingIntegrated: boolean;
  verifying: boolean;
  polling: boolean;
  canCompare: boolean;
  verifyDisabled: boolean;
  calibrationWarning: string | null;
  showComparison: boolean;
  onVerify: () => void;
  onCompare: () => void;
}) {
  const predictionCoverage = recommendation?.coverage_ratio ?? recommendation?.coverage_score ?? null;
  const sionnaRatio = sionnaCoverage?.coverage_ratio ?? sionnaCoverage?.coverage_score ?? null;
  const calibratedSionnaRatio =
    calibratedSionnaCoverage?.coverage_ratio ?? calibratedSionnaCoverage?.coverage_score ?? null;
  const integratedRatio = integratedCoverage?.coverage_ratio ?? integratedCoverage?.coverage_score ?? null;
  const sionnaVsIntegrated =
    calibratedSionnaRatio != null && integratedRatio != null
      ? calibratedSionnaRatio - integratedRatio
      : null;
  const isBusy = verifying || polling;

  return (
    <section className="rounded-xl border border-[#D8E3F0] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-foreground">정밀 검증 비교</h3>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            선택한 후보 위치에 공유기를 배치하고 전파 시뮬레이션을 실행해 현재 통합맵과 비교합니다.
          </p>
        </div>
        {(isBusy || loadingIntegrated) && (
          <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
        )}
      </div>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onVerify}
          disabled={verifyDisabled || isBusy}
          className={cn(
            'flex-1 rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors',
            'border-[#D8E3F0] bg-white text-slate-600 hover:bg-muted/60',
            'disabled:cursor-not-allowed disabled:opacity-50',
          )}
        >
          {isBusy ? (
            <span className="inline-flex items-center justify-center gap-1.5">
              <Loader2 className="h-4 w-4 animate-spin" />
              {verifying ? '비교 요청 중' : '정밀 시뮬레이션 실행 중'}
            </span>
          ) : (
            '현재 위치와 비교'
          )}
        </button>
        {canCompare && (
          <button
            type="button"
            onClick={onCompare}
            className={cn(
              'flex-1 rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors',
              showComparison
                ? 'border-emerald-400 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                : 'border-[#D8E3F0] bg-white text-slate-600 hover:bg-muted/60',
            )}
          >
            {showComparison ? '비교 닫기' : '비교 보기'}
          </button>
        )}
      </div>

      {calibrationWarning && (
        <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-700">
          {calibrationWarning}
        </p>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <MetricTile label="빠른 예측 신호 범위" value={formatCoveragePercent(predictionCoverage)} />
        <MetricTile label="정밀 예측 신호 범위" value={formatCoveragePercent(sionnaRatio)} />
        <MetricTile label="보정 후 정밀 신호 범위" value={formatCoveragePercent(calibratedSionnaRatio)} />
        <MetricTile label="현재 통합맵 신호 범위" value={formatCoveragePercent(integratedRatio)} />
        <MetricTile label="정밀-통합 차이" value={formatCoverageDelta(sionnaVsIntegrated)} />
        <MetricTile label="정밀 평균 신호" value={formatDbm(sionnaCoverage?.average_rssi_dbm)} />
        <MetricTile label="보정 후 평균 신호" value={formatDbm(calibratedSionnaCoverage?.average_rssi_dbm)} />
        <MetricTile label="정밀 하위 10%" value={formatDbm(sionnaCoverage?.bottom_10_percent_rssi_dbm)} />
        <MetricTile label="실행 상태" value={runStatus ?? '-'} />
      </div>
    </section>
  );
}

function SimComparisonCard({
  integratedCoverage,
  recommendedCoverage,
  hasIntegratedHeatmap,
  hasRecommendedHeatmap,
  recommendedIsEstimate,
  simComparisonTab,
  onTabChange,
}: {
  integratedCoverage: GridCoverageMetrics | null;
  recommendedCoverage: GridCoverageMetrics | null;
  hasIntegratedHeatmap: boolean;
  hasRecommendedHeatmap: boolean;
  recommendedIsEstimate: boolean;
  simComparisonTab: 'baseline' | 'verification';
  onTabChange: (tab: 'baseline' | 'verification') => void;
}) {
  const bCov = integratedCoverage?.coverage_ratio ?? integratedCoverage?.coverage_score ?? null;
  const vCov = recommendedCoverage?.coverage_ratio ?? recommendedCoverage?.coverage_score ?? null;
  const covDelta = bCov != null && vCov != null ? vCov - bCov : null;
  const rssiDelta =
    integratedCoverage?.average_rssi_dbm != null && recommendedCoverage?.average_rssi_dbm != null
      ? recommendedCoverage.average_rssi_dbm - integratedCoverage.average_rssi_dbm
      : null;
  const botDelta =
    integratedCoverage?.bottom_10_percent_rssi_dbm != null &&
    recommendedCoverage?.bottom_10_percent_rssi_dbm != null
      ? recommendedCoverage.bottom_10_percent_rssi_dbm - integratedCoverage.bottom_10_percent_rssi_dbm
      : null;

  return (
    <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
      <h3 className="text-sm font-bold text-emerald-800">현재 위치 vs 추천 위치 비교</h3>
      <p className="mt-0.5 text-[11px] text-emerald-700">
        좌측 지도 탭으로 현재/추천 위치 맵을 전환하세요.
      </p>
      {recommendedIsEstimate && (
        <p className="mt-1 text-[11px] text-amber-700">
          추천 위치는 아직 정밀 시뮬레이션 결과가 없어 path-loss 기반 예측값으로 비교합니다.
        </p>
      )}

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="text-[10px] font-semibold text-muted-foreground" />
        <div className="text-[10px] font-semibold text-slate-600">현재 위치</div>
        <div className="text-[10px] font-semibold text-blue-600">추천 위치</div>

        <div className="rounded-lg bg-white px-2 py-2 text-[10px] font-medium text-muted-foreground">커버리지</div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'baseline' ? 'bg-slate-100 text-slate-800' : 'bg-white text-slate-600')}>
          {formatCoveragePercent(bCov)}
        </div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'verification' ? 'bg-blue-100 text-blue-800' : 'bg-white text-blue-600')}>
          {formatCoveragePercent(vCov)}
        </div>

        <div className="rounded-lg bg-white px-2 py-2 text-[10px] font-medium text-muted-foreground">평균 신호</div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'baseline' ? 'bg-slate-100 text-slate-800' : 'bg-white text-slate-600')}>
          {formatDbm(integratedCoverage?.average_rssi_dbm)}
        </div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'verification' ? 'bg-blue-100 text-blue-800' : 'bg-white text-blue-600')}>
          {formatDbm(recommendedCoverage?.average_rssi_dbm)}
        </div>

        <div className="rounded-lg bg-white px-2 py-2 text-[10px] font-medium text-muted-foreground">하위 10%</div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'baseline' ? 'bg-slate-100 text-slate-800' : 'bg-white text-slate-600')}>
          {formatDbm(integratedCoverage?.bottom_10_percent_rssi_dbm)}
        </div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'verification' ? 'bg-blue-100 text-blue-800' : 'bg-white text-blue-600')}>
          {formatDbm(recommendedCoverage?.bottom_10_percent_rssi_dbm)}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <DeltaTile label="커버리지 변화" delta={covDelta} isRatio />
        <DeltaTile label="평균 신호 변화" delta={rssiDelta} unit="dBm" />
        <DeltaTile label="하위 10% 변화" delta={botDelta} unit="dBm" />
      </div>

      {(hasIntegratedHeatmap || hasRecommendedHeatmap) && (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            disabled={!hasIntegratedHeatmap}
            onClick={() => onTabChange('baseline')}
            className={cn(
              'flex-1 rounded-md border py-1.5 text-xs font-medium transition-colors',
              simComparisonTab === 'baseline'
                ? 'border-slate-400 bg-slate-700 text-white'
                : hasIntegratedHeatmap
                  ? 'border-[#D8E3F0] bg-white text-slate-500 hover:bg-muted/60'
                  : 'cursor-not-allowed border-[#E5EAF2] bg-muted text-muted-foreground/50',
            )}
          >
            현재 위치 보기
          </button>
          <button
            type="button"
            disabled={!hasRecommendedHeatmap}
            onClick={() => onTabChange('verification')}
            className={cn(
              'flex-1 rounded-md border py-1.5 text-xs font-medium transition-colors',
              simComparisonTab === 'verification'
                ? 'border-blue-500 bg-blue-600 text-white'
                : hasRecommendedHeatmap
                  ? 'border-[#D8E3F0] bg-white text-slate-500 hover:bg-muted/60'
                  : 'cursor-not-allowed border-[#E5EAF2] bg-muted text-muted-foreground/50',
            )}
          >
            추천 위치 보기
          </button>
        </div>
      )}
    </section>
  );
}

function DeltaTile({
  label,
  delta,
  isRatio,
  unit,
}: {
  label: string;
  delta: number | null;
  isRatio?: boolean;
  unit?: string;
}) {
  if (delta == null || !Number.isFinite(delta)) {
    return (
      <div className="rounded-lg bg-white px-2 py-2 text-center">
        <p className="text-[10px] text-muted-foreground">{label}</p>
        <p className="mt-0.5 text-sm font-bold text-foreground">-</p>
      </div>
    );
  }
  const positive = delta > 0;
  const display = isRatio
    ? `${positive ? '+' : ''}${(delta * 100).toFixed(1)}%`
    : `${positive ? '+' : ''}${delta.toFixed(1)}${unit ?? ''}`;
  return (
    <div className="rounded-lg bg-white px-2 py-2 text-center">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className={cn('mt-0.5 text-sm font-bold', positive ? 'text-emerald-600' : delta < 0 ? 'text-red-500' : 'text-foreground')}>
        {display}
      </p>
    </div>
  );
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[#E5EAF2] bg-white px-3 py-2">
      <p className="text-[10px] font-medium text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-bold text-foreground">{value}</p>
    </div>
  );
}

function formatCoveragePercent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '-';
  const percent = value <= 1 ? value * 100 : value;
  return `${percent.toFixed(1)}%`;
}

function formatCoverageDelta(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '-';
  const percent = value <= 1 && value >= -1 ? value * 100 : value;
  const sign = percent > 0 ? '+' : '';
  return `${sign}${percent.toFixed(1)}%`;
}

function formatDbm(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value.toFixed(1)} dBm`;
}

function readStoredMeasurementView(floorId: string | null): StoredMeasurementView | null {
  if (!floorId || typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(MEASUREMENT_VIEW_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as {
      byFloor?: Record<string, Partial<StoredMeasurementView>>;
    };
    const value = parsed.byFloor?.[floorId];
    if (!value) return null;
    return {
      sessionId: value.sessionId ?? null,
      sceneVersionId: value.sceneVersionId ?? null,
      apBssid: value.apBssid ?? null,
    };
  } catch {
    return null;
  }
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
  const RANK_STYLES = [
    { border: 'border-[#8BDFDD]', badge: 'bg-[#8BDFDD]',  selectedBorder: 'border-[#8BDFDD] ring-1 ring-[#8BDFDD]/60', savedButton: 'border-[#8BDFDD] bg-[#8BDFDD] text-white' },
    { border: 'border-[#C47BE4]', badge: 'bg-[#C47BE4]',  selectedBorder: 'border-[#C47BE4] ring-1 ring-[#9B8EC7]/60', savedButton: 'border-[#C47BE4] bg-[#C47BE4] text-white' },
    { border: 'border-[#FF8FB7]', badge: 'bg-[#FF8FB7]',  selectedBorder: 'border-[#FF8FB7] ring-1 ring-[#F075AE]/60', savedButton: 'border-[#FF8FB7] bg-[#FF8FB7] text-white' },
    { border: 'border-[#67C090]', badge: 'bg-[#67C090]',  selectedBorder: 'border-[#67C090] ring-1 ring-[#67C090]/60', savedButton: 'border-[#67C090] bg-[#67C090] text-white' },
    { border: 'border-[#D8D365]', badge: 'bg-[#D8D365]',  selectedBorder: 'border-[#D8D365] ring-1 ring-[#D8D365]/60', savedButton: 'border-[#D8D365] bg-[#D8D365] text-white' },
  ];
  const style = RANK_STYLES[(rec.rank - 1) % RANK_STYLES.length];

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
        saved || selected ? `${style.selectedBorder} shadow-sm` : 'border-[#E5EAF2]',
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white', style.badge)}>
          {rec.rank}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-bold text-foreground">{rec.rank}순위 추천</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {rec.ap_positions && rec.ap_positions.length > 1
              ? rec.ap_positions.map((p) => `공유기${p.ap_index} (${p.x.toFixed(0)}m, ${p.y.toFixed(0)}m)`).join(' · ')
              : `위치 X ${rec.recommended_x.toFixed(0)}m / Y ${rec.recommended_y.toFixed(0)}m`}
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
            우선 평가 영역에 가장 잘 닿는 위치
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            빠른 평가{' '}
            <span className="font-semibold text-foreground">{rec.score.toFixed(3)}</span>
            {rec.verified_score != null && (
              <>
                {' '}· 보정 점수{' '}
                <span className="font-semibold text-emerald-700">{rec.verified_score.toFixed(3)}</span>
              </>
            )}
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
            ? style.savedButton
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
  const steps = PROGRESS_STEPS.map((step) => ({
    ...step,
    done:
      step.id < activeStep ||
      (step.id === 1 && pageStatus !== 'idle') ||
      (step.id === 2 && (pageStatus === 'success' || pageStatus === 'loading')) ||
      (step.id === 3 && activeStep >= 3),
    current: step.id === activeStep && pageStatus !== 'error',
  }));

  return (
    <ol className="flex w-full">
      {steps.map((step, index) => {
        const isFirst = index === 0;
        const isLast = index === steps.length - 1;
        const connectorDone = step.id <= activeStep;
        return (
          <li key={step.id} className="flex min-w-0 flex-1 flex-col items-center">
            {/* 원 + 양쪽 연결선 */}
            <div className="flex w-full items-center">
              <div className={cn('h-0.5 flex-1', isFirst ? 'invisible' : connectorDone ? 'bg-emerald-400' : 'bg-[#E5EAF2]')} aria-hidden="true" />
              <div
                className={cn(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold',
                  step.done && !step.current && 'bg-emerald-500 text-white',
                  step.current && 'bg-blue-600 text-white',
                  !step.done && !step.current && 'bg-muted text-muted-foreground',
                )}
              >
                {step.done && !step.current ? <CheckCircle2 className="h-4 w-4" /> : step.id}
              </div>
              <div className={cn('h-0.5 flex-1', isLast ? 'invisible' : step.id < activeStep ? 'bg-emerald-400' : 'bg-[#E5EAF2]')} aria-hidden="true" />
            </div>
            {/* 라벨 */}
            <span
              className={cn(
                'mt-2 text-center text-xs leading-tight',
                step.current ? 'font-semibold text-foreground' : 'text-muted-foreground',
              )}
            >
              {step.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
