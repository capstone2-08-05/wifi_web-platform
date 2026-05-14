import { useState } from 'react';
import { CheckCircle2, ChevronUp, Minimize2, RotateCcw, Save } from 'lucide-react';
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

export function ReviewCard({
  draft,
  nextVersionNo,
  isPromoting,
  isResetting,
  onPromote,
  onReset,
  errorMessage,
}: ReviewCardProps) {
  const [minimized, setMinimized] = useState(false);

  const counts = {
    rooms: draft.rooms?.length ?? 0,
    walls: draft.walls?.length ?? 0,
    openings: draft.openings?.length ?? 0,
    objects: draft.objects?.length ?? 0,
  };

  if (minimized) {
    return (
      <div className="pointer-events-auto absolute right-6 top-6 flex items-center gap-2 rounded-full border bg-card px-3 py-2 text-xs shadow-md">
        <CheckCircle2 className="h-4 w-4 text-primary" />
        <span className="font-medium">분석 완료</span>
        <span className="text-muted-foreground">
          방 {counts.rooms} · 벽 {counts.walls} · 객체 {counts.objects}
        </span>
        <button
          type="button"
          onClick={() => setMinimized(false)}
          className="ml-1 inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary/90"
        >
          <ChevronUp className="h-3 w-3" />
          확정 패널 열기
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="mb-4 flex items-start gap-3">
        <CheckCircle2 className="mt-0.5 h-5 w-5 text-primary" />
        <div className="flex-1">
          <h3 className="text-base font-semibold">도면 분석 완료</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">
            확정하면 새 버전 #{nextVersionNo} 으로 저장되고, 그 위에서 이어서 작업할 수 있습니다.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setMinimized(true)}
          aria-label="패널 최소화"
          className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <Minimize2 className="h-4 w-4" />
        </button>
      </div>

      <dl className="grid grid-cols-4 gap-3">
        <Stat label="방" value={counts.rooms} />
        <Stat label="벽" value={counts.walls} />
        <Stat label="개구부" value={counts.openings} />
        <Stat label="객체" value={counts.objects} />
      </dl>

      <div className="mt-4 rounded-md bg-muted/40 p-3">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Draft ID</p>
        <p className="mt-0.5 break-all font-mono text-xs">{draft.id}</p>
      </div>

      {errorMessage && (
        <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {errorMessage}
        </p>
      )}

      <div className="mt-5 flex items-center justify-between">
        <button
          type="button"
          onClick={onReset}
          disabled={isResetting || isPromoting}
          className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-accent disabled:opacity-50"
        >
          <RotateCcw className="h-4 w-4" />
          {isResetting ? '삭제 중…' : '다시 업로드'}
        </button>
        <button
          type="button"
          onClick={onPromote}
          disabled={isPromoting || isResetting}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {isPromoting ? '확정 중…' : '확정하기'}
        </button>
      </div>

      <p className="mt-3 text-[11px] text-muted-foreground">
        ※ 우측 상단 아이콘으로 패널을 최소화하면 캔버스에서 도형을 자유롭게 편집할 수 있어요.
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border bg-background px-3 py-2.5">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold">{value}</dd>
    </div>
  );
}
