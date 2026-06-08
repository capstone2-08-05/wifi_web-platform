/** 도메인 enum 값 → 사용자 표시용 한국어 라벨. */

/** opening_type (door/window/...) → 사용자 친화 라벨. 미상이면 '개구부'. */
export function openingTypeLabel(type: string | null | undefined): string {
  switch ((type ?? '').toLowerCase()) {
    case 'door':
      return '문';
    case 'window':
      return '창문';
    default:
      return '개구부';
  }
}

/** object_type → 사용자 친화 라벨. value 는 백엔드 enum 값 그대로 유지. */
const OBJECT_TYPE_LABELS: Record<string, string> = {
  furniture: '가구',
  bathroom: '화장실',
  kitchen: '주방',
  stairs: '계단',
  elevator: '엘리베이터',
  toilet: '변기',
  sink: '싱크대',
  bathtub: '욕조',
  bed: '침대',
  sofa: '소파',
  table: '테이블',
  closet: '붙박이장',
};

/**
 * 객체 종류 변경 select 의 옵션 (백엔드 enum 값).
 * 2026-05-16 DB 조회 기준 실제 사용되는 값(`SELECT DISTINCT object_type FROM objects/draft_objects`).
 * AI 모델이 새 클래스를 뱉으면 라벨 매핑(OBJECT_TYPE_LABELS) 에는 있으니 표시는 정상.
 * 단, 사용자가 이 선택지를 통해 변경할 수 있는 값만 여기에 둔다.
 */
export const OBJECT_TYPE_OPTIONS = [
  'furniture',
  'bathroom',
  'stairs',
  'sofa',
  'table',
];

export function objectTypeLabel(type: string | null | undefined): string {
  const key = (type ?? '').toLowerCase();
  return OBJECT_TYPE_LABELS[key] ?? type ?? '객체';
}

/** 벽의 wall_role → 한국어 라벨. */
const WALL_ROLE_LABELS: Record<string, string> = {
  inner: '내벽',
  outer: '외벽',
  partition: '칸막이',
};

export function wallRoleLabel(role: string | null | undefined): string {
  const key = (role ?? '').toLowerCase();
  return WALL_ROLE_LABELS[key] ?? role ?? '-';
}

/** 재질(material_label / material_code) → 한국어 라벨. Sionna 유효 재질만 포함. */
const MATERIAL_LABELS: Record<string, string> = {
  concrete: '콘크리트',
  brick: '벽돌',
  drywall: '석고보드',
  plasterboard: '석고보드',  // Sionna 내부 키 (drywall alias)
  glass: '유리',
  wood: '목재',
  metal: '금속',
  chipboard: '칩보드',
  ceiling_board: '천장재',
};

export function materialLabel(material: string | null | undefined): string {
  const key = (material ?? '').toLowerCase();
  return MATERIAL_LABELS[key] ?? material ?? '-';
}

/** 재질 코드 → 캔버스 벽 stroke 색상 (oklch). */
export const MATERIAL_COLORS: Record<string, string> = {
  concrete:     'oklch(0.38 0.01 250)',   // 짙은 회색
  brick:        'oklch(0.52 0.13 35)',    // 벽돌 적갈색
  drywall:      'oklch(0.65 0.07 80)',    // 베이지
  plasterboard: 'oklch(0.65 0.07 80)',    // 베이지 (drywall alias)
  wood:         'oklch(0.55 0.10 55)',    // 갈색
  glass:        'oklch(0.60 0.12 220)',   // 하늘색
  metal:        'oklch(0.52 0.05 245)',   // 강철 청회색
  chipboard:    'oklch(0.62 0.07 75)',    // 황갈색
  ceiling_board:'oklch(0.68 0.06 85)',    // 황토
};

/** material_label → stroke 색상. null/미지정이면 진회색. */
export function materialColor(material: string | null | undefined): string {
  const key = (material ?? '').toLowerCase().replace(/^itu_/, '');
  return MATERIAL_COLORS[key] ?? 'oklch(0.25 0 0)';
}

/** room_type → 한국어 라벨. 미상이면 그대로 반환. */
const ROOM_TYPE_LABELS: Record<string, string> = {
  general: '일반',
  living: '거실',
  living_room: '거실',
  bedroom: '침실',
  kitchen: '주방',
  bathroom: '화장실',
  office: '사무실',
  hallway: '복도',
  corridor: '복도',
  lobby: '로비',
  storage: '창고',
  closet: '붙박이장',
  utility: '다용도실',
  balcony: '베란다',
  dining: '식당',
  dining_room: '식당',
};

export function roomTypeLabel(type: string | null | undefined): string {
  const key = (type ?? '').toLowerCase();
  return ROOM_TYPE_LABELS[key] ?? type ?? '-';
}
