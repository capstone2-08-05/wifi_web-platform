import { useMemo, useRef, useState } from 'react';
import { parseGeometry, type Coord } from '@/features/editor/geometry-utils';
import { loadCachedViewBox } from '@/features/editor/viewbox-cache';
import {
  deriveImageExtent,
  inferImageExtentFromWallBounds,
  useImageNaturalDimensions,
} from '@/features/editor/floorplan-image-extent';
import type {
  DraftObject,
  DraftOpening,
  DraftRoom,
  DraftWall,
  SceneVersion,
} from '@/types/scene';
import { cn } from '@/lib/utils';

export interface PlacedAp {
  id: string;          // 'ap1', 'ap2', ... — 사용자/SageMaker 식별자
  x_m: number;
  y_m: number;
  z_m: number;
}

/** 모든 AP 에 공통 적용되는 출력 파워 (백엔드 simulation.tx_power_dbm 으로 보냄). */
export const DEFAULT_TX_POWER_DBM = 20;

const MAX_APS = 8;
const DEFAULT_AP_Z_M = 2.5;
const AP_MARKER_RADIUS_M = 0.26;
const AP_LABEL_FONT_SIZE_M = 0.19;

interface Props {
  sceneVersion: SceneVersion | null | undefined;
  /** 원본 도면 이미지 (배경에 연하게 깔림). */
  backgroundImageUrl?: string | null;
  aps: PlacedAp[];
  onAdd: (ap: PlacedAp) => void;
  onMove: (id: string, x: number, y: number) => void;
  onRemove: (id: string) => void;
  /** true 면 다음 캔버스 클릭이 새 AP 추가. false 면 기존 AP 드래그/삭제만. */
  pending: boolean;
  onClearPending: () => void;
  /** RF 시뮬레이션 결과 히트맵 (presigned URL). 있으면 도면 위에 오버레이. */
  heatmapUrl?: string | null;
  /** 히트맵의 실제 미터 좌표 영역 (bounds_json 에서 파싱). */
  heatmapBounds?: { minX: number; minY: number; maxX: number; maxY: number } | null;
  /** true 면 AP 추가/드래그/삭제 모두 비활성화 — 결과 보기 전용. */
  readOnly?: boolean;
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

/**
 * 캔버스 viewBox 계산. imageExtent 가 주어지면 union(walls, image) 로 잡아서
 * 이미지와 벽이 같은 좌표계로 함께 표시되도록 함. 없으면 도형(walls/rooms/openings)
 * bounds 기준 fallback.
 *
 * 객체(가구/공간 박스) 는 건물 밖으로 삐져나갈 수 있어 viewBox 에서 제외 — 캔버스가
 * 일그러지지 않도록 고정. 밖으로 나간 객체는 잘려 보이지만 비율은 안정적.
 */
function computeViewBox(
  scene: SceneVersion | null | undefined,
  imageExtent: { w: number; h: number } | null,
): {
  x: number;
  y: number;
  w: number;
  h: number;
} {
  const b = emptyBounds();
  for (const room of scene?.rooms ?? []) {
    const g = parseGeometry(room.polygon_geom);
    if (g?.type === 'Polygon')
      for (const ring of g.coordinates) for (const [x, y] of ring) extendBounds(b, x, y);
  }
  for (const wall of scene?.walls ?? []) {
    const g = parseGeometry(wall.centerline_geom);
    if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
  }
  for (const op of scene?.openings ?? []) {
    const g = parseGeometry(op.line_geom);
    if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
  }
  // image extent 가 있으면 (0,0)~(extent.w, extent.h) 도 bounds 에 포함 → union.
  if (imageExtent) {
    extendBounds(b, 0, 0);
    extendBounds(b, imageExtent.w, imageExtent.h);
  }
  if (!isFinite(b.minX)) return { x: 0, y: 0, w: 10, h: 10 };
  const w = b.maxX - b.minX || 1;
  const h = b.maxY - b.minY || 1;
  const padding = Math.max(w, h) * 0.05;
  return { x: b.minX - padding, y: b.minY - padding, w: w + 2 * padding, h: h + 2 * padding };
}

/**
 * 시뮬레이션 페이지 캔버스 — 확정 버전 도형(rooms/walls/openings/objects)을 read-only 로
 * 보여주고, 그 위에 사용자가 AP 를 자유롭게 배치/드래그/삭제. 최대 8개.
 *
 * 렌더링 스타일은 공간편집(DraftSceneCanvas) 와 시각적으로 일치시킨다.
 */
export function SimulationCanvas({
  sceneVersion,
  backgroundImageUrl,
  aps,
  onAdd,
  onMove,
  onRemove,
  pending,
  onClearPending,
  heatmapUrl,
  heatmapBounds,
  readOnly = false,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const sceneId = sceneVersion?.id ?? null;

  // 배경 이미지를 editor 와 동일한 좌표계로 배치하기 위해 imageExtent (미터) 계산.
  // 있으면 image 는 (0,0)~(extent.w, extent.h) 에 그림 → 벽과 정확히 정렬.
  // 없으면 viewBox 영역에 fit 으로 fallback (정렬은 안 맞아도 결과는 보임).
  const imageDims = useImageNaturalDimensions(backgroundImageUrl ?? null);
  const imageExtent = useMemo(() => {
    // 1순위: 도형 bounds 역추정 — SceneVersion 은 summary 가 없고, rescale 후
    // localStorage 가 stale 될 수 있으므로 bounds 를 우선 사용.
    // (bounds = 현재 geometry 좌표에서 직접 계산 → 항상 현재 scale 에 정확)
    const b = emptyBounds();
    for (const wall of sceneVersion?.walls ?? []) {
      const g = parseGeometry(wall.centerline_geom);
      if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
    }
    const fromBounds = inferImageExtentFromWallBounds(imageDims, isFinite(b.minX) ? b : null);
    if (fromBounds) return fromBounds;
    // 2순위: localStorage 캐시 (벽 데이터 없거나 guard 실패 시 fallback)
    return deriveImageExtent(imageDims, {
      sourceAssetId: sceneVersion?.source_asset_id ?? null,
      floorId: sceneVersion?.floor_id ?? null,
    });
  }, [imageDims, sceneVersion?.source_asset_id, sceneVersion?.floor_id, sceneVersion?.walls]);

  // imageExtent 가 있으면 항상 image+shape union 으로 계산 (editor 와 동일한 로직).
  // 캐시는 imageExtent 없이 저장된 경우 배경 이미지가 clipPath 에 잘리는 문제를 일으킬 수 있어
  // imageExtent 확보 이후엔 무시.
  const vb = useMemo(() => {
    if (imageExtent) return computeViewBox(sceneVersion, imageExtent);
    const cached = loadCachedViewBox(sceneVersion?.floor_id ?? null);
    if (cached) return cached;
    return computeViewBox(sceneVersion, null);
  }, [sceneVersion, imageExtent]);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState<Coord>([0, 0]);

  const getSvgPoint = (e: React.PointerEvent): Coord | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const t = pt.matrixTransform(ctm.inverse());
    return [t.x, t.y];
  };

  const handleSvgPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (readOnly) return;
    if (dragId) return;
    if (!pending) return;
    if (e.target !== e.currentTarget) return; // AP 또는 도형 위 클릭은 새 AP 추가가 아님
    if (aps.length >= MAX_APS) return;
    const pt = getSvgPoint(e);
    if (!pt) return;
    onAdd({
      id: nextApId(aps),
      x_m: pt[0],
      y_m: pt[1],
      z_m: DEFAULT_AP_Z_M,
    });
    onClearPending();
  };

