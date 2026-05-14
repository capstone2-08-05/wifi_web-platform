import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CheckCircle2,
  ChevronRight,
  Loader2,
  Map as MapIcon,
  Play,
  RotateCcw,
  Sparkles,
  Trash2,
  Wifi,
} from 'lucide-react';
import { useAppStore } from '@/stores/app-store';
import { useFloorVersions } from '@/hooks/use-scene-version';
import { useCreateRfRun, useRfMaps, useRfRun } from '@/hooks/use-rf-run';
import {
  useApCandidates,
  useApLayouts,
  useCreateApLayout,
  useDeleteApLayout,
  useGenerateApCandidates,
} from '@/hooks/use-ap-layouts';
import { HelpFab } from '@/components/HelpFab';
import { SimulationResultCard } from '@/features/simulation/SimulationResultCard';
import {
  SimulationHistory,
  type SimulationHistoryItem,
} from '@/features/simulation/SimulationHistory';
import type { ApCandidate, ApLayout } from '@/types/ap-layout';

type SimulationState = 'idle' | 'running' | 'complete';

export default function SimulationPage() {
  const floorId = useAppStore((s) => s.selectedFloorId);
  const versionsQuery = useFloorVersions(floorId);
  // 현재 활성 버전 (없으면 가장 최근 버전)
  const currentVersion =
    versionsQuery.data?.find((v) => v.is_current) ?? versionsQuery.data?.[0] ?? null;

  const [activeRunId, setActiveRunId] = useState<string | null>(null);

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
        <div className="mt-5 grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
          <div className="min-h-0 rounded-2xl border bg-background p-6 shadow-sm">
            <SimulationVisualization
              state={state}
              mapUrl={rfMapsQuery.data?.[0]?.storage_url}
            />
          </div>

          <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
            {state === 'complete' && (
              <SimulationResultCard
                avgRssiDbm={metrics.avgRssiDbm ?? -65}
                coveragePercent={metrics.coveragePercent ?? 0}
              />
            )}
            {state === 'complete' && activeRunId && (
              <ApPlacementPanel rfRunId={activeRunId} />
            )}
            <SimulationHistory items={history} showCompareButton={false} />
          </aside>
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
          <button
            type="button"
            onClick={onReset}
            className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm font-medium text-foreground/80 shadow-sm hover:bg-accent"
          >
            <RotateCcw className="h-4 w-4" />
            다시 실행
          </button>
        )}
      </div>
    </header>
  );
}

