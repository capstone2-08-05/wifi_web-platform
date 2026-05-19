import { useMemo, useRef } from 'react';
import { parseGeometry } from '@/features/editor/geometry-utils';
import type {
  DraftObject,
  DraftOpening,
  DraftWall,
  SceneVersion,
} from '@/types/scene';
import { cn } from '@/lib/utils';

export type MeasurementPointQuality = 'good' | 'warning' | 'poor';

export interface MeasurementPoint {
  id: string;
  x_m: number;
  y_m: number;
  quality: MeasurementPointQuality;
  /** 시퀀스 표시용 — 측정 경로 라인 연결 순서. */
  order: number;
}

export interface PlacedApSimple {
  id: string;
  x_m: number;
  y_m: number;
  label?: string;
}

export type MeasurementViewMode = 'route' | 'heatmap' | 'both';

interface Props {
  sceneVersion: SceneVersion | null | undefined;
  points: MeasurementPoint[];
  aps: PlacedApSimple[];
  mode: MeasurementViewMode;
  /** 강조 표시할 측정 포인트 (불량 지점). 외곽 링이 진하게 표시됨. */
  highlightedPointId?: string | null;
}

interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function emptyBounds(): Bounds {
  return { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
}

function extendBounds(b: Bounds, x: number, y: number) {
  if (x < b.minX) b.minX = x;
  if (y < b.minY) b.minY = y;
  if (x > b.maxX) b.maxX = x;
  if (y > b.maxY) b.maxY = y;
}

/** viewBox 는 도형(walls/openings) 기준. 객체는 건물 밖으로 나갈 수 있어 제외. */
function computeViewBox(scene: SceneVersion | null | undefined) {
  const b = emptyBounds();
  for (const wall of scene?.walls ?? []) {
    const g = parseGeometry(wall.centerline_geom);
    if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
  }
  for (const op of scene?.openings ?? []) {
    const g = parseGeometry(op.line_geom);
    if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
  }
  if (!isFinite(b.minX)) return { x: 0, y: 0, w: 10, h: 10 };
  const w = b.maxX - b.minX || 1;
  const h = b.maxY - b.minY || 1;
  const padding = Math.max(w, h) * 0.1;
  return { x: b.minX - padding, y: b.minY - padding, w: w + 2 * padding, h: h + 2 * padding };
}

const QUALITY_FILL: Record<MeasurementPointQuality, string> = {
  good: 'oklch(0.72 0.18 145)',
  warning: 'oklch(0.78 0.15 85)',
  poor: 'oklch(0.62 0.22 25)',
};

const QUALITY_HEATMAP_RGBA: Record<MeasurementPointQuality, string> = {
  good: 'rgba(74, 222, 128, 0.55)',
  warning: 'rgba(250, 204, 21, 0.45)',
  poor: 'rgba(248, 113, 113, 0.6)',
};

/**
 * 실측/진단 캔버스. 확정 버전 도형 위에 측정 경로(line + 색상 dot) 와/또는
 * 실측 히트맵(radial gradient) 을 모드에 따라 토글 렌더링.
 * 데이터(points, aps) 가 비어있어도 도면만 렌더되도록 동작.
 */
export function MeasurementCanvas({
  sceneVersion,
  points,
  aps,
  mode,
  highlightedPointId,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const sceneId = sceneVersion?.id ?? null;
  const vb = useMemo(() => computeViewBox(sceneVersion), [sceneId]);
  const sortedPoints = useMemo(
    () => [...points].sort((a, b) => a.order - b.order),
    [points],
  );

  // 히트맵 점 반경 — viewBox 크기에 비례. 보통 ~1.5m 정도 영향권으로 보이도록.
  const heatmapRadius = Math.max(0.8, Math.min(vb.w, vb.h) * 0.15);

  const showRoute = mode === 'route' || mode === 'both';
  const showHeatmap = mode === 'heatmap' || mode === 'both';

  return (
    <div
      className={cn(
        'relative flex h-full w-full items-center justify-center overflow-hidden rounded-xl border bg-[#f8fafc] p-6',
        '[background-image:radial-gradient(circle,_oklch(0.92_0_0)_1px,_transparent_1px)]',
        '[background-position:0_0] [background-size:18px_18px]',
      )}
    >
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full select-none"
      >
        <defs>
          {(['good', 'warning', 'poor'] as const).map((q) => (
            <radialGradient key={q} id={`heat-${q}`}>
              <stop offset="0%" stopColor={QUALITY_HEATMAP_RGBA[q]} />
              <stop offset="100%" stopColor={QUALITY_HEATMAP_RGBA[q].replace(/[\d.]+\)$/, '0)')} />
            </radialGradient>
          ))}
        </defs>

        {/* 히트맵: 도형보다 아래에 깔아 도면이 위에 보이도록. */}
        {showHeatmap &&
          sortedPoints.map((p) => (
            <circle
              key={`heat-${p.id}`}
              cx={p.x_m}
              cy={p.y_m}
              r={heatmapRadius}
              fill={`url(#heat-${p.quality})`}
              pointerEvents="none"
            />
          ))}

        {(sceneVersion?.walls ?? []).map((w) => (
          <WallShape key={w.id} wall={w} />
        ))}
        {(sceneVersion?.openings ?? []).map((o) => (
          <OpeningShape key={o.id} opening={o} />
        ))}
        {(sceneVersion?.objects ?? []).map((o) => (
          <ObjectShape key={o.id} object={o} />
        ))}

        {/* 측정 경로 라인 — 점들 순서대로 점선 연결. */}
        {showRoute && sortedPoints.length >= 2 && (
          <polyline
            points={sortedPoints.map((p) => `${p.x_m},${p.y_m}`).join(' ')}
            fill="none"
            stroke="oklch(0.6 0.18 255)"
            strokeWidth="2"
            strokeDasharray="6 4"
            vectorEffect="non-scaling-stroke"
            pointerEvents="none"
          />
        )}

        {/* 측정 포인트 점. */}
        {showRoute &&
          sortedPoints.map((p) => (
            <g key={`pt-${p.id}`} pointerEvents="none">
              <circle
                cx={p.x_m}
                cy={p.y_m}
                r={Math.max(0.08, vb.w * 0.008)}
                fill={QUALITY_FILL[p.quality]}
                stroke={highlightedPointId === p.id ? 'oklch(0.45 0.22 25)' : 'white'}
                strokeWidth={highlightedPointId === p.id ? 0.06 : 0.04}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          ))}

        {/* AP 마커 — 파란 원에 흰색 wifi 아이콘. */}
        {aps.map((ap) => (
          <ApMarker key={ap.id} ap={ap} />
        ))}
      </svg>
    </div>
  );
}

// ============================================
// 도형 (read-only)
// ============================================

function WallShape({ wall }: { wall: DraftWall }) {
  const g = parseGeometry(wall.centerline_geom);
  if (g?.type !== 'LineString') return null;
  const start = g.coordinates[0];
  const end = g.coordinates[g.coordinates.length - 1];
  if (!start || !end) return null;
  return (
    <line
      x1={start[0]}
      y1={start[1]}
      x2={end[0]}
      y2={end[1]}
      stroke="oklch(0.25 0 0)"
      strokeWidth="4"
      strokeLinecap="round"
      vectorEffect="non-scaling-stroke"
      pointerEvents="none"
    />
  );
}

function OpeningShape({ opening }: { opening: DraftOpening }) {
  const g = parseGeometry(opening.line_geom);
  if (g?.type !== 'LineString') return null;
  const start = g.coordinates[0];
  const end = g.coordinates[g.coordinates.length - 1];
  if (!start || !end) return null;
  const isDoor = opening.opening_type === 'door';
  const color = isDoor ? 'oklch(0.55 0.22 264)' : 'oklch(0.7 0.18 200)';
  return (
    <line
      x1={start[0]}
      y1={start[1]}
      x2={end[0]}
      y2={end[1]}
      stroke={color}
      strokeWidth="5"
      strokeLinecap="butt"
      vectorEffect="non-scaling-stroke"
      pointerEvents="none"
    />
  );
}

function ObjectShape({ object }: { object: DraftObject }) {
  const g = parseGeometry(object.point_geom);
  if (g?.type !== 'Point') return null;
  const [x, y] = g.coordinates;
  const meta = (object.metadata_json ?? {}) as Record<string, unknown>;
  const w = typeof meta.width_m === 'number' && meta.width_m > 0 ? meta.width_m : 1.6;
  const h = typeof meta.height_m === 'number' && meta.height_m > 0 ? meta.height_m : 1.6;
  const label =
    (typeof meta.label === 'string' && meta.label) ||
    objectTypeLabel(object.object_type);
  return (
    <g pointerEvents="none">
      <rect
        x={x - w / 2}
        y={y - h / 2}
        width={w}
        height={h}
        rx="0.15"
        fill="oklch(0.95 0.03 240)"
        stroke="oklch(0.74 0.08 240)"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
      {label && (
        <text
          x={x}
          y={y}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={Math.min(w, h) * 0.22}
          fontWeight="500"
          fill="oklch(0.4 0.04 240)"
        >
          {label}
        </text>
      )}
    </g>
  );
}

const OBJECT_TYPE_LABEL: Record<string, string> = {
  furniture: '가구',
  table: '테이블',
  bathroom: '화장실',
  kitchen: '주방',
  stairs: '계단',
  counter: '카운터',
  storage: '창고',
};

function objectTypeLabel(t: string | null | undefined): string | null {
  if (!t) return null;
  return OBJECT_TYPE_LABEL[t] ?? t;
}

function ApMarker({ ap }: { ap: PlacedApSimple }) {
  const fill = 'oklch(0.55 0.22 254)';
  const r = 0.5;
  const iconSize = r * 1.1;
  const iconScale = iconSize / 24;
  return (
    <g pointerEvents="none">
      <circle cx={ap.x_m} cy={ap.y_m} r={r} fill={fill} />
      <g
        transform={`translate(${ap.x_m - iconSize / 2}, ${ap.y_m - iconSize / 2}) scale(${iconScale})`}
        fill="none"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 20h.01" />
        <path d="M2 8.82a15 15 0 0 1 20 0" />
        <path d="M5 12.859a10 10 0 0 1 14 0" />
        <path d="M8.5 16.429a5 5 0 0 1 7 0" />
      </g>
      {ap.label && (
        <text
          x={ap.x_m}
          y={ap.y_m + r + 0.35}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={0.35}
          fontWeight="600"
          fill="oklch(0.4 0.1 254)"
        >
          {ap.label}
        </text>
      )}
    </g>
  );
}
