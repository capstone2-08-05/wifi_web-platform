import { useMemo } from 'react';
import { resolveHeatmapImageUrl } from '@/lib/ai-api-image-proxy';

/** RF heatmap 표시 URL — dev 에서 ai_api localhost 는 Vite 프록시 경로로 변환. */
export function useRfMapImageUrl(sourceUrl: string | null | undefined): string | null {
  return useMemo(() => resolveHeatmapImageUrl(sourceUrl ?? null), [sourceUrl]);
}
