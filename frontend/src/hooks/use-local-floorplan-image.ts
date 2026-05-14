import { useEffect, useState } from 'react';

/**
 * 도면 이미지 로컬 캐시 — 백엔드가 source_asset_id 안 채우는 케이스 우회.
 * 사용자가 업로드한 파일을 base64 로 localStorage 에 보관하고, 캔버스 배경에 사용.
 *
 * - 키: `floorplan-image-${floorId}`
 * - PDF 는 브라우저가 직접 렌더링 불가하므로 스킵 (image/* 만 저장).
 * - localStorage 용량 초과 시 조용히 실패.
 */

const PREFIX = 'floorplan-image-';

function key(floorId: string): string {
  return `${PREFIX}${floorId}`;
}

function readForFloor(floorId: string | null): string | null {
  if (!floorId) return null;
  try {
    return localStorage.getItem(key(floorId));
  } catch {
    return null;
  }
}

export function useLocalFloorplanImage(floorId: string | null): string | null {
  const [dataUrl, setDataUrl] = useState<string | null>(() => readForFloor(floorId));

  useEffect(() => {
    setDataUrl(readForFloor(floorId));
  }, [floorId]);

  // 다른 탭/스코프에서 변경되거나 같은 페이지의 saveLocalFloorplanImage 호출 후 동기화.
  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<{ floorId: string }>).detail;
      if (!floorId) return;
      if (detail?.floorId === floorId || e.type === 'storage') {
        setDataUrl(readForFloor(floorId));
      }
    };
    window.addEventListener('storage', onChange);
    window.addEventListener('floorplan-image-changed', onChange);
    return () => {
      window.removeEventListener('storage', onChange);
      window.removeEventListener('floorplan-image-changed', onChange);
    };
  }, [floorId]);

  return dataUrl;
}

/** 도면 파일을 floor 별로 캐시. 이미지 파일만 저장 (PDF 는 스킵). */
export function saveLocalFloorplanImage(floorId: string, file: File): void {
  if (!file.type.startsWith('image/')) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const dataUrl = reader.result as string;
      localStorage.setItem(key(floorId), dataUrl);
      // 같은 페이지에서 듣고 있는 hook 들 알림.
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

export function clearLocalFloorplanImage(floorId: string): void {
  try {
    localStorage.removeItem(key(floorId));
    window.dispatchEvent(
      new CustomEvent('floorplan-image-changed', { detail: { floorId } }),
    );
  } catch {
    /* noop */
  }
}
