import { parseGeometry } from '@/features/editor/geometry-utils';
import { nextApSequentialName } from '@/lib/ap-layout-naming';
import type { ApLayout } from '@/types/ap-layout';
import type { RadioInterface } from '@/types/rf';
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
  const physicalRaw =
    (requestJson as { physical_aps_snapshot?: unknown }).physical_aps_snapshot ??
    (requestJson as { physical_aps?: unknown }).physical_aps;
  if (Array.isArray(physicalRaw) && physicalRaw.length > 0) {
    const out: CanvasExistingAp[] = [];
    physicalRaw.forEach((entry, i) => {
      if (!entry || typeof entry !== 'object') return;
      const r = entry as Record<string, unknown>;
      const x = Number(r['x'] ?? r['x_m']);
      const y = Number(r['y'] ?? r['y_m']);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      const id = typeof r['id'] === 'string' ? r['id'] : `ap${i + 1}`;
      const radios = Array.isArray(r['radios']) ? (r['radios'] as RadioInterface[]) : undefined;
      out.push({
        id,
        x_m: x,
        y_m: y,
        z_m: Number(r['z'] ?? r['z_m'] ?? 2.5),
        label: typeof r['name'] === 'string' ? r['name'] : id.toUpperCase(),
        radios,
        movable: typeof r['movable'] === 'boolean' ? r['movable'] : true,
      });
    });
    return out;
  }

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
    out.push({
      id,
      x_m: x,
      y_m: y,
      z_m: Number(r['z_m'] ?? r['z'] ?? 2.5),
      label: id.toUpperCase(),
    });
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
