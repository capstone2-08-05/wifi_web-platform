import { useMemo, useState } from 'react';
import { Check, ChevronDown, ChevronUp, History, Loader2, Trash2 } from 'lucide-react';
import { useSetCurrentVersion } from '@/hooks/use-scene-version';
import { useHiddenVersions } from '@/hooks/use-hidden-versions';
import { cn } from '@/lib/utils';
import type { SceneVersion } from '@/types/scene';

interface Props {
  versions: SceneVersion[];
}

/**
 * §7.3 버전 히스토리 패널. PromotedCard 하단에 토글로 노출.
 * 옛 버전 클릭 → PATCH /scene-versions/{id}/set-current 호출.
 */
export function VersionHistoryPanel({ versions }: Props) {
  const [open, setOpen] = useState(false);
  const setCurrent = useSetCurrentVersion();
  const { isHidden, hide } = useHiddenVersions();

  // 숨겨진 버전은 목록에서 제외 (현재 버전은 절대 숨기지 않음).
  const visible = useMemo(
    () => versions.filter((v) => v.is_current || !isHidden(v.id)),
    [versions, isHidden],
  );

  if (visible.length === 0) return null;

  // 최신순 정렬 (version_no DESC)
  const sorted = [...visible].sort((a, b) => b.version_no - a.version_no);

  const handleHide = (id: string, versionNo: number) => {
    if (window.confirm(`버전 #${versionNo} 을(를) 정말 삭제하시겠습니까?`)) {
      hide(id);
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
          버전 히스토리 ({visible.length}개)
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
            return (
              <li key={v.id} className={cn('flex items-center', v.is_current && 'bg-primary/5')}>
                <button
                  type="button"
                  disabled={v.is_current || isSwitching}
                  onClick={() => setCurrent.mutate(v.id)}
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
                  onClick={() => handleHide(v.id, v.version_no)}
                  disabled={v.is_current || isSwitching}
                  title={v.is_current ? '현재 버전은 삭제할 수 없습니다' : '버전 삭제'}
                  aria-label={`버전 #${v.version_no} 삭제`}
                  className="mr-2 rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
                >
                  <Trash2 className="h-3 w-3" />
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
