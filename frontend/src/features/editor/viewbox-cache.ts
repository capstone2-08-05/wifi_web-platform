/**
 * 공용 viewBox 캐시 — editor / simulation / measurement 캔버스가 같은 영역을 표시하도록 공유.
 *
 * editor 의 DraftSceneCanvas 가 처음 마운트될 때 도면 + 배경 이미지 union 으로 viewBox 를
 * 계산하고 이 키에 저장한다. 시뮬레이션/실측 페이지의 캔버스는 이 캐시를 읽어 같은 영역을
 * 표시한다. 사용자가 도형을 작게 그려도 캔버스 영역이 갑자기 줄지 않고, 페이지 간 일관성 유지.
 */
export interface CachedViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

const PREFIX = 'draft-viewbox:v2:';

export function viewBoxCacheKey(floorId: string): string {
  return PREFIX + floorId;
}

export function loadCachedViewBox(floorId: string | null | undefined): CachedViewBox | null {
  if (!floorId) return null;
  try {
    const raw = localStorage.getItem(viewBoxCacheKey(floorId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CachedViewBox>;
    if (
      typeof parsed.x === 'number' &&
      typeof parsed.y === 'number' &&
      typeof parsed.w === 'number' &&
      typeof parsed.h === 'number' &&
      parsed.w > 0 &&
      parsed.h > 0
    ) {
      return parsed as CachedViewBox;
    }
  } catch {
    // localStorage 접근 실패 / JSON parse 실패: 캐시 무시.
  }
  return null;
}