  const handleApPointerDown = (e: React.PointerEvent, ap: PlacedAp) => {
    if (readOnly) return;
    e.stopPropagation();
    const pt = getSvgPoint(e);
    if (!pt) return;
    svgRef.current?.setPointerCapture(e.pointerId);
    setDragId(ap.id);
    setDragOffset([pt[0] - ap.x_m, pt[1] - ap.y_m]);
  };

  const handleSvgPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!dragId) return;
    const pt = getSvgPoint(e);
    if (!pt) return;
    onMove(dragId, pt[0] - dragOffset[0], pt[1] - dragOffset[1]);
  };

  const handleSvgPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!dragId) return;
    try {
      svgRef.current?.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
    setDragId(null);
  };

  const cursorClass = readOnly
    ? 'cursor-default'
    : pending
    ? 'cursor-crosshair'
    : dragId
    ? 'cursor-grabbing'
    : 'cursor-default';

  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden bg-[#f8fafc] p-6 [background-image:radial-gradient(circle,_oklch(0.92_0_0)_1px,_transparent_1px)] [background-position:0_0] [background-size:18px_18px]">
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMid meet"
        overflow="hidden"
        className={cn('h-full w-full select-none overflow-hidden', cursorClass)}
        onPointerDown={handleSvgPointerDown}
        onPointerMove={handleSvgPointerMove}
        onPointerUp={handleSvgPointerUp}
        onPointerCancel={handleSvgPointerUp}
      >
        <defs>
          {/* viewBox(=도면) 영역으로 클립. AP/히트맵/이전 버전 도형이 도면 밖이어도
              튀어나가지 않도록 잘라낸다 (도면 비례 유지). */}
          <clipPath id="sc-viewbox-clip">
            <rect x={vb.x} y={vb.y} width={vb.w} height={vb.h} />
          </clipPath>
        </defs>
        <g clipPath="url(#sc-viewbox-clip)">
        {backgroundImageUrl && (
          <image
            href={backgroundImageUrl}
            xlinkHref={backgroundImageUrl}
            // imageExtent 가 있으면 실제 미터 좌표 (0,0)~(extent.w, extent.h) 에 배치 →
            // 벽 좌표와 동일 좌표계 → 정렬 일치. 없으면 vb 영역에 fitting (fallback).
            x={imageExtent ? 0 : vb.x}
            y={imageExtent ? 0 : vb.y}
            width={imageExtent ? imageExtent.w : vb.w}
            height={imageExtent ? imageExtent.h : vb.h}
            preserveAspectRatio={imageExtent ? 'none' : 'xMidYMid meet'}
            opacity={0.35}
            pointerEvents="none"
            crossOrigin="anonymous"
            onError={() => {
              console.warn('[SimulationCanvas] 배경 도면 이미지 로드 실패:', backgroundImageUrl);
            }}
          />
        )}
        {/* RF 시뮬레이션 히트맵 오버레이 — 배경 도면 위, 도형 아래.
            bounds_json 이 있으면 그 미터 좌표에 정확히 배치(도면과 1:1 정렬).
            없으면(파싱 실패) fallback 으로 viewBox 영역에 fitting → 정렬은 안 맞아도
            적어도 결과가 보이게는 함. */}
        {heatmapUrl && (
          <image
            href={heatmapUrl}
            xlinkHref={heatmapUrl}
            x={heatmapBounds ? heatmapBounds.minX : vb.x}
            y={heatmapBounds ? heatmapBounds.minY : vb.y}
            width={heatmapBounds ? heatmapBounds.maxX - heatmapBounds.minX : vb.w}
            height={heatmapBounds ? heatmapBounds.maxY - heatmapBounds.minY : vb.h}
            preserveAspectRatio={heatmapBounds ? 'none' : 'xMidYMid meet'}
            opacity={0.6}
            pointerEvents="none"
            onError={() => {
              console.warn('[SimulationCanvas] 히트맵 이미지 로드 실패:', heatmapUrl);
            }}
          />
        )}
        {/* [room 비활성화] 시뮬레이션 캔버스에서 room 영역 렌더 제거. 다시 켜려면 아래 블록 주석 해제. */}
        {/* {(sceneVersion?.rooms ?? []).map((r) => (
          <RoomShape key={r.id} room={r} />
        ))} */}
        {(sceneVersion?.walls ?? []).map((w) => (
          <WallShape key={w.id} wall={w} />
        ))}
        {(sceneVersion?.openings ?? []).map((o) => (
          <OpeningShape key={o.id} opening={o} />
        ))}
        {/* [object 비활성화] 시뮬레이션 캔버스에서 가구/공간성 객체 렌더 제거.
            다시 켜려면 아래 블록 주석 해제. */}
        {(sceneVersion?.objects ?? []).filter((o) => o.object_type === 'column').map((o) => (
          <ObjectShape key={o.id} object={o} />
        ))}

        {aps.map((ap) => (
          <ApMarker
            key={ap.id}
            ap={ap}
            isDragging={dragId === ap.id}
            onPointerDown={(e) => handleApPointerDown(e, ap)}
            onRemove={() => onRemove(ap.id)}
          />
        ))}
        </g>
      </svg>
    </div>
  );
}

