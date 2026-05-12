import { Link } from 'react-router-dom';
import {
  ChevronRight,
  Map,
  Radio,
  Smartphone,
  type LucideIcon,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { cn } from '@/lib/utils';

type Tone = 'blue' | 'purple' | 'green';

const TONE: Record<
  Tone,
  { iconBg: string; iconText: string; hoverBg: string; hoverBorder: string }
> = {
  blue: {
    iconBg: 'bg-blue-100',
    iconText: 'text-blue-600',
    hoverBg: 'hover:bg-blue-50',
    hoverBorder: 'hover:border-blue-300',
  },
  purple: {
    iconBg: 'bg-purple-100',
    iconText: 'text-purple-600',
    hoverBg: 'hover:bg-purple-50',
    hoverBorder: 'hover:border-purple-300',
  },
  green: {
    iconBg: 'bg-emerald-100',
    iconText: 'text-emerald-600',
    hoverBg: 'hover:bg-emerald-50',
    hoverBorder: 'hover:border-emerald-300',
  },
};

const QUICK_ACTIONS = [
  {
    to: '/mobile',
    icon: Smartphone,
    label: '현장 모바일 앱 연결',
    sub: 'QR 스캔으로 기기 연동',
    tone: 'blue',
  },
  {
    to: '/editor',
    icon: Map,
    label: '공간 및 가구 편집',
    sub: '도면 수정 및 장애물 배치',
    tone: 'purple',
  },
  {
    to: '/simulation',
    icon: Radio,
    label: '품질 시뮬레이션',
    sub: '가상 AP 배치 및 커버리지 확인',
    tone: 'green',
  },
] as const satisfies ReadonlyArray<{
  to: string;
  icon: LucideIcon;
  label: string;
  sub: string;
  tone: Tone;
}>;

export default function DashboardPage() {
  return (
    <div className="h-full space-y-6 overflow-auto p-6">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">대시보드</h1>
        <p className="text-sm text-muted-foreground">
          현장 앱과 연동된 매장 도면 및 최신 진단 내역을 확인하세요.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
        <Card title="현재 작업 중인 도면" className="min-h-96">
          <div className="flex h-full min-h-80 items-center justify-center rounded-md bg-muted/40 text-sm text-muted-foreground">
            (도면 미리보기 — Editor 구현 후 연결)
          </div>
        </Card>

        <div className="space-y-6">
          <Card title="빠른 실행">
            <ul className="space-y-3">
              {QUICK_ACTIONS.map((a) => (
                <QuickAction key={a.to} {...a} />
              ))}
            </ul>
          </Card>

          <Card title="현장 앱 최근 진단">
            <div className="text-sm text-muted-foreground">
              (진단 API 스펙 수신 후 연결)
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function QuickAction({
  to,
  icon: Icon,
  label,
  sub,
  tone,
}: {
  to: string;
  icon: LucideIcon;
  label: string;
  sub: string;
  tone: Tone;
}) {
  const t = TONE[tone];
  return (
    <li>
      <Link
        to={to}
        className={cn(
          'flex items-center gap-3 rounded-md border bg-background p-3 transition-colors',
          t.hoverBg,
          t.hoverBorder,
        )}
      >
        <div
          className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-md',
            t.iconBg,
            t.iconText,
          )}
        >
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium">{label}</div>
          <div className="text-xs text-muted-foreground">{sub}</div>
        </div>
        <ChevronRight className="h-4 w-4 text-muted-foreground" />
      </Link>
    </li>
  );
}
