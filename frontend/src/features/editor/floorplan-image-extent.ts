/**
 * 배경 도면 이미지의 실제 미터 extent 계산 — DraftSceneCanvas / SimulationCanvas 공용.
 *
 * 핵심: 벽 좌표가 `pixel × scale_ratio_m_per_px` 로 미터화 되었으므로, 같은 scale 을
 * 이미지에 적용하면 벽과 정확히 정렬되는 (0,0)~(extent.w, extent.h) 사각형을 얻는다.
 *
 * 우선순위:
 *   1. summary_json.scale_ratio_m_per_px (신규, draft 직후만 채워짐)
 *   2. summary_json.storage.real_width_m (legacy)
 *   3. localStorage 캐시 (asset_id / floor_id 키) — promote 후 SceneVersion 으로
 *      바뀌어 summary 가 비어도 복원 가능
 *
 * scale_ratio 캐시도 같은 패턴으로 보관 — editor 에서 한 번 저장하면 simulation
 * 페이지에서 동일하게 복원.
 */
import { useEffect, useState } from 'react';

const REAL_WIDTH_CACHE_PREFIX = 'asset-real-width-m:v1:';
const SCALE_RATIO_CACHE_PREFIX = 'asset-scale-ratio-m-per-px:v1:';

// ============================================
// real_width_m (legacy) 캐시
// ============================================
export function loadCachedRealWidth(key: string): number | null {
  try {
    const raw = localStorage.getItem(REAL_WIDTH_CACHE_PREFIX + key);
    if (!raw) return null;
    const v = Number(raw);
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

export function saveCachedRealWidth(key: string, w: number): void {
  try {
    localStorage.setItem(REAL_WIDTH_CACHE_PREFIX + key, String(w));
  } catch {
    /* quota / private mode: 무시 */
  }
}

// ============================================
// scale_ratio_m_per_px 캐시 (신규, 권장)
// ============================================
export function loadCachedScaleRatio(key: string): number | null {
  try {
    const raw = localStorage.getItem(SCALE_RATIO_CACHE_PREFIX + key);
    if (!raw) return null;
    const v = Number(raw);
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

export function saveCachedScaleRatio(key: string, ratio: number): void {
  try {
    localStorage.setItem(SCALE_RATIO_CACHE_PREFIX + key, String(ratio));
  } catch {
    /* quota / private mode: 무시 */
  }
}

// ============================================
// Hook: 이미지 natural 픽셀 dim
// ============================================
export function useImageNaturalDimensions(
  url: string | null | undefined,
): { w: number; h: number } | null {
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => {
    setDims(null);
    if (!url) return;
    const img = new Image();
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

// ============================================
// 핵심: imageExtent (미터) 계산
// ============================================
export interface ImageExtentSource {
  /** draft 직후 summary_json.storage.real_width_m */
  realWidthM?: number | null;
  /** draft 직후 summary_json.scale_ratio_m_per_px */
  scaleRatioMPerPx?: number | null;
  /** 캐시 lookup 키. 둘 다 시도하므로 가능한 만큼 채움. */
  sourceAssetId?: string | null;
  floorId?: string | null;
}

/**
 * 이미지의 실제 미터 크기. summary 우선, 없으면 캐시 fallback. 둘 다 없으면 null.
 *
 * imageDims 가 없으면 (이미지 못 로드) 항상 null.
 */
export function deriveImageExtent(
  imageDims: { w: number; h: number } | null,
  src: ImageExtentSource,
): { w: number; h: number } | null {
  if (!imageDims || imageDims.w <= 0) return null;

  const scaleRatio = resolveScaleRatio(src);
  if (scaleRatio != null) {
    return { w: imageDims.w * scaleRatio, h: imageDims.h * scaleRatio };
  }

  const realWidthM = resolveRealWidth(src);
  if (realWidthM != null) {
    return {
      w: realWidthM,
      h: realWidthM * (imageDims.h / imageDims.w),
    };
  }
  return null;
}

function resolveScaleRatio(src: ImageExtentSource): number | null {
  const fromSummary = src.scaleRatioMPerPx;
  if (typeof fromSummary === 'number' && fromSummary > 0) return fromSummary;
  if (src.sourceAssetId) {
    const v = loadCachedScaleRatio(src.sourceAssetId);
    if (v != null) return v;
  }
  if (src.floorId) {
    const v = loadCachedScaleRatio(src.floorId);
    if (v != null) return v;
  }
  return null;
}

function resolveRealWidth(src: ImageExtentSource): number | null {
  const fromSummary = src.realWidthM;
  if (typeof fromSummary === 'number' && fromSummary > 0) return fromSummary;
  if (src.sourceAssetId) {
    const v = loadCachedRealWidth(src.sourceAssetId);
    if (v != null) return v;
  }
  if (src.floorId) {
    const v = loadCachedRealWidth(src.floorId);
    if (v != null) return v;
  }
  return null;
}

/** 벽 bounds + 이미지 픽셀 크기로 scale_ratio 를 역추정 (캐시 miss 시 fallback). */
export function inferImageExtentFromWallBounds(
  imageDims: { w: number; h: number } | null,
  bounds: { minX: number; maxX: number; minY: number; maxY: number } | null,
): { w: number; h: number } | null {
  if (!imageDims || imageDims.w <= 0 || imageDims.h <= 0 || !bounds) return null;
  const { minX, minY, maxX, maxY } = bounds;
  if (!Number.isFinite(maxX) || !Number.isFinite(maxY) || maxX <= 0 || maxY <= 0) {
    return null;
  }
  // 도면 분석 결과는 보통 (0,0) 근처에서 시작. 여백이 크면 추정 불가.
  if (minX > 2 || minY > 2) return null;
  const scaleX = maxX / imageDims.w;
  const scaleY = maxY / imageDims.h;
  const scale = Math.max(scaleX, scaleY);
  if (!Number.isFinite(scale) || scale <= 0) return null;
  return { w: imageDims.w * scale, h: imageDims.h * scale };
}
