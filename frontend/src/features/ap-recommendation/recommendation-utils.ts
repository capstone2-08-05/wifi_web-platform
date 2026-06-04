import type {
  ExistingAp,
  ApRecommendationRequest,
  ApRecommendationResponse,
  ApRecommendationResult,
} from '@/types/ap-recommendation';
import type { UUID } from '@/types/common';
import { parseGeometry } from '@/features/editor/geometry-utils';
import { CANVAS_BLUE } from '@/lib/canvas-scene-colors';

/** AP 추천 순위 — 하늘색 단일 계열 (진→옅, 명도 차이 확대) */
const RANK1_SKY = '#3B82F6';
const RANK2_SKY = '#60A5FA';
const RANK3_SKY = '#BFDBFE';
const RANK_SKY_MUTED = '#EAF4FF';
const RANK2_SKY_HOVER = '#3B82F6';
const RANK3_SKY_HOVER = '#93C5FD';

/** primary hover — blue-600, 1위 캔버스 마커 강조용 */
const CANVAS_BLUE_HOVER = 'oklch(0.546 0.245 262.881)';

/** AP 설치 높이 기본값 — SimulationCanvas DEFAULT_AP_Z_M 과 동일. */
export const AP_DEFAULT_Z_M = 2.5;

/** 미터 단위 선택 영역 (API x_min/x_max/y_min/y_max). */
export interface MeterBBox {
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
}

const MIN_SELECTION_M = 0.2;

/** normalizeRect 결과 → MeterBBox. */
export function meterBBoxFromRect(rect: {
  x: number;
  y: number;
  w: number;
  h: number;
}): MeterBBox {
  return {
    x_min: rect.x,
    x_max: rect.x + rect.w,
    y_min: rect.y,
    y_max: rect.y + rect.h,
  };
}

export function isValidSelectionBBox(bbox: MeterBBox | null): bbox is MeterBBox {
  if (!bbox) return false;
  const w = bbox.x_max - bbox.x_min;
  const h = bbox.y_max - bbox.y_min;
  return w >= MIN_SELECTION_M && h >= MIN_SELECTION_M;
}

export function validSelectionBBoxes(bboxes: MeterBBox[] | null | undefined): MeterBBox[] {
  return (bboxes ?? []).filter(isValidSelectionBBox);
}

export function unionMeterBBoxes(bboxes: MeterBBox[]): MeterBBox | null {
  const valid = validSelectionBBoxes(bboxes);
  if (valid.length === 0) return null;
  return {
    x_min: Math.min(...valid.map((b) => b.x_min)),
    x_max: Math.max(...valid.map((b) => b.x_max)),
    y_min: Math.min(...valid.map((b) => b.y_min)),
    y_max: Math.max(...valid.map((b) => b.y_max)),
  };
}

/** POST /ap-recommendation 요청 본문 조립 (백엔드 default 필드는 생략). */
export function buildApRecommendationPayload(params: {
  sceneVersionId: UUID;
  bboxes: MeterBBox[];
  existingAps: { id: string; x_m: number; y_m: number }[];
  txPowerDbm?: number;
}): ApRecommendationRequest {
  const bboxes = validSelectionBBoxes(params.bboxes);
  const union = unionMeterBBoxes(bboxes);
  if (!union) {
    throw new Error('At least one valid target bbox is required.');
  }
  return {
    scene_version_id: params.sceneVersionId,
    x_min: union.x_min,
    x_max: union.x_max,
    y_min: union.y_min,
    y_max: union.y_max,
    candidate_bboxes: bboxes,
    target_bboxes: bboxes,
    existing_aps: mapToExistingAps(params.existingAps, params.txPowerDbm),
  };
}

/** 응답 → UI 표시용 배열로 normalize. */
export function normalizeRecommendations(
  response: ApRecommendationResponse | null | undefined,
): ApRecommendationResult[] {
  if (!response) return [];
  return response.recommendations.map((item) => ({
    rank: item.rank,
    recommended_x: item.recommended_x,
    recommended_y: item.recommended_y,
    score: item.score,
    candidates_evaluated: response.candidates_evaluated,
    coverage_score: item.coverage_score,
    coverage_ratio: item.coverage_ratio,
    weak_zone_improvement_score: item.weak_zone_improvement_score,
    weak_zone_improvement_db: item.weak_zone_improvement_db,
    bottom_10_percent_score: item.bottom_10_percent_score,
    bottom_10_percent_rssi_dbm: item.bottom_10_percent_rssi_dbm,
    average_rssi_score: item.average_rssi_score,
    average_rssi_dbm: item.average_rssi_dbm,
    baseline_improvement_score: item.baseline_improvement_score,
    baseline_improvement_db: item.baseline_improvement_db,
  }));
}

