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

type ViewBox = { x: number; y: number; w: number; h: number };

/** 도형(rooms/walls/openings) 의 미터 단위 bounding box. 가구(objects) 는 제외. */
function computeShapeBounds(draft: SceneDraft): Bounds {
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
  return b;
}

/**
 * 캔버스 viewBox 계산.
 * - imageExtent 가 있으면 (real_width_m + 이미지 natural 비율로 추정한 실제 미터 크기):
 *   이미지가 (0,0) ~ (imageExtent.w, imageExtent.h) 에 위치한다고 가정하고, 도형 bounds 와
 *   합집합 → "도형을 줄여도 캔버스가 이미지 크기만큼은 유지" 됨 (사용자 요구).
 * - imageExtent 가 없으면 도형 bounds 만 사용 (기존 동작 fallback).
 */
function computeViewBox(
  draft: SceneDraft,
  imageExtent?: { w: number; h: number } | null,
): ViewBox {
  const b = computeShapeBounds(draft);
  if (imageExtent && imageExtent.w > 0 && imageExtent.h > 0) {
    // 이미지는 (0, 0) 기준 배치. 도형 bounds 와 합집합.
    if (!isFinite(b.minX)) {
      // 도형이 비어있으면 이미지만으로 계산.
      const padding = Math.max(imageExtent.w, imageExtent.h) * 0.05;
      return {
        x: -padding,
        y: -padding,
        w: imageExtent.w + 2 * padding,
        h: imageExtent.h + 2 * padding,
      };
    }
    const minX = Math.min(b.minX, 0);
    const minY = Math.min(b.minY, 0);
    const maxX = Math.max(b.maxX, imageExtent.w);
    const maxY = Math.max(b.maxY, imageExtent.h);
    const w = maxX - minX;
    const h = maxY - minY;
    const padding = Math.max(w, h) * 0.05;
    return { x: minX - padding, y: minY - padding, w: w + 2 * padding, h: h + 2 * padding };
  }
  // fallback: shape bounds only.
  if (!isFinite(b.minX)) return { x: 0, y: 0, w: 10, h: 10 };
  const w = b.maxX - b.minX || 1;
  const h = b.maxY - b.minY || 1;
  const padding = Math.max(w, h) * 0.05;
  return { x: b.minX - padding, y: b.minY - padding, w: w + 2 * padding, h: h + 2 * padding };
}

// draft.id 별 최초 viewBox 를 localStorage 에 캐싱 (이미지 extent 없을 때의 fallback).
// 새로고침 후에도 같은 draft 면 같은 viewBox 가 복원되어, 그룹 리사이즈로 도형이
// 줄어들었을 때 캔버스가 작아진 도형에 자동 맞춤되는 현상(라벨·핸들이 커보임)을 막는다.
// 이미지 extent (real_width_m + natural dims) 가 있는 경우엔 union viewBox 가 자연스럽게
// 안정적이므로 캐시 불필요.
const VIEWBOX_CACHE_PREFIX = 'draft-viewbox:v1:';

function loadCachedViewBox(draftId: string): ViewBox | null {
  try {
    const raw = localStorage.getItem(VIEWBOX_CACHE_PREFIX + draftId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ViewBox>;
    if (
      typeof parsed.x === 'number' &&
      typeof parsed.y === 'number' &&
      typeof parsed.w === 'number' &&
      typeof parsed.h === 'number' &&
      parsed.w > 0 &&
      parsed.h > 0
    ) {
      return parsed as ViewBox;
    }
  } catch {
    // localStorage 접근 실패 / JSON parse 실패: 캐시 무시.
  }
  return null;
}

function saveCachedViewBox(draftId: string, vb: ViewBox) {
  try {
    localStorage.setItem(VIEWBOX_CACHE_PREFIX + draftId, JSON.stringify(vb));
  } catch {
    // quota exceeded / private mode: 무시. 캐시 없이도 동작.
  }
}

function resolveInitialViewBox(draft: SceneDraft): ViewBox {
  const cached = loadCachedViewBox(draft.id);
  if (cached) return cached;
  const computed = computeViewBox(draft);
  saveCachedViewBox(draft.id, computed);
  return computed;
}

/**
 * 이미지를 비동기 로드해서 naturalWidth/Height 반환. URL 바뀌면 null 로 리셋.
 * presigned URL 의 만료/갱신 시에도 동작.
 */
function useImageNaturalDimensions(
  url: string | null | undefined,
): { w: number; h: number } | null {
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => {
    setDims(null);
    if (!url) return;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    let cancelled = false;
    img.onload = () => {
      if (!cancelled && img.naturalWidth > 0 && img.naturalHeight > 0) {
        setDims({ w: img.naturalWidth, h: img.naturalHeight });
      }
    };
    img.onerror = () => {
      if (!cancelled) setDims(null);
    };
    img.src = url;
    return () => {
      cancelled = true;
    };
  }, [url]);
  return dims;
}

// real_width_m 를 localStorage 에 캐싱.
// 분석 직후 draft 의 summary_json.storage.real_width_m 가 있을 때 저장 →
// 이후 promote 되어 SceneVersion 으로 바뀌면 (summary_json={}) 이 캐시에서 복원.
// → 확정 직후에도 imageExtent 가 살아있어 viewBox 가 안 흔들림.
//
// 저장은 source_asset_id / floor_id 둘 다 키로 → 백엔드가 둘 중 한쪽만 채워주는
// 응답이어도 lookup 성공. 같은 floor 에 여러 도면이 올라가는 경우는 실무상 없음.
const REAL_WIDTH_CACHE_PREFIX = 'asset-real-width-m:v1:';