// ============================================
// 도형 (read-only) — 공간편집 DraftSceneCanvas 와 시각적 동일.
// ============================================

function RoomShape({ room }: { room: DraftRoom }) {
  const g = parseGeometry(room.polygon_geom);
  if (g?.type !== 'Polygon') return null;
  const ring = g.coordinates[0];
  if (!ring || ring.length === 0) return null;
  const isClosed =
    ring.length > 0 &&
    ring[0][0] === ring[ring.length - 1][0] &&
    ring[0][1] === ring[ring.length - 1][1];
  const labelPts = isClosed ? ring.slice(0, -1) : ring;
  const points = ring.map(([x, y]) => `${x},${y}`).join(' ');
  const label = roomLabel(room);
  const center = polygonCentroid(labelPts);
  const bb = polygonBounds(labelPts);
  return (
    <g pointerEvents="none">
      <polygon
        points={points}
        fill="oklch(0.95 0.01 256)"
        stroke="oklch(0.86 0 0)"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
      {label && (
        <text
          x={center[0]}
          y={center[1]}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={computeLabelFontSize(label, bb.w, bb.h)}
          fontWeight="600"
          fill="oklch(0.35 0.02 256)"
          style={{ userSelect: 'none' }}
        >
          {label}
        </text>
      )}
    </g>
  );
}
void RoomShape;

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
  const label = isDoor ? '문' : '창문';
  const midX = (start[0] + end[0]) / 2;
  const midY = (start[1] + end[1]) / 2;
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const offsetM = 0.17;
  const labelX = midX + nx * offsetM;
  const labelY = midY + ny * offsetM;
  return (
    <g pointerEvents="none">
      <line
        x1={start[0]}
        y1={start[1]}
        x2={end[0]}
        y2={end[1]}
        stroke={color}
        strokeWidth="5"
        strokeLinecap="butt"
        vectorEffect="non-scaling-stroke"
      />
      <text
        x={labelX}
        y={labelY}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={OPENING_LABEL_FONT_SIZE_M}
        fontWeight="500"
        fill={color}
        style={{ userSelect: 'none' }}
      >
        {label}
      </text>
    </g>
  );
}

