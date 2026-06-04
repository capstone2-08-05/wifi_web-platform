import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  Loader2,
  Maximize2,
  Sliders,
  Sparkles,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { RSSI_HEATMAP_GRADIENT_CSS, dbmToHeatmapColor } from '@/lib/rssi-colormap';
import type {
  CalibrationEvaluationResponse,
  CalibrationRun,
  ParameterUpdate,
  SpaceType,
} from '@/types/calibration-run';

/** 공간 유형 select 표시명. SpaceType literal 과 1:1. */
const SPACE_TYPE_OPTIONS: { value: SpaceType; label: string }[] = [
  { value: 'unknown', label: '미지정' },
  { value: 'cafe', label: '카페' },
  { value: 'study_room', label: '스터디룸' },
  { value: 'classroom', label: '강의실' },
  { value: 'office', label: '오피스' },
  { value: 'residential', label: '원룸/주거' },
];

/** UI 전용 — 보정 실행 전 선행 조건 (API/로직 변경 없음). */
export type CalibrationGate =
  | 'no_measurement'
  | 'insufficient_points'
  | 'outside_sim_area'
  | 'no_simulation'
  | 'ready';

type CalibrationUiStatus = 'needs_data' | 'ready' | 'running' | 'complete' | 'failed';

interface Props {
  run: CalibrationRun | null;
  isPolling: boolean;
  isStarting: boolean;
  canCalibrate: boolean;
  /** 비활성 시 사용자에게 보여줄 사유 (측정 부족 / 시뮬 부족 등). */
  disabledReason?: string | null;
  /** 선행 조건 — 안내 박스 문구 분기용. */
  calibrationGate?: CalibrationGate;
  /** false 면 select 대신 현재 값만 표시 (상단 FloorSpaceTypeSelector 와 중복 방지). */
  showSpaceTypeField?: boolean;
  /** 사용자가 선택한 공간 유형 — Floor.space_type 과 동기화 권장. */
  spaceType: SpaceType;
  onSpaceTypeChange?: (next: SpaceType) => void;
  onCalibrate: () => void;
  showCalibrateButton?: boolean;
  /** false 면 "실측/진단으로 이동" 링크 숨김 (이미 해당 페이지일 때). */
  showMeasurementLink?: boolean;
  onAddReferenceMeasurement?: () => void;
  parameterUpdates: ParameterUpdate[];
  evaluation?: CalibrationEvaluationResponse | null;
  backgroundImageUrl?: string | null;
}

/**
 * 시뮬레이션 보정 카드 — 실측과 시뮬 비교로 예측 정확도를 높이는 보정 UI.
 */
