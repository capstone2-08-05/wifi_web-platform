import { BarChart3 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  /** null 이면 "—" 표시 (버전 mismatch 등으로 비교 불가). */
  avgRssiDbm: number | null;
  coveragePercent: number | null;
  /** 비활성 사유 안내 (옛 버전이라 표시 안함 등). */
  staleReason?: string | null;
}

export function SimulationResultCard({
  avgRssiDbm,
  coveragePercent,
  staleReason,
}: Props) {
  // mock: rssi -100~-30 범위를 0~100 으로 매핑
  const rssiFillPct =
    avgRssiDbm == null
      ? 0
      : Math.max(0, Math.min(100, ((avgRssiDbm + 100) / 70) * 100));
  const coverageFillPct = coveragePercent ?? 0;

  return (
    <section className="rounded-2xl border bg-background p-5 shadow-sm">
      <header className="mb-4 flex items-center gap-2">
        <BarChart3 className="h-4 w-4 text-primary" strokeWidth={2} />
        <h3 className="text-sm font-bold">새로운 배치 예측 결과</h3>
      </header>

      <Metric
        label="평균 신호 강도"
        valueText={avgRssiDbm == null ? '—' : formatNum(avgRssiDbm)}
        unit={avgRssiDbm == null ? '' : 'dBm'}
        fillPct={rssiFillPct}
        barColor="bg-emerald-500"
      />

      <div className="mt-5">
        <Metric
          label="면적 커버리지 (양호)"
          valueText={coveragePercent == null ? '—' : formatNum(coveragePercent)}
          unit={coveragePercent == null ? '' : '%'}
          fillPct={coverageFillPct}
          barColor="bg-primary"
        />
      </div>

      {staleReason && (
        <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
          {staleReason}
        </p>
      )}
    </section>
  );
}

/** 소수 셋째자리에서 반올림 → 둘째자리까지 표시. 정수면 "100" 같이 trailing 0 안 붙음. */
function formatNum(n: number): string {
  return Number(n.toFixed(2)).toString();
}

function Metric({
  label,
  valueText,
  unit,
  fillPct,
  barColor,
}: {
  label: string;
  valueText: string;
  unit: string;
  fillPct: number;
  barColor: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] font-medium text-foreground/80">{label}</span>
        <span className="text-2xl font-bold tabular-nums">
          {valueText}
          <span className="ml-1 text-xs font-medium text-muted-foreground">{unit}</span>
        </span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn('h-full rounded-full transition-all', barColor)}
          style={{ width: `${fillPct}%` }}
        />
      </div>
    </div>
  );
}
