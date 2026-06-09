import { useState } from 'react';
import { ArrowLeftRight, ChevronDown, History, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface SimulationHistoryItem {
  id: string;
  /** RF Run.created_at (ISO) — 카드 제목·실행 시점 표시용. */
  createdAt: string;
  status?: string;
  avgRssiDbm: number | null;
  coveragePercent: number | null;
  active?: boolean;
}

interface Props {
  items: SimulationHistoryItem[];
  isLoading?: boolean;
  showCompareButton?: boolean;
  onSelect?: (id: string) => void;
}

type CoverageStatus = {
  label: string;
  badgeClass: string;
};

export function SimulationHistory({ items, isLoading, showCompareButton, onSelect }: Props) {
  const [expanded, setExpanded] = useState(true);
  const bestId = findBestResultId(items);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3">
      <header className={cn('py-[3px]', expanded && 'mb-3')}>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex w-full items-start justify-between gap-2 py-[3px] text-left"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <History className="h-3.5 w-3.5 shrink-0 text-slate-400" strokeWidth={2} />
              <h3 className="text-sm font-semibold text-slate-900">시뮬레이션 기록</h3>
              {!isLoading && items.length > 0 && (
                <span className="text-[10px] text-slate-400">({items.length})</span>
              )}
            </div>
            {expanded && (
              <p className="mt-1 pl-5 text-[11px] leading-relaxed text-slate-500">
                최근 실행 결과를 비교해볼 수 있습니다.
              </p>
            )}
          </div>
          <ChevronDown
            className={cn(
              'mt-0.5 h-4 w-4 shrink-0 text-slate-400 transition-transform',
              expanded && 'rotate-180',
            )}
            aria-hidden
          />
        </button>
      </header>

      {expanded &&
        (isLoading ? (
          <ul className="space-y-1.5" aria-busy="true" aria-label="기록 불러오는 중">
            {Array.from({ length: 3 }, (_, i) => (
              <li key={i}>
                <HistoryCardSkeleton />
              </li>
            ))}
          </ul>
        ) : items.length === 0 ? (
          <EmptyHistoryState />
        ) : (
          <ul className="space-y-1.5">
            {items.map((item) => (
              <li key={item.id}>
                <HistoryCard
                  item={item}
                  isBest={item.id === bestId}
                  onSelect={onSelect}
                />
              </li>
            ))}
          </ul>
        ))}

      {expanded && showCompareButton && (
        <button
          type="button"
          className="mt-2.5 inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-200 bg-white py-1.5 text-xs font-medium text-blue-600 transition-colors hover:bg-slate-50"
        >
          <ArrowLeftRight className="h-3.5 w-3.5" />
          두 시뮬레이션 결과 비교하기
        </button>
      )}
    </section>
  );
}