export function CalibrationCard({
  run,
  isPolling,
  isStarting,
  canCalibrate,
  disabledReason,
  calibrationGate,
  spaceType,
  onSpaceTypeChange,
  onCalibrate,
  showCalibrateButton = true,
  showSpaceTypeField = true,
  showMeasurementLink = true,
  onAddReferenceMeasurement,
  parameterUpdates,
  evaluation,
  backgroundImageUrl,
}: Props) {
  const succeeded = run?.status === 'succeeded';
  const failed = run?.status === 'failed';
  const showProgress = isStarting || isPolling;
  const isComplete = succeeded || !!evaluation;

  const uiStatus: CalibrationUiStatus = showProgress
    ? 'running'
    : failed
      ? 'failed'
      : isComplete
        ? 'complete'
        : canCalibrate
          ? 'ready'
          : 'needs_data';

  const gate: CalibrationGate =
    calibrationGate ??
    (canCalibrate
      ? 'ready'
      : disabledReason?.includes('시뮬레이션')
        ? 'no_simulation'
        : disabledReason?.includes('측정점')
          ? 'insufficient_points'
          : 'no_measurement');

  return (
    <div className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-sm">
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Sliders className="h-4 w-4" />
          </span>
          <h3 className="text-sm font-semibold leading-tight text-foreground">시뮬레이션 보정</h3>
        </div>
        <CalibrationStatusBadge status={uiStatus} />
      </header>

      <div className="mt-3 space-y-1">
        <p className="text-xs leading-snug text-foreground/90">
          실측값을 기준으로 시뮬레이션 오차를 줄입니다.
        </p>
        <p className="text-[11px] leading-snug text-muted-foreground">
          {uiStatus === 'needs_data'
            ? '측정 데이터를 먼저 수집하면 보정값을 계산할 수 있습니다.'
            : '보정 후 시뮬레이션을 다시 실행하면 더 정확한 예측을 확인할 수 있습니다.'}
        </p>
      </div>

      {showSpaceTypeField ? (
        <SpaceTypeField
          spaceType={spaceType}
          onSpaceTypeChange={onSpaceTypeChange ?? (() => {})}
          disabled={showProgress}
        />
      ) : (
        <SpaceTypeReadonly spaceType={spaceType} />
      )}

      {uiStatus === 'needs_data' && (
        <CalibrationGateNotice
          gate={gate}
          disabledReason={disabledReason}
          showMeasurementLink={showMeasurementLink}
        />
      )}

      {uiStatus === 'running' && (
        <div className="mt-3 flex items-center gap-2.5 rounded-xl border border-primary/15 bg-primary/5 px-3 py-2.5">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
          <div>
            <p className="text-xs font-medium text-foreground">
              {isStarting ? '보정을 시작하는 중…' : '보정 중…'}
            </p>
            <p className="text-[11px] text-muted-foreground">잠시만 기다려주세요.</p>
          </div>
        </div>
      )}

      {uiStatus === 'complete' && run && (
        <CalibrationResult run={run} parameterUpdates={parameterUpdates} evaluation={evaluation} />
      )}

      {uiStatus === 'failed' && (
        <div className="mt-3 flex gap-2.5 rounded-xl border border-destructive/20 bg-destructive/5 px-3 py-2.5">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p className="text-[11px] leading-relaxed text-destructive">
            보정에 실패했습니다. 측정 데이터가 충분한지 확인해주세요.
          </p>
        </div>
      )}

      {uiStatus === 'complete' && !run && evaluation && (
        <div className="mt-3 flex gap-2.5 rounded-xl border border-emerald-200/80 bg-emerald-50/80 px-3 py-2.5">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
          <p className="text-[11px] leading-relaxed text-emerald-900">
            보정된 값으로 시뮬레이션을 다시 실행해보세요.
          </p>
        </div>
      )}

      <CalibrationEvaluationPanel
        evaluation={evaluation ?? extractEvaluationResponse(run)}
        backgroundImageUrl={backgroundImageUrl}
        onAddReferenceMeasurement={onAddReferenceMeasurement}
      />

      {showCalibrateButton && (
        <div className="mt-3 space-y-2">
          {uiStatus === 'complete' && (
            <p className="text-[11px] leading-snug text-muted-foreground">
              보정 결과는 다음 시뮬레이션 실행에 반영됩니다.
            </p>
          )}
          <button
            type="button"
            onClick={onCalibrate}
            disabled={!canCalibrate || showProgress}
            className={cn(
              'inline-flex w-full items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-xs font-semibold transition-colors',
              uiStatus === 'complete'
                ? 'border border-slate-200 bg-white text-foreground hover:bg-slate-50 disabled:opacity-60'
                : 'bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50',
            )}
          >
            {showProgress ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                보정 중…
              </>
            ) : uiStatus === 'complete' ? (
              <>
                <Sparkles className="h-3.5 w-3.5" />
                다시 보정하기
              </>
            ) : (
              <>
                <Sliders className="h-3.5 w-3.5" />
                보정 실행하기
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}

function CalibrationStatusBadge({ status }: { status: CalibrationUiStatus }) {
  const config: Record<
    CalibrationUiStatus,
    { label: string; className: string }
  > = {
    needs_data: {
      label: '측정 필요',
      className: 'border-sky-300 bg-sky-100 text-sky-700',
    },
    ready: {
      label: '보정 가능',
      className: 'border-primary/20 bg-primary/5 text-primary',
    },
    running: {
      label: '보정 중',
      className: 'border-primary/20 bg-primary/5 text-primary',
    },
    complete: {
      label: '보정 완료',
      className: 'border-emerald-200/80 bg-emerald-50 text-emerald-800',
    },
    failed: {
      label: '보정 실패',
      className: 'border-destructive/20 bg-destructive/5 text-destructive',
    },
  };
  const { label, className } = config[status];
  return (
    <span
      className={cn(
        'shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold leading-snug',
        className,
      )}
    >
      {label}
    </span>
  );
}

function SpaceTypeReadonly({ spaceType }: { spaceType: SpaceType }) {
  const label =
    SPACE_TYPE_OPTIONS.find((o) => o.value === spaceType)?.label ?? '미지정';
  return (
    <div className="mt-3">
      <span className="text-[11px] font-medium text-foreground/80">공간 유형</span>
      <div
        className={cn(
          'mt-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2',
          'text-xs font-medium text-foreground shadow-sm',
        )}
      >
        {label}
      </div>
    </div>
  );
}

function SpaceTypeField({
  spaceType,
  onSpaceTypeChange,
  disabled,
}: {
  spaceType: SpaceType;
  onSpaceTypeChange: (next: SpaceType) => void;
  disabled: boolean;
}) {
  return (
    <div className="mt-3">
      <label className="block">
        <span className="text-[11px] font-medium text-foreground/80">공간 유형</span>
        <span className="mt-0.5 block text-[10px] text-muted-foreground">
          초기 보정값을 정하는 기준입니다.
        </span>
        <div className="relative mt-1.5">
          <select
            value={spaceType}
            onChange={(e) => onSpaceTypeChange(e.target.value as SpaceType)}
            disabled={disabled}
            className={cn(
              'h-9 w-full appearance-none rounded-xl border border-slate-200 bg-white',
              'px-3 pr-9 text-xs font-medium text-foreground shadow-sm',
              'focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/20',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
          >
            {SPACE_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown
            className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
        </div>
      </label>
    </div>
  );
}

function CalibrationGateNotice({
  gate,
  disabledReason,
  showMeasurementLink,
}: {
  gate: CalibrationGate;
  disabledReason?: string | null;
  showMeasurementLink: boolean;
}) {
  if (gate === 'no_simulation') {
    return (
      <div className="mt-3 flex gap-2.5 rounded-xl border border-slate-200/80 bg-slate-50 px-3 py-2.5">
        <ClipboardList className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium text-foreground">시뮬레이션 결과가 필요합니다</p>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            시뮬레이션 페이지에서 한 번 실행한 뒤, 다시 보정을 시도해주세요.
          </p>
          <Link
            to="/simulation"
            className="inline-flex items-center text-[11px] font-semibold text-primary hover:underline"
          >
            시뮬레이션으로 이동
          </Link>
        </div>
      </div>
    );
  }

  if (gate === 'insufficient_points') {
    return (
      <div className="mt-3 flex gap-2.5 rounded-xl border border-slate-200/80 bg-slate-50 px-3 py-2.5">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium text-foreground">측정점이 더 필요합니다</p>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            {disabledReason ??
              '도면 전반에 골고루 측정하면 더 안정적인 보정값을 얻을 수 있습니다.'}
          </p>
        </div>
      </div>
    );
  }

  if (gate === 'outside_sim_area') {
    return (
      <div className="mt-3 flex gap-2.5 rounded-xl border border-amber-200/80 bg-amber-50 px-3 py-2.5">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium text-foreground">측정 위치가 도면 밖입니다</p>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            {disabledReason ??
              '모바일 앱에서 도면 벽 안쪽의 시작 위치를 지정하고, 건물 안을 따라 다시 측정해주세요.'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 flex gap-2.5 rounded-xl border border-slate-200/80 bg-slate-50 px-3 py-2.5">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
      <div className="min-w-0 space-y-1">
        <p className="text-xs font-medium text-foreground">측정 데이터가 필요합니다</p>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          실측/진단에서 측정을 완료하면 보정을 실행할 수 있습니다.
        </p>
        {showMeasurementLink && (
          <Link
            to="/measurement"
            className="inline-flex items-center text-[11px] font-semibold text-primary hover:underline"
          >
            실측/진단으로 이동
          </Link>
        )}
      </div>
    </div>
  );
}

function CalibrationResult({
  run,
  parameterUpdates,
  evaluation,
}: {
  run: CalibrationRun;
  parameterUpdates: ParameterUpdate[];
  evaluation?: CalibrationEvaluationResponse | null;
}) {
  const metrics = parseCalibrationMetrics(evaluation?.metrics ?? run.error_metrics_json);
  const feedbackMessage = typeof run.error_metrics_json?.['feedback_message'] === 'string'
    ? (run.error_metrics_json['feedback_message'] as string)
    : null;
  return (
    <div className="mt-3 space-y-2">
      <div className="rounded-lg border bg-muted/40 p-3">
        <p className="text-[11px] font-semibold text-muted-foreground">보정 결과</p>
        <div className="mt-1.5 grid grid-cols-2 gap-2">
          <MetricCell label="RMSE" value={metrics.rmse} unit="dB" />
          <MetricCell label="MAE" value={metrics.mae} unit="dB" />
        </div>
      </div>
      {feedbackMessage && (
        <div className="rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-[11px] leading-relaxed text-foreground/80">
          {feedbackMessage}
        </div>
      )}
      <div className="flex items-center justify-between gap-2 rounded-md border bg-background px-3 py-2 text-xs">
        <span className="text-muted-foreground">변경된 파라미터</span>
        <span className="font-semibold tabular-nums">{parameterUpdates.length} 개</span>
      </div>
      {parameterUpdates.length > 0 && (
        <details className="rounded-md border bg-background text-xs">
          <summary className="cursor-pointer px-3 py-2 font-medium hover:bg-accent">
            변경 이력 보기
          </summary>
          <ul className="max-h-48 divide-y overflow-y-auto px-3 pb-2 text-[11px]">
            {parameterUpdates.map((u) => (
              <li key={u.id} className="py-2">
                <p className="font-medium">
                  {u.target_type} · {u.param_name}
                </p>
                <p className="text-muted-foreground">
                  <span className="line-through">{formatValue(u.old_value_json)}</span>
                  {' → '}
                  <span className="font-medium text-foreground">
                    {formatValue(u.new_value_json)}
                  </span>
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-[11px] text-muted-foreground">
        보정 결과는 다음 시뮬레이션 실행 시 자동으로 반영됩니다.
      </p>
    </div>
  );
}

function CalibrationEvaluationPanel({
  evaluation,
  backgroundImageUrl,
  onAddReferenceMeasurement,
}: {
  evaluation: CalibrationEvaluationResponse | null;
  backgroundImageUrl?: string | null;
  onAddReferenceMeasurement?: () => void;
}) {
  const [detailOpen, setDetailOpen] = useState(false);
  if (!evaluation) return null;
  const maps = [
    evaluation.maps.baseline,
    evaluation.maps.calibrated,
    evaluation.maps.measured_reference,
  ].filter((map): map is NonNullable<typeof map> => map != null);
  const m = evaluation.metrics;
  const comparisonPoints = evaluation.points.evaluation ?? evaluation.points.validation;
  const comparisonLabel =
    evaluation.evaluation?.split &&
    typeof evaluation.evaluation.split === 'object' &&
    'metric_point_source' in evaluation.evaluation.split
      ? String((evaluation.evaluation.split as Record<string, unknown>).metric_point_source)
      : 'reference';
  const comparisonLabelKo = formatComparisonPointSource(comparisonLabel);
  const frequencyText = formatFrequencyCheck(evaluation);
  const fmt = (v: unknown, digits = 1) =>
    typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '--';
  return (
    <section className="mt-3 space-y-3 rounded-lg border bg-muted/30 p-3">
      <div>
        <p className="text-[11px] font-semibold text-foreground">참조 비교 기준</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          지표는 {comparisonLabelKo} 포인트를 실측 비교 데이터로 사용합니다. 참조맵은 측정값을
          보간한 결과이며, 절대적인 정답(ground truth)이 아닙니다.
        </p>
        {frequencyText && (
          <p className="mt-1 rounded-md border bg-background px-2 py-1 text-[10px] leading-relaxed text-muted-foreground">
            {frequencyText}
          </p>
        )}
      </div>

      <button
        type="button"
        onClick={() => setDetailOpen(true)}
        className="inline-flex w-full items-center justify-center gap-1 rounded-md border bg-background px-2 py-1.5 text-[11px] font-medium hover:bg-accent"
      >
        <Maximize2 className="h-3 w-3" />
        자세히 보기
      </button>
      {onAddReferenceMeasurement && (
        <button
          type="button"
          onClick={onAddReferenceMeasurement}
          className="inline-flex w-full items-center justify-center rounded-md bg-primary px-2 py-1.5 text-[11px] font-medium text-primary-foreground hover:bg-primary/90"
        >
          정답(참조) 데이터 추가 측정
        </button>
      )}

      <div className="overflow-x-auto">
        <div className="grid min-w-[620px] grid-cols-3 gap-2">
          {maps.map((map) => (
            <MiniRssiMap
              key={map.label}
              map={map}
              colorScale={evaluation.color_scale}
              calibrationPoints={evaluation.points.calibration}
              validationPoints={comparisonPoints}
              backgroundImageUrl={backgroundImageUrl}
            />
          ))}
        </div>
      </div>

      <div className="rounded-md border bg-background p-2 text-[11px]">
        <div className="grid grid-cols-4 gap-2 font-semibold text-muted-foreground">
          <span>지표</span>
          <span>보정 전</span>
          <span>보정 후</span>
          <span>개선</span>
        </div>
        <MetricRow
          label="MAE"
          before={fmt(m.baseline_mae_db)}
          after={fmt(m.calibrated_mae_db)}
          improvement={`${fmt(m.mae_improvement_db)} dB`}
        />
        <MetricRow
          label="RMSE"
          before={fmt(m.baseline_rmse_db)}
          after={fmt(m.calibrated_rmse_db)}
          improvement={`${fmt(m.rmse_improvement_db)} dB`}
        />
        <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
          MAE는 평균 오차입니다. RMSE는 큰 오차를 더 크게 반영해서, 특정 위치에서 예측이 많이 틀어졌는지 보기 좋습니다.
        </p>
      </div>

      <details className="rounded-md border bg-background text-[11px]">
        <summary className="cursor-pointer px-3 py-2 font-medium">
          참조 비교 오차 ({comparisonPoints.length}개)
        </summary>
        <div className="max-h-48 overflow-auto">
          <table className="w-full min-w-[520px] text-left">
            <thead className="sticky top-0 bg-background text-muted-foreground">
              <tr>
                <th className="px-2 py-1">포인트</th>
                <th className="px-2 py-1">실측</th>
                <th className="px-2 py-1">보정 전</th>
                <th className="px-2 py-1">보정 후</th>
                <th className="px-2 py-1">보정 전 오차</th>
                <th className="px-2 py-1">보정 후 오차</th>
              </tr>
            </thead>
            <tbody>
              {comparisonPoints.map((p, idx) => (
                <tr key={p.point_id} className="border-t">
                  <td className="px-2 py-1">P{String(idx + 1).padStart(2, '0')}</td>
                  <td className="px-2 py-1">{fmt(p.rssi_dbm)} dBm</td>
                  <td className="px-2 py-1">{fmt(p.baseline_pred_dbm)} dBm</td>
                  <td className="px-2 py-1">{fmt(p.calibrated_pred_dbm)} dBm</td>
                  <td className="px-2 py-1">{fmt(p.baseline_error_db)} dB</td>
                  <td className="px-2 py-1">{fmt(p.calibrated_error_db)} dB</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <CalibrationEvaluationDetailModal
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        evaluation={evaluation}
        backgroundImageUrl={backgroundImageUrl}
        onAddReferenceMeasurement={onAddReferenceMeasurement}
      />
    </section>
  );
}

function CalibrationEvaluationDetailModal({
  open,
  onClose,
  evaluation,
  backgroundImageUrl,
  onAddReferenceMeasurement,
}: {
  open: boolean;
  onClose: () => void;
  evaluation: CalibrationEvaluationResponse;
  backgroundImageUrl?: string | null;
  onAddReferenceMeasurement?: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const maps = [
    evaluation.maps.baseline,
    evaluation.maps.calibrated,
    evaluation.maps.measured_reference,
  ].filter((map): map is NonNullable<typeof map> => map != null);
  const m = evaluation.metrics;
  const comparisonPoints = evaluation.points.evaluation ?? evaluation.points.validation;
  const comparisonLabel =
    evaluation.evaluation?.split &&
    typeof evaluation.evaluation.split === 'object' &&
    'metric_point_source' in evaluation.evaluation.split
      ? String((evaluation.evaluation.split as Record<string, unknown>).metric_point_source)
      : 'reference';
  const comparisonLabelKo = formatComparisonPointSource(comparisonLabel);
  const frequencyText = formatFrequencyCheck(evaluation);
  const fmt = (v: unknown, digits = 1) =>
    typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '--';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-7xl flex-col overflow-hidden rounded-xl border bg-background shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-3 border-b px-5 py-3">
          <div>
            <h2 className="text-base font-semibold">3-way RSSI 맵 비교</h2>
            <p className="text-xs text-muted-foreground">
              동일 도면·격자·범위·색상 스케일 기준. 지표는 {comparisonLabelKo} 포인트를 실측
              비교 데이터로 사용합니다.
            </p>
            {frequencyText && (
              <p className="mt-1 text-xs text-muted-foreground">{frequencyText}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {onAddReferenceMeasurement && (
              <button
                type="button"
                onClick={() => {
                  onAddReferenceMeasurement();
                  onClose();
                }}
                className="rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90"
              >
                정답(참조) 데이터 추가 측정
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border hover:bg-accent"
              aria-label="닫기"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-auto p-5">
          <div className="grid gap-4 xl:grid-cols-3">
            {maps.map((map) => (
              <MiniRssiMap
                key={map.label}
                map={map}
                colorScale={evaluation.color_scale}
                calibrationPoints={evaluation.points.calibration}
                validationPoints={comparisonPoints}
                backgroundImageUrl={backgroundImageUrl}
                size="large"
                errorMode={map.label.toLowerCase().includes('baseline') ? 'baseline' : map.label.toLowerCase().includes('calibrated') ? 'calibrated' : undefined}
              />
            ))}
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[24rem_1fr]">
            <div className="rounded-lg border bg-muted/20 p-4 text-sm">
              <p className="font-semibold">비교 지표</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                MAE는 각 측정 지점의 평균 오차입니다. RMSE는 큰 오차를 더 크게 반영해서, 보정 후에도 크게 틀린 구간이 남아 있는지 보여줍니다.
              </p>
              <div className="mt-3 grid grid-cols-4 gap-2 text-xs font-semibold text-muted-foreground">
                <span>지표</span>
                <span>보정 전</span>
                <span>보정 후</span>
                <span>개선</span>
              </div>
              <MetricRow
                label="MAE"
                before={fmt(m.baseline_mae_db)}
                after={fmt(m.calibrated_mae_db)}
                improvement={`${fmt(m.mae_improvement_db)} dB`}
              />
              <MetricRow
                label="RMSE"
                before={fmt(m.baseline_rmse_db)}
                after={fmt(m.calibrated_rmse_db)}
                improvement={`${fmt(m.rmse_improvement_db)} dB`}
              />
              <div className="mt-4 flex flex-wrap gap-3 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#0f766e]" />
                  보정용
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="h-0 w-0 border-x-[5px] border-b-[9px] border-x-transparent border-b-[#dc2626]" />
                  비교용
                </span>
              </div>
            </div>

            <div className="rounded-lg border bg-background p-4 text-xs">
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="font-semibold">포인트별 오차</p>
                <p className="text-muted-foreground">보정 전 vs 보정 후 (dB)</p>
              </div>
              <ErrorBarChart points={comparisonPoints} />
            </div>
          </div>

          <div className="mt-4 rounded-lg border bg-background text-xs">
              <div className="border-b px-4 py-3 font-semibold">
                참조 비교 오차 ({comparisonPoints.length}개)
              </div>
              <div className="max-h-72 overflow-auto">
                <table className="w-full min-w-[640px] text-left">
                  <thead className="sticky top-0 bg-background text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">포인트</th>
                      <th className="px-3 py-2">실측</th>
                      <th className="px-3 py-2">보정 전 예측</th>
                      <th className="px-3 py-2">보정 후 예측</th>
                      <th className="px-3 py-2">보정 전 오차</th>
                      <th className="px-3 py-2">보정 후 오차</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparisonPoints.map((p, idx) => (
                      <tr key={p.point_id} className="border-t">
                        <td className="px-3 py-2">P{String(idx + 1).padStart(2, '0')}</td>
                        <td className="px-3 py-2">{fmt(p.rssi_dbm)} dBm</td>
                        <td className="px-3 py-2">{fmt(p.baseline_pred_dbm)} dBm</td>
                        <td className="px-3 py-2">{fmt(p.calibrated_pred_dbm)} dBm</td>
                        <td className="px-3 py-2">{fmt(p.baseline_error_db)} dB</td>
                        <td className="px-3 py-2">{fmt(p.calibrated_error_db)} dB</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MetricRow({
  label,
  before,
  after,
  improvement,
}: {
  label: string;
  before: string;
  after: string;
  improvement: string;
}) {
  return (
    <div className="mt-1 grid grid-cols-4 gap-2 tabular-nums">
      <span className="font-medium">{label}</span>
      <span>{before} dB</span>
      <span>{after} dB</span>
      <span>{improvement}</span>
    </div>
  );
}

function MiniRssiMap({
  map,
  colorScale,
  calibrationPoints,
  validationPoints,
  backgroundImageUrl,
  size = 'compact',
  errorMode,
}: {
  map: CalibrationEvaluationResponse['maps']['baseline'];
  colorScale: { min_dbm: number; max_dbm: number };
  calibrationPoints: CalibrationEvaluationResponse['points']['calibration'];
  validationPoints: CalibrationEvaluationResponse['points']['validation'];
  backgroundImageUrl?: string | null;
  size?: 'compact' | 'large';
  errorMode?: 'baseline' | 'calibrated';
}) {
  const bounds = map.bounds_m;
  const w = Math.max(bounds.max_x - bounds.min_x, 1);
  const h = Math.max(bounds.max_y - bounds.min_y, 1);
  const rows = map.values_dbm.length;
  const cols = map.values_dbm[0]?.length ?? 0;
  return (
    <div className={size === 'large' ? 'rounded-lg border bg-background p-3' : 'rounded-md border bg-background p-2'}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className={size === 'large' ? 'truncate text-sm font-semibold' : 'truncate text-[11px] font-semibold'}>
          {formatEvaluationMapLabel(map.label)}
        </p>
        {size === 'large' && (
          <span className="text-[11px] text-muted-foreground">
            {colorScale.min_dbm} ~ {colorScale.max_dbm} dBm
          </span>
        )}
      </div>
      <svg viewBox={`${bounds.min_x} ${bounds.min_y} ${w} ${h}`} className={size === 'large' ? 'aspect-[4/3] w-full overflow-hidden rounded-md border bg-white' : 'aspect-[4/3] w-full overflow-hidden rounded border bg-white'}>
        {backgroundImageUrl && (
          <image
            href={backgroundImageUrl}
            x={bounds.min_x}
            y={bounds.min_y}
            width={w}
            height={h}
            preserveAspectRatio="none"
            opacity="0.28"
          />
        )}
        {map.values_dbm.map((row, r) =>
          row.map((value, c) => {
            const x = bounds.min_x + (w * c) / Math.max(cols, 1);
            const y = bounds.min_y + (h * r) / Math.max(rows, 1);
            return (
              <rect
                key={`${r}-${c}`}
                x={x}
                y={y}
                width={w / Math.max(cols, 1)}
                height={h / Math.max(rows, 1)}
                fill={rssiColor(value, colorScale.min_dbm, colorScale.max_dbm)}
                opacity="0.72"
              />
            );
          }),
        )}
        {calibrationPoints.map((p, idx) => (
          <circle
            key={`c-${p.point_id}`}
            cx={p.x_m}
            cy={p.y_m}
            r={w * 0.012}
            fill="#0f766e"
            stroke="white"
            strokeWidth={w * 0.004}
          >
            <title>{pointTooltip(p, idx, 'calibration')}</title>
          </circle>
        ))}
        {size === 'large' &&
          errorMode &&
          validationPoints.map((p, idx) => {
            const err = errorMode === 'baseline' ? p.baseline_error_db : p.calibrated_error_db;
            if (typeof err !== 'number' || !Number.isFinite(err)) return null;
            const radius = w * (0.01 + Math.min(err, 18) / 18 * 0.028);
            return (
              <circle
                key={`err-${errorMode}-${p.point_id}`}
                cx={p.x_m}
                cy={p.y_m}
                r={radius}
                fill={errorColor(err)}
                opacity="0.28"
                stroke={errorColor(err)}
                strokeWidth={w * 0.003}
              >
                <title>{pointTooltip(p, idx, 'comparison')}</title>
              </circle>
            );
          })}
        {validationPoints.map((p, idx) => (
          <path
            key={`v-${p.point_id}`}
            d={`M ${p.x_m} ${p.y_m - w * 0.014} L ${p.x_m - w * 0.014} ${p.y_m + w * 0.014} L ${p.x_m + w * 0.014} ${p.y_m + w * 0.014} Z`}
            fill="#dc2626"
            stroke="white"
            strokeWidth={w * 0.004}
          >
            <title>{pointTooltip(p, idx, 'comparison')}</title>
          </path>
        ))}
      </svg>
      {size === 'large' && <RssiScaleBar min={colorScale.min_dbm} max={colorScale.max_dbm} />}
    </div>
  );
}

function pointTooltip(
  point: CalibrationEvaluationResponse['points']['validation'][number],
  index: number,
  kind: 'calibration' | 'comparison',
): string {
  const pointName = `P${String(index + 1).padStart(2, '0')}`;
  const purpose = kind === 'calibration' ? '보정용' : '비교용';
  const lines = [
    `${pointName} (${purpose})`,
    `실측 RSSI: ${formatTooltipNumber(point.rssi_dbm, 'dBm')}`,
    `보정 전 예측: ${formatTooltipNumber(point.baseline_pred_dbm, 'dBm')}`,
    `보정 후 예측: ${formatTooltipNumber(point.calibrated_pred_dbm, 'dBm')}`,
    `보정 전 오차: ${formatTooltipNumber(point.baseline_error_db, 'dB')}`,
    `보정 후 오차: ${formatTooltipNumber(point.calibrated_error_db, 'dB')}`,
    `위치: ${formatTooltipNumber(point.x_m, 'm')}, ${formatTooltipNumber(point.y_m, 'm')}`,
  ];
  return lines.join('\n');
}

function formatTooltipNumber(value: unknown, unit: string): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toFixed(1)} ${unit}`
    : '--';
}

function RssiScaleBar({ min, max }: { min: number; max: number }) {
  return (
    <div className="mt-2">
      <div
        className="h-2 rounded-full"
        style={{ background: RSSI_HEATMAP_GRADIENT_CSS }}
      />
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>{min} dBm</span>
        <span>{max} dBm</span>
      </div>
    </div>
  );
}

function ErrorBarChart({
  points,
}: {
  points: CalibrationEvaluationResponse['points']['validation'];
}) {
  const visible = points.slice(0, 24);
  const maxErr = Math.max(
    1,
    ...visible.flatMap((p) => [
      typeof p.baseline_error_db === 'number' ? p.baseline_error_db : 0,
      typeof p.calibrated_error_db === 'number' ? p.calibrated_error_db : 0,
    ]),
  );
  if (visible.length === 0) {
    return <p className="text-muted-foreground">비교할 포인트가 없습니다.</p>;
  }
  return (
    <div className="max-h-72 space-y-2 overflow-auto pr-1">
      {visible.map((p, idx) => {
        const before = typeof p.baseline_error_db === 'number' ? p.baseline_error_db : 0;
        const after = typeof p.calibrated_error_db === 'number' ? p.calibrated_error_db : 0;
        return (
          <div key={p.point_id} className="grid grid-cols-[2.5rem_1fr_3rem] items-center gap-2">
            <span className="font-medium text-muted-foreground">P{String(idx + 1).padStart(2, '0')}</span>
            <div className="space-y-1">
              <div className="h-2 rounded-full bg-muted">
                <div
                  className="h-2 rounded-full bg-rose-500"
                  style={{ width: `${Math.max(2, (before / maxErr) * 100)}%` }}
                />
              </div>
              <div className="h-2 rounded-full bg-muted">
                <div
                  className="h-2 rounded-full bg-emerald-500"
                  style={{ width: `${Math.max(2, (after / maxErr) * 100)}%` }}
                />
              </div>
            </div>
            <span className="text-right tabular-nums">
              {after.toFixed(1)}
            </span>
          </div>
        );
      })}
      {points.length > visible.length && (
        <p className="pt-1 text-[11px] text-muted-foreground">
          {points.length}개 중 상위 {visible.length}개만 표시합니다. 전체 값은 아래 표에서 확인하세요.
        </p>
      )}
      <div className="flex gap-3 pt-1 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1"><span className="h-2 w-4 rounded bg-rose-500" /> 보정 전</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-4 rounded bg-emerald-500" /> 보정 후</span>
      </div>
    </div>
  );
}

function errorColor(errorDb: number): string {
  if (errorDb <= 3) return '#10b981';
  if (errorDb <= 7) return '#f59e0b';
  return '#ef4444';
}

function formatComparisonPointSource(source: string): string {
  switch (source.toLowerCase()) {
    case 'reference':
      return '참조';
    case 'validation':
      return '검증';
    case 'calibration':
      return '보정';
    case 'evaluation':
      return '평가';
    default:
      return source;
  }
}

function formatEvaluationMapLabel(label: string): string {
  const lower = label.toLowerCase();
  if (lower.includes('baseline')) return '보정 전 시뮬레이션';
  if (lower.includes('calibrated')) return '보정 후 시뮬레이션';
  if (lower.includes('measured reference') || lower.includes('reference map')) return '실측 참조맵';
  return label;
}

function formatFrequencyCheck(evaluation: CalibrationEvaluationResponse): string | null {
  const measurement = evaluation.evaluation?.['measurement_frequency'];
  const physical = evaluation.evaluation?.['rf_physical'];
  if (!measurement || typeof measurement !== 'object') return null;
  const m = measurement as Record<string, unknown>;
  if (m.available !== true) return '실측 frequency_mhz가 없어 2.4GHz/5GHz 여부를 확인할 수 없습니다.';
  const p = physical && typeof physical === 'object' ? (physical as Record<string, unknown>) : {};
  const measuredBand = String(m.dominant_band ?? 'unknown');
  const avgMhz = typeof m.avg_frequency_mhz === 'number' ? m.avg_frequency_mhz : null;
  const rfGhz = typeof p.frequency_ghz === 'number' ? p.frequency_ghz : null;
  const txPower = typeof p.tx_power_dbm === 'number' ? p.tx_power_dbm : null;
  const measured = avgMhz != null ? `${measuredBand} (${(avgMhz / 1000).toFixed(2)}GHz avg)` : measuredBand;
  const simulated = rfGhz != null ? `${rfGhz.toFixed(2)}GHz` : 'unknown GHz';
  const tx = txPower != null ? `, Tx ${txPower.toFixed(1)}dBm` : '';
  return `실측 주파수: ${measured} / RF 시뮬레이션: ${simulated}${tx}`;
}

function rssiColor(value: number, min: number, max: number): string {
  return dbmToHeatmapColor(value, min, max);
}

function extractEvaluationResponse(run: CalibrationRun | null): CalibrationEvaluationResponse | null {
  const value = run?.error_metrics_json?.['evaluation_response'];
  if (!value || typeof value !== 'object') return null;
  return value as CalibrationEvaluationResponse;
}

function MetricCell({
  label,
  value,
  unit,
}: {
  label: string;
  value: number | null;
  unit: string;
}) {
  return (
    <div className="rounded-md bg-background px-2.5 py-1.5 text-center">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold tabular-nums">
        {value == null ? '—' : value.toFixed(2)}
        {value != null && <span className="ml-0.5 text-[10px] text-muted-foreground">{unit}</span>}
      </p>
    </div>
  );
}

function parseCalibrationMetrics(m: Record<string, unknown> | null | undefined): {
  rmse: number | null;
  mae: number | null;
} {
  if (!m) return { rmse: null, mae: null };
  const toNum = (k: string): number | null => {
    const v = m[k];
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string' && v.trim() && Number.isFinite(Number(v))) return Number(v);
    return null;
  };
  return {
    rmse:
      toNum('calibrated_rmse_db') ??
      toNum('rmse_dbm') ??
      toNum('rmse') ??
      toNum('rmse_after'),
    mae:
      toNum('calibrated_mae_db') ??
      toNum('mae_dbm') ??
      toNum('mae') ??
      toNum('mae_after'),
  };
}

function formatValue(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'number') return v.toFixed(3);
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}
