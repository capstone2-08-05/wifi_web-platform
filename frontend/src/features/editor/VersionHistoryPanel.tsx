import { useState } from 'react';
import { Check, ChevronDown, ChevronUp, History, Loader2, Trash2 } from 'lucide-react';
import {
  useDeleteSceneVersion,
  useSetCurrentVersion,
} from '@/hooks/use-scene-version';
import { cn } from '@/lib/utils';
import type { SceneVersion } from '@/types/scene';

interface Props {
  versions: SceneVersion[];
  /** 버전 전환 성공 후 호출 — 상위에서 PromotedCard 를 최소화시키는 데 사용. */
  onSwitched?: () => void;
}

/**
 * §7.3 도면 버전 패널. PromotedCard 하단에 토글로 노출.
 * - 클릭 → PATCH /scene-versions/{id}/set-current
 * - 휴지통 → DELETE /scene-versions/{id} (children · rf_runs · patch_logs cascade)
 */
export function VersionHistoryPanel({ versions, onSwitched }: Props) {
  const [open, setOpen] = useState(false);
  const setCurrent = useSetCurrentVersion();
  const remove = useDeleteSceneVersion();

  if (versions.length === 0) return null;

  // 최신순 정렬 (version_no DESC)
  const sorted = [...versions].sort((a, b) => b.version_no - a.version_no);

  const handleDelete = (v: SceneVersion) => {
    if (
      window.confirm(
        `버전 #${v.version_no} 을(를) 정말 삭제하시겠습니까?\n관련된 시뮬레이션 결과와 변경 이력도 함께 삭제됩니다.`,
      )
    ) {
      remove.mutate({ versionId: v.id, sourceDraftId: v.source_draft_id });
    }
  };

  return (
    <div className="mt-4 rounded-md border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs font-medium hover:bg-muted/50"
      >
        <span className="inline-flex items-center gap-1.5">
          <History className="h-3.5 w-3.5 text-muted-foreground" />
          도면 버전 ({versions.length}개)
        </span>
        {open ? (
          <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        )}
      </button>

      {open && (
        <ul className="border-t">
          {sorted.map((v) => {
            const isSwitching = setCurrent.isPending && setCurrent.variables === v.id;
            const isDeleting = remove.isPending && remove.variables?.versionId === v.id;
            return (
              <li key={v.id} className={cn('flex items-center', v.is_current && 'bg-primary/5')}>
                <button
                  type="button"
                  disabled={v.is_current || isSwitching || isDeleting}
                  onClick={() =>
                    setCurrent.mutate(v.id, {
                      onSuccess: () => onSwitched?.(),
                    })
                  }
                  className={cn(
                    'flex flex-1 items-center justify-between gap-3 px-3 py-2 text-left text-xs transition-colors',
                    !v.is_current && 'hover:bg-muted/60 disabled:opacity-50',
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold">버전 #{v.version_no}</span>
                      {v.is_current && (
                        <span className="inline-flex items-center gap-0.5 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                          <Check className="h-2.5 w-2.5" />
                          현재
                        </span>
                      )}
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      {formatDate(v.created_at)}
                    </p>
                  </div>
                  {isSwitching ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                  ) : !v.is_current ? (
                    <span className="text-[10px] text-primary">전환하기</span>
                  ) : null}
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(v)}
                  disabled={isSwitching || isDeleting}
                  title="버전 삭제 (시뮬레이션·변경 이력 함께 삭제됨)"
                  aria-label={`버전 #${v.version_no} 삭제`}
                  className="mr-2 rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-30"
                >
                  {isDeleting ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Trash2 className="h-3 w-3" />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}
