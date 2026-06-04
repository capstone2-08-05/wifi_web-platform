/**
 * RSSI heatmap colormap — matplotlib/OpenCV jet style.
 * Weak → blue, medium → cyan/green/yellow, strong → red.
 */

/** RGB tuples at t = 0 (weakest) … 1 (strongest) */
export const RSSI_HEATMAP_STOPS_RGB: ReadonlyArray<readonly [number, number, number]> = [
  [0, 0, 128],
  [0, 0, 255],
  [0, 128, 255],
  [0, 255, 255],
  [128, 255, 128],
  [255, 255, 0],
  [255, 128, 0],
  [255, 0, 0],
  [128, 0, 0],
];

export const RSSI_HEATMAP_GRADIENT_CSS = buildHeatmapGradientCss();

export function buildHeatmapGradientCss(): string {
  const stops = RSSI_HEATMAP_STOPS_RGB.map((rgb, i) => {
    const pct = ((i / (RSSI_HEATMAP_STOPS_RGB.length - 1)) * 100).toFixed(1);
    const [r, g, b] = rgb;
    return `rgb(${r}, ${g}, ${b}) ${pct}%`;
  }).join(', ');
  return `linear-gradient(to right, ${stops})`;
}

/** dBm → jet RGB string. Weak signal = blue, strong = red. */
export function dbmToHeatmapColor(dbm: number, min: number, max: number): string {
  if (!Number.isFinite(dbm) || max <= min) return 'rgb(255, 255, 255)';
  const t = Math.max(0, Math.min(1, (dbm - min) / (max - min)));
  const scaled = t * (RSSI_HEATMAP_STOPS_RGB.length - 1);
  const lo = Math.floor(scaled);
  const hi = Math.min(RSSI_HEATMAP_STOPS_RGB.length - 1, lo + 1);
  const frac = scaled - lo;
  const c0 = RSSI_HEATMAP_STOPS_RGB[lo];
  const c1 = RSSI_HEATMAP_STOPS_RGB[hi];
  const r = Math.round(c0[0] + frac * (c1[0] - c0[0]));
  const g = Math.round(c0[1] + frac * (c1[1] - c0[1]));
  const b = Math.round(c0[2] + frac * (c1[2] - c0[2]));
  return `rgb(${r}, ${g}, ${b})`;
}
