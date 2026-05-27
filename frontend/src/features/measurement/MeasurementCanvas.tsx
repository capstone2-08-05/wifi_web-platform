import { useMemo, useRef } from 'react';
import { parseGeometry } from '@/features/editor/geometry-utils';
import { loadCachedViewBox } from '@/features/editor/viewbox-cache';
import {
  deriveImageExtent,
  useImageNaturalDimensions,
} from '@/features/editor/floorplan-image-extent';
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

/** 측정점 색 모드 — heatmap 배경과 시각 통일하려면 'dbm', 신호 품질 한눈에 보려면 'quality'. */
export type PointColorMode = 'quality' | 'dbm';

interface Props {
  sceneVersion: SceneVersion | null | undefined;
  /** 원본 도면 이미지 (배경에 연하게 깔림). 공간편집/시뮬과 동일한 방식. */
  backgroundImageUrl?: string | null;
  points: MeasurementPoint[];
  /** 실제 측정 RSSI (dBm) — dbm color mode 에서 색 계산에 사용. points 와 같은 순서/id 매핑. */
  pointRssiByOrder?: Map<string, number>;
  aps: PlacedApSimple[];
  mode: MeasurementViewMode;
  /** 강조 표시할 측정 포인트 (불량 지점). 외곽 링이 진하게 표시됨. */
  highlightedPointId?: string | null;
  /**
   * GP regression dense heatmap (백엔드 #81 / `/estimated-coverage`).
   * 있으면 'heatmap' / 'both' 모드에서 측정점 radial gradient 대신 이 이미지를 깔아준다.
   */
  estimatedHeatmap?: {
    url: string;
    bounds: { min_x: number; min_y: number; max_x: number; max_y: number };
  } | null;
  /** dbm color mode 일 때 색 범위 (heatmap rssi_range 와 일치시켜야 통일). 미지정 시 -90~-30. */
  pointColorRange?: { min: number; max: number };
  /** 측정점 색 모드. 미지정 시 route='quality', heatmap/both='dbm' 자동. */
  pointColorMode?: PointColorMode;
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

/** viewBox 는 도형(walls/openings) 기준. imageExtent 주어지면 union 으로 잡아서
 *  배경 이미지와 벽이 같은 좌표계로 정렬 표시. 객체는 건물 밖으로 나갈 수 있어 제외. */
function computeViewBox(
  scene: SceneVersion | null | undefined,
  imageExtent: { w: number; h: number } | null,
) {
  const b = emptyBounds();
  for (const wall of scene?.walls ?? []) {
    const g = parseGeometry(wall.centerline_geom);
    if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
  }
  for (const op of scene?.openings ?? []) {
    const g = parseGeometry(op.line_geom);
    if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
  }
  if (imageExtent) {
    extendBounds(b, 0, 0);
    extendBounds(b, imageExtent.w, imageExtent.h);
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

// matplotlib inferno cmap stops — Sionna heatmap 과 동일 visual language.
// HeatmapColorLegend.tsx 와 동기화 유지.
const INFERNO_STOPS = [
  [0, 0, 4],
  [22, 11, 57],
  [66, 10, 104],
  [106, 23, 110],
  [147, 38, 103],
  [188, 55, 84],
  [221, 81, 58],
  [243, 120, 25],
  [252, 165, 10],
  [246, 215, 70],
  [252, 255, 164],
] as const;

/** dBm 값 → inferno cmap RGB. min/max 범위로 정규화 후 stops 사이 선형 보간. */
function dbmToInfernoColor(dbm: number, min: number, max: number): string {
  if (!Number.isFinite(dbm) || max <= min) return 'rgb(255, 255, 255)';
  const t = Math.max(0, Math.min(1, (dbm - min) / (max - min)));
  const scaled = t * (INFERNO_STOPS.length - 1);
  const lo = Math.floor(scaled);
  const hi = Math.min(INFERNO_STOPS.length - 1, lo + 1);
  const frac = scaled - lo;
  const c0 = INFERNO_STOPS[lo];
  const c1 = INFERNO_STOPS[hi];
  const r = Math.round(c0[0] + frac * (c1[0] - c0[0]));
  const g = Math.round(c0[1] + frac * (c1[1] - c0[1]));
  const b = Math.round(c0[2] + frac * (c1[2] - c0[2]));
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * 실측/진단 캔버스. 확정 버전 도형 위에 측정 경로(line + 색상 dot) 와/또는
 * 실측 히트맵(radial gradient) 을 모드에 따라 토글 렌더링.
 * 데이터(points, aps) 가 비어있어도 도면만 렌더되도록 동작.
 */
export function MeasurementCanvas({
  sceneVersion,
  backgroundImageUrl,
  points,
  pointRssiByOrder,
  aps,
  mode,
  highlightedPointId,
  estimatedHeatmap,
  pointColorRange,
  pointColorMode,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const sceneId = sceneVersion?.id ?? null;

  // 배경 이미지를 editor 와 동일한 좌표계로 배치하기 위해 imageExtent (미터) 계산.
  // image 는 (0,0)~(extent.w, extent.h) 에 그림 → 벽과 정확히 정렬.
  const imageDims = useImageNaturalDimensions(backgroundImageUrl ?? null);
  const imageExtent = useMemo(
    () =>
      deriveImageExtent(imageDims, {
        sourceAssetId: sceneVersion?.source_asset_id ?? null,
        floorId: sceneVersion?.floor_id ?? null,
      }),
    [imageDims, sceneVersion?.source_asset_id, sceneVersion?.floor_id],
  );

  // viewBox: imageExtent 있으면 union(walls, image) 자체 계산 (가장 안정적).
  // 없을 때만 editor 캐시 fallback → 도형 bounds 최후.
  const vb = useMemo(() => {
    if (imageExtent) return computeViewBox(sceneVersion, imageExtent);
    const cached = loadCachedViewBox(sceneVersion?.floor_id ?? null);
    if (cached) return cached;
    return computeViewBox(sceneVersion, null);
  }, [sceneId, sceneVersion?.floor_id, imageExtent]);
  const sortedPoints = useMemo(
    () => [...points].sort((a, b) => a.order - b.order),
    [points],
  );

  // 히트맵 점 반경 — viewBox 크기에 비례. 보통 ~1.5m 정도 영향권으로 보이도록.
  const heatmapRadius = Math.max(0.8, Math.min(vb.w, vb.h) * 0.15);

  const showLine = mode === 'route' || mode === 'both';
  const showHeatmap = mode === 'heatmap' || mode === 'both';
  // dots 는 모든 모드에서 표시 — 측정 데이터의 본체. heatmap 탭에서도 점 보여야 어디서 측정했는지 알 수 있음.
  const showDots = sortedPoints.length > 0;
  // 색 모드: 사용자 지정 > heatmap/both 면 dbm, 그 외 quality (route 또는 dots 만).
  const effectiveColorMode: PointColorMode =
    pointColorMode ?? (showHeatmap ? 'dbm' : 'quality');
  const dbmMin = pointColorRange?.min ?? -90;
  const dbmMax = pointColorRange?.max ?? -30;

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
        overflow="hidden"
        className="h-full w-full select-none overflow-hidden"
      >
        <defs>
          {/* viewBox(=도면) 영역으로 클립. 측정점/AP/히트맵이 도면 밖 좌표여도
              밖으로 튀어나가지 않도록 잘라낸다 (도면 비례 유지). */}
          <clipPath id="mc-viewbox-clip">
            <rect x={vb.x} y={vb.y} width={vb.w} height={vb.h} />
          </clipPath>
          {(['good', 'warning', 'poor'] as const).map((q) => (
            <radialGradient key={q} id={`heat-${q}`}>
              <stop offset="0%" stopColor={QUALITY_HEATMAP_RGBA[q]} />
              <stop offset="100%" stopColor={QUALITY_HEATMAP_RGBA[q].replace(/[\d.]+\)$/, '0)')} />
            </radialGradient>
          ))}
        </defs>

        {/* 모든 콘텐츠를 도면 영역으로 클립. */}
        <g clipPath="url(#mc-viewbox-clip)">

        {/* 배경 원본 도면 이미지 — 가장 아래에 연하게 (공간편집/시뮬과 동일).
            imageExtent 있으면 실제 미터 좌표 배치 → 벽과 정렬. 없으면 viewBox fit. */}
        {backgroundImageUrl && (
          <image
            href={backgroundImageUrl}
            xlinkHref={backgroundImageUrl}
            x={imageExtent ? 0 : vb.x}
            y={imageExtent ? 0 : vb.y}
            width={imageExtent ? imageExtent.w : vb.w}
            height={imageExtent ? imageExtent.h : vb.h}
            preserveAspectRatio={imageExtent ? 'none' : 'xMidYMid meet'}
            opacity={0.35}
            pointerEvents="none"
            crossOrigin="anonymous"
            onError={() => {
              console.warn(
                '[MeasurementCanvas] 배경 도면 이미지 로드 실패:',
                backgroundImageUrl,
              );
            }}
          />
        )}

        {/* 히트맵: 도형보다 아래에 깔아 도면이 위에 보이도록.
            GP regression dense heatmap 이 있으면 그것을 우선 표시 (전체 도면 커버).
            없으면 측정점 주변 radial gradient 로 fallback. */}
        {showHeatmap && estimatedHeatmap ? (
          <image
            href={estimatedHeatmap.url}
            xlinkHref={estimatedHeatmap.url}
            x={estimatedHeatmap.bounds.min_x}
            y={estimatedHeatmap.bounds.min_y}
            width={estimatedHeatmap.bounds.max_x - estimatedHeatmap.bounds.min_x}
            height={estimatedHeatmap.bounds.max_y - estimatedHeatmap.bounds.min_y}
            preserveAspectRatio="none"
            opacity={0.65}
            pointerEvents="none"
            onError={() => {
              console.warn(
                '[MeasurementCanvas] estimated coverage heatmap 로드 실패:',
                estimatedHeatmap.url,
              );
            }}
          />
        ) : (
          showHeatmap &&
          sortedPoints.map((p) => (
            <circle
              key={`heat-${p.id}`}
              cx={p.x_m}
              cy={p.y_m}
              r={heatmapRadius}
              fill={`url(#heat-${p.quality})`}
              pointerEvents="none"
            />
          ))
        )}

        {(sceneVersion?.walls ?? []).map((w) => (
          <WallShape key={w.id} wall={w} />
        ))}
        {(sceneVersion?.openings ?? []).map((o) => (
          <OpeningShape key={o.id} opening={o} />
        ))}
        {(sceneVersion?.objects ?? []).map((o) => (
          <ObjectShape key={o.id} object={o} />
        ))}

        {/* 측정 경로 라인 — route/both 모드에서만 (heatmap 모드는 점만 표시). */}
        {showLine && sortedPoints.length >= 2 && (
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

        {/* 측정 포인트 점 — 모든 모드에서 표시. heatmap 모드에선 dbm 그라데이션 색 */}
        {showDots &&
          sortedPoints.map((p) => {
            const fill =
              effectiveColorMode === 'dbm'
                ? dbmToInfernoColor(
                    pointRssiByOrder?.get(p.id) ?? Number.NaN,
                    dbmMin,
                    dbmMax,
                  )
                : QUALITY_FILL[p.quality];
            return (
              <g key={`pt-${p.id}`} pointerEvents="none">
                <circle
                  cx={p.x_m}
                  cy={p.y_m}
                  r={Math.max(0.08, vb.w * 0.008)}
                  fill={fill}
                  stroke={highlightedPointId === p.id ? 'oklch(0.45 0.22 25)' : 'white'}
                  strokeWidth={highlightedPointId === p.id ? 0.06 : 0.04}
                  vectorEffect="non-scaling-stroke"
                />
              </g>
            );
          })}

        {/* AP 마커 — 파란 원에 흰색 wifi 아이콘. */}
        {aps.map((ap) => (
          <ApMarker key={ap.id} ap={ap} />
        ))}
        </g>
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
