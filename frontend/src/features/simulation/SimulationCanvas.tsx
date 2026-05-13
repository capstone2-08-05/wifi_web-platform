import {
  CheckCircle2,
  Loader2,
  MousePointer2,
  Maximize2,
  Minimize2,
  RotateCw,
  Wifi,
} from 'lucide-react';
import type {
  FloorAp,
  FloorObject,
  FloorRoom,
  FloorScene,
  HeatmapRegion,
} from '@/types/floor-scene';
import { ApPaletteMenu } from './ApPaletteMenu';

export type SimulationState = 'idle' | 'running' | 'complete';

interface Props {
  state: SimulationState;
  scene: FloorScene;
  heatmap?: HeatmapRegion[];
  expanded?: boolean;
  onToggleExpand?: () => void;
}

export function SimulationCanvas({
  state,
  scene,
  heatmap,
  expanded,
  onToggleExpand,
}: Props) {
  const showHeatmap = state === 'complete' && !!heatmap?.length;
  const showSelection = state === 'idle';

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
            scene={scene}
            heatmap={showHeatmap ? heatmap : undefined}
            withSelection={showSelection}
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
      <div className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm shadow-sm">
        <MousePointer2 className="h-4 w-4 text-primary" />
        <span className="font-semibold">도면 배치 모드</span>
        <span className="text-muted-foreground">- AP와 가구를 드래그하여 이동할 수 있습니다.</span>
      </div>
    );
  }
  if (state === 'running') {
    return (
      <div className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-sm shadow-sm">
        <RotateCw className="h-4 w-4 animate-spin text-primary" />
        <span className="font-semibold">전파 도달 범위 계산 중...</span>
      </div>
    );
  }
  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2 text-sm shadow-sm">
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
  scene: FloorScene;
  heatmap?: HeatmapRegion[];
  withSelection: boolean;
}

function FloorPlanSvg({ scene, heatmap, withSelection }: FloorPlanSvgProps) {
  const { viewBox } = scene;
  return (
    <svg
      viewBox={`0 0 ${viewBox.width} ${viewBox.height}`}
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
        width={viewBox.width - 120}
        height={viewBox.height - 140}
        rx="6"
        fill="white"
        stroke="oklch(0.85 0 0)"
        strokeWidth="2"
      />
      <line
        x1="290"
        y1="100"
        x2="290"
        y2={viewBox.height - 40}
        stroke="oklch(0.88 0 0)"
        strokeWidth="2"
      />

      {heatmap && (
        <g>
          {heatmap.map((r, i) => (
            <ellipse
              key={`h-${i}`}
              cx={r.cx}
              cy={r.cy}
              rx={r.rx}
              ry={r.ry}
              fill={`url(#sim-${r.intensity})`}
            />
          ))}
        </g>
      )}

      {scene.rooms.map((room) => (
        <RoomShape key={room.id} room={room} />
      ))}

      {scene.objects.map((obj) =>
        obj.id === scene.selectedObjectId ? (
          withSelection ? (
            <SelectedObject key={obj.id} obj={obj} />
          ) : (
            <BlackAnchor key={obj.id} obj={obj} />
          )
        ) : (
          <FurnitureShape key={obj.id} obj={obj} />
        ),
      )}

      {scene.aps.map((ap) => (
        <ApMarker key={ap.id} ap={ap} />
      ))}
    </svg>
  );
}

function RoomShape({ room }: { room: FloorRoom }) {
  return (
    <g>
      <rect
        x={room.x}
        y={room.y}
        width={room.width}
        height={room.height}
        rx="8"
        fill="oklch(0.92 0 0)"
      />
      <text
        x={room.x + room.width / 2}
        y={room.y + room.height / 2 + 6}
        textAnchor="middle"
        className="fill-foreground/70"
        style={{ fontSize: '15px', fontWeight: 500 }}
      >
        {room.label}
      </text>
    </g>
  );
}

function FurnitureShape({ obj }: { obj: FloorObject }) {
  if (obj.shape === 'circle') {
    const { cx = 0, cy = 0, r = 30 } = obj;
    return (
      <g>
        <circle cx={cx} cy={cy} r={r} fill="oklch(0.95 0.04 256)" />
        <text
          x={cx}
          y={cy + 6}
          textAnchor="middle"
          className="fill-primary/80"
          style={{ fontSize: '13px', fontWeight: 500 }}
        >
          {obj.label}
        </text>
      </g>
    );
  }
  const { x = 0, y = 0, width = 0, height = 0 } = obj;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} rx="6" fill="oklch(0.95 0.04 256)" />
      <text
        x={x + width / 2}
        y={y + height / 2 + 5}
        textAnchor="middle"
        className="fill-primary/80"
        style={{ fontSize: '13px', fontWeight: 500 }}
      >
        {obj.label}
      </text>
    </g>
  );
}

function SelectedObject({ obj }: { obj: FloorObject }) {
  if (obj.shape !== 'rect') return <FurnitureShape obj={obj} />;
  const { x = 0, y = 0, width = 0, height = 0 } = obj;
  const cxCenter = x + width / 2;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx="4"
        fill="white"
        stroke="oklch(0.55 0.22 264)"
        strokeWidth="2"
      />
      <Handle cx={x} cy={y} />
      <Handle cx={x + width} cy={y} />
      <Handle cx={x} cy={y + height} />
      <Handle cx={x + width} cy={y + height} />
      <rect x={x + width - 15} y={y - 8} width="14" height="14" fill="oklch(0.2 0 0)" />
      <line
        x1={cxCenter}
        y1={y}
        x2={cxCenter}
        y2={y - 38}
        stroke="oklch(0.55 0.22 264)"
        strokeWidth="2"
      />
      <circle cx={cxCenter} cy={y - 46} r="11" fill="oklch(0.55 0.22 264)" />
      <text
        x={cxCenter}
        y={y - 42}
        textAnchor="middle"
        fill="white"
        style={{ fontSize: '11px', fontWeight: 600 }}
      >
        ↑
      </text>
    </g>
  );
}

function BlackAnchor({ obj }: { obj: FloorObject }) {
  // running/complete 상태에선 핸들 대신 작은 검은 anchor 만 표시 (시안 일관성).
  if (obj.shape !== 'rect') return null;
  const { x = 0, y = 0, width = 0, height = 0 } = obj;
  return (
    <rect
      x={x + width / 2 - 7}
      y={y + height / 2 - 7}
      width="14"
      height="14"
      fill="oklch(0.2 0 0)"
    />
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

function ApMarker({ ap }: { ap: FloorAp }) {
  return (
    <g>
      <circle cx={ap.cx} cy={ap.cy} r="22" fill="oklch(0.55 0.22 264)" />
      <foreignObject x={ap.cx - 9} y={ap.cy - 9} width="18" height="18">
        <Wifi className="h-[18px] w-[18px] text-white" />
      </foreignObject>
      <text
        x={ap.cx}
        y={ap.cy + 42}
        textAnchor="middle"
        className="fill-foreground"
        style={{ fontSize: '12px', fontWeight: 600 }}
      >
        {ap.label}
      </text>
    </g>
  );
}
