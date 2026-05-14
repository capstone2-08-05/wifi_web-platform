import { useEffect, useMemo, useRef, useState } from 'react';
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

/** 생성 진행 중 임시 상태. */
type CreatingState =
  | { kind: 'wall'; firstPoint: Coord }
  | { kind: 'opening'; firstPoint: Coord }
  | { kind: 'polygon'; points: Coord[] }
  | null;

/** 폴리곤 닫기 임계값 (미터). 시작점 근처 클릭으로 인식. */
const POLYGON_CLOSE_THRESHOLD_M = 0.4;

/** 끝점 스냅 반경 (미터). 이 안에 기존 끝점이 있으면 딱 붙음. */
const SNAP_RADIUS_M = 0.25;
/** 수평/수직 스냅 허용 오차 (미터). 그리는 선이 거의 수평/수직이면 정확히 맞춤. */
const AXIS_SNAP_TOLERANCE_M = 0.2;

function distance(a: Coord, b: Coord): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

// ============================================
// 스냅 (벽 잇기 보조)
// ============================================
/** draft 내 모든 끝점/꼭짓점을 스냅 anchor 로 수집. exclude 한 엔티티는 제외. */
function collectSnapAnchors(
  draft: SceneDraft,
  exclude?: SelectedEntityRef | null,
): Coord[] {
  const anchors: Coord[] = [];
  for (const wall of draft.walls) {
    if (exclude?.kind === 'wall' && exclude.id === wall.id) continue;
    const g = parseGeometry(wall.centerline_geom);
    if (g?.type === 'LineString') for (const c of g.coordinates) anchors.push(c);
  }
  for (const op of draft.openings) {
    if (exclude?.kind === 'opening' && exclude.id === op.id) continue;
    const g = parseGeometry(op.line_geom);
    if (g?.type === 'LineString') for (const c of g.coordinates) anchors.push(c);
  }
  for (const room of draft.rooms) {
    if (exclude?.kind === 'room' && exclude.id === room.id) continue;
    const g = parseGeometry(room.polygon_geom);
    if (g?.type === 'Polygon') for (const ring of g.coordinates) for (const c of ring) anchors.push(c);
  }
  return anchors;
}

/** pt 에서 radius 이내 가장 가까운 anchor. 없으면 null. */
function nearestAnchor(pt: Coord, anchors: Coord[], radius: number): Coord | null {
  let best: Coord | null = null;
  let bestD = radius;
  for (const a of anchors) {
    const d = Math.hypot(a[0] - pt[0], a[1] - pt[1]);
    if (d < bestD) {
      bestD = d;
      best = a;
    }
  }
  return best;
}

/** from 기준으로 to 가 거의 수평/수직이면 정확히 맞춘 좌표 반환. */
function axisSnap(from: Coord, to: Coord, tol: number): Coord {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  if (Math.abs(dy) < tol && Math.abs(dx) >= Math.abs(dy)) return [to[0], from[1]];
  if (Math.abs(dx) < tol && Math.abs(dy) > Math.abs(dx)) return [from[0], to[1]];
  return to;
}

interface SnapResult {
  point: Coord;
  snapped: boolean;
}

/** 끝점 스냅(1순위) → 축 스냅(2순위, axisFrom 지정 시) 순으로 적용. */
function snapPoint(
  raw: Coord,
  anchors: Coord[],
  axisFrom?: Coord | null,
): SnapResult {
  const anchor = nearestAnchor(raw, anchors, SNAP_RADIUS_M);
  if (anchor) return { point: [anchor[0], anchor[1]], snapped: true };
  if (axisFrom) {
    const axed = axisSnap(axisFrom, raw, AXIS_SNAP_TOLERANCE_M);
    if (axed[0] !== raw[0] || axed[1] !== raw[1]) return { point: axed, snapped: true };
  }
  return { point: raw, snapped: false };
}

