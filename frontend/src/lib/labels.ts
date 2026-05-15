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

/** 객체 종류 변경 select 의 옵션 (백엔드 enum 값). */
export const OBJECT_TYPE_OPTIONS = Object.keys(OBJECT_TYPE_LABELS);

export function objectTypeLabel(type: string | null | undefined): string {
  const key = (type ?? '').toLowerCase();
  return OBJECT_TYPE_LABELS[key] ?? type ?? '객체';
}
