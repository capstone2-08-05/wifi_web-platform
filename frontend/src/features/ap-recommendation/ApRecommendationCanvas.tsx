import { useMemo, useRef, useState } from 'react';
import { parseGeometry, type Coord } from '@/features/editor/geometry-utils';
import { loadCachedViewBox } from '@/features/editor/viewbox-cache';
import {
  deriveImageExtent,
  useImageNaturalDimensions,
} from '@/features/editor/floorplan-image-extent';
import type { ApRecommendationResult } from '@/types/ap-recommendation';
import type { DraftOpening, DraftWall, SceneVersion } from '@/types/scene';
import { cn } from '@/lib/utils';
import { CANVAS_BLUE, CANVAS_WINDOW } from '@/lib/canvas-scene-colors';
import {
  clampCoord,
  clampMeterBBox,
  clampRectToBounds,
  computeSceneBounds,
  isValidSelectionBBox,
  meterBBoxFromRect,
  normalizeRect,
  type MeterBBox,
} from './recommendation-utils';

export interface CanvasExistingAp {
  id: string;
  x_m: number;
  y_m: number;
  label?: string;
}

const RECOMMEND_RADIUS_M = 0.28;
const DRAG_THRESHOLD_M = 0.15;
/** viewBox 너비 비율 — 도면 스케일과 무관하게 화면에서 읽기 쉬운 라벨 크기 */
const CANVAS_LABEL_VB_RATIO = 0.018;

const SELECTION_BADGE_LABEL = '우선 개선 영역';
/** 우선 개선 영역 — bright lemon yellow (문·창문·primary blue 와 구분) */
const SELECTION_FILL = 'rgba(254, 240, 138, 0.35)';
const SELECTION_FILL_PREVIEW = 'rgba(254, 240, 138, 0.28)';
const SELECTION_STROKE = '#FACC15';
const SELECTION_LABEL_BG = '#FACC15';
const SELECTION_LABEL_TEXT = '#111827';
/** 선택 rect 모서리 — 도면 미터 좌표 기준 */
const SELECTION_CORNER_R = 0.14;

function selectionBadgeMetrics(labelFontM: number) {
  const font = labelFontM * 0.92;
  const padX = labelFontM * 0.24;
  let textWidth = 0;
  for (const ch of SELECTION_BADGE_LABEL) {
    textWidth += ch === ' ' ? font * 0.28 : font * 0.88;
  }
  const width = padX * 2 + textWidth;
  const height = labelFontM * 1.45;
  const cornerR = labelFontM * 0.22;
  return { font, padX, width, height, cornerR };
}

function canvasLabelFontM(viewBoxW: number): number {
  return viewBoxW * CANVAS_LABEL_VB_RATIO;
}

interface Props {
  sceneVersion: SceneVersion | null | undefined;
  backgroundImageUrl?: string | null;
  existingAps: CanvasExistingAp[];
  selectionBBox: MeterBBox | null;
  onSelectionChange: (bbox: MeterBBox | null) => void;
  recommendations: ApRecommendationResult[];
  selectedRecommendationRank: number | null;
  disabled?: boolean;
  /** true면 새 우선 개선 영역 드래그 불가 (추천 완료·계산 중) */
  dragDisabled?: boolean;
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
  const padding = Math.max(w, h) * 0.05;
  return { x: b.minX - padding, y: b.minY - padding, w: w + 2 * padding, h: h + 2 * padding };
}

