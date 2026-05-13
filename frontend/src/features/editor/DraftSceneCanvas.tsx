import { useEffect, useRef, useState } from 'react';
import type {
  DraftEntityKind,
  DraftObject,
  DraftOpening,
  DraftRoom,
  DraftWall,
  SceneDraft,
  SelectedEntityRef,
} from '@/types/scene';
import {
  moveLineStringVertex,
  movePolygonVertex,
  parseGeometry,
  translateGeometry,
  type Coord,
  type GeoJsonGeometry,
} from './geometry-utils';
import type { EditorTool } from '@/stores/editor-store';

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

function computeViewBox(draft: SceneDraft): { x: number; y: number; w: number; h: number } {
  const b = emptyBounds();
  for (const room of draft.rooms) {
    const g = parseGeometry(room.polygon_geom);
    if (g?.type === 'Polygon') {
      for (const ring of g.coordinates) for (const [x, y] of ring) extendBounds(b, x, y);
    }
  }
  for (const wall of draft.walls) {
    const g = parseGeometry(wall.centerline_geom);
    if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
  }
  for (const op of draft.openings) {
    const g = parseGeometry(op.line_geom);
    if (g?.type === 'LineString') for (const [x, y] of g.coordinates) extendBounds(b, x, y);
  }
  for (const obj of draft.objects) {
    const g = parseGeometry(obj.point_geom);
    if (g?.type === 'Point') {
      const [x, y] = g.coordinates;
      extendBounds(b, x, y);
    }
  }
  if (!isFinite(b.minX)) return { x: 0, y: 0, w: 10, h: 10 };
  const w = b.maxX - b.minX || 1;
  const h = b.maxY - b.minY || 1;
  const padding = Math.max(w, h) * 0.05;
  return { x: b.minX - padding, y: b.minY - padding, w: w + 2 * padding, h: h + 2 * padding };
}

const DRAG_THRESHOLD_M = 0.05;

type DragState =
  | {
      mode: 'shape';
      ref: SelectedEntityRef;
      startSvg: Coord;
      delta: Coord;
    }
  | {
      mode: 'vertex';
      ref: SelectedEntityRef;
      vertexIndex: number;
      startSvg: Coord;
      delta: Coord;
    };

/** 생성 진행 중 임시 상태 (예: 벽 그릴 때 첫 클릭 후 두 번째 대기). */
type CreatingState = { kind: 'wall'; firstPoint: Coord } | null;

interface Props {
  draft: SceneDraft;
  selectedRef?: SelectedEntityRef | null;
  onSelect?: (ref: SelectedEntityRef | null) => void;
  /** 드래그 종료 시 새 geometry. 호출 측이 적절한 *_geom 필드로 PATCH 한다. */
  onDragEnd?: (ref: SelectedEntityRef, geometry: GeoJsonGeometry) => void;
  /** 현재 도구 (좌측 도구바). 'select' 이외 모드면 그리기 흐름으로 전환. */
  tool?: EditorTool;
  /** 새 도형 생성. body 는 *_geom + 필수 메타 포함. */
  onCreate?: (kind: DraftEntityKind, body: Record<string, unknown>) => void;
}

