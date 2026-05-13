import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Map as MapIcon, Play, RotateCcw, Save } from 'lucide-react';
import { useAppStore } from '@/stores/app-store';
import { useFloorVersions } from '@/hooks/use-scene-version';
import { useCreateRfRun, useRfMaps, useRfRun } from '@/hooks/use-rf-run';
import { HelpFab } from '@/components/HelpFab';
import {
  SimulationCanvas,
  type SimulationState,
} from '@/features/simulation/SimulationCanvas';
import { SimulationResultCard } from '@/features/simulation/SimulationResultCard';
import {
  SimulationHistory,
  type SimulationHistoryItem,
} from '@/features/simulation/SimulationHistory';
import {
  MOCK_SIMULATION_FLOOR_SCENE,
  MOCK_SIMULATION_HEATMAP,
} from '@/features/simulation/mocks';

export default function SimulationPage() {
  const floorId = useAppStore((s) => s.selectedFloorId);
  const versionsQuery = useFloorVersions(floorId);
  // 현재 활성 버전 (없으면 가장 최근 버전)
  const currentVersion =
    versionsQuery.data?.find((v) => v.is_current) ?? versionsQuery.data?.[0] ?? null;

  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const createRfRun = useCreateRfRun();
  const rfRunPoll = useRfRun(activeRunId);
  const rfMapsQuery = useRfMaps(activeRunId, rfRunPoll.isSucceeded);

  // 백엔드 상태 → UI 상태 매핑
  const state: SimulationState = (() => {
    if (!activeRunId) return 'idle';
    if (rfRunPoll.isSucceeded) return 'complete';
    if (rfRunPoll.isFailed) return 'idle'; // 토스트로 알림 + 다시 시작 가능
    return 'running';
  })();

  const handleStart = () => {
    if (!currentVersion) return;
    createRfRun.mutate(
      {
        scene_version_id: currentVersion.id,
        run_type: 'forward',
      },
      { onSuccess: (data) => setActiveRunId(data.id) },
    );
  };

  const handleReset = () => {
    setActiveRunId(null);
  };

  // 메트릭 추출 (백엔드가 metrics_json 안에 다양한 키로 넣을 수 있어 유연하게)
  const metrics = parseMetrics(
    rfRunPoll.rfRun?.metrics_json,
    rfMapsQuery.data?.[0]?.metrics_json,
  );

  // 시뮬레이션 기록 — 현재 실행 + (TODO: 과거 RF runs 목록)
  const history: SimulationHistoryItem[] = currentVersion
    ? [
        ...(rfRunPoll.isSucceeded
          ? [
              {
                id: `run-${activeRunId}`,
                label: `시뮬레이션 결과 #${rfRunPoll.rfRun?.id?.slice(0, 6) ?? ''}`,
                timeLabel: '방금 전',
                avgRssiDbm: metrics.avgRssiDbm ?? 0,
                coveragePercent: metrics.coveragePercent ?? 0,
                active: true,
              },
            ]
          : []),
      ]
    : [];

  return (
    <div className="relative flex h-full flex-col p-6">
      <PageHeader
        state={state}
        hasVersion={!!currentVersion}
        isStarting={createRfRun.isPending}
        onStart={handleStart}
        onReset={handleReset}
      />

      {!floorId ? (
        <EmptyState
          title="층을 선택해주세요"
          subtitle="대시보드에서 층을 선택하면 시뮬레이션을 시작할 수 있습니다."
        />
      ) : versionsQuery.isLoading ? (
        <EmptyState title="버전 정보를 불러오는 중..." />
      ) : !currentVersion ? (
        <EmptyState
          title="확정된 도면 버전이 없습니다"
          subtitle="공간 편집에서 도면을 분석·확정한 후 시뮬레이션을 실행할 수 있습니다."
          ctaLabel="공간 편집으로 이동"
          ctaTo="/editor"
        />
      ) : (
        <div
          className={
            expanded
              ? 'mt-5 grid min-h-0 flex-1 grid-cols-1 gap-6'
              : 'mt-5 grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]'
          }
        >
          <div className="min-h-0">
            <SimulationCanvas
              state={state}
              scene={MOCK_SIMULATION_FLOOR_SCENE}
              heatmap={MOCK_SIMULATION_HEATMAP}
              expanded={expanded}
              onToggleExpand={() => setExpanded((v) => !v)}
            />
          </div>

          {!expanded && (
            <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
              {state === 'complete' && (
                <SimulationResultCard
                  avgRssiDbm={metrics.avgRssiDbm ?? -65}
                  coveragePercent={metrics.coveragePercent ?? 0}
                />
              )}
              <SimulationHistory
                items={history}
                showCompareButton={false}
              />
            </aside>
          )}
        </div>
      )}

      <HelpFab />
    </div>
  );
}

