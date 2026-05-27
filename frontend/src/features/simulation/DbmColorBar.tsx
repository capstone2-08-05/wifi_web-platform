/**
 * RSSI dBm → 색 그라데이션 + tick 라벨 colorbar.
 *
 * matplotlib horizontal colorbar 스타일 — gradient 아래에 tick 들이 정렬돼서
 * "이 색 = 이 dBm" 한눈에 매핑. 시뮬/측정 페이지 모두에서 같은 visual language.
 *
 * inferno cmap 11 stops — Sionna heatmap PNG, MeasurementCanvas 측정점 색, 본 컴포넌트
 * 모두 동일 stop 사용 (HeatmapColorLegend, MeasurementCanvas 와 동기화).
 */

const INFERNO_GRADIENT =
  'linear-gradient(to right, ' +
  '#000004 0%, #160b39 10%, #420a68 20%, #6a176e 30%, ' +
  '#932667 40%, #bc3754 50%, #dd513a 60%, #f37819 70%, ' +
  '#fca50a 80%, #f6d746 90%, #fcffa4 100%)';

interface Props {
  vmin: number;
  vmax: number;
  /** 표시할 tick 개수 (기본 5). 양 끝 포함. */
  tickCount?: number;
  /** 라벨 — 컬러바 위쪽에 작게 표시 (예: "실측 RSSI", "예측 RSSI"). 미지정시 없음. */
  label?: string;
  /** 데이터가 sim 기반 정확 스케일이 아닌 경우 (예: API 응답 없을때 fallback). 표시되면 "approx." 뱃지. */
  approximate?: boolean;
  className?: string;
}

export function DbmColorBar({
  vmin,
  vmax,
  tickCount = 5,
  label,
  approximate = false,
  className,
}: Props) {
  // tick 위치 0~100% 균등 분포 + 값 보간.
  const ticks = Array.from({ length: tickCount }, (_, i) => {
    const t = tickCount === 1 ? 0 : i / (tickCount - 1);
    return {
      pct: t * 100,
      value: vmin + t * (vmax - vmin),
    };
  });

  return (
    <div
      className={
        'pointer-events-none flex flex-col gap-1 rounded-md border bg-card/95 px-3 py-2 shadow-sm backdrop-blur ' +
        (className ?? '')
      }
      role="img"
      aria-label={`RSSI 색 범례: ${vmin.toFixed(0)} ~ ${vmax.toFixed(0)} dBm`}
    >
      {(label || approximate) && (
        <div className="flex items-center justify-between text-[10px] font-medium text-muted-foreground">
          <span>{label ?? ''}</span>
          {approximate && (
            <span className="text-[9px] text-muted-foreground/70">approx.</span>
          )}
        </div>
      )}
      {/* gradient bar */}
      <div
        className="h-3 w-full rounded-sm border border-border/60"
        style={{ backgroundImage: INFERNO_GRADIENT }}
      />
      {/* tick marks — gradient 바로 아래 short vertical line + 값 */}
      <div className="relative h-4 w-full">
        {ticks.map((t, i) => (
          <div
            key={i}
            className="absolute top-0 -translate-x-1/2 text-center"
            style={{ left: `${t.pct}%` }}
          >
            <div className="mx-auto h-1 w-px bg-border" />
            <div className="mt-0.5 font-mono text-[10px] tabular-nums text-foreground/70">
              {t.value.toFixed(0)}
            </div>
          </div>
        ))}
      </div>
      <div className="text-right text-[9px] text-muted-foreground">dBm</div>
    </div>
  );
}