export function DraftSceneCanvas({
  draft,
  selectedRef,
  onSelect,
  onDragEnd,
  tool = 'select',
  onCreate,
}: Props) {
  const vb = computeViewBox(draft);
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [creating, setCreating] = useState<CreatingState>(null);
  const [cursorPos, setCursorPos] = useState<Coord | null>(null);

  // 도구 변화에 따른 임시 생성 상태 리셋 (props 변화 시 state 조정 패턴).
  // useEffect 대신 render 중에 비교 → setState 하면 cascading render 없이 즉시 리셋.
  const [prevTool, setPrevTool] = useState(tool);
  if (prevTool !== tool) {
    setPrevTool(tool);
    setCreating(null);
    setCursorPos(null);
  }

  const isCreationMode = tool === 'rect' || tool === 'circle' || tool === 'text';

  // Escape 키로 진행 중 생성 취소
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setCreating(null);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

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

  const startShapeDrag = (e: React.PointerEvent, ref: SelectedEntityRef) => {
    // 생성 모드에선 도형 클릭이 드래그/선택을 일으키지 않음. 이벤트가 SVG 로 버블링되어
    // 빈 캔버스 클릭과 동일하게 처리되도록 stopPropagation 안 함.
    if (tool !== 'select') return;
    e.stopPropagation();
    const pt = getSvgPoint(e);
    if (!pt) return;
    svgRef.current?.setPointerCapture(e.pointerId);
    setDrag({ mode: 'shape', ref, startSvg: pt, delta: [0, 0] });
    onSelect?.(ref);
  };

  const startVertexDrag = (
    e: React.PointerEvent,
    ref: SelectedEntityRef,
    vertexIndex: number,
  ) => {
    if (tool !== 'select') return;
    e.stopPropagation();
    const pt = getSvgPoint(e);
    if (!pt) return;
    svgRef.current?.setPointerCapture(e.pointerId);
    setDrag({ mode: 'vertex', ref, vertexIndex, startSvg: pt, delta: [0, 0] });
    onSelect?.(ref);
  };

  const handleSvgPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const pt = getSvgPoint(e);
    if (!pt) return;
    // 생성 모드 / 벽 그리기 preview 용으로 항상 cursor 추적
    if (isCreationMode) setCursorPos(pt);
    if (!drag) return;
    setDrag((prev) =>
      prev ? { ...prev, delta: [pt[0] - prev.startSvg[0], pt[1] - prev.startSvg[1]] } : null,
    );
  };

  const handleSvgPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!drag) return;
    try {
      svgRef.current?.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
    const captured = drag;
    setDrag(null);

    const [dx, dy] = captured.delta;
    if (Math.abs(dx) < DRAG_THRESHOLD_M && Math.abs(dy) < DRAG_THRESHOLD_M) return;

    const newGeom = buildDraggedGeometry(captured, draft);
    if (newGeom) onDragEnd?.(captured.ref, newGeom);
  };

  const handleSvgPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    // 생성 모드 처리
    if (tool === 'rect') {
      const pt = getSvgPoint(e);
      if (!pt) return;
      if (!creating) {
        // 첫 클릭: 시작점 저장
        setCreating({ kind: 'wall', firstPoint: pt });
      } else {
        // 두 번째 클릭: 벽 생성
        const start = creating.firstPoint;
        const dx = pt[0] - start[0];
        const dy = pt[1] - start[1];
        if (Math.abs(dx) > DRAG_THRESHOLD_M || Math.abs(dy) > DRAG_THRESHOLD_M) {
          onCreate?.('wall', {
            wall_role: 'inner',
            source_method: 'user_drawn',
            centerline_geom: {
              type: 'LineString',
              coordinates: [start, pt],
            },
          });
        }
        setCreating(null);
      }
      return;
    }
    if (tool === 'circle') {
      const pt = getSvgPoint(e);
      if (!pt) return;
      onCreate?.('object', {
        object_type: 'furniture',
        source_method: 'user_drawn',
        point_geom: { type: 'Point', coordinates: pt },
      });
      return;
    }
    // select 모드: 빈 영역 클릭 → 선택 해제
    if (e.target === e.currentTarget) onSelect?.(null);
  };

  const isSelected = (kind: SelectedEntityRef['kind'], id: string) =>
    selectedRef?.kind === kind && selectedRef.id === id;

  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden bg-[#f8fafc] p-6 [background-image:radial-gradient(circle,_oklch(0.92_0_0)_1px,_transparent_1px)] [background-position:0_0] [background-size:18px_18px]">
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMid meet"
        className={
          isCreationMode
            ? 'h-full w-full cursor-crosshair select-none'
            : 'h-full w-full select-none'
        }
        onPointerDown={handleSvgPointerDown}
        onPointerMove={handleSvgPointerMove}
        onPointerUp={handleSvgPointerUp}
        onPointerCancel={handleSvgPointerUp}
      >
        {draft.rooms.map((room) => (
          <RoomShape
            key={room.id}
            room={room}
            selected={isSelected('room', room.id)}
            drag={matchDrag(drag, 'room', room.id)}
            onShapePointerDown={(e) => startShapeDrag(e, { kind: 'room', id: room.id })}
            onVertexPointerDown={(e, idx) =>
              startVertexDrag(e, { kind: 'room', id: room.id }, idx)
            }
          />
        ))}

        {draft.walls.map((wall) => (
          <WallShape
            key={wall.id}
            wall={wall}
            selected={isSelected('wall', wall.id)}
            drag={matchDrag(drag, 'wall', wall.id)}
            onShapePointerDown={(e) => startShapeDrag(e, { kind: 'wall', id: wall.id })}
            onVertexPointerDown={(e, idx) =>
              startVertexDrag(e, { kind: 'wall', id: wall.id }, idx)
            }
          />
        ))}

        {draft.openings.map((op) => (
          <OpeningShape
            key={op.id}
            opening={op}
            selected={isSelected('opening', op.id)}
            drag={matchDrag(drag, 'opening', op.id)}
            onShapePointerDown={(e) => startShapeDrag(e, { kind: 'opening', id: op.id })}
            onVertexPointerDown={(e, idx) =>
              startVertexDrag(e, { kind: 'opening', id: op.id }, idx)
            }
          />
        ))}

        {draft.objects.map((obj) => (
          <ObjectShape
            key={obj.id}
            object={obj}
            selected={isSelected('object', obj.id)}
            drag={matchDrag(drag, 'object', obj.id)}
            onShapePointerDown={(e) => startShapeDrag(e, { kind: 'object', id: obj.id })}
          />
        ))}

        {/* 벽 생성 preview — 첫 점 찍은 후 cursor 까지 점선 */}
        {creating?.kind === 'wall' && cursorPos && (
          <g pointerEvents="none">
            <line
              x1={creating.firstPoint[0]}
              y1={creating.firstPoint[1]}
              x2={cursorPos[0]}
              y2={cursorPos[1]}
              stroke="oklch(0.55 0.22 264)"
              strokeWidth="4"
              strokeDasharray="6 4"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={creating.firstPoint[0]}
              cy={creating.firstPoint[1]}
              r="0.15"
              fill="oklch(0.55 0.22 264)"
            />
          </g>
        )}

        {/* 가구 placement hover hint */}
        {tool === 'circle' && cursorPos && (
          <circle
            cx={cursorPos[0]}
            cy={cursorPos[1]}
            r="0.18"
            fill="oklch(0.9 0.04 256)"
            stroke="oklch(0.55 0.22 264)"
            strokeWidth="2"
            strokeDasharray="3 2"
            vectorEffect="non-scaling-stroke"
            opacity="0.7"
            pointerEvents="none"
          />
        )}
      </svg>

      <ScaleHint draft={draft} bounds={vb} dragging={!!drag} />
      {isCreationMode && <CreationHint tool={tool} creating={creating} />}
    </div>
  );
}