function ObjectShape({ object }: { object: DraftObject }) {
  const g = parseGeometry(object.point_geom);
  if (g?.type !== 'Point') return null;
  const [x, y] = g.coordinates;
  const meta = (object.metadata_json ?? {}) as Record<string, unknown>;
  const w = typeof meta.width_m === 'number' && meta.width_m > 0 ? meta.width_m : SPACE_DEFAULT_SIZE_M;
  const h = typeof meta.height_m === 'number' && meta.height_m > 0 ? meta.height_m : SPACE_DEFAULT_SIZE_M;
  const label = objectLabel(object);
  const spaceLike = isSpaceLikeObject(object);
  const isColumn = object.object_type === 'column';
  const strokeDasharray = spaceLike ? '0.18 0.12' : undefined;
  return (
    <g pointerEvents="none">
      <rect
        x={x - w / 2}
        y={y - h / 2}
        width={w}
        height={h}
        rx={isColumn ? 0 : 0.15}
        fill={isColumn ? 'oklch(0.25 0.02 256)' : 'oklch(0.95 0.03 240)'}
        stroke={isColumn ? 'oklch(0.18 0.02 256)' : 'oklch(0.74 0.08 240)'}
        strokeWidth="1.5"
        strokeDasharray={strokeDasharray}
        vectorEffect="non-scaling-stroke"
      />
      {label && (
        <text
          x={x}
          y={y}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={computeLabelFontSize(label, w, h)}
          fontWeight="500"
          fill={isColumn ? 'white' : 'oklch(0.4 0.04 240)'}
          style={{ userSelect: 'none' }}
        >
          {label}
        </text>
      )}
    </g>
  );
}

// ============================================
// AP 마커 (드래그 + 라벨 + 삭제) — 도형보다 작게.
// ============================================

