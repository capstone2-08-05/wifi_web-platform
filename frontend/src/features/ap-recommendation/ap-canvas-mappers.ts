import { parseGeometry } from '@/features/editor/geometry-utils';
import { nextApSequentialName } from '@/lib/ap-layout-naming';
import type { ApLayout } from '@/types/ap-layout';
import type { CanvasExistingAp } from './ApRecommendationCanvas';

/** ApLayout.point_geom → 캔버스 AP 마커. */
export function apLayoutsToCanvas(layouts: ApLayout[]): CanvasExistingAp[] {
  const result: CanvasExistingAp[] = [];
  for (const l of layouts) {
    const g = parseGeometry(l.point_geom);
    if (g?.type !== 'Point') continue;
    const [x, y] = g.coordinates;
    result.push({ id: l.id, x_m: x, y_m: y, label: l.ap_name });
  }
  return result;
}

/** rf_run.request_json.access_points → 캔버스 AP 마커. */
export function apsFromRfRunRequest(
  requestJson: Record<string, unknown> | undefined,
): CanvasExistingAp[] {
  if (!requestJson) return [];
  const raw = (requestJson as { access_points?: unknown }).access_points;
  if (!Array.isArray(raw)) return [];
  const out: CanvasExistingAp[] = [];
  raw.forEach((entry, i) => {
    if (!entry || typeof entry !== 'object') return;
    const r = entry as Record<string, unknown>;
    const x = Number(r['x_m'] ?? r['x']);
    const y = Number(r['y_m'] ?? r['y']);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const id = typeof r['id'] === 'string' ? r['id'] : `ap${i + 1}`;
    out.push({ id, x_m: x, y_m: y, label: id.toUpperCase() });
  });
  return out;
}

/** POST /ap-layouts — 새 AP 이름 (기존 이름 접미사 최댓값 + 1). */
export function nextApLayoutName(
  layouts: { ap_name: string }[],
  canvasAps: { id: string; label?: string }[],
): string {
  const names = [
    ...layouts.map((l) => l.ap_name),
    ...canvasAps.flatMap((a) => [a.label, a.id].filter((v): v is string => !!v)),
  ];
  return nextApSequentialName(names);
}