function CreationHint({
  tool,
  creating,
}: {
  tool: EditorTool;
  creating: CreatingState;
}) {
  let text = '';
  if (tool === 'rect') {
    text = creating
      ? '두 번째 점을 클릭해 벽을 완성하세요. (Esc 취소)'
      : '첫 번째 점을 클릭해 벽 그리기를 시작하세요.';
  } else if (tool === 'circle') {
    text = '캔버스를 클릭해 가구를 배치하세요.';
  } else if (tool === 'text') {
    text = '구역 라벨 추가는 현재 미지원입니다.';
  }
  if (!text) return null;
  return (
    <div className="pointer-events-none absolute left-1/2 top-4 -translate-x-1/2 rounded-md bg-slate-900/90 px-3 py-1.5 text-xs font-medium text-white shadow-md">
      {text}
    </div>
  );
}

function matchDrag(
  drag: DragState | null,
  kind: SelectedEntityRef['kind'],
  id: string,
): DragState | null {
  if (drag && drag.ref.kind === kind && drag.ref.id === id) return drag;
  return null;
}

/** drag 진행 중인 도형의 effective coords 계산 (rendering 용). */
function effectiveLineCoords(coords: Coord[], drag: DragState | null): Coord[] {
  if (!drag) return coords;
  const [dx, dy] = drag.delta;
  if (drag.mode === 'shape') {
    return coords.map(([x, y]) => [x + dx, y + dy] as Coord);
  }
  return moveLineStringVertex(coords, drag.vertexIndex, dx, dy);
}

function effectivePolygonRings(rings: Coord[][], drag: DragState | null): Coord[][] {
  if (!drag) return rings;
  const [dx, dy] = drag.delta;
  if (drag.mode === 'shape') {
    return rings.map((r) => r.map(([x, y]) => [x + dx, y + dy] as Coord));
  }
  return movePolygonVertex(rings, drag.vertexIndex, dx, dy);
}

function effectivePoint(p: Coord, drag: DragState | null): Coord {
  if (!drag) return p;
  if (drag.mode !== 'shape') return p;
  const [dx, dy] = drag.delta;
  return [p[0] + dx, p[1] + dy];
}

