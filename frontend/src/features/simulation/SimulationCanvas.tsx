import {
  CheckCircle2,
  Loader2,
  MousePointer2,
  Maximize2,
  Minimize2,
  RotateCw,
  Wifi,
} from 'lucide-react';
import { ApPaletteMenu } from './ApPaletteMenu';

export type SimulationState = 'idle' | 'running' | 'complete';

interface Props {
  state: SimulationState;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

export function SimulationCanvas({ state, expanded, onToggleExpand }: Props) {
  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-2xl border bg-[#f8fafc] [background-image:radial-gradient(circle,_oklch(0.92_0_0)_1px,_transparent_1px)] [background-position:0_0] [background-size:18px_18px]">
      <div className="relative z-10 flex items-start justify-between gap-3 p-5">
        <div className="flex flex-col gap-2">
          <TopLeftBadge state={state} />
          {state === 'complete' && (
            <div className="inline-flex w-fit items-center gap-4 rounded-lg border bg-background/90 px-4 py-2 text-xs shadow-sm backdrop-blur">
              <span className="font-semibold text-foreground/80">품질 예측 보기</span>
              <span className="h-3 w-px bg-border" />
              <LegendDot color="bg-emerald-500" label="양호" />
              <LegendDot color="bg-amber-400" label="보통" />
              <LegendDot color="bg-red-500" label="취약" />
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onToggleExpand}
          aria-label={expanded ? '축소' : '확대'}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border bg-background shadow-sm transition-colors hover:bg-accent"
        >
          {expanded ? (
            <Minimize2 className="h-4 w-4 text-muted-foreground" />
          ) : (
            <Maximize2 className="h-4 w-4 text-muted-foreground" />
          )}
        </button>
      </div>

      {state === 'idle' && (
        <div className="absolute right-5 top-20 z-10">
          <ApPaletteMenu />
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <div
          className={
            state === 'running'
              ? 'pointer-events-none h-full w-full blur-sm'
              : 'h-full w-full'
          }
        >
          <FloorPlanSvg
            withHeatmap={state === 'complete'}
            withSelection={state === 'idle'}
          />
        </div>

        {state === 'running' && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 px-6 text-center">
            <Loader2 className="h-16 w-16 animate-spin text-primary" strokeWidth={2.5} />
            <h3 className="text-lg font-bold">공간 기반 와이파이 품질을 분석중입니다</h3>
            <p className="text-sm leading-relaxed text-muted-foreground">
              도면의 구조와 장애물을 파악하여
              <br />
              전파 도달 범위를 계산하고 있습니다...
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function TopLeftBadge({ state }: { state: SimulationState }) {
  if (state === 'idle') {
    return (
      <div className="absolute left-5 top-5 z-10 inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm shadow-sm">
        <MousePointer2 className="h-4 w-4 text-primary" />
        <span className="font-semibold">도면 배치 모드</span>
        <span className="text-muted-foreground">- AP와 가구를 드래그하여 이동할 수 있습니다.</span>
      </div>
    );
  }
  if (state === 'running') {
    return (
      <div className="absolute left-5 top-5 z-10 inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm shadow-sm">
        <RotateCw className="h-4 w-4 animate-spin text-primary" />
        <span className="font-semibold">전파 도달 범위 계산 중...</span>
      </div>
    );
  }
  return (
    <div className="absolute left-5 top-5 z-10 inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2 text-sm shadow-sm">
      <CheckCircle2 className="h-4 w-4 text-emerald-600" />
      <span className="font-semibold text-emerald-700">시뮬레이션 완료 (새로운 배치)</span>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`block h-2.5 w-2.5 rounded-full ${color}`} />
      <span className="text-foreground/80">{label}</span>
    </span>
  );
}

interface FloorPlanSvgProps {
  withHeatmap: boolean;
  withSelection: boolean;
}

function FloorPlanSvg({ withHeatmap, withSelection }: FloorPlanSvgProps) {
  return (
    <svg
      viewBox="0 0 800 520"
      preserveAspectRatio="xMidYMid meet"
      className="h-full w-full p-4"
    >
      <defs>
        <radialGradient id="sim-bad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="oklch(0.62 0.22 25)" stopOpacity="0.55" />
          <stop offset="80%" stopColor="oklch(0.62 0.22 25)" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="sim-warn" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="oklch(0.85 0.18 85)" stopOpacity="0.5" />
          <stop offset="80%" stopColor="oklch(0.85 0.18 85)" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="sim-good" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="oklch(0.72 0.18 145)" stopOpacity="0.5" />
          <stop offset="80%" stopColor="oklch(0.72 0.18 145)" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect
        x="60"
        y="100"
        width="680"
        height="380"
        rx="6"
        fill="white"
        stroke="oklch(0.85 0 0)"
        strokeWidth="2"
      />
      <line
        x1="290"
        y1="100"
        x2="290"
        y2="480"
        stroke="oklch(0.88 0 0)"
        strokeWidth="2"
      />

      {withHeatmap && (
        <g>
          <ellipse cx="500" cy="280" rx="280" ry="200" fill="url(#sim-good)" />
          <ellipse cx="600" cy="200" rx="160" ry="120" fill="url(#sim-good)" />
          <ellipse cx="170" cy="400" rx="160" ry="130" fill="url(#sim-bad)" />
          <ellipse cx="540" cy="380" rx="80" ry="60" fill="url(#sim-warn)" />
        </g>
      )}

      {/* 주방/카운터 */}
      <g>
        <rect x="100" y="140" width="160" height="100" rx="8" fill="oklch(0.92 0 0)" />
        <text
          x="180"
          y="196"
          textAnchor="middle"
          className="fill-foreground/70"
          style={{ fontSize: '15px', fontWeight: 500 }}
        >
          주방 / 카운터
        </text>
      </g>
      {/* 창고 */}
      <g>
        <rect x="100" y="280" width="160" height="100" rx="8" fill="oklch(0.92 0 0)" />
        <text
          x="180"
          y="336"
          textAnchor="middle"
          className="fill-foreground/70"
          style={{ fontSize: '15px', fontWeight: 500 }}
        >
          창고
        </text>
      </g>

      {/* 테이블 우상 */}
      <g>
        <circle cx="600" cy="190" r="42" fill="oklch(0.95 0.04 256)" />
        <text
          x="600"
          y="196"
          textAnchor="middle"
          className="fill-primary/80"
          style={{ fontSize: '13px', fontWeight: 500 }}
        >
          테이블
        </text>
      </g>
      {/* 테이블 좌하 */}
      <g>
        <circle cx="380" cy="380" r="38" fill="oklch(0.95 0.04 256)" />
        <text
          x="380"
          y="386"
          textAnchor="middle"
          className="fill-primary/80"
          style={{ fontSize: '13px', fontWeight: 500 }}
        >
          테이블
        </text>
      </g>
      {/* 단체석 */}
      <g>
        <rect x="610" y="370" width="90" height="48" rx="6" fill="oklch(0.95 0.04 256)" />
        <text
          x="655"
          y="400"
          textAnchor="middle"
          className="fill-primary/80"
          style={{ fontSize: '13px', fontWeight: 500 }}
        >
          단체석
        </text>
      </g>

      {/* 선택된 사각형 (idle 일 때만 핸들 표시) */}
      {withSelection ? (
        <g>
          <rect
            x="440"
            y="290"
            width="140"
            height="80"
            rx="4"
            fill="white"
            stroke="oklch(0.55 0.22 264)"
            strokeWidth="2"
          />
          <Handle cx={440} cy={290} />
          <Handle cx={580} cy={290} />
          <Handle cx={440} cy={370} />
          <Handle cx={580} cy={370} />
          <rect x="565" y="282" width="14" height="14" fill="oklch(0.2 0 0)" />
          <line
            x1="510"
            y1="290"
            x2="510"
            y2="252"
            stroke="oklch(0.55 0.22 264)"
            strokeWidth="2"
          />
          <circle cx="510" cy="244" r="11" fill="oklch(0.55 0.22 264)" />
          <text
            x="510"
            y="248"
            textAnchor="middle"
            fill="white"
            style={{ fontSize: '11px', fontWeight: 600 }}
          >
            ↑
          </text>
        </g>
      ) : (
        <rect x="500" y="330" width="14" height="14" fill="oklch(0.2 0 0)" />
      )}

      <ApMarker cx={430} cy={190} label="AP 1" />
      <ApMarker cx={685} cy={465} label="AP 2" />
    </svg>
  );
}

function Handle({ cx, cy }: { cx: number; cy: number }) {
  return (
    <circle
      cx={cx}
      cy={cy}
      r="7"
      fill="white"
      stroke="oklch(0.55 0.22 264)"
      strokeWidth="2"
    />
  );
}

function ApMarker({ cx, cy, label }: { cx: number; cy: number; label: string }) {
  return (
    <g>
      <circle cx={cx} cy={cy} r="22" fill="oklch(0.55 0.22 264)" />
      <foreignObject x={cx - 9} y={cy - 9} width="18" height="18">
        <Wifi className="h-[18px] w-[18px] text-white" />
      </foreignObject>
      <text
        x={cx}
        y={cy + 42}
        textAnchor="middle"
        className="fill-foreground"
        style={{ fontSize: '12px', fontWeight: 600 }}
      >
        {label}
      </text>
    </g>
  );
}