/** 선택된 엔티티의 vertexIndex 번째 꼭짓점 좌표 (스냅 기준점 계산용). */
function getEntityVertex(
  draft: SceneDraft,
  ref: SelectedEntityRef,
  vertexIndex: number,
): Coord | null {
  if (ref.kind === 'wall') {
    const g = parseGeometry(draft.walls.find((w) => w.id === ref.id)?.centerline_geom);
    return g?.type === 'LineString' ? g.coordinates[vertexIndex] ?? null : null;
  }
  if (ref.kind === 'opening') {
    const g = parseGeometry(draft.openings.find((o) => o.id === ref.id)?.line_geom);
    return g?.type === 'LineString' ? g.coordinates[vertexIndex] ?? null : null;
  }
  if (ref.kind === 'room') {
    const g = parseGeometry(draft.rooms.find((r) => r.id === ref.id)?.polygon_geom);
    return g?.type === 'Polygon' ? g.coordinates[0]?.[vertexIndex] ?? null : null;
  }
  return null;
}

/** 엔티티의 모든 "기준점" — shape 드래그 스냅 시 어떤 점이든 anchor 에 붙도록. */
function getEntityRefPoints(draft: SceneDraft, ref: SelectedEntityRef): Coord[] {
  if (ref.kind === 'wall') {
    const g = parseGeometry(draft.walls.find((w) => w.id === ref.id)?.centerline_geom);
    return g?.type === 'LineString' ? g.coordinates : [];
  }
  if (ref.kind === 'opening') {
    const g = parseGeometry(draft.openings.find((o) => o.id === ref.id)?.line_geom);
    return g?.type === 'LineString' ? g.coordinates : [];
  }
  if (ref.kind === 'room') {
    const g = parseGeometry(draft.rooms.find((r) => r.id === ref.id)?.polygon_geom);
    return g?.type === 'Polygon' ? g.coordinates[0] ?? [] : [];
  }
  // object — Point 하나
  const g = parseGeometry(draft.objects.find((o) => o.id === ref.id)?.point_geom);
  return g?.type === 'Point' ? [g.coordinates] : [];
}

/** 점 p 를 선분 a-b 에 수직투영한 좌표. */
function projectOnSegment(p: Coord, a: Coord, b: Coord): Coord {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lenSq = dx * dx + dy * dy;
  if (lenSq < 1e-9) return [a[0], a[1]];
  let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return [a[0] + t * dx, a[1] + t * dy];
}

/** pt 에서 radius 이내, 가장 가까운 wall 선분 위의 점 (객체를 벽에 붙이기용). */
function nearestWallProjection(
  pt: Coord,
  draft: SceneDraft,
  radius: number,
): Coord | null {
  let best: Coord | null = null;
  let bestD = radius;
  for (const wall of draft.walls) {
    const g = parseGeometry(wall.centerline_geom);
    if (g?.type !== 'LineString') continue;
    for (let i = 0; i + 1 < g.coordinates.length; i++) {
      const proj = projectOnSegment(pt, g.coordinates[i], g.coordinates[i + 1]);
      const d = Math.hypot(proj[0] - pt[0], proj[1] - pt[1]);
      if (d < bestD) {
        bestD = d;
        best = proj;
      }
    }
  }
  return best;
}

/**
 * shape 드래그(엔티티 통째 이동) 스냅 delta 계산.
 * - 모든 기준점 중 하나라도 기존 anchor 끝점 근처면 거기에 붙임.
 * - object 는 추가로 벽 선분 위에도 투영 (벽에 딱 붙이기).
 */
