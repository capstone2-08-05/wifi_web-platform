import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, ChevronUp, Minimize2, Radio } from 'lucide-react';
import type { SceneVersion } from '@/types/scene';
import { VersionHistoryPanel } from './VersionHistoryPanel';

interface PromotedCardProps {
  version: SceneVersion;
  versions?: SceneVersion[];
  onReupload: () => void;
  /** "빈 도면으로 시작" — 새 SceneDraft 를 빈 상태로 생성. 미제공 시 버튼 숨김. */
  onStartBlank?: () => void;
  isStartingBlank?: boolean;
}

export function PromotedCard({
  version,
  versions,
  onReupload,
  onStartBlank,
  isStartingBlank,
}: PromotedCardProps) {
  const [minimized, setMinimized] = useState(false);

  // versions 리스트에 is_current 가 잡혀있으면 그쪽을 진실의 원천으로 사용.
  // (justPromoted 로 캡처된 stale version prop 이 전환 후에도 따라오지 않는 문제 해결.)
  const displayVersion = versions?.find((v) => v.is_current) ?? version;

  if (minimized) {
    return (
      <div
        key="promoted-min"
        className="pointer-events-auto absolute right-6 top-6 flex items-center gap-2 rounded-full border bg-card px-3 py-2 text-xs shadow-md motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300 motion-safe:ease-out"
      >
        <CheckCircle2 className="h-4 w-4 text-primary" />
        <span className="font-medium">버전 #{displayVersion.version_no} 활성</span>
        <button
          type="button"
          onClick={() => setMinimized(false)}
          className="ml-1 inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary/90"
        >
          <ChevronUp className="h-3 w-3" />
          버전 정보 열기
        </button>
      </div>
    );
  }

  return (
    <div
      key="promoted-full"
      className="flex flex-col overflow-hidden rounded-xl border bg-card shadow-sm motion-safe:animate-in motion-safe:fade-in motion-safe:duration-500 motion-safe:ease-out"
    >
      <div className="p-6 pb-4">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-6 w-6 text-primary" />
          <div className="flex-1">
            <h3 className="text-lg font-semibold">버전 #{displayVersion.version_no} 확정 완료</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {displayVersion.is_current
                ? '이어서 편집하시려면 오른쪽 위 최소화 버튼을 눌러 캔버스로 돌아가세요.'
                : '새 버전이 저장되었습니다.'}
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

        {versions && versions.length > 1 && (
          <VersionHistoryPanel
            versions={versions}
            onSwitched={() => setMinimized(true)}
          />
        )}

        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onReupload}
            className="rounded-md border px-3 py-2 text-sm hover:bg-accent"
          >
            새 버전 업로드
          </button>
          {onStartBlank && (
            <button
              type="button"
              onClick={onStartBlank}
              disabled={isStartingBlank}
              className="rounded-md border px-3 py-2 text-sm hover:bg-accent disabled:opacity-50"
            >
              {isStartingBlank ? '생성 중…' : '빈 도면으로 시작'}
            </button>
          )}
          <Link
            to="/simulation"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Radio className="h-4 w-4" />
            시뮬레이션 실행
          </Link>
        </div>
      </div>
      <p className="border-t border-slate-100 px-6 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
        ※ 우측 상단 아이콘으로 패널을 최소화하면 캔버스에서 도면을 확인할 수 있어요.
      </p>
    </div>
  );
}

