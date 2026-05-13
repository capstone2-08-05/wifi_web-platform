import { useEffect, useRef, useState } from 'react';
import { Play, RotateCcw, Save } from 'lucide-react';
import { HelpFab } from '@/components/HelpFab';
import {
  SimulationCanvas,
  type SimulationState,
} from '@/features/simulation/SimulationCanvas';
import { SimulationResultCard } from '@/features/simulation/SimulationResultCard';
import { SimulationHistory } from '@/features/simulation/SimulationHistory';
import {
  MOCK_SIMULATION_FLOOR_SCENE,
  MOCK_SIMULATION_HEATMAP,
  MOCK_SIMULATION_HISTORY_BASE,
  MOCK_SIMULATION_NEW_RESULT,
} from '@/features/simulation/mocks';

const SIM_DURATION_MS = 2500;

export default function SimulationPage() {
  const [state, setState] = useState<SimulationState>('idle');
  const [expanded, setExpanded] = useState(false);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
  }, []);

  const startSimulation = () => {
    setState('running');
    timerRef.current = window.setTimeout(() => setState('complete'), SIM_DURATION_MS);
  };

  const resetSimulation = () => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    setState('idle');
  };

  const history =
    state === 'complete' ? [MOCK_SIMULATION_NEW_RESULT, ...MOCK_SIMULATION_HISTORY_BASE] : MOCK_SIMULATION_HISTORY_BASE;

  return (
    <div className="relative flex h-full flex-col p-6">
      <PageHeader
        state={state}
        onStart={startSimulation}
        onReset={resetSimulation}
      />

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
                avgRssiDbm={MOCK_SIMULATION_NEW_RESULT.avgRssiDbm}
                coveragePercent={MOCK_SIMULATION_NEW_RESULT.coveragePercent}
              />
            )}
            <SimulationHistory
              items={history}
              showCompareButton={state !== 'idle' && history.length >= 2}
            />
          </aside>
        )}
      </div>

      <HelpFab />
    </div>
  );
}

function PageHeader({
  state,
  onStart,
  onReset,
}: {
  state: SimulationState;
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
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
          >
            <Play className="h-4 w-4 fill-current" />
            시뮬레이션 실행
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

