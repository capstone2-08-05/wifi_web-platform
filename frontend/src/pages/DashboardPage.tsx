import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ChevronRight,
  ImageOff,
  Map,
  Radio,
  Smartphone,
  type LucideIcon,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { HelpFab } from '@/components/HelpFab';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/stores/app-store';
import { FloorPreview } from '@/features/dashboard/FloorPreview';
import { DiagnosticsList } from '@/features/dashboard/DiagnosticsList';
import {
  MOCK_DASHBOARD_FLOOR_SCENE,
  MOCK_DIAGNOSTICS,
} from '@/features/dashboard/mocks';

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
  const projectId = useAppStore((s) => s.selectedProjectId);
  const floorId = useAppStore((s) => s.selectedFloorId);
  const hasFloorSelected = !!projectId && !!floorId;
  const [expanded, setExpanded] = useState(false);
  const toggleExpand = () => setExpanded((v) => !v);

  return (
    <div className="relative h-full overflow-auto p-6">
      <div className="space-y-6">
        <header className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">대시보드</h1>
          <p className="text-sm text-muted-foreground">
            현장 앱과 연동된 매장 도면 및 최신 진단 내역을 확인하세요.
          </p>
        </header>

        <div
          className={
            expanded
              ? 'grid grid-cols-1 gap-6'
              : 'grid grid-cols-1 gap-6 lg:grid-cols-[2fr_minmax(320px,1fr)]'
          }
        >
          <Card title="현재 작업 중인 도면" className="min-h-140">
            <div className={expanded ? 'h-180' : 'h-120'}>
              {hasFloorSelected ? (
                <FloorPreview
                  scene={MOCK_DASHBOARD_FLOOR_SCENE}
                  expanded={expanded}
                  onToggleExpand={toggleExpand}
                />
              ) : (
                <FloorEmptyState hasProject={!!projectId} />
              )}
            </div>
          </Card>

          {!expanded && (
            <div className="space-y-6">
              <Card title="빠른 실행">
                <ul className="space-y-3">
                  {QUICK_ACTIONS.map((a) => (
                    <QuickAction key={a.to} {...a} />
                  ))}
                </ul>
              </Card>

              <Card title="현장 앱 최근 진단">
                {hasFloorSelected ? (
                <DiagnosticsList items={MOCK_DIAGNOSTICS} />
              ) : (
                <DiagnosticsEmptyState />
              )}
              </Card>
            </div>
          )}
        </div>
      </div>

      <HelpFab />
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

function FloorEmptyState({ hasProject }: { hasProject: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-md border border-dashed bg-muted/20 p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <ImageOff className="h-5 w-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">
        {hasProject ? '층을 선택해주세요' : '프로젝트를 먼저 선택해주세요'}
      </p>
      <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
        상단 셀렉터에서 작업할 도면(층)을 선택하면 현재 작업 중인 도면 미리보기가 표시됩니다.
      </p>
      <Link
        to="/editor"
        className="mt-2 inline-flex items-center gap-1 rounded-md border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
      >
        공간 편집으로 이동
        <ChevronRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

function DiagnosticsEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
        <Activity className="h-4 w-4 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">진단된 내역이 없습니다</p>
      <p className="max-w-xs text-[11px] leading-relaxed text-muted-foreground">
        모바일 앱으로 현장을 측정하면 이곳에 신호 약점 / 이상 구역이 표시됩니다.
      </p>
    </div>
  );
}