function ApMarker({
  ap,
  isDragging,
  onPointerDown,
  onRemove,
}: {
  ap: PlacedAp;
  isDragging: boolean;
  onPointerDown: (e: React.PointerEvent) => void;
  onRemove: () => void;
}) {
  const fill = 'oklch(0.55 0.22 254)';
  const r = AP_MARKER_RADIUS_M;
  // lucide Wifi 아이콘 (24x24 viewBox) 을 r 안에 들어갈 크기로 스케일.
  const iconSize = r * 1.1; // 원 지름의 약 55%
  const iconScale = iconSize / 24;
  return (
    <g className={isDragging ? 'cursor-grabbing' : 'cursor-grab'}>
      <circle
        cx={ap.x_m}
        cy={ap.y_m}
        r={r}
        fill={fill}
        onPointerDown={onPointerDown}
      />
      {/* lucide Wifi 아이콘 path 인라인 — 우측 "AP 추가" 패널과 동일 모양. */}
      <g
        transform={`translate(${ap.x_m - iconSize / 2}, ${ap.y_m - iconSize / 2}) scale(${iconScale})`}
        pointerEvents="none"
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
      {/* 라벨 박스 */}
      <g pointerEvents="none">
        <rect
          x={ap.x_m - 0.18}
          y={ap.y_m + r + 0.04}
          width={r * 1.8}
          height={r * 0.75}
          rx={r * 0.18}
          fill="white"
          stroke="oklch(0.85 0.02 240)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        <text
          x={ap.x_m}
          y={ap.y_m + r + r * 0.38}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={AP_LABEL_FONT_SIZE_M}
          fontWeight="600"
          fill="oklch(0.25 0.04 240)"
          style={{ userSelect: 'none' }}
        >
          {ap.id.toUpperCase()}
        </text>
      </g>
      {/* 삭제 버튼 — AP 크기에 맞춰 우측 상단에 충분히 크게 표시. */}
      <g
        onPointerDown={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className="cursor-pointer"
      >
        <circle
          cx={ap.x_m + r * 0.85}
          cy={ap.y_m - r * 0.85}
          r={r * 0.34}
          fill="oklch(0.65 0.21 25)"
          stroke="white"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
        <text
          x={ap.x_m + r * 0.85}
          y={ap.y_m - r * 0.85}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={r * 0.42}
          fontWeight="700"
          fill="white"
          pointerEvents="none"
          style={{ userSelect: 'none' }}
        >
          ×
        </text>
      </g>
    </g>
  );
}

// ============================================
// 라벨/유틸 — 공간편집과 일관된 매핑.
// ============================================

const AUTO_ROOM_NAME = /^room[_\s-]?\d+$/i;
const SPACE_DEFAULT_SIZE_M = 1.6;
const OPENING_LABEL_FONT_SIZE_M = 0.13;

const ROOM_TYPE_LABEL: Record<string, string> = {
  general: 'room',
  room: 'room',
  unknown: 'room',
  kitchen: '주방',
  storage: '창고',
  office: '사무실',
  meeting: '회의실',
  bathroom: '화장실',
  lobby: '로비',
  hall: '홀',
  corridor: '복도',
  dining: '식당',
  bedroom: '침실',
  livingroom: '거실',
};

const OBJECT_TYPE_LABEL: Record<string, string> = {
  table: '테이블',
  chair: '의자',
  desk: '책상',
  sofa: '소파',
  bed: '침대',
  ap: '공유기',
  furniture: '가구',
  counter: '카운터',
  refrigerator: '냉장고',
  toilet: '변기',
  sink: '세면대',
  bathtub: '욕조',
  door: '문',
  window: '창문',
  bathroom: '화장실',
  restroom: '화장실',
  toilet_room: '화장실',
  kitchen: '주방',
  stairs: '계단',
  staircase: '계단',
  elevator: '엘리베이터',
  closet: '벽장',
  storage: '창고',
  pantry: '팬트리',
  utility: '다용도실',
  lobby: '로비',
};

const SPACE_LIKE_TYPES = new Set([
  'bathroom',
  'restroom',
  'toilet_room',
  'kitchen',
  'stairs',
  'staircase',
  'elevator',
  'closet',
  'storage',
  'pantry',
  'utility',
  'lobby',
]);

function roomLabel(room: DraftRoom): string | null {
  const name = room.room_name?.trim();
  if (name && !AUTO_ROOM_NAME.test(name)) return name;
  if (room.room_type) return ROOM_TYPE_LABEL[room.room_type] ?? room.room_type;
  return 'room';
}

function objectLabel(object: DraftObject): string | null {
  if (!object.object_type) return null;
  if (object.object_type === 'column') return '기둥';
  return OBJECT_TYPE_LABEL[object.object_type] ?? object.object_type;
}

function isSpaceLikeObject(o: DraftObject): boolean {
  return !!o.object_type && SPACE_LIKE_TYPES.has(o.object_type);
}

function polygonCentroid(points: Coord[]): Coord {
  if (points.length === 0) return [0, 0];
  const n = points.length;
  const sx = points.reduce((s, p) => s + p[0], 0);
  const sy = points.reduce((s, p) => s + p[1], 0);
  return [sx / n, sy / n];
}

function polygonBounds(points: Coord[]): { w: number; h: number } {
  if (points.length === 0) return { w: 0, h: 0 };
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of points) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { w: maxX - minX, h: maxY - minY };
}

function computeLabelFontSize(label: string, w: number, h: number): number {
  const charCount = Math.max(1, label.length);
  const widthFit = (w * 0.5) / charCount;
  const heightFit = h * 0.35;
  const size = Math.min(widthFit, heightFit, OPENING_LABEL_FONT_SIZE_M);
  return Math.max(0.08, size);
}

function nextApId(aps: PlacedAp[]): string {
  const used = new Set(aps.map((a) => a.id));
  for (let i = 1; i <= MAX_APS; i++) {
    const id = `ap${i}`;
    if (!used.has(id)) return id;
  }
  return `ap${aps.length + 1}`;
}