function HistoryCard({
  item,
  isBest,
  onSelect,
}: {
  item: SimulationHistoryItem;
  isBest: boolean;
  onSelect?: (id: string) => void;
}) {
  const runStatus = getRunStatus(item.status);
  const coverageStatus = getCoverageStatus(item.coveragePercent);
  const title = formatExecutionLabel(item.createdAt);
  const shortId = item.id.slice(0, 6);
  const isRunning = item.status === 'pending' || item.status === 'running';

  return (
    <button
      type="button"
      onClick={() => onSelect?.(item.id)}
      disabled={!onSelect || isRunning}
      className={cn(
        'relative w-full rounded-md border p-2.5 text-left transition-colors disabled:cursor-default',
        isBest && !item.active && 'border-blue-400 bg-gradient-to-br from-blue-50/80 to-white shadow-sm shadow-blue-100',
        !isBest && 'border-slate-200 bg-white',
        item.active && 'border-blue-400 bg-blue-50/60',
        !item.active && !isRunning && 'hover:border-slate-300',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className={cn('text-[13px] font-medium', isBest ? 'text-slate-900' : 'text-slate-800')}>{title}</span>
        {runStatus ? (
          <span
            className={cn(
              'inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-xs',
              runStatus.badgeClass,
            )}
          >
            {isRunning && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
            {runStatus.label}
          </span>
        ) : isBest ? (
          <span className="shrink-0 rounded bg-blue-600 px-2 py-0.5 text-xs font-semibold text-white shadow-sm shadow-blue-300">
            최고
          </span>
        ) : (
          coverageStatus && (
            <span
              className={cn(
                'shrink-0 rounded border px-1.5 py-0.5 text-xs',
                coverageStatus.badgeClass,
              )}
            >
              {coverageStatus.label}
            </span>
          )
        )}
      </div>

      <div className="mt-1 space-y-1">
        <p className="text-[11px] text-slate-500">
          평균 신호 세기
          <span className="ml-2 font-medium tabular-nums text-slate-700">
            {item.avgRssiDbm == null ? '—' : formatRssi(item.avgRssiDbm)}
          </span>
        </p>
        <p className="flex items-center justify-between gap-2 text-[11px] text-slate-500">
          <span>
            안정 신호 범위
            <span className="ml-2 font-medium tabular-nums text-slate-700">
              {item.coveragePercent == null ? '—' : formatCoverage(item.coveragePercent)}
            </span>
          </span>
          <span className="shrink-0 tabular-nums text-[10px] text-slate-400/80">#{shortId}</span>
        </p>
      </div>
    </button>
  );
}

function EmptyHistoryState() {
  return (
    <div className="rounded-md border border-dashed border-slate-200 px-3 py-5 text-center">
      <p className="text-xs font-medium text-slate-700">아직 실행된 시뮬레이션이 없습니다.</p>
      <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
        AP를 배치한 뒤 시뮬레이션을 실행하면 결과가 여기에 표시됩니다.
      </p>
    </div>
  );
}

function HistoryCardSkeleton() {
  return (
    <div className="animate-pulse rounded-md border border-slate-200 bg-white p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="h-3.5 w-24 rounded bg-slate-100" />
        <div className="h-5 w-10 rounded bg-slate-100" />
      </div>
      <div className="mt-1 space-y-1">
        <div className="h-2.5 w-36 rounded bg-slate-100" />
        <div className="flex items-center justify-between gap-2">
          <div className="h-2.5 w-32 rounded bg-slate-100" />
          <div className="h-2.5 w-10 rounded bg-slate-100" />
        </div>
      </div>
    </div>
  );
}

function getRunStatus(status: string | undefined): CoverageStatus | null {
  if (status === 'running' || status === 'pending') {
    return {
      label: '실행 중',
      badgeClass: 'border-blue-100 bg-blue-50 text-blue-600',
    };
  }
  if (status === 'failed') {
    return {
      label: '실패',
      badgeClass: 'border-red-100 bg-red-50 text-red-600',
    };
  }
  return null;
}

/** 커버리지 ≥70% 양호 · ≥40% 일부 개선 필요 · 그 미만 개선 필요 */
function getCoverageStatus(coverage: number | null): CoverageStatus | null {
  if (coverage == null) return null;
  if (coverage >= 70) {
    return {
      label: '양호',
      badgeClass: 'border-slate-100 bg-slate-50 text-slate-600',
    };
  }
  if (coverage >= 40) {
    return {
      label: '일부 개선 필요',
      badgeClass: 'border-amber-100/80 bg-amber-50 text-amber-600',
    };
  }
  return {
    label: '개선 필요',
    badgeClass: 'border-slate-100 bg-slate-50 text-slate-500',
  };
}

/** 커버리지 최대 → 동률이면 평균 신호 세기(dBm)가 더 높은(덜 음수) 항목. */
function findBestResultId(items: SimulationHistoryItem[]): string | null {
  const ranked = items.filter(
    (item) => item.status === 'succeeded' && item.coveragePercent != null,
  );
  if (ranked.length === 0) return null;

  let best = ranked[0];
  for (let i = 1; i < ranked.length; i += 1) {
    const candidate = ranked[i];
    const cmp = compareResults(candidate, best);
    if (cmp > 0) best = candidate;
  }
  return best.id;
}

function compareResults(a: SimulationHistoryItem, b: SimulationHistoryItem): number {
  const ac = a.coveragePercent ?? -Infinity;
  const bc = b.coveragePercent ?? -Infinity;
  if (ac !== bc) return ac - bc;

  const ar = a.avgRssiDbm;
  const br = b.avgRssiDbm;
  if (ar == null && br == null) return 0;
  if (ar == null) return -1;
  if (br == null) return 1;
  return ar - br;
}

function formatExecutionLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '실행 기록';
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${month}월 ${day}일 ${hh}:${mm} 실행`;
}

function formatRssi(n: number): string {
  return `${n.toFixed(1)} dBm`;
}

function formatCoverage(n: number): string {
  return `${n.toFixed(1)}%`;
}
