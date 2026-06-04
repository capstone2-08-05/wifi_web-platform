/**
 * RF 시뮬레이션 히트맵 색 → dBm 범례.
 *
 * color_scale (vmin/vmax) 은 RfMap.metrics_json 에서 가져옴.
 * matplotlib `jet` cmap 과 동일한 stops 로 CSS gradient 재현.
 */

import { RSSI_HEATMAP_GRADIENT_CSS } from '@/lib/rssi-colormap';

const DEFAULT_VMIN_DBM = -85;
const DEFAULT_VMAX_DBM = -30;

/** RfMap.metrics_json.color_scale 또는 metrics_json.radio_map.color_scale 에서 추출. */
export function extractColorScale(
  raw: unknown,
): { vminDbm: number; vmaxDbm: number } | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  const vmin = Number(obj['vmin_dbm']);
  const vmax = Number(obj['vmax_dbm']);
  if (!Number.isFinite(vmin) || !Number.isFinite(vmax) || vmax <= vmin) return null;
  return { vminDbm: vmin, vmaxDbm: vmax };
}

interface Props {
  /** color_scale 객체 — 미지정 시 기본 dBm 범위로 fallback. */
  scale?: { vminDbm: number; vmaxDbm: number } | null;
  className?: string;
}

/**
 * 가로 그라데이션 + 양 끝/중간 dBm 라벨. 캔버스 모서리에 작게 띄우는 용도.
 */
export function HeatmapColorLegend({ scale, className }: Props) {
  const vmin = scale?.vminDbm ?? DEFAULT_VMIN_DBM;
  const vmax = scale?.vmaxDbm ?? DEFAULT_VMAX_DBM;
  const vmid = (vmin + vmax) / 2;
  const isFallback = !scale;

  return (
    <div
      className={
        'pointer-events-none flex flex-col gap-1 rounded-md border bg-card/90 px-2.5 py-1.5 shadow-sm backdrop-blur' +
        (className ? ` ${className}` : '')
      }
      role="img"
      aria-label={`RSS dBm 색상 범례: ${vmin.toFixed(0)} dBm 에서 ${vmax.toFixed(0)} dBm`}
    >
      <div className="flex items-center justify-between gap-2 text-[10px] font-medium text-muted-foreground">
        <span>RSS (dBm)</span>
        {isFallback && <span className="text-[9px] text-muted-foreground/70">approx.</span>}
      </div>
      <div
        className="h-2.5 w-44 rounded-sm border border-border/60"
        style={{ backgroundImage: RSSI_HEATMAP_GRADIENT_CSS }}
      />
      <div className="flex justify-between text-[10px] font-mono tabular-nums text-foreground/70">
        <span>{vmin.toFixed(0)}</span>
        <span>{vmid.toFixed(0)}</span>
        <span>{vmax.toFixed(0)}</span>
      </div>
    </div>
  );
}
