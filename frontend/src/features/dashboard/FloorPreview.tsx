import { Maximize2, Minimize2, Loader2, Wifi } from 'lucide-react';
import type { FloorAp, FloorObject, FloorRoom, FloorScene } from '@/types/floor-scene';

interface Props {
  scene: FloorScene;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

export function FloorPreview({ scene, expanded, onToggleExpand }: Props) {
  const { viewBox } = scene;
  return (
    <div className="relative h-full w-full rounded-md border bg-[#f8fafc] p-4 [background-image:radial-gradient(circle,_oklch(0.92_0_0)_1px,_transparent_1px)] [background-position:0_0] [background-size:18px_18px]">
      <div className="absolute right-4 top-4 z-10">
        <button
          type="button"
          onClick={onToggleExpand}
          aria-label={expanded ? '축소' : '확대'}
          className="flex h-8 w-8 items-center justify-center rounded-md border bg-background shadow-sm hover:bg-accent"
        >
          {expanded ? (
            <Minimize2 className="h-4 w-4 text-muted-foreground" />
          ) : (
            <Maximize2 className="h-4 w-4 text-muted-foreground" />
          )}
        </button>
      </div>

      <div className="relative mx-auto flex h-full max-w-3xl items-center justify-center">
        <svg
          viewBox={`0 0 ${viewBox.width} ${viewBox.height}`}
          preserveAspectRatio="xMidYMid meet"
          className="h-full w-full"
        >
          {/* 외곽 도면 */}
          <rect
            x="60"
            y="80"
            width={viewBox.width - 120}
            height={viewBox.height - 140}
            rx="6"
            fill="white"
            stroke="oklch(0.85 0 0)"
            strokeWidth="2"
          />
          <line
            x1="290"
            y1="80"
            x2="290"
            y2={viewBox.height - 60}
            stroke="oklch(0.88 0 0)"
            strokeWidth="2"
          />

          {scene.rooms.map((room) => (
            <RoomShape key={room.id} room={room} />
          ))}

          {scene.objects.map((obj) =>
            obj.id === scene.selectedObjectId ? (
              <SelectedObject key={obj.id} obj={obj} />
            ) : (
              <FurnitureShape key={obj.id} obj={obj} />
            ),
          )}

          {scene.aps.map((ap) => (
            <ApMarker key={ap.id} ap={ap} />
          ))}
        </svg>

        <div className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2">
          <div className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-xs font-medium text-white shadow-lg">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Live preview loading, interactions may not be saved
          </div>
        </div>
      </div>
    </div>
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
  // 현재는 rect 만 지원 (Figma 시안 기준).
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
