import { Maximize2, Minimize2, Loader2, Wifi } from 'lucide-react';

// 백엔드/캔버스 연동 전까지의 정적 미니 도면 시각화 (Figma 시안용).
// 좌표는 800x500 viewBox 기준.

interface Props {
  expanded?: boolean;
  onToggleExpand?: () => void;
}

export function FloorPreview({ expanded, onToggleExpand }: Props = {}) {
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
          viewBox="0 0 800 500"
          preserveAspectRatio="xMidYMid meet"
          className="h-full w-full"
        >
          {/* 외곽 도면 박스 */}
          <rect
            x="60"
            y="80"
            width="680"
            height="360"
            rx="6"
            fill="white"
            stroke="oklch(0.85 0 0)"
            strokeWidth="2"
          />

          {/* 왼쪽 구획 (주방/창고 영역) */}
          <line
            x1="290"
            y1="80"
            x2="290"
            y2="440"
            stroke="oklch(0.88 0 0)"
            strokeWidth="2"
          />

          {/* 주방/카운터 */}
          <g>
            <rect
              x="100"
              y="120"
              width="160"
              height="120"
              rx="8"
              fill="oklch(0.92 0 0)"
            />
            <text
              x="180"
              y="186"
              textAnchor="middle"
              className="fill-foreground/70"
              style={{ fontSize: '15px', fontWeight: 500 }}
            >
              주방 / 카운터
            </text>
          </g>

          {/* 창고 */}
          <g>
            <rect
              x="100"
              y="280"
              width="160"
              height="120"
              rx="8"
              fill="oklch(0.92 0 0)"
            />
            <text
              x="180"
              y="346"
              textAnchor="middle"
              className="fill-foreground/70"
              style={{ fontSize: '15px', fontWeight: 500 }}
            >
              창고
            </text>
          </g>

          {/* 테이블 (우상단 원) */}
          <g>
            <circle
              cx="600"
              cy="170"
              r="44"
              fill="oklch(0.95 0.04 256)"
            />
            <text
              x="600"
              y="176"
              textAnchor="middle"
              className="fill-primary/80"
              style={{ fontSize: '13px', fontWeight: 500 }}
            >
              테이블
            </text>
          </g>

          {/* 테이블 (좌하단 원) */}
          <g>
            <circle
              cx="370"
              cy="340"
              r="40"
              fill="oklch(0.95 0.04 256)"
            />
            <text
              x="370"
              y="346"
              textAnchor="middle"
              className="fill-primary/80"
              style={{ fontSize: '13px', fontWeight: 500 }}
            >
              테이블
            </text>
          </g>

          {/* 단체석 */}
          <g>
            <rect
              x="620"
              y="320"
              width="100"
              height="50"
              rx="6"
              fill="oklch(0.95 0.04 256)"
            />
            <text
              x="670"
              y="350"
              textAnchor="middle"
              className="fill-primary/80"
              style={{ fontSize: '13px', fontWeight: 500 }}
            >
              단체석
            </text>
          </g>

          {/* 선택된 테이블 (가운데, blue border + 핸들) */}
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
            {/* 4 corner handles */}
            <Handle cx={440} cy={290} />
            <Handle cx={580} cy={290} />
            <Handle cx={440} cy={370} />
            <Handle cx={580} cy={370} />
            {/* 우상단 검은 작은 탭 */}
            <rect
              x="565"
              y="282"
              width="14"
              height="14"
              fill="oklch(0.2 0 0)"
            />
            {/* 위쪽 회전 핸들 */}
            <line
              x1="510"
              y1="290"
              x2="510"
              y2="252"
              stroke="oklch(0.55 0.22 264)"
              strokeWidth="2"
            />
            <circle
              cx="510"
              cy="244"
              r="11"
              fill="oklch(0.55 0.22 264)"
            />
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

          {/* AP 1 — 상단 중앙 */}
          <ApMarker cx={430} cy={170} label="AP 1" />

          {/* AP 2 — 우하단 */}
          <ApMarker cx={680} cy={420} label="AP 2" />
        </svg>

        {/* Live preview loading 토스트 */}
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
      <g transform={`translate(${cx - 9}, ${cy - 9})`}>
        <foreignObject width="18" height="18">
          <Wifi className="h-[18px] w-[18px] text-white" />
        </foreignObject>
      </g>
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