function PageHeader({
  state,
  hasVersion,
  isStarting,
  onStart,
  onReset,
}: {
  state: SimulationState;
  hasVersion: boolean;
  isStarting: boolean;
  onStart: () => void;
  onReset: () => void;
}) {
  return (
    <header className="flex items-start justify-between gap-4">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">시뮬레이션</h1>
        <p className="text-sm text-muted-foreground">
          저장된 도면을 불러와 가구와 AP를 자유롭게 배치하고 예상 품질을 비교합니다.
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {state === 'idle' ? (
          <button
            type="button"
            onClick={onStart}
            disabled={!hasVersion || isStarting}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-4 w-4 fill-current" />
            {isStarting ? '요청 중...' : '시뮬레이션 실행'}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={onReset}
              className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm font-medium text-foreground/80 shadow-sm hover:bg-accent"
            >
              <RotateCcw className="h-4 w-4" />
              배치 다시하기
            </button>
            <button
              type="button"
              disabled={state === 'running'}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              시뮬레이션 저장하기
            </button>
          </>
        )}
      </div>
    </header>
  );
}

function EmptyState({
  title,
  subtitle,
  ctaLabel,
  ctaTo,
}: {
  title: string;
  subtitle?: string;
  ctaLabel?: string;
  ctaTo?: string;
}) {
  return (
    <div className="mt-5 flex flex-1 items-center justify-center">
      <div className="flex max-w-md flex-col items-center gap-3 rounded-xl border border-dashed bg-background p-10 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
          <MapIcon className="h-6 w-6 text-primary" strokeWidth={1.8} />
        </div>
        <p className="text-base font-semibold">{title}</p>
        {subtitle && (
          <p className="text-xs leading-relaxed text-muted-foreground">{subtitle}</p>
        )}
        {ctaLabel && ctaTo && (
          <Link
            to={ctaTo}
            className="mt-2 inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            {ctaLabel}
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        )}
      </div>
    </div>
  );
}

/**
 * 백엔드 metrics_json 에서 표시용 값 추출.
 * AI 서버가 다양한 키로 넣을 수 있어 흔히 쓰이는 키들을 fallback 순으로 확인.
 */
function parseMetrics(
  ...sources: Array<Record<string, unknown> | undefined>
): { avgRssiDbm: number | null; coveragePercent: number | null } {
  const merged: Record<string, unknown> = {};
  for (const s of sources) {
    if (s) Object.assign(merged, s);
  }
  const pickNumber = (...keys: string[]): number | null => {
    for (const k of keys) {
      const v = merged[k];
      if (typeof v === 'number' && Number.isFinite(v)) return v;
      if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) {
        return Number(v);
      }
    }
    return null;
  };
  return {
    avgRssiDbm: pickNumber('avg_rssi_dbm', 'avg_dbm', 'rssi_avg', 'avg_rssi'),
    coveragePercent: pickNumber('coverage_percent', 'coverage', 'coverage_pct'),
  };
}
