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
