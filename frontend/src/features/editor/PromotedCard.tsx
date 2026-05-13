import { Link } from 'react-router-dom';
import { CheckCircle2, History } from 'lucide-react';
import type { SceneVersion } from '@/types/scene';
import { useVersionPatchLogs } from '@/hooks/use-patch-logs';

interface PromotedCardProps {
  version: SceneVersion;
  onReupload: () => void;
}

export function PromotedCard({ version, onReupload }: PromotedCardProps) {
  // 확정본 변경 이력 (§9.1) — Draft 단계 변경은 안 쌓이고, 확정 후 PATCH 시 기록됨.
  const patchLogsQuery = useVersionPatchLogs(version.id, { page: 1, page_size: 1 });
  const totalPatchLogs = patchLogsQuery.data?.total ?? 0;

  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="mt-0.5 h-6 w-6 text-primary" />
        <div className="flex-1">
          <h3 className="text-lg font-semibold">버전 #{version.version_no} 확정 완료</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {version.is_current
              ? '현재 버전으로 설정되었습니다. 이 버전 위에서 이어서 작업할 수 있습니다.'
              : '새 버전이 저장되었습니다.'}
          </p>
        </div>
      </div>

      <dl className="mt-5 space-y-2 rounded-md bg-muted/40 p-4 text-sm">
        <Row label="버전 번호" value={`#${version.version_no}`} />
        <Row label="현재 버전" value={version.is_current ? 'true' : 'false'} />
        <Row label="version_id" value={version.id} mono />
        <Row label="floor_id" value={version.floor_id} mono />
        <Row label="source_draft_id" value={version.source_draft_id} mono />
      </dl>

      <div className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
        <History className="h-3.5 w-3.5" />
        변경 이력 {totalPatchLogs} 건 (확정 후 수정 시 기록됩니다)
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onReupload}
          className="rounded-md border px-3 py-2 text-sm hover:bg-accent"
        >
          새 도면 업로드
        </button>
        <Link
          to="/dashboard"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          대시보드로
        </Link>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className={mono ? 'break-all text-right font-mono text-xs' : 'text-right'}>{value}</dd>
    </div>
  );
}
