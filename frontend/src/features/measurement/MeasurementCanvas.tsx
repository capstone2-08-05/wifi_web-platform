import { Wifi } from 'lucide-react';
import type {
  FloorAp,
  FloorObject,
  FloorRoom,
  FloorScene,
  HeatmapRegion,
} from '@/types/floor-scene';
import type { MeasurementPoint, MeasurementSeverity } from './mocks';

export type MeasurementView = 'path' | 'heatmap' | 'combined';

interface Props {
  view: MeasurementView;
  scene: FloorScene;
  points: MeasurementPoint[];
  heatmap?: HeatmapRegion[];
}

const SEVERITY_COLOR: Record<MeasurementSeverity, string> = {
  good: 'oklch(0.72 0.18 145)',
  warning: 'oklch(0.78 0.15 85)',
  bad: 'oklch(0.62 0.22 25)',
};

export function MeasurementCanvas({ view, scene, points, heatmap }: Props) {
  const showHeatmap = (view === 'heatmap' || view === 'combined') && !!heatmap?.length;
  const showPath = view === 'path' || view === 'combined';
  const { viewBox } = scene;

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-md border bg-[#f8fafc] [background-image:radial-gradient(circle,_oklch(0.92_0_0)_1px,_transparent_1px)] [background-position:0_0] [background-size:18px_18px]">
      <div className="p-4">
        <Legend />
      </div>

      <div className="relative min-h-0 flex-1">
        <svg
          viewBox={`0 0 ${viewBox.width} ${viewBox.height}`}
          preserveAspectRatio="xMidYMid meet"
          className="h-full w-full p-4"
        >
          <defs>
            <radialGradient id="hot-bad" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="oklch(0.62 0.22 25)" stopOpacity="0.55" />
              <stop offset="80%" stopColor="oklch(0.62 0.22 25)" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="hot-warn" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="oklch(0.85 0.18 85)" stopOpacity="0.55" />
              <stop offset="80%" stopColor="oklch(0.85 0.18 85)" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="hot-good" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="oklch(0.72 0.18 145)" stopOpacity="0.5" />
              <stop offset="80%" stopColor="oklch(0.72 0.18 145)" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* 외곽 도면 */}
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

          {/* 히트맵 레이어 */}
          {showHeatmap && heatmap && (
            <g>
              {heatmap.map((r, i) => (
                <ellipse
                  key={`h-${i}`}
                  cx={r.cx}
                  cy={r.cy}
                  rx={r.rx}
                  ry={r.ry}
                  fill={`url(#hot-${r.intensity})`}
                />
              ))}
            </g>
          )}

          {scene.rooms.map((room) => (
            <RoomShape key={room.id} room={room} />
          ))}

          {scene.objects.map((obj) => (
            <FurnitureShape key={obj.id} obj={obj} />
          ))}

          {/* 검은 작은 사각형 (선택된 객체 표시 / 측정 마커 anchor) — 시안 일관성 */}
          <rect x="500" y="330" width="14" height="14" fill="oklch(0.2 0 0)" />

          {/* 경로 (path, combined 탭에서만) */}
          {showPath && (
            <g>
              <polyline
                points={points.map((p) => `${p.x},${p.y}`).join(' ')}
                fill="none"
                stroke="oklch(0.55 0.22 264)"
                strokeWidth="2.5"
                strokeDasharray="6 5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {points.map((p) => (
                <circle
                  key={p.id}
                  cx={p.x}
                  cy={p.y}
                  r="8"
                  fill={SEVERITY_COLOR[p.severity]}
                  stroke="white"
                  strokeWidth="2.5"
                />
              ))}
            </g>
          )}

          {scene.aps.map((ap) => (
            <ApMarker key={ap.id} ap={ap} />
          ))}
        </svg>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="inline-flex items-center gap-4 rounded-lg border bg-background/90 px-4 py-2 text-xs shadow-sm backdrop-blur">
      <span className="font-semibold text-foreground/80">실측 포인트 범례</span>
      <span className="h-3 w-px bg-border" />
      <LegendDot color="bg-emerald-500" label="양호" />
      <LegendDot color="bg-amber-400" label="주의" />
      <LegendDot color="bg-red-500" label="불량" />
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
