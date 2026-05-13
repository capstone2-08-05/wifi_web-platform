import { AlertTriangle, AlertCircle, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

type Severity = 'critical' | 'warning' | 'good' | 'weak';

interface Diagnostic {
  id: string;
  location: string;
  timeLabel: string;
  severity: Severity;
  statusText: string;
  description: string;
}

const MOCK_DIAGNOSTICS: Diagnostic[] = [
  {
    id: 'd-1',
    location: '창고 앞 구석 테이블',
    timeLabel: '방금 전',
    severity: 'critical',
    statusText: '신호 끊김 (-85dBm)',
    description: '고객 클레임 다수 발생 구역. 철제 수납장 영향 의심됨.',
  },
  {
    id: 'd-2',
    location: '카운터 포스기 주변',
    timeLabel: '2시간 전',
    severity: 'warning',
    statusText: '간헐적 속도 저하',
    description: '결제 시 지연 발생. 채널 간섭 확인 필요.',
  },
  {
    id: 'd-3',
    location: '메인 홀 중앙',
    timeLabel: '어제',
    severity: 'good',
    statusText: '양호 (-45dBm)',
    description: '특이사항 없음. 정상 서비스 중.',
  },
  {
    id: 'd-4',
    location: '화장실 앞 복도',
    timeLabel: '3일 전',
    severity: 'weak',
    statusText: '신호 약함 (-72dBm)',
    description: '콘크리트 벽체 영향으로 보임. 사용상 큰 무리는 없음.',
  },
];

const SEVERITY_STYLES: Record<
  Severity,
  { dot: string; statusText: string; icon: 'warning' | 'alert' | 'dot' }
> = {
  critical: { dot: 'bg-red-500', statusText: 'text-red-600', icon: 'warning' },
  warning: { dot: 'bg-orange-500', statusText: 'text-orange-600', icon: 'alert' },
  good: { dot: 'bg-slate-300', statusText: 'text-emerald-600', icon: 'dot' },
  weak: { dot: 'bg-slate-300', statusText: 'text-amber-600', icon: 'dot' },
};

const DOT_TONE: Record<Severity, string> = {
  critical: 'bg-red-500',
  warning: 'bg-orange-500',
  good: 'bg-emerald-500',
  weak: 'bg-amber-500',
};

export function DiagnosticsList() {
  return (
    <ul className="space-y-4">
      {MOCK_DIAGNOSTICS.map((d) => (
        <DiagnosticItem key={d.id} item={d} />
      ))}
      <li>
        <button
          type="button"
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
