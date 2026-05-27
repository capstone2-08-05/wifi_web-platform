import { Loader2, Sliders } from 'lucide-react';
import type {
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
