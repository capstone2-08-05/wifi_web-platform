import { useCallback, useMemo, useRef, useState } from 'react';
import { parseGeometry, type Coord } from '@/features/editor/geometry-utils';
import {
  deriveImageExtent,
  useImageNaturalDimensions,
} from '@/features/editor/floorplan-image-extent';
import type { ApRecommendationResult } from '@/types/ap-recommendation';
import type { PhysicalAp, RadioInterface } from '@/types/rf';
import type { DraftObject, DraftOpening, DraftWall, SceneVersion } from '@/types/scene';
import { cn } from '@/lib/utils';
import { dbmToHeatmapColor } from '@/lib/rssi-colormap';
import { DbmColorBar } from '@/features/simulation/DbmColorBar';
import {
  clampCoord,
  clampMeterBBox,
  clampRectToBounds,
  computeSceneBounds,
  isValidSelectionBBox,
  meterBBoxFromRect,
  normalizeRect,
  validRecommendationAreas,
  type ApRecommendationArea,
  type ApRecommendationAreaType,
} from './recommendation-utils';

export interface CanvasExistingAp {
  id: string;
  x_m: number;
  y_m: number;
  z_m?: number;
  label?: string;
  radios?: RadioInterface[];
  movable?: boolean;
}

const RECOMMEND_RADIUS_M = 0.28;
const DRAG_THRESHOLD_M = 0.15;
/** viewBox 너비 비율 — 도면 스케일과 무관하게 화면에서 읽기 쉬운 라벨 크기 */
const CANVAS_LABEL_VB_RATIO = 0.018;

const AREA_STYLE: Record<
  ApRecommendationAreaType,
  { label: string; fill: string; stroke: string; badge: string }
> = {
  candidate: {
    label: '설치 가능 영역',
    fill: 'rgb(37 99 235 / 0.18)',
    stroke: 'rgb(37 99 235)',
    badge: 'oklch(0.55 0.22 254)',
  },
  priority: {
    label: '우선 평가 영역',
    fill: 'rgb(22 163 74 / 0.18)',
    stroke: 'rgb(22 163 74)',
    badge: 'oklch(0.62 0.18 145)',
  },
  excluded: {
    label: '제외 영역',
    fill: 'rgb(239 68 68 / 0.16)',
    stroke: 'rgb(220 38 38)',
    badge: 'oklch(0.62 0.21 25)',
  },
};

function canvasLabelFontM(viewBoxW: number): number {
  return viewBoxW * CANVAS_LABEL_VB_RATIO;
}