/** drag 종료 시 적용할 새 GeoJSON 생성. */
function buildDraggedGeometry(drag: DragState, draft: SceneDraft): GeoJsonGeometry | null {
  const { ref } = drag;
  if (ref.kind === 'wall') {
    const w = draft.walls.find((x) => x.id === ref.id);
    const g = parseGeometry(w?.centerline_geom);
    if (g?.type !== 'LineString') return null;
    if (drag.mode === 'shape') return translateGeometry(g, drag.delta[0], drag.delta[1]);
    return {
      type: 'LineString',
      coordinates: moveLineStringVertex(g.coordinates, drag.vertexIndex, drag.delta[0], drag.delta[1]),
    };
  }
  if (ref.kind === 'opening') {
    const o = draft.openings.find((x) => x.id === ref.id);
    const g = parseGeometry(o?.line_geom);
    if (g?.type !== 'LineString') return null;
    if (drag.mode === 'shape') return translateGeometry(g, drag.delta[0], drag.delta[1]);
    return {
      type: 'LineString',
      coordinates: moveLineStringVertex(g.coordinates, drag.vertexIndex, drag.delta[0], drag.delta[1]),
    };
  }
  if (ref.kind === 'room') {
    const r = draft.rooms.find((x) => x.id === ref.id);
    const g = parseGeometry(r?.polygon_geom);
    if (g?.type !== 'Polygon') return null;
    if (drag.mode === 'shape') return translateGeometry(g, drag.delta[0], drag.delta[1]);
    return {
      type: 'Polygon',
      coordinates: movePolygonVertex(g.coordinates, drag.vertexIndex, drag.delta[0], drag.delta[1]),
    };
  }
  // object — Point, vertex 모드는 무의미. shape drag 만.
  const o = draft.objects.find((x) => x.id === ref.id);
  const g = parseGeometry(o?.point_geom);
  if (g?.type !== 'Point') return null;
  if (drag.mode !== 'shape') return null;
  return translateGeometry(g, drag.delta[0], drag.delta[1]);
}

// ============================================
// 도형 컴포넌트
// ============================================

interface ShapeBaseProps {
  selected: boolean;
  drag: DragState | null;
  onShapePointerDown: (e: React.PointerEvent) => void;
}
interface VertexAwareProps extends ShapeBaseProps {
  onVertexPointerDown: (e: React.PointerEvent, vertexIndex: number) => void;
}

function RoomShape({
  room,
  selected,
  drag,
  onShapePointerDown,
  onVertexPointerDown,
}: { room: DraftRoom } & VertexAwareProps) {
  const g = parseGeometry(room.polygon_geom);
  if (g?.type !== 'Polygon') return null;
  const rings = effectivePolygonRings(g.coordinates, drag);
  const ring = rings[0];
  if (!ring) return null;
  const isClosed =
    ring.length > 0 &&
    ring[0][0] === ring[ring.length - 1][0] &&
    ring[0][1] === ring[ring.length - 1][1];
  const handlePts = isClosed ? ring.slice(0, -1) : ring;
  const points = ring.map(([x, y]) => `${x},${y}`).join(' ');
  return (
    <g>
      <polygon
        points={points}
        fill={selected ? 'oklch(0.92 0.05 264)' : 'oklch(0.95 0.01 256)'}
        stroke={selected ? 'oklch(0.55 0.22 264)' : 'oklch(0.86 0 0)'}
        strokeWidth={selected ? 3 : 1.5}
        vectorEffect="non-scaling-stroke"
        className="cursor-pointer"
        onPointerDown={onShapePointerDown}
      />
      {selected &&
        handlePts.map((pt, i) => (
          <VertexHandle
            key={i}
            x={pt[0]}
            y={pt[1]}
            onPointerDown={(e) => onVertexPointerDown(e, i)}
          />
        ))}
    </g>
  );
}

function WallShape({
  wall,
  selected,
  drag,
  onShapePointerDown,
  onVertexPointerDown,
}: { wall: DraftWall } & VertexAwareProps) {
  const g = parseGeometry(wall.centerline_geom);
  if (g?.type !== 'LineString') return null;
  const coords = effectiveLineCoords(g.coordinates, drag);
  const [start, end] = coords;
  if (!start || !end) return null;
  return (
    <g>
      <line
        x1={start[0]}
        y1={start[1]}
        x2={end[0]}
        y2={end[1]}
        stroke="transparent"
        strokeWidth="14"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        className="cursor-pointer"
        onPointerDown={onShapePointerDown}
      />
      <line
        x1={start[0]}
        y1={start[1]}
        x2={end[0]}
        y2={end[1]}
        stroke={selected ? 'oklch(0.55 0.22 264)' : 'oklch(0.25 0 0)'}
        strokeWidth={selected ? 6 : 4}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        pointerEvents="none"
      />
      {selected && (
        <>
          <VertexHandle x={start[0]} y={start[1]} onPointerDown={(e) => onVertexPointerDown(e, 0)} />
          <VertexHandle x={end[0]} y={end[1]} onPointerDown={(e) => onVertexPointerDown(e, 1)} />
        </>
      )}
    </g>
  );
}

