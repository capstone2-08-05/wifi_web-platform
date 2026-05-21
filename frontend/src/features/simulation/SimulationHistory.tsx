import { ArrowLeftRight, Clock } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface SimulationHistoryItem {
  id: string;
  label: string;
  timeLabel: string;
  /** 메트릭이 RfMap 에 있어서 history list 에선 비어있을 수 있음. null → "—" 표시. */
  avgRssiDbm: number | null;
  coveragePercent: number | null;
  active?: boolean;
}

interface Props {
  items: SimulationHistoryItem[];
  showCompareButton?: boolean;
  onSelect?: (id: string) => void;
  emptyMessage?: string;
}

export function SimulationHistory({ items, showCompareButton, onSelect, emptyMessage }: Props) {
  return (
    <section className="rounded-2xl border bg-background p-5 shadow-sm">
      <header className="mb-4 flex items-center gap-2">
        <Clock className="h-4 w-4 text-foreground/70" strokeWidth={2} />
        <h3 className="text-sm font-bold">시뮬레이션 기록</h3>
      </header>

      {items.length === 0 ? (
        <p className="py-2 text-xs text-muted-foreground">
          {emptyMessage ?? '아직 시뮬레이션 기록이 없습니다.'}
        </p>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onSelect?.(item.id)}
                disabled={!onSelect}
                className={cn(
                  'w-full rounded-lg border p-3 text-left transition-colors hover:border-primary/40 disabled:cursor-default',
                  item.active && 'border-primary/40 bg-primary/5',
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-semibold">{item.label}</span>
                  <span className="shrink-0 rounded-full bg-muted/60 px-2 py-0.5 text-[11px] text-muted-foreground">
                    {item.timeLabel}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-3 text-[12px] text-muted-foreground">
                  <span>
                    평균:{' '}
                    <span className="font-semibold text-foreground">
                      {item.avgRssiDbm == null ? '—' : `${formatNum(item.avgRssiDbm)}dBm`}
                    </span>
                  </span>
                  <span>
                    커버리지:{' '}
                    <span className="font-semibold text-foreground">
                      {item.coveragePercent == null ? '—' : `${formatNum(item.coveragePercent)}%`}
                    </span>
                  </span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}

      {showCompareButton && (
        <button
          type="button"
          className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-primary/40 bg-background py-2.5 text-sm font-semibold text-primary hover:bg-primary/5"
        >
          <ArrowLeftRight className="h-4 w-4" />두 시뮬레이션 결과 비교하기
        </button>
      )}
    </section>
  );
}

/** 소수 셋째자리에서 반올림 → 둘째자리까지 표시. 정수면 trailing 0 안 붙음. */
function formatNum(n: number): string {
  return Number(n.toFixed(2)).toString();
}
