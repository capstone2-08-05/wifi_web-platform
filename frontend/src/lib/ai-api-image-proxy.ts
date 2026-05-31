/** Vite dev server 가 `/__ai_api__` → ai_api 로 프록시할 때 쓰는 prefix. */
export const AI_API_DEV_PROXY_PREFIX = '/__ai_api__';

/** local ai_api heatmap URL — 브라우저가 직접 localhost:9000 에 접속하면 실패. */
export function isAiApiHeatmapUrl(url: string): boolean {
  if (!/^https?:\/\//i.test(url)) return false;
  if (url.includes('/internal/sionna/images/')) return true;
  return /localhost:9000|127\.0\.0\.1:9000/i.test(url);
}

/** `http://localhost:9000/internal/...` → `/__ai_api__/internal/...` (dev 전용). */
export function toAiApiDevProxyUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return `${AI_API_DEV_PROXY_PREFIX}${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}

/**
 * RF heatmap `<image href>` 용 URL.
 * - S3 presigned 등: 그대로
 * - dev + ai_api localhost: Vite 프록시 경로로 변환
 */
export function resolveHeatmapImageUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (import.meta.env.DEV && isAiApiHeatmapUrl(url)) {
    return toAiApiDevProxyUrl(url);
  }
  return url;
}
