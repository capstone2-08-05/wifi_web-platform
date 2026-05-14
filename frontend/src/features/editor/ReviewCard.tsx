import { CheckCircle2, RotateCcw, Save } from 'lucide-react';
import type { SceneDraft } from '@/types/scene';

interface ReviewCardProps {
  draft: SceneDraft;
  nextVersionNo: number;
  isPromoting: boolean;
  isResetting: boolean;
  onPromote: () => void;
  onReset: () => void;
  errorMessage?: string;
}

/**
 * 분석 완료 후 우측 상단에 떠 있는 슬림 패널.
 * 캔버스를 가리지 않도록 카드 chrome 을 최소화 — 카운트는 inline, 버튼만 노출.
 */
export function ReviewCard({
  draft,
  nextVersionNo,
  isPromoting,
  isResetting,
  onPromote,
  onReset,
  errorMessage,
}: ReviewCardProps) {
  const counts = {
    rooms: draft.rooms?.length ?? 0,
    walls: draft.walls?.length ?? 0,
    openings: draft.openings?.length ?? 0,
    objects: draft.objects?.length ?? 0,
  };

  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-background/95 px-3 py-2.5 shadow-md backdrop-blur">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
        <span className="text-sm font-semibold">분석 완료</span>
        <span className="ml-auto flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Stat label="방" value={counts.rooms} />
          <Stat label="벽" value={counts.walls} />
          <Stat label="개구부" value={counts.openings} />
          <Stat label="객체" value={counts.objects} />
        </span>
      </div>

      {errorMessage && (
        <p className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-[11px] text-destructive">
          {errorMessage}
        </p>
      )}

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={onReset}
          disabled={isResetting || isPromoting}
          className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          {isResetting ? '삭제 중…' : '다시 업로드'}
        </button>
        <button
          type="button"
          onClick={onPromote}
          disabled={isPromoting || isResetting}
          className="ml-auto inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Save className="h-3.5 w-3.5" />
          {isPromoting ? '확정 중…' : `확정 #${nextVersionNo}`}
        </button>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className="tabular-nums">
      {label}
      <span className="ml-0.5 font-semibold text-foreground">{value}</span>
    </span>
  );
}