function computeShapeSnapDelta(
  draft: SceneDraft,
  ref: SelectedEntityRef,
  rawDelta: Coord,
  anchors: Coord[],
): { delta: Coord; snapPoint: Coord | null } {
  const pts = getEntityRefPoints(draft, ref);
  let best: { from: Coord; to: Coord } | null = null;
  let bestD = SNAP_RADIUS_M;

  for (const pt of pts) {
    const moved: Coord = [pt[0] + rawDelta[0], pt[1] + rawDelta[1]];
    const anchor = nearestAnchor(moved, anchors, SNAP_RADIUS_M);
    if (anchor) {
      const d = Math.hypot(anchor[0] - moved[0], anchor[1] - moved[1]);
      if (d < bestD) {
        bestD = d;
        best = { from: pt, to: [anchor[0], anchor[1]] };
      }
    }
  }

  // object: 벽 선분 위로 투영 (끝점 스냅이 없을 때만 시도)
  if (ref.kind === 'object' && pts.length === 1) {
    const moved: Coord = [pts[0][0] + rawDelta[0], pts[0][1] + rawDelta[1]];
    const proj = nearestWallProjection(moved, draft, SNAP_RADIUS_M);
    if (proj) {
      const d = Math.hypot(proj[0] - moved[0], proj[1] - moved[1]);
      if (d < bestD) {
        bestD = d;
        best = { from: pts[0], to: proj };
      }
    }
  }

  if (best) {
    return {
      delta: [best.to[0] - best.from[0], best.to[1] - best.from[1]],
      snapPoint: best.to,
    };
  }
  return { delta: rawDelta, snapPoint: null };
}