export function ApRecommendationCanvas({
  sceneVersion,
  backgroundImageUrl,
  selectionBBox,
  onSelectionChange,
  recommendations,
  selectedRecommendationRank,
  disabled = false,
  dragDisabled = false,
}: Props) {
  const interactionBlocked = disabled || dragDisabled;
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ start: Coord; current: Coord } | null>(null);

  const imageDims = useImageNaturalDimensions(backgroundImageUrl ?? null);
  const imageExtent = useMemo(
    () =>
      deriveImageExtent(imageDims, {
        sourceAssetId: sceneVersion?.source_asset_id ?? null,
        floorId: sceneVersion?.floor_id ?? null,
      }),
    [imageDims, sceneVersion?.source_asset_id, sceneVersion?.floor_id],
  );

  const vb = useMemo(() => {
    const cached = loadCachedViewBox(sceneVersion?.floor_id ?? null);
    if (cached) return cached;
    if (imageExtent) return computeViewBox(sceneVersion, imageExtent);
    return computeViewBox(sceneVersion, null);
  }, [sceneVersion?.floor_id, sceneVersion, imageExtent]);

  const sceneBounds = useMemo(
    () => computeSceneBounds(sceneVersion, imageExtent),
    [sceneVersion, imageExtent],
  );

  const clampPoint = (pt: Coord): Coord => clampCoord(pt, sceneBounds);

  const getSvgPoint = (e: React.PointerEvent): Coord | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const t = pt.matrixTransform(ctm.inverse());
    return clampPoint([t.x, t.y]);
  };

  const handlePointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (interactionBlocked) return;
    const pt = getSvgPoint(e);
    if (!pt) return;
    svgRef.current?.setPointerCapture(e.pointerId);
    setDrag({ start: pt, current: pt });
  };

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (interactionBlocked) return;
    if (!drag) return;
    const pt = getSvgPoint(e);
    if (!pt) return;
    setDrag({ start: drag.start, current: pt });
  };

  const finishDrag = (e: React.PointerEvent<SVGSVGElement>) => {
    if (interactionBlocked) return;
    if (!drag) return;
    try {
      svgRef.current?.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
    const rect = clampRectToBounds(normalizeRect(drag.start, drag.current), sceneBounds);
    setDrag(null);
    if (rect.w < DRAG_THRESHOLD_M || rect.h < DRAG_THRESHOLD_M) {
      onSelectionChange(null);
      return;
    }
    const bbox = clampMeterBBox(meterBBoxFromRect(rect), sceneBounds);
    if (isValidSelectionBBox(bbox)) {
      onSelectionChange(bbox);
    }
  };

  const dragRect = drag
    ? clampRectToBounds(normalizeRect(drag.start, drag.current), sceneBounds)
    : null;
  const clampedSelectionBBox = selectionBBox
    ? clampMeterBBox(selectionBBox, sceneBounds)
    : null;
  const showDragPreview =
    dragRect && (dragRect.w >= DRAG_THRESHOLD_M || dragRect.h >= DRAG_THRESHOLD_M);
  const labelFontM = canvasLabelFontM(vb.w);
  const selectionBadge = selectionBadgeMetrics(labelFontM);
  const selectionBadgeY = clampedSelectionBBox
    ? Math.max(sceneBounds.yMin, clampedSelectionBBox.y_min - selectionBadge.height)
    : 0;

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#f8fafc] [background-image:radial-gradient(circle,oklch(0.92_0_0)_1px,transparent_1px)] bg-size-[18px_18px] bg-position-[0_0]">
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMid meet"
        overflow="hidden"
        className={cn(
          'h-full w-full select-none touch-none',
          disabled && 'cursor-not-allowed opacity-60',
          !disabled && dragDisabled && 'cursor-default',
          !disabled && !dragDisabled && 'cursor-crosshair',
        )}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
      >
        <defs>
          <clipPath id="ap-rec-scene-clip">
            <rect
              x={sceneBounds.xMin}
              y={sceneBounds.yMin}
              width={sceneBounds.xMax - sceneBounds.xMin}
              height={sceneBounds.yMax - sceneBounds.yMin}
            />
          </clipPath>
        </defs>
        <g clipPath="url(#ap-rec-scene-clip)">
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
            />
          )}

          {(sceneVersion?.walls ?? []).map((w) => (
            <WallShape key={w.id} wall={w} />
          ))}
          {(sceneVersion?.openings ?? []).map((o) => (
            <OpeningShape key={o.id} opening={o} />
          ))}
        </g>

        {/* 선택 영역 — clamp된 좌표, clipPath 밖(배지가 상단에서 잘리지 않도록) */}
        <g pointerEvents="none">
          {clampedSelectionBBox && (
            <g>
              <rect
                x={clampedSelectionBBox.x_min}
                y={clampedSelectionBBox.y_min}
                width={clampedSelectionBBox.x_max - clampedSelectionBBox.x_min}
                height={clampedSelectionBBox.y_max - clampedSelectionBBox.y_min}
                rx={SELECTION_CORNER_R}
                ry={SELECTION_CORNER_R}
                fill={SELECTION_FILL}
                stroke={SELECTION_STROKE}
                strokeWidth="1.5"
                vectorEffect="non-scaling-stroke"
              />
              <rect
                x={clampedSelectionBBox.x_min}
                y={selectionBadgeY}
                width={selectionBadge.width}
                height={selectionBadge.height}
                rx={selectionBadge.cornerR}
                ry={selectionBadge.cornerR}
                fill={SELECTION_LABEL_BG}
              />
              <text
                x={clampedSelectionBBox.x_min + selectionBadge.padX}
                y={selectionBadgeY + selectionBadge.height * 0.62}
                fontSize={selectionBadge.font}
                fontWeight="500"
                fill={SELECTION_LABEL_TEXT}
                style={{ userSelect: 'none' }}
              >
                우선 개선 영역
              </text>
            </g>
          )}

          {showDragPreview && dragRect && (
            <rect
              x={dragRect.x}
              y={dragRect.y}
              width={dragRect.w}
              height={dragRect.h}
              rx={SELECTION_CORNER_R}
              ry={SELECTION_CORNER_R}
              fill={SELECTION_FILL_PREVIEW}
              stroke={SELECTION_STROKE}
              strokeWidth="1.5"
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </g>

        {/* 추천 AP 마커 — 선택 영역 위에 표시 */}
        <g pointerEvents="none">
          {recommendations.map((rec) => (
            <RecommendationMarker
              key={rec.rank}
              rec={rec}
              selected={selectedRecommendationRank === rec.rank}
              labelFontM={labelFontM}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}

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
  const color = isDoor ? CANVAS_BLUE : CANVAS_WINDOW;
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

/* [existing AP 비표시] ExistingApMarker — 다시 켤 때 주석 해제
function ExistingApMarker({ ap }: { ap: CanvasExistingAp }) {
  const r = EXISTING_AP_RADIUS_M;
  const label = ap.label ?? ap.id.toUpperCase();
  return (
    <g pointerEvents="none">
      <circle cx={ap.x_m} cy={ap.y_m} r={r} fill={CANVAS_BLUE} />
      <g
        transform={`translate(${ap.x_m - r * 0.55}, ${ap.y_m - r * 0.55}) scale(${r / 12})`}
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
        fontSize={EXISTING_AP_LABEL_FONT_M}
        fontWeight="600"
        fill="oklch(0.25 0.04 240)"
        style={{ userSelect: 'none' }}
      >
        {label}
      </text>
    </g>
  );
}
*/

function RecommendationMarker({
  rec,
  selected,
  labelFontM,
}: {
  rec: ApRecommendationResult;
  selected: boolean;
  labelFontM: number;
}) {
  const r = RECOMMEND_RADIUS_M;
  const fill = selected ? '#059669' : '#10b981';
  return (
    <g pointerEvents="none">
      <circle
        cx={rec.recommended_x}
        cy={rec.recommended_y}
        r={r}
        fill={fill}
        stroke="white"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
      <text
        x={rec.recommended_x}
        y={rec.recommended_y}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={Math.max(r * 0.55, labelFontM * 0.65)}
        fontWeight="600"
        fill="white"
        style={{ userSelect: 'none' }}
      >
        AP
      </text>
      <text
        x={rec.recommended_x}
        y={rec.recommended_y + r + labelFontM * 1.05}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={labelFontM}
        fontWeight="600"
        fill={fill}
        stroke="white"
        strokeWidth={labelFontM * 0.1}
        paintOrder="stroke fill"
        style={{ userSelect: 'none' }}
      >
        추천 위치
      </text>
    </g>
  );
}