/** 캔버스 AP → API existing_aps. tx_power_dbm 없으면 필드 생략(백엔드 default 20). */
export function mapToExistingAps(
  aps: { id: string; x_m: number; y_m: number }[],
  txPowerDbm?: number,
): ExistingAp[] {
  return aps.map((ap) => {
    const base: ExistingAp = { id: ap.id, x_m: ap.x_m, y_m: ap.y_m };
    if (txPowerDbm != null && Number.isFinite(txPowerDbm)) {
      base.tx_power_dbm = txPowerDbm;
    }
    return base;
  });
}

/** 두 코너 → (x,y,w,h) 사각형 정규화. */
export function normalizeRect(
  a: [number, number],
  b: [number, number],
): { x: number; y: number; w: number; h: number } {
  const x = Math.min(a[0], b[0]);
  const y = Math.min(a[1], b[1]);
  const w = Math.abs(a[0] - b[0]);
  const h = Math.abs(a[1] - b[1]);
  return { x, y, w, h };
}

/** 드래그 선택 가능 영역 (미터). 도면 이미지 extent 또는 벽/개구부 tight bounds. */
export interface SceneBounds {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function clampCoord(
  point: [number, number],
  bounds: SceneBounds,
): [number, number] {
  return [
    clamp(point[0], bounds.xMin, bounds.xMax),
    clamp(point[1], bounds.yMin, bounds.yMax),
  ];
}

/** 사각형을 scene bounds 안으로 제한. */
export function clampRectToBounds(
  rect: { x: number; y: number; w: number; h: number },
  bounds: SceneBounds,
): { x: number; y: number; w: number; h: number } {
  const x1 = clamp(rect.x, bounds.xMin, bounds.xMax);
  const y1 = clamp(rect.y, bounds.yMin, bounds.yMax);
  const x2 = clamp(rect.x + rect.w, bounds.xMin, bounds.xMax);
  const y2 = clamp(rect.y + rect.h, bounds.yMin, bounds.yMax);
  return normalizeRect([x1, y1], [x2, y2]);
}

/** MeterBBox를 scene bounds 안으로 제한. */
export function clampMeterBBox(bbox: MeterBBox, bounds: SceneBounds): MeterBBox {
  const x_min = clamp(bbox.x_min, bounds.xMin, bounds.xMax);
  const x_max = clamp(bbox.x_max, bounds.xMin, bounds.xMax);
  const y_min = clamp(bbox.y_min, bounds.yMin, bounds.yMax);
  const y_max = clamp(bbox.y_max, bounds.yMin, bounds.yMax);
  return {
    x_min: Math.min(x_min, x_max),
    x_max: Math.max(x_min, x_max),
    y_min: Math.min(y_min, y_max),
    y_max: Math.max(y_min, y_max),
  };
}

interface GeometryBoundsInput {
  walls?: { centerline_geom?: Record<string, unknown> | null }[];
  openings?: { line_geom?: Record<string, unknown> | null }[];
}

function extendBoundsFromGeometry(
  b: { minX: number; minY: number; maxX: number; maxY: number },
  geom: Record<string, unknown> | null | undefined,
) {
  const g = parseGeometry(geom);
  if (g?.type !== 'LineString') return;
  for (const [x, y] of g.coordinates) {
    if (x < b.minX) b.minX = x;
    if (y < b.minY) b.minY = y;
    if (x > b.maxX) b.maxX = x;
    if (y > b.maxY) b.maxY = y;
  }
}

/** 도면 이미지 extent 우선, 없으면 벽/개구부 union tight bounds. */
export function computeSceneBounds(
  scene: GeometryBoundsInput | null | undefined,
  imageExtent: { w: number; h: number } | null,
): SceneBounds {
  if (imageExtent && imageExtent.w > 0 && imageExtent.h > 0) {
    return { xMin: 0, yMin: 0, xMax: imageExtent.w, yMax: imageExtent.h };
  }
  const b = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
  for (const wall of scene?.walls ?? []) {
    extendBoundsFromGeometry(b, wall.centerline_geom);
  }
  for (const opening of scene?.openings ?? []) {
    extendBoundsFromGeometry(b, opening.line_geom);
  }
  if (!Number.isFinite(b.minX)) {
    return { xMin: 0, yMin: 0, xMax: 10, yMax: 10 };
  }
  return { xMin: b.minX, yMin: b.minY, xMax: b.maxX, yMax: b.maxY };
}

/** AP 추천 순위 — 패널 accent/badge·캔버스 마커 (하늘색 계열). */
export interface RecommendationRankUi {
  accent: string;
  accentMuted: string;
  fill: string;
  fillHighlighted: string;
  markerLabelFill: string;
  badgeClass: string;
  cardAccentClass: string;
  cardHighlightClass: string;
  title: string;
}

export function getRecommendationRankUi(rank: number): RecommendationRankUi {
  switch (rank) {
    case 1:
      return {
        accent: RANK1_SKY,
        accentMuted: RANK_SKY_MUTED,
        fill: CANVAS_BLUE,
        fillHighlighted: CANVAS_BLUE_HOVER,
        markerLabelFill: '#FFFFFF',
        badgeClass: 'bg-[#3B82F6] text-white font-bold',
        cardAccentClass: 'border-l-[#3B82F6]',
        cardHighlightClass: 'bg-[#EAF4FF]/70',
        title: '1위 추천 위치',
      };
    case 2:
      return {
        accent: RANK2_SKY,
        accentMuted: RANK_SKY_MUTED,
        fill: RANK2_SKY,
        fillHighlighted: RANK2_SKY_HOVER,
        markerLabelFill: '#1E3A8A',
        badgeClass: 'bg-[#60A5FA] text-[#1E3A8A] font-semibold',
        cardAccentClass: 'border-l-[#60A5FA]',
        cardHighlightClass: 'bg-white',
        title: '2위 추천 위치',
      };
    default:
      return {
        accent: RANK3_SKY,
        accentMuted: RANK_SKY_MUTED,
        fill: RANK3_SKY,
        fillHighlighted: RANK3_SKY_HOVER,
        markerLabelFill: '#2563EB',
        badgeClass: 'bg-[#BFDBFE] text-[#2563EB] font-semibold',
        cardAccentClass: 'border-l-[#BFDBFE]',
        cardHighlightClass: 'bg-white',
        title: `${rank}위 추천 위치`,
      };
  }
}

function getScoreGapMetrics(
  rec: ApRecommendationResult,
  first: ApRecommendationResult,
  all: ApRecommendationResult[],
) {
  const gap = first.score - rec.score;
  const scores = all.map((r) => r.score);
  const scoreSpan = Math.max(...scores) - Math.min(...scores);
  const normalized = scoreSpan > 0 ? gap / scoreSpan : 0;
  return { gap, normalized };
}

function isNearBboxEdge(rec: ApRecommendationResult, bbox: MeterBBox): boolean {
  const w = bbox.x_max - bbox.x_min;
  const h = bbox.y_max - bbox.y_min;
  const thresholdX = Math.max(w * 0.12, 0.4);
  const thresholdY = Math.max(h * 0.12, 0.4);
  return (
    rec.recommended_x - bbox.x_min < thresholdX ||
    bbox.x_max - rec.recommended_x < thresholdX ||
    rec.recommended_y - bbox.y_min < thresholdY ||
    bbox.y_max - rec.recommended_y < thresholdY
  );
}

function distanceBetween(a: ApRecommendationResult, b: ApRecommendationResult): number {
  return Math.hypot(a.recommended_x - b.recommended_x, a.recommended_y - b.recommended_y);
}

function describeCoverageAdvantage(
  rec: ApRecommendationResult,
  first: ApRecommendationResult,
  all: ApRecommendationResult[],
): string {
  const { gap, normalized } = getScoreGapMetrics(rec, first, all);
  const distFromFirst = distanceBetween(rec, first);
  const nearEqual = gap <= 0.5 || normalized <= 0.08;
  const moderate = normalized <= 0.35;

  if (rec.rank === 2) {
    if (nearEqual && distFromFirst >= 0.8) {
      return '1위와 거의 같은 신호 커버를 내면서, 다른 지점이라 천장·전원 등 설치 제약에 맞추기 좋습니다.';
    }
    if (nearEqual) {
      return '1위와 성능이 거의 같아, 1위 설치가 어려울 때 바로 쓸 수 있는 대안입니다.';
    }
    if (moderate) {
      return '1위보다 일부 구역 신호는 약간 낮지만, 두 번째로 균형 잡힌 커버를 기대할 수 있습니다.';
    }
    return '1위보다 커버는 낮지만, 다른 지점 배치가 필요할 때 고려할 수 있습니다.';
  }

  if (nearEqual && distFromFirst >= 0.8) {
    return '1위와 비슷한 커버를 유지하면서, 분산·예비 배치에 활용하기 좋습니다.';
  }
  if (moderate) {
    return `${rec.rank}순위이지만 1위와 비슷한 수준을 유지하며, 다른 위치의 대안으로 쓸 수 있습니다.`;
  }
  return '1위보다 커버는 낮지만, 1·2위 설치가 어렵거나 배치 변경 시 참고할 수 있는 옵션입니다.';
}

/** API score 기반 추천 이유 문장 (raw 점수 미노출) */
export function getRecommendationReason(
  rec: ApRecommendationResult,
  all: ApRecommendationResult[],
  bbox: MeterBBox | null,
): string {
  const first = all.find((r) => r.rank === 1) ?? all[0];
  const parts: string[] = [];

  if (rec.rank === 1) {
    parts.push(
      '우선 개선 영역·도면 평가 지점에서 음영 구역을 줄이고 예측 신호가 가장 잘 닿는 위치입니다.',
    );
    if (bbox && isNearBboxEdge(rec, bbox)) {
      parts.push('선택 영역 가장자리 근처입니다.');
    }
    return parts.join(' ');
  }

  if (!first) return '';

  return describeCoverageAdvantage(rec, first, all);
}
