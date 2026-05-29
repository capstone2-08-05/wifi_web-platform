import { useEffect, useState } from 'react';
import { Loader2, Maximize2, Sliders, X } from 'lucide-react';
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

interface Props {
  run: CalibrationRun | null;
  isPolling: boolean;
  isStarting: boolean;
  canCalibrate: boolean;
  /** 비활성 시 사용자에게 보여줄 사유 (측정 부족 / 시뮬 부족 등). */
  disabledReason?: string | null;
  /** 사용자가 선택한 공간 유형 — calibration 의 soft prior 로 backend 에 전달. */
  spaceType: SpaceType;
  onSpaceTypeChange: (next: SpaceType) => void;
  onCalibrate: () => void;
  parameterUpdates: ParameterUpdate[];
  evaluation?: CalibrationEvaluationResponse | null;
  backgroundImageUrl?: string | null;
}

/**
 * 시뮬레이션 보정 카드 — 측정 vs 시뮬 비교로 시뮬 파라미터(벽 흡수율 등) 자동 보정.
 * 시뮬레이션 페이지의 우측 사이드바에 노출. 보정 결과는 다음 시뮬 실행 시 자동 반영.
 */
export function CalibrationCard({
  run,
  isPolling,
  isStarting,
  canCalibrate,
  disabledReason,
  spaceType,
  onSpaceTypeChange,
  onCalibrate,
  parameterUpdates,
  evaluation,
  backgroundImageUrl,
}: Props) {
  const succeeded = run?.status === 'succeeded';
  const failed = run?.status === 'failed';
  const showProgress = isStarting || isPolling;

  return (
    <div className="rounded-2xl border bg-background p-5 shadow-sm">
      <header className="mb-3 flex items-center gap-2">
        <Sliders className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-bold">시뮬레이션 보정</h3>
      </header>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        실측과 시뮬레이션 결과를 비교해서 벽 흡수율 등 시뮬 파라미터를 자동 보정합니다.
        보정 후 시뮬레이션을 다시 실행하면 더 정확한 예측을 얻을 수 있습니다.
      </p>

      {/* 공간 유형 select — calibration BO 의 soft prior. 잘못 골라도 BO 가 어느 정도 보정. */}
      <label className="mt-3 block">
        <span className="text-[11px] font-medium text-muted-foreground">공간 유형</span>
        <select
          value={spaceType}
          onChange={(e) => onSpaceTypeChange(e.target.value as SpaceType)}
          disabled={showProgress}
          className="mt-1 block w-full rounded-md border bg-background px-2.5 py-1.5 text-xs font-medium shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50"
        >
          {SPACE_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[10px] leading-relaxed text-muted-foreground">
          공간 유형은 보정의 초기 가정만 좁혀줍니다. 실제 결과는 측정 RSSI 기반으로 결정됩니다.
        </span>
      </label>

      {showProgress ? (
        <div className="mt-3 flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2.5 text-xs">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
          <span className="font-medium">
            {isStarting ? '보정 요청 중…' : '보정 진행 중…'}
          </span>
        </div>
      ) : succeeded && run ? (
        <CalibrationResult run={run} parameterUpdates={parameterUpdates} />
      ) : failed ? (
        <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[11px] text-destructive">
          보정에 실패했습니다. 측정 데이터가 충분한지 확인해주세요.
        </p>
      ) : null}

      <CalibrationEvaluationPanel
        evaluation={evaluation ?? extractEvaluationResponse(run)}
        backgroundImageUrl={backgroundImageUrl}
      />

      <button
        type="button"
        onClick={onCalibrate}
        disabled={!canCalibrate || showProgress}
        className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        <Sliders className="h-3.5 w-3.5" />
        {succeeded ? '다시 보정 실행' : '보정 실행'}
      </button>
      {!canCalibrate && disabledReason && (
        <p className="mt-2 text-[11px] text-muted-foreground">{disabledReason}</p>
      )}
    </div>
  );
}

function CalibrationResult({
  run,
  parameterUpdates,
}: {
  run: CalibrationRun;
  parameterUpdates: ParameterUpdate[];
}) {
  const metrics = parseCalibrationMetrics(run.error_metrics_json);
  const feedbackMessage = typeof run.error_metrics_json?.['feedback_message'] === 'string'
    ? (run.error_metrics_json['feedback_message'] as string)
    : null;
  return (
    <div className="mt-3 space-y-2">
      <div className="rounded-lg border bg-muted/40 p-3">
        <p className="text-[11px] font-semibold text-muted-foreground">보정 결과</p>
        <div className="mt-1.5 grid grid-cols-2 gap-2">
          <MetricCell label="RMSE" value={metrics.rmse} unit="dBm" />
          <MetricCell label="MAE" value={metrics.mae} unit="dBm" />
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
}: {
  evaluation: CalibrationEvaluationResponse | null;
  backgroundImageUrl?: string | null;
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
  const fmt = (v: unknown, digits = 1) =>
    typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '--';
  return (
    <section className="mt-3 space-y-3 rounded-lg border bg-muted/30 p-3">
      <div>
        <p className="text-[11px] font-semibold text-foreground">
          Reference comparison 기준
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Metrics use {comparisonLabel} points as the measured comparison data. Reference maps are interpolated measurements, not absolute ground truth.
        </p>
      </div>

      <button
        type="button"
        onClick={() => setDetailOpen(true)}
        className="inline-flex w-full items-center justify-center gap-1 rounded-md border bg-background px-2 py-1.5 text-[11px] font-medium hover:bg-accent"
      >
        <Maximize2 className="h-3 w-3" />
        Detail view
      </button>

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
          <span>Metric</span>
          <span>Before</span>
          <span>After</span>
          <span>Improvement</span>
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
      </div>

      <details className="rounded-md border bg-background text-[11px]">
        <summary className="cursor-pointer px-3 py-2 font-medium">
          Reference comparison errors ({comparisonPoints.length})
        </summary>
        <div className="max-h-48 overflow-auto">
          <table className="w-full min-w-[520px] text-left">
            <thead className="sticky top-0 bg-background text-muted-foreground">
              <tr>
                <th className="px-2 py-1">Point</th>
                <th className="px-2 py-1">Measured</th>
                <th className="px-2 py-1">Baseline</th>
                <th className="px-2 py-1">Calibrated</th>
                <th className="px-2 py-1">Before</th>
                <th className="px-2 py-1">After</th>
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
      />
    </section>
  );
}

function CalibrationEvaluationDetailModal({
  open,
  onClose,
  evaluation,
  backgroundImageUrl,
}: {
  open: boolean;
  onClose: () => void;
  evaluation: CalibrationEvaluationResponse;
  backgroundImageUrl?: string | null;
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
            <h2 className="text-base font-semibold">3-way RSSI map comparison</h2>
            <p className="text-xs text-muted-foreground">
              Same floorplan, grid, bounds, and RSSI color scale. Metrics use {comparisonLabel} points as measured comparison data.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border hover:bg-accent"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
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
              />
            ))}
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[24rem_1fr]">
            <div className="rounded-lg border bg-muted/20 p-4 text-sm">
              <p className="font-semibold">Validation metrics</p>
              <div className="mt-3 grid grid-cols-4 gap-2 text-xs font-semibold text-muted-foreground">
                <span>Metric</span>
                <span>Before</span>
                <span>After</span>
                <span>Improvement</span>
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
                  calibration
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="h-0 w-0 border-x-[5px] border-b-[9px] border-x-transparent border-b-[#dc2626]" />
                  comparison
                </span>
              </div>
            </div>

            <div className="rounded-lg border bg-background text-xs">
              <div className="border-b px-4 py-3 font-semibold">
                Reference comparison errors ({comparisonPoints.length})
              </div>
              <div className="max-h-72 overflow-auto">
                <table className="w-full min-w-[640px] text-left">
                  <thead className="sticky top-0 bg-background text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">Point</th>
                      <th className="px-3 py-2">Measured</th>
                      <th className="px-3 py-2">Baseline Pred</th>
                      <th className="px-3 py-2">Calibrated Pred</th>
                      <th className="px-3 py-2">Before Error</th>
                      <th className="px-3 py-2">After Error</th>
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
}: {
  map: CalibrationEvaluationResponse['maps']['baseline'];
  colorScale: { min_dbm: number; max_dbm: number };
  calibrationPoints: CalibrationEvaluationResponse['points']['calibration'];
  validationPoints: CalibrationEvaluationResponse['points']['validation'];
  backgroundImageUrl?: string | null;
  size?: 'compact' | 'large';
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
          {map.label}
        </p>
        {size === 'large' && (
          <span className="text-[11px] text-muted-foreground">
            {colorScale.min_dbm} to {colorScale.max_dbm} dBm
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
        {calibrationPoints.map((p) => (
          <circle key={`c-${p.point_id}`} cx={p.x_m} cy={p.y_m} r={w * 0.012} fill="#0f766e" stroke="white" strokeWidth={w * 0.004} />
        ))}
        {validationPoints.map((p) => (
          <path
            key={`v-${p.point_id}`}
            d={`M ${p.x_m} ${p.y_m - w * 0.014} L ${p.x_m - w * 0.014} ${p.y_m + w * 0.014} L ${p.x_m + w * 0.014} ${p.y_m + w * 0.014} Z`}
            fill="#dc2626"
            stroke="white"
            strokeWidth={w * 0.004}
          />
        ))}
      </svg>
      {size === 'large' && <RssiScaleBar min={colorScale.min_dbm} max={colorScale.max_dbm} />}
    </div>
  );
}

function RssiScaleBar({ min, max }: { min: number; max: number }) {
  return (
    <div className="mt-2">
      <div
        className="h-2 rounded-full"
        style={{
          background:
            'linear-gradient(90deg, rgb(12,7,134), rgb(75,3,161), rgb(125,3,168), rgb(203,71,119), rgb(248,149,64), rgb(240,249,33))',
        }}
      />
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>{min} dBm</span>
        <span>{max} dBm</span>
      </div>
    </div>
  );
}

function rssiColor(value: number, min: number, max: number): string {
  const t = Math.max(0, Math.min(1, (value - min) / Math.max(max - min, 1)));
  const stops = [
    [12, 7, 134],
    [75, 3, 161],
    [125, 3, 168],
    [203, 71, 119],
    [248, 149, 64],
    [240, 249, 33],
  ];
  const pos = t * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(pos));
  const local = pos - i;
  const a = stops[i];
  const b = stops[i + 1];
  const rgb = a.map((v, idx) => Math.round(v + (b[idx] - v) * local));
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
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
    rmse: toNum('rmse_dbm') ?? toNum('rmse') ?? toNum('rmse_after'),
    mae: toNum('mae_dbm') ?? toNum('mae') ?? toNum('mae_after'),
  };
}

function formatValue(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'number') return v.toFixed(3);
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}
