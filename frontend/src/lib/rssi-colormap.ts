/**
 * RSSI heatmap colormap — warm thermal (Wikipedia-style).
 * Weak → deep navy → blue → teal → green → yellow (peak warmth) → orange → red.
 * Strong signal appears as bright yellow/amber rather than dark red.
 */

/** RGB tuples at t = 0 (weakest) … 1 (strongest) */
export const RSSI_HEATMAP_STOPS_RGB: ReadonlyArray<readonly [number, number, number]> = [
  [30,  80, 235],  // bright blue       (very weak)
  [0,  140, 255],  // royal blue
  [0,  210, 255],  // sky blue / cyan
  [0,  240, 190],  // teal
  [30, 240,  70],  // green
  [160, 240,   0], // yellow-green
  [255, 235,   0], // bright yellow
  [255, 160,   0], // amber
  [255,  55,   0], // orange-red
  [235,   0,   0], // bright red
  [195,   0,   0], // medium red        (very strong)
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
