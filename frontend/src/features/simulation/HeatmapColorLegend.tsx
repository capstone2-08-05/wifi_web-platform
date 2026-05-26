/**
 * RF 시뮬레이션 히트맵 색 → dBm 범례.
 *
 * 각 run 의 실제 사용된 색 스케일 (vmin/vmax, auto-scale p5-p95) 을 ai_api 가
 * `artifacts.radiomap.color_scale` 로 노출 → backend 가 RfMap.metrics_json.color_scale
 * 에 보관 → 이 컴포넌트가 그대로 사용. matplotlib inferno cmap 의 stops 을 CSS gradient
 * 로 재현해서 동일한 시각화 제공.
 *
 * color_scale 이 없는 경우 (옛 run / sagemaker 응답에 미포함) 합리적 기본값 -85~-30 dBm
 * 으로 표시 — 사용자는 대략의 범위라도 파악 가능.
 */

// matplotlib inferno 의 11개 stops (0.0 → 1.0). matplotlib.cm.inferno(t) 와 같은 색.
const INFERNO_STOPS: ReadonlyArray<string> = [
  '#000004',
  '#160b39',
  '#420a68',
  '#6a176e',
  '#932667',
  '#bc3754',
  '#dd513a',
  '#f37819',
  '#fca50a',
  '#f6d746',
  '#fcffa4',
];

function buildGradientCss(): string {
  // 수평 그라데이션 — 왼쪽=낮은 신호(짙은 보라), 오른쪽=높은 신호(밝은 노랑).
  const stops = INFERNO_STOPS.map(
    (color, i) => `${color} ${((i / (INFERNO_STOPS.length - 1)) * 100).toFixed(1)}%`,
  ).join(', ');
  return `linear-gradient(to right, ${stops})`;
}

const GRADIENT_CSS = buildGradientCss();

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
        style={{ backgroundImage: GRADIENT_CSS }}
      />
      <div className="flex justify-between text-[10px] font-mono tabular-nums text-foreground/70">
        <span>{vmin.toFixed(0)}</span>
        <span>{vmid.toFixed(0)}</span>
        <span>{vmax.toFixed(0)}</span>
      </div>
    </div>
  );
}