function polygonCentroid(points: Coord[]): Coord {
  if (points.length === 0) return [0, 0];
  const n = points.length;
  const sx = points.reduce((s, p) => s + p[0], 0);
  const sy = points.reduce((s, p) => s + p[1], 0);
  return [sx / n, sy / n];
}

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
  // 스냅 발생 시 표시할 위치 (초록 링). 스냅 안 되면 null.
  const [snapIndicator, setSnapIndicator] = useState<Coord | null>(null);

  // 스냅 anchor 목록 — 드래그/선택 중인 엔티티는 자기 자신에 안 붙도록 제외.
  const snapAnchors = useMemo(
    () => collectSnapAnchors(draft, selectedRef ?? null),
    [draft, selectedRef],
  );

  // 도구 변화에 따른 임시 생성 상태 리셋 (props 변화 시 state 조정 패턴).
  // useEffect 대신 render 중에 비교 → setState 하면 cascading render 없이 즉시 리셋.
  const [prevTool, setPrevTool] = useState(tool);
  if (prevTool !== tool) {
    setPrevTool(tool);
    setCreating(null);
    setCursorPos(null);
    setSnapIndicator(null);
  }

  const isCreationMode =
    tool === 'rect' ||
    tool === 'circle' ||
    tool === 'text' ||
    tool === 'polygon' ||
    tool === 'opening';

  // Escape 키로 진행 중 생성 취소
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setCreating(null);
        setSnapIndicator(null);
      }
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
    const raw = getSvgPoint(e);
    if (!raw) return;

    // ─ 생성 모드: cursor 를 스냅해서 preview 가 딱 붙도록 ─
    if (isCreationMode) {
      // 벽/문창 그리는 중이면 첫 점 기준 수평/수직 스냅도 적용
      const axisFrom =
        creating && (creating.kind === 'wall' || creating.kind === 'opening')
          ? creating.firstPoint
          : null;
      const res = snapPoint(raw, snapAnchors, axisFrom);
      setCursorPos(res.point);
      setSnapIndicator(res.snapped ? res.point : null);
    }

    if (!drag) {
      if (!isCreationMode) setSnapIndicator(null);
      return;
    }

    // ─ vertex 드래그: 목표 꼭짓점을 스냅 → snapped delta 로 반영 ─
    if (drag.mode === 'vertex') {
      const orig = getEntityVertex(draft, drag.ref, drag.vertexIndex);
      if (orig) {
        const rawTarget: Coord = [
          orig[0] + (raw[0] - drag.startSvg[0]),
          orig[1] + (raw[1] - drag.startSvg[1]),
        ];
        const res = snapPoint(rawTarget, snapAnchors);
        setSnapIndicator(res.snapped ? res.point : null);
        setDrag((prev) =>
          prev
            ? { ...prev, delta: [res.point[0] - orig[0], res.point[1] - orig[1]] }
            : null,
        );
        return;
      }
    }

    // ─ shape 드래그: object 는 벽/앵커에 스냅, wall/opening/room 은 끝점·꼭짓점 스냅 ─
    {
      const rawDelta: Coord = [raw[0] - drag.startSvg[0], raw[1] - drag.startSvg[1]];
      const { delta, snapPoint } = computeShapeSnapDelta(
        draft,
        drag.ref,
        rawDelta,
        snapAnchors,
      );
      setSnapIndicator(snapPoint);
      setDrag((prev) => (prev ? { ...prev, delta } : null));
    }
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
    setSnapIndicator(null);

    const [dx, dy] = captured.delta;
    if (Math.abs(dx) < DRAG_THRESHOLD_M && Math.abs(dy) < DRAG_THRESHOLD_M) return;

    const newGeom = buildDraggedGeometry(captured, draft);
    if (newGeom) onDragEnd?.(captured.ref, newGeom);
  };

  const handleSvgPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    // ─ 벽 (2 클릭 LineString) ─
    if (tool === 'rect') {
      const raw = getSvgPoint(e);
      if (!raw) return;
      if (!creating || creating.kind !== 'wall') {
        // 첫 점도 기존 끝점에 스냅 (벽 잇기 시작점 정확히)
        const start = snapPoint(raw, snapAnchors).point;
        setCreating({ kind: 'wall', firstPoint: start });
      } else {
        const start = creating.firstPoint;
        const pt = snapPoint(raw, snapAnchors, start).point;
        if (Math.abs(pt[0] - start[0]) > DRAG_THRESHOLD_M || Math.abs(pt[1] - start[1]) > DRAG_THRESHOLD_M) {
          onCreate?.('wall', {
            wall_role: 'inner',
            source_method: 'user_drawn',
            centerline_geom: { type: 'LineString', coordinates: [start, pt] },
          });
        }
        setCreating(null);
        setSnapIndicator(null);
      }
      return;
    }

    // ─ 문/창 (2 클릭 LineString, opening_type=door 기본) ─
    if (tool === 'opening') {
      const raw = getSvgPoint(e);
      if (!raw) return;
      if (!creating || creating.kind !== 'opening') {
        const start = snapPoint(raw, snapAnchors).point;
        setCreating({ kind: 'opening', firstPoint: start });
      } else {
        const start = creating.firstPoint;
        const pt = snapPoint(raw, snapAnchors, start).point;
        const width = distance(start, pt);
        if (width > DRAG_THRESHOLD_M) {
          onCreate?.('opening', {
            opening_type: 'door',
            width_m: Number(width.toFixed(2)),
            height_m: 2.1,
            source_method: 'user_drawn',
            line_geom: { type: 'LineString', coordinates: [start, pt] },
          });
        }
        setCreating(null);
        setSnapIndicator(null);
      }
      return;
    }

    // ─ 가구 (1 클릭 Point) ─
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

    // ─ 방 (다중 클릭 Polygon, 시작점 클릭 또는 Enter 로 닫기) ─
    if (tool === 'polygon') {
      const pt = getSvgPoint(e);
      if (!pt) return;
      if (!creating || creating.kind !== 'polygon') {
        setCreating({ kind: 'polygon', points: [pt] });
        return;
      }
      const pts = creating.points;
      // 3 점 이상일 때 시작점 근처 클릭 → 닫기
      if (pts.length >= 3 && distance(pt, pts[0]) < POLYGON_CLOSE_THRESHOLD_M) {
        const ring = [...pts, pts[0]];
        const centroid = polygonCentroid(pts);
        onCreate?.('room', {
          room_type: 'general',
          source_method: 'user_drawn',
          polygon_geom: { type: 'Polygon', coordinates: [ring] },
          centroid_geom: { type: 'Point', coordinates: centroid },
        });
        setCreating(null);
        return;
      }
      // 그 외 → 점 추가
      setCreating({ kind: 'polygon', points: [...pts, pt] });
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

        {/* 벽 생성 preview */}
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

        {/* 개구부(문/창) 생성 preview */}
        {creating?.kind === 'opening' && cursorPos && (
          <g pointerEvents="none">
            <line
              x1={creating.firstPoint[0]}
              y1={creating.firstPoint[1]}
              x2={cursorPos[0]}
              y2={cursorPos[1]}
              stroke="oklch(0.55 0.22 264)"
              strokeWidth="5"
              strokeDasharray="4 3"
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

        {/* 방(다각형) 생성 preview */}
        {creating?.kind === 'polygon' && (() => {
          const pts = creating.points;
          const canClose =
            pts.length >= 3 && cursorPos && distance(cursorPos, pts[0]) < POLYGON_CLOSE_THRESHOLD_M;
          const polyPoints = pts.map(([x, y]) => `${x},${y}`).join(' ');
          return (
            <g pointerEvents="none">
              {/* 닫혀 보이도록 hover 상태에선 채우기 */}
              {canClose && pts.length >= 3 && (
                <polygon
                  points={polyPoints}
                  fill="oklch(0.92 0.05 264 / 0.3)"
                  stroke="oklch(0.55 0.22 264)"
                  strokeWidth="3"
                  strokeDasharray="6 4"
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {/* 이어진 변들 */}
              {!canClose && pts.length >= 2 && (
                <polyline
                  points={polyPoints}
                  fill="none"
                  stroke="oklch(0.55 0.22 264)"
                  strokeWidth="3"
                  strokeDasharray="6 4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {/* 마지막 점 → cursor preview 변 */}
              {!canClose && cursorPos && pts.length > 0 && (
                <line
                  x1={pts[pts.length - 1][0]}
                  y1={pts[pts.length - 1][1]}
                  x2={cursorPos[0]}
                  y2={cursorPos[1]}
                  stroke="oklch(0.55 0.22 264)"
                  strokeWidth="2"
                  strokeDasharray="3 3"
                  strokeLinecap="round"
                  opacity="0.6"
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {/* 꼭짓점들 — 첫 점은 크게(닫기 가능 표시) */}
              {pts.map((p, i) => {
                const isFirst = i === 0;
                const isFirstHighlighted = isFirst && canClose;
                return (
                  <circle
                    key={i}
                    cx={p[0]}
                    cy={p[1]}
                    r={isFirstHighlighted ? 0.28 : isFirst ? 0.2 : 0.13}
                    fill={isFirstHighlighted ? 'oklch(0.55 0.22 264)' : 'white'}
                    stroke="oklch(0.55 0.22 264)"
                    strokeWidth={isFirstHighlighted ? 2 : 3}
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
            </g>
          );
        })()}

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

        {/* 스냅 인디케이터 — 끝점/축에 딱 붙었을 때 초록 링 */}
        {snapIndicator && (
          <g pointerEvents="none">
            <circle
              cx={snapIndicator[0]}
              cy={snapIndicator[1]}
              r="0.28"
              fill="none"
              stroke="oklch(0.72 0.19 145)"
              strokeWidth="2.5"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={snapIndicator[0]}
              cy={snapIndicator[1]}
              r="0.07"
              fill="oklch(0.72 0.19 145)"
            />
          </g>
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
    text =
      creating?.kind === 'wall'
        ? '두 번째 점을 클릭해 벽을 완성하세요. 기존 끝점·수평/수직에 자동으로 붙습니다. (Esc 취소)'
        : '첫 번째 점을 클릭해 벽 그리기를 시작하세요. 기존 벽 끝점 근처면 딱 붙습니다.';
  } else if (tool === 'opening') {
    text =
      creating?.kind === 'opening'
        ? '두 번째 점을 클릭해 문/창을 완성하세요. 벽 끝점·수평/수직에 자동으로 붙습니다. (Esc 취소)'
        : '첫 번째 점을 클릭해 문/창 그리기를 시작하세요.';
  } else if (tool === 'polygon') {
    if (!creating || creating.kind !== 'polygon') {
      text = '첫 번째 점을 클릭해 방 만들기를 시작하세요.';
    } else if (creating.points.length < 3) {
      text = `점을 클릭해 방 외곽을 만드세요 (${creating.points.length}/3+). Esc 로 취소.`;
    } else {
      text = `시작점을 다시 클릭하면 방이 완성됩니다. (현재 ${creating.points.length}개 점)`;
    }
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
