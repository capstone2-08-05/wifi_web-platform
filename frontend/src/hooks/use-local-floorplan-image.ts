import { useEffect, useState } from 'react';

/**
 * 도면 이미지 로컬 캐시 — 백엔드가 source_asset_id 안 채우는 케이스 + 백엔드가 자산 URL 을
 * 상대경로(`/assets/{id}/raw`) 로만 주는 local 모드 케이스 우회.
 *
 * 키 전략 — **자산별 키 우선, 층별 키 fallback**:
 *   - `floorplan-image-asset:{assetId}` (신규, 자산 ID 별로 별도 보관 → 히스토리 버전 클릭 시
 *     그 당시 업로드한 이미지가 정확히 복원됨)
 *   - `floorplan-image-{floorId}` (legacy, 층당 1장 — 항상 가장 최근 업로드. 새 업로드 직후
 *     아직 source_asset_id 모를 때 임시로 쓰는 staging)
 *
 * 새 업로드 흐름:
 *   1. EditorPage.handleFile → `saveLocalFloorplanImage(floorId, file)` (asset_id 없음 → floor 키만)
 *   2. analyze 완료, draft 의 source_asset_id 알게 됨 → `linkFloorImageToAsset(floorId, assetId)`
 *      가 floor 키 내용을 asset 키로 복사 (덮어쓰지 않음 — 기존 asset 캐시가 있으면 그대로)
 *
 * 히스토리 버전 로드:
 *   useLocalFloorplanImage({ floorId, sourceAssetId }) — assetId 키 hit 면 즉시 반환,
 *   없으면 floor 키 (latest) 로 fallback. assetId 가 null 이면 floor 키만 사용 (legacy 동작).
 *
 * - PDF 는 브라우저가 직접 렌더링 불가하므로 스킵 (image/* 만 저장).
 * - localStorage 용량 초과 시 조용히 실패.
 */

const FLOOR_PREFIX = 'floorplan-image-';
const ASSET_PREFIX = 'floorplan-image-asset:';

function floorKey(floorId: string): string {
  return `${FLOOR_PREFIX}${floorId}`;
}

function assetKey(assetId: string): string {
  return `${ASSET_PREFIX}${assetId}`;
}

function readEntry(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function readForAssetOrFloor(
  floorId: string | null,
  sourceAssetId: string | null | undefined,
  allowFloorFallback: boolean,
): string | null {
  if (sourceAssetId) {
    const v = readEntry(assetKey(sourceAssetId));
    if (v) return v;
  }
  if (allowFloorFallback && floorId) {
    const v = readEntry(floorKey(floorId));
    if (v) return v;
  }
  return null;
}

export interface UseLocalFloorplanImageOpts {
  floorId: string | null;
  /** SceneVersion / SceneDraft 의 source_asset_id — 있으면 이 자산별 키를 우선 읽음. */
  sourceAssetId?: string | null;
  allowFloorFallback?: boolean;
}

/**
 * 두 가지 호출 시그니처 지원:
 *   - useLocalFloorplanImage(floorId)                   (legacy)
 *   - useLocalFloorplanImage({ floorId, sourceAssetId })
 */
export function useLocalFloorplanImage(
  floorIdOrOpts: string | null | UseLocalFloorplanImageOpts,
): string | null {
  const opts: UseLocalFloorplanImageOpts =
    typeof floorIdOrOpts === 'object' && floorIdOrOpts !== null
      ? floorIdOrOpts
      : { floorId: floorIdOrOpts ?? null };
  const { floorId, sourceAssetId } = opts;
  const allowFloorFallback = opts.allowFloorFallback ?? !sourceAssetId;

  const [dataUrl, setDataUrl] = useState<string | null>(() =>
    readForAssetOrFloor(floorId, sourceAssetId, allowFloorFallback),
  );

  useEffect(() => {
    setDataUrl(readForAssetOrFloor(floorId, sourceAssetId, allowFloorFallback));
  }, [floorId, sourceAssetId, allowFloorFallback]);

  // 다른 탭/스코프에서 변경되거나 같은 페이지의 save/link 호출 후 동기화.
  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<{ floorId?: string; assetId?: string }>).detail;
      // 우리 키와 무관한 storage 이벤트는 무시.
      if (e.type === 'floorplan-image-changed') {
        const matchesFloor = !!floorId && detail?.floorId === floorId;
        const matchesAsset = !!sourceAssetId && detail?.assetId === sourceAssetId;
        if (!matchesFloor && !matchesAsset) return;
      }
      setDataUrl(readForAssetOrFloor(floorId, sourceAssetId, allowFloorFallback));
    };
    window.addEventListener('storage', onChange);
    window.addEventListener('floorplan-image-changed', onChange);
    return () => {
      window.removeEventListener('storage', onChange);
      window.removeEventListener('floorplan-image-changed', onChange);
    };
  }, [floorId, sourceAssetId, allowFloorFallback]);

  return dataUrl;
}

/** 업로드 직후 호출 — floor 키에 저장 (asset_id 아직 모를 때의 staging). */
export function saveLocalFloorplanImage(floorId: string, file: File): void {
  if (!file.type.startsWith('image/')) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const dataUrl = reader.result as string;
      localStorage.setItem(floorKey(floorId), dataUrl);
      window.dispatchEvent(
        new CustomEvent('floorplan-image-changed', { detail: { floorId } }),
      );
    } catch (e) {
      // 용량 초과 등 — 무시 (배경만 못 보일 뿐 핵심 기능은 정상).
      console.warn('[FloorplanImage] localStorage 저장 실패:', e);
    }
  };
  reader.readAsDataURL(file);
}

/**
 * Draft/Version 의 source_asset_id 알게 된 순간 호출 — floor 키의 이미지를 asset 키로
 * 복사 보존. 이후 새 업로드가 floor 키를 덮어써도 옛 자산 이미지는 asset 키로 살아남음.
 * 이미 asset 키에 값이 있으면 덮어쓰지 않음 (한번 link 되면 그 후 불변).
 */
export function linkFloorImageToAsset(
  floorId: string | null | undefined,
  assetId: string | null | undefined,
): void {
  if (!floorId || !assetId) return;
  try {
    if (localStorage.getItem(assetKey(assetId))) return; // 이미 link 됨
    const fromFloor = localStorage.getItem(floorKey(floorId));
    if (!fromFloor) return;
    localStorage.setItem(assetKey(assetId), fromFloor);
    window.dispatchEvent(
      new CustomEvent('floorplan-image-changed', { detail: { assetId } }),
    );
  } catch {
    /* quota / private mode — 무시 */
  }
}

export function clearLocalFloorplanImage(floorId: string): void {
  try {
    localStorage.removeItem(floorKey(floorId));
    window.dispatchEvent(
      new CustomEvent('floorplan-image-changed', { detail: { floorId } }),
    );
  } catch {
    /* noop */
  }
}