function loadCachedRealWidth(key: string): number | null {
  try {
    const raw = localStorage.getItem(REAL_WIDTH_CACHE_PREFIX + key);
    if (!raw) return null;
    const v = Number(raw);
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

function saveCachedRealWidth(key: string, w: number): void {
  try {
    localStorage.setItem(REAL_WIDTH_CACHE_PREFIX + key, String(w));
  } catch {
    // 캐시 실패는 무시 — 기능적 영향 없음 (summary_json 있을 때만 안 흔들림).
  }
}

/**
 * draft 의 summary_json (있으면) 또는 캐시에서 real_width_m 조회. 순수함수.
 * 캐시 lookup 은 source_asset_id / floor_id 양쪽 키를 모두 시도 — 백엔드가 draft 와
 * version 에서 source_asset_id 를 다르게 (한쪽 null) 응답하는 경우에도 hit.
 */
function getRealWidthM(draft: SceneDraft): number | null {
  const summary = (draft.summary_json ?? {}) as {
    storage?: { real_width_m?: number };
  };
  const fromSummary = summary.storage?.real_width_m;
  if (typeof fromSummary === 'number' && fromSummary > 0) return fromSummary;
  if (draft.source_asset_id) {
    const v = loadCachedRealWidth(draft.source_asset_id);
    if (v != null) return v;
  }
  if (draft.floor_id) {
    const v = loadCachedRealWidth(draft.floor_id);
    if (v != null) return v;
  }
  return null;
}

/**
 * summary_json 의 scale_ratio_m_per_px 조회. geom 변환에 쓴 최종 scale (m/px).
 * 벽 좌표가 `pixel × scale_ratio` 로 미터화됐으므로, 같은 scale 로 이미지를 놓으면
 * 벽과 정확히 정렬됨. OCR 추정/기본 fallback 무관하게 백엔드가 항상 기록.
 */
function getScaleRatioMPerPx(draft: SceneDraft): number | null {
  const summary = (draft.summary_json ?? {}) as {
    scale_ratio_m_per_px?: number;
  };
  const v = summary.scale_ratio_m_per_px;
  if (typeof v === 'number' && v > 0) return v;
  return null;
}

/**
 * 이미지의 실제 미터 크기 계산. 두 가지 소스:
 *   1. scale_ratio_m_per_px (신규, 권장): imageDims_px × scale → 벽과 동일 좌표계 정렬.
 *   2. real_width_m (legacy): 사용자가 입력하던 도면 가로폭. 옛 draft 호환용.
 * 둘 다 없으면 null → fallback 으로 도형 bounds 기준 viewBox 사용.
 */
function deriveImageExtent(
  draft: SceneDraft,
  imageDims: { w: number; h: number } | null,
): { w: number; h: number } | null {
  if (!imageDims || imageDims.w <= 0) return null;

  // 1순위: scale_ratio (이미지 픽셀 × m/px = 미터 크기). 벽과 정확히 겹침.
  const scaleRatio = getScaleRatioMPerPx(draft);
  if (scaleRatio != null) {
    return {
      w: imageDims.w * scaleRatio,
      h: imageDims.h * scaleRatio,
    };
  }

  // 2순위 (legacy): real_width_m. 옛 draft / version-as-draft 캐시 호환.
  const realWidthM = getRealWidthM(draft);
  if (realWidthM != null) {
    return {
      w: realWidthM,
      h: realWidthM * (imageDims.h / imageDims.w),
    };
  }
  return null;
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
    }
  | {
      mode: 'resize';
      ref: SelectedEntityRef;
      cornerSign: [-1 | 1, -1 | 1];
      startSvg: Coord;
      delta: Coord;
    }
  | {
      // 빈 캔버스에서 사각형 드래그 → 영역 내부 도형 일괄 선택.
      mode: 'marquee';
      startSvg: Coord;
      currentSvg: Coord;
      additive: boolean;
    }
  | {
      // 다중 선택 bbox 의 모서리 드래그 → 모든 선택 도형을 같은 비율로 스케일.
      // fixed=고정 모서리(반대편), startCorner=드래그 시작 좌표, currentCorner=현재 커서.
      mode: 'group-resize';
      fixed: Coord;
      startCorner: Coord;
      currentCorner: Coord;
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
// 스냅 타겟은 "벽" 으로 한정한다. 창문/문(opening) 끝점에는 안 붙도록 —
// 벽을 이으려는데 자꾸 가까운 창문에 붙는 문제 방지. 벽은 끝점뿐 아니라
// 선분 위 어디든 붙는다 (벽 중간에 다른 벽/개구부를 잇는 경우).

/** draft 의 모든 벽 끝점을 스냅 anchor 로 수집. exclude 한 벽은 제외. */
function collectWallAnchors(
  draft: SceneDraft,
  excludeWallId?: string | null,
): Coord[] {
  const anchors: Coord[] = [];
  for (const wall of draft.walls) {
    if (excludeWallId && wall.id === excludeWallId) continue;
    const g = parseGeometry(wall.centerline_geom);
    if (g?.type === 'LineString') for (const c of g.coordinates) anchors.push(c);
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
function snapToAxis(from: Coord, to: Coord, tol: number): Coord {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  if (Math.abs(dy) < tol && Math.abs(dx) >= Math.abs(dy)) return [to[0], from[1]];
  if (Math.abs(dx) < tol && Math.abs(dy) > Math.abs(dx)) return [from[0], to[1]];
  return to;
}

type SnapKind = 'wall-anchor' | 'wall-projection' | 'axis';

interface SnapResult {
  point: Coord;
  snapped: boolean;
  kind?: SnapKind;
}

/**
 * 벽 우선 스냅: 벽 끝점(1순위) → 벽 선분 위 투영(2순위) → 축 스냅(3순위).
 * opening(창문/문) 에는 절대 안 붙는다.
 */
function snapToWall(
  raw: Coord,
  draft: SceneDraft,
  wallAnchors: Coord[],
  axisFrom?: Coord | null,
  excludeWallId?: string | null,
): SnapResult {
  // 1) 벽 끝점
  const anchor = nearestAnchor(raw, wallAnchors, SNAP_RADIUS_M);
  if (anchor) return { point: [anchor[0], anchor[1]], snapped: true, kind: 'wall-anchor' };
  // 2) 벽 선분 위 (끝점이 아니어도 벽 라인에 붙음)
  const proj = nearestWallProjection(raw, draft, SNAP_RADIUS_M, excludeWallId);
  if (proj) return { point: proj, snapped: true, kind: 'wall-projection' };
  // 3) 축 스냅 (그리는 중 / vertex 드래그 시 반대편 꼭짓점 기준)
  if (axisFrom) {
    const axed = snapToAxis(axisFrom, raw, AXIS_SNAP_TOLERANCE_M);
    if (axed[0] !== raw[0] || axed[1] !== raw[1]) return { point: axed, snapped: true, kind: 'axis' };
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
  // object — 스냅 비활성화. 객체 중심점을 벽 끝점에 붙이면 박스가 건물 밖으로 나가는
  // 부작용이 있어, 객체는 자유 배치가 자연스럽다.
  return [];
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

/** pt 에서 radius 이내, 가장 가까운 wall 선분 위의 점. excludeWallId 는 제외. */
function nearestWallProjection(
  pt: Coord,
  draft: SceneDraft,
  radius: number,
  excludeWallId?: string | null,
): Coord | null {
  let best: Coord | null = null;
  let bestD = radius;
  for (const wall of draft.walls) {
    if (excludeWallId && wall.id === excludeWallId) continue;
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
 * 모든 기준점에 대해 벽 끝점(1순위) / 벽 선분 위(2순위) 스냅을 시도.
 * opening 끝점에는 안 붙는다 — 벽에만.
 */
function computeShapeSnapDelta(
  draft: SceneDraft,
  ref: SelectedEntityRef,
  rawDelta: Coord,
  wallAnchors: Coord[],
): { delta: Coord; snapPoint: Coord | null } {
  const pts = getEntityRefPoints(draft, ref);
  const excludeWallId = ref.kind === 'wall' ? ref.id : null;
  let best: { from: Coord; to: Coord } | null = null;
  let bestD = SNAP_RADIUS_M;

  for (const pt of pts) {
    const moved: Coord = [pt[0] + rawDelta[0], pt[1] + rawDelta[1]];
    // 1순위: 벽 끝점
    const anchor = nearestAnchor(moved, wallAnchors, SNAP_RADIUS_M);
    if (anchor) {
      const d = Math.hypot(anchor[0] - moved[0], anchor[1] - moved[1]);
      if (d < bestD) {
        bestD = d;
        best = { from: pt, to: [anchor[0], anchor[1]] };
      }
      continue;
    }
    // 2순위: 벽 선분 위 투영 (객체/개구부를 벽에 딱 붙이기)
    const proj = nearestWallProjection(moved, draft, SNAP_RADIUS_M, excludeWallId);
    if (proj) {
      const d = Math.hypot(proj[0] - moved[0], proj[1] - moved[1]);
      if (d < bestD) {
        bestD = d;
        best = { from: pt, to: proj };
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

/** 두 코너 좌표로 (x,y,w,h) 사각형 정규화. w,h 는 항상 ≥ 0. */
function normalizeRect(
  a: Coord,
  b: Coord,
): { x: number; y: number; w: number; h: number } {
  const x = Math.min(a[0], b[0]);
  const y = Math.min(a[1], b[1]);
  const w = Math.abs(a[0] - b[0]);
  const h = Math.abs(a[1] - b[1]);
  return { x, y, w, h };
}

/** 점이 사각형 안인지. */
function pointInRect(
  pt: Coord,
  rect: { x: number; y: number; w: number; h: number },
): boolean {
  return (
    pt[0] >= rect.x &&
    pt[0] <= rect.x + rect.w &&
    pt[1] >= rect.y &&
    pt[1] <= rect.y + rect.h
  );
}

/**
 * 마퀴 영역 안에 들어간 도형 ref 들 수집.
 * - wall/opening (LineString) → 양 끝점 모두 영역 안일 때
 * - room (Polygon) → 외곽링 모든 점이 영역 안일 때
 * - object (Point) → 박스 4 모서리가 영역 안일 때 (박스가 통째로 들어와야 선택됨)
 */
function collectEntitiesInRect(
  draft: SceneDraft,
  rect: { x: number; y: number; w: number; h: number },
): SelectedEntityRef[] {
  const hits: SelectedEntityRef[] = [];
  for (const wall of draft.walls) {
    const g = parseGeometry(wall.centerline_geom);
    if (g?.type !== 'LineString') continue;
    if (g.coordinates.every((p) => pointInRect(p, rect))) {
      hits.push({ kind: 'wall', id: wall.id });
    }
  }
  for (const op of draft.openings) {
    const g = parseGeometry(op.line_geom);
    if (g?.type !== 'LineString') continue;
    if (g.coordinates.every((p) => pointInRect(p, rect))) {
      hits.push({ kind: 'opening', id: op.id });
    }
  }
  for (const room of draft.rooms) {
    const g = parseGeometry(room.polygon_geom);
    if (g?.type !== 'Polygon') continue;
    const outer = g.coordinates[0] ?? [];
    if (outer.length > 0 && outer.every((p) => pointInRect(p, rect))) {
      hits.push({ kind: 'room', id: room.id });
    }
  }
  for (const obj of draft.objects) {
    const g = parseGeometry(obj.point_geom);
    if (g?.type !== 'Point') continue;
    const [cx, cy] = g.coordinates;
    const meta = (obj.metadata_json ?? {}) as Record<string, unknown>;
    const w =
      typeof meta.width_m === 'number' && meta.width_m > 0 ? meta.width_m : 1.6;
    const h =
      typeof meta.height_m === 'number' && meta.height_m > 0 ? meta.height_m : 1.6;
    const corners: Coord[] = [
      [cx - w / 2, cy - h / 2],
      [cx + w / 2, cy - h / 2],
      [cx - w / 2, cy + h / 2],
      [cx + w / 2, cy + h / 2],
    ];
    if (corners.every((p) => pointInRect(p, rect))) {
      hits.push({ kind: 'object', id: obj.id });
    }
  }
  return hits;
}

/** group-resize 드래그에서 sx, sy 추출. 0 으로 나눠지면 1 유지(축에 평행한 corner 일 때). */
function groupResizeScale(
  drag: Extract<DragState, { mode: 'group-resize' }>,
): { sx: number; sy: number } {
  const dx0 = drag.startCorner[0] - drag.fixed[0];
  const dy0 = drag.startCorner[1] - drag.fixed[1];
  const dx1 = drag.currentCorner[0] - drag.fixed[0];
  const dy1 = drag.currentCorner[1] - drag.fixed[1];
  const sx = Math.abs(dx0) > 1e-6 ? dx1 / dx0 : 1;
  const sy = Math.abs(dy0) > 1e-6 ? dy1 / dy0 : 1;
  // 최소 스케일 — 너무 작아지면 선택군이 점으로 수렴해버리므로 floor.
  const MIN = 0.05;
  return {
    sx: Math.abs(sx) < MIN ? Math.sign(sx) * MIN || MIN : sx,
    sy: Math.abs(sy) < MIN ? Math.sign(sy) * MIN || MIN : sy,
  };
}

/** 고정점(fix) 기준으로 (x, y) 를 (sx, sy) 만큼 스케일. */
function scaleAround(pt: Coord, fix: Coord, sx: number, sy: number): Coord {
  return [fix[0] + (pt[0] - fix[0]) * sx, fix[1] + (pt[1] - fix[1]) * sy];
}

/** 선택된 도형들의 AABB(미니멈 경계상자). 없으면 null. */
function computeSelectionBounds(
  draft: SceneDraft,
  refs: SelectedEntityRef[],
): { x: number; y: number; w: number; h: number } | null {
  const b = emptyBounds();
  let any = false;
  for (const ref of refs) {
    if (ref.kind === 'wall') {
      const g = parseGeometry(draft.walls.find((w) => w.id === ref.id)?.centerline_geom);
      if (g?.type === 'LineString')
        for (const [x, y] of g.coordinates) {
          extendBounds(b, x, y);
          any = true;
        }
    } else if (ref.kind === 'opening') {
      const g = parseGeometry(draft.openings.find((o) => o.id === ref.id)?.line_geom);
      if (g?.type === 'LineString')
        for (const [x, y] of g.coordinates) {
          extendBounds(b, x, y);
          any = true;
        }
    } else if (ref.kind === 'room') {
      const g = parseGeometry(draft.rooms.find((r) => r.id === ref.id)?.polygon_geom);
      if (g?.type === 'Polygon')
        for (const ring of g.coordinates)
          for (const [x, y] of ring) {
            extendBounds(b, x, y);
            any = true;
          }
    } else {
      const obj = draft.objects.find((o) => o.id === ref.id);
      const g = parseGeometry(obj?.point_geom);
      if (g?.type !== 'Point') continue;
      const [cx, cy] = g.coordinates;
      const meta = (obj?.metadata_json ?? {}) as Record<string, unknown>;
      const w =
        typeof meta.width_m === 'number' && meta.width_m > 0 ? meta.width_m : 1.6;
      const h =
        typeof meta.height_m === 'number' && meta.height_m > 0 ? meta.height_m : 1.6;
      extendBounds(b, cx - w / 2, cy - h / 2);
      extendBounds(b, cx + w / 2, cy + h / 2);
      any = true;
    }
  }
  if (!any || !isFinite(b.minX)) return null;
  return { x: b.minX, y: b.minY, w: b.maxX - b.minX, h: b.maxY - b.minY };
}

function polygonCentroid(points: Coord[]): Coord {
  if (points.length === 0) return [0, 0];
  const n = points.length;
  const sx = points.reduce((s, p) => s + p[0], 0);
  const sy = points.reduce((s, p) => s + p[1], 0);
  return [sx / n, sy / n];
}

/** 다각형 점들의 AABB(축정렬 경계상자) 가로/세로 길이. 라벨 크기 계산용. */
function polygonBounds(points: Coord[]): { w: number; h: number } {
  if (points.length === 0) return { w: 0, h: 0 };
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of points) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { w: Math.max(0, maxX - minX), h: Math.max(0, maxY - minY) };
}

interface Props {
  draft: SceneDraft;
  /** 선택된 도형들. 단일 선택이면 길이 1, 다중 선택이면 N. */
  selectedRefs?: SelectedEntityRef[];
  /**
   * 도형 선택 콜백.
   * - additive=true (Shift+클릭): 기존 선택에 추가/토글
   * - additive=false (일반 클릭): 단일 선택으로 교체
   * - ref=null: 전체 해제
   */
  onSelect?: (ref: SelectedEntityRef | null, options?: { additive?: boolean }) => void;
  /** Marquee 드래그 종료 시 영역 내부 도형들을 한꺼번에 선택. additive=true 면 기존 선택에 합집합. */
  onSelectMany?: (refs: SelectedEntityRef[], options?: { additive?: boolean }) => void;
  /**
   * 다중 선택 bbox 모서리 드래그 종료 시, 고정점과 스케일을 알려줌.
   * 호출 측이 각 선택 도형 좌표/메타데이터를 변환해서 PATCH 한다.
   */
  onGroupResizeEnd?: (params: {
    fixed: Coord;
    sx: number;
    sy: number;
    refs: SelectedEntityRef[];
  }) => void;
  /** 드래그 종료 시 새 geometry. 호출 측이 적절한 *_geom 필드로 PATCH 한다. */
  onDragEnd?: (ref: SelectedEntityRef, geometry: GeoJsonGeometry) => void;
  /** 공간성 객체 박스 리사이즈 종료. metadata_json 의 width_m/height_m 업데이트용. */
  onResizeObject?: (ref: SelectedEntityRef, widthM: number, heightM: number) => void;
  /** 현재 도구 (좌측 도구바). 'select' 이외 모드면 그리기 흐름으로 전환. */
  tool?: EditorTool;
  /** 새 도형 생성. body 는 *_geom + 필수 메타 포함. */
  onCreate?: (kind: DraftEntityKind, body: Record<string, unknown>) => void;
  /** 원본 도면 이미지 URL — 벡터 도형 뒤에 연하게 깔아 비교용. */
  backgroundImageUrl?: string | null;
}

export function DraftSceneCanvas({
  draft,
  selectedRefs,
  onSelect,
  onSelectMany,
  onGroupResizeEnd,
  onDragEnd,
  onResizeObject,
  tool = 'select',
  onCreate,
  backgroundImageUrl,
}: Props) {
  // 배경 도면 이미지의 natural 픽셀 dim → real_width_m 와 조합해 실제 미터 크기 산출.
  // 이미지 extent 가 있으면 viewBox 는 (이미지 + 도형) 합집합 → 도형을 줄여도 캔버스가
  // 이미지 크기는 유지 → "도면 위에 그렸을 때 그림+도면 크기 저장 + 화면에 안 늘어남".
  // 이미지가 없거나 real_width_m 가 없으면 fallback 으로 캐시된 도형 bounds viewBox.
  const imageDims = useImageNaturalDimensions(backgroundImageUrl ?? null);
  // 부수효과: draft 의 summary_json 에 real_width_m 이 있으면 캐시에 저장.
  // 이후 promote → version-as-draft (summary_json={}) 가 되면 이 캐시로 복원 → viewBox 안정.
  // source_asset_id 와 floor_id 두 키 모두로 저장 — 백엔드 응답이 둘 중 하나만
  // 채워주는 케이스(promote 전후로 source_asset_id 가 한쪽만 null 등) 에서도 lookup 성공.
  useEffect(() => {
    const summary = (draft.summary_json ?? {}) as {
      storage?: { real_width_m?: number };
    };
    const v = summary.storage?.real_width_m;
    if (typeof v !== 'number' || v <= 0) return;
    if (draft.source_asset_id) saveCachedRealWidth(draft.source_asset_id, v);
    if (draft.floor_id) saveCachedRealWidth(draft.floor_id, v);
  }, [draft]);
  const imageExtent = useMemo(
    () => deriveImageExtent(draft, imageDims),
    [draft, imageDims],
  );

  const [vb, setVb] = useState(() =>
    imageExtent ? computeViewBox(draft, imageExtent) : resolveInitialViewBox(draft),
  );
  // viewBox 리셋은 floor 가 바뀔 때만. draft.id 가 바뀌어도 (promote → version-as-draft)
  // 같은 floor 면 viewBox 유지 → 확정 전후로 객체 크기 일정.
  const [prevFloorId, setPrevFloorId] = useState(draft.floor_id);
  const [prevExtent, setPrevExtent] = useState(imageExtent);
  if (prevFloorId !== draft.floor_id) {
    setPrevFloorId(draft.floor_id);
    setPrevExtent(imageExtent);
    setVb(imageExtent ? computeViewBox(draft, imageExtent) : resolveInitialViewBox(draft));
  } else if (prevExtent !== imageExtent) {
    // 이미지 로드 완료 시 viewBox 를 union 으로 한 번 업데이트.
    setPrevExtent(imageExtent);
    if (imageExtent) setVb(computeViewBox(draft, imageExtent));
  }

  // 핸들 크기는 현재 도형의 자연 크기에 비례 — viewBox 가 고정돼도 사용자가 그룹
  // 리사이즈로 도형을 작게 만들면 핸들도 같이 작아짐.
  const naturalSize = useMemo(() => {
    const nb = computeViewBox(draft);
    return Math.max(nb.w, nb.h);
  }, [draft]);
  const handleSize = Math.max(0.03, Math.min(0.08, naturalSize * 0.006));

  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [creating, setCreating] = useState<CreatingState>(null);
  const [cursorPos, setCursorPos] = useState<Coord | null>(null);
  // 스냅 발생 시 표시할 위치 (초록 링). 스냅 안 되면 null.
  const [snapIndicator, setSnapIndicator] = useState<Coord | null>(null);
  // 벽/문창 vertex 가 반대편 꼭짓점 기준 0°/90° 에 스냅된 순간의 가이드 정보.
  // from = 고정된 반대편 꼭짓점, to = 스냅된 현재 꼭짓점, axis = 'h'(수평선)|'v'(수직선).
  const [axisSnap, setAxisSnapState] = useState<{
    axis: 'h' | 'v';
    from: Coord;
    to: Coord;
  } | null>(null);

  // 단일 선택일 때의 primary ref. vertex/resize 핸들·라벨은 단일 선택 시에만 의미.
  const selectedRef: SelectedEntityRef | null =
    selectedRefs && selectedRefs.length === 1 ? selectedRefs[0] : null;

  // 스냅 anchor = 벽 끝점만. 드래그/선택 중인 벽은 자기 자신에 안 붙도록 제외.
  const wallAnchors = useMemo(
    () =>
      collectWallAnchors(
        draft,
        selectedRef?.kind === 'wall' ? selectedRef.id : null,
      ),
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
    // Shift+클릭: 추가 선택. 그 외엔 단일 선택으로 교체.
    // 이미 선택된 도형을 드래그 시작할 땐 선택 유지 (다중 선택 드래그 자연스럽게).
    const alreadySelected = !!selectedRefs?.some(
      (r) => r.kind === ref.kind && r.id === ref.id,
    );
    if (e.shiftKey) {
      onSelect?.(ref, { additive: true });
    } else if (!alreadySelected) {
      onSelect?.(ref);
    }
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

  const startResizeDrag = (
    e: React.PointerEvent,
    ref: SelectedEntityRef,
    cornerSign: [-1 | 1, -1 | 1],
  ) => {
    if (tool !== 'select') return;
    e.stopPropagation();
    const pt = getSvgPoint(e);
    if (!pt) return;
    svgRef.current?.setPointerCapture(e.pointerId);
    setDrag({ mode: 'resize', ref, cornerSign, startSvg: pt, delta: [0, 0] });
    onSelect?.(ref);
  };

  const startGroupResizeDrag = (
    e: React.PointerEvent,
    fixedCorner: Coord,
    startCorner: Coord,
  ) => {
    if (tool !== 'select') return;
    e.stopPropagation();
    svgRef.current?.setPointerCapture(e.pointerId);
    setDrag({
      mode: 'group-resize',
      fixed: fixedCorner,
      startCorner,
      currentCorner: startCorner,
    });
  };

  const handleSvgPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const raw = getSvgPoint(e);
    if (!raw) return;

    // ─ 생성 모드: cursor 를 벽에 스냅해서 preview 가 딱 붙도록 ─
    if (isCreationMode) {
      // 벽/문창 그리는 중이면 첫 점 기준 수평/수직 스냅도 적용
      const axisFrom =
        creating && (creating.kind === 'wall' || creating.kind === 'opening')
          ? creating.firstPoint
          : null;
      const res = snapToWall(raw, draft, wallAnchors, axisFrom);
      setCursorPos(res.point);
      setSnapIndicator(res.snapped ? res.point : null);
    }

    if (!drag) {
      if (!isCreationMode) setSnapIndicator(null);
      return;
    }

    // ─ marquee 드래그: 사각형만 갱신, 실 선택은 pointerUp 에서. ─
    if (drag.mode === 'marquee') {
      setDrag((prev) => (prev && prev.mode === 'marquee' ? { ...prev, currentSvg: raw } : prev));
      return;
    }

    // ─ group-resize: 현재 모서리 위치만 갱신. 미리보기는 effective* 가 처리. ─
    if (drag.mode === 'group-resize') {
      setDrag((prev) =>
        prev && prev.mode === 'group-resize' ? { ...prev, currentCorner: raw } : prev,
      );
      return;
    }

    // ─ vertex 드래그: 목표 꼭짓점을 벽에 스냅 → snapped delta 로 반영 ─
    if (drag.mode === 'vertex') {
      const orig = getEntityVertex(draft, drag.ref, drag.vertexIndex);
      if (orig) {
        const rawTarget: Coord = [
          orig[0] + (raw[0] - drag.startSvg[0]),
          orig[1] + (raw[1] - drag.startSvg[1]),
        ];
        const excludeWallId = drag.ref.kind === 'wall' ? drag.ref.id : null;
        // 벽/문창은 2-점 LineString — 반대편 꼭짓점을 axis 기준점으로 넘겨서
        // 드래그 결과가 수평/수직에 가까우면 정확히 90° 로 스냅. (방=폴리곤은 제외)
        let axisFrom: Coord | null = null;
        if (drag.ref.kind === 'wall' || drag.ref.kind === 'opening') {
          const otherIdx = drag.vertexIndex === 0 ? 1 : 0;
          axisFrom = getEntityVertex(draft, drag.ref, otherIdx);
        }
        const res = snapToWall(rawTarget, draft, wallAnchors, axisFrom, excludeWallId);
        // axis 스냅은 별도 가이드(점선+90°뱃지)로 표시 — 일반 초록 링은 숨김.
        setSnapIndicator(res.snapped && res.kind !== 'axis' ? res.point : null);
        if (res.kind === 'axis' && axisFrom) {
          // axisFrom 과 같은 x → 수직, 같은 y → 수평
          const axis: 'h' | 'v' = res.point[0] === axisFrom[0] ? 'v' : 'h';
          setAxisSnapState({ axis, from: axisFrom, to: res.point });
        } else {
          setAxisSnapState(null);
        }
        setDrag((prev) =>
          prev
            ? { ...prev, delta: [res.point[0] - orig[0], res.point[1] - orig[1]] }
            : null,
        );
        return;
      }
    }

    // ─ shape 드래그: 엔티티 통째 이동 — 기준점을 벽 끝점/선분에 스냅 ─
    {
      const rawDelta: Coord = [raw[0] - drag.startSvg[0], raw[1] - drag.startSvg[1]];
      // 다중 선택 그룹 이동(드래그된 도형이 선택군에 속함)이면 스냅 비활성화 — 모든
      // 선택 도형이 같이 움직여야 하는데 한 도형 기준 스냅이 걸리면 어색하고 시각적으로
      // 초록 인디케이터가 거슬림.
      const isGroupDrag =
        (selectedRefs?.length ?? 0) > 1 &&
        !!selectedRefs?.some(
          (r) => r.kind === drag.ref.kind && r.id === drag.ref.id,
        );
      const { delta: snappedDelta, snapPoint } = isGroupDrag
        ? { delta: rawDelta, snapPoint: null }
        : computeShapeSnapDelta(draft, drag.ref, rawDelta, wallAnchors);
      // 객체(Point) 는 캔버스 viewBox 밖으로 못 나가도록 박스 모서리 기준 clamp.
      // 벽/방/문창 등은 사용자가 의도적으로 외곽으로 끌 수 있어 clamp 안 함.
      const delta = clampObjectDelta(snappedDelta, drag.ref, draft, vb);
      setSnapIndicator(snapPoint);
      setDrag((prev) => (prev ? { ...prev, delta } : null));
    }
  };

  /** 객체가 viewBox 안에 머무르도록 delta clamp. 객체가 아니면 그대로 통과. */
  function clampObjectDelta(
    delta: Coord,
    ref: SelectedEntityRef,
    scene: SceneDraft,
    vbox: { x: number; y: number; w: number; h: number },
  ): Coord {
    if (ref.kind !== 'object') return delta;
    const obj = scene.objects.find((o) => o.id === ref.id);
    const g = parseGeometry(obj?.point_geom);
    if (g?.type !== 'Point') return delta;
    const meta = (obj?.metadata_json ?? {}) as Record<string, unknown>;
    const w = typeof meta.width_m === 'number' && meta.width_m > 0 ? meta.width_m : 1.6;
    const h = typeof meta.height_m === 'number' && meta.height_m > 0 ? meta.height_m : 1.6;
    const [cx, cy] = g.coordinates;
    // 박스 중심이 들어갈 수 있는 범위: viewBox 안에 박스 전체가 들어가도록.
    const minCx = vbox.x + w / 2;
    const maxCx = vbox.x + vbox.w - w / 2;
    const minCy = vbox.y + h / 2;
    const maxCy = vbox.y + vbox.h - h / 2;
    const clampedX = Math.max(minCx, Math.min(maxCx, cx + delta[0]));
    const clampedY = Math.max(minCy, Math.min(maxCy, cy + delta[1]));
    return [clampedX - cx, clampedY - cy];
  }

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
    setAxisSnapState(null);

    // marquee: 박스 크기가 임계 이상이면 영역 안 도형 일괄 선택; 미만이면 단순 클릭으로 보고 선택 해제.
    if (captured.mode === 'marquee') {
      const rect = normalizeRect(captured.startSvg, captured.currentSvg);
      const tiny =
        rect.w < DRAG_THRESHOLD_M && rect.h < DRAG_THRESHOLD_M;
      if (tiny) {
        if (!captured.additive) onSelect?.(null);
        return;
      }
      const hits = collectEntitiesInRect(draft, rect);
      onSelectMany?.(hits, { additive: captured.additive });
      return;
    }

    // group-resize: scale 이 의미 있는 경우 한해 상위로 전달.
    if (captured.mode === 'group-resize') {
      const { sx, sy } = groupResizeScale(captured);
      const meaningful = Math.abs(sx - 1) > 0.01 || Math.abs(sy - 1) > 0.01;
      if (meaningful && selectedRefs && selectedRefs.length >= 2) {
        onGroupResizeEnd?.({
          fixed: captured.fixed,
          sx,
          sy,
          refs: selectedRefs,
        });
      }
      return;
    }

    const [dx, dy] = captured.delta;
    if (Math.abs(dx) < DRAG_THRESHOLD_M && Math.abs(dy) < DRAG_THRESHOLD_M) return;

    if (captured.mode === 'resize') {
      // 객체의 현재 크기 + delta 로 새 사이즈 계산 (대칭, 최소 0.2m).
      const obj = draft.objects.find((o) => o.id === captured.ref.id);
      if (!obj || captured.ref.kind !== 'object') return;
      const cur = readObjectSize(obj);
      const newW = Math.max(0.2, cur.width + captured.delta[0] * captured.cornerSign[0] * 2);
      const newH = Math.max(0.2, cur.height + captured.delta[1] * captured.cornerSign[1] * 2);
      onResizeObject?.(captured.ref, newW, newH);
      return;
    }

    const newGeom = buildDraggedGeometry(captured, draft);
    if (newGeom) onDragEnd?.(captured.ref, newGeom);
  };

  const handleSvgPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    // ─ 벽 (2 클릭 LineString) ─
    if (tool === 'rect') {
      const raw = getSvgPoint(e);
      if (!raw) return;
      if (!creating || creating.kind !== 'wall') {
        // 첫 점도 기존 벽에 스냅 (벽 잇기 시작점 정확히)
        const start = snapToWall(raw, draft, wallAnchors).point;
        setCreating({ kind: 'wall', firstPoint: start });
      } else {
        const start = creating.firstPoint;
        const pt = snapToWall(raw, draft, wallAnchors, start).point;
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
        const start = snapToWall(raw, draft, wallAnchors).point;
        setCreating({ kind: 'opening', firstPoint: start });
      } else {
        const start = creating.firstPoint;
        const pt = snapToWall(raw, draft, wallAnchors, start).point;
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
    // [room 비활성화] AP 후보 알고리즘이 room 정보를 강제로 쓰지 않기로 결정 → UI 노출 제거.
    // 데이터 모델·API 는 유지하므로 도구만 막음. 다시 켜려면 아래 블록 주석 해제.
    // if (tool === 'polygon') {
    //   const pt = getSvgPoint(e);
    //   if (!pt) return;
    //   if (!creating || creating.kind !== 'polygon') {
    //     setCreating({ kind: 'polygon', points: [pt] });
    //     return;
    //   }
    //   const pts = creating.points;
    //   // 3 점 이상일 때 시작점 근처 클릭 → 닫기
    //   if (pts.length >= 3 && distance(pt, pts[0]) < POLYGON_CLOSE_THRESHOLD_M) {
    //     const ring = [...pts, pts[0]];
    //     const centroid = polygonCentroid(pts);
    //     onCreate?.('room', {
    //       room_type: 'general',
    //       source_method: 'user_drawn',
    //       polygon_geom: { type: 'Polygon', coordinates: [ring] },
    //       centroid_geom: { type: 'Point', coordinates: centroid },
    //     });
    //     setCreating(null);
    //     return;
    //   }
    //   // 그 외 → 점 추가
    //   setCreating({ kind: 'polygon', points: [...pts, pt] });
    //   return;
    // }

    // select 모드: 빈 영역 → marquee 드래그 시작 (작은 움직임이면 pointerUp 에서 선택 해제로 처리).
    if (e.target === e.currentTarget) {
      const pt = getSvgPoint(e);
      if (!pt) return;
      svgRef.current?.setPointerCapture(e.pointerId);
      setDrag({ mode: 'marquee', startSvg: pt, currentSvg: pt, additive: e.shiftKey });
    }
  };

  const isSelected = (kind: SelectedEntityRef['kind'], id: string) =>
    !!selectedRefs?.some((r) => r.kind === kind && r.id === id);

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
        {backgroundImageUrl && (
          <image
            href={backgroundImageUrl}
            xlinkHref={backgroundImageUrl}
            // imageExtent 가 있으면 실제 미터 좌표 (0,0)~(extent.w, extent.h) 에 배치 →
            // 도형과 동일 좌표계 → 정렬 일치. 없으면 vb 영역에 fitting (fallback).
            x={imageExtent ? 0 : vb.x}
            y={imageExtent ? 0 : vb.y}
            width={imageExtent ? imageExtent.w : vb.w}
            height={imageExtent ? imageExtent.h : vb.h}
            opacity={0.25}
            preserveAspectRatio={imageExtent ? 'none' : 'xMidYMid meet'}
            pointerEvents="none"
            crossOrigin="anonymous"
            onError={() => {
              // 이미지 로드 실패: CORS / private S3 / 잘못된 URL 가능성.
              console.warn('[Canvas] 배경 도면 이미지 로드 실패:', backgroundImageUrl);
            }}
          />
        )}
        {/* 일반 렌더: 선택된 항목은 제외하고 그린 뒤, 마지막에 다시 위에 올림. */}
        {/* 타입 있는 방(화장실 등)만 표시 — 벽으로 둘러싸인 영역 + 라벨. 표시 전용
            (이름 없는 일반 방 room_0/1/2 는 잡동사니라 숨김). */}
        {draft.rooms
          .filter((r) => r.room_type)
          .map((room) => (
            <RoomShape
              key={room.id}
              room={room}
              selected={false}
              drag={matchDrag(drag, 'room', room.id)}
              handleSize={handleSize}
              onShapePointerDown={() => {}}
              onVertexPointerDown={() => {}}
            />
          ))}

        {draft.walls
          .filter((w) => !isSelected('wall', w.id))
          .map((wall) => (
            <WallShape
              key={wall.id}
              wall={wall}
              selected={false}
              drag={matchDrag(drag, 'wall', wall.id)}
              handleSize={handleSize}
              onShapePointerDown={(e) => startShapeDrag(e, { kind: 'wall', id: wall.id })}
              onVertexPointerDown={(e, idx) =>
                startVertexDrag(e, { kind: 'wall', id: wall.id }, idx)
              }
            />
          ))}

        {draft.openings
          .filter((o) => !isSelected('opening', o.id))
          .map((op) => (
            <OpeningShape
              key={op.id}
              opening={op}
              selected={false}
              drag={matchDrag(drag, 'opening', op.id)}
              handleSize={handleSize}
              onShapePointerDown={(e) => startShapeDrag(e, { kind: 'opening', id: op.id })}
              onVertexPointerDown={(e, idx) =>
                startVertexDrag(e, { kind: 'opening', id: op.id }, idx)
              }
            />
          ))}

        {draft.objects
          .filter((o) => !isSelected('object', o.id))
          .map((obj) => (
            <ObjectShape
              key={obj.id}
              object={obj}
              selected={false}
              drag={matchDrag(drag, 'object', obj.id)}
              handleSize={handleSize}
              onShapePointerDown={(e) => startShapeDrag(e, { kind: 'object', id: obj.id })}
              onResizePointerDown={(e, sign) =>
                startResizeDrag(e, { kind: 'object', id: obj.id }, sign)
              }
            />
          ))}

        {/* 선택된 항목들 — 항상 맨 위에 렌더 (단일/다중 모두). */}
        {(selectedRefs ?? []).map((ref) => {
          // [room 비활성화] 선택된 room 도 렌더 스킵.
          // if (ref.kind === 'room') {
          //   const room = draft.rooms.find((r) => r.id === ref.id);
          //   return room ? (
          //     <RoomShape
          //       key={`sel-${room.id}`}
          //       room={room}
          //       selected
          //       drag={groupDrag(drag, selectedRefs, 'room', room.id)}
          //       handleSize={handleSize}
          //       onShapePointerDown={(e) => startShapeDrag(e, { kind: 'room', id: room.id })}
          //       onVertexPointerDown={(e, idx) =>
          //         startVertexDrag(e, { kind: 'room', id: room.id }, idx)
          //       }
          //     />
          //   ) : null;
          // }
          if (ref.kind === 'room') return null;
          if (ref.kind === 'wall') {
            const wall = draft.walls.find((w) => w.id === ref.id);
            return wall ? (
              <WallShape
                key={`sel-${wall.id}`}
                wall={wall}
                selected
                drag={groupDrag(drag, selectedRefs, 'wall', wall.id)}
                handleSize={handleSize}
                onShapePointerDown={(e) => startShapeDrag(e, { kind: 'wall', id: wall.id })}
                onVertexPointerDown={(e, idx) =>
                  startVertexDrag(e, { kind: 'wall', id: wall.id }, idx)
                }
              />
            ) : null;
          }
          if (ref.kind === 'opening') {
            const op = draft.openings.find((o) => o.id === ref.id);
            return op ? (
              <OpeningShape
                key={`sel-${op.id}`}
                opening={op}
                selected
                drag={groupDrag(drag, selectedRefs, 'opening', op.id)}
                handleSize={handleSize}
                onShapePointerDown={(e) => startShapeDrag(e, { kind: 'opening', id: op.id })}
                onVertexPointerDown={(e, idx) =>
                  startVertexDrag(e, { kind: 'opening', id: op.id }, idx)
                }
              />
            ) : null;
          }
          const obj = draft.objects.find((o) => o.id === ref.id);
          return obj ? (
            <ObjectShape
              key={`sel-${obj.id}`}
              object={obj}
              selected
              drag={groupDrag(drag, selectedRefs, 'object', obj.id)}
              handleSize={handleSize}
              onShapePointerDown={(e) => startShapeDrag(e, { kind: 'object', id: obj.id })}
              onResizePointerDown={(e, sign) =>
                startResizeDrag(e, { kind: 'object', id: obj.id }, sign)
              }
            />
          ) : null;
        })}

        {/* 다중 선택 bbox + 4 모서리 그룹 리사이즈 핸들 */}
        {tool === 'select' &&
          selectedRefs &&
          selectedRefs.length >= 2 &&
          drag?.mode !== 'group-resize' &&
          (() => {
            const b = computeSelectionBounds(draft, selectedRefs);
            if (!b || b.w < 0.1 || b.h < 0.1) return null;
            const corners: { sign: [-1 | 1, -1 | 1]; x: number; y: number }[] = [
              { sign: [-1, -1], x: b.x, y: b.y },
              { sign: [1, -1], x: b.x + b.w, y: b.y },
              { sign: [-1, 1], x: b.x, y: b.y + b.h },
              { sign: [1, 1], x: b.x + b.w, y: b.y + b.h },
            ];
            return (
              <g>
                <rect
                  x={b.x}
                  y={b.y}
                  width={b.w}
                  height={b.h}
                  fill="none"
                  stroke="oklch(0.55 0.22 264)"
                  strokeWidth="1.5"
                  strokeDasharray="0.18 0.12"
                  vectorEffect="non-scaling-stroke"
                  pointerEvents="none"
                />
                {corners.map((c) => (
                  <GroupResizeHandle
                    key={`gr-${c.sign[0]}-${c.sign[1]}`}
                    x={c.x}
                    y={c.y}
                    size={handleSize}
                    onPointerDown={(e) => {
                      // 반대편 모서리가 고정점.
                      const fx = c.sign[0] === -1 ? b.x + b.w : b.x;
                      const fy = c.sign[1] === -1 ? b.y + b.h : b.y;
                      startGroupResizeDrag(e, [fx, fy], [c.x, c.y]);
                    }}
                  />
                ))}
              </g>
            );
          })()}

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
              r="0.07"
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
              r="0.07"
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
                    r={isFirstHighlighted ? 0.13 : isFirst ? 0.09 : 0.06}
                    fill={isFirstHighlighted ? 'oklch(0.55 0.22 264)' : 'white'}
                    stroke="oklch(0.55 0.22 264)"
                    strokeWidth={isFirstHighlighted ? 2 : 2}
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

        {/* Marquee 선택 박스 — 영역 안 도형들을 일괄 선택 */}
        {drag?.mode === 'marquee' &&
          (() => {
            const r = normalizeRect(drag.startSvg, drag.currentSvg);
            if (r.w < DRAG_THRESHOLD_M && r.h < DRAG_THRESHOLD_M) return null;
            return (
              <rect
                x={r.x}
                y={r.y}
                width={r.w}
                height={r.h}
                fill="oklch(0.62 0.18 264 / 0.08)"
                stroke="oklch(0.62 0.18 264)"
                strokeWidth="1.5"
                strokeDasharray="4 3"
                vectorEffect="non-scaling-stroke"
                pointerEvents="none"
              />
            );
          })()}

        {/* 스냅 인디케이터 — 끝점/축에 딱 붙었을 때 초록 링 */}
        {snapIndicator && (
          <g pointerEvents="none">
            <circle
              cx={snapIndicator[0]}
              cy={snapIndicator[1]}
              r={handleSize * 2.3}
              fill="none"
              stroke="oklch(0.72 0.19 145)"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={snapIndicator[0]}
              cy={snapIndicator[1]}
              r={handleSize * 0.7}
              fill="oklch(0.72 0.19 145)"
            />
          </g>
        )}

        {/* 축 스냅 가이드 — 벽/문창 vertex 가 반대편 꼭짓점 기준 정확히 수평/수직이 된 순간.
            (a) 캔버스 전체에 cyan 점선, (b) 스냅된 vertex 위치에 cyan 도트, (c) 90° 뱃지. */}
        {axisSnap && (
          <g pointerEvents="none">
            {axisSnap.axis === 'h' ? (
              <line
                x1={vb.x}
                y1={axisSnap.from[1]}
                x2={vb.x + vb.w}
                y2={axisSnap.from[1]}
                stroke="oklch(0.82 0.22 135)"
                strokeWidth="1.5"
                strokeDasharray="0.18 0.12"
                vectorEffect="non-scaling-stroke"
              />
            ) : (
              <line
                x1={axisSnap.from[0]}
                y1={vb.y}
                x2={axisSnap.from[0]}
                y2={vb.y + vb.h}
                stroke="oklch(0.82 0.22 135)"
                strokeWidth="1.5"
                strokeDasharray="0.18 0.12"
                vectorEffect="non-scaling-stroke"
              />
            )}
            <circle
              cx={axisSnap.to[0]}
              cy={axisSnap.to[1]}
              r={handleSize * 0.8}
              fill="oklch(0.82 0.22 135)"
            />
            {/* 90° 뱃지 — 스냅된 vertex 우상단에 살짝 띄워서. */}
            <g transform={`translate(${axisSnap.to[0] + handleSize * 1.6} ${axisSnap.to[1] - handleSize * 1.6})`}>
              <rect
                x={0}
                y={-handleSize * 1.4}
                width={handleSize * 4.2}
                height={handleSize * 1.8}
                rx={handleSize * 0.4}
                fill="oklch(0.82 0.22 135)"
              />
              <text
                x={handleSize * 2.1}
                y={-handleSize * 0.45}
                textAnchor="middle"
                fontSize={handleSize * 1.2}
                fontWeight="600"
                fill="white"
              >
                90°
              </text>
            </g>
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
  // marquee/group-resize 모드는 특정 ref 가 없음 — 도형별 단일 매칭 대상 아님.
  if (!drag || drag.mode === 'marquee' || drag.mode === 'group-resize') return null;
  if (drag.ref.kind === kind && drag.ref.id === id) return drag;
  return null;
}

/**
 * 다중 선택 + shape 드래그 시 그룹 미리보기용.
 * 드래그 중인 도형이 선택군에 포함되고 현재 도형도 선택군에 있다면 같은 delta 를 적용한
 * 가상 shape-drag 상태를 반환 (실 PATCH 는 pointerUp 에서 일괄 처리).
 */
function groupDrag(
  drag: DragState | null,
  selectedRefs: SelectedEntityRef[] | undefined,
  kind: SelectedEntityRef['kind'],
  id: string,
): DragState | null {
  const exact = matchDrag(drag, kind, id);
  if (exact) return exact;
  if (!drag || !selectedRefs || selectedRefs.length < 2) return null;
  const thisInSelection = selectedRefs.some((r) => r.kind === kind && r.id === id);
  if (!thisInSelection) return null;
  // group-resize: 선택된 모든 도형이 같은 변환을 받음.
  if (drag.mode === 'group-resize') return drag;
  // shape 드래그: 드래그된 도형이 선택군에 속하면 같은 delta 를 다른 선택 도형에도 미리보기.
  if (drag.mode === 'shape') {
    const draggedInSelection = selectedRefs.some(
      (r) => r.kind === drag.ref.kind && r.id === drag.ref.id,
    );
    if (!draggedInSelection) return null;
    return {
      mode: 'shape',
      ref: { kind, id },
      startSvg: drag.startSvg,
      delta: drag.delta,
    };
  }
  return null;
}

/** drag 진행 중인 도형의 effective coords 계산 (rendering 용). */
function effectiveLineCoords(coords: Coord[], drag: DragState | null): Coord[] {
  if (!drag || drag.mode === 'marquee' || drag.mode === 'resize') return coords;
  if (drag.mode === 'group-resize') {
    const { sx, sy } = groupResizeScale(drag);
    return coords.map((c) => scaleAround(c, drag.fixed, sx, sy));
  }
  const [dx, dy] = drag.delta;
  if (drag.mode === 'shape') {
    return coords.map(([x, y]) => [x + dx, y + dy] as Coord);
  }
  return moveLineStringVertex(coords, drag.vertexIndex, dx, dy);
}

function effectivePolygonRings(rings: Coord[][], drag: DragState | null): Coord[][] {
  if (!drag || drag.mode === 'marquee' || drag.mode === 'resize') return rings;
  if (drag.mode === 'group-resize') {
    const { sx, sy } = groupResizeScale(drag);
    return rings.map((r) => r.map((c) => scaleAround(c, drag.fixed, sx, sy)));
  }
  const [dx, dy] = drag.delta;
  if (drag.mode === 'shape') {
    return rings.map((r) => r.map(([x, y]) => [x + dx, y + dy] as Coord));
  }
  return movePolygonVertex(rings, drag.vertexIndex, dx, dy);
}

function effectivePoint(p: Coord, drag: DragState | null): Coord {
  if (!drag) return p;
  if (drag.mode === 'group-resize') {
    const { sx, sy } = groupResizeScale(drag);
    return scaleAround(p, drag.fixed, sx, sy);
  }
  if (drag.mode !== 'shape') return p;
  const [dx, dy] = drag.delta;
  return [p[0] + dx, p[1] + dy];
}

/**
 * drag 종료 시 적용할 새 GeoJSON 생성.
 * 호출 측에서 resize / marquee / group-resize 는 이미 분기 처리해 early return → 여기로
 * 들어오는 drag 는 shape 또는 vertex 뿐이라 타입으로 좁혀 받음 (TS narrowing 일관).
 */
function buildDraggedGeometry(
  drag: Extract<DragState, { mode: 'shape' | 'vertex' }>,
  draft: SceneDraft,
): GeoJsonGeometry | null {
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
  /** vertex/resize 핸들 시각 크기 (반지름, 미터). 도면 크기에 비례해 부모가 계산. */
  handleSize: number;
  onShapePointerDown: (e: React.PointerEvent) => void;
}
interface VertexAwareProps extends ShapeBaseProps {
  onVertexPointerDown: (e: React.PointerEvent, vertexIndex: number) => void;
}

function RoomShape({
  room,
  selected,
  drag,
  handleSize,
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
  const label = roomLabel(room);
  const center = polygonCentroid(handlePts);
  const ringBounds = polygonBounds(handlePts);
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
      {label && (
        <text
          x={center[0]}
          y={center[1]}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={computeLabelFontSize(label, ringBounds.w, ringBounds.h)}
          fontWeight="600"
          fill="oklch(0.35 0.02 256)"
          pointerEvents="none"
          style={{ userSelect: 'none' }}
        >
          {label}
        </text>
      )}
      {selected &&
        handlePts.map((pt, i) => (
          <VertexHandle
            key={i}
            x={pt[0]}
            y={pt[1]}
            size={handleSize}
            onPointerDown={(e) => onVertexPointerDown(e, i)}
          />
        ))}
    </g>
  );
}

/** AI 자동 생성으로 의심되는 이름. 사용자가 의도적으로 붙인 이름이 아니면 무시. */
const AUTO_ROOM_NAME = /^room[_\s-]?\d+$/i;

/** 방 표시용 라벨 — 의미 있는 room_name 이 있으면 우선, 그 외엔 room_type 한글 변환. */
function roomLabel(room: DraftRoom): string | null {
  const name = room.room_name?.trim();
  if (name && !AUTO_ROOM_NAME.test(name)) return name;
  if (room.room_type) return ROOM_TYPE_LABEL[room.room_type] ?? room.room_type;
  return 'room';
}

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

function WallShape({
  wall,
  selected,
  drag,
  handleSize,
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
          <VertexHandle x={start[0]} y={start[1]} size={handleSize} onPointerDown={(e) => onVertexPointerDown(e, 0)} />
          <VertexHandle x={end[0]} y={end[1]} size={handleSize} onPointerDown={(e) => onVertexPointerDown(e, 1)} />
        </>
      )}
    </g>
  );
}

function OpeningShape({
  opening,
  selected,
  drag,
  handleSize,
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
  const label = isDoor ? '문' : '창문';
  // 라벨은 선의 중점에서 수직 방향으로 살짝 떨어뜨려 배치.
  const midX = (start[0] + end[0]) / 2;
  const midY = (start[1] + end[1]) / 2;
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const len = Math.hypot(dx, dy) || 1;
  // 수직 단위 벡터
  const nx = -dy / len;
  const ny = dx / len;
  const offsetM = 0.17;
  const labelX = midX + nx * offsetM;
  const labelY = midY + ny * offsetM;
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
      <text
        x={labelX}
        y={labelY}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={OPENING_LABEL_FONT_SIZE_M}
        fontWeight="500"
        fill={baseColor}
        pointerEvents="none"
        style={{ userSelect: 'none' }}
      >
        {label}
      </text>
      {selected && (
        <>
          <VertexHandle x={start[0]} y={start[1]} size={handleSize} onPointerDown={(e) => onVertexPointerDown(e, 0)} />
          <VertexHandle x={end[0]} y={end[1]} size={handleSize} onPointerDown={(e) => onVertexPointerDown(e, 1)} />
        </>
      )}
    </g>
  );
}

function ObjectShape({
  object,
  selected,
  drag,
  handleSize,
  onShapePointerDown,
  onResizePointerDown,
}: { object: DraftObject } & ShapeBaseProps & {
  onResizePointerDown?: (e: React.PointerEvent, sign: [-1 | 1, -1 | 1]) => void;
}) {
  const g = parseGeometry(object.point_geom);
  if (g?.type !== 'Point') return null;
  const [x, y] = effectivePoint(g.coordinates, drag);
  const label = objectLabel(object);
  const spaceLike = isSpaceLikeObject(object);

  // 모든 객체 동일한 박스 + 라벨 + 리사이즈 핸들. 색은 통일하되,
  // 공간성(bathroom/kitchen/stairs ...) 은 점선 테두리로 "공간" 임을 시각적으로 구분.
  const size = readObjectSize(object);
  let w = size.width;
  let h = size.height;
  if (drag?.mode === 'resize') {
    w = Math.max(0.2, w + drag.delta[0] * drag.cornerSign[0] * 2);
    h = Math.max(0.2, h + drag.delta[1] * drag.cornerSign[1] * 2);
  } else if (drag?.mode === 'group-resize') {
    const { sx, sy } = groupResizeScale(drag);
    w = Math.max(0.2, w * Math.abs(sx));
    h = Math.max(0.2, h * Math.abs(sy));
  }
  const fill = selected ? 'oklch(0.92 0.05 264)' : 'oklch(0.95 0.03 240)';
  const stroke = selected ? 'oklch(0.55 0.22 264)' : 'oklch(0.74 0.08 240)';
  const labelFill = 'oklch(0.4 0.04 240)';
  // 공간성 객체는 선택 여부와 무관하게 항상 점선 (공간 vs 가구 구분 일관).
  const strokeDasharray = spaceLike ? '0.18 0.12' : undefined;

  return (
    <g className="cursor-pointer">
      <rect
        x={x - w / 2}
        y={y - h / 2}
        width={w}
        height={h}
        rx="0.15"
        fill={fill}
        stroke={stroke}
        strokeWidth={selected ? 3 : 1.5}
        strokeDasharray={strokeDasharray}
        vectorEffect="non-scaling-stroke"
        onPointerDown={onShapePointerDown}
      />
      {label && (
        <text
          x={x}
          y={y}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={computeLabelFontSize(label, w, h)}
          fontWeight="500"
          fill={labelFill}
          pointerEvents="none"
          style={{ userSelect: 'none' }}
        >
          {label}
        </text>
      )}
      {selected && onResizePointerDown && (
        <>
          <ResizeCorner x={x - w / 2} y={y - h / 2} sign={[-1, -1]} size={handleSize} onPointerDown={onResizePointerDown} />
          <ResizeCorner x={x + w / 2} y={y - h / 2} sign={[1, -1]} size={handleSize} onPointerDown={onResizePointerDown} />
          <ResizeCorner x={x - w / 2} y={y + h / 2} sign={[-1, 1]} size={handleSize} onPointerDown={onResizePointerDown} />
          <ResizeCorner x={x + w / 2} y={y + h / 2} sign={[1, 1]} size={handleSize} onPointerDown={onResizePointerDown} />
        </>
      )}
    </g>
  );
}

function objectLabel(object: DraftObject): string | null {
  if (!object.object_type) return null;
  return OBJECT_TYPE_LABEL[object.object_type] ?? object.object_type;
}

/** "점"이 아닌 "공간"으로 인식되어야 자연스러운 object_type 들. 시각적으로 점선 박스로 구분. */
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

function isSpaceLikeObject(o: DraftObject): boolean {
  return !!o.object_type && SPACE_LIKE_TYPES.has(o.object_type);
}

const SPACE_DEFAULT_SIZE_M = 1.6;

/** metadata_json 에 저장된 width_m / height_m 읽기. 없으면 기본값. */
/** 문/창문 라벨의 고정 폰트 크기 (미터 단위). 개구부 길이와 무관하게 일정. */
const OPENING_LABEL_FONT_SIZE_M = 0.13;

/** 방/공간성 객체 라벨이 박스 안에 들어가도록 폰트 크기 계산 (미터 단위).
 *  최대 크기는 개구부 라벨과 동일 (OPENING_LABEL_FONT_SIZE_M). */
function computeLabelFontSize(label: string, w: number, h: number): number {
  const charCount = Math.max(1, label.length);
  // 한글 기준 글자당 폭 ≈ fontSize. 안전한 여백을 위해 박스 너비의 50% 만 사용.
  const widthFit = (w * 0.5) / charCount;
  const heightFit = h * 0.35;
  const size = Math.min(widthFit, heightFit, OPENING_LABEL_FONT_SIZE_M);
  return Math.max(0.08, size);
}

function readObjectSize(o: DraftObject): { width: number; height: number } {
  const meta = o.metadata_json ?? {};
  const w = typeof meta.width_m === 'number' ? meta.width_m : SPACE_DEFAULT_SIZE_M;
  const h = typeof meta.height_m === 'number' ? meta.height_m : SPACE_DEFAULT_SIZE_M;
  return { width: w, height: h };
}

/** 객체 박스 4모서리 리사이즈 핸들. */
function ResizeCorner({
  x,
  y,
  sign,
  size,
  onPointerDown,
}: {
  x: number;
  y: number;
  sign: [-1 | 1, -1 | 1];
  size: number;
  onPointerDown: (e: React.PointerEvent, sign: [-1 | 1, -1 | 1]) => void;
}) {
  return (
    <g onPointerDown={(e) => onPointerDown(e, sign)} className="cursor-nwse-resize">
      <circle cx={x} cy={y} r={size * 4} fill="transparent" />
      <circle
        cx={x}
        cy={y}
        r={size}
        fill="white"
        stroke="oklch(0.55 0.22 264)"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </g>
  );
}

const OBJECT_TYPE_LABEL: Record<string, string> = {
  table: '테이블',
  chair: '의자',
  desk: '책상',
  sofa: '소파',
  bed: '침대',
  ap: 'AP',
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

function GroupResizeHandle({
  x,
  y,
  size,
  onPointerDown,
}: {
  x: number;
  y: number;
  size: number;
  onPointerDown: (e: React.PointerEvent) => void;
}) {
  const outer = size * 3.6;
  const inner = size * 1.6;
  return (
    <g onPointerDown={onPointerDown} className="cursor-nwse-resize">
      <rect x={x - outer / 2} y={y - outer / 2} width={outer} height={outer} fill="transparent" />
      <rect
        x={x - inner / 2}
        y={y - inner / 2}
        width={inner}
        height={inner}
        fill="white"
        stroke="oklch(0.55 0.22 264)"
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
      />
    </g>
  );
}

function VertexHandle({
  x,
  y,
  size,
  onPointerDown,
}: {
  x: number;
  y: number;
  size: number;
  onPointerDown: (e: React.PointerEvent) => void;
}) {
  return (
    <g onPointerDown={onPointerDown} className="cursor-grab">
      <circle cx={x} cy={y} r={size * 3.7} fill="transparent" />
      <circle
        cx={x}
        cy={y}
        r={size}
        fill="white"
        stroke="oklch(0.55 0.22 264)"
        strokeWidth="1.5"
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