interface Props {
  sceneVersion: SceneVersion | null | undefined;
  backgroundImageUrl?: string | null;
  existingAps: CanvasExistingAp[];
  selectedAreas: ApRecommendationArea[];
  activeAreaType: ApRecommendationAreaType;
  onAreasChange: (areas: ApRecommendationArea[]) => void;
  recommendations: ApRecommendationResult[];
  recommendationMode?: 'add' | 'replace' | 'relocate_all' | 'relocate_selected';
  selectedReplacementIds?: string[];
  movableApIds?: string[];
  selectedRecommendationRank: number | null;
  heatmapMode?: 'prediction' | 'measurement';
  measurementHeatmap?: {
    url?: string | null;
    valuesDbm?: number[][];
    bounds: { min_x: number; min_y: number; max_x: number; max_y: number };
    rssiRange?: { min: number; max: number };
    source?: 'measurement' | 'simulation';
  } | null;
  disabled?: boolean;
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
  existingAps,
  selectedAreas,
  activeAreaType,
  onAreasChange,
  recommendations,
  recommendationMode = 'add',
  selectedReplacementIds = [],
  movableApIds = [],
  selectedRecommendationRank,
  heatmapMode = 'prediction',
  measurementHeatmap,
  disabled = false,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ start: Coord; current: Coord } | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; dbm: number } | null>(null);

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
    if (imageExtent) return computeViewBox(sceneVersion, imageExtent);
    return computeViewBox(sceneVersion, null);
  }, [sceneVersion, imageExtent]);

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
    if (disabled) return;
    const pt = getSvgPoint(e);
    if (!pt) return;
    svgRef.current?.setPointerCapture(e.pointerId);
    setDrag({ start: pt, current: pt });
  };

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!drag) return;
    const pt = getSvgPoint(e);
    if (!pt) return;
    setDrag({ start: drag.start, current: pt });
  };

  const finishDrag = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!drag) return;
    try {
      svgRef.current?.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
    const rect = clampRectToBounds(normalizeRect(drag.start, drag.current), sceneBounds);
    setDrag(null);
    if (rect.w < DRAG_THRESHOLD_M || rect.h < DRAG_THRESHOLD_M) {
      return;
    }
    const bbox = clampMeterBBox(meterBBoxFromRect(rect), sceneBounds);
    if (isValidSelectionBBox(bbox)) {
      onAreasChange([
        ...selectedAreas,
        {
          id: `${activeAreaType}-${Date.now()}-${selectedAreas.length}`,
          type: activeAreaType,
          bbox,
        },
      ]);
    }
  };

  const dragRect = drag
    ? clampRectToBounds(normalizeRect(drag.start, drag.current), sceneBounds)
    : null;
  const clampedAreas = validRecommendationAreas(selectedAreas).map((area) => ({
    ...area,
    bbox: clampMeterBBox(area.bbox, sceneBounds),
  }));
  const selectedRecommendation = useMemo(
    () => recommendations.find((rec) => rec.rank === selectedRecommendationRank) ?? null,
    [recommendations, selectedRecommendationRank],
  );
  const predictionCells = useMemo(
    () => buildPredictionCells(selectedRecommendation?.prediction_points ?? []),
    [selectedRecommendation],
  );
  const showDragPreview =
    dragRect && (dragRect.w >= DRAG_THRESHOLD_M || dragRect.h >= DRAG_THRESHOLD_M);
  const labelFontM = canvasLabelFontM(vb.w);
  const selectionBadgeH = labelFontM * 1.55;
  const selectionBadgeW = labelFontM * 8.4;
  const removeButtonR = labelFontM * 0.7;

  const removeSelectedArea = (id: string) => {
    onAreasChange(selectedAreas.filter((area) => area.id !== id));
  };

  const handleSvgMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const svg = svgRef.current;
      if (!svg) return;
      const pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return;
      const sp = pt.matrixTransform(ctm.inverse());

      if (heatmapMode === 'measurement' && measurementHeatmap?.valuesDbm && measurementHeatmap.bounds) {
        const { min_x, min_y, max_x, max_y } = measurementHeatmap.bounds;
        const rows = measurementHeatmap.valuesDbm.length;
        const cols = measurementHeatmap.valuesDbm[0]?.length ?? 0;
        if (rows > 0 && cols > 0) {
          const cellW = (max_x - min_x) / cols;
          const cellH = (max_y - min_y) / rows;
          const col = Math.floor((sp.x - min_x) / cellW);
          const row = Math.floor((sp.y - min_y) / cellH);
          if (row >= 0 && row < rows && col >= 0 && col < cols) {
            const dbm = measurementHeatmap.valuesDbm[row][col];
            if (dbm != null && Number.isFinite(dbm)) {
              setTooltip({ x: e.clientX, y: e.clientY, dbm });
              return;
            }
          }
        }
      } else if (heatmapMode === 'prediction' && predictionCells) {
        const half = Math.max(predictionCells.cellW, predictionCells.cellH) * 0.6;
        let best: { dist: number; dbm: number } | null = null;
        for (const pt2 of predictionCells.points) {
          if (Math.abs(pt2.x - sp.x) < half && Math.abs(pt2.y - sp.y) < half) {
            const dist = Math.hypot(pt2.x - sp.x, pt2.y - sp.y);
            if (!best || dist < best.dist) best = { dist, dbm: pt2.rssi_dbm };
          }
        }
        if (best) { setTooltip({ x: e.clientX, y: e.clientY, dbm: best.dbm }); return; }
      }
      setTooltip(null);
    },
    [heatmapMode, measurementHeatmap, predictionCells],
  );

  const heatmapRssiRange = heatmapMode === 'measurement'
    ? (measurementHeatmap?.rssiRange ?? null)
    : predictionCells?.range ?? null;
  const showLegend = heatmapRssiRange !== null && (
    (heatmapMode === 'measurement' && !!measurementHeatmap) ||
    (heatmapMode === 'prediction' && !!predictionCells)
  );

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#f8fafc] [background-image:radial-gradient(circle,oklch(0.92_0_0)_1px,transparent_1px)] bg-size-[18px_18px] bg-position-[0_0]">
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMid meet"
        overflow="hidden"
        className={cn(
          'h-full w-full select-none touch-none',
          disabled ? 'cursor-not-allowed opacity-60' : 'cursor-crosshair',
        )}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        onMouseMove={handleSvgMouseMove}
        onMouseLeave={() => setTooltip(null)}
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
            />
          )}

          {heatmapMode === 'prediction' && predictionCells && (
            <g opacity={0.62} pointerEvents="none">
              {predictionCells.points.map((point, idx) => (
                <rect
                  key={`ap-rec-pred-${idx}`}
                  x={point.x - predictionCells.cellW / 2}
                  y={point.y - predictionCells.cellH / 2}
                  width={predictionCells.cellW}
                  height={predictionCells.cellH}
                  fill={dbmToHeatmapColor(
                    point.rssi_dbm,
                    predictionCells.range.min,
                    predictionCells.range.max,
                  )}
                />
              ))}
            </g>
          )}

          {heatmapMode === 'measurement' && measurementHeatmap?.valuesDbm && measurementHeatmap.bounds ? (
            <g opacity={0.65} pointerEvents="none">
              {measurementHeatmap.valuesDbm.map((row, rowIdx) =>
                row.map((value, colIdx) => {
                  const rows = measurementHeatmap.valuesDbm?.length ?? 1;
                  const cols = row.length || 1;
                  const bounds = measurementHeatmap.bounds!;
                  const cellW = (bounds.max_x - bounds.min_x) / cols;
                  const cellH = (bounds.max_y - bounds.min_y) / rows;
                  const range = measurementHeatmap.rssiRange ?? { min: -90, max: -30 };
                  return (
                    <rect
                      key={`ap-rec-measured-${rowIdx}-${colIdx}`}
                      x={bounds.min_x + colIdx * cellW}
                      y={bounds.min_y + rowIdx * cellH}
                      width={cellW}
                      height={cellH}
                      fill={dbmToHeatmapColor(value, range.min, range.max)}
                    />
                  );
                }),
              )}
            </g>
          ) : heatmapMode === 'measurement' && measurementHeatmap?.url && measurementHeatmap.bounds && (
            <image
              href={measurementHeatmap.url}
              xlinkHref={measurementHeatmap.url}
              x={measurementHeatmap.bounds.min_x}
              y={measurementHeatmap.bounds.min_y}
              width={measurementHeatmap.bounds.max_x - measurementHeatmap.bounds.min_x}
              height={measurementHeatmap.bounds.max_y - measurementHeatmap.bounds.min_y}
              preserveAspectRatio="none"
              opacity={0.62}
              pointerEvents="none"
            />
          )}

          {(sceneVersion?.walls ?? []).map((w) => (
            <WallShape key={w.id} wall={w} />
          ))}
          {(sceneVersion?.openings ?? []).map((o) => (
            <OpeningShape key={o.id} opening={o} />
          ))}
          {(sceneVersion?.objects ?? []).filter((o) => o.object_type === 'column').map((o) => (
            <ObjectShape key={o.id} object={o} />
          ))}

          {existingAps.map((ap) => (
            <ExistingApMarker
              key={ap.id}
              ap={ap}
              state={getExistingApState(ap.id, recommendationMode, selectedReplacementIds, movableApIds)}
              labelFontM={labelFontM}
            />
          ))}

          {[...recommendations]
            .sort((a, b) => {
              // 선택된 순위를 맨 위에 (마지막 렌더 = SVG 최상단)
              if (a.rank === selectedRecommendationRank) return 1;
              if (b.rank === selectedRecommendationRank) return -1;
              // 나머지는 역순 (낮은 순위일수록 위에 — 1순위가 가장 마지막)
              return b.rank - a.rank;
            })
            .map((rec) => (
              <RecommendationMarker
                key={rec.rank}
                rec={rec}
                selected={selectedRecommendationRank === rec.rank}
                labelFontM={labelFontM}
                mode={recommendationMode}
              />
            ))}
        </g>

        {/* 선택 영역 — clamp된 좌표, clipPath 밖(배지가 상단에서 잘리지 않도록) */}
        <g>
          {clampedAreas.map((area) => {
            const bbox = area.bbox;
            const style = AREA_STYLE[area.type];
            return (
              <g key={area.id}>
                <rect
                  x={bbox.x_min}
                  y={bbox.y_min}
                  width={bbox.x_max - bbox.x_min}
                  height={bbox.y_max - bbox.y_min}
                  fill={style.fill}
                  stroke={style.stroke}
                  strokeWidth="1.5"
                  vectorEffect="non-scaling-stroke"
                />
                <rect
                  x={bbox.x_min}
                  y={bbox.y_min - selectionBadgeH}
                  width={selectionBadgeW}
                  height={selectionBadgeH}
                  fill={style.badge}
                />
                <text
                  x={bbox.x_min + labelFontM * 0.45}
                  y={bbox.y_min - selectionBadgeH * 0.38}
                  fontSize={labelFontM * 0.92}
                  fontWeight="600"
                  fill="white"
                  pointerEvents="none"
                  style={{ userSelect: 'none' }}
                >
                  {style.label}
                </text>
                <g
                  className="cursor-pointer"
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    removeSelectedArea(area.id);
                  }}
                >
                  <circle
                    cx={bbox.x_max}
                    cy={bbox.y_min}
                    r={removeButtonR}
                    fill="oklch(0.62 0.21 25)"
                    stroke="white"
                    strokeWidth="1.5"
                    vectorEffect="non-scaling-stroke"
                  />
                  <text
                    x={bbox.x_max}
                    y={bbox.y_min}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={labelFontM}
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
          })}

          {showDragPreview && dragRect && (
            <rect
              x={dragRect.x}
              y={dragRect.y}
              width={dragRect.w}
              height={dragRect.h}
              fill={AREA_STYLE[activeAreaType].fill}
              stroke={AREA_STYLE[activeAreaType].stroke}
              strokeWidth="1.5"
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
              pointerEvents="none"
            />
          )}
        </g>
      </svg>

      {/* 색 범례 — 히트맵이 보일 때만 표시 */}
      {showLegend && heatmapRssiRange && (
        <div className="pointer-events-none absolute left-2 top-2 z-10 w-52">
          <DbmColorBar
            vmin={heatmapRssiRange.min}
            vmax={heatmapRssiRange.max}
            label={heatmapMode === 'measurement' ? '실측/보정 신호' : '예측 신호'}
            className="pointer-events-auto"
          />
        </div>
      )}

      {/* 마우스 호버 툴팁 */}
      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 rounded-md bg-slate-800/90 px-2 py-1 text-[11px] font-medium text-white shadow-lg"
          style={{ left: tooltip.x + 14, top: tooltip.y - 28 }}
        >
          {tooltip.dbm.toFixed(1)} dBm
        </div>
      )}
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

