import { AlertTriangle, AlertCircle, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

export type DiagnosticSeverity = 'critical' | 'warning' | 'good' | 'weak';

export interface Diagnostic {
  id: string;
  location: string;
  timeLabel: string;
  severity: DiagnosticSeverity;
  statusText: string;
  description: string;
}

interface Props {
  items: Diagnostic[];
  onSeeAll?: () => void;
}

const SEVERITY_STYLES: Record<
  DiagnosticSeverity,
  { dot: string; statusText: string; icon: 'warning' | 'alert' | 'dot' }
> = {
  critical: { dot: 'bg-red-500', statusText: 'text-red-600', icon: 'warning' },
  warning: { dot: 'bg-orange-500', statusText: 'text-orange-600', icon: 'alert' },
  good: { dot: 'bg-slate-300', statusText: 'text-emerald-600', icon: 'dot' },
  weak: { dot: 'bg-slate-300', statusText: 'text-amber-600', icon: 'dot' },
};

const DOT_TONE: Record<DiagnosticSeverity, string> = {
  critical: 'bg-red-500',
  warning: 'bg-orange-500',
  good: 'bg-emerald-500',
  weak: 'bg-amber-500',
};

export function DiagnosticsList({ items, onSeeAll }: Props) {
  return (
    <ul className="space-y-4">
      {items.map((d) => (
        <DiagnosticItem key={d.id} item={d} />
      ))}
      <li>
        <button
          type="button"
          onClick={onSeeAll}
          className="inline-flex w-full items-center justify-center gap-1 rounded-md py-2 text-sm font-medium text-primary hover:text-primary/80"
        >
          진단 내역 전체 보기
          <ChevronRight className="h-4 w-4" />
        </button>
      </li>
    </ul>
  );
}

function DiagnosticItem({ item }: { item: Diagnostic }) {
  const styles = SEVERITY_STYLES[item.severity];
  return (
    <li>
      <div className="flex gap-2.5">
        <div className="flex pt-1.5">
          <span className={cn('block h-2 w-2 shrink-0 rounded-full', styles.dot)} />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-sm font-semibold text-foreground">{item.location}</h4>
            <span className="shrink-0 rounded-full bg-muted/60 px-2 py-0.5 text-[11px] text-muted-foreground">
              {item.timeLabel}
            </span>
          </div>
          <div
            className={cn(
              'flex items-center gap-1.5 text-[13px] font-medium',
              styles.statusText,
            )}
          >
            {styles.icon === 'warning' && <AlertTriangle className="h-3.5 w-3.5" />}
            {styles.icon === 'alert' && <AlertCircle className="h-3.5 w-3.5" />}
            {styles.icon === 'dot' && (
              <span className={cn('block h-2 w-2 rounded-full', DOT_TONE[item.severity])} />
            )}
            {item.statusText}
          </div>
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            {item.description}
          </p>
        </div>
      </div>
    </li>
  );
}
