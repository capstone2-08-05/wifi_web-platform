import { useEffect, useMemo, useState } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { Ban, CheckCircle2, Loader2, MapPin, Sparkles, Target } from 'lucide-react';
import type { HttpError } from '@/api/client';
import { calibrationRunApi } from '@/api/calibration-run';
import { rfRunApi } from '@/api/rf-run';
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
    hint: '좌석·작업 공간처럼 Wi-Fi 품질을 중요하게 볼 영역입니다.',
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
  const [nAps, setNAps] = useState(1);
  const [recommendationMode, setRecommendationMode] = useState<RecommendationMode>('add');
  const [replaceTargetApIds, setReplaceTargetApIds] = useState<string[]>([]);
  const [relocateTargetApIds, setRelocateTargetApIds] = useState<string[]>([]);
  const [targetTotalAps, setTargetTotalAps] = useState<number | null>(null);
  const [targetBands, setTargetBands] = useState<WifiBand[]>(['5G']);
  const [combinePolicy, setCombinePolicy] = useState<CombinePolicy>('prefer_5g_then_2g');
  const verifyWithSionna = true;
  const verificationTopK = 5;
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
  const [compareWithMeasurement, setCompareWithMeasurement] = useState(false);
  const [verificationRunId, setVerificationRunId] = useState<string | null>(null);
  const [verificationRank, setVerificationRank] = useState<number | null>(null);
  const [recommendationUpdatedAt, setRecommendationUpdatedAt] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [showSimComparison, setShowSimComparison] = useState(false);
  const [simComparisonTab, setSimComparisonTab] = useState<'baseline' | 'verification'>('verification');

  const recommendMutation = useApRecommendation();
  const recommendationRunsQuery = useApRecommendationRuns(sceneVersionId, 10);
  const createLayout = useCreateApLayout();
  const verificationPoll = useRfRun(verificationRunId);
  const verificationMapsQuery = useRfMaps(verificationRunId, verificationPoll.isSucceeded);
  const baselineRunDetail = useRfRun(latestRfRunId);
  const autoVerificationRuns = useMemo(
    () =>
      (recommendMutation.data?.verification_jobs ?? [])
        .filter((job): job is typeof job & { rf_run_id: string } => typeof job.rf_run_id === 'string')
        .map((job) => ({ rank: job.candidate_rank, runId: job.rf_run_id })),
    [recommendMutation.data?.verification_jobs],
  );
  const autoVerificationRunQueries = useQueries({
    queries: autoVerificationRuns.map((job) => ({
      queryKey: ['rf-run', job.runId] as const,
      queryFn: () => rfRunApi.get(job.runId),
      enabled: !!job.runId,
      refetchInterval: (query: { state: { data?: { status?: string } } }) =>
        isRfRunTerminal(query.state.data?.status) ? false : 3_000,
      refetchIntervalInBackground: false,
    })),
  });
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
  const verificationScoresByRank = useMemo(() => {
    const scores = new Map<number, VerificationScore>();
    autoVerificationRuns.forEach((job, index) => {
      const run = autoVerificationRunQueries[index]?.data;
      const heatmap = extractRadioMapHeatmap(run?.metrics_json);
      const coverage = computeGridCoverageMetricsFromValues(heatmap?.valuesDbm);
      scores.set(job.rank, {
        score: computeVerificationScore(coverage),
        status: run?.status ?? null,
        coverage,
      });
    });
    return scores;
  }, [autoVerificationRunQueries, autoVerificationRuns]);
  const rankedRecommendations = useMemo(() => {
    return recommendations
      .map((rec) => {
        const verification = verificationScoresByRank.get(rec.rank);
        return {
          ...rec,
          verified_score: verification?.score ?? rec.verified_score ?? null,
          verification_status: verification?.status ?? rec.verification_status ?? null,
        };
      })
      .sort((a, b) => {
        const aScore = a.verified_score ?? a.score;
        const bScore = b.verified_score ?? b.score;
        if (bScore !== aScore) return bScore - aScore;
        return b.score - a.score;
      });
  }, [recommendations, verificationScoresByRank]);
  const selectedRecommendation = useMemo(
    () => rankedRecommendations.find((rec) => rec.rank === selectedRank) ?? rankedRecommendations[0] ?? null,
    [rankedRecommendations, selectedRank],
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
  const comparisonHeatmap = verificationCalibratedHeatmap ?? verificationHeatmap ?? integratedHeatmap;
  const showComparisonHeatmap = compareWithMeasurement && !!comparisonHeatmap;
  const verificationMatchesSelection =
    selectedRecommendation != null && verificationRank === selectedRecommendation.rank;

  const canvasHeatmap = showSimComparison && verificationMatchesSelection
    ? (simComparisonTab === 'baseline' ? baselineHeatmap : (verificationCalibratedHeatmap ?? verificationHeatmap))
    : showComparisonHeatmap ? comparisonHeatmap : null;
  const useComparisonMode = (showSimComparison && verificationMatchesSelection) || showComparisonHeatmap;

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
      setCompareWithMeasurement(false);
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
    setCompareWithMeasurement(stored.compareWithMeasurement);
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
    setCompareWithMeasurement(false);
    setRecommendationUpdatedAt(latestRun.created_at);
    setPageError(null);
    if (sceneVersionId) {
      patchRecommendationScene(sceneVersionId, {
        sceneVersionId,
        areas: runAreas,
        recommendations: runRecommendations,
        selectedRank: runRecommendations[0]?.rank ?? null,
        savedRank: null,
        compareWithMeasurement: false,
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
    setCompareWithMeasurement(false);
    setVerificationRunId(null);
    setVerificationRank(null);
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
      verificationTopK,
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
    persistRecommendationSession({
      areas: validAreas,
      savedRank: null,
      compareWithMeasurement: false,
    });
    recommendMutation.mutate(payload, {
      onSuccess: (data) => {
        const normalized = normalizeRecommendations(data);
        const firstVerificationJob = data.verification_jobs?.find((job) => job.rf_run_id);
        const firstVerificationRunId =
          typeof firstVerificationJob?.rf_run_id === 'string' ? firstVerificationJob.rf_run_id : null;
        const firstVerificationRank =
          typeof firstVerificationJob?.candidate_rank === 'number'
            ? firstVerificationJob.candidate_rank
            : null;
        setRecommendations(normalized);
        setSelectedRank(normalized[0]?.rank ?? null);
        setCompareWithMeasurement(!!firstVerificationRunId);
        setVerificationRunId(firstVerificationRunId);
        setVerificationRank(firstVerificationRank);
        persistRecommendationSession({
          areas: validAreas,
          recommendations: normalized,
          selectedRank: normalized[0]?.rank ?? null,
          savedRank: null,
          compareWithMeasurement: !!firstVerificationRunId,
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
    const verificationRunForRank = getVerificationRunIdForRank(recommendMutation.data ?? null, rec.rank);
    setVerificationRunId(verificationRunForRank);
    setVerificationRank(verificationRunForRank ? rec.rank : null);
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
    const verificationRunForRank = getVerificationRunIdForRank(recommendMutation.data ?? null, rec.rank);
    setVerificationRunId(verificationRunForRank);
    setVerificationRank(verificationRunForRank ? rec.rank : null);
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

  const statusHint = getStatusHint(pageStatus, pageError, savedRank);

  return (
    <div className="flex h-full flex-col overflow-auto bg-[#F8FAFC]">
      {/* 본문 헤더 — Figma: 제목 + 설명 + 우측 CTA */}
      <header className="shrink-0 px-6 pb-4 pt-6 lg:px-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              공유기 위치 추천
            </h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              설치 가능 영역과 우선 평가 영역을 표시하면 신호가 잘 닿는 공유기 위치를 추천합니다.
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-stretch gap-1.5 sm:items-end">
            {/* 추천 모드 */}
            <div className="flex items-center gap-2 sm:justify-end">
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

            {/* 모드별 부가 입력 */}
            <TargetBandControls
              targetBands={targetBands}
              combinePolicy={combinePolicy}
              onTargetBandsChange={setTargetBands}
              onCombinePolicyChange={setCombinePolicy}
              disabled={recommendMutation.isPending}
            />
            <RecommendationAdvancedControls />

            {recommendationMode === 'replace' && (
              <div className="flex items-center gap-2 sm:justify-end">
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
                    <option key={ap.id} value={ap.id}>
                      {ap.id}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {recommendationMode === 'relocate_selected' && (
              <div className="flex items-center gap-2 sm:justify-end">
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
                    <option key={ap.id} value={ap.id}>
                      {ap.id}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {recommendationMode === 'relocate_all' && (
              <div className="flex items-center gap-2 sm:justify-end">
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

            {/* add / replace 모드에서는 설치 개수 선택 유지 */}
            {(recommendationMode === 'add' || recommendationMode === 'replace') && (
            <div className="flex items-center gap-2 sm:justify-end">
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
                'inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold shadow-sm transition-colors',
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
              <p className="text-[11px] text-amber-600 sm:text-right">
                공유기 위치 저장은 시뮬레이션 실행 후 가능합니다.
              </p>
            )}
            {modeValidationError && !recommendMutation.isPending && (
              <p className="text-[11px] text-amber-600 sm:text-right">
                {modeValidationError}
              </p>
            )}
            {sceneVersionId && !canRecommend && !recommendMutation.isPending && (
              <p className="text-[11px] text-muted-foreground sm:text-right">
                공유기를 둘 수 있는 영역을 먼저 지정하면 추천을 실행할 수 있습니다.
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
              <>
                {showSimComparison && verificationMatchesSelection && (
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
                      기존 시뮬
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
                      추천 검증
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
                  recommendations={recommendations}
                  recommendationMode={recommendationMode}
                  selectedReplacementIds={replaceTargetApIds}
                  movableApIds={relocateTargetApIds}
                  selectedRecommendationRank={selectedRank}
                  heatmapMode={useComparisonMode ? 'measurement' : 'prediction'}
                  measurementHeatmap={canvasHeatmap}
                  disabled={recommendMutation.isPending || createLayout.isPending}
                />
              </>
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
                  통합 분석 보기
                </button>
              )}
            </div>
            {recommendations.length > 0 && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                {showComparisonHeatmap
                  ? verificationCalibratedHeatmap
                    ? '선택 후보의 정밀 검증 결과에 예측·실측 보정을 적용한 통합맵을 보고 있습니다.'
                    : '측정 페이지의 예측·실측 통합 분석맵을 보고 있습니다.'
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
                  도면에서 설치 가능 영역을 먼저 지정한 뒤 추천을 실행해 주세요.
                </p>
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
                  starting={recommendMutation.isPending}
                  polling={verificationMatchesSelection && verificationPoll.isPolling}
                  canCompare={verificationMatchesSelection && verificationPoll.isSucceeded}
                  showComparison={showSimComparison}
                  onCompare={() => {
                    setShowSimComparison((v) => !v);
                    setSimComparisonTab('verification');
                  }}
                />
                {showSimComparison && verificationMatchesSelection && (
                  <SimComparisonCard
                    baselineCoverage={
                      baselineCoverageMetrics ??
                      extractRunCoverageMetrics(baselineRunDetail.rfRun?.metrics_json) ??
                      extractRunCoverageMetrics(latestRfRun?.metrics_json)
                    }
                    verificationCoverage={
                      verificationCalibratedCoverageMetrics ??
                      verificationCoverageMetrics ??
                      extractRunCoverageMetrics(verificationPoll.rfRun?.metrics_json)
                    }
                    hasBaselineHeatmap={!!baselineHeatmap}
                    hasVerificationHeatmap={!!(verificationCalibratedHeatmap ?? verificationHeatmap)}
                    simComparisonTab={simComparisonTab}
                    onTabChange={setSimComparisonTab}
                  />
                )}
                {rankedRecommendations.map((rec) => (
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
      return '도면 위에서 설치 가능 영역을 먼저 드래그해 주세요.';
    case 'areaSelected':
      return '필요하면 우선 평가 영역이나 제외 영역을 추가한 뒤 추천을 실행하세요.';
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

function canvasApToPhysicalAp(ap: CanvasExistingAp, targetBands: WifiBand[]): PhysicalAp {
  const enabledRadios = (ap.radios ?? []).filter((radio) => radio.enabled !== false);
  const matchingRadios = enabledRadios.filter((radio) => targetBands.includes(radio.band));
  const radios =
    matchingRadios.length > 0
      ? matchingRadios
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

function getVerificationRunIdForRank(
  response: ApRecommendationResponse | null,
  rank: number,
): string | null {
  const job = response?.verification_jobs?.find((entry) => entry.candidate_rank === rank);
  return typeof job?.rf_run_id === 'string' ? job.rf_run_id : null;
}

function TargetBandControls({
  targetBands,
  combinePolicy,
  onTargetBandsChange,
  onCombinePolicyChange,
  disabled,
}: {
  targetBands: WifiBand[];
  combinePolicy: CombinePolicy;
  onTargetBandsChange: (bands: WifiBand[]) => void;
  onCombinePolicyChange: (policy: CombinePolicy) => void;
  disabled?: boolean;
}) {
  const bandModes: Array<{ key: string; label: string; bands: WifiBand[] }> = [
    { key: '5g', label: '5GHz', bands: ['5G'] },
    { key: '2g', label: '2.4GHz', bands: ['2.4G'] },
    { key: 'dual', label: '5GHz + 2.4GHz', bands: ['5G', '2.4G'] },
  ];
  const currentKey =
    targetBands.length > 1 ? 'dual' : targetBands[0] === '2.4G' ? '2g' : '5g';
  const policies: Array<{ value: CombinePolicy; label: string }> = [
    { value: 'prefer_5g_then_2g', label: '5GHz 우선' },
    { value: 'max', label: '더 강한 신호' },
    { value: 'weighted', label: '가중 평균' },
  ];

  return (
    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
      <span className="text-[12px] text-slate-500">주파수</span>
      <div
        className="inline-flex items-center rounded-lg bg-slate-100 p-0.5"
        title="2.4GHz와 5GHz는 전파 특성이 달라 추천 평가에 주파수 정보를 함께 전달합니다."
      >
        {bandModes.map((mode) => (
          <button
            key={mode.key}
            type="button"
            disabled={disabled}
            onClick={() => onTargetBandsChange(mode.bands)}
            className={cn(
              'inline-flex h-6 items-center rounded-md px-2 text-[11px] transition-colors',
              currentKey === mode.key
                ? 'bg-white font-semibold text-blue-700 shadow-sm'
                : 'text-slate-500 hover:text-slate-800',
            )}
          >
            {mode.label}
          </button>
        ))}
      </div>
      <select
        value={combinePolicy}
        disabled={disabled}
        onChange={(event) => onCombinePolicyChange(event.target.value as CombinePolicy)}
        className="h-7 rounded-md border border-slate-200 bg-white px-2 text-[11px] font-medium text-slate-700 focus:border-blue-300 focus:outline-none disabled:opacity-50"
        aria-label="주파수 통합 방식"
      >
        {policies.map((policy) => (
          <option key={policy.value} value={policy.value}>
            {policy.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function RecommendationAdvancedControls() {
  return (
    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
      <span
        className="inline-flex h-7 items-center rounded-md border border-slate-200 bg-white px-2 text-[11px] font-medium text-slate-700"
        title="실측 데이터가 있으면 시스템이 위치별 오차를 약하게 자동 보정합니다."
      >
        오차 자동 보정
      </span>
      <span
        className="inline-flex h-7 items-center rounded-md border border-emerald-200 bg-emerald-50 px-2 text-[11px] font-semibold text-emerald-700"
        title="추천을 실행하면 상위 5개 후보를 자동으로 정밀 검증하고 결과를 저장합니다."
      >
        상위 5개 자동 비교
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

interface VerificationScore {
  score: number | null;
  status: string | null;
  coverage: GridCoverageMetrics | null;
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

interface RecommendationHeatmap {
  valuesDbm: number[][];
  bounds: { min_x: number; min_y: number; max_x: number; max_y: number };
  rssiRange?: { min: number; max: number };
  source: 'simulation';
}

function extractRadioMapHeatmap(
  metricsJson: Record<string, unknown> | null | undefined,
): RecommendationHeatmap | null {
  const radioMap = metricsJson?.['radio_map'];
  if (!radioMap || typeof radioMap !== 'object') return null;
  const map = radioMap as Record<string, unknown>;
  const values = coerceNumberGrid(map['values_dbm']);
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

function isRfRunTerminal(status: string | null | undefined): boolean {
  return ['done', 'completed', 'succeeded', 'failed', 'error', 'cancelled'].includes(String(status ?? '').toLowerCase());
}

function computeVerificationScore(coverage: GridCoverageMetrics | null): number | null {
  if (!coverage) return null;
  const coverageScore = coverage.coverage_ratio ?? coverage.coverage_score ?? null;
  const averageScore =
    coverage.average_rssi_dbm == null ? null : normalizeRange(coverage.average_rssi_dbm, -85, -45);
  const bottomScore =
    coverage.bottom_10_percent_rssi_dbm == null
      ? null
      : normalizeRange(coverage.bottom_10_percent_rssi_dbm, -85, -67);
  return weightedAverage([
    [coverageScore, 0.45],
    [averageScore, 0.35],
    [bottomScore, 0.2],
  ]);
}

function normalizeRange(value: number, min: number, max: number): number {
  if (max <= min) return 0;
  return Math.max(0, Math.min(1, (value - min) / (max - min)));
}

function weightedAverage(values: Array<[number | null | undefined, number]>): number | null {
  let numerator = 0;
  let denominator = 0;
  for (const [value, weight] of values) {
    if (value == null || !Number.isFinite(value)) continue;
    numerator += value * weight;
    denominator += weight;
  }
  return denominator > 0 ? numerator / denominator : null;
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
        <MetricTile label="추천 예측 커버리지" value={formatCoveragePercent(predictionCoverage)} />
        <MetricTile label={usingFallback ? '시뮬레이션 커버리지' : '통합 분석 커버리지'} value={formatCoveragePercent(measuredCoverage)} />
        <MetricTile label="커버리지 차이" value={formatCoverageDelta(coverageDelta)} />
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
      {response?.verification_jobs && response.verification_jobs.length > 0 && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
          <p className="text-[11px] font-semibold text-slate-700">
            정밀 검증: {formatVerificationStatus(response.verification_status)}
          </p>
          <div className="mt-1 space-y-1">
            {response.verification_jobs.map((job) => (
              <p key={job.candidate_id} className="text-[11px] text-muted-foreground">
                {job.candidate_rank}순위: 빠른 평가 {job.fast_score?.toFixed(3) ?? '-'} / {formatVerificationStatus(job.status)}
                {job.rf_run_id ? ` · Run ${String(job.rf_run_id).slice(0, 8)}` : ''}
              </p>
            ))}
          </div>
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

function formatVerificationStatus(value: unknown): string {
  if (value === 'deferred') return '대기 중';
  if (value === 'pending') return '준비 중';
  if (value === 'running') return '검증 중';
  if (value === 'succeeded' || value === 'success') return '완료';
  if (value === 'failed' || value === 'error') return '실패';
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
  starting,
  polling,
  canCompare,
  showComparison,
  onCompare,
}: {
  recommendation: ApRecommendationResult | null;
  integratedCoverage: GridCoverageMetrics | null;
  sionnaCoverage: GridCoverageMetrics | null;
  calibratedSionnaCoverage: GridCoverageMetrics | null;
  runStatus: string | null;
  loadingIntegrated: boolean;
  starting: boolean;
  polling: boolean;
  canCompare: boolean;
  showComparison: boolean;
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
  const isBusy = starting || polling;

  return (
    <section className="rounded-xl border border-[#D8E3F0] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-foreground">정밀 검증 비교</h3>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            선택한 후보를 더 정밀한 전파 시뮬레이션으로 다시 확인하고 현재 통합맵과 비교합니다.
          </p>
        </div>
        {(isBusy || loadingIntegrated) && (
          <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
        )}
      </div>

      <div className="mt-3 flex gap-2">
        {!canCompare && (
          <div className="flex-1 rounded-lg border border-[#E5EAF2] bg-muted px-3 py-2.5 text-center text-sm font-medium text-muted-foreground">
            {isBusy ? (
              <span className="inline-flex items-center justify-center gap-1.5">
                <Loader2 className="h-4 w-4 animate-spin" />
                자동 검증 중
              </span>
            ) : (
              '자동 검증 결과 대기'
            )}
          </div>
        )}
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
            {showComparison ? '비교 닫기' : '비교하기'}
          </button>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <MetricTile label="빠른 예측 커버리지" value={formatCoveragePercent(predictionCoverage)} />
        <MetricTile label="정밀 예측 커버리지" value={formatCoveragePercent(sionnaRatio)} />
        <MetricTile label="보정 후 정밀 커버리지" value={formatCoveragePercent(calibratedSionnaRatio)} />
        <MetricTile label="현재 통합맵 커버리지" value={formatCoveragePercent(integratedRatio)} />
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
  baselineCoverage,
  verificationCoverage,
  hasBaselineHeatmap,
  hasVerificationHeatmap,
  simComparisonTab,
  onTabChange,
}: {
  baselineCoverage: GridCoverageMetrics | null;
  verificationCoverage: GridCoverageMetrics | null;
  hasBaselineHeatmap: boolean;
  hasVerificationHeatmap: boolean;
  simComparisonTab: 'baseline' | 'verification';
  onTabChange: (tab: 'baseline' | 'verification') => void;
}) {
  const bCov = baselineCoverage?.coverage_ratio ?? baselineCoverage?.coverage_score ?? null;
  const vCov = verificationCoverage?.coverage_ratio ?? verificationCoverage?.coverage_score ?? null;
  const covDelta = bCov != null && vCov != null ? vCov - bCov : null;
  const rssiDelta =
    baselineCoverage?.average_rssi_dbm != null && verificationCoverage?.average_rssi_dbm != null
      ? verificationCoverage.average_rssi_dbm - baselineCoverage.average_rssi_dbm
      : null;
  const botDelta =
    baselineCoverage?.bottom_10_percent_rssi_dbm != null &&
    verificationCoverage?.bottom_10_percent_rssi_dbm != null
      ? verificationCoverage.bottom_10_percent_rssi_dbm - baselineCoverage.bottom_10_percent_rssi_dbm
      : null;

  return (
    <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
      <h3 className="text-sm font-bold text-emerald-800">기존 시뮬 vs 추천 검증 비교</h3>
      <p className="mt-0.5 text-[11px] text-emerald-700">
        좌측 지도 탭으로 기존/추천 맵을 전환하세요.
      </p>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="text-[10px] font-semibold text-muted-foreground" />
        <div className="text-[10px] font-semibold text-slate-600">기존 시뮬</div>
        <div className="text-[10px] font-semibold text-blue-600">추천 검증</div>

        <div className="rounded-lg bg-white px-2 py-2 text-[10px] font-medium text-muted-foreground">커버리지</div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'baseline' ? 'bg-slate-100 text-slate-800' : 'bg-white text-slate-600')}>
          {formatCoveragePercent(bCov)}
        </div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'verification' ? 'bg-blue-100 text-blue-800' : 'bg-white text-blue-600')}>
          {formatCoveragePercent(vCov)}
        </div>

        <div className="rounded-lg bg-white px-2 py-2 text-[10px] font-medium text-muted-foreground">평균 신호</div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'baseline' ? 'bg-slate-100 text-slate-800' : 'bg-white text-slate-600')}>
          {formatDbm(baselineCoverage?.average_rssi_dbm)}
        </div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'verification' ? 'bg-blue-100 text-blue-800' : 'bg-white text-blue-600')}>
          {formatDbm(verificationCoverage?.average_rssi_dbm)}
        </div>

        <div className="rounded-lg bg-white px-2 py-2 text-[10px] font-medium text-muted-foreground">하위 10%</div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'baseline' ? 'bg-slate-100 text-slate-800' : 'bg-white text-slate-600')}>
          {formatDbm(baselineCoverage?.bottom_10_percent_rssi_dbm)}
        </div>
        <div className={cn('rounded-lg px-2 py-2 text-sm font-bold', simComparisonTab === 'verification' ? 'bg-blue-100 text-blue-800' : 'bg-white text-blue-600')}>
          {formatDbm(verificationCoverage?.bottom_10_percent_rssi_dbm)}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <DeltaTile label="커버리지 변화" delta={covDelta} isRatio />
        <DeltaTile label="평균 신호 변화" delta={rssiDelta} unit="dBm" />
        <DeltaTile label="하위 10% 변화" delta={botDelta} unit="dBm" />
      </div>

      {(hasBaselineHeatmap || hasVerificationHeatmap) && (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            disabled={!hasBaselineHeatmap}
            onClick={() => onTabChange('baseline')}
            className={cn(
              'flex-1 rounded-md border py-1.5 text-xs font-medium transition-colors',
              simComparisonTab === 'baseline'
                ? 'border-slate-400 bg-slate-700 text-white'
                : hasBaselineHeatmap
                  ? 'border-[#D8E3F0] bg-white text-slate-500 hover:bg-muted/60'
                  : 'cursor-not-allowed border-[#E5EAF2] bg-muted text-muted-foreground/50',
            )}
          >
            기존 시뮬 보기
          </button>
          <button
            type="button"
            disabled={!hasVerificationHeatmap}
            onClick={() => onTabChange('verification')}
            className={cn(
              'flex-1 rounded-md border py-1.5 text-xs font-medium transition-colors',
              simComparisonTab === 'verification'
                ? 'border-blue-500 bg-blue-600 text-white'
                : hasVerificationHeatmap
                  ? 'border-[#D8E3F0] bg-white text-slate-500 hover:bg-muted/60'
                  : 'cursor-not-allowed border-[#E5EAF2] bg-muted text-muted-foreground/50',
            )}
          >
            추천 검증 보기
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
    { border: 'border-emerald-300', badge: 'bg-emerald-500', selectedBorder: 'border-emerald-400 ring-1 ring-emerald-300' },
    { border: 'border-blue-300',    badge: 'bg-blue-500',    selectedBorder: 'border-blue-400 ring-1 ring-blue-300' },
    { border: 'border-orange-300',  badge: 'bg-orange-500',  selectedBorder: 'border-orange-400 ring-1 ring-orange-300' },
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
                {' '}· 정밀 평가{' '}
                <span className="font-semibold text-emerald-700">{rec.verified_score.toFixed(3)}</span>
              </>
            )}
          </p>
          {rec.verification_status && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              자동 검증 {formatVerificationStatus(rec.verification_status)}
            </p>
          )}
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
