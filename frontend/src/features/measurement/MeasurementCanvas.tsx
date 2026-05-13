import { Wifi } from 'lucide-react';

export type MeasurementView = 'path' | 'heatmap' | 'combined';

interface Props {
  view: MeasurementView;
}

// 측정 포인트 (mock). 실제로는 GET /measurement-sessions/{id}/points 응답으로 받아야 함.
const POINTS = [
  { id: 'P-01', x: 420, y: 180, severity: 'good' as const },
  { id: 'P-02', x: 510, y: 180, severity: 'good' as const },
  { id: 'P-03', x: 510, y: 280, severity: 'good' as const },
  { id: 'P-04', x: 320, y: 280, severity: 'good' as const },
  { id: 'P-05', x: 320, y: 380, severity: 'bad' as const },
  { id: 'P-06', x: 510, y: 340, severity: 'warning' as const },
  { id: 'P-07', x: 640, y: 340, severity: 'good' as const },
  { id: 'P-08', x: 640, y: 440, severity: 'good' as const },
];

const SEVERITY_COLOR: Record<'good' | 'warning' | 'bad', string> = {
  good: 'oklch(0.72 0.18 145)',
  warning: 'oklch(0.78 0.15 85)',
  bad: 'oklch(0.62 0.22 25)',
};

export function MeasurementCanvas({ view }: Props) {
  const showHeatmap = view === 'heatmap' || view === 'combined';
  const showPath = view === 'path' || view === 'combined';

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-md border bg-[#f8fafc] [background-image:radial-gradient(circle,_oklch(0.92_0_0)_1px,_transparent_1px)] [background-position:0_0] [background-size:18px_18px]">
      <div className="p-4">
        <Legend />
      </div>

      <div className="relative min-h-0 flex-1">
        <svg
          viewBox="0 0 800 520"
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

          {/* 히트맵 레이어 (heatmap, combined 탭에서만) */}
          {showHeatmap && (
            <g>
              {/* 좋은 영역 (도면 가운데~우측) */}
              <ellipse cx="480" cy="270" rx="260" ry="190" fill="url(#hot-good)" />
              {/* 주의 영역 (가운데 약간 우측) */}
              <ellipse cx="540" cy="340" rx="100" ry="70" fill="url(#hot-warn)" />
              {/* 불량 영역 (좌하단 창고 앞) */}
              <ellipse cx="180" cy="400" rx="140" ry="110" fill="url(#hot-bad)" />
            </g>
          )}

          {/* 방/구획 */}
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

          {/* 가구 */}
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

          {/* 검은 작은 사각형 (선택된 객체 표시 / 측정 마커 anchor) */}
          <rect x="500" y="330" width="14" height="14" fill="oklch(0.2 0 0)" />

          {/* 경로 (path, combined 탭에서만) */}
          {showPath && (
            <g>
              <polyline
                points={POINTS.map((p) => `${p.x},${p.y}`).join(' ')}
                fill="none"
                stroke="oklch(0.55 0.22 264)"
                strokeWidth="2.5"
                strokeDasharray="6 5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {POINTS.map((p) => (
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

          {/* AP 마커 */}
          <ApMarker cx={430} cy={190} label="AP 1" />
          <ApMarker cx={685} cy={465} label="AP 2" />
        </svg>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="absolute left-4 top-4 z-10 inline-flex items-center gap-4 rounded-lg border bg-background/90 px-4 py-2 text-xs shadow-sm backdrop-blur">
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
