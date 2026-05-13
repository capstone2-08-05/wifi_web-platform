import { useEffect, useState } from 'react';
import { Copy, Loader2, RefreshCw, Smartphone, X } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { useAppStore } from '@/stores/app-store';
import { useCreateMeasurementLink } from '@/hooks/use-measurement-link';
import { toast } from '@/stores/toast-store';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function MobileConnectModal({ open, onClose }: Props) {
  const floorId = useAppStore((s) => s.selectedFloorId);
  const projectId = useAppStore((s) => s.selectedProjectId);
  const createLink = useCreateMeasurementLink();
  const link = createLink.data;

  // 모달 열릴 때 floorId 가 있으면 자동 트리거
  useEffect(() => {
    if (!open) return;
    if (!floorId) return;
    if (createLink.isPending || link) return;
    createLink.mutate(floorId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, floorId]);

  // 닫힐 때 상태 초기화 (다음 열릴 때 새 QR 발급)
  useEffect(() => {
    if (!open) createLink.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // ESC 키로 닫기
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border bg-background p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <Smartphone className="h-5 w-5 text-primary" />
            <h2 className="text-base font-bold">모바일 앱 연결</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {!projectId || !floorId ? (
          <EmptyState />
        ) : createLink.isPending ? (
          <PendingState />
        ) : link ? (
          <ReadyState
            qrPayload={link.qr_payload}
            token={link.token}
            expiresAt={link.expires_at}
            deepLink={link.deep_link}
            onRefresh={() => createLink.mutate(floorId)}
          />
        ) : createLink.isError ? (
          <ErrorState onRetry={() => createLink.mutate(floorId)} />
        ) : null}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mt-5 rounded-lg border border-dashed bg-muted/30 p-6 text-center">
      <p className="text-sm font-medium">프로젝트와 층을 먼저 선택해주세요</p>
      <p className="mt-1 text-xs text-muted-foreground">
        대시보드 헤더의 셀렉터로 작업할 도면을 선택한 후 다시 시도하세요.
      </p>
    </div>
  );
}

function PendingState() {
  return (
    <div className="mt-5 flex flex-col items-center gap-3 p-6 text-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="text-sm font-medium">QR 코드 발급 중…</p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mt-5 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-center">
      <p className="text-sm font-medium text-destructive">QR 코드를 받지 못했어요</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
      >
        <RefreshCw className="h-3.5 w-3.5" />
        다시 시도
      </button>
    </div>
  );
}

function ReadyState({
  qrPayload,
  token,
  expiresAt,
  deepLink,
  onRefresh,
}: {
  qrPayload: string;
  token: string;
  expiresAt: string;
  deepLink: string;
  onRefresh: () => void;
}) {
  const remaining = useCountdown(expiresAt);

  const copyDeepLink = async () => {
    try {
      await navigator.clipboard.writeText(deepLink);
      toast.info('딥링크가 복사되었습니다');
    } catch {
      toast.error('복사에 실패했습니다', deepLink);
    }
  };

  return (
    <div className="mt-5 space-y-4">
      <p className="text-center text-xs text-muted-foreground">
        모바일 앱으로 아래 QR 코드를 스캔하면 측정이 시작됩니다.
      </p>

      <div className="flex justify-center rounded-xl border bg-white p-4">
        <QRCodeSVG value={qrPayload} size={200} level="M" includeMargin />
      </div>

      <div className="space-y-2 rounded-lg border bg-muted/20 p-3 text-xs">
        <Row label="토큰" value={token} mono />
        <Row label="만료까지" value={remaining ?? '만료됨'} />
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={copyDeepLink}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border bg-background px-3 py-2 text-xs font-medium hover:bg-accent"
        >
          <Copy className="h-3.5 w-3.5" />
          딥링크 복사
        </button>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border bg-background px-3 py-2 text-xs font-medium hover:bg-accent"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          새로 발급
        </button>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span
        className={mono ? 'max-w-[60%] truncate text-right font-mono' : 'text-right'}
        title={mono ? value : undefined}
      >
        {value}
      </span>
    </div>
  );
}

/** 만료까지 남은 시간 카운트다운. 만료되면 null. */
function useCountdown(expiresAtIso: string): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const target = new Date(expiresAtIso).getTime();
  const diffMs = target - now;
  if (!Number.isFinite(diffMs) || diffMs <= 0) return null;
  const totalSec = Math.floor(diffMs / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}분 ${String(s).padStart(2, '0')}초`;
}