/* [existing AP 비표시] ExistingApMarker — 다시 켤 때 주석 해제
function ExistingApMarker({ ap }: { ap: CanvasExistingAp }) {
  const r = EXISTING_AP_RADIUS_M;
  const label = ap.label ?? ap.id.toUpperCase();
  return (
    <g pointerEvents="none">
      <circle cx={ap.x_m} cy={ap.y_m} r={r} fill="oklch(0.55 0.22 254)" />
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

type ExistingApMarkerState = 'current' | 'fixed' | 'movable' | 'replace-target';

function getExistingApState(
  apId: string,
  mode: 'add' | 'replace' | 'relocate_all' | 'relocate_selected',
  replacementIds: string[],
  movableIds: string[],
): ExistingApMarkerState {
  if (mode === 'replace' && replacementIds.includes(apId)) return 'replace-target';
  if (mode === 'relocate_all') return 'movable';
  if (mode === 'relocate_selected') return movableIds.includes(apId) ? 'movable' : 'fixed';
  return 'current';
}

function ExistingApMarker({
  ap,
  state,
  labelFontM,
}: {
  ap: CanvasExistingAp;
  state: ExistingApMarkerState;
  labelFontM: number;
}) {
  const r = 0.22;
  const label = ap.label ?? ap.id.toUpperCase();
  const styles: Record<ExistingApMarkerState, { fill: string; stroke: string; badge: string }> = {
    current: { fill: 'oklch(0.48 0.12 250)', stroke: 'white', badge: '' },
    fixed: { fill: 'oklch(0.42 0.02 250)', stroke: 'oklch(0.85 0.02 250)', badge: 'L' },
    movable: { fill: 'oklch(0.62 0.16 45)', stroke: 'white', badge: 'M' },
    'replace-target': { fill: 'oklch(0.58 0.2 25)', stroke: 'white', badge: 'R' },
  };
  const style = styles[state];
  return (
    <g pointerEvents="none">
      <circle
        cx={ap.x_m}
        cy={ap.y_m}
        r={r}
        fill={style.fill}
        stroke={style.stroke}
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
        opacity={state === 'current' ? 0.85 : 0.95}
      />
      {style.badge && (
        <g>
          <circle
            cx={ap.x_m + r * 0.72}
            cy={ap.y_m - r * 0.72}
            r={r * 0.48}
            fill="white"
            stroke={style.fill}
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
          <text
            x={ap.x_m + r * 0.72}
            y={ap.y_m - r * 0.72}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={Math.max(labelFontM * 0.72, r * 0.54)}
            fontWeight="800"
            fill={style.fill}
            style={{ userSelect: 'none' }}
          >
            {style.badge}
          </text>
        </g>
      )}
      <text
        x={ap.x_m}
        y={ap.y_m + r + labelFontM * 0.8}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={labelFontM * 0.92}
        fontWeight="600"
        fill="oklch(0.25 0.04 240)"
        stroke="white"
        strokeWidth={labelFontM * 0.12}
        paintOrder="stroke fill"
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
  const w = typeof meta.width_m === 'number' && meta.width_m > 0 ? meta.width_m : 0.6;
  const h = typeof meta.height_m === 'number' && meta.height_m > 0 ? meta.height_m : 0.6;
  return (
    <g pointerEvents="none">
      <rect
        x={x - w / 2}
        y={y - h / 2}
        width={w}
        height={h}
        rx={0}
        fill="oklch(0.25 0.02 256)"
        stroke="oklch(0.18 0.02 256)"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
      <text
        x={x}
        y={y}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={Math.min(w, h) * 0.25}
        fontWeight="600"
        fill="white"
        style={{ userSelect: 'none' }}
      >
        기둥
      </text>
    </g>
  );
}

function RecommendationMarker({
  rec,
  selected,
  labelFontM,
  mode,
}: {
  rec: ApRecommendationResult;
  selected: boolean;
  labelFontM: number;
  mode: 'add' | 'replace' | 'relocate_all' | 'relocate_selected';
}) {
  const r = RECOMMEND_RADIUS_M;

  // 순위별 색상 — 선택 시 진하게, 비선택 시 연하게
  const RANK_COLORS: Record<number, { base: string; dim: string; label: string }> = {
    1: { base: 'oklch(0.55 0.20 145)', dim: 'oklch(0.72 0.18 145)', label: 'oklch(0.28 0.10 145)' },  // 초록
    2: { base: 'oklch(0.55 0.20 260)', dim: 'oklch(0.72 0.18 260)', label: 'oklch(0.28 0.10 260)' },  // 파랑
    3: { base: 'oklch(0.55 0.20 50)',  dim: 'oklch(0.72 0.18 50)',  label: 'oklch(0.28 0.10 50)'  },  // 주황
  };
  const color = RANK_COLORS[rec.rank] ?? RANK_COLORS[1];
  const fill = selected ? color.base : color.dim;
  const labelColor = color.label;

  // 멀티 AP일 때 ap_positions 전체 표시, 단일 AP면 recommended_x/y 사용
  const positions = getRecommendationPositions(rec);
  const showMoves = mode === 'replace' || mode === 'relocate_all' || mode === 'relocate_selected';

  return (
    <g pointerEvents="none">
      {showMoves &&
        (rec.relocation_moves ?? []).map((move) => (
          <g key={`${move.ap_id}-${move.to_x}-${move.to_y}`}>
            <line
              x1={move.from_x}
              y1={move.from_y}
              x2={move.to_x}
              y2={move.to_y}
              stroke={selected ? 'oklch(0.55 0.2 145)' : 'oklch(0.62 0.16 45)'}
              strokeWidth="2"
              strokeDasharray="5 4"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={move.from_x}
              cy={move.from_y}
              r={r * 0.5}
              fill="white"
              stroke="oklch(0.62 0.16 45)"
              strokeWidth="1.5"
              vectorEffect="non-scaling-stroke"
            />
          </g>
        ))}
      {positions.map((pos) => (
        <g key={`${pos.id ?? pos.index}-${pos.x}-${pos.y}`}>
          <circle
            cx={pos.x}
            cy={pos.y}
            r={r}
            fill={fill}
            stroke="white"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
          <text
            x={pos.x}
            y={pos.y}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={Math.max(r * 0.75, labelFontM * 0.85)}
            fontWeight="700"
            fill="white"
            style={{ userSelect: 'none' }}
          >
            {positions.length > 1 ? `${rec.rank}-${pos.index}` : rec.rank}
          </text>
          <text
            x={pos.x}
            y={pos.y + r + labelFontM * 1.05}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={labelFontM}
            fontWeight="700"
            fill={labelColor}
            stroke="white"
            strokeWidth={labelFontM * 0.12}
            paintOrder="stroke fill"
            style={{ userSelect: 'none' }}
          >
            {positions.length > 1 ? `추천${rec.rank} 공유기${pos.index}` : `추천 ${rec.rank}`}
          </text>
        </g>
      ))}
    </g>
  );
}

function getRecommendationPositions(rec: ApRecommendationResult): Array<{
  x: number;
  y: number;
  index: number;
  id?: string;
}> {
  type RecommendationPosition = { x: number; y: number; index: number; id?: string };
  const finalAps = (rec.final_aps ?? rec.recommended_aps ?? []) as Array<
    Partial<PhysicalAp> & { x?: number; y?: number; x_m?: number; y_m?: number }
  >;
  const fromFinal: RecommendationPosition[] = [];
  finalAps.forEach((ap, idx) => {
    const x = Number(ap.x ?? ap.x_m);
    const y = Number(ap.y ?? ap.y_m);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    fromFinal.push({ x, y, index: idx + 1, id: ap.id });
  });
  if (fromFinal.length > 0) return fromFinal;
  if (rec.ap_positions && rec.ap_positions.length > 0) {
    return rec.ap_positions.map((p) => ({ x: p.x, y: p.y, index: p.ap_index }));
  }
  return [{ x: rec.recommended_x, y: rec.recommended_y, index: 1 }];
}

function buildPredictionCells(points: ApRecommendationResult['prediction_points']) {
  const valid = points.filter(
    (point) =>
      Number.isFinite(point.x) &&
      Number.isFinite(point.y) &&
      Number.isFinite(point.rssi_dbm),
  );
  if (valid.length === 0) return null;
  const xs = [...new Set(valid.map((point) => point.x))].sort((a, b) => a - b);
  const ys = [...new Set(valid.map((point) => point.y))].sort((a, b) => a - b);
  const cellW = minPositiveDelta(xs) ?? 1;
  const cellH = minPositiveDelta(ys) ?? cellW;
  const values = valid.map((point) => point.rssi_dbm);
  const min = Math.min(-90, Math.min(...values));
  const max = Math.max(-30, Math.max(...values));
  return {
    points: valid,
    cellW,
    cellH,
    range: { min, max },
  };
}

function minPositiveDelta(values: number[]): number | null {
  let best = Infinity;
  for (let i = 1; i < values.length; i += 1) {
    const delta = values[i] - values[i - 1];
    if (delta > 1e-6 && delta < best) best = delta;
  }
  return Number.isFinite(best) ? best : null;
}
