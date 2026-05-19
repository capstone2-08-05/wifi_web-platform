import { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  Clock,
  MapPin,
  Smartphone,
  TrendingUp,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { HelpFab } from '@/components/HelpFab';
import { MobileConnectModal } from '@/features/mobile/MobileConnectModal';
import { Popover } from '@/components/ui/Popover';
import { useAppStore } from '@/stores/app-store';
import type { MeasurementSession } from '@/types/measurement-session';
import { useFloorVersions, useSceneVersion } from '@/hooks/use-scene-version';
import {
  useFloorMeasurementSessions,
  useMeasurementPoints,
} from '@/hooks/use-measurement-session';
import {
  MeasurementCanvas,
  type MeasurementPoint as CanvasPoint,
  type MeasurementPointQuality,
  type MeasurementViewMode,
  type PlacedApSimple,
} from '@/features/measurement/MeasurementCanvas';
import type { MeasurementPoint as ApiPoint } from '@/types/measurement-session';

export default function MeasurementPage() {
  const floorId = useAppStore((s) => s.selectedFloorId);

  // 확정된 도면 (캔버스 배경).
  const versionsQuery = useFloorVersions(floorId);
  const versions = versionsQuery.data ?? [];
  const currentVersion = versions.find((v) => v.is_current) ?? versions[0] ?? null;
  const versionDetailQuery = useSceneVersion(currentVersion?.id ?? null);
  const sceneVersion = versionDetailQuery.data ?? null;

  // 측정 세션. 기본은 최근 세션 자동 선택, 사용자가 '이력 보기' 로 다른 세션 선택 가능.
  const sessionsQuery = useFloorMeasurementSessions(floorId);
  const sessions = sessionsQuery.data?.items ?? [];
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const activeSession =
    sessions.find((s) => s.id === selectedSessionId) ?? sessions[0] ?? null;
  const pointsQuery = useMeasurementPoints(activeSession?.id ?? null);
  const points = pointsQuery.data?.items ?? [];

  const canvasPoints = useMemo(() => apiPointsToCanvas(points), [points]);

  const [mode, setMode] = useState<MeasurementViewMode>('route');
  const [mobileOpen, setMobileOpen] = useState(false);

  const hasVersion = versions.length > 0;
  const hasMeasurement = points.length > 0;

  return (
    <div className="relative flex h-full flex-col gap-5 p-6">
      <PageHeader
        sessions={sessions}
        activeSession={activeSession}
        onSelectSession={(id) => setSelectedSessionId(id)}
        onStartMeasurement={() => setMobileOpen(true)}
      />

      {!floorId ? (
        <EmptyState
          title="층을 먼저 선택해주세요"
          subtitle="상단 셀렉터에서 작업할 도면(층)을 선택하면 측정 시작 흐름이 표시됩니다."
        />
      ) : !hasVersion ? (
        <EmptyState
          title="확정된 도면이 필요합니다"
          subtitle="공간 편집에서 도면을 분석·확정한 후 모바일 앱으로 실측을 진행할 수 있습니다."
        />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 xl:grid-cols-[1fr_22rem]">
          <section className="flex min-h-0 flex-col gap-3">
            <TabBar mode={mode} onChange={setMode} />
            <div className="relative flex min-h-0 flex-1 flex-col gap-2 rounded-xl border bg-card p-4 shadow-sm">
              <Legend />
              <div className="relative min-h-112 flex-1">
                <MeasurementCanvas
                  sceneVersion={sceneVersion}
                  points={canvasPoints}
                  aps={[] as PlacedApSimple[]}
                  mode={mode}
                />
                {!hasMeasurement && <CanvasEmptyOverlay loading={pointsQuery.isFetching} />}
              </div>
            </div>
          </section>

          <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto">
            <DiagnosticCard points={canvasPoints} />
            <CauseAnalysisCard hasData={hasMeasurement} />
          </aside>
        </div>
      )}

      <MobileConnectModal open={mobileOpen} onClose={() => setMobileOpen(false)} />
      <HelpFab />
    </div>
  );
}

// ============================================
// API → 캔버스 포인트 변환
// ============================================

/** RSSI(dBm) → 신호 품질 라벨. 일반적인 Wi-Fi 임계값(>-67 양호 / >-75 주의 / 이하 불량). */
function qualityFromRssi(rssi: number | null): MeasurementPointQuality {
  if (rssi == null) return 'warning';
  if (rssi >= -67) return 'good';
  if (rssi >= -75) return 'warning';
  return 'poor';
}

function apiPointsToCanvas(points: ApiPoint[]): CanvasPoint[] {
  return points.map((p, idx) => ({
    id: p.id,
    x_m: p.floor_position.x,
    y_m: p.floor_position.y,
    quality: qualityFromRssi(p.rssi_dbm),
    order: p.step_index ?? idx + 1,
  }));
}

// ============================================
// 헤더
// ============================================

function PageHeader({
  sessions,
  activeSession,
  onSelectSession,
  onStartMeasurement,
}: {
  sessions: MeasurementSession[];
  activeSession: MeasurementSession | null;
  onSelectSession: (id: string) => void;
  onStartMeasurement: () => void;
}) {
  const hasSessions = sessions.length > 0;
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">실측 및 진단</h1>
        <p className="text-sm text-muted-foreground">
          모바일 기기로 측정한 실제 와이파이 품질 데이터와 시뮬레이션을 통합하여 분석합니다.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Popover
          align="end"
          contentClassName="w-72 max-h-80 overflow-y-auto"
          trigger={({ toggle }) => (
            <button
              type="button"
              onClick={toggle}
              disabled={!hasSessions}
              className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm font-medium text-foreground shadow-sm hover:bg-accent disabled:opacity-50"
            >
              <Clock className="h-4 w-4 text-muted-foreground" />
              이력 보기
              {activeSession && (
                <span className="text-xs font-normal text-muted-foreground">
                  ({formatRelative(activeSession.created_at)})
                </span>
              )}
            </button>
          )}
        >
          {({ close }) => (
            <div className="py-1">
              <p className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                측정 세션 ({sessions.length})
              </p>
              {sessions.map((s) => {
                const isActive = activeSession?.id === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      onSelectSession(s.id);
                      close();
                    }}
                    className={cn(
                      'flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-xs hover:bg-accent',
                      isActive && 'bg-accent',
                    )}
                  >
                    <span className="flex w-full items-center justify-between">
                      <span className="font-medium text-foreground">
                        {formatRelative(s.created_at)}
                      </span>
                      <SessionStatusBadge status={s.status} />
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {s.measurement_type} · {s.id.slice(0, 8)}…
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </Popover>
        <button
          type="button"
          onClick={onStartMeasurement}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90"
        >
          <Smartphone className="h-4 w-4" />
          새로운 측정 시작
        </button>
      </div>
    </header>
  );
}

function SessionStatusBadge({ status }: { status: string }) {
  const style =
    status === 'completed'
      ? 'bg-emerald-100 text-emerald-700'
      : status === 'in_progress'
      ? 'bg-amber-100 text-amber-700'
      : 'bg-muted text-muted-foreground';
  const label =
    status === 'completed' ? '완료' : status === 'in_progress' ? '진행 중' : status;
  return (
    <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium', style)}>{label}</span>
  );
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  if (sameDay(d, today)) return `오늘 ${hh}:${mm}`;
  if (sameDay(d, yesterday)) return `어제 ${hh}:${mm}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`;
}

function sameDay(a: Date, b: Date) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

// ============================================
// 탭 / 범례
// ============================================

const TABS: { id: MeasurementViewMode; label: string }[] = [
  { id: 'route', label: '측정 경로 보기' },
  { id: 'heatmap', label: '실측 히트맵' },
  { id: 'both', label: '예측·실측 통합 분석' },
];

function TabBar({
  mode,
  onChange,
}: {
  mode: MeasurementViewMode;
  onChange: (m: MeasurementViewMode) => void;
}) {
  return (
    <div role="tablist" className="flex items-center gap-6 border-b">
      {TABS.map((t) => {
        const active = mode === t.id;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={cn(
              '-mb-px border-b-2 px-1 py-2.5 text-sm font-medium transition-colors',
              active
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

function Legend() {
  return (
    <div className="inline-flex w-fit items-center gap-3 rounded-md border bg-background px-3 py-1.5 text-[11px] text-muted-foreground shadow-sm">
      <span className="font-semibold text-foreground">실측 포인트 범례</span>
      <LegendDot color="oklch(0.72 0.18 145)" label="양호" />
      <LegendDot color="oklch(0.78 0.15 85)" label="주의" />
      <LegendDot color="oklch(0.62 0.22 25)" label="불량" />
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="inline-block h-2 w-2 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}

function CanvasEmptyOverlay({ loading }: { loading: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div className="pointer-events-auto max-w-sm rounded-xl border bg-background/95 px-5 py-4 text-center shadow-sm backdrop-blur">
        <p className="text-sm font-semibold">
          {loading ? '측정 데이터 불러오는 중...' : '측정 데이터가 없습니다'}
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          상단의 "새로운 측정 시작" 또는 헤더의 "모바일 앱 연결" 로 측정을 진행하면
          여기에 결과가 표시됩니다.
        </p>
      </div>
    </div>
  );
}

// ============================================
// 우측 진단 카드
// ============================================

function DiagnosticCard({ points }: { points: CanvasPoint[] }) {
  // 가장 신호가 약한 (불량 > 주의 > 양호) 포인트를 우선 노출.
  const worst = useMemo(() => pickWorstPoint(points), [points]);

  if (points.length === 0) {
    return (
      <div className="rounded-xl border bg-card p-4 shadow-sm">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <TrendingUp className="h-4 w-4 text-primary" />
          예측·실측 통합 진단
        </h2>
        <p className="mt-3 text-xs text-muted-foreground">
          측정 데이터가 없습니다. 모바일 앱으로 측정을 진행하면 가장 신호가 약한 지점의
          진단이 자동으로 표시됩니다.
        </p>
      </div>
    );
  }

  const statusLabel =
    worst.quality === 'poor'
      ? '상태 불량'
      : worst.quality === 'warning'
      ? '상태 주의'
      : '상태 양호';
  const statusStyle =
    worst.quality === 'poor'
      ? 'bg-destructive/10 text-destructive'
      : worst.quality === 'warning'
      ? 'bg-amber-100 text-amber-700'
      : 'bg-emerald-100 text-emerald-700';

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold">
        <TrendingUp className="h-4 w-4 text-primary" />
        예측·실측 통합 진단
      </h2>

      <div className="mt-4 flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <MapPin className="h-4 w-4 text-destructive" />
          <p className="text-sm font-semibold">
            측정 포인트{' '}
            <span className="text-muted-foreground">#{worst.order}</span>
          </p>
        </div>
        <span className={cn('rounded-md px-2 py-0.5 text-[11px] font-medium', statusStyle)}>
          {statusLabel}
        </span>
      </div>

      <p className="mt-3 text-[11px] text-muted-foreground">
        좌표 {worst.x_m.toFixed(2)}, {worst.y_m.toFixed(2)} m
      </p>

      {/* 예측치(시뮬레이션) 비교는 RF Run 결과와 매칭이 필요 — calibration-runs API 연결 후 노출 예정. */}
    </div>
  );
}

function pickWorstPoint(points: CanvasPoint[]): CanvasPoint {
  const rank: Record<MeasurementPointQuality, number> = {
    poor: 0,
    warning: 1,
    good: 2,
  };
  return [...points].sort((a, b) => rank[a.quality] - rank[b.quality])[0];
}

function CauseAnalysisCard({ hasData }: { hasData: boolean }) {
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <AlertTriangle className="h-4 w-4 text-amber-500" />
        원인 분석 및 조치
      </h3>
      {hasData ? (
        <p className="mt-2 rounded-md bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-900">
          캘리브레이션 결과가 도착하면 신호 약화의 원인 후보와 조치가 여기에 표시됩니다.
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          불량 지점이 검출되면 원인 후보와 조치 방안이 여기에 표시됩니다.
        </p>
      )}
      <button
        type="button"
        disabled={!hasData}
        className="mt-3 inline-flex w-full items-center justify-center gap-1 rounded-md border bg-background px-3 py-2 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
      >
        조치 방법 확인하기
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ============================================
// 빈 상태
// ============================================

function EmptyState({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="flex max-w-lg flex-col items-center gap-3 rounded-2xl border border-dashed bg-background p-10 text-center shadow-sm">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
          <Activity className="h-6 w-6 text-primary" strokeWidth={1.8} />
        </div>
        <p className="text-base font-semibold">{title}</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{subtitle}</p>
      </div>
    </div>
  );
}
