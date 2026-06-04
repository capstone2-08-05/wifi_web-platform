import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { RSSI_HEATMAP_GRADIENT_CSS } from '@/lib/rssi-colormap';
import { cn } from '@/lib/utils';

/**
 * RSSI dBm → 색 그라데이션 + tick 라벨 colorbar.
 *
 * matplotlib `jet` cmap — Sionna/GP heatmap PNG, MeasurementCanvas, 본 컴포넌트 동기화.
 */

const DBM_QUALITY_LABELS = [
  { dbm: -30, label: '매우 강함' },
  { dbm: -50, label: '강함' },
  { dbm: -60, label: '좋음' },
  { dbm: -70, label: '보통' },
  { dbm: -80, label: '약함' },
  { dbm: -90, label: '매우 약함' },
];

interface Props {
  vmin: number;
  vmax: number;
  /** 표시할 tick 개수 (기본 5). 양 끝 포함. */
  tickCount?: number;
  /** 라벨 — 컬러바 위쪽에 작게 표시 (예: "실측 RSSI", "예측 RSSI"). 미지정시 없음. */
  label?: string;
  className?: string;
}

export function DbmColorBar({
  vmin,
  vmax,
  tickCount = 5,
  label,
  className,
}: Props) {
  const [expanded, setExpanded] = useState(true);
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
      className={cn(
        'pointer-events-auto flex flex-col gap-1 rounded-md border bg-card/95 px-3 py-2 shadow-sm backdrop-blur',
        className,
      )}
      role="img"
      aria-label={`RSSI 색 범례: ${vmin.toFixed(0)} ~ ${vmax.toFixed(0)} dBm`}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center justify-between gap-2 text-left text-[10px] font-medium text-muted-foreground"
        aria-expanded={expanded}
      >
        <span>{label ?? 'RSSI 범례'}</span>
        <span className="inline-flex items-center gap-1">
          <ChevronDown
            className={cn('h-3 w-3 transition-transform', expanded && 'rotate-180')}
            aria-hidden="true"
          />
        </span>
      </button>
      {expanded && (
        <>
          {/* gradient bar */}
          <div
            className="h-3 w-full rounded-sm border border-border/60"
            style={{ backgroundImage: RSSI_HEATMAP_GRADIENT_CSS }}
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
          <div className="mt-1 border-t pt-1.5">
            <p className="mb-1 text-[9px] font-medium text-muted-foreground">
              숫자가 0에 가까울수록 신호가 강합니다.
            </p>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[9px] leading-tight text-muted-foreground">
              {DBM_QUALITY_LABELS.map((item) => (
                <div key={item.dbm} className="flex items-center justify-between gap-2">
                  <span className="font-mono tabular-nums text-foreground/75">
                    {item.dbm} dBm
                  </span>
                  <span>{item.label}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