function SimulationVisualization({
  state,
  mapUrl,
}: {
  state: SimulationState;
  mapUrl?: string;
}) {
  if (state === 'idle') {
    return (
      <div className="flex h-full min-h-80 flex-col items-center justify-center gap-2 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
          <Play className="h-5 w-5 text-primary" />
        </div>
        <p className="text-sm font-medium">시뮬레이션 실행 대기 중</p>
        <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
          상단의 시뮬레이션 실행 버튼을 누르면 확정된 도면 기준으로 RF 시뮬레이션이 시작됩니다.
        </p>
      </div>
    );
  }
  if (state === 'running') {
    return (
      <div className="flex h-full min-h-80 flex-col items-center justify-center gap-2 text-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-sm font-medium">RF 시뮬레이션 진행 중</p>
        <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
          서버에서 결과를 계산하는 동안 잠시만 기다려주세요. 최대 약 15분이 소요될 수 있습니다.
        </p>
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col gap-3">
      {mapUrl ? (
        <img
          src={mapUrl}
          alt="RF 시뮬레이션 결과 맵"
          className="w-full flex-1 rounded-md object-contain"
          loading="lazy"
        />
      ) : (
        <div className="flex h-full min-h-80 flex-col items-center justify-center gap-2 text-center">
          <MapIcon className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm font-medium">결과 맵을 불러오는 중입니다</p>
          <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
            잠시 후 자동으로 표시됩니다.
          </p>
        </div>
      )}
    </div>
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
 * §14 AP 후보/배치 패널.
 * RF Run 이 succeeded 된 후에만 표시되고, 후보 생성 + 후보 선택 → 배치 저장 흐름.
 */
function ApPlacementPanel({ rfRunId }: { rfRunId: string }) {
  const generate = useGenerateApCandidates();
  const candidatesQuery = useApCandidates(rfRunId);
  const layoutsQuery = useApLayouts(rfRunId);
  const createLayout = useCreateApLayout();
  const deleteLayout = useDeleteApLayout(rfRunId);

  const candidates = candidatesQuery.data ?? [];
  const layouts = layoutsQuery.data ?? [];

  const handleGenerate = () => generate.mutate({ rf_run_id: rfRunId, candidate_type: 'auto' });

  const handleConfirmCandidate = (c: ApCandidate) => {
    if (!c.point_geom) return;
    const seq = layouts.length + 1;
    createLayout.mutate({
      rf_run_id: rfRunId,
      ap_name: `AP-${String(seq).padStart(2, '0')}`,
      point_geom: c.point_geom,
      z_m: c.z_m ?? 2.5,
    });
  };

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <Wifi className="h-4 w-4 text-primary" />
          AP 배치 (§14)
        </h3>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={generate.isPending}
          className="inline-flex items-center gap-1 rounded-md border bg-background px-2.5 py-1 text-xs font-medium hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {generate.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          {candidates.length > 0 ? '재생성' : '후보 생성'}
        </button>
      </div>

      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        시뮬레이션 결과 기반 추천 위치를 확인하고, 마음에 드는 후보를 확정해 배치를 저장하세요.
      </p>

      <section className="mt-3">
        <p className="mb-1.5 text-[11px] font-semibold text-muted-foreground">후보 ({candidates.length})</p>
        {candidatesQuery.isLoading ? (
          <p className="py-2 text-[11px] text-muted-foreground">불러오는 중...</p>
        ) : candidates.length === 0 ? (
          <p className="py-2 text-[11px] text-muted-foreground">
            아직 생성된 후보가 없습니다. 위 버튼으로 생성하세요.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {candidates.map((c) => (
              <li
                key={c.id}
                className="flex items-center justify-between gap-2 rounded-md border bg-background px-2.5 py-1.5 text-xs"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium">
                      {c.score != null ? `점수 ${c.score.toFixed(2)}` : '점수 N/A'}
                    </span>
                    <span className="rounded bg-muted px-1.5 text-[10px] uppercase text-muted-foreground">
                      {c.candidate_type}
                    </span>
                  </div>
                  <p className="truncate text-[10px] text-muted-foreground">
                    {formatPoint(c.point_geom)} · z={c.z_m ?? '?'} m
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => handleConfirmCandidate(c)}
                  disabled={createLayout.isPending}
                  className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                >
                  <CheckCircle2 className="h-3 w-3" />
                  배치
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-3">
        <p className="mb-1.5 text-[11px] font-semibold text-muted-foreground">확정된 배치 ({layouts.length})</p>
        {layoutsQuery.isLoading ? (
          <p className="py-2 text-[11px] text-muted-foreground">불러오는 중...</p>
        ) : layouts.length === 0 ? (
          <p className="py-2 text-[11px] text-muted-foreground">
            아직 확정된 AP 배치가 없습니다.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {layouts.map((l) => (
              <ApLayoutRow
                key={l.id}
                layout={l}
                onDelete={() => deleteLayout.mutate(l.id)}
                disabled={deleteLayout.isPending}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ApLayoutRow({
  layout,
  onDelete,
  disabled,
}: {
  layout: ApLayout;
  onDelete: () => void;
  disabled: boolean;
}) {
  return (
    <li className="flex items-center justify-between gap-2 rounded-md border bg-background px-2.5 py-1.5 text-xs">
      <div className="min-w-0">
        <div className="font-medium">{layout.ap_name}</div>
        <p className="truncate text-[10px] text-muted-foreground">
          {formatPoint(layout.point_geom)} · z={layout.z_m ?? '?'} m
        </p>
      </div>
      <button
        type="button"
        onClick={onDelete}
        disabled={disabled}
        aria-label="삭제"
        className="rounded-md p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </li>
  );
}

function formatPoint(geom: Record<string, unknown> | null): string {
  if (!geom) return '좌표 없음';
  const coords = (geom as { coordinates?: unknown }).coordinates;
  if (Array.isArray(coords) && coords.length >= 2) {
    const x = Number(coords[0]);
    const y = Number(coords[1]);
    if (Number.isFinite(x) && Number.isFinite(y)) {
      return `(${x.toFixed(2)}, ${y.toFixed(2)})`;
    }
  }
  return '좌표 형식 오류';
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