function OpeningShape({
  opening,
  selected,
  drag,
  onShapePointerDown,
  onVertexPointerDown,
}: { opening: DraftOpening } & VertexAwareProps) {
  const g = parseGeometry(opening.line_geom);
  if (g?.type !== 'LineString') return null;
  const coords = effectiveLineCoords(g.coordinates, drag);
  const [start, end] = coords;
  if (!start || !end) return null;
  const isDoor = opening.opening_type === 'door';
  const baseColor = isDoor ? 'oklch(0.55 0.22 264)' : 'oklch(0.7 0.18 200)';
  return (
    <g>
      <line
        x1={start[0]}
        y1={start[1]}
        x2={end[0]}
        y2={end[1]}
        stroke="transparent"
        strokeWidth="14"
        vectorEffect="non-scaling-stroke"
        className="cursor-pointer"
        onPointerDown={onShapePointerDown}
      />
      <line
        x1={start[0]}
        y1={start[1]}
        x2={end[0]}
        y2={end[1]}
        stroke={baseColor}
        strokeWidth={selected ? 8 : 5}
        strokeLinecap="butt"
        vectorEffect="non-scaling-stroke"
        pointerEvents="none"
      />
      {selected && (
        <>
          <VertexHandle x={start[0]} y={start[1]} onPointerDown={(e) => onVertexPointerDown(e, 0)} />
          <VertexHandle x={end[0]} y={end[1]} onPointerDown={(e) => onVertexPointerDown(e, 1)} />
        </>
      )}
    </g>
  );
}

function ObjectShape({
  object,
  selected,
  drag,
  onShapePointerDown,
}: { object: DraftObject } & ShapeBaseProps) {
  const g = parseGeometry(object.point_geom);
  if (g?.type !== 'Point') return null;
  const [x, y] = effectivePoint(g.coordinates, drag);
  return (
    <g onPointerDown={onShapePointerDown} className="cursor-pointer">
      <circle cx={x} cy={y} r="0.4" fill="transparent" />
      <circle
        cx={x}
        cy={y}
        r="0.18"
        fill={selected ? 'oklch(0.55 0.22 264)' : 'oklch(0.9 0.04 256)'}
        stroke={selected ? 'oklch(0.45 0.22 264)' : 'oklch(0.55 0.22 264)'}
        strokeWidth={selected ? 3 : 1.5}
        vectorEffect="non-scaling-stroke"
      />
    </g>
  );
}

function VertexHandle({
  x,
  y,
  onPointerDown,
}: {
  x: number;
  y: number;
  onPointerDown: (e: React.PointerEvent) => void;
}) {
  return (
    <g onPointerDown={onPointerDown} className="cursor-grab">
      {/* 클릭 영역 확장 */}
      <circle cx={x} cy={y} r="0.35" fill="transparent" />
      <circle
        cx={x}
        cy={y}
        r="0.16"
        fill="white"
        stroke="oklch(0.55 0.22 264)"
        strokeWidth="3"
        vectorEffect="non-scaling-stroke"
      />
    </g>
  );
}

function ScaleHint({
  draft,
  bounds,
  dragging,
}: {
  draft: SceneDraft;
  bounds: { w: number; h: number };
  dragging?: boolean;
}) {
  const summary = (draft.summary_json ?? {}) as { storage?: { real_width_m?: number } };
  const realWidth = summary.storage?.real_width_m;
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 inline-flex items-center gap-2 rounded-md border bg-background/90 px-2.5 py-1 text-[11px] text-muted-foreground shadow-sm backdrop-blur">
      <span className="font-mono">
        {bounds.w.toFixed(1)} × {bounds.h.toFixed(1)} m
      </span>
      {realWidth != null && (
        <>
          <span className="h-3 w-px bg-border" />
          <span>입력 너비 {realWidth} m</span>
        </>
      )}
      {dragging && (
        <>
          <span className="h-3 w-px bg-border" />
          <span className="text-primary">드래그 중…</span>
        </>
      )}
    </div>
  );
}
